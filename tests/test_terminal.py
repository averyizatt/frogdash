"""The Terminal tab's helper (tools/frogdash_terminal.py): one command, as the screen user,
so sudo works as at the keyboard. runuser is replaced by a stand-in that runs the command
as the user running the tests; everything else is the helper's own code."""
import getpass
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
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


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_tab_learns_whether_sudo_works(self):
        state = State()
        state.terminal_enabled = True
        async with TestClient(TestServer(create_app(state))) as client:
            body = await (await client.get('/terminal')).json()
            self.assertEqual(body, {'enabled': True, 'sudo': False})     # No helper socket here


if __name__ == '__main__':
    unittest.main()
