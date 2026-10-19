"""CAN that stops receiving with the key on is reset by the root helper (canwatch.py)."""
import json
from pathlib import Path
import tempfile
import unittest

from hardware.frogdash import canwatch
from hardware.frogdash.canwatch import CanWatch
from hardware.frogdash.state import State


class Health:
    def __init__(self):
        self.status = {'ups': {'available': True, 'input_present': True}}


class Log:
    def __init__(self):
        self.lines = []

    def write(self, level, area, text, detail=None):
        self.lines.append((level, area, text))


class CanWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.now = 0.0
        self.state = State('socketcan', clock=lambda: self.now)
        self.state.health = Health()
        self.state.eventlog = self.log = Log()
        self.watch = CanWatch(self.state, self.folder)
        self.request = self.folder / 'can-request'

    def tick(self, seconds=1, frames=0):
        self.now += seconds
        self.state.received += frames
        self.watch.check()

    def test_a_bus_that_stops_receiving_is_reset_a_few_times_then_left_until_frames_return(self):
        self.tick(frames=0)
        for _ in range(5):
            self.tick(frames=20)
        for _ in range(9):
            self.tick()
        self.assertFalse(self.request.exists())             # Nine seconds: a module restarting, cranking
        self.tick()
        self.assertEqual(self.request.read_text(), 'reset')
        self.assertIn('CAN stopped receiving (10 s with the key on): resetting can0', self.log.lines[-1][2])
        self.request.unlink()                               # The helper took it
        (self.folder / 'can-status.json').write_text(json.dumps({'result': 'ok', 'message': 'can0 taken down and up again'}))
        self.tick()
        self.assertEqual(self.watch.helper, 'ok')
        self.assertEqual(self.watch.snapshot()['last_result']['result'], 'ok')
        # Still silent: again at 60 s and 300 s, then no more.
        while self.now < 400:
            self.tick()
            self.request.unlink(missing_ok=True)
        self.assertEqual(self.watch.resets, len(canwatch.TRIES_AT_S))
        self.assertIn('Last try until frames come back', self.log.lines[-1][2])
        # Frames again: said so, and a later silence is handled from the start.
        self.tick(frames=5)
        self.assertEqual(self.log.lines[-1], ('info', 'can', 'CAN receiving again after the reset'))
        for _ in range(10):
            self.tick()
        self.assertTrue(self.request.exists())
        self.assertEqual(self.watch.resets, len(canwatch.TRIES_AT_S) + 1)

    def test_a_quiet_bus_with_the_key_off_or_in_replay_is_left_alone(self):
        self.tick(frames=0)
        self.tick(frames=20)
        self.state.health.status['ups']['input_present'] = False
        for _ in range(30):
            self.tick()
        self.assertFalse(self.request.exists())
        # Key on again: the silence counts from then, not from key-off.
        self.state.health.status['ups']['input_present'] = True
        for _ in range(9):
            self.tick()
        self.assertFalse(self.request.exists())
        self.tick()
        self.assertTrue(self.request.exists())
        replay = CanWatch(State('replay', clock=lambda: self.now), self.folder / 'other')
        for _ in range(30):
            self.now += 1
            replay.check()
        self.assertEqual(replay.resets, 0)

    def test_a_missing_helper_is_said_once_and_its_request_cleared(self):
        self.tick(frames=0)
        for _ in range(10):
            self.tick()
        self.assertTrue(self.request.exists())
        self.assertIn('has received nothing since the dash started', self.log.lines[-1][2])
        for _ in range(canwatch.HELPER_WAIT_S + 1):
            self.tick()
        self.assertEqual(self.watch.helper, 'missing')
        self.assertFalse(self.request.exists())
        self.assertEqual(sum('did not answer' in text for _, _, text in self.log.lines), 1)

    def test_the_snapshot_reports_the_watch(self):
        self.tick(frames=3)
        self.assertEqual(self.state.snapshot()['can_watch'], None)
        self.state.can_watch = self.watch
        shown = self.state.snapshot()['can_watch']
        self.assertEqual((shown['resets'], shown['helper']), (0, 'unknown'))


if __name__ == '__main__':
    unittest.main()
