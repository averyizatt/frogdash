import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import web
from hardware.frogdash.shutdown import ShutdownHistory
from hardware.frogdash.state import State
from hardware.frogdash.server import create_app
from hardware.frogdash.recorder import Recorder, Config
from hardware.frogdash.trip import Trip
from hardware.frogdash.driving import Driving
from hardware.frogdash.race import Race
from hardware.frogdash.health import read_ups
from hardware.power.monitor import PiSugar


class ShutdownRecordTests(unittest.TestCase):
    def test_clean_boot_crash_and_same_boot_service_restarts(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'shutdown.json'
            first = ShutdownHistory(path, 'boot-a')
            first.start()
            self.assertIsNone(first.snapshot()['previous'])
            first.finish(State())
            second = ShutdownHistory(path, 'boot-b')
            second.start()
            self.assertEqual(second.snapshot()['previous']['state'], 'saved')
            self.assertFalse(second.snapshot()['previous']['recording_enabled'])
            # Crash/restart during the same boot preserves previous boot evidence.
            restart = ShutdownHistory(path, 'boot-b')
            restart.start()
            self.assertEqual(restart.snapshot()['previous']['boot_id'], 'boot-a')
            self.assertEqual(restart.document['current']['interruptions'], 1)
            restart.finish(State())
            third = ShutdownHistory(path, 'boot-c')
            third.start()
            self.assertEqual(third.snapshot()['previous']['boot_id'], 'boot-b')
            self.assertEqual(third.snapshot()['previous']['interruptions'], 1)
            # No finish simulates SIGKILL or sudden power loss.
            fourth = ShutdownHistory(path, 'boot-d')
            fourth.start()
            self.assertEqual(fourth.snapshot()['previous']['state'], 'running')

    def test_incomplete_success_record_cannot_claim_sync(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'shutdown.json'
            path.write_text(json.dumps({'version': 1, 'current': {
                'run_id': 'test', 'state': 'saved', 'boot_id': 'a'}}))
            record = ShutdownHistory(path, 'b')
            record.start()
            self.assertIsNone(record.snapshot()['previous'])
            self.assertTrue(record.snapshot()['error'])

    def test_storage_failure_is_not_clean_and_invalid_history_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'shutdown.json'
            path.write_text('invalid')
            record = ShutdownHistory(path, 'a')
            record.start()
            self.assertIsNone(record.snapshot()['previous'])
            self.assertTrue(record.snapshot()['error'])
            state = State()
            state.trip.error = 'Trip write failed'
            record.finish(state)
            next_boot = ShutdownHistory(path, 'b')
            next_boot.start()
            self.assertEqual(next_boot.snapshot()['previous']['state'], 'save_failed')
            self.assertIn('Trip write failed', next_boot.snapshot()['previous']['errors'])
            with patch('hardware.frogdash.shutdown.atomic_write', side_effect=OSError('disk full')):
                failed = ShutdownHistory(path, 'c')
                failed.start()
                self.assertFalse(failed.snapshot()['tracking'])
                failed.finish(State())
            self.assertEqual(json.loads(path.read_text())['current']['state'], 'running')


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_is_written_after_real_logs_and_state_close(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            state = State()
            state.trip = Trip(state, root / 'trip.json')
            state.driving = Driving(state, root)
            state.race = Race(root / 'race.json')
            state.race.dirty = True
            state.recorder = Recorder(state, Config(root / 'logs', free_bytes=0))
            state.shutdown_history = ShutdownHistory(root / 'shutdown.json', 'boot-a')
            runner = web.AppRunner(create_app(state))
            await runner.setup()
            await asyncio.sleep(.2)
            self.assertEqual(json.loads((root / 'shutdown.json').read_text())['current']['state'], 'running')
            finish = state.shutdown_history.finish
            def checked_finish(current):
                self.assertTrue(state.recorder.writer.closed)
                self.assertTrue((root / 'trip.json').exists())
                self.assertTrue((root / 'race.json').exists())
                self.assertFalse(state.driving.storage_error)
                finish(current)
            with patch.object(state.shutdown_history, 'finish', side_effect=checked_finish):
                await runner.cleanup()
            evidence = json.loads((root / 'shutdown.json').read_text())['current']
            self.assertEqual(evidence['state'], 'saved')
            self.assertGreater(evidence['log_rows'], 0)
            self.assertEqual(evidence['dropped_samples'], state.recorder.dropped)

    async def test_close_exception_leaves_incomplete_marker(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            state = State()
            state.recorder = Recorder(state, Config(root / 'logs', free_bytes=0))
            state.shutdown_history = ShutdownHistory(root / 'shutdown.json', 'boot-a')
            runner = web.AppRunner(create_app(state))
            await runner.setup()
            await asyncio.sleep(.1)
            # The real close releases resources; emulate a final flush failure.
            close = state.recorder.close
            async def failed_close():
                await close()
                raise OSError('final fsync failed')
            with patch.object(state.recorder, 'close', side_effect=failed_close):
                with self.assertRaises(OSError):
                    await runner.cleanup()
            self.assertEqual(json.loads((root / 'shutdown.json').read_text())['current']['state'], 'running')


class UPSDiagnosticsTests(unittest.TestCase):
    def test_telemetry_invalid_fields_are_independent_and_never_fake_zero(self):
        client = PiSugar()
        replies = {'get battery': 'nan', 'get battery_v': '4.05',
                   'get battery_charging': 'false', 'get auto_power_on': 'true'}
        client.request = lambda command: replies[command]
        result = client.telemetry()
        self.assertIsNone(result['battery_percent'])
        self.assertEqual(result['battery_volts'], 4.05)
        self.assertFalse(result['charging'])
        self.assertTrue(result['auto_power_on'])
        self.assertTrue(result['errors'])

    def test_missing_malformed_and_stale_status_are_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'status.json'
            self.assertFalse(read_ups(path, 100)['available'])
            status = {'monotonic': 99, 'input_present': False, 'remaining_seconds': 4,
                      'ups': {'sampled_monotonic': 98, 'battery_percent': 78,
                              'battery_volts': 3.9, 'auto_power_on': True, 'charging': False}}
            path.write_text(json.dumps(status))
            result = read_ups(path, 100)
            self.assertTrue(result['available'])
            self.assertEqual(result['battery_percent'], 78)
            self.assertFalse(result['input_present'])
            self.assertFalse(read_ups(path, 103)['available'])
            self.assertFalse(read_ups(path, 90)['available'])
            status['monotonic'] = 119
            path.write_text(json.dumps(status))
            self.assertIsNone(read_ups(path, 120)['battery_percent'])
            for invalid in ('[]', '{', '{"monotonic": "bad"}', '{"monotonic": NaN}'):
                path.write_text(invalid)
                self.assertFalse(read_ups(path, 100)['available'])
