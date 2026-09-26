import asyncio
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import CookieJar, ClientSession, UnixConnector, web
from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.connectivity import Connectivity, TransferPortal
from hardware.frogdash.hotspot_helper import Hotspot, create_helper, LIFETIME
from hardware.frogdash.recorder import Recorder, Config
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from tools.inspect_mlg import Reader
from tools.mcp2515_config import overlay
from tools.setup_hotspot import profile

UUID = 'd19bc877-cb2b-4a99-90c7-cd827377bda8'


class Network:
    def __init__(self):
        self.enabled = False
        self.calls = []
        self.fail_down = False

    async def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ('connection', 'up'):
            self.enabled = True
        elif args[:2] == ('connection', 'down'):
            if self.fail_down:
                raise OSError('busy')
            self.enabled = False
        return UUID if self.enabled else ''


class SetupTests(unittest.TestCase):
    def test_requires_real_oscillator_and_free_interrupt(self):
        self.assertIn('oscillator=8000000,interrupt=25', overlay(8000000))
        self.assertIn('mcp2515-can1', overlay(16000000, 24, 1))
        with self.assertRaises(ValueError): overlay(0)
        with self.assertRaises(ValueError): overlay(8000000, 11)

    def test_protected_profile_never_autoconnects(self):
        config = profile(UUID, 'wlan0', 'Frogdash', 'a' * 20)
        for setting in ('autoconnect=false', 'mode=ap', 'hidden=false', 'key-mgmt=wpa-psk', 'proto=rsn;', 'address1=10.42.0.1/24'):
            self.assertIn(setting, config)
        with self.assertRaises(ValueError): profile(UUID, 'wlan0;reboot', 'Frogdash', 'a' * 20)
        with self.assertRaises(ValueError): profile(UUID, 'wlan0', 'a\n[ipv4]', 'a' * 20)


class ConnectivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_helper_timeout_shutdown_and_allowlisted_commands(self):
        network = Network()
        clock = [0]
        hotspot = Hotspot({'uuid': UUID, 'ssid': 'Frogdash', 'password': 'a' * 20}, network, lambda: clock[0])
        async with TestClient(TestServer(create_helper(hotspot))) as client:
            self.assertFalse((await (await client.get('/status')).json())['enabled'])
            for body in ({'enabled': 'yes'}, {'enabled': True, 'command': 'reboot'}, []):
                self.assertEqual((await client.post('/hotspot', json=body)).status, 400)
            response = await client.post('/hotspot', json={'enabled': True})
            self.assertTrue((await response.json())['enabled'])
            clock[0] = LIFETIME + 1
            network.fail_down = True
            self.assertEqual((await client.get('/status')).status, 503)
            self.assertGreater(hotspot.deadline, 0)
            network.fail_down = False
            self.assertFalse((await (await client.get('/status')).json())['enabled'])
            await client.post('/hotspot', json={'enabled': True})
        self.assertFalse(network.enabled)
        mutations = [c for c in network.calls if c[0] == 'connection']
        self.assertTrue(all(c in [('connection', 'up', 'uuid', UUID), ('connection', 'down', 'uuid', UUID)] for c in mutations))

    async def test_helper_restart_turns_off_leftover_profile(self):
        network = Network()
        network.enabled = True
        hotspot = Hotspot({'uuid': UUID, 'ssid': 'Frogdash', 'password': 'a' * 20}, network)
        async with TestClient(TestServer(create_helper(hotspot))):
            self.assertFalse(network.enabled)

    async def test_remote_portal_auth_download_and_no_vehicle_control_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State()
            state.recorder = Recorder(state, Config(Path(directory), free_bytes=0))
            writer = state.recorder.writer
            writer.write(state.snapshot(), 0)
            filename = writer.path.name
            portal = TransferPortal(state)
            async with TestClient(TestServer(portal.app('127.0.0.0/8')), cookie_jar=CookieJar(unsafe=True)) as client:
                origin = str(client.make_url('/')).rstrip('/')
                self.assertEqual((await client.get('/')).status, 200)
                self.assertEqual((await client.get('/transfer.js')).status, 200)
                self.assertEqual((await client.get('/api/logs')).status, 401)
                self.assertEqual((await client.get('/logs/' + filename)).status, 401)
                self.assertEqual((await client.post('/session', json={'code': portal.code}, headers={'Origin': 'http://elsewhere'})).status, 403)
                self.assertEqual((await client.post('/session', json={'code': '000'}, headers={'Origin': origin})).status, 401)
                response = await client.post('/session', json={'code': portal.code}, headers={'Origin': origin})
                self.assertEqual(response.status, 200)
                self.assertIn('HttpOnly', response.headers['Set-Cookie'])
                self.assertEqual((await client.get('/logs/' + filename)).status, 409)
                writer.finish_file()
                response = await client.get('/logs/' + filename)
                self.assertTrue(list(Reader(io.BytesIO(await response.read())).records()))
                self.assertEqual((await client.get('/state')).status, 404)
                self.assertEqual((await client.post('/connectivity', json={'enabled': True}, headers={'Origin': origin})).status, 404)
                self.assertEqual((await client.get('/logs/nope.mlg')).status, 404)
                status = await (await client.get('/api/status')).json()
                self.assertNotIn('controls', status)
                await portal.close()
                self.assertEqual((await client.get('/api/logs')).status, 401)
            writer.close()

    async def test_portal_limits_guesses_and_rejects_other_networks(self):
        portal = TransferPortal(State())
        async with TestClient(TestServer(portal.app('127.0.0.0/8'))) as client:
            origin = str(client.make_url('/')).rstrip('/')
            for _ in range(10):
                self.assertEqual((await client.post('/session', json={'code': 'wrong'}, headers={'Origin': origin})).status, 401)
            self.assertEqual((await client.post('/session', json={'code': portal.code}, headers={'Origin': origin})).status, 429)
        async with TestClient(TestServer(portal.app())) as client:
            self.assertEqual((await client.get('/')).status, 403)

    async def test_dashboard_toggle_requires_local_origin_and_boolean(self):
        connectivity = AsyncMock()
        connectivity.status = {'configured': True, 'enabled': False}
        connectivity.update.return_value = {'configured': True, 'enabled': True}
        app = create_app(State(), connectivity=connectivity)
        async with TestClient(TestServer(app)) as client:
            self.assertEqual((await client.post('/connectivity', json={'enabled': True}, headers={'Origin': 'http://bad.invalid'})).status, 403)
            self.assertEqual((await client.post('/connectivity', json={'enabled': True}, headers={'Host': 'bad.invalid'})).status, 403)
            self.assertEqual((await client.post('/connectivity', json={'enabled': 1})).status, 400)
            self.assertEqual((await client.post('/connectivity', json={'enabled': True})).status, 200)
            connectivity.update.assert_awaited_once_with(True)

    @unittest.skipIf(__import__('os').name == 'nt', 'Unix socket broker integration runs on Linux')
    async def test_unix_broker_controls_portal_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            hotspot = Hotspot({'uuid': UUID, 'ssid': 'Frogdash', 'password': 'a' * 20}, Network())
            runner = web.AppRunner(create_helper(hotspot))
            await runner.setup()
            path = Path(directory) / 'helper.sock'
            await web.UnixSite(runner, str(path)).start()
            connect = Connectivity(State(), path)
            with patch.object(TransferPortal, 'start', new_callable=AsyncMock):
                await connect.start()
                status = await connect.update(True)
                self.assertTrue(status['enabled'])
                self.assertEqual(len(status['access_code']), 8)
                await connect.update(False)
                self.assertIsNone(connect.portal)
                await connect.close()
            await runner.cleanup()


if __name__ == '__main__':
    unittest.main()
