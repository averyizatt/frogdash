"""Local HTTP + WebSocket service, independently paced per browser client."""
import argparse
import asyncio
import json
from collections import deque
from contextlib import suppress
from pathlib import Path

from aiohttp import web, WSMsgType, ClientError
from .adapters import read_replay, replay, socketcan
from .state import State
from .gps import GPS, gpsd
from .recorder import Config as LogConfig, Recorder, NAME as LOG_NAME, MIB
from .connectivity import Connectivity, require_local
from .race import Race
from .driving import Driving
from .health import Health

WEB = Path(__file__).resolve().parents[1] / "ui"


def create_app(state, adapter=None, connectivity=None):
    app = web.Application()
    clients = set()

    async def lifecycle(app):
        tasks = [asyncio.create_task(adapter())] if adapter else []
        race_task = asyncio.create_task(state.race.run())
        drive_task = asyncio.create_task(state.driving.run())
        health_task = asyncio.create_task(state.health.run()) if state.health else None
        if state.gps:
            state.gps.on_report = state.race.feed
            tasks.append(asyncio.create_task(gpsd(state.gps)))
        if state.recorder:
            state.recorder.start()
        if connectivity:
            await connectivity.start()
        yield
        await state.controls.close()
        if connectivity:
            await connectivity.close()
        if state.health:
            state.health.stopping = True
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        state.race.stopping = True
        await race_task
        state.driving.stopping = True
        await drive_task
        if health_task:
            await health_task
        if state.recorder:
            await state.recorder.close()
        await asyncio.gather(*(ws.close(code=1001, message=b"Service stopping") for ws in list(clients)))

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
        return web.json_response({key: snapshot[key] for key in ('mode', 'transport', 'modules', 'gps', 'recording', 'system', 'can_errors')})

    async def logs(request):
        files = await asyncio.to_thread(state.recorder.files) if state.recorder else []
        return web.json_response({'recording': dict(state.recorder.status) if state.recorder else {'state': 'disabled', 'enabled': False}, 'files': files},
                                 headers={'Cache-Control': 'no-store'})

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

    async def asset(request):
        name = request.match_info.get("name", "index.html")
        if name not in {"index.html", "app.js", "style.css", "personalize.js", "driving.js", "review.js", "review.css"}:
            raise web.HTTPNotFound()
        return web.FileResponse(WEB / name, headers={"Cache-Control": "no-store"})

    app.cleanup_ctx.append(lifecycle)
    app.add_routes([web.get("/state", websocket), web.get("/health", health),
                    web.get("/raw", raw), web.get('/logs', logs), web.get('/logs/{name}', download_log),
                    web.get('/connectivity', wifi_status), web.post('/connectivity', wifi_toggle),
                    web.post('/race', race_command), web.get('/race/results', race_results),
                    web.get('/drive/settings', drive_settings), web.post('/drive/settings', drive_settings),
                    web.post('/drive/{action:mark|ack}', drive_action),
                    web.get('/drives', drives), web.get('/drives/{name}', drive_review),
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
    parser.add_argument('--log-dir', type=Path, help='Enable rotating MLG recording in this dedicated directory')
    parser.add_argument('--log-hz', type=float, default=20)
    parser.add_argument('--log-minutes', type=float, default=30)
    parser.add_argument('--log-file-mib', type=int, default=32)
    parser.add_argument('--log-total-mib', type=int, default=2048)
    parser.add_argument('--log-min-free-mib', type=int, default=256)
    parser.add_argument('--hotspot-socket', type=Path, help='Enable the optional local Wi-Fi helper socket')
    parser.add_argument('--race-file', type=Path, default=Path('/var/lib/frogdash/race.json'), help='Saved start/finish and last 50 race sessions')
    parser.add_argument('--data-dir', type=Path, default=Path('/var/lib/frogdash'), help='Alert settings and bounded drive reviews')
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
    state.race = Race(args.race_file if not args.replay else None)
    state.driving = Driving(state, args.data_dir / 'replay' if args.replay else args.data_dir)
    state.health = Health(state, args.interface, args.log_dir or args.data_dir)
    if args.log_dir:
        try:
            config = LogConfig(args.log_dir.resolve(), args.log_hz, args.log_minutes * 60,
                               args.log_file_mib * MIB, args.log_total_mib * MIB, args.log_min_free_mib * MIB)
        except ValueError as exc:
            parser.error(str(exc))
        state.recorder = Recorder(state, config)
    if args.gpsd:
        state.gps = GPS(device=args.gps_device, transmit=not args.gps_no_transmit)
    if args.replay:
        try:
            frames = read_replay(args.replay)
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        adapter = lambda: replay(state, frames, args.loop)
    else:
        adapter = lambda: socketcan(state, args.interface)
    connectivity = Connectivity(state, args.hotspot_socket) if args.hotspot_socket else None
    web.run_app(create_app(state, adapter, connectivity), host="127.0.0.1", port=args.port, access_log=None, shutdown_timeout=3)


if __name__ == "__main__":
    main()
