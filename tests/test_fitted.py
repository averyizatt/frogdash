"""Module analog inputs with no sensor on them are "not fitted", not faults (fitted.py).

The car's water/meth board reports fuel pressure, meth pressure, boost reference, intake
air, engine bay, ambient and cabin out of range at every start (none is fitted); that lit
SENSOR FAULT on every drive with nothing in the fault lists (2026-11).
"""
import tempfile
import unittest
from pathlib import Path

from hardware.frogdash.fitted import OK_S, FittedSensors
from hardware.frogdash.state import State

# The car's 0x303 at every start: oil pressure in range; fuel, meth, boost reference,
# intake, bay, ambient and cabin flagged (bits 1-7: 0xFE).
CAR = bytes.fromhex('7D0000003C41FE00')
OIL_OUT_TOO = bytes.fromhex('7D0000003C41FF00')


class FittedTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'analog-sensors.json'
        self.state = State(clock=lambda: self.now, wall=lambda: self.now + 100)
        self.state.connected = True
        self.state.fitted = FittedSensors(self.path)

    def tearDown(self):
        self.folder.cleanup()

    def drive(self, frame, seconds, step=0.5):
        end = self.now + seconds
        while self.now < end:
            self.state.ingest(0x303, frame)
            self.now += step

    def values(self):
        return self.state.snapshot()['values']

    def test_inputs_that_never_read_in_range_are_not_faults(self):
        self.drive(CAR, 10)
        values = self.values()
        for name in ('engine.fuel_pressure_psi', 'meth.pressure_psi', 'engine.boost_ref_psi', 'environment.ambient_c', 'environment.cabin_c'):
            self.assertEqual(values[name]['quality'], 'unavailable', name)
            self.assertTrue(values[name]['not_fitted'], name)
        self.assertEqual(values['engine.oil_pressure_psi']['quality'], 'live')
        self.assertFalse(any(v['quality'] == 'fault' for v in values.values()), 'nothing for SENSOR FAULT')
        self.assertIn('engine.fuel_pressure_psi', self.state.snapshot()['analog']['not_fitted'])

    def test_a_sensor_that_has_worked_still_faults(self):
        self.drive(CAR, OK_S + 1)
        self.assertTrue(self.state.fitted.fitted('engine.oil_pressure_psi'))
        self.drive(OIL_OUT_TOO, 3)
        self.assertEqual(self.values()['engine.oil_pressure_psi']['quality'], 'fault')

    def test_a_moment_in_range_is_not_enough(self):
        self.drive(bytes.fromhex('7D0000003C410000'), 1)   # A module starting up: all clear for a second
        self.drive(CAR, 5)
        self.assertFalse(self.state.fitted.fitted('engine.fuel_pressure_psi'))
        self.assertEqual(self.values()['engine.fuel_pressure_psi']['quality'], 'unavailable')

    def test_remembered_across_restarts_and_forgotten_on_request(self):
        self.drive(CAR, OK_S + 1)
        again = FittedSensors(self.path)
        self.assertTrue(again.fitted('engine.oil_pressure_psi'))
        self.assertFalse(again.fitted('engine.fuel_pressure_psi'))
        again.forget()
        self.assertFalse(FittedSensors(self.path).fitted('engine.oil_pressure_psi'))

    def test_an_unreadable_file_starts_afresh(self):
        self.path.write_text('not json', encoding='utf-8')
        self.assertEqual(FittedSensors(self.path).seen, set())


if __name__ == '__main__':
    unittest.main()
