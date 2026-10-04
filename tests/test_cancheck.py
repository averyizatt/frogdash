import unittest

from hardware.frogdash import cancheck
from hardware.frogdash.state import State


class Clock:
    def __init__(self): self.now = 5.0
    def __call__(self): return self.now


class CanCheckTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.state = State(clock=self.clock)
        self.state.connected = True

    def row(self, can_id):
        return next(r for r in cancheck.report(self.state)['rows'] if r['id'] == f'0x{can_id:03X}')

    def test_missing_ok_stopped_and_rate(self):
        self.assertEqual(self.row(0x300)['status'], 'missing')
        for _ in range(11):
            self.state.ingest(0x300, bytes([0, 0, 85, 1, 20, 60, 70, 0]))
            self.clock.now += .1
        row = self.row(0x300)
        self.assertEqual((row['status'], row['rate_hz']), ('ok', 10.0))
        self.assertIn('No faults reported', row['notes'])
        self.clock.now += 10
        self.assertEqual(self.row(0x300)['status'], 'stopped')

    def test_faults_and_out_of_range_are_explained(self):
        self.state.ingest(0x300, bytes([3, 0, 255, 0, 0, 40, 40, 0x22]))
        row = self.row(0x300)
        text = ' '.join(row['notes'])
        self.assertEqual(row['status'], 'fault')
        self.assertIn('MAP sensor reading invalid', text)
        self.assertIn('No command master', text)
        self.assertIn('Tank byte is 255', text)

    def test_wrong_length_is_rejected_with_reason(self):
        self.state.ingest(0x300, bytes(6))
        row = self.row(0x300)
        self.assertEqual(row['status'], 'rejected')
        self.assertIn('expected DLC 8, got 6', row['summary'])
        self.assertIn('Flash the current firmware', ' '.join(row['notes']))

    def test_buttons_are_named(self):
        self.state.ingest(0x501, bytes([9, 31, 4, 1]))
        self.assertIn('Pressed now: ON + SET/ACCEL', self.row(0x501)['notes'][0])
        self.state.ingest(0x501, bytes([0, 31, 5, 1]))
        self.assertIn('Pressed now: nothing', self.row(0x501)['notes'][0])

    def test_realtime_base_1792_and_other_ids(self):
        self.state.ingest(0x700, bytes(8))
        self.state.ingest(0x123, bytes(2))
        report = cancheck.report(self.state)
        self.assertEqual(next(r for r in report['rows'] if r['purpose'].startswith('Realtime broadcast'))['id'], '0x700')
        self.assertIn('0x123', report['other_ids'])


if __name__ == '__main__':
    unittest.main()
