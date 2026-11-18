"""A car without the reference car's Frogdash modules: they are not expected, checked or alerted on."""
import unittest
from unittest import mock

from hardware.frogdash import cancheck, protocol
from hardware.frogdash.alerts import module_quiet
from hardware.frogdash.state import State

NONE = {'gateway': False, 'taillights': False, 'watermeth': False}


class ModulePresenceTests(unittest.TestCase):
    def test_the_reference_car_has_them_all(self):
        modules = {row[0] for row in cancheck.expected_rows()}
        self.assertTrue({'Taillights', 'Comfort gateway', 'Water/meth'} <= modules)

    def test_a_car_without_them(self):
        with mock.patch.dict(protocol.MODULES_PRESENT, NONE):
            self.assertFalse({'Taillights', 'Comfort gateway', 'Water/meth'} & {row[0] for row in cancheck.expected_rows()})
            state = State()
            state.ingest(0x100, bytes(7))                     # Even a stray frame on its ID
            snapshot = state.snapshot()
            self.assertEqual(snapshot['modules'], {})
            snapshot.update(mode='socketcan', transport={'connected': True})
            for name in ('taillights', 'comfort', 'watermeth'):
                self.assertIsNone(module_quiet(snapshot, name))
            from hardware.frogdash.fwupdate import Firmware
            self.assertEqual(Firmware(state, None).modules, {})

    def test_only_taillights_never_alerts_on_the_gateway(self):
        with mock.patch.dict(protocol.MODULES_PRESENT, {**NONE, 'taillights': True}):
            snapshot = {'mode': 'socketcan', 'transport': {'connected': True}, 'modules': {'taillights': 'live'}}
            self.assertIsNone(module_quiet(snapshot, 'comfort'))
            rows = {row[0] for row in cancheck.expected_rows()}
            self.assertIn('Taillights', rows)
            self.assertNotIn('Comfort gateway', rows)


if __name__ == '__main__':
    unittest.main()
