import os
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State


class TerminalTests(unittest.IsolatedAsyncioTestCase):
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
    async def test_runs_a_command_and_reports_exit_code(self):
        state = State()
        state.terminal_enabled = True
        async with TestClient(TestServer(create_app(state))) as client:
            result = await (await client.post('/terminal', json={'command': 'echo hello; exit 3'})).json()
            self.assertEqual((result['output'].strip(), result['exit']), ('hello', 3))


if __name__ == '__main__':
    unittest.main()
