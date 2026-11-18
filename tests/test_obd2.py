"""Generic OBD-II (hardware/frogdash/obd2.py): mode 01 answers, and what the dash asks next."""
import unittest

from hardware.frogdash import ecu, obd2
from hardware.frogdash.obd2 import Poller, decode, request


def answer(pid, *data):
    return bytes([2 + len(data), 0x41, pid, *data] + [0x55] * (5 - len(data)))


class DecodeTests(unittest.TestCase):
    def test_sae_j1979_formulas(self):
        # Worked examples: RPM 0x1AF8 / 4 = 1726; coolant 0x7B - 40 = 83 C; speed 88 km/h;
        # MAF 0x0190 / 100 = 4 g/s; module voltage 0x3A98 / 1000 = 15.0 V; advance 0x80 / 2 - 64 = 0.
        self.assertEqual(decode(answer(0x0C, 0x1A, 0xF8)), {'ecu.rpm': 1726.0})
        self.assertEqual(decode(answer(0x05, 0x7B)), {'ecu.coolant_c': 83})
        self.assertEqual(decode(answer(0x0D, 88)), {'ecu.vehicle_speed_kph': 88})
        self.assertEqual(decode(answer(0x10, 0x01, 0x90)), {'ecu.maf_g_s': 4.0})
        self.assertEqual(decode(answer(0x42, 0x3A, 0x98)), {'ecu.battery_v': 15.0})
        self.assertEqual(decode(answer(0x0E, 0x80)), {'ecu.spark_deg': 0.0})
        self.assertEqual(decode(answer(0x06, 128)), {'ecu.stft1_pct': 0.0})
        self.assertAlmostEqual(decode(answer(0x24, 0x80, 0x00))['ecu.lambda1'], 1.0)
        self.assertAlmostEqual(decode(answer(0x11, 255))['ecu.throttle_pct'], 100.0)

    def test_other_answers_are_ignored(self):
        self.assertEqual(decode(bytes([3, 0x7F, 0x01, 0x12, 0, 0, 0, 0])), {})      # Negative response
        self.assertEqual(decode(answer(0x99, 1)), {})                              # Unknown PID
        self.assertEqual(decode(bytes([2, 0x41, 0x0C])), {})                       # Too short for RPM

    def test_request_frame(self):
        self.assertEqual(request(0x0C), bytes([0x02, 0x01, 0x0C, 0x55, 0x55, 0x55, 0x55, 0x55]))


class PollerTests(unittest.TestCase):
    def test_asks_what_is_supported_until_the_car_answers(self):
        poller = Poller()
        ident, data = poller.frame(0.0)
        self.assertEqual((ident, data[2]), (0x7DF, 0x00))
        self.assertIsNone(poller.frame(0.1))                       # Nothing known yet; asks again later
        self.assertEqual(poller.frame(3.1)[1][2], 0x00)

    def test_cycles_supported_readings_with_the_fast_ones_between(self):
        poller = Poller()
        poller.frame(0.0)
        # The car supports 0x05 (coolant), 0x0C (RPM), 0x0D (speed), 0x2F (fuel level) and 0x20 (more).
        bits = sum(1 << (32 - pid) for pid in (0x05, 0x0C, 0x0D, 0x20))
        poller.seen(bytes([6, 0x41, 0x00, *bits.to_bytes(4, 'big'), 0x55]))
        self.assertEqual(poller.frame(5.0)[1][2], 0x20)            # Then the next bitmap
        poller.seen(bytes([6, 0x41, 0x20, *(1 << (32 - (0x2F - 0x20))).to_bytes(4, 'big'), 0x55]))
        asked = [poller.frame(10 + n)[1][2] for n in range(8)]
        self.assertEqual(set(asked), {0x05, 0x0C, 0x0D, 0x2F})
        self.assertTrue(all(p in (0x0C, 0x0D) for p in asked[1::2]) or all(p in (0x0C, 0x0D) for p in asked[0::2]))

    def test_29_bit_requests(self):
        poller = Poller(extended=True)
        ident, _ = poller.frame(0.0)
        self.assertEqual(ident, 0x18DB33F1 | 0x80000000)


class ProfileTests(unittest.TestCase):
    def test_profiles_read_answers_from_any_engine_ecu(self):
        p11, p29 = ecu.load('obd2'), ecu.load('obd2_29bit')
        self.assertEqual(p11.decode(0x7E9, answer(0x0C, 0x0F, 0xA0)), {'ecu.rpm': 1000.0})
        self.assertTrue(p29.is_ecu(0x18DAF110) and p29.is_ecu(0x18DAF11A))
        self.assertEqual(p29.decode(0x18DAF110, answer(0x05, 90)), {'ecu.coolant_c': 50})
        self.assertEqual(p11.keys(), obd2.keys())

    def test_the_answers_reach_the_gauges(self):
        from hardware.frogdash import protocol
        from hardware.frogdash.state import State
        previous = protocol.ECU
        try:
            protocol.use(ecu.load('obd2'))
            state = State(wall=lambda: 1000.0)
            state.obd = Poller()
            state.ingest(0x7E8, answer(0x0C, 0x0F, 0xA0))
            state.ingest(0x7E8, answer(0x00, 0x00, 0x10, 0x00, 0x00))      # Bit for PID 0x0C (RPM)
            values = state.snapshot()['values']
            self.assertEqual(values['engine.rpm']['value'], 1000.0)
            self.assertIn(0x0C, state.obd.supported)
        finally:
            protocol.use(previous)


if __name__ == '__main__':
    unittest.main()
