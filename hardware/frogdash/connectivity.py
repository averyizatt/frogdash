"""Local hotspot control and a separate, authenticated phone site: logs, faults, updates."""
import asyncio
from collections import deque
from contextlib import suppress
import ipaddress
import json
from pathlib import Path
import secrets
import time

import aiohttp
from aiohttp import web

from . import selftest
from .hotspot_helper import ADDRESS, PORT
from .recorder import NAME

TRANSFER_UI = Path(__file__).resolve().parents[1] / 'transfer'
DEFAULT_SOCKET = Path('/run/frogdash-connect/control.sock')
RESUME_S = 15 * 60   # An update started from the phone keeps the hotspot and the login this long.
CAMERAS_OFF = 'Cameras are off while the phone hotspot is on (they share one Wi-Fi adapter)'
# Helper results kept in the data folder, included in the diagnostics download.
STATUS_FILES = ('update-status.json', 'setup-status.json', 'gps-status.json', 'wifi-status.json')


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, AttributeError):
        return None


def load_resume(folder, wall=time.time):
    """The code and session kept across an update restart, while still fresh."""
    data = read_json(folder / 'hotspot-resume.json') if folder else None
    if (isinstance(data, dict) and isinstance(data.get('code'), str) and isinstance(data.get('session'), str)
            and isinstance(data.get('until'), (int, float)) and 0 < data['until'] - wall() <= RESUME_S):
        return data
    return None


def require_local(request):
    try:
        local = ipaddress.ip_address(request.remote).is_loopback
    except (ValueError, TypeError):
        local = False
    if not local or request.url.host not in {'localhost', '127.0.0.1', '::1'}:
        raise web.HTTPForbidden(text='Use the dashboard on the Pi')
    if request.headers.get('Origin') not in (None, f'{request.scheme}://{request.host}'):
        raise web.HTTPForbidden(text='Same-origin dashboard only')


