import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.paint import Paint
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

PNG = 'data:image/png;base64,iVBORw0KGgo='


class AppearanceImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_images_survive_on_disk_and_are_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State()
            state.paint = Paint(Path(folder) / 'appearance-paint.json')
            async with TestClient(TestServer(create_app(state))) as client:
                url = '/ui/appearance/image/background'
                self.assertEqual((await client.get(url)).status, 404)
                self.assertEqual((await client.put(url, json={'data': PNG})).status, 204)
                self.assertEqual(await (await client.get(url)).json(), {'data': PNG})
                self.assertTrue((Path(folder) / 'appearance-background.json').exists())
                self.assertEqual((await client.put(url, json={'data': 'javascript:alert(1)'})).status, 400)
                self.assertEqual((await client.put('/ui/appearance/image/other', json={'data': PNG})).status, 404)
                self.assertEqual((await client.delete(url)).status, 204)
                self.assertEqual((await client.get(url)).status, 404)


if __name__ == '__main__':
    unittest.main()


class UpdateRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_button_writes_request_and_reports_status(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State()
            state.paint = Paint(Path(folder) / 'appearance-paint.json')
            async with TestClient(TestServer(create_app(state))) as client:
                status = await (await client.get('/update')).json()
                self.assertEqual((status['state'], status['pending']), ('idle', False))
                self.assertEqual((await client.post('/update')).status, 200)
                self.assertTrue((Path(folder) / 'update-request').exists())
                self.assertTrue((await (await client.get('/update')).json())['pending'])
                (Path(folder) / 'update-request').unlink()
                (Path(folder) / 'update-status.json').write_text('{"state":"updated","message":"Updated (3 changes). Restarting the dash","version":"abc1234","time":1}')
                status = await (await client.get('/update')).json()
                self.assertEqual((status['state'], status['version'], status['pending']), ('updated', 'abc1234', False))
