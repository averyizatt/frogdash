"""The rescue screen (tools/frogdash_rescue.py): what it shows when the dash is down, the
actions behind its buttons, and that nothing but its own page can use them."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from tools import frogdash_rescue as rescue_module
from tools.frogdash_rescue import Rescue, handler


class Runner:
    """systemctl, git and journalctl, recorded; git answers as a checkout at 'bad1234'."""
    def __init__(self):
        self.calls = []

    def __call__(self, *command, timeout=30):
        self.calls.append(' '.join(command))
        if command[0] == 'git' and 'rev-parse' in command:
            return 0, 'bad1234' if command[-1] == 'HEAD' else command[-1][:7]
        if command[0] == 'git' and command[3] == 'log':
            return 0, 'bad1234 20 Oct 14:02 Live graphs with uPlot'
        if command[:2] == ('systemctl', 'is-active') and 'frogdash.service' in command:
            return 3, 'activating'
        if command[0] == 'systemctl' and '--quiet' in command:
            return 3, ''
        if command[0] == 'journalctl':
            return 0, "ModuleNotFoundError: No module named 'pyubx2'"
        return 0, ''


class RescueTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.state = Path(self.folder.name)
        patcher = patch.multiple(rescue_module, STATE=self.state, BUSY=self.state / 'busy', UNITS=self.state / 'units',
                                 REPO=self.state / 'repo')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)
        self.runner = Runner()
        self.rescue = Rescue(runner=self.runner, port=1)   # Nothing answers on port 1: the dash is down
        self.rescue.internet = lambda: False

    def wait(self):
        for _ in range(100):
            if self.rescue.action['state'] != 'running':
                return self.rescue.action
            time.sleep(.02)
        self.fail('the action did not finish')

    def test_it_says_why_the_dash_is_down_and_what_can_be_done(self):
        (self.state / 'last-good').write_text('good5678\n')
        state = self.rescue.state()
        self.assertFalse(state['answering'])
        self.assertEqual(state['service'], 'activating')
        self.assertIn('pyubx2', state['journal'])
        self.assertEqual((state['good'], state['previous'], state['internet']), ('good567', '', False))
        self.assertTrue(state['actions']['good']['available'])
        self.assertFalse(state['actions']['previous']['available'])          # No update to undo is saved
        self.assertEqual(self.rescue.start('previous'), 'There is no earlier version saved to go back to')
        self.assertEqual(self.rescue.start('erase'), 'Unknown action')

    def test_going_back_to_the_version_that_ran(self):
        (self.state / 'last-good').write_text('good5678\n')
        self.assertIsNone(self.rescue.start('good'))
        action = self.wait()
        self.assertEqual(action['state'], 'done', action)
        self.assertIn('git -C', next(c for c in self.runner.calls if 'reset --keep' in c))
        self.assertIn('systemctl restart frogdash.service', self.runner.calls)
        self.assertEqual((self.state / 'update-bad').read_text().strip(), 'bad1234')
        self.assertFalse((self.state / 'busy').exists())

    def test_the_updater_actions_are_its_request_words(self):
        for action, word in (('update', 'requested'), ('setup', 'setup')):
            self.assertIsNone(self.rescue.start(action))
            self.wait()
            self.assertEqual((self.state / 'update-request').read_text(), word)
        (self.state / 'update-previous').write_text('prev9999')
        self.assertIsNone(self.rescue.start('previous'))
        self.wait()
        self.assertEqual((self.state / 'update-request').read_text(), 'rollback')
        self.assertIsNone(self.rescue.start('restart'))
        self.assertEqual(self.wait()['state'], 'done')

    def test_only_its_own_page_can_act(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.rescue, 0))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        port = server.server_address[1]

        def ask(method, path, headers=None, body=None):
            link = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            link.request(method, path, body=body, headers=headers or {})
            answer = link.getresponse()
            return answer.status, answer.read()

        status, page = ask('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'The dash is not running', page)
        self.assertEqual(ask('GET', '/state')[0], 404)                                         # Not without its header
        self.assertEqual(json.loads(ask('GET', '/state', {'X-Frogdash-Rescue': '1'})[1])['service'], 'activating')
        body = json.dumps({'action': 'restart'})
        self.assertEqual(ask('POST', '/act', {'Content-Type': 'text/plain'}, body)[0], 403)    # Another page's plain form
        self.assertEqual(ask('POST', '/act', {'X-Frogdash-Rescue': '1', 'Host': 'evil.example'}, body)[0], 403)
        self.assertEqual(ask('POST', '/act', {'X-Frogdash-Rescue': '1'}, body)[0], 200)


if __name__ == '__main__':
    unittest.main()