class TransferPortal:
    def __init__(self, state, folder=None, wall=time.time):
        self.state, self.folder, self.wall = state, folder, wall
        resume = load_resume(folder, wall)
        self.code = resume['code'] if resume else f'{secrets.randbelow(100_000_000):08d}'
        self.session = resume['session'] if resume else secrets.token_urlsafe(32)
        self.attempts = deque(maxlen=10)
        self.runner = None

    def update_status(self):
        status = read_json(self.folder / 'update-status.json') if self.folder else None
        if not isinstance(status, dict):
            status = {'state': 'idle', 'message': 'No update has been run yet'}
        status['pending'] = bool(self.folder) and (self.folder / 'update-request').exists()
        return status

    def firmware_status(self):
        firmware = getattr(self.state, 'firmware', None)
        return {firmware.name: firmware.snapshot()} if firmware else {}

    def check(self):
        return {'report': selftest.report(self.state, self.folder), 'update': self.update_status(), 'firmware': self.firmware_status()}

    def diagnostics(self):
        """Everything needed to see what went wrong, in one file."""
        files = {name: read_json(self.folder / name) for name in STATUS_FILES} if self.folder else {}
        try:
            failure = (self.folder / 'update-failure.log').read_text(encoding='utf-8', errors='replace')[-20000:]
        except (OSError, AttributeError):
            failure = None
        return {'format': 'dash-diagnostics', 'version': 1, 'created_ms': int(self.wall() * 1000),
                'check': selftest.report(self.state, self.folder), 'update': self.update_status(),
                'helpers': files, 'update_failure_log': failure,
                'logs': self.state.recorder.files() if self.state.recorder else [],
                'snapshot': self.state.snapshot()}

    def request_update(self, action):
        (self.folder / 'update-request').write_text('rollback' if action == 'rollback' else 'requested', encoding='utf-8')
        # The dash restarts during an update: keep this hotspot and login so the phone page carries on.
        (self.folder / 'hotspot-resume.json').write_text(json.dumps(
            {'until': self.wall() + RESUME_S, 'code': self.code, 'session': self.session}), encoding='utf-8')

    def app(self, allowed_network='10.42.0.0/24'):
        network = ipaddress.ip_network(allowed_network)

        @web.middleware
        async def access(request, handler):
            try:
                permitted = ipaddress.ip_address(request.remote) in network
            except (TypeError, ValueError):
                permitted = False
            if not permitted:
                raise web.HTTPForbidden()
            if request.method not in {'GET', 'HEAD'} and request.headers.get('Origin') != f'{request.scheme}://{request.host}':
                raise web.HTTPForbidden(text='Same-origin requests only')
            public = request.path in {'/', '/transfer.js', '/transfer.css', '/review.js', '/review.css', '/session'}
            cookie = request.cookies.get('frogdash_session', '')
            if not public and not (cookie.isascii() and secrets.compare_digest(cookie, self.session)):
                raise web.HTTPUnauthorized(text='Enter the code shown on the dash')
            response = await handler(request)
            response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
            return response

        app = web.Application(middlewares=[access], client_max_size=1024)

        async def check(request):
            return web.json_response(await asyncio.to_thread(self.check))

        async def diagnostics(request):
            body = json.dumps(await asyncio.to_thread(self.diagnostics), default=str, indent=1)
            name = time.strftime('dash-diagnostics-%Y%m%d-%H%M%S.json', time.gmtime(self.wall()))
            return web.Response(text=body, content_type='application/json',
                                headers={'Content-Disposition': f'attachment; filename="{name}"'})

        async def finish_log(request):
            # Closes the file being recorded so it can be downloaded; recording carries on in a new one.
            if not self.state.recorder:
                raise web.HTTPNotFound(text='Logging is not enabled')
            if not self.state.recorder.finish_current():
                raise web.HTTPServiceUnavailable(text='The recorder is busy; try again')
            return web.json_response({'ok': True})

        async def update(request):
            if not self.folder or self.state.mode == 'replay':
                raise web.HTTPNotFound(text='Updates are not available here')
            if request.method == 'POST':
                # Two fixed actions, the same two as the buttons on the dash.
                try:
                    body = await request.json()
                    action = body.get('action') if isinstance(body, dict) else None
                except (ValueError, TypeError):
                    action = None
                if action not in ('update', 'rollback'):
                    raise web.HTTPBadRequest(text='Expected action: update or rollback')
                await asyncio.to_thread(self.request_update, action)
            return web.json_response(await asyncio.to_thread(self.update_status))

        async def firmware(request):
            # A module's firmware over the CAN bus: the same fixed action as the dash's own button.
            module = getattr(self.state, 'firmware', None)
            if not module:
                raise web.HTTPNotFound(text='Firmware updates are not available here')
            if request.method == 'POST':
                try:
                    body = await request.json()
                    valid = isinstance(body, dict) and body.get('module') == module.name and body.get('action') == 'install'
                except (ValueError, TypeError):
                    valid = False
                if not valid:
                    raise web.HTTPBadRequest(text='Expected module and action: install')
                error = module.start()
                if error:
                    raise web.HTTPConflict(text=error)
            return web.json_response(self.firmware_status())

        async def asset(request):
            return web.FileResponse(TRANSFER_UI / request.match_info.get('name', 'index.html'))

        async def review_asset(request):
            return web.FileResponse(TRANSFER_UI.parent / 'ui' / request.match_info['name'])

        async def login(request):
            now = time.monotonic()
            while self.attempts and self.attempts[0] < now - 60:
                self.attempts.popleft()
            if len(self.attempts) >= 10:
                raise web.HTTPTooManyRequests(text='Wait one minute before retrying')
            self.attempts.append(now)
            try:
                body = await request.json()
                code = body.get('code') if isinstance(body, dict) else None
                valid = isinstance(code, str) and code.isascii() and secrets.compare_digest(code, self.code)
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise web.HTTPUnauthorized(text='Incorrect access code')
            response = web.json_response({'ok': True})
            response.set_cookie('frogdash_session', self.session, httponly=True, samesite='Strict', max_age=1200)
            return response

        async def status(request):
            snapshot = self.state.snapshot()
            return web.json_response({key: snapshot[key] for key in ('transport', 'modules', 'gps', 'recording', 'mode', 'system', 'can_errors')})

        async def drives(request):
            return web.json_response({'drives': await self.state.driving.get_reviews()})

        async def review(request):
            try:
                return web.json_response(await self.state.driving.get_review(request.match_info['name']))
            except (OSError, ValueError, TypeError):
                raise web.HTTPNotFound(text='Drive review unavailable')

        async def logs(request):
            files = await asyncio.to_thread(self.state.recorder.files) if self.state.recorder else []
            return web.json_response({'files': files})

        async def download(request):
            name = request.match_info['name']
            if not self.state.recorder or not NAME.fullmatch(name):
                raise web.HTTPNotFound()
            path = self.state.recorder.config.directory / name
            if path == self.state.recorder.writer.path:
                raise web.HTTPConflict(text='This file is still recording. Download a completed log.')
            if path.is_symlink() or not path.is_file():
                raise web.HTTPNotFound()
            return web.FileResponse(path, headers={'Content-Type': 'application/octet-stream',
                'Content-Disposition': f'attachment; filename="{name}"'})

        app.add_routes([web.get('/', asset), web.get('/{name:transfer\\.js|transfer\\.css}', asset),
                        web.get('/{name:review\\.js|review\\.css}', review_asset),
                        web.post('/session', login), web.get('/api/status', status), web.get('/api/logs', logs),
                        web.get('/api/check', check), web.get('/diagnostics.json', diagnostics),
                        web.post('/api/logs/finish', finish_log), web.get('/api/update', update), web.post('/api/update', update),
                        web.get('/api/firmware', firmware), web.post('/api/firmware', firmware),
                        web.get('/api/drives', drives), web.get('/api/drives/{name}', review),
                        web.get('/logs/{name}', download)])
        return app

    async def start(self):
        # Never bind 0.0.0.0: neither Ethernet nor home Wi-Fi gets this listener.
        runner = web.AppRunner(self.app(), access_log=None, shutdown_timeout=1)
        await runner.setup()
        try:
            await web.TCPSite(runner, ADDRESS, PORT).start()
        except BaseException:
            await runner.cleanup()
            raise
        self.runner = runner

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        self.session = secrets.token_urlsafe(32)


