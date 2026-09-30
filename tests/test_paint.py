"""Appearance snapshot: saved by the service and served inside index.html for the first paint."""
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.paint import Paint, validate
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

GOOD = {'style': '--accent: #ff2bd6; --numeral-font: "DejaVu Sans Mono",Consolas,monospace; --widget-fill: 80%',
        'data': {'gauges': 'cyber', 'instrumentStyle': 'race', 'preset': 'cyberdeck', 'scene': None}, 'splash': True}


class PaintTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'appearance-paint.json'

    async def client(self, paint):
        state = State()
        state.paint = paint
        client = TestClient(TestServer(create_app(state), host='127.0.0.1'))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client

    async def test_saved_look_is_served_in_the_page_and_survives_restart(self):
        client = await self.client(Paint(self.path))
        page = await (await client.get('/')).text()
        self.assertIn('<html lang="en">', page)  # Nothing saved yet: page unchanged.
        self.assertEqual((await client.post('/ui/appearance', json=GOOD)).status, 204)
        # A new service instance reads it back from disk, as after a power cut.
        client = await self.client(Paint(self.path))
        page = await (await client.get('/')).text()
        head = page.split('>', 2)[1]
        self.assertIn('data-gauges="cyber"', head)
        self.assertIn('data-instrument-style="race"', head)
        self.assertIn('data-splash-pending="true"', head)
        self.assertIn('--accent: #ff2bd6', head)
        self.assertIn('&quot;DejaVu Sans Mono&quot;', head)  # Quotes are escaped inside the attribute.
        self.assertNotIn('scene', head)

    async def test_unsafe_snapshots_are_rejected(self):
        client = await self.client(Paint(self.path))
        for style in ('color: red', '--x: url(http://example.com)', '--x: a"><script>alert(1)</script>', '--x: expression(alert(1))'):
            response = await client.post('/ui/appearance', json={**GOOD, 'style': style})
            self.assertEqual(response.status, 400, style)
        for data in ({'bad name': 'x'}, {'gauges': 'a b'}, {'gauges': 5}):
            self.assertEqual((await client.post('/ui/appearance', json={**GOOD, 'data': data})).status, 400, data)
        self.assertEqual((await client.post('/ui/appearance', json={**GOOD, 'extra': 1})).status, 400)
        self.assertFalse(self.path.exists())

    async def test_remote_pages_cannot_set_the_look(self):
        client = await self.client(Paint(self.path))
        response = await client.post('/ui/appearance', json=GOOD, headers={'Origin': 'http://evil.example'})
        self.assertEqual(response.status, 403)
        self.assertFalse(self.path.exists())

    def test_corrupt_file_is_ignored(self):
        self.path.write_text('{not json', encoding='utf-8')
        self.assertIsNone(Paint(self.path).value)
        self.path.write_text('{"style": "color: red", "data": {}, "splash": false}', encoding='utf-8')
        self.assertIsNone(Paint(self.path).value)

    def test_validate_drops_empty_values(self):
        self.assertEqual(validate(GOOD)['data'], {'gauges': 'cyber', 'instrumentStyle': 'race', 'preset': 'cyberdeck'})


if __name__ == '__main__':
    unittest.main()
