"""Reverse camera service: on-demand start, MJPEG framing, idle stop and honest errors."""
import asyncio
import threading
import time
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.camera import Camera
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

JPEG = b'\xff\xd8fake-jpeg\xff\xd9'


class FakeSensor:
    """Emits frames from a worker thread like the picamera2 encoder callback."""
    def __init__(self):
        self.starts = self.stops = 0

    def __call__(self, camera):
        self.starts += 1
        running = threading.Event(); running.set()

        def run():
            while running.is_set():
                camera.publish_threadsafe(JPEG)
                time.sleep(.01)
        worker = threading.Thread(target=run, daemon=True); worker.start()

        def stop():
            self.stops += 1
            running.clear(); worker.join(1)
        return stop


class CameraTests(unittest.IsolatedAsyncioTestCase):
    async def client(self, state):
        client = TestClient(TestServer(create_app(state), host='127.0.0.1'))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client

    async def test_disabled_camera_reports_and_refuses_stream(self):
        client = await self.client(State())
        self.assertEqual(await (await client.get('/camera/status')).json(), {'enabled': False})
        self.assertEqual((await client.get('/camera/stream')).status, 404)

    async def test_stream_starts_on_demand_and_stops_after_idle(self):
        sensor, state = FakeSensor(), State()
        state.camera = Camera(opener=sensor, idle_s=.05)
        client = await self.client(state)
        self.assertFalse((await (await client.get('/camera/status')).json())['running'])
        response = await client.get('/camera/stream')
        self.assertEqual(response.status, 200)
        self.assertIn('multipart/x-mixed-replace', response.headers['Content-Type'])
        chunk = b''
        while chunk.count(JPEG) < 3:
            chunk += await asyncio.wait_for(response.content.read(4096), 2)
        self.assertIn(b'--frogdashframe\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n' % len(JPEG), chunk)
        status = await (await client.get('/camera/status')).json()
        self.assertTrue(status['running'])
        self.assertEqual(status['viewers'], 1)
        self.assertLess(status['frame_age_ms'], 500)
        response.close()
        for _ in range(100):
            if not state.camera.running:
                break
            await asyncio.sleep(.02)
        self.assertFalse(state.camera.running)
        self.assertEqual((sensor.starts, sensor.stops), (1, 1))

    async def test_second_viewer_shares_one_capture(self):
        sensor, camera = FakeSensor(), Camera(opener=FakeSensor(), idle_s=5)
        camera.opener = sensor
        await camera.acquire(); await camera.acquire()
        self.assertEqual(sensor.starts, 1)
        await camera.release()
        self.assertTrue(camera.running)
        await camera.close()

    async def test_missing_camera_is_reported_not_hidden(self):
        def missing(camera):
            raise RuntimeError('no cameras available')
        state = State()
        state.camera = Camera(opener=missing)
        client = await self.client(state)
        response = await client.get('/camera/stream')
        self.assertEqual(response.status, 503)
        self.assertIn('no cameras available', await response.text())
        status = await (await client.get('/camera/status')).json()
        self.assertIn('no cameras available', status['error'])
        self.assertIsNone(status['frame_age_ms'])
        self.assertEqual(status['viewers'], 0)

    async def test_non_jpeg_data_is_ignored(self):
        camera = Camera(opener=FakeSensor())
        camera.publish(b'not a jpeg')
        self.assertIsNone(camera.frame)
        self.assertIsNone(await camera.next_frame(0, timeout=.01))

    def test_invalid_configuration(self):
        for kwargs in ({'width': 50}, {'fps': 120}, {'rotate': 90}, {'quality': 'ultra'}):
            with self.assertRaises(ValueError):
                Camera(**kwargs)

    async def test_remote_clients_cannot_view_camera(self):
        state = State()
        state.camera = Camera(opener=FakeSensor())
        client = await self.client(state)
        response = await client.get('/camera/stream', headers={'Origin': 'http://evil.example'})
        self.assertEqual(response.status, 403)
        self.assertEqual(state.camera.viewers, 0)


if __name__ == '__main__':
    unittest.main()
