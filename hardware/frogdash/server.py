"""Local HTTP + WebSocket service, independently paced per browser client."""
import argparse
import asyncio
import codecs
import json
import os
import re
from collections import deque
from contextlib import suppress
from pathlib import Path

from aiohttp import web, WSMsgType, ClientError
from .adapters import read_replay, replay, socketcan
from .state import State
from .gps import GPS, gpsd
from .gpswatch import GpsRecovery
from .gpsaid import GpsAid
from .helpers import Helpers
from .fwupdate import Firmware
from .recorder import Config as LogConfig, Recorder, NAME as LOG_NAME, MIB
from .connectivity import Connectivity, DEFAULT_SOCKET, require_local
from .race import Race
from .driving import Driving, atomic_write
from .eventlog import EventLog, read as read_events, as_text as events_text
from .github_link import GitHubLink
from .summary import DriveSummary
from .health import Health
from .shutdown import ShutdownHistory
from .trip import Trip
from .nav import Navigator
from .operations import Operations
from .backlight import Backlight
from .supervision import supervise, watchdog
from .camera import BOUNDARY as CAMERA_BOUNDARY, Camera
from .paint import Paint, validate as validate_paint
from .imports import Imports
from . import cancheck, methtune, selftest
from .parking import rolling

TERMINAL_SOCKET = Path('/run/frogdash-terminal.sock')

WIFI_PASSWORD = re.compile(r"[\x20-\x7E]{8,63}")


def valid_ssid(name):
    """1 to 32 bytes of printable characters: an iPhone's hotspot has a curly apostrophe."""
    return isinstance(name, str) and 0 < len(name.encode('utf-8')) <= 32 and name.isprintable()
