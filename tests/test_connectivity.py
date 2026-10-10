import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import CookieJar, ClientSession, UnixConnector, web
from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.connectivity import Connectivity, RESUME_S, TransferPortal, load_resume
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

    async def test_phone_sees_faults_downloads_diagnostics_and_finishes_the_current_log(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'update-status.json').write_text(json.dumps({'state': 'rolledback', 'message': 'Update undone', 'version': 'abc1234', 'previous': ''}))
            (folder / 'update-failure.log').write_text('Traceback: the new version crashed\n')
            (folder / 'setup-status.json').write_text(json.dumps({'stamp': 'x', 'running': False, 'steps': [{'name': 'Phone hotspot', 'result': 'ok', 'detail': 'Ready'}]}))
            state = State()
            state.recorder = Recorder(state, Config(folder / 'logs', free_bytes=0))
            state.recorder.start()
            portal = TransferPortal(state, folder)
            async with TestClient(TestServer(portal.app('127.0.0.0/8')), cookie_jar=CookieJar(unsafe=True)) as client:
                origin = str(client.make_url('/')).rstrip('/')
                for path in ('/api/check', '/diagnostics.json', '/api/update'):
                    self.assertEqual((await client.get(path)).status, 401, path)         # Nothing without the dash code.
                self.assertEqual((await client.post('/api/logs/finish', headers={'Origin': origin})).status, 401)
                self.assertEqual((await client.post('/api/update', json={'action': 'update'}, headers={'Origin': origin})).status, 401)
                await client.post('/session', json={'code': portal.code}, headers={'Origin': origin})

                check = await (await client.get('/api/check')).json()
                lines = {line['name']: line for line in check['report']['lines']}
                self.assertEqual(lines['Last update']['status'], 'warn')                 # The same system check the dash shows.
                self.assertEqual(check['update']['state'], 'rolledback')
                self.assertGreater(check['report']['counts']['fail'] + check['report']['counts']['warn'], 0)

                response = await client.get('/diagnostics.json')
                self.assertIn('attachment; filename="dash-diagnostics-', response.headers['Content-Disposition'])
                bundle = json.loads(await response.text())
                self.assertEqual(bundle['format'], 'dash-diagnostics')
                self.assertIn('Traceback', bundle['update_failure_log'])
                self.assertEqual(bundle['helpers']['setup-status.json']['steps'][0]['name'], 'Phone hotspot')
                self.assertIsNone(bundle['helpers']['gps-status.json'])                  # Not written yet: present and empty.
                self.assertIn('values', bundle['snapshot'])
                self.assertEqual(len(bundle['check']['lines']), len(check['report']['lines']))
                self.assertNotIn(portal.code, await response.text())                    # No credentials in the file.
                self.assertNotIn(portal.session, await response.text())

                # The log being recorded cannot be downloaded until it is finished from the phone.
                for _ in range(100):
                    files = (await (await client.get('/api/logs')).json())['files']
                    if files and files[0]['active']:
                        break
                    await asyncio.sleep(.05)
                current = files[0]['name']
                self.assertEqual((await client.get('/logs/' + current)).status, 409)
                self.assertEqual((await client.post('/api/logs/finish')).status, 403)    # Same-origin only.
                self.assertEqual((await client.post('/api/logs/finish', headers={'Origin': origin})).status, 200)
                for _ in range(100):
                    response = await client.get('/logs/' + current)
                    if response.status == 200:
                        break
                    await asyncio.sleep(.05)
                self.assertTrue(list(Reader(io.BytesIO(await response.read())).records()))
                for _ in range(100):                                                     # Recording carried on in a new file.
                    files = (await (await client.get('/api/logs')).json())['files']
                    if len(files) == 2 and files[0]['active']:
                        break
                    await asyncio.sleep(.05)
                self.assertEqual((len(files), files[0]['active'], files[1]['name']), (2, True, current))
            await state.recorder.close()

    async def test_phone_can_start_an_update_and_keeps_its_login_through_the_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            now = [1_000_000.0]
            portal = TransferPortal(State(), folder, wall=lambda: now[0])
            async with TestClient(TestServer(portal.app('127.0.0.0/8')), cookie_jar=CookieJar(unsafe=True)) as client:
                origin = str(client.make_url('/')).rstrip('/')
                await client.post('/session', json={'code': portal.code}, headers={'Origin': origin})
                self.assertEqual((await (await client.get('/api/update')).json())['state'], 'idle')
                for bad in ({'action': 'reboot'}, {'action': 'helpers'}, {'action': ['update']}, {}, 'update'):
                    self.assertEqual((await client.post('/api/update', json=bad, headers={'Origin': origin})).status, 400, bad)
                self.assertFalse((folder / 'update-request').exists())                   # Only the two fixed actions exist.
                self.assertEqual((await client.post('/api/update', json={'action': 'update'})).status, 403)
                status = await (await client.post('/api/update', json={'action': 'update'}, headers={'Origin': origin})).json()
                self.assertTrue(status['pending'])
                self.assertEqual((folder / 'update-request').read_text(), 'requested')
                await client.post('/api/update', json={'action': 'rollback'}, headers={'Origin': origin})
                self.assertEqual((folder / 'update-request').read_text(), 'rollback')
            # The dash restarts: the new portal takes over the same code and login, so the page carries on.
            now[0] += 120
            again = TransferPortal(State(), folder, wall=lambda: now[0])
            self.assertEqual((again.code, again.session), (portal.code, portal.session))
            self.assertIsNotNone(load_resume(folder, lambda: now[0]))
            # ...but only for a while, and never from a file that claims too much.
            now[0] += RESUME_S
            later = TransferPortal(State(), folder, wall=lambda: now[0])
            self.assertNotEqual(later.session, portal.session)
            (folder / 'hotspot-resume.json').write_text(json.dumps({'until': now[0] + 10 * RESUME_S, 'code': '1', 'session': 'x'}))
            self.assertIsNone(load_resume(folder, lambda: now[0]))
            (folder / 'hotspot-resume.json').write_text('not json')
            self.assertIsNone(load_resume(folder, lambda: now[0]))
        # Without a data folder (replay, tests) there is nothing to update.
        async with TestClient(TestServer(TransferPortal(State()).app('127.0.0.0/8')), cookie_jar=CookieJar(unsafe=True)) as client:
            self.assertEqual((await client.get('/api/update')).status, 401)

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
