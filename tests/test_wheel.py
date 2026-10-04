import unittest

from hardware.frogdash.state import State
from hardware.frogdash.wheel import SteeringWheel
from hardware.frogdash.protocol import decode


class WheelTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.wheel = SteeringWheel(lambda: self.now)
        self.seq = 0

    def frame(self, mask, dt=.05):
        self.now += dt
        self.wheel.observe(bytes([mask, self.seq, 1]))
        self.seq = (self.seq + 1) & 255

    def actions(self):
        return [e['action'] for e in self.wheel.snapshot(True)['events']]

    def test_press_release_between_screen_snapshots_is_preserved(self):
        self.frame(0)
        self.frame(16)
        self.frame(0, .02)
        self.assertEqual(self.actions(), ['ok'])
        self.assertEqual(self.actions(), ['ok'])  # Stable event ID, UI deduplicates.
        self.assertEqual(self.wheel.snapshot(True)['seq'], 1)

    def test_boot_held_chords_and_reconnect_require_release(self):
        self.frame(16)
        self.frame(0)
        self.assertEqual(self.actions(), [])
        self.frame(3)
        self.frame(1)
        self.frame(0)
        self.assertEqual(self.actions(), [])
        self.frame(1)
        self.assertEqual(self.actions(), ['up'])
        self.wheel.snapshot(False)
        self.frame(16)
        self.frame(0)
        self.assertEqual(self.actions(), [])

    def test_ok_long_hold_back_once_without_click_on_release(self):
        self.frame(0)
        self.frame(16)
        for _ in range(20): self.frame(16)
        self.frame(0)
        self.assertEqual(self.actions(), ['hold'])

    def test_repeat_stops_on_stale_and_duplicate_frames(self):
        self.frame(0)
        self.frame(2)
        for _ in range(10): self.frame(2)
        self.assertEqual(self.actions(), ['down', 'down'])
        self.now += .4
        self.assertEqual(self.actions(), [])
        self.frame(2)
        self.frame(0)
        self.frame(8)
        original = self.wheel.sequence
        for _ in range(10):
            self.now += .05
            self.wheel.observe(bytes([8, original, 1]))
        self.assertEqual(self.actions(), [])
        self.assertFalse(self.wheel.armed)

    def test_sequence_wrap_and_event_backlog_are_bounded(self):
        self.seq = 254
        self.frame(0)
        self.frame(4)
        self.frame(0)
        self.frame(16)
        self.frame(0)
        self.assertEqual(self.actions(), ['left', 'ok'])
        for _ in range(100):
            self.frame(1, .001); self.frame(0, .001)
        self.assertEqual(len(self.wheel.events), 32)

    def test_invalid_extended_and_replay_do_not_navigate(self):
        for frame in (bytes([32, 0, 1]), bytes([0, 0, 0]), bytes([0, 0])):
            with self.assertRaises(ValueError): decode(0x205, frame)
        for mode, extended in [('replay', False), ('socketcan', True)]:
            state = State(mode=mode, clock=lambda: self.now)
            state.connected = True
            for mask in (0, 16, 0): state.ingest(0x205, bytes([mask, mask, 1]), extended=extended)
            self.assertEqual(state.snapshot()['wheel']['events'], [])
        state = State(clock=lambda: self.now)
        state.connected = True
        state.ingest(0x205, bytes([0, 0, 1]))
        state.ingest(0x205, bytes([16, 1, 1]))
        state.ingest(0x205, bytes([0, 2, 2]))
        state.ingest(0x205, bytes([0, 3, 1]))
        self.assertEqual(state.snapshot()['wheel']['events'], [])


if __name__ == '__main__': unittest.main()
