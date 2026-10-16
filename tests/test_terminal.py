"""The Terminal tab's helper (tools/frogdash_terminal.py): one command, as the screen user,
so sudo works as at the keyboard. runuser is replaced by a stand-in that runs the command
as the user running the tests; everything else is the helper's own code."""
import asyncio
import getpass
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash import server
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saved = dict(os.environ)
        base = Path(self.folder.name)
        self.units = base / 'units'
        (self.units / 'multi-user.target.wants').mkdir(parents=True)
        os.environ['FROGDASH_UNITS'] = str(self.units)
        runuser = base / 'runuser'
        runuser.write_text('#!/bin/sh\n# runuser -u USER -- command...\nshift 3\nexec "$@"\n', newline='\n')
        runuser.chmod(0o755)
        os.environ['FROGDASH_RUNUSER'] = str(runuser)
        import importlib
        import frogdash_terminal
        self.t = importlib.reload(frogdash_terminal)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        self.folder.cleanup()

    def test_it_says_what_is_wrong_with_a_bad_request_or_no_screen_user(self):
        self.assertIn('Expected one command', self.t.handle(b'not json')['output'])
        self.assertIn('Expected one command', self.t.handle(json.dumps({'command': '  '}).encode())['output'])
        self.assertIn('not installed', self.t.handle(json.dumps({'command': 'id'}).encode())['output'])

    @unittest.skipUnless(os.name == 'posix', 'runs commands through /bin/bash as a Unix user')
    def test_a_command_runs_as_the_screen_user_and_a_slow_one_is_stopped(self):
        me = getpass.getuser()
        (self.units / f'multi-user.target.wants/frogdash-console@{me}.service').write_text('')
        answer = self.t.handle(json.dumps({'command': 'echo hello; whoami; exit 3'}).encode())
        self.assertEqual((answer['exit'], answer['output'], answer['user']), (3, f'hello\n{me}\n', me))
        code, text = self.t.run('echo started; sleep 30', me, timeout=1)
        self.assertEqual(code, 124)
        self.assertIn('started', text)
        self.assertIn('[stopped after 1 s]', text)


    @unittest.skipUnless(os.name == 'posix', 'a pty is Unix only')
    def test_a_session_waits_for_input_and_ends_with_the_shell(self):
        me = getpass.getuser()
        dash, helper = socket.socketpair()
        worker = threading.Thread(target=self.t.session, args=(me, helper.fileno(), helper.fileno()), daemon=True)
        worker.start()
        seen = b''

        def until(text, timeout=10):
            nonlocal seen
            dash.settimeout(timeout)
            deadline = time.monotonic() + timeout
            while text.encode() not in seen and time.monotonic() < deadline:
                seen += dash.recv(4096)
            return text.encode() in seen
        # A prompt that waits for an answer, as nmcli --ask or sudo would.
        dash.sendall(b'read -p "Password: " answer; echo "got-$answer"\n')
        self.assertTrue(until('Password: '))
        dash.sendall(b'hunter2\n')
        self.assertTrue(until('got-hunter2'))
        dash.sendall(b'exit\n')
        self.assertTrue(until('[the shell has ended]'))
        worker.join(10)
        self.assertFalse(worker.is_alive())


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.name == 'posix', 'Unix sockets')
    async def test_the_page_and_the_helper_are_joined_both_ways(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'terminal.sock'
            received = []

            async def fake_helper(reader, writer):
                received.append(await reader.readline())         # {"mode": "session"}
                writer.write('welcome é\r\n'.encode())
                await writer.drain()
                received.append(await reader.read(100))
                writer.write(b'done\r\n')
                await writer.drain()
                writer.close()
            helper = await asyncio.start_unix_server(fake_helper, path=str(path))
            state = State()
            state.terminal_enabled = True
            with mock.patch.object(server, 'TERMINAL_SOCKET', path):
                async with TestClient(TestServer(create_app(state))) as client:
                    self.assertTrue((await (await client.get('/terminal')).json())['sudo'])
                    ws = await client.ws_connect('/terminal/session')
                    self.assertEqual(await ws.receive_str(timeout=5), 'welcome é\r\n')
                    await ws.send_str('ls\n')
                    self.assertEqual(await ws.receive_str(timeout=5), 'done\r\n')
                    await ws.close()
            helper.close()
            self.assertEqual(json.loads(received[0]), {'mode': 'session'})
            self.assertEqual(received[1], b'ls\n')

    async def test_without_the_helper_there_is_no_live_session(self):
        state = State()
        state.terminal_enabled = True
        async with TestClient(TestServer(create_app(state))) as client:
            self.assertEqual((await client.get('/terminal/session')).status, 404)

    async def test_health_says_whether_the_engine_is_running(self):
        state = State()
        async with TestClient(TestServer(create_app(state))) as client:
            self.assertFalse((await (await client.get('/health')).json())['engine_running'])
            state.ingest(0x5E8, bytes.fromhex('07080D7A080201F4'))      # MicroSquirt: 3450 RPM
            self.assertTrue((await (await client.get('/health')).json())['engine_running'])

    async def test_off_by_default_and_input_is_validated(self):
        state = State()
        async with TestClient(TestServer(create_app(state))) as client:
            self.assertEqual((await client.get('/terminal')).status, 404)
            self.assertEqual((await client.post('/terminal', json={'command': 'echo hi'})).status, 404)
            state.terminal_enabled = True
            self.assertEqual((await client.get('/terminal')).status, 200)
            for bad in ({}, {'command': ''}, {'command': 5}, {'command': 'x' * 2001}):
                self.assertEqual((await client.post('/terminal', json=bad)).status, 400)

    @unittest.skipUnless(os.path.exists('/bin/bash'), 'needs bash')
    async def test_without_the_helper_it_runs_restricted_and_reports_the_exit_code(self):
        state = State()
        state.terminal_enabled = True
        async with TestClient(TestServer(create_app(state))) as client:
            result = await (await client.post('/terminal', json={'command': 'echo hello; exit 3'})).json()
            self.assertEqual((result['output'].strip(), result['exit']), ('hello', 3))

    async def test_the_tab_learns_whether_sudo_works(self):
        state = State()
        state.terminal_enabled = True
        async with TestClient(TestServer(create_app(state))) as client:
            body = await (await client.get('/terminal')).json()
            self.assertEqual(body, {'enabled': True, 'sudo': False})     # No helper socket here


if __name__ == '__main__':
    unittest.main()
