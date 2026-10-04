import struct
import unittest
from unittest.mock import Mock

from hardware.frogdash.protocol import LENGTHS, decode
from hardware.frogdash.state import State
from hardware.frogdash.adapters import CAN_FRAME, unpack_frame
from hardware.frogdash.gps import GPS, next_report


class ProtocolTests(unittest.TestCase):
    def test_all_contract_lengths_and_short_frames(self):
        for identifier, length in LENGTHS.items():
            data = bytearray(length)
            if identifier == 0x30A:
                data[3] = 2
            if identifier == 0x205:
                data[2] = 1
            if identifier == 0x103:
                data[0] = 5  # Taillight status report.
            if identifier == 0x501:
                data[3] = 1
            if identifier == 0x503:
                data[0] = data[5] = 1
            self.assertTrue(decode(identifier, data), hex(identifier))
            with self.assertRaises(ValueError):
                decode(identifier, data[:-1])

    def test_taillights_separate_side_inputs(self):
        values = decode(0x100, bytes.fromhex('05 01 05 02 80 46 10'))
        self.assertTrue(values['lighting.turn_left'].value)
        self.assertFalse(values['lighting.turn_right'].value)
        self.assertTrue(values['lighting.brake'].value)
        self.assertTrue(values['lighting.running'].value)
        self.assertEqual(values['lighting.die_c'].value, 70)

    def test_mixed_endianness_and_scaling(self):
        self.assertEqual(decode(0x202, bytes.fromhex('0D7A 012C 01 01 14 00'))['tach.rpm'].value, 3450)
        self.assertEqual(decode(0x309, bytes.fromhex('7A0D 64 01'))['runtime.rpm'].value, 3450)
        gps = decode(0x203, bytes.fromhex('02F4 FFF6 0B 03 13 0E'))
        self.assertEqual(gps['vehicle.speed_kph'].value, 75.6)
        self.assertEqual(gps['gps.altitude_m'].value, -10)
        self.assertEqual(decode(0x303, bytes.fromhex('7D4F00003C410001'))['engine.oil_pressure_psi'].value, 62.5)
        self.assertEqual(decode(0x300, bytes.fromhex('02326401551E5000'))['engine.iat_c'].value, -10)
        self.assertEqual(decode(0x307, bytes.fromhex('13140FB403225500'))['knock.last_rpm'].value, 3400)

    def test_validity_and_checksums(self):
        self.assertEqual(decode(0x203, bytes.fromhex('02F400000B010300'))['vehicle.speed_kph'].quality, 'unavailable')
        self.assertEqual(decode(0x202, bytes.fromhex('0D7A000003010000'))['tach.rpm'].quality, 'unavailable')
        self.assertEqual(decode(0x307, bytes.fromhex('63140FB403225500'))['knock.energy'].quality, 'fault')
        with self.assertRaises(ValueError):
            decode(0x304, b'\0' * 7 + b'\1')
        with self.assertRaises(ValueError):
            decode(0x30A, bytes([0x40, 0, 1, 1]))

    def test_ecu_dash_and_realtime(self):
        d = decode(0x5E8, struct.pack('>hHhh', 1800, 3450, 2050, 500))
        self.assertEqual(d['ecu.rpm'].value, 3450)
        self.assertAlmostEqual(d['ecu.coolant_c'].value, (205 - 32) * 5 / 9)
        for base in (0x700, 0x5F0):
            d = decode(base + 2, struct.pack('>hhhh', 900, 1800, -100, 2050))
            self.assertEqual(d['ecu.baro_kpa'].value, 90)
            self.assertAlmostEqual(d['ecu.iat_c'].value, (-10 - 32) * 5 / 9)
        self.assertEqual(decode(0x5EA, bytes.fromhex('937C03E800000000'))['ecu.ego_correction_pct'].value, 100)

    def test_ms2_status_word_offsets_and_unsigned_dwell(self):
        for base in (0x5F0, 0x700):
            values = decode(base + 10, bytes.fromhex('01020304FFFE0607'))
            self.assertEqual([values[f'ecu.status{i}'].value for i in range(1, 8)],
                             [1, 2, 3, 4, -2, 6, 7])
            values = decode(base + 9, struct.pack('>hhHH', 125, -25, 40000, 65535))
            self.assertEqual(values['ecu.ego1_v'].value, 1.25)
            self.assertEqual(values['ecu.ego2_v'].value, -.25)
            self.assertEqual(values['ecu.dwell_ms'].value, 4000)
            self.assertEqual(values['ecu.trailing_dwell_ms'].value, 6553.5)

    def test_ms2_diagnostic_scaling_and_supported_fields(self):
        cases = [
            (1, bytes.fromhex('FF9C1234937C0000'), {'spark_deg': -10, 'injection_flags': 18, 'engine_flags': 52, 'afr_target': 14.7, 'afr2_target': 12.4}),
            (7, struct.pack('>hhhh', -15, -125, -20, -300), {'cold_advance_deg': -1.5, 'tps_rate_pct_s': -12.5, 'map_rate_kpa_s': -20, 'rpm_rate_rpm_s': -3000}),
            (12, struct.pack('>ii', 123456, -123456), {'wall_fuel1_us': 1234.56, 'wall_fuel2_us': -1234.56}),
            (13, struct.pack('>hhhh', 123, -456, 789, 0), {'sensor1': 12.3, 'sensor2': -45.6, 'sensor3': 78.9, 'sensor4': 0}),
            (18, struct.pack('>hhhh', 1500, 2500, 3500, 4500), {'pwseq1_ms': 1.5, 'pwseq2_ms': 2.5, 'pwseq3_ms': 3.5, 'pwseq4_ms': 4.5}),
            (43, bytes.fromhex('FE020000000000F6'), {'sync_loss_count': 254, 'sync_loss_reason': 2, 'timing_error_pct': -10}),
        ]
        for base in (0x5F0, 0x700):
            for group, payload, expected in cases:
                actual = decode(base + group, payload)
                for key, value in expected.items():
                    self.assertEqual(actual['ecu.' + key].value, value, (base, group, key))
        self.assertEqual(decode(0x5EC, bytes(8)), {})  # MS3 VSS is not MS2 speed.
        self.assertNotIn('ecu.sensor11', decode(0x5F0 + 15, bytes(8)))
        self.assertEqual(decode(0x5EB, bytes.fromhex('008A007BFE381900'))['ecu.knock_retard_deg'].value, 2.5)

    def test_fuel_controller_percentage_and_invalid_reports(self):
        for raw, pct in ((0, 0), (1, .1), (500, 50), (1000, 100)):
            d = decode(0x204, raw.to_bytes(2, 'big') + b'\x01')
            self.assertEqual(d['vehicle.fuel_pct'].value, pct)
            self.assertEqual(d['vehicle.fuel_pct'].quality, 'live')
        for frame, quality in [('FFFF00', 'unavailable'), ('000002', 'fault'),
                               ('01F403', 'fault'), ('03E901', 'fault'), ('FFFF01', 'fault')]:
            sample = decode(0x204, bytes.fromhex(frame))['vehicle.fuel_pct']
            self.assertEqual(sample.quality, quality)
            self.assertIsNone(sample.value)

    def test_kernel_frame_flags(self):
        frame = unpack_frame(CAN_FRAME.pack(0x80000100, 7, bytes(8)))
        self.assertEqual(frame, (0x100, bytes(7), True, False, False))
        with self.assertRaises(ValueError):
            unpack_frame(CAN_FRAME.pack(0x100, 9, bytes(8)))


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.state = State(clock=lambda: self.now, wall=lambda: self.now + 100)
        self.state.connected = True

    def values(self): return self.state.snapshot()['values']

    def test_unrelated_messages_do_not_refresh_old_rpm(self):
        self.state.ingest(0x5E8, bytes.fromhex('03840D7A08020000'))
        self.now = 1.1
        self.state.ingest(0x5EA, bytes.fromhex('937C03E800000000'))
        self.assertEqual(self.values()['engine.rpm']['quality'], 'stale')
        self.assertEqual(self.values()['engine.afr']['quality'], 'live')

    def test_fault_flags_apply_across_frames_and_recover(self):
        self.state.ingest(0x300, bytes.fromhex('0100640055505000'))
        self.assertEqual(self.values()['engine.iat_c']['quality'], 'unavailable')
        self.state.ingest(0x303, bytes.fromhex('7D4F00003C411100'))
        self.assertEqual(self.values()['engine.iat_c']['quality'], 'fault')
        self.assertEqual(self.values()['engine.oil_pressure_psi']['quality'], 'fault')
        self.state.ingest(0x303, bytes.fromhex('7D4F00003C410000'))
        self.assertEqual(self.values()['engine.iat_c']['quality'], 'live')
        self.now = 2
        self.state.ingest(0x300, bytes.fromhex('0100640055505000'))
        self.assertEqual(self.values()['engine.iat_c']['quality'], 'stale')

    def test_disconnection_malformed_and_unsupported(self):
        self.state.ingest(0x202, bytes.fromhex('0D7A000001010000'))
        self.state.ingest(0x202, b'\0')
        self.assertEqual(self.values()['engine.rpm']['quality'], 'fault')
        self.state.ingest(0x202, bytes.fromhex('0D7A000001010000'))
        self.state.connected = False
        self.assertEqual(self.values()['engine.rpm']['quality'], 'stale')
        self.assertEqual(self.values()['vehicle.fuel_pct']['quality'], 'unavailable')

    def test_raw_and_events_are_bounded_and_extended_never_decodes(self):
        self.state.ingest(0x100, bytes(7), extended=True)
        self.assertNotIn('lighting.turn_left', self.values())
        for identifier in range(300):
            self.state.ingest(identifier, b'')
        self.assertEqual(len(self.state.raw), 256)
        for _ in range(110):
            self.state.ingest(0x308, bytes([1, 2, 3, 4]))
        self.assertEqual(len(self.state.events), 100)

    def test_fuel_can_freshness_fault_and_recovery(self):
        self.state.ingest(0x204, bytes.fromhex('01F401'))
        self.assertEqual(self.values()['vehicle.fuel_pct']['value'], 50)
        self.now = 2.1
        self.state.ingest(0x200, bytes(8))
        self.assertEqual(self.values()['vehicle.fuel_pct']['quality'], 'stale')
        self.state.ingest(0x204, bytes.fromhex('01F401'))
        self.state.ingest(0x204, bytes.fromhex('01F4'))
        self.assertEqual(self.values()['vehicle.fuel_pct']['quality'], 'fault')
        self.state.ingest(0x204, bytes.fromhex('03E801'))
        self.assertEqual(self.values()['vehicle.fuel_pct']['value'], 100)
        self.state.trip.sample(self.state.snapshot())
        self.assertAlmostEqual(self.state.trip.snapshot()['remaining_l'], self.state.trip.settings['capacity_l'])
        self.assertEqual(self.state.trip.snapshot()['fuel_source'], 'CAN fuel level')
        self.state.connected = False
        self.assertEqual(self.values()['vehicle.fuel_pct']['quality'], 'stale')
        self.state.trip.sample(self.state.snapshot())
        self.assertIsNone(self.state.trip.snapshot()['remaining_l'])

    def test_dash_and_realtime_expire_independently(self):
        self.state.ingest(0x5E8, struct.pack('>hHhh', 1000, 2000, 1800, 0))
        self.now = .2
        self.state.ingest(0x700, struct.pack('>HHHH', 10, 1500, 1500, 2500))
        self.assertEqual(self.values()['engine.rpm']['value'], 2500)
        self.now = .4
        self.state.ingest(0x5E8, struct.pack('>hHhh', 1000, 3000, 1800, 0))
        self.assertEqual(self.values()['engine.rpm']['value'], 3000)
        self.now = 1.3
        self.state.ingest(0x701, bytes(8))
        self.assertEqual(self.values()['engine.rpm']['quality'], 'live')
        self.assertEqual(self.values()['ecu.pw1_ms']['quality'], 'stale')
        self.now = 1.5
        self.state.ingest(0x701, bytes(8))
        self.assertEqual(self.values()['engine.rpm']['quality'], 'stale')

    def test_ecu_priority_and_fallback(self):
        self.state.ingest(0x5E8, bytes.fromhex('03840D7A08020000'))
        self.state.ingest(0x202, bytes.fromhex('0BB8000001010000'))
        self.assertEqual(self.values()['engine.rpm']['value'], 3450)
        self.now = 1.1
        self.state.ingest(0x202, bytes.fromhex('0BB8000001010000'))
        self.assertEqual(self.values()['engine.rpm']['value'], 3000)