IMAGE_DATA = re.compile(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+")

WEB = Path(__file__).resolve().parents[1] / "ui"


async def preset_pause():
    await asyncio.sleep(.3)  # Controls space commands at least 0.25 s apart.


def create_app(state, adapter=None, connectivity=None):
    @web.middleware
    async def recovery_guard(request, handler):
        if request.method == 'POST' and state.operations.restoring:
            raise web.HTTPServiceUnavailable(text='Restore recovery pending; restart service to finish')
        if request.method == 'POST' and request.path not in {'/operations/settings', '/operations/restore'}:
            async with state.operations.lock:
                if state.operations.restoring:
                    raise web.HTTPServiceUnavailable(text='Restore recovery pending; restart service to finish')
                return await handler(request)
        return await handler(request)
    app = web.Application(client_max_size=7 * 1024 * 1024, middlewares=[recovery_guard])
    clients = set()

    async def lifecycle(app):
        async def step(name, work):
            """One step of starting or stopping. A failure is recorded and the next step still
            runs: at key-off, closing the drive recording must not depend on the steps before."""
            try:
                result = work()
                if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as error:
                state.fault(name, error)

        async def finish(task):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task

        if state.shutdown_history:
            await step('shutdown history', lambda: asyncio.to_thread(state.shutdown_history.start))
        await step('settings restore', state.operations.recover)
        notify_task = asyncio.create_task(watchdog())
        # Every loop below is supervised (supervision.py): if one fails it is recorded and
        # started again, instead of that feature stopping for the rest of the drive.
        tasks = [supervise(state, 'CAN reader', adapter)] if adapter else []
        race_task = supervise(state, 'race timer', state.race.run, state.race)
        drive_task = supervise(state, 'drive alerts', state.driving.run, state.driving)
        trip_task = supervise(state, 'trip', state.trip.run, state.trip)
        nav_task = supervise(state, 'navigation', state.nav.run, state.nav)
        health_task = supervise(state, 'Pi health', state.health.run, state.health) if state.health else None
        await step('controls', state.controls.start)
        if state.gps:
            state.gps.on_report = state.race.feed
            tasks.append(supervise(state, 'GPS reader', lambda: gpsd(state.gps)))
            if state.gps_recovery:
                tasks.append(supervise(state, 'GPS recovery', state.gps_recovery.run, state.gps_recovery))
            if state.gps_aid:
                tasks.append(supervise(state, 'GPS satellite data', state.gps_aid.run, state.gps_aid))
        if state.helpers:
            tasks.append(supervise(state, 'Pi setup check', state.helpers.run))
        if state.dashcam:
            tasks.append(supervise(state, 'dash cam', state.dashcam.run))
        if state.firmware:
            tasks.append(supervise(state, 'module firmware', state.firmware.run))
        eventlog_task = supervise(state, 'event log', state.eventlog.run, state.eventlog) if state.eventlog else None
        summary_task = supervise(state, 'drive summary', state.summary.run, state.summary) if state.summary else None
        if state.recorder:
            await step('recorder', state.recorder.start)
        if connectivity:
            await step('phone page', connectivity.start)
        yield
        if state.camera:
            await step('rear camera', state.camera.close)
        if state.dashcam:
            await step('dash cam', state.dashcam.close)
        await finish(notify_task)
        await step('controls', state.controls.close)
        if connectivity:
            await step('phone page', connectivity.close)
        if state.health:
            state.health.stopping = True
        for task in tasks:
            await finish(task)
        # These save their last state as they stop: they are let finish, not cancelled.
        for owner, task, name in ((state.race, race_task, 'race timer'), (state.driving, drive_task, 'drive alerts'),
                                  (state.trip, trip_task, 'trip'), (state.nav, nav_task, 'navigation'),
                                  (state.health, health_task, 'Pi health')):
            if task:
                owner.stopping = True
                await step(name, lambda task=task: asyncio.wait_for(task, 10))
        if summary_task:
            state.summary.stopping = True
            await finish(summary_task)
            await step('drive summary', lambda: asyncio.to_thread(state.summary.finish, 'dash stopped'))   # Before the event log closes
        if eventlog_task:
            state.eventlog.stopping = True
            await finish(eventlog_task)
            await step('event log', lambda: state.eventlog.write('info', 'dash', 'Dash stopping'))
        if state.recorder:
            await step('recorder', state.recorder.close)
        await step('screens', lambda: asyncio.gather(*(ws.close(code=1001, message=b"Service stopping") for ws in list(clients)),
                                                     return_exceptions=True))
        if state.shutdown_history:
            await step('shutdown history', lambda: asyncio.to_thread(state.shutdown_history.finish, state))

    async def websocket(request):
        if request.url.host not in {'127.0.0.1', 'localhost', '::1'}:
            raise web.HTTPForbidden(text="Local dashboard only")
        origin = request.headers.get("Origin")
        if origin and origin != f"{request.scheme}://{request.host}":
            raise web.HTTPForbidden(text="Same-origin clients only")
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=1024)
        await ws.prepare(request)
        clients.add(ws)

        async def publish():
            while not ws.closed:
                await asyncio.wait_for(ws.send_json(state.snapshot()), timeout=2)
                await asyncio.sleep(.1)

        task = asyncio.create_task(publish())
        task.add_done_callback(lambda _: asyncio.create_task(ws.close()) if not ws.closed else None)
        requests, seen = set(), deque(maxlen=64)

        async def command(message):
            request_id = message['request_id']
            try:
                result = await state.controls.execute(message.get('action'), message.get('value'), owner=ws)
            except (ValueError, TypeError) as exc:
                result = {'status': 'rejected', 'message': str(exc)}
            if not ws.closed:
                with suppress(ConnectionError):
                    await ws.send_json({'type': 'command_result', 'request_id': request_id, **result})

        try:
            async for incoming in ws:
                if incoming.type != WSMsgType.TEXT: continue
                try:
                    message = json.loads(incoming.data)
                    if not isinstance(message, dict) or message.get('type') != 'command':
                        raise ValueError('Expected a command object')
                    request_id = message.get('request_id')
                    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 64:
                        raise ValueError('Invalid request ID')
                    if request_id in seen: raise ValueError('Duplicate command; not resent')
                    if len(requests) >= 4: raise ValueError('Too many pending commands')
                    seen.append(request_id)
                    pending = asyncio.create_task(command(message))
                    requests.add(pending)
                    pending.add_done_callback(requests.discard)
                except (ValueError, TypeError) as exc:
                    await ws.send_json({'type': 'command_result', 'status': 'rejected', 'message': str(exc)})
        finally:
            # Cancel unsent/in-flight requests before releasing the test lease.
            for pending in requests: pending.cancel()
            await asyncio.gather(*requests, return_exceptions=True)
            await state.controls.release(ws)
            task.cancel()
            with suppress(asyncio.CancelledError, ConnectionError, TimeoutError):
                await task
            clients.discard(ws)
        return ws

    async def health(request):
        snapshot = state.snapshot()
        # ui_clients lets the updater confirm the screen reconnected after a restart;
        # engine_running lets the Wi-Fi keeper leave the adapter free while the engine is off.
        rpm = state.runtime.rpm()
        return web.json_response({**{key: snapshot[key] for key in ('mode', 'transport', 'modules', 'gps', 'recording', 'system', 'can_errors')},
                                  'ui_clients': len(clients), 'engine_running': bool(rpm and rpm >= 300)})

    async def events(request):
        """The dash's record of what went wrong (eventlog.py): ?since=<unix time>, ?format=text."""
        if not state.eventlog:
            raise web.HTTPNotFound(text='No event log on this dash')
        try:
            since = float(request.query.get('since', 0))
            limit = max(1, min(5000, int(request.query.get('limit', 500))))
        except ValueError:
            raise web.HTTPBadRequest(text='since and limit are numbers')
        entries = await asyncio.to_thread(read_events, state.eventlog.folder, since, limit)
        if request.query.get('format') == 'text':
            return web.Response(text=events_text(entries), headers={'Cache-Control': 'no-store'})
        return web.json_response({'entries': entries, 'error': state.eventlog.error}, headers={'Cache-Control': 'no-store'})

    async def uploads(request):
        """Reports to GitHub (github_link.py): how they stand, and Connect / Disconnect."""
        require_local(request)
        if not state.github:
            raise web.HTTPNotFound(text='Uploads are only on the dash in the car')
        if request.method == 'POST':
            try:
                action = (await request.json()).get('action')
            except (ValueError, AttributeError):
                raise web.HTTPBadRequest(text='Invalid request')
            if action not in ('connect', 'disconnect'):
                raise web.HTTPBadRequest(text='connect or disconnect')
            try:
                if action == 'connect':
                    await state.github.connect()
                else:
                    await asyncio.to_thread(state.github.disconnect)
            except ValueError as error:
                raise web.HTTPConflict(text=str(error))
            except Exception as error:   # Said on the card, never a bare 500 page.
                raise web.HTTPInternalServerError(text=f'GitHub link failed: {error}')
        try:
            body = await asyncio.to_thread(state.github.status)
        except Exception as error:
            raise web.HTTPInternalServerError(text=f'Upload status unreadable: {error}')
        return web.json_response(body, headers={'Cache-Control': 'no-store'})

    async def logs(request):
        files = await asyncio.to_thread(state.recorder.files) if state.recorder else []
        return web.json_response({'recording': dict(state.recorder.status) if state.recorder else {'state': 'disabled', 'enabled': False}, 'files': files},
                                 headers={'Cache-Control': 'no-store'})

    async def finish_log(request):
        # The uploader (tools/frogdash_upload.py) finishes the file being recorded so the
        # drive that has just ended goes up complete.
        require_local(request)
        if not state.recorder:
            raise web.HTTPNotFound()
        return web.json_response({'ok': state.recorder.finish_current()})

    async def download_log(request):
        name = request.match_info['name']
        if not state.recorder or not LOG_NAME.fullmatch(name):
            raise web.HTTPNotFound()
        path = state.recorder.config.directory / name
        if path == state.recorder.writer.path:
            raise web.HTTPConflict(text='This log is still recording; download it after rotation or shutdown.')
        if path.is_symlink() or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Content-Type': 'application/octet-stream',
                                               'Content-Disposition': f'attachment; filename="{name}"', 'Cache-Control': 'no-store'})

    async def raw(request):
        return web.json_response(list(state.raw.values()))

    async def update(request):
        # The Update button: a root-owned path unit watches for the request file.
        require_local(request)
        folder = state.paint.path.parent if state.paint else None
        if not folder or state.mode == 'replay':
            raise web.HTTPNotFound()
        if request.method == 'POST':
            # 'rollback' returns to the version before the last update (tools/frogdash_update.sh).
            undo = False
            if request.can_read_body:
                try:
                    undo = (await request.json()).get('action') == 'rollback'
                except (ValueError, AttributeError):
                    raise web.HTTPBadRequest(text='Invalid update request')
            await asyncio.to_thread((folder / 'update-request').write_text, 'rollback' if undo else 'requested')
            return web.json_response({'state': 'requested', 'message': 'Going back requested' if undo else 'Update requested'})
        try:
            status = json.loads(await asyncio.to_thread((folder / 'update-status.json').read_text))
        except (OSError, ValueError):
            status = {'state': 'idle', 'message': 'No update has been run yet'}
        status['pending'] = (folder / 'update-request').exists()
        return web.json_response(status, headers={'Cache-Control': 'no-store'})

    async def screen(request):
        # The screen mode (tools/frogdash_screen.py, run as root by frogdash-screen.path):
        # try exact 1920 x 720 with a restart, keep it, or go back to the screen's own modes.
        require_local(request)
        folder = state.paint.path.parent if state.paint else None
        if not folder or state.mode == 'replay':
            raise web.HTTPNotFound()
        if request.method == 'POST':
            try:
                action = (await request.json()).get('action')
            except (ValueError, AttributeError):
                raise web.HTTPBadRequest(text='Invalid screen request')
            if action not in ('trial', 'keep', 'revert'):
                raise web.HTTPBadRequest(text='Unknown screen action')
            # Trying and going back restart the Pi; KEEP is the answer during a trial.
            if action != 'keep' and rolling(state):
                raise web.HTTPConflict(text='Stop the car first: this restarts the dash')
            await asyncio.to_thread((folder / 'screen-request').write_text, action)
            return web.json_response({'state': 'requested'})
        try:
            status = json.loads(await asyncio.to_thread((folder / 'screen-status.json').read_text))
        except (OSError, ValueError):
            status = {'state': 'idle', 'message': 'Not checked yet: the screen helper runs after the next update or start'}
        status['pending'] = (folder / 'screen-request').exists()
        # Only what the screen page needs; the full survey goes into the diagnostics download.
        keep = ('state', 'message', 'pending', 'started', 'deadline_s', 'applied', 'connectors', 'boot_time', 'first_render')
        return web.json_response({k: status[k] for k in keep if k in status}, headers={'Cache-Control': 'no-store'})

    async def firmware(request):
        # A module's firmware over the CAN bus (fwupdate.py): what it runs, what is ready, install.
        require_local(request)
        if not state.firmware:
            raise web.HTTPNotFound(text='Firmware updates are not available here')
        if request.method == 'POST':
            try:
                body = await request.json()
                valid = isinstance(body, dict) and body.get('module') in state.firmware.modules and body.get('action') == 'install'
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise web.HTTPBadRequest(text='Expected a known module and action: install')
            error = state.firmware.start(body['module'])
            if error:
                raise web.HTTPConflict(text=error)
        return web.json_response(state.firmware.snapshot(), headers={'Cache-Control': 'no-store'})

    async def tune(request):
        # TunerStudio over the dash: a request for the kiosk launcher to collect (tune.py).
        require_local(request)
        if state.mode == 'replay':
            raise web.HTTPNotFound()
        if request.method == 'POST':
            try:
                return web.json_response(state.tune.request((await request.json()).get('action')))
            except (ValueError, AttributeError) as error:
                raise web.HTTPConflict(text=str(error) or 'Invalid TunerStudio request')
        return web.json_response(state.tune.snapshot(), headers={'Cache-Control': 'no-store'})

    preset_lock = asyncio.Lock()

    async def meth_presets(request):
        # Water/meth pulse presets: list, apply (one setting at a time, each acknowledged
        # by the controller), and the owner's three Custom slots.
        require_local(request)
        mirror = state.meth_tune
        if request.method == 'GET':
            return web.json_response(mirror.preset_list(), headers={'Cache-Control': 'no-store'})
        try:
            body = await request.json()
            action, name = body.get('action'), body.get('name')
            if action == 'save':
                mirror.store(name)
                await asyncio.to_thread(mirror.persist)
                message = f'Current settings saved as {name}'
            elif action == 'delete':
                mirror.remove(name)
                await asyncio.to_thread(mirror.persist)
                message = f'{name} cleared'
            elif action in ('apply', 'fluid'):
                # A flow preset (pulse timing and limits) or a tank mix (blend and dose limit).
                choices = mirror.presets() if action == 'apply' else methtune.FLUIDS
                target = choices.get(name) if isinstance(name, str) else None
                if target is None:
                    raise ValueError('Unknown preset' if action == 'apply' else 'Unknown tank mix')
                if not mirror.complete():
                    raise ValueError('The water/meth controller has not reported its settings yet')
                if preset_lock.locked():
                    raise ValueError('A preset is already being applied')
                steps = methtune.plan(mirror.values, target)
                if steps is None:
                    raise ValueError('That preset cannot be reached from the current settings')
                async with preset_lock:
                    for index, (key, value) in enumerate(steps):
                        if index:
                            await preset_pause()
                        result = await state.controls.execute('meth.setting', key << 16 | value)
                        if result['status'] not in ('acknowledged', 'adjusted'):
                            raise ValueError(f"Stopped after {index} of {len(steps)} changes: {result['message']}")
                message = (f'{name} applied ({len(steps)} changes). Save to controller to keep it after power-off'
                           if steps else f'{name} is already set')
            else:
                raise ValueError('Unknown preset action')
        except (ValueError, AttributeError, TypeError) as error:
            raise web.HTTPConflict(text=str(error) or 'Invalid preset request')
        return web.json_response({'message': message, **mirror.preset_list()}, headers={'Cache-Control': 'no-store'})

    async def tune_kiosk(request):
        # The kiosk launcher's 2 s report; the reply is what it should do now.
        require_local(request)
        try:
            return web.json_response({'action': state.tune.report(await request.json())})
        except (ValueError, AttributeError, TypeError):
            raise web.HTTPBadRequest(text='Invalid kiosk report')

    async def wifi_client(request):
        # Join a Wi-Fi network for internet: a root-owned path unit performs the request.
        require_local(request)
        folder = state.paint.path.parent if state.paint else None
        if not folder or state.mode == 'replay':
            raise web.HTTPNotFound()
        if request.method == 'POST':
            try:
                body = await request.json()
                action, ssid, password = body.get('action'), body.get('ssid', ''), body.get('password', '')
                if action not in ('scan', 'connect', 'disconnect') or not isinstance(ssid, str) or not isinstance(password, str):
                    raise ValueError()
                if action == 'connect' and (not valid_ssid(ssid) or (password and not WIFI_PASSWORD.fullmatch(password))):
                    raise ValueError()
            except (ValueError, AttributeError, TypeError):
                raise web.HTTPBadRequest(text='Network name up to 32 characters; password 8 to 63 characters')
            await asyncio.to_thread(atomic_write, folder / 'wifi-request.json', {'action': action, 'ssid': ssid, 'password': password})
            return web.json_response({'pending': True})
        try:
            status = json.loads(await asyncio.to_thread((folder / 'wifi-status.json').read_text))
        except (OSError, ValueError):
            status = {'state': 'idle', 'message': 'Press Scan to look for networks', 'networks': []}
        status['pending'] = (folder / 'wifi-request.json').exists()
        return web.json_response(status, headers={'Cache-Control': 'no-store'})

    async def self_test(request):
        folder = state.paint.path.parent if state.paint else None
        return web.json_response(await asyncio.to_thread(selftest.report, state, folder), headers={'Cache-Control': 'no-store'})

    async def can_capture(request):
        # Record raw CAN traffic for a few seconds, then download it in candump log format.
        require_local(request)
        now = state.clock()
        if request.method == 'POST':
            try:
                seconds = int((await request.json()).get('seconds', 10))
            except (ValueError, AttributeError, TypeError):
                raise web.HTTPBadRequest(text='seconds must be a number')
            state.capture, state.capture_until = [], now + max(1, min(120, seconds))
        if request.query.get('download') and state.capture is not None:
            return web.Response(text='\n'.join(state.capture) + '\n', content_type='text/plain',
                                headers={'Content-Disposition': 'attachment; filename="frogdash-can.log"', 'Cache-Control': 'no-store'})
        return web.json_response({'frames': len(state.capture or []), 'recording': state.capture is not None and now <= state.capture_until,
                                  'remaining_s': max(0, round(state.capture_until - now)), 'available': state.capture is not None},
                                 headers={'Cache-Control': 'no-store'})

    def terminal_helper():
        # The Terminal helper (tools/frogdash_terminal.py, frogdash-terminal.socket) runs a
        # command as the screen user, so sudo works. The setup lets this service reach it
        # only while --terminal is set; without it the command runs here, restricted.
        return os.name == 'posix' and TERMINAL_SOCKET.exists() and os.access(TERMINAL_SOCKET, os.W_OK)

    async def terminal(request):
        # Optional (--terminal): a command from the dash's own screen (loopback only), as
        # the screen user through the helper when it is installed, else as this service's
        # own restricted user. Not interactive either way.
        require_local(request)
        if not state.terminal_enabled or state.mode == 'replay':
            raise web.HTTPNotFound(text='Terminal is not enabled (--terminal)')
        if request.method == 'GET':
            return web.json_response({'enabled': True, 'sudo': terminal_helper()})
        try:
            command = (await request.json()).get('command')
            if not isinstance(command, str) or not command.strip() or len(command) > 2000:
                raise ValueError()
        except (ValueError, AttributeError, TypeError):
            raise web.HTTPBadRequest(text='Type a command (up to 2000 characters)')
        if terminal_helper():
            try:
                reader, writer = await asyncio.open_unix_connection(str(TERMINAL_SOCKET), limit=1 << 20)
                writer.write(json.dumps({'command': command}).encode() + b'\n')
                await writer.drain()
                answer = json.loads(await asyncio.wait_for(reader.readline(), 90))
                writer.close()
                return web.json_response({'exit': answer.get('exit'), 'output': answer.get('output', ''), 'user': answer.get('user')},
                                         headers={'Cache-Control': 'no-store'})
            except (OSError, ValueError, asyncio.TimeoutError) as error:
                return web.json_response({'exit': 2, 'output': f'The Terminal helper did not answer: {error}'}, headers={'Cache-Control': 'no-store'})
        process = await asyncio.create_subprocess_exec('/bin/bash', '-c', command, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'TERM': 'dumb', 'LC_ALL': 'C'})
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 30)
            code, note = process.returncode, ''
        except asyncio.TimeoutError:
            process.kill()
            output, code, note = await process.stdout.read(), 124, '\n[stopped after 30 s]'
        text = output.decode('utf-8', 'replace')
        if len(text) > 100000:
            text = '[earlier output trimmed]\n' + text[-100000:]
        return web.json_response({'exit': code, 'output': text + note}, headers={'Cache-Control': 'no-store'})

    async def terminal_session(request):
        # The Terminal tab's live shell: this page's keystrokes in, the shell's output out,
        # through the helper (as the screen user, in a pty, so prompts wait for an answer).
        require_local(request)
        if not state.terminal_enabled or state.mode == 'replay' or not terminal_helper():
            raise web.HTTPNotFound(text='The interactive terminal needs --terminal and its helper (Update now once)')
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=64 * 1024)
        await ws.prepare(request)
        try:
            reader, writer = await asyncio.open_unix_connection(str(TERMINAL_SOCKET))
        except OSError as error:
            await ws.send_str(f'The Terminal helper did not answer: {error}\r\n')
            await ws.close()
            return ws
        writer.write(b'{"mode": "session"}\n')
        await writer.drain()
        decoder = codecs.getincrementaldecoder('utf-8')('replace')

        async def shell_to_page():
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                text = decoder.decode(data)
                if text and not ws.closed:
                    await ws.send_str(text)
            if not ws.closed:
                await ws.close()
        relay = asyncio.create_task(shell_to_page())
        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    writer.write(message.data.encode('utf-8'))
                    await writer.drain()
                elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()        # The helper ends the shell when its connection closes.
            relay.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await relay
        return ws

    async def can_check(request):
        return web.json_response(cancheck.report(state), headers={'Cache-Control': 'no-store'})

    async def race_command(request):
        require_local(request)
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'action'} or not isinstance(body['action'], str):
                raise ValueError('Expected a race action')
            if not state.gps or state.mode == 'replay':
                raise ValueError('Race timing requires the local USB GPS (--gpsd)')
            state.race.command(body['action'])
        except (ValueError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response(state.race.snapshot(), headers={'Cache-Control': 'no-store'})

    async def race_results(request):
        require_local(request)
        return web.json_response({'version': 1, 'gate': state.race.gate, 'history': state.race.history},
            headers={'Cache-Control': 'no-store', 'Content-Disposition': 'attachment; filename="frogdash-race-results.json"'})

    async def drive_settings(request):
        require_local(request)
        if request.method == 'POST':
            try:
                state.driving.configure(await request.json())
            except (ValueError, TypeError) as exc:
                raise web.HTTPBadRequest(text=str(exc))
            await state.driving.save()
        return web.json_response(state.driving.snapshot(), headers={'Cache-Control': 'no-store'})

    async def drive_action(request):
        require_local(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError('Expected an object')
            if request.match_info['action'] == 'mark' and set(body) <= {'label'}:
                result = state.driving.bookmark(body.get('label', 'Driver bookmark'))
            elif request.match_info['action'] == 'ack' and set(body) == {'key'} and isinstance(body['key'], str):
                state.driving.acknowledge(body['key'])
                result = state.driving.snapshot()
            else:
                raise ValueError('Unknown action or fields')
        except (ValueError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc))
        return web.json_response(result, headers={'Cache-Control': 'no-store'})

    async def drives(request):
        require_local(request)
        return web.json_response({'drives': await state.driving.get_reviews()}, headers={'Cache-Control': 'no-store'})

    async def trip(request):
        require_local(request)
        if request.method == 'POST':
            try:
                body = await request.json()
                if not isinstance(body, dict):
                    raise ValueError('Expected a trip command')
                if set(body) == {'settings'}:
                    state.trip.configure(body['settings'])
                elif set(body) == {'reset'} and isinstance(body['reset'], str):
                    state.trip.reset(body['reset'])
                elif set(body) == {'remaining_l'}:
                    state.trip.set_fuel(body['remaining_l'])
                elif set(body) == {'odometer_km'}:
                    state.trip.set_odometer(body['odometer_km'])
                else:
                    raise ValueError('Unknown trip command or fields')
            except (ValueError, TypeError) as exc:
                raise web.HTTPBadRequest(text=str(exc))
            await state.trip.save(force=True)
        return web.json_response(state.trip.snapshot(), headers={'Cache-Control': 'no-store'})

    async def drive_review(request):
        require_local(request)
        try:
            data = await state.driving.get_review(request.match_info['name'])
        except (OSError, ValueError, TypeError):
            raise web.HTTPNotFound(text='Drive review unavailable')
        return web.json_response(data, headers={'Cache-Control': 'no-store'})

    async def wifi_status(request):
        require_local(request)
        return web.json_response(dict(connectivity.status) if connectivity else
            {'configured': False, 'enabled': False, 'error': 'Wi-Fi setup is not enabled in this service.'},
            headers={'Cache-Control': 'no-store'})

    async def wifi_toggle(request):
        require_local(request)
        if not connectivity or state.mode == 'replay':
            raise web.HTTPServiceUnavailable(text='Wi-Fi control unavailable')
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'enabled'} or type(body['enabled']) is not bool:
                raise ValueError()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text='Expected enabled: true or false')
        try:
            return web.json_response(await connectivity.update(body['enabled']))
        except (OSError, TimeoutError, ClientError):
            raise web.HTTPServiceUnavailable(text='Could not update hotspot')

    async def camera_status(request):
        require_local(request)
        body = state.camera.status() if state.camera else {'enabled': False}
        return web.json_response(body, headers={'Cache-Control': 'no-store'})

    async def camera_stream(request):
        require_local(request)
        if not state.camera:
            raise web.HTTPNotFound(text='Reverse camera is not enabled (--camera)')
        return await mjpeg(request, state.camera)

    async def dashcam_status(request):
        require_local(request)
        body = state.dashcam.status() if state.dashcam else {'enabled': False}
        return web.json_response(body, headers={'Cache-Control': 'no-store'})

    async def dashcam_stream(request):
        require_local(request)
        if not state.dashcam:
            raise web.HTTPNotFound(text='Dash cam is not enabled (--dashcam)')
        return await mjpeg(request, state.dashcam)

    async def dashcam_side(request):
        require_local(request)
        if not state.dashcam:
            raise web.HTTPNotFound(text='Dash cam is not enabled (--dashcam)')
        try:
            side = (await request.json()).get('side')
            await asyncio.to_thread(state.dashcam.switch, side)
        except (ValueError, AttributeError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc) or 'Invalid side')
        except (OSError, RuntimeError) as exc:
            raise web.HTTPServiceUnavailable(text=f'Dash cam did not switch: {exc}'[:200])
        return web.json_response(state.dashcam.status())

    async def dashcam_warm(request):
        # Keep the dash cam's picture arriving in the background so a view is instant.
        require_local(request)
        if not state.dashcam:
            raise web.HTTPNotFound(text='Dash cam is not enabled (--dashcam)')
        try:
            body = await request.json()
            if not isinstance(body, dict) or type(body.get('enabled')) is not bool:
                raise ValueError()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text='Expected enabled: true or false')
        await asyncio.to_thread(state.dashcam.set_keep_warm, body['enabled'])
        return web.json_response(state.dashcam.status())

    async def mjpeg(request, camera):
        try:
            await camera.acquire()
        except Exception:
            raise web.HTTPServiceUnavailable(text=camera.error or 'Camera unavailable')
        response = web.StreamResponse(headers={'Content-Type': f'multipart/x-mixed-replace; boundary={CAMERA_BOUNDARY}',
                                               'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        try:
            await response.prepare(request)
            sequence = 0
            while True:
                item = await camera.next_frame(sequence)
                if item is None:
                    if not camera.running:
                        break
                    continue
                sequence, frame = item
                await response.write(b'--%s\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n' % (CAMERA_BOUNDARY.encode(), len(frame)) + frame + b'\r\n')
        except ConnectionResetError:
            pass
        finally:
            await camera.release()
        return response

    async def asset(request):
        name = request.match_info.get("name", "index.html")
        if name not in {"index.html", "app.js", "style.css", "keyboard.js", "keyboard.css", "summary.js", "viewport.js", "responsive.css", "instruments.js", "instruments.css", "personalize.js", "driving.js", "trip.js", "operations.js", "units.js", "review.js", "review.css", "navigation.js", "camera.js", "camera.css", "dashcam.js", "map.js", "boot.js", "taillights.js", "taillights.css", "taillight-settings.js", "meth-tune.js", "knock.js", "knock.css", "screen.js"}:
            raise web.HTTPNotFound()
        if name == 'index.html' and state.paint and state.paint.value:
            page = await asyncio.to_thread((WEB / name).read_text, encoding='utf-8')
            return web.Response(text=state.paint.inject(page), content_type='text/html', headers={"Cache-Control": "no-store"})
        return web.FileResponse(WEB / name, headers={"Cache-Control": "no-store"})

    async def import_list(request):
        require_local(request)
        if not state.imports:
            return web.json_response({'directory': None, 'files': [], 'error': 'Import folder not configured'}, headers={'Cache-Control': 'no-store'})
        return web.json_response(await asyncio.to_thread(state.imports.listing), headers={'Cache-Control': 'no-store'})

    async def import_file(request):
        require_local(request)
        path = state.imports and await asyncio.to_thread(state.imports.path, request.match_info['name'])
        if not path:
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    async def taillight_frames(request):
        # Frames recorded from the CustomTaillights firmware for the on-screen mirror.
        name = request.match_info['name']
        if name not in {'frames.bin', 'frames.json'}:
            raise web.HTTPNotFound()
        return web.FileResponse(WEB / 'taillights' / name, headers={'Cache-Control': 'no-cache'})

    async def map_data(request):
        # Offline street maps built by tools/make_map.py (OpenStreetMap, ODbL).
        name = request.match_info['name']
        path = WEB.parent / 'maps' / name
        if not re.fullmatch(r'[a-z0-9-]{1,40}\.json', name) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Cache-Control': 'no-cache'})

    async def appearance_snapshot(request):
        # The dashboard's current look, written to disk so the next start paints it first.
        require_local(request)
        if not state.paint:
            raise web.HTTPNotFound()
        raw = await request.read()
        if len(raw) > 32768:
            raise web.HTTPBadRequest(text='Snapshot too large')
        try:
            value = validate_paint(json.loads(raw))
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text='Invalid appearance snapshot')
        if value != state.paint.value:
            await asyncio.to_thread(state.paint.save, value)
        return web.Response(status=204)

    async def appearance_image(request):
        # Background/splash images on disk: browser storage may not reach the SD card before key-off.
        require_local(request)
        field = request.match_info['field']
        if not state.paint:
            raise web.HTTPNotFound()
        path = state.paint.path.with_name(f'appearance-{field}.json')
        if request.method == 'GET':
            try:
                data = await asyncio.to_thread(lambda: json.loads(path.read_text(encoding='utf-8'))['data'])
            except (OSError, ValueError, KeyError, TypeError):
                raise web.HTTPNotFound()
            return web.json_response({'data': data}, headers={'Cache-Control': 'no-store'})
        if request.method == 'DELETE':
            await asyncio.to_thread(path.unlink, missing_ok=True)
            return web.Response(status=204)
        raw = await request.read()
        try:
            data = json.loads(raw)['data']
        except (ValueError, KeyError, TypeError):
            raise web.HTTPBadRequest(text='Invalid image')
        if not isinstance(data, str) or len(data) >= 1500000 or not IMAGE_DATA.fullmatch(data):
            raise web.HTTPBadRequest(text='Invalid image')
        await asyncio.to_thread(atomic_write, path, {'data': data})
        return web.Response(status=204)

    async def operations(request):
        require_local(request)
        action = request.match_info['action']
        try:
            if action == 'diagnostic' and request.method == 'GET':
                return web.json_response(state.operations.diagnostic(), headers={'Content-Disposition': 'attachment; filename="frogdash-diagnostic.json"', 'Cache-Control': 'no-store'})
            if action == 'status' and request.method == 'GET':
                return web.json_response({**state.operations.status(), 'ui': state.operations.data['ui'], 'backlight': state.backlight.status()}, headers={'Cache-Control': 'no-store'})
            if action == 'backup' and request.method == 'POST':
                body = await request.json()
                if not isinstance(body, dict) or set(body) != {'ui'}:
                    raise ValueError('Expected current display preferences')
                return web.json_response(state.operations.backup(body['ui']))
            if action == 'restore' and request.method == 'POST':
                ui = await state.operations.restore(await request.json())
                return web.json_response({'ui': ui})
            if action == 'settings' and request.method == 'POST':
                await state.operations.change(await request.json())
                return web.json_response(state.operations.status())
            if action == 'backlight' and request.method == 'POST':
                body = await request.json()
                if not isinstance(body, dict) or set(body) != {'percent'}:
                    raise ValueError('Expected percent')
                percent = await asyncio.to_thread(state.backlight.set, body['percent'])
                return web.json_response({'percent': percent})
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            raise web.HTTPBadRequest(text=str(exc))
        except OSError:
            raise web.HTTPServiceUnavailable(text=state.operations.error or 'Could not save settings; check storage and permissions')
        raise web.HTTPNotFound()

    async def heartbeat(request):
        require_local(request)
        import re
        token = request.match_info['token']
        if not re.fullmatch('[0-9a-f]{32}', token):
            raise web.HTTPBadRequest()
        now = state.clock()
        if request.method == 'POST':
            if request.can_read_body:
                raw = await request.read()
                if len(raw) > 4096:
                    raise web.HTTPBadRequest(text='Display report too large')
                try:
                    import math
                    data = json.loads(raw)
                    report = data['display']
                    allowed = {'screen', 'viewport', 'visual', 'pixel_ratio', 'responsive',
                               'dashboard', 'position', 'transform', 'margin', 'body_overflow',
                               'scroll', 'browser', 'responsive_css'}
                    if set(data) != {'display'} or not isinstance(report, dict) or not set(report) <= allowed:
                        raise ValueError()
                    for value in report.values():
                        if isinstance(value, str):
                            if len(value) > 200:
                                raise ValueError()
                        elif isinstance(value, list):
                            if len(value) > 5 or any(type(n) not in (int, float) or abs(n) > 100000 or not math.isfinite(n) for n in value):
                                raise ValueError()
                        elif type(value) not in (bool, int, float) or abs(value) > 100000 or not math.isfinite(value):
                            raise ValueError()
                    state.operations.display_report = {'sampled': now, 'display': report}
                except (ValueError, TypeError, KeyError):
                    raise web.HTTPBadRequest(text='Invalid display report')
            state.operations.heartbeats[token] = now
            state.operations.heartbeats = {k: v for k, v in state.operations.heartbeats.items() if now - v < 120}
            if len(state.operations.heartbeats) > 16:
                del state.operations.heartbeats[next(iter(state.operations.heartbeats))]
        seen = state.operations.heartbeats.get(token)
        return web.json_response({'alive': seen is not None and now - seen < 10}, headers={'Cache-Control': 'no-store'})

    async def display_info(request):
        require_local(request)
        report = state.operations.display_report
        if not report:
            return web.json_response({'status': 'waiting for kiosk heartbeat'}, headers={'Cache-Control': 'no-store'})
        age = max(0, state.clock() - report['sampled'])
        return web.json_response({'status': 'fresh' if age < 10 else 'stale',
                                  'age_seconds': round(age, 2), **report['display']},
                                 headers={'Cache-Control': 'no-store'})

    app.cleanup_ctx.append(lifecycle)
    app.add_routes([web.get("/state", websocket), web.get("/health", health),
                    web.get("/ui/display", display_info), web.get("/raw", raw), web.get("/can/check", can_check), web.get("/selftest", self_test), web.get("/can/capture", can_capture), web.post("/can/capture", can_capture), web.get("/terminal", terminal), web.get("/terminal/session", terminal_session), web.get("/meth/presets", meth_presets), web.post("/meth/presets", meth_presets), web.get("/tune", tune), web.post("/tune", tune), web.post("/tune/kiosk", tune_kiosk), web.post("/terminal", terminal), web.get("/update", update), web.get("/screen", screen), web.post("/screen", screen), web.get("/firmware", firmware), web.post("/firmware", firmware), web.get("/wifi-client", wifi_client), web.post("/wifi-client", wifi_client), web.post("/update", update), web.get('/logs', logs), web.get('/events', events), web.get('/uploads', uploads), web.post('/uploads', uploads), web.post('/logs/finish', finish_log), web.get('/logs/{name}', download_log),
                    web.get('/connectivity', wifi_status), web.post('/connectivity', wifi_toggle),
                    web.post('/race', race_command), web.get('/race/results', race_results),
                    web.get('/drive/settings', drive_settings), web.post('/drive/settings', drive_settings),
                    web.post('/drive/{action:mark|ack}', drive_action),
                    web.get('/drives', drives), web.get('/drives/{name}', drive_review),
                    web.get('/trip', trip), web.post('/trip', trip),
                    web.get('/operations/{action}', operations), web.post('/operations/{action}', operations),
                    web.post('/ui/appearance', appearance_snapshot),
                    web.route('*', '/ui/appearance/image/{field:background|splash}', appearance_image),
                    web.get('/taillights/{name}', taillight_frames), web.get('/maps/{name}', map_data),
                    web.get('/ui/import', import_list), web.get('/ui/import/{name}', import_file),
                    web.get('/camera/status', camera_status), web.get('/camera/stream', camera_stream),
                    web.get('/dashcam/status', dashcam_status), web.get('/dashcam/stream', dashcam_stream),
                    web.post('/dashcam/side', dashcam_side), web.post('/dashcam/warm', dashcam_warm),
                    web.get('/ui/heartbeat/{token}', heartbeat), web.post('/ui/heartbeat/{token}', heartbeat),
                    web.get("/", asset), web.get("/{name}", asset)])
    return app


def main():
    parser = argparse.ArgumentParser(description="Frogdash CAN dashboard with optional USB GPS broadcast")
    parser.add_argument("--interface", default="can0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--gpsd", action="store_true", help="Use local gpsd USB GPS and broadcast 0x203")
    parser.add_argument("--gps-device", help="gpsd device path; otherwise lock to first receiver")
    parser.add_argument("--gps-no-transmit", action="store_true", help="Use USB GPS locally without CAN GPS transmission")
    parser.add_argument("--terminal", action="store_true",
                        help="Enable the Terminal tab: commands run as the unprivileged dash service user, local screen only")
    parser.add_argument("--no-engine-runtime", action="store_true",
                        help="Do not publish 0x309 engine RPM for water/meth (use when the CCM dashboard firmware sends it)")
    parser.add_argument('--log-dir', type=Path, help='Enable rotating MLG recording in this dedicated directory')
    parser.add_argument('--log-hz', type=float, default=20)
    parser.add_argument('--log-minutes', type=float, default=30)
    parser.add_argument('--log-file-mib', type=int, default=32)
    parser.add_argument('--log-total-mib', type=int, default=2048)
    parser.add_argument('--log-min-free-mib', type=int, default=256)
    parser.add_argument('--hotspot-socket', type=Path, help='Enable the optional local Wi-Fi helper socket')
    parser.add_argument('--race-file', type=Path, default=Path('/var/lib/frogdash/race.json'), help='Saved start/finish and last 50 race sessions')
    parser.add_argument('--data-dir', type=Path, default=Path('/var/lib/frogdash'), help='Alert settings and bounded drive reviews')
    parser.add_argument('--camera', action='store_true', help='Enable the Raspberry Pi CSI reverse camera (python3-picamera2)')
    parser.add_argument('--camera-size', default='1024x768', help='Capture size WIDTHxHEIGHT (default 1024x768)')
    parser.add_argument('--camera-quality', choices=('medium', 'high', 'max'), default='high', help='MJPEG image quality (default high)')
    parser.add_argument('--camera-fps', type=int, default=30)
    parser.add_argument('--camera-rotate', type=int, choices=(0, 180), default=0, help='180 if the camera is mounted upside down')
    parser.add_argument('--dashcam', action='store_true', help='Enable the Wi-Fi dash cam view (Viidure-app cameras; needs ffmpeg)')
    parser.add_argument('--dashcam-host', default='192.168.169.1', help="Dash cam IP on its Wi-Fi (default 192.168.169.1)")
    parser.add_argument('--dashcam-width', type=int, default=1280, help='Displayed width; the stream is scaled down to this (default 1280)')
    parser.add_argument('--camera-keep-warm', action='store_true', help='Keep the camera running between views for instant display')
    parser.add_argument('--backlight-name', help='Explicit Linux /sys/class/backlight device; requires write permission')
    args = parser.parse_args()
    if args.loop and not args.replay:
        parser.error("--loop requires --replay")
    if args.replay and args.gpsd:
        parser.error("--gpsd cannot be combined with replay")
    if args.replay and args.hotspot_socket:
        parser.error('--hotspot-socket cannot be combined with replay')
    if (args.gps_device or args.gps_no_transmit) and not args.gpsd:
        parser.error("GPS options require --gpsd")
    state = State("replay" if args.replay else "socketcan")
    state.terminal_enabled = args.terminal and not args.replay
    if args.no_engine_runtime:
        state.runtime.enabled, state.runtime.status = False, 'disabled (--no-engine-runtime)'
    state.race = Race(args.race_file if not args.replay else None)
    state.driving = Driving(state, args.data_dir / 'replay' if args.replay else args.data_dir)
    state.trip = Trip(state, (args.data_dir / 'replay' if args.replay else args.data_dir) / 'trip.json')
    state.nav = Navigator(state.clock, state.wall, None if args.replay else args.data_dir / 'nav.json')
    state.operations = Operations(state, args.data_dir / 'replay' if args.replay else args.data_dir)
    state.backlight = Backlight(args.backlight_name)
    state.health = Health(state, args.interface, args.log_dir or args.data_dir)
    state.controls.load_interior((args.data_dir / 'replay' if args.replay else args.data_dir) / 'interior.json')
    state.controls.load_meth((args.data_dir / 'replay' if args.replay else args.data_dir) / 'meth-arm.json')
    state.meth_tune.load((args.data_dir / 'replay' if args.replay else args.data_dir) / 'meth-presets.json')
    state.imports = Imports((args.data_dir / 'replay' if args.replay else args.data_dir) / 'import', Path(__file__).resolve().parents[1] / 'art')
    state.paint = Paint((args.data_dir / 'replay' if args.replay else args.data_dir) / 'appearance-paint.json')
    state.shutdown_history = ShutdownHistory((args.data_dir / 'replay' if args.replay else args.data_dir) / 'shutdown.json')
    state.eventlog = EventLog(state, (args.data_dir / 'replay' if args.replay else args.data_dir) / 'events')
    state.summary = DriveSummary(state, args.data_dir / 'replay' if args.replay else args.data_dir)
    if args.log_dir:
        try:
            config = LogConfig(args.log_dir.resolve(), args.log_hz, args.log_minutes * 60,
                               args.log_file_mib * MIB, args.log_total_mib * MIB, args.log_min_free_mib * MIB)
        except ValueError as exc:
            parser.error(str(exc))
        state.recorder = Recorder(state, config)
    if (args.camera_keep_warm or args.camera_size != '1024x768' or args.camera_quality != 'high' or args.camera_fps != 30 or args.camera_rotate) and not args.camera:
        parser.error('Camera options require --camera')
    if args.dashcam:
        from .dashcam import Dashcam
        try:
            # Buffers in the background by default; the dash cam view has the switch.
            state.dashcam = Dashcam(args.dashcam_host, width=args.dashcam_width, keep_warm=True,
                                    settings=args.data_dir / 'dashcam.json')
        except ValueError as exc:
            parser.error(f'Invalid dash cam option: {exc}')
    if args.camera:
        try:
            width, height = (int(n) for n in args.camera_size.lower().split('x'))
            state.camera = Camera(width, height, args.camera_fps, args.camera_rotate, idle_s=10 ** 9 if args.camera_keep_warm else 20, quality=args.camera_quality)
        except ValueError as exc:
            parser.error(f'Invalid camera option: {exc}')
    if not args.replay:
        state.helpers = Helpers(args.data_dir)
        state.firmware = Firmware(state, args.data_dir / 'firmware')
        state.github = GitHubLink(args.data_dir)
    if args.gpsd:
        state.gps = GPS(device=args.gps_device, transmit=not args.gps_no_transmit)
        # Watches for a missing position and works through the recovery steps (gpswatch.py).
        state.gps_recovery = GpsRecovery(state.gps, args.data_dir, state.clock)
        # Satellite data kept across power-offs: the VK-162 has no backup battery (gpsaid.py).
        state.gps_aid = GpsAid(state.gps, args.data_dir, state.nav)
    if args.replay:
        try:
            frames = read_replay(args.replay)
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        adapter = lambda: replay(state, frames, args.loop)
    else:
        adapter = lambda: socketcan(state, args.interface)
    # The helper's socket has a fixed place; the option only overrides it. Until the Pi
    # setup has installed the helper the Wi-Fi tab says so and nothing else changes.
    socket_path = args.hotspot_socket or (DEFAULT_SOCKET if os.name == 'posix' and not args.replay else None)
    connectivity = Connectivity(state, socket_path, args.data_dir) if socket_path else None
    web.run_app(create_app(state, adapter, connectivity), host="127.0.0.1", port=args.port, access_log=None, shutdown_timeout=3)


if __name__ == "__main__":
    main()
