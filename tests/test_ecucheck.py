"""The wizard's connection test (hardware/frogdash/ecucheck.py): one answer per situation."""
import struct
import unittest

from hardware.frogdash import ecu
from hardware.frogdash.ecucheck import check

MS = ecu.load('megasquirt')
HOLLEY = ecu.load('holley')
HALTECH = ecu.load('haltech')
ALL = [ecu.load(name) for name in ecu.built_in()]
MS_FRAMES = [(0x5E8, False, bytes.fromhex('03840D7A08020000')), (0x5EA, False, bytes.fromhex('937C03E800000000'))]


def haltech_frames():
    # 0x360: RPM, MAP (0.1 kPa), throttle; 0x372: battery (0.1 V)
    return [(0x360, False, struct.pack('>HHHH', 850, 1013, 0, 0)), (0x372, False, struct.pack('>HHHH', 139, 0, 0, 0))]


class ConnectionTests(unittest.TestCase):
    def test_talking_shows_live_readings(self):
        result = check(MS, MS_FRAMES, 500000, True, others=ALL)
        self.assertEqual(result['state'], 'ok')
        self.assertIn('MicroSquirt is talking', result['message'])
        self.assertTrue(result['readings'])

    def test_no_can_interface(self):
        self.assertEqual(check(MS, [], 500000, False)['state'], 'no_interface')

    def test_holley_on_a_500k_bus_says_the_speeds_differ(self):
        result = check(HOLLEY, [], 500000, True, others=ALL)
        self.assertEqual(result['state'], 'wrong_speed')
        self.assertIn('1 Mbit/s', result['message'])
        self.assertIn('500 kbit/s', result['message'])
        self.assertEqual(result['hints'], HOLLEY.data['setup'])               # Holley's own setup steps

    def test_silent_bus_gives_the_ecus_steps_and_the_wiring(self):
        result = check(HALTECH, [], 1000000, True, others=ALL)
        self.assertEqual(result['state'], 'silent')
        self.assertIn('120 ohm', result['hints'][-1])

    def test_errors_and_no_messages(self):
        self.assertEqual(check(HALTECH, [], 1000000, True, errors=5, others=ALL)['state'], 'errors')

    def test_another_ecus_messages_are_named(self):
        result = check(HALTECH, MS_FRAMES + [(0x5EB, False, bytes(8))], 1000000, True, others=ALL)
        self.assertEqual((result['state'], result['suggest']), ('other_ecu', 'megasquirt'))

    def test_11_bit_frames_for_a_29_bit_ecu(self):
        result = check(HOLLEY, [(0x123, False, bytes(8))], 1000000, True, others=[HOLLEY])
        self.assertEqual(result['state'], 'wrong_ids')

    def test_frames_but_not_this_ecus(self):
        result = check(HALTECH, [(0x123, False, bytes(8))], 1000000, True, others=ALL)
        self.assertEqual(result['state'], 'not_this_ecu')

    def test_haltech_talking(self):
        result = check(HALTECH, haltech_frames(), 1000000, True, others=ALL)
        self.assertEqual(result['state'], 'ok')
        self.assertIn('RPM 850', result['message'])

    def test_the_cars_own_modules_are_not_taken_for_an_ecu(self):
        rusefi = ecu.load('rusefi')                                          # Its default 0x200 is the gateway's
        modules = [(0x200, False, bytes(8)), (0x202, False, bytes(8)), (0x203, False, bytes(8))]
        self.assertEqual(check(rusefi, modules, 500000, True, others=ALL)['state'], 'ok')
        self.assertNotEqual(check(rusefi, modules, 500000, True, others=ALL, owned=[(0x200, 0x20F)])['state'], 'ok')


if __name__ == '__main__':
    unittest.main()