class Connectivity:
    def __init__(self, state, socket_path, folder=None):
        self.state, self.socket_path, self.folder = state, socket_path, folder
        self.status = {'configured': False, 'enabled': False, 'error': None}
        self.client = self.task = self.portal = None
        self.lock = asyncio.Lock()

    async def start(self):
        self.client = aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=str(self.socket_path)),
                                            timeout=aiohttp.ClientTimeout(total=25))
        async def poll():
            while True:
                try:
                    await self.update()
                except (OSError, aiohttp.ClientError, TimeoutError):
                    pass
                await asyncio.sleep(2)
        self.task = asyncio.create_task(poll())

    async def update(self, enabled=None):
        async with self.lock:
            try:
                response = await (self.client.get('http://localhost/status') if enabled is None else
                                  self.client.post('http://localhost/hotspot', json={'enabled': enabled}))
                async with response:
                    response.raise_for_status()
                    status = await response.json()
                if status['enabled'] and not self.portal:
                    portal = TransferPortal(self.state, self.folder)
                    await portal.start()
                    self.portal = portal
                elif not status['enabled'] and self.portal:
                    await self.portal.close()
                    self.portal = None
                self.status = {**status, 'error': None, 'url': f'http://{ADDRESS}:{PORT}',
                               'access_code': self.portal.code if self.portal else ''}
                self.hold_cameras(status.get('enabled') and status.get('shares_camera'))
            except (OSError, aiohttp.ClientError, TimeoutError):
                if self.portal:
                    await self.portal.close()
                    self.portal = None
                self.hold_cameras(False)
                self.status = {'configured': False, 'enabled': False,
                               'error': 'The phone hotspot is not set up yet. Press Update now: the dash sets it up itself '
                                        '(System check > Updates > Phone hotspot shows progress).'}
                raise
            return dict(self.status)

    def hold_cameras(self, held):
        camera = getattr(self.state, 'dashcam', None)
        if camera:
            camera.hold(CAMERAS_OFF if held else None)

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if self.client:
            # An update started from the phone restarts the dash: the hotspot stays up for it.
            if not load_resume(self.folder):
                with suppress(OSError, aiohttp.ClientError, TimeoutError):
                    await self.update(False)
            await self.client.close()
        if self.portal:
            await self.portal.close()
            self.portal = None
