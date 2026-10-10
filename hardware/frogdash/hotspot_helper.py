"""Privileged, Unix-socket-only broker for ONE preconfigured NetworkManager AP.

No arbitrary commands, interface names, file paths or network settings are accepted.
The dashboard remains unprivileged. Provision with tools/setup_hotspot.py on the Pi.
"""
import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import time
from uuid import UUID

from aiohttp import web

ADDRESS = '10.42.0.1'
PORT = 8081
LIFETIME = 20 * 60
# While this file is fresh the Wi-Fi keeper leaves the dash cam's adapter alone
# (tools/frogdash_netkeeper.sh). It lives in this service's own runtime directory.
LOCK = Path('/run/frogdash-connect/hotspot.lock')
CAMERA_PROFILE = 'dashcam'


async def nmcli(*arguments):
    process = await asyncio.create_subprocess_exec('/usr/bin/nmcli', '--wait', '15', *arguments,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env={**os.environ, 'LC_ALL': 'C'})
    try:
        out, _ = await asyncio.wait_for(process.communicate(), 20)
    except (TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise OSError('NetworkManager could not complete the hotspot command; check its journal and Wi-Fi adapter.')
    return out.decode().strip()


class Hotspot:
    def __init__(self, config, run=nmcli, clock=time.monotonic, adapter_lock=LOCK):
        self.uuid = str(UUID(config['uuid']))
        self.ssid, self.password = config['ssid'], config['password']
        self.run, self.clock, self.adapter_lock = run, clock, adapter_lock
        self.deadline = 0
        self.enabled = False
        self.shared = False   # The hotspot is on the adapter the dash cam uses
        self.lock = asyncio.Lock()

    async def shares_camera(self):
        """True when the hotspot and the dash cam are set up on the same Wi-Fi adapter."""
        try:
            mine = await self.run('-g', 'connection.interface-name', 'connection', 'show', 'uuid', self.uuid)
            camera = await self.run('-g', 'connection.interface-name', 'connection', 'show', 'id', CAMERA_PROFILE)
        except OSError:
            return False  # No dash cam profile.
        return bool(mine) and mine == camera

    def hold_adapter(self, held):
        try:
            if held:
                self.adapter_lock.touch()
            else:
                self.adapter_lock.unlink(missing_ok=True)
        except OSError:
            pass

    async def active(self):
        output = await self.run('-t', '-f', 'UUID', 'connection', 'show', '--active')
        return self.uuid in output.splitlines()

    async def disable(self):
        # Keep the deadline until down succeeds: watchdog must retry after errors.
        if await self.active():
            await self.run('connection', 'down', 'uuid', self.uuid)
        self.enabled, self.deadline = False, 0
        if self.shared:
            # Hand the adapter back: the Wi-Fi keeper and NetworkManager rejoin the dash cam.
            self.hold_adapter(False)
            self.shared = False

    async def set_enabled(self, enabled):
        async with self.lock:
            if enabled:
                # Mark the lease before activation so failed/partial activation
                # is still shut down by the watchdog.
                self.deadline = self.clock() + LIFETIME
                # The hotspot has priority: with one adapter the cameras are off while it is on.
                self.shared = await self.shares_camera()
                if self.shared:
                    self.hold_adapter(True)
                    with suppress(OSError):
                        await self.run('connection', 'down', 'id', CAMERA_PROFILE)
                await self.run('connection', 'up', 'uuid', self.uuid)
                self.enabled = await self.active()
                if not self.enabled:
                    raise OSError('Hotspot activation did not complete')
            else:
                await self.disable()
            return self.status()

    def status(self):
        return {'configured': True, 'enabled': self.enabled, 'ssid': self.ssid,
                'password': self.password if self.enabled else '', 'address': ADDRESS, 'port': PORT,
                'shares_camera': self.enabled and self.shared,
                'remaining_seconds': max(0, int(self.deadline - self.clock())) if self.enabled else 0}

    async def refresh(self):
        async with self.lock:
            active = await self.active()
            if active and (not self.deadline or self.clock() >= self.deadline):
                await self.disable()
            else:
                self.enabled = active
                if active and self.shared:
                    self.hold_adapter(True)   # Kept fresh: a stale lock is ignored after 5 minutes.


def create_helper(hotspot):
    app = web.Application(client_max_size=1024)

    async def status(request):
        try:
            await hotspot.refresh()
            return web.json_response(hotspot.status())
        except (OSError, TimeoutError):
            raise web.HTTPServiceUnavailable(text='NetworkManager unavailable')

    async def toggle(request):
        try:
            message = await request.json()
            if not isinstance(message, dict) or set(message) != {'enabled'} or type(message['enabled']) is not bool:
                raise ValueError('Expected enabled: true or false')
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text='Expected enabled: true or false')
        try:
            return web.json_response(await hotspot.set_enabled(message['enabled']))
        except (OSError, TimeoutError):
            raise web.HTTPServiceUnavailable(text='Hotspot command failed; check NetworkManager')

    async def lifecycle(app):
        # Never resume an AP left behind by a crash or an earlier boot.
        await hotspot.set_enabled(False)
        async def watchdog():
            while True:
                await asyncio.sleep(2)
                with suppress(OSError, TimeoutError):
                    await hotspot.refresh()
        task = asyncio.create_task(watchdog())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        with suppress(OSError, TimeoutError):
            await hotspot.set_enabled(False)

    app.cleanup_ctx.append(lifecycle)
    app.add_routes([web.get('/status', status), web.post('/hotspot', toggle)])
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('/etc/frogdash/hotspot.json'))
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    # systemd owns the parent directory; Unix socket permissions are the boundary.
    os.umask(0o117)
    web.run_app(create_helper(Hotspot(config)), path='/run/frogdash-connect/control.sock',
                access_log=None, print=None)


if __name__ == '__main__':
    main()
