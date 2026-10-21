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


if __name__ == '__main__':
    unittest.main()
