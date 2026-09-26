import asyncio
from datetime import datetime, timezone
import math
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.race import Race, MPH
from hardware.frogdash.gps import GPS
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.log_channels import CHANNELS, row_values


class RaceTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.race = Race(clock=lambda: self.now, wall=lambda: 1700000000 + self.now)

    def feed(self, t, speed=0, north=0, **kwargs):
        self.now = t
        report = {'class': 'TPV', 'mode': 3, 'time': datetime.fromtimestamp(1700000000 + t, timezone.utc).isoformat(),
                  'speed': speed, 'lat': north / 111194.9266, 'lon': 0, **kwargs}
        self.race.feed(report)
        return report

    def launch(self):
        self.feed(0)
        self.race.command('accel')
        for i in range(1, 21):
            self.feed(i / 10)

    def test_acceleration_interpolation_and_distance_integral(self):
        self.launch()
        for i in range(1, 161):
            self.feed(2 + i / 10, speed=4 * i / 10)
        self.assertEqual(self.race.phase, 'complete')
        for name, speed in [('0_30', 30 * MPH), ('0_60', 60 * MPH), ('0_100kph', 100 / 3.6)]:
            self.assertAlmostEqual(self.race.splits[name], speed / 4, places=5)
        for name, dist in [('eighth', 201.168), ('quarter', 402.336)]:
            expected = math.sqrt(dist / 2)
            self.assertAlmostEqual(self.race.splits[name], expected, places=5)
            self.assertAlmostEqual(self.race.splits[name + '_mph'], 4 * expected / MPH, places=5)
        self.assertEqual(len(self.race.history), 1)
        self.assertEqual(self.race.warnings, [])

    def test_cannot_arm_rolling_or_launch_without_stationary_hold(self):
        self.feed(0, speed=10)
        with self.assertRaisesRegex(ValueError, 'stop'):
            self.race.command('accel')
        self.feed(1)
        self.race.command('accel')
        self.feed(1.1, speed=1)
        self.assertEqual(self.race.phase, 'armed')
        self.assertIsNone(self.race.start)

    def test_duplicate_partial_epochs_do_not_refresh_or_add_distance(self):
        self.launch()
        report = self.feed(2.1, speed=.4)
        before = self.race.distance_m
        self.now = 2.5
        self.race.feed(report)
        self.race.feed({'class': 'TPV', 'mode': 3, 'time': report['time'], 'lat': 1})
        self.assertEqual(self.race.distance_m, before)
        self.assertEqual(self.race.received, 2.1)
        self.now = 4
        self.race.tick()
        self.assertEqual(self.race.phase, 'invalid')
        self.feed(4.1, speed=.5)
        self.assertEqual(self.race.phase, 'invalid')  # No silent resumption.

    def test_fix_gap_jump_backwards_and_noise_abort_once(self):
        for failure in ('fix', 'gap', 'jump', 'backwards', 'nan'):
            with self.subTest(failure=failure):
                self.setUp(); self.launch()
                if failure == 'fix': self.feed(2.1, mode=1)
                if failure == 'gap': self.feed(4, speed=1)
                if failure == 'jump': self.feed(2.1, speed=20)
                if failure == 'backwards': self.feed(1)
                if failure == 'nan': self.feed(2.1, speed=float('nan'))
                self.assertEqual(self.race.phase, 'invalid')
                self.race.tick()
                self.assertEqual(len(self.race.history), 1)

    def test_lap_gate_requires_exit_reentry_and_minimum_time(self):
        self.feed(0)
        self.race.command('gate'); self.race.command('laps')
        for t in range(1, 21): self.feed(t)
        self.assertEqual(self.race.phase, 'armed')  # Idling on gate is not a crossing.
        for t, north in [(21, 10), (22, 30), (23, 50), (24, 30), (25, 10)]:
            self.feed(t, speed=10, north=north)
        self.assertEqual(self.race.phase, 'running')
        self.assertAlmostEqual(self.race.start, 1700000024.5, places=4)
        for t in range(26, 46): self.feed(t, speed=10, north=10)
        self.assertEqual(self.race.lap_count, 0)
        for t, north in [(46, 30), (47, 50), (48, 30), (49, 10)]:
            self.feed(t, speed=10, north=north)
        self.assertEqual(self.race.lap_count, 1)
        self.assertAlmostEqual(self.race.best_lap, 24, places=4)
        self.assertIn('Coarse', self.race.warnings[0])
        with self.assertRaisesRegex(ValueError, '15 seconds'): self.race.command('lap')

    def test_manual_laps_and_missing_position(self):
        self.feed(0); self.race.command('laps')
        for t in range(1, 21): self.feed(t)
        self.race.command('lap')
        self.assertEqual(self.race.laps[0]['source'], 'manual')
        self.assertEqual(self.race.best_lap, 20)
        self.feed(21, lat=None)
        self.now = 22
        self.race.tick()
        self.assertEqual(self.race.phase, 'invalid')

    def test_partial_lap_position_merges_only_same_epoch(self):
        self.feed(0); self.race.command('laps')
        report = self.feed(.1, lat=None)
        self.assertEqual(self.race.phase, 'running')
        self.race.feed({'class': 'TPV', 'mode': 3, 'time': report['time'], 'lat': 0, 'lon': 0})
        self.assertAlmostEqual(self.race.elapsed, .1, places=5)
        self.assertEqual(self.race.received, .1)
        self.race.command('stop'); self.race.command('gate')
        self.race.command('reset')
        self.assertIsNotNone(self.race.gate)
        self.race.command('clear_gate')
        self.assertIsNone(self.race.gate)

    def test_gps_receiver_selection_applies_to_race_hook(self):
        gps = GPS(device='/dev/ttyACM0')
        gps.on_report = self.race.feed
        report = {'class': 'TPV', 'mode': 3, 'speed': 0, 'time': '2026-09-26T12:00:00Z'}
        gps.update({**report, 'device': '/dev/other'})
        self.assertIsNone(self.race.sample)
        gps.update({**report, 'device': '/dev/ttyACM0'})
        self.assertTrue(self.race.fresh())

    def test_log_contains_race_status_and_invalid_results_are_nan(self):
        state = State(clock=lambda: self.now)
        state.race = self.race
        self.launch(); self.feed(2.1, speed=20)
        snapshot = state.snapshot()
        rows = row_values(snapshot, 1)
        index = next(i for i, c in enumerate(CHANNELS) if c.key == 'race.phase')
        self.assertEqual(rows[3 + index * 2], 5)
        index = next(i for i, c in enumerate(CHANNELS) if c.key == 'race.elapsed_s')
        self.assertTrue(math.isnan(rows[3 + index * 2]))


class RaceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_storage_restart_and_failure_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'race.json'
            race = Race(path)
            race.gate = [40, -105]
            for _ in range(60): race.finish('stopped', 'test')
            await race.save()
            loaded = Race(path)
            self.assertEqual(len(loaded.history), 50)
            self.assertEqual(loaded.gate, [40, -105])
            self.assertEqual(loaded.phase, 'idle')
            self.assertFalse(path.with_suffix('.tmp').exists())
            race.path = path / 'bad.json'; race.dirty = True
            await race.save()
            self.assertTrue(race.storage_error)
            path.write_text('{"version":1,"history":[{"best_lap":NaN}]}', encoding='utf-8')
            self.assertTrue(Race(path).storage_error)

    async def test_local_api_rejects_missing_gps_and_cross_origin(self):
        state = State()
        async with TestClient(TestServer(create_app(state))) as client:
            self.assertEqual((await client.post('/race', json={'action': 'accel'})).status, 400)
            self.assertEqual((await client.post('/race', json={'action': 'stop'}, headers={'Origin': 'https://example.org'})).status, 403)
            self.assertEqual((await client.post('/race', json={'action': 'stop', 'command': 'shell'})).status, 400)
            self.assertEqual((await client.get('/race/results')).status, 200)

    async def test_timer_runs_and_invalidates_without_browser(self):
        race = Race()
        report = {'class': 'TPV', 'mode': 3, 'speed': 0, 'time': '2026-09-26T12:00:00Z'}
        race.feed(report); race.command('accel')
        task = asyncio.create_task(race.run())
        await asyncio.sleep(1.7)
        self.assertEqual(race.phase, 'invalid')
        race.stopping = True
        await task