class GPSTests(unittest.TestCase):
    def test_libgps_partial_reads_never_reuse_previous_report(self):
        session = Mock()
        session.data = {'class': 'TPV', 'mode': 3, 'speed': 21}
        session.read.return_value = 0
        self.assertIsNone(next_report(session))
        session.read.return_value = -1
        with self.assertRaises(ConnectionError): next_report(session)

    def setUp(self):
        self.now = 0
        self.gps = GPS(clock=lambda: self.now, wall=lambda: self.now)
        self.gps.connected = True

    def fix(self, **kwargs):
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 3, 'speed': 21, 'altMSL': -10, **kwargs})

    def test_gpsd_to_can_roundtrip(self):
        self.fix()
        self.gps.update({'class': 'SKY', 'device': '/dev/ttyACM0', 'satellites': [{'used': True}, {'used': False}]})
        self.assertEqual(self.gps.frame(), bytes.fromhex('02F4 FFF6 01 03 1B 02'))
        self.assertEqual(decode(0x203, self.gps.frame())['vehicle.speed_kph'].value, 75.6)

    def test_no_fix_stale_missing_speed_disconnect_and_nan(self):
        self.fix()
        self.now = 2.1
        self.assertNotEqual(self.gps.values()['vehicle.speed_kph']['quality'], 'live')
        self.assertEqual(self.gps.frame()[:2], b'\0\0')
        self.fix(mode=1)
        self.assertEqual(self.gps.frame()[6] & 0x10, 0)
        self.fix(speed=float('nan'))
        self.assertEqual(self.gps.frame()[:2], b'\0\0')
        self.fix()
        self.gps.connected = False
        self.assertEqual(self.gps.values()['vehicle.speed_kph']['quality'], 'stale')
        self.assertEqual(self.gps.frame()[6] & 0x10, 0)

    def test_device_isolation_and_partial_reports(self):
        self.fix()
        self.fix(device='/dev/ttyACM1', speed=100)
        self.assertAlmostEqual(self.gps.values()['vehicle.speed_kph']['value'], 75.6)
        self.now = 1
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 3, 'lat': 40})
        self.now = 2.1
        self.assertEqual(self.gps.values()['vehicle.speed_kph']['quality'], 'stale')

    def test_usb_gps_survives_can_disconnect_and_has_no_can_fallback(self):
        self.fix()
        state = State(clock=lambda: self.now)
        state.gps = self.gps
        self.assertEqual(state.snapshot()['values']['vehicle.speed_kph']['quality'], 'live')
        self.gps.connected = False
        state.connected = True
        state.ingest(0x203, bytes.fromhex('02F4 FFF6 0B 03 13 0E'))
        self.assertEqual(state.snapshot()['values']['vehicle.speed_kph']['quality'], 'stale')


if __name__ == '__main__':
    unittest.main()
