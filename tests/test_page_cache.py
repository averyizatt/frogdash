"""The browser keeps the page's scripts and styles (and Chromium the compiled code of the
scripts) between starts, but asks the dash each time, so an update is seen at once. The
page itself, which carries the saved look, is never kept."""
import unittest

from aiohttp.test_utils import TestClient, TestServer

from hardware.frogdash.server import create_app
from hardware.frogdash.state import State


class PageCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_scripts_are_kept_and_checked_the_page_is_not_kept(self):
        async with TestClient(TestServer(create_app(State()))) as client:
            first = await client.get('/app.js')
            self.assertEqual(first.status, 200)
            self.assertEqual(first.headers['Cache-Control'], 'no-cache')
            tag = first.headers.get('ETag')
            self.assertTrue(tag)
            again = await client.get('/app.js', headers={'If-None-Match': tag})
            self.assertEqual(again.status, 304)                      # Unchanged: the kept copy and its compiled code
            for name in ('later.js', 'style.css', 'graphs.js'):
                self.assertEqual((await client.get('/' + name)).headers['Cache-Control'], 'no-cache', name)
            self.assertEqual((await client.get('/')).headers['Cache-Control'], 'no-store')

    async def test_photo_faces_are_served_and_nothing_else_from_there(self):
        async with TestClient(TestServer(create_app(State()))) as client:
            self.assertEqual((await client.get('/skins.js')).status, 200)
            face = await client.get('/skins/ferrari.jpg')
            self.assertEqual((face.status, face.content_type), (200, 'image/jpeg'))
            self.assertGreater(len(await face.read()), 50_000)
            for name in ('ferrari-lamps.jpg', 'fox.jpg', 'saleen.jpg'):
                self.assertEqual((await client.get('/skins/' + name)).status, 200, name)
            for name in ('missing.jpg', '..%2Fskins.js', 'ferrari.JPG', 'ferrari.jpg.bak'):
                self.assertEqual((await client.get('/skins/' + name)).status, 404, name)

    async def test_the_reports_get_the_live_picture_and_the_pages_own_timing(self):
        async with TestClient(TestServer(create_app(State()))) as client:
            snapshot = await (await client.get('/snapshot')).json()
            for part in ('modules', 'transport', 'faults', 'updating', 'gps', 'firmware'):
                self.assertIn(part, snapshot)
            token = 'a' * 32
            sent = await client.post(f'/ui/heartbeat/{token}', json={'display': {'viewport': [1920, 720], 'first_frame_ms': 812,
                                                                                'others_loaded_ms': 4930}})
            self.assertEqual(sent.status, 200)
            shown = await (await client.get('/ui/display')).json()
            self.assertEqual((shown['first_frame_ms'], shown['others_loaded_ms']), (812, 4930))


if __name__ == '__main__':
    unittest.main()
