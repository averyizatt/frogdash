"""Local hotspot control and a separate, authenticated log/status transfer site."""
import asyncio
from collections import deque
from contextlib import suppress
import ipaddress
from pathlib import Path
import secrets
import time

import aiohttp
from aiohttp import web

from .hotspot_helper import ADDRESS, PORT
from .recorder import NAME

TRANSFER_UI = Path(__file__).resolve().parents[1] / 'transfer'


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
    def __init__(self, state):
        self.state = state
        self.code = f'{secrets.randbelow(100_000_000):08d}'
        self.session = secrets.token_urlsafe(32)
        self.attempts = deque(maxlen=10)
        self.runner = None

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
            public = request.path in {'/', '/transfer.js', '/transfer.css', '/session'}
            cookie = request.cookies.get('frogdash_session', '')
            if not public and not (cookie.isascii() and secrets.compare_digest(cookie, self.session)):
                raise web.HTTPUnauthorized(text='Enter the code shown on the dash')
            response = await handler(request)
            response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
            return response

        app = web.Application(middlewares=[access], client_max_size=1024)

        async def asset(request):
            return web.FileResponse(TRANSFER_UI / request.match_info.get('name', 'index.html'))

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
            return web.json_response({key: snapshot[key] for key in ('transport', 'modules', 'gps', 'recording', 'mode')})

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
                        web.post('/session', login), web.get('/api/status', status), web.get('/api/logs', logs),
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
    def __init__(self, state, socket_path):
        self.state, self.socket_path = state, socket_path
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
                    portal = TransferPortal(self.state)
                    await portal.start()
                    self.portal = portal
                elif not status['enabled'] and self.portal:
                    await self.portal.close()
                    self.portal = None
                self.status = {**status, 'error': None, 'url': f'http://{ADDRESS}:{PORT}',
                               'access_code': self.portal.code if self.portal else ''}
            except (OSError, aiohttp.ClientError, TimeoutError):
                if self.portal:
                    await self.portal.close()
                    self.portal = None
                self.status = {'configured': False, 'enabled': False,
                               'error': 'Wi-Fi helper or transfer page unavailable. Check Pi hotspot setup and service journal.'}
                raise
            return dict(self.status)

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if self.client:
            with suppress(OSError, aiohttp.ClientError, TimeoutError):
                await self.update(False)
            await self.client.close()
        if self.portal:
            await self.portal.close()
            self.portal = None
