"""One failing part of the dash must not stop the others: the snapshot leaves the part out
and records why, a bad CAN frame is skipped, a crashed background loop is started again,
the controls guard keeps its other jobs, and the event log shows each fault once."""
import asyncio
import tempfile
from pathlib import Path
import unittest

from hardware.frogdash.adapters import replay
from hardware.frogdash.eventlog import EventLog
from hardware.frogdash.state import State
from hardware.frogdash.supervision import keep_running


class SnapshotTests(unittest.TestCase):
    def test_a_failing_part_is_left_out_and_recorded_and_the_rest_carries_on(self):
        state = State(clock=lambda: 10)
        state.ingest(0x202, bytes.fromhex('0D7A000001010000'))           # Tach: 3450 RPM
        def broken(*args):
            raise ZeroDivisionError('float division by zero')
        state.nav.step = broken
        state.meth_tune.snapshot = broken
        snapshot = state.snapshot()                                        # Does not raise
        self.assertEqual(snapshot['values']['tach.rpm']['value'], 3450)
        self.assertIsNone(snapshot['meth_tune'])
        self.assertIn('navigation', snapshot['faults'])
        self.assertIn('ZeroDivisionError: float division by zero (test_resilience.py:', snapshot['faults']['navigation'])
        self.assertIn('water/meth tuning', snapshot['faults'])

    def test_the_event_log_writes_each_fault_once(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State(clock=lambda: 10)
            log = EventLog(state, Path(folder))
            state.fault('trip', KeyError('odometer_km'))
            snapshot = state.snapshot()
            log.watch(snapshot)
            log.watch(snapshot)
            lines = [e['text'] for e in log.recent if e['area'] == 'dash']
            self.assertEqual(lines, ["trip failed: KeyError: 'odometer_km'"])


class CanTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_frame_that_raises_is_skipped_and_the_replay_carries_on(self):
        state = State(clock=lambda: 10)
        original = state.controls.observe
        def picky(can_id, data):
            if can_id == 0x300:
                raise IndexError('index out of range')
            return original(can_id, data)
        state.controls.observe = picky
        frames = [(0.0, 0x300, bytes(8), False), (0.0, 0x202, bytes.fromhex('0D7A000001010000'), False)]
        await replay(state, frames)
        self.assertEqual(state.malformed, 1)
        self.assertIn('replayed frame 0x300', state.faults)
        self.assertEqual(state.samples['tach.rpm', 0x202]['value'], 3450)   # The next frame still arrived


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_failed_loop_is_recorded_and_started_again_and_a_finished_one_is_not(self):
        state = State(clock=lambda: 10)
        runs = []

        async def flaky():
            runs.append(len(runs))
            if len(runs) == 1:
                raise RuntimeError('first time')
        await asyncio.wait_for(keep_running(state, 'trip', flaky), 5)
        self.assertEqual(runs, [0, 1])
        self.assertIn('RuntimeError: first time', state.faults['trip'])

    async def test_the_controls_guard_keeps_its_other_jobs(self):
        state = State(clock=lambda: 10)
        controls = state.controls
        done = []

        async def broken():
            raise ValueError('bad value')

        async def fine():
            done.append(1)
            if len(done) >= 2:
                controls.closing = True
        controls.check_lighting = broken
        controls.keep_meth_armed = fine
        await asyncio.wait_for(controls.guard_lighting(), 5)
        self.assertGreaterEqual(len(done), 2)
        self.assertIn('taillight guard', state.faults)


if __name__ == '__main__':
    unittest.main()
