import asyncio
import io
import threading
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.dashcam import Dashcam, ffmpeg_command, open_dashcam, split_jpegs
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

JPEG = b'\xff\xd8' + b'\x01\xff\x00\x02' + b'\xff\xd9'


class FakeProcess:
    def __init__(self, data):
        self.stdout, self.stderr = io.BytesIO(data), io.BytesIO(b'connection closed')
        self.terminated = False
    def terminate(self): self.terminated = True
    def wait(self, timeout=None): return 0
    def kill(self): pass


class FakeSocket:
    def __init__(self): self.closed = False
    def settimeout(self, t): pass
    def recv(self, n): raise OSError('timed out')
    def close(self): self.closed = True


class DashcamTests(unittest.TestCase):
    def test_split_jpegs_keeps_partial_frames(self):
        frames, rest = split_jpegs(b'junk' + JPEG + JPEG[:5])
        self.assertEqual((frames, rest), ([JPEG], JPEG[:5]))
        frames, rest = split_jpegs(rest + JPEG[5:] + JPEG)
        self.assertEqual((frames, rest), ([JPEG, JPEG], b''))

    def test_ffmpeg_reads_video_only_and_scales(self):
        command = ffmpeg_command('rtsp://192.168.169.1:554/', 1280, 15, 'high')
        self.assertIn('0:v:0', command)
        self.assertIn('-an', command)
        self.assertIn("scale='min(1280,iw)':-2", command)
        self.assertEqual(command[command.index('-rtsp_transport') + 1], 'tcp')

    def test_opener_copies_app_sequence_and_publishes_frames(self):
        calls, frames, ended = [], [], threading.Event()
        def get(host, path):
            calls.append(path)
            return {'result': 0}
        camera = Dashcam(get=get)
        camera.side = 'rear'
        camera.publish_threadsafe = frames.append
        camera.ended_threadsafe = ended.set
        process, sock = FakeProcess(JPEG + JPEG), FakeSocket()
        commands = []
        def popen(command, **kwargs):
            commands.append(command)
            return process
        stop = open_dashcam(camera, get=get, popen=popen, connect=lambda *a, **k: sock)
        self.assertTrue(ended.wait(2))  # Stream ended: the view closes so it can restart.
        stop()
        self.assertEqual([c.split('?')[0] for c in calls[:3]], ['/app/setsystime', '/app/enterrecorder', '/app/setparamvalue'])
        self.assertEqual(calls[2], '/app/setparamvalue?param=switchcam&value=1')
        self.assertIn('rtsp://192.168.169.1:554/', commands[0])
        self.assertEqual(frames, [JPEG, JPEG])
        self.assertTrue(process.terminated and sock.closed)
        self.assertIn('Dash cam stream ended', camera.error)

    def test_refused_live_view_raises(self):
        with self.assertRaises(RuntimeError):
            open_dashcam(Dashcam(), get=lambda host, path: {'result': 98})

    def test_switch_validates_and_applies_live(self):
        calls = []
        camera = Dashcam(get=lambda host, path: calls.append(path) or {'result': 0})
        with self.assertRaises(ValueError):
            camera.switch('left')
        camera.switch('rear')
        self.assertEqual((camera.side, calls), ('rear', []))  # Not running: applied on next start.
        camera._stop = lambda: None
        camera.switch('front')
        self.assertEqual(calls, ['/app/setparamvalue?param=switchcam&value=0'])


class DashcamRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes(self):
        state = State()
        async with TestClient(TestServer(create_app(state))) as client:
            self.assertEqual(await (await client.get('/dashcam/status')).json(), {'enabled': False})
            self.assertEqual((await client.get('/dashcam/stream')).status, 404)
            state.dashcam = Dashcam(get=lambda host, path: {'result': 0})
            status = await (await client.get('/dashcam/status')).json()
            self.assertEqual((status['enabled'], status['side'], status['host']), (True, 'front', '192.168.169.1'))
            self.assertEqual((await client.post('/dashcam/side', json={'side': 'up'})).status, 400)
            response = await client.post('/dashcam/side', json={'side': 'rear'})
            self.assertEqual((response.status, (await response.json())['side']), (200, 'rear'))
            self.assertEqual((await client.get('/dashcam.js')).status, 200)


if __name__ == '__main__':
    unittest.main()
