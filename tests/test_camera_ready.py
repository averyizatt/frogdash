"""The dash cam picture kept ready in the background, and the phone hotspot's priority over the cameras."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.camera import Camera
from hardware.frogdash.connectivity import CAMERAS_OFF, Connectivity
from hardware.frogdash.dashcam import Dashcam, PARK_S, RETRY_MAX_S, STALL_S, START_GRACE_S
from hardware.frogdash import dashcam as dashcam_module
from hardware.frogdash.hotspot_helper import Hotspot, create_helper
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

JPEG = b'\xff\xd8' + b'\x01\xff\x00\x02' + b'\xff\xd9'
UUID = 'd19bc877-cb2b-4a99-90c7-cd827377bda8'
ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which('sh')


class Source:
    """Stands in for the dash cam: counts starts and stops, can refuse to start."""
    def __init__(self):
        self.starts, self.stops, self.refuse, self.sides = 0, 0, False, []

    def open(self, camera):
        if self.refuse:
            raise RuntimeError('Dash cam refused live view')
        self.starts += 1
        self.sides.append(camera.side)
        def stop():
            self.stops += 1
        return stop


class ReadyPictureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100.0
        self.source = Source()
        self.requests = []
        self.camera = Dashcam(opener=self.source.open, clock=lambda: self.now, keep_warm=True,
                              get=lambda host, path: self.requests.append(path) or {'result': 0})

    async def test_buffers_on_the_rear_camera_with_nobody_watching_and_a_view_is_instant(self):
        self.assertEqual(await self.camera.tend(), 2.0)
        self.assertEqual((self.source.starts, self.source.sides, self.camera.viewers), (1, ['rear'], 0))
        self.camera.publish(JPEG)
        # Reverse: the viewer gets the picture that is already arriving, with no start-up.
        await self.camera.acquire()
        self.assertEqual(await self.camera.next_frame(0, timeout=.01), (1, JPEG))
        self.assertEqual(self.source.starts, 1)
        await self.camera.release()
        self.now += 3600                                     # An hour later, nobody watching: still running.
        self.camera.publish(JPEG)
        await self.camera.tend()
        self.assertEqual((self.source.starts, self.source.stops, self.camera.running), (1, 0, True))

    async def test_an_old_picture_is_never_shown_as_live(self):
        await self.camera.tend()
        self.camera.publish(JPEG)
        self.now += 5                                        # The stream froze five seconds ago.
        await self.camera.acquire()
        self.assertIsNone(await self.camera.next_frame(0, timeout=.01))
        self.camera.publish(JPEG)
        self.assertEqual((await self.camera.next_frame(0, timeout=.01))[0], 2)
        plain = Camera(opener=lambda camera: (lambda: None), clock=lambda: self.now)    # The same rule for the Pi camera.
        await plain.acquire()
        plain.publish(JPEG)
        self.now += 2
        self.assertIsNone(await plain.next_frame(0, timeout=.01))

    async def test_a_lost_or_frozen_stream_is_reconnected_by_itself(self):
        await self.camera.tend()
        self.camera.publish(JPEG)
        self.now += STALL_S - 1
        await self.camera.tend()
        self.assertEqual(self.source.stops, 0)               # A short gap is left alone.
        self.now += 2
        self.assertEqual(await self.camera.tend(), 1.0)      # Frozen: closed, retried in a second.
        self.assertEqual((self.source.stops, self.camera.running), (1, False))
        await self.camera.tend()
        self.assertEqual(self.source.starts, 2)
        self.now += START_GRACE_S - 1                        # No first picture yet: within the allowance.
        await self.camera.tend()
        self.assertEqual(self.source.stops, 1)
        self.now += 2
        await self.camera.tend()
        self.assertEqual(self.source.stops, 2)
        await self.camera.close()                            # The stream ending by itself (camera switched off).
        await self.camera.tend()
        self.assertEqual(self.source.starts, 3)

    async def test_a_camera_that_is_off_is_retried_less_and_less_often(self):
        self.source.refuse = True
        delay, waits = 1.0, []
        for _ in range(8):
            delay = await self.camera.tend(delay)
            waits.append(delay)
        self.assertEqual(waits[:4], [4.0, 8.0, 16.0, RETRY_MAX_S])
        self.assertEqual(waits[-1], RETRY_MAX_S)
        self.assertIn('refused', self.camera.error)
        self.source.refuse = False                           # Ignition on: the camera comes up.
        self.assertEqual(await self.camera.tend(delay), 2.0)
        self.assertTrue(self.camera.running)

    async def test_after_a_look_at_the_front_it_returns_to_the_rear_camera(self):
        await self.camera.tend()
        await self.camera.acquire()
        await asyncio.to_thread(self.camera.switch, 'front')
        self.assertEqual(self.requests, ['/app/setparamvalue?param=switchcam&value=0'])
        await asyncio.to_thread(self.camera.switch, 'front')
        self.assertEqual(len(self.requests), 1)              # Already there: the camera is not asked again.
        original = dashcam_module.PARK_S
        dashcam_module.PARK_S = .01
        try:
            await self.camera.release()
            await asyncio.sleep(.1)
        finally:
            dashcam_module.PARK_S = original
        self.assertEqual((self.camera.side, self.requests[-1]), ('rear', '/app/setparamvalue?param=switchcam&value=1'))
        self.assertEqual((self.source.starts, self.source.stops), (1, 0))    # Switched, not restarted.
        self.assertGreater(PARK_S, 1)

    async def test_the_owner_can_switch_buffering_off_and_the_choice_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'dashcam.json'
            camera = Dashcam(opener=self.source.open, clock=lambda: self.now, keep_warm=True, settings=settings, idle_s=.01,
                             get=lambda host, path: {'result': 0})
            self.assertTrue(camera.status()['keep_warm'])
            await camera.tend()
            self.assertTrue(camera.running)
            camera.set_keep_warm(False)
            await camera.tend()                               # Stops as an idle view would, and stays stopped.
            await asyncio.sleep(.1)
            self.assertFalse(camera.running)
            await camera.tend()
            self.assertEqual(self.source.starts, 1)
            await camera.acquire()                            # A view still works, starting on demand as before.
            self.assertEqual(self.source.starts, 2)
            await camera.release()
            await asyncio.sleep(.1)
            self.assertFalse(camera.running)
            self.assertEqual(json.loads(settings.read_text()), {'keep_warm': False})
            again = Dashcam(opener=self.source.open, keep_warm=True, settings=settings)
            self.assertFalse(again.keep_warm)                 # After a restart too.

    async def test_route_and_default(self):
        state = State()
        async with TestClient(TestServer(create_app(state))) as client:
            self.assertEqual((await client.post('/dashcam/warm', json={'enabled': True})).status, 404)
            state.dashcam = Dashcam(opener=self.source.open, keep_warm=True, get=lambda host, path: {'result': 0})
            for bad in ({'enabled': 'yes'}, {}, []):
                self.assertEqual((await client.post('/dashcam/warm', json=bad)).status, 400)
            status = await (await client.post('/dashcam/warm', json={'enabled': False})).json()
            self.assertEqual((status['keep_warm'], status['held']), (False, None))


class Network:
    """NetworkManager as the hotspot broker sees it: one or two adapters."""
    def __init__(self, hotspot_on='wlan0', camera_on='wlan1'):
        self.hotspot_on, self.camera_on = hotspot_on, camera_on
        self.active, self.calls = False, []

    async def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ('-g', 'connection.interface-name'):
            if args[-2:] == ('uuid', UUID):
                return self.hotspot_on
            if self.camera_on is None:
                raise OSError('no such connection profile')
            return self.camera_on
        if args == ('connection', 'up', 'uuid', UUID):
            self.active = True
        elif args == ('connection', 'down', 'uuid', UUID):
            self.active = False
        return UUID if self.active else ''


class HotspotPriorityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.lock = Path(self.folder.name) / 'hotspot.lock'

    def tearDown(self):
        self.folder.cleanup()

    def hotspot(self, network):
        return Hotspot({'uuid': UUID, 'ssid': 'Foxbody Dash', 'password': 'a' * 20}, network, adapter_lock=self.lock)

    async def test_on_one_adapter_the_hotspot_takes_it_and_gives_it_back(self):
        network = Network(hotspot_on='wlan1', camera_on='wlan1')
        hotspot = self.hotspot(network)
        status = await hotspot.set_enabled(True)
        self.assertTrue(status['enabled'] and status['shares_camera'])
        self.assertTrue(self.lock.exists())                   # The Wi-Fi keeper leaves the adapter alone...
        down, up = network.calls.index(('connection', 'down', 'id', 'dashcam')), network.calls.index(('connection', 'up', 'uuid', UUID))
        self.assertLess(down, up)                             # ...and the dash cam is dropped before the hotspot comes up.
        os.utime(self.lock, (1, 1))
        await hotspot.refresh()
        self.assertGreater(self.lock.stat().st_mtime, 1000)   # Kept fresh for as long as the hotspot is on.
        status = await hotspot.set_enabled(False)
        self.assertFalse(status['enabled'] or status['shares_camera'])
        self.assertFalse(self.lock.exists())                  # Handed back: the cameras reconnect.
        self.assertNotIn(('connection', 'up', 'id', 'dashcam'), network.calls)   # By the keeper, not by a wait here.

    async def test_with_two_adapters_or_no_dash_cam_nothing_is_taken(self):
        for network in (Network('wlan0', 'wlan1'), Network('wlan0', None)):
            hotspot = self.hotspot(network)
            status = await hotspot.set_enabled(True)
            self.assertTrue(status['enabled'])
            self.assertFalse(status['shares_camera'])
            self.assertFalse(self.lock.exists())
            self.assertNotIn(('connection', 'down', 'id', 'dashcam'), network.calls)
            await hotspot.set_enabled(False)

    async def test_the_timeout_also_hands_the_adapter_back(self):
        network, clock = Network('wlan1', 'wlan1'), [0.0]
        hotspot = Hotspot({'uuid': UUID, 'ssid': 'Foxbody Dash', 'password': 'a' * 20}, network, lambda: clock[0], adapter_lock=self.lock)
        async with TestClient(TestServer(create_helper(hotspot))) as client:
            self.assertTrue((await (await client.post('/hotspot', json={'enabled': True})).json())['shares_camera'])
            clock[0] = 21 * 60
            self.assertFalse((await (await client.get('/status')).json())['enabled'])
            self.assertFalse(self.lock.exists())

    async def test_the_dash_stops_using_the_cameras_while_the_hotspot_has_their_adapter(self):
        source = Source()
        state = State()
        state.dashcam = Dashcam(opener=source.open, keep_warm=True, get=lambda host, path: {'result': 0})
        await state.dashcam.tend()
        self.assertTrue(state.dashcam.running)
        link = Connectivity(state, Path('unused'))
        link.hold_cameras(True)
        await state.dashcam.tend()
        self.assertEqual((state.dashcam.running, source.stops, state.dashcam.status()['held']), (False, 1, CAMERAS_OFF))
        with self.assertRaises(RuntimeError):                 # A view says why, and does not hammer the Wi-Fi.
            await state.dashcam.acquire()
        self.assertEqual((state.dashcam.viewers, source.starts), (0, 1))
        for _ in range(5):
            await state.dashcam.tend()
        self.assertEqual(source.starts, 1)
        link.hold_cameras(False)                              # Hotspot off: buffering starts again by itself.
        await state.dashcam.tend()
        self.assertEqual((state.dashcam.running, source.starts, state.dashcam.status()['held']), (True, 2, None))


@unittest.skipUnless(SHELL, 'needs sh')
class KeeperTests(unittest.TestCase):
    """The Wi-Fi keeper run for a moment against a stand-in NetworkManager."""
    def run_keeper(self, lock_age=None):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'bin').mkdir()
            shims = {'nmcli': 'echo "$@" >> "$KEEPER_LOG"\ncase "$*" in *"-f NAME con show --active"*) ;; *"-f NAME con show"*) echo dashcam;; '
                              '*"connection.interface-name con show dashcam"*) echo wlan1;; esac\n',
                     'sleep': '[ "$1" = 0 ] || exit 0\nexec /bin/sleep 0.2\n'}
            for name, body in shims.items():
                (base / 'bin' / name).write_text('#!/bin/sh\n' + body, newline='\n')
                (base / 'bin' / name).chmod(0o755)
            lock = base / 'hotspot.lock'
            if lock_age is not None:
                lock.write_text('')
                stamp = lock.stat().st_mtime - lock_age
                os.utime(lock, (stamp, stamp))
            env = {**os.environ, 'PATH': str(base / 'bin') + os.pathsep + os.environ['PATH'], 'KEEPER_LOG': (base / 'log').as_posix(),
                   'FROGDASH_WIFI_LOCKS': f"{(base / 'none.lock').as_posix()} {lock.as_posix()}", 'FROGDASH_KEEPER_PERIOD': '0'}
            try:
                subprocess.run([SHELL, (ROOT / 'tools/frogdash_netkeeper.sh').as_posix()], env=env, capture_output=True, timeout=2)
            except subprocess.TimeoutExpired:
                pass
            log = (base / 'log').read_text() if (base / 'log').exists() else ''
            return log, lock.exists()

    def test_reconnects_the_dash_cam_unless_the_hotspot_holds_the_adapter(self):
        log, _ = self.run_keeper()
        self.assertIn('dev wifi rescan ifname wlan1', log)            # Nothing holds it: the dash cam is rejoined.
        log, held = self.run_keeper(lock_age=30)
        self.assertNotIn('rescan', log)                               # The hotspot has it: left alone.
        self.assertTrue(held)
        log, held = self.run_keeper(lock_age=400)
        self.assertIn('dev wifi rescan ifname wlan1', log)            # A lock left by a crash expires.
        self.assertFalse(held)


if __name__ == '__main__':
    unittest.main()
