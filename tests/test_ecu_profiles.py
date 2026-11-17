"""ECU profiles (hardware/frogdash/ecu/): the generic decoder, the checks on a profile, and
proof that the MegaSquirt profile reads every frame exactly as the hand-written decoder did."""
import json
import random
import struct
import unittest

from hardware.frogdash import ecu, protocol

try:
    from tests.ms_reference import reference
except ImportError:   # pragma: no cover (run from inside tests/)
    from ms_reference import reference


def frame(**fields):
    base = {'name': 'TEST', 'ids': ['0x360'], 'length': 8, 'signals': []}
    return {**base, **fields}


def profile(**fields):
    base = {'id': 'test', 'label': 'Test ECU', 'bitrate': 500000, 'status': 'documented',
            'frames': [frame(signals=[{'key': 'ecu.rpm', 'layout': 'u16@0'}])]}
    return {**base, **fields}


class MegaSquirtProfileTests(unittest.TestCase):
    def test_every_frame_decodes_exactly_as_before_profiles(self):
        ms = ecu.load('megasquirt')
        rng = random.Random(1512)
        edges = [bytes([b] * 8) for b in (0x00, 0x01, 0x7F, 0x80, 0xFF)]
        ids = sorted(ms.ids())
        self.assertEqual(len(ids), 5 + 64 + 64)               # 0x5E8-0x5EC, 0x5F0-0x62F, 0x700-0x73F
        checked = 0
        for can_id in ids:
            for data in edges + [bytes(rng.randrange(256) for _ in range(8)) for _ in range(200)]:
                new = {k: s.value for k, s in protocol.decode(can_id, data).items()}
                self.assertEqual(new, reference(can_id, data), f'0x{can_id:03X} {data.hex()}')
                self.assertTrue(all(s.quality == 'live' for s in protocol.decode(can_id, data).values()))
                checked += len(new)
        self.assertGreater(checked, 35000)                   # Every value of 133 IDs x 205 frames

    def test_it_keeps_the_ecu_ids_and_their_rules(self):
        self.assertTrue(all(protocol.is_ecu(i) for i in (0x5E8, 0x5EC, 0x5F0, 0x62F, 0x700, 0x73F)))
        self.assertFalse(any(protocol.is_ecu(i) for i in (0x5E7, 0x5ED, 0x630, 0x6FF, 0x740, 0x300, 0x680)))
        self.assertEqual(protocol.decode(0x5EC, bytes(8)), {})       # MS3's VSS frame: not read
        with self.assertRaises(ValueError):
            protocol.decode(0x5E8, bytes(7))
        self.assertEqual((protocol.timeout(0x5F0), protocol.timeout(0x300)), (1.0, .5))

    def test_what_the_dash_shows_about_it(self):
        shown = ecu.load('megasquirt').summary()
        self.assertEqual((shown['label'], shown['bitrate'], shown['status'], shown['tuner']['name']),
                         ('MicroSquirt', 500000, 'car', 'TunerStudio MS'))
        self.assertTrue(shown['source']['url'].startswith('https://www.msextra.com/'))
        self.assertGreater(shown['signals'], 80)

    def test_every_built_in_profile_loads_and_fits_a_car(self):
        bare = protocol.owned_ranges({'modules': {}, 'gps': {'enabled': False, 'transmit_on_can': False}})
        for name in ecu.built_in():
            loaded = ecu.load(name)
            self.assertEqual(protocol.clashes(loaded, bare), [], f'{name} in a car with no Frogdash modules')
            if protocol.clashes(loaded):
                # In a car with every module, a profile that clashes must be movable to a free place.
                self.assertIsNotNone(loaded.base, f'{name} takes module IDs and cannot be moved')
                self.assertEqual(protocol.clashes(ecu.load(name, 0x400)), [], name)
            self.assertIn('url', loaded.data.get('source', {}), f'{name} must name the document it is from')
            self.assertIn(loaded.status, ecu.STATUSES)


def le(*parts):
    """Bytes as rusEFI's firmware packs its structs: little-endian fields one after another."""
    out = b''
    for value, size in parts:
        out += int(value).to_bytes(size, 'little', signed=value < 0)
    return out


class RusefiProfileTests(unittest.TestCase):
    """Frames built the way can_verbose.cpp fills them (rusefi/rusefi bfde8f4), physical
    value times the firmware's PACK_MULT constant, and read back through the profile."""

    def setUp(self):
        self.before = protocol.ECU, protocol.OWNED
        # A car with no Frogdash modules: rusEFI at its default base, 0x200.
        protocol.use(ecu.load('rusefi'), protocol.owned_ranges({'modules': {}, 'gps': {'enabled': False, 'transmit_on_can': False}}))

    def tearDown(self):
        protocol.use(*self.before)

    def values(self, offset, data):
        return {k: v.value for k, v in protocol.decode(0x200 + offset, data).items()}

    def test_engine_readings(self):
        speeds = self.values(1, le((3000, 2), (round(15.5 * 50), 2), (85, 1), (20, 1), (88, 1), (10, 1)))
        self.assertEqual(speeds, {'ecu.rpm': 3000, 'ecu.spark_deg': 15.5, 'ecu.injector_duty_pct': 42.5,
                                  'ecu.coil_duty_pct': 10.0, 'ecu.vehicle_speed_kph': 88, 'ecu.ethanol_pct': 10})
        self.assertEqual(self.values(1, le((800, 2), (-5 * 50, 2), (0, 4)))['ecu.spark_deg'], -5.0)     # Retarded
        sensors = self.values(3, le((round(101.3 * 30), 2), (90 + 40, 1), (25 + 40, 1), (40, 1), (40, 1), (35 + 40, 1), (100, 1)))
        self.assertEqual((sensors['ecu.map_kpa'], sensors['ecu.coolant_c'], sensors['ecu.iat_c'], sensors['ecu.mcu_temp_c'],
                          sensors['ecu.fuel_level_pct']), (101.3, 90, 25, 35, 50.0))
        self.assertEqual(self.values(3, le((0, 2), (0, 6)))['ecu.coolant_c'], -40)
        sensors2 = self.values(4, le((0, 2), (9000, 2), (100 + 40, 1), (30 + 40, 1), (13800, 2)))
        self.assertEqual((sensors2['ecu.oil_pressure_kpa'], sensors2['ecu.oil_temp_c'], sensors2['ecu.battery_v']), (300.0, 100, 13.8))
        fueling = self.values(7, le((9800, 2), (10000, 2), (round(400 * 30), 2), (50, 2)))
        self.assertEqual((fueling['ecu.lambda1'], fueling['ecu.lambda2'], fueling['ecu.fuel_pressure_low_kpa'],
                          fueling['ecu.fuel_pressure_high_kpa']), (0.98, 1.0, 400.0, 500))
        throttle = self.values(2, le((-100, 2), (2550, 2), (-100, 2), (0, 2)))
        self.assertEqual((throttle['ecu.pedal_pct'], throttle['ecu.throttle_pct']), (-1.0, 25.5))     # -1: no pedal sensor
        self.assertEqual(self.values(5, le((450, 2), (12345, 2), (round(3.2 * 300), 2), (7, 2)))['ecu.pw1_ms'], 3.2)

    def test_status_bits_cams_egts_and_knock(self):
        status = self.values(0, le((3, 2), (6051, 2), (0b10001001, 1), (2, 1), (1234, 2)))
        self.assertEqual((status['ecu.warning_count'], status['ecu.last_error'], status['ecu.rev_limit'], status['ecu.check_engine'],
                          status['ecu.fan2'], status['ecu.fuel_pump'], status['ecu.gear'], status['ecu.distance_km']),
                         (3, 6051, 1, 1, 1, 0, 2, 123.4))
        cams = self.values(8, le((-12, 1), (-10, 1), (25, 1), (25, 1), (0, 4)))
        self.assertEqual((cams['ecu.cam1_intake_deg'], cams['ecu.cam1_intake_target_deg'], cams['ecu.cam1_exhaust_deg']), (-12, -10, 25))
        self.assertEqual(self.values(9, bytes([170, 0, 0, 0, 0, 0, 0, 255]))['ecu.egt1_c'], 850)
        self.assertEqual(self.values(9, bytes([0] * 7 + [255]))['ecu.egt8_c'], 1275)
        self.assertEqual(self.values(10, le((-60, 1), (3, 1), (0, 6)))['ecu.knock2_db'], 3)
        self.assertEqual(self.values(11, bytes([1, 0, 0, 0, 0, 0, 0, 0])), {'ecu.brake_pedal': 1})

    def test_its_frames_are_never_taken_for_the_modules_whose_ids_they_share(self):
        # 0x203 is rusEFI's Sensors 1 here, not GPS; 0x205 is Fueling, not wheel buttons.
        self.assertIn('ecu.map_kpa', protocol.decode(0x203, bytes(8)))
        self.assertNotIn('vehicle.speed_kph', protocol.decode(0x203, bytes(8)))
        self.assertTrue(protocol.is_ecu(0x205))
        self.assertEqual(protocol.decode(0x20C, bytes(3)), {})                          # Past its 12 frames

    def test_the_dash_files_its_frames_as_the_ecus(self):
        from hardware.frogdash.state import State
        state = State('socketcan', clock=lambda: 100.0, wall=lambda: 1794000000.0)
        state.connected = True
        calls = []
        state.wheel.observe = lambda data: calls.append(data)
        state.ingest(0x205, le((450, 2), (12345, 2), (960, 2), (7, 2)))
        values = state.snapshot()['values']
        self.assertEqual((values['ecu.pw1_ms']['value'], values['ecu.knock_count']['source_id'], calls), (3.2, 0x205, []))

    def test_moved_to_another_base(self):
        moved = ecu.load('rusefi', 0x400)
        protocol.use(moved)
        self.assertEqual({k: v.value for k, v in protocol.decode(0x401, le((2500, 2), (0, 6))).items()}['ecu.rpm'], 2500)
        self.assertFalse(protocol.is_ecu(0x201))
        self.assertEqual(moved.summary()['base']['used'], '0x400')
        self.assertEqual([i for i, _ in moved.checks()], [0x401, 0x403])

    def test_in_a_car_with_the_comfort_module_its_default_base_is_refused(self):
        with self.assertRaises(ecu.ProfileError) as caught:
            protocol.use(ecu.load('rusefi'), protocol.owned_ranges())
        self.assertIn('ecu.base_id', str(caught.exception))


class MaxxEcuProfileTests(unittest.TestCase):
    """Frames built from MaxxECU's default CAN output protocol v1.3 table (little-endian int16,
    value = raw x scale) and read back through the profile, at its fixed IDs 0x520-0x542."""

    def setUp(self):
        self.before = protocol.ECU, protocol.OWNED
        protocol.use(ecu.load('maxxecu'), protocol.owned_ranges())    # Fits a car with every Frogdash module

    def tearDown(self):
        protocol.use(*self.before)

    def values(self, can_id, *parts):
        return {k: v.value for k, v in protocol.decode(can_id, le(*parts)).items()}

    def test_engine_readings(self):
        self.assertEqual(self.values(0x520, (6500, 2), (455, 2), (1823, 2), (850, 2)),
                         {'ecu.rpm': 6500, 'ecu.throttle_pct': 45.5, 'ecu.map_kpa': 182.3, 'ecu.lambda': 0.85})
        slow = self.values(0x530, (1385, 2), (852, 2), (-55, 2), (920, 2))
        self.assertEqual(slow, {'ecu.battery_v': 13.85, 'ecu.baro_kpa': 85.2, 'ecu.iat_c': -5.5, 'ecu.coolant_c': 92.0})
        oil = self.values(0x536, (3, 2), (405, 2), (4120, 2), (1055, 2))
        self.assertEqual((oil['ecu.gear'], oil['ecu.boost_duty_pct'], oil['ecu.oil_pressure_kpa'], oil['ecu.oil_temp_c']), (3, 40.5, 412.0, 105.5))
        self.assertEqual(self.values(0x521, (0, 2), (0, 2), (-35, 2), (0, 2))['ecu.spark_deg'], -3.5)      # After TDC
        self.assertEqual(self.values(0x522, (312, 2), (0, 2), (0, 2), (1234, 2))['ecu.vehicle_speed_kph'], 123.4)
        self.assertEqual(self.values(0x537, (3000, 2), (0, 2), (0, 2), (2000, 2))['ecu.boost_target_kpa'], 200.0)

    def test_flags_acceleration_and_bytes(self):
        flags = self.values(0x526, (0b10000010, 1), (0b00000011, 1), (0, 2), (7200, 2), (0, 2))
        self.assertEqual((flags['ecu.rev_limit'], flags['ecu.knock_detected'], flags['ecu.brake_pedal'], flags['ecu.clutch_pedal'],
                          flags['ecu.launch_control'], flags['ecu.rev_limit_rpm']), (1, 1, 1, 1, 0, 7200))
        self.assertEqual(self.values(0x527, (-125, 2), (0, 6))['ecu.accel_forward_g'], -1.25)
        tank = self.values(0x540, (2, 1), (1, 1), (453, 2), (0, 4))
        self.assertEqual((tank['ecu.boost_table'], tank['ecu.tune_selector'], tank['ecu.virtual_fuel_l']), (2, 1, 45.3))

    def test_what_is_left_out(self):
        self.assertFalse(protocol.is_ecu(0x52A))                    # Not in the protocol
        self.assertNotIn('ecu.error_codes', ecu.load('maxxecu').keys())   # Page and DBC disagree on its scale


class EcumasterProfileTests(unittest.TestCase):
    """Frames built from the EMU Black manual's CAN Stream table (v1.4): little-endian, value =
    raw x multiplier, at the default base 0x600."""

    def setUp(self):
        self.before = protocol.ECU, protocol.OWNED
        protocol.use(ecu.load('ecumaster'), protocol.owned_ranges())    # 0x600-0x607: clear of every module

    def tearDown(self):
        protocol.use(*self.before)

    def values(self, offset, *parts):
        return {k: v.value for k, v in protocol.decode(0x600 + offset, le(*parts)).items()}

    def test_engine_readings(self):
        self.assertEqual(self.values(0, (5200, 2), (131, 1), (-12, 1), (185, 2), (186, 2)),
                         {'ecu.rpm': 5200, 'ecu.throttle_pct': 65.5, 'ecu.iat_c': -12, 'ecu.map_kpa': 185, 'ecu.pw1_ms': 3.0})
        speed = self.values(2, (112, 2), (86, 1), (95, 1), (64, 1), (48, 1), (-8, 2))
        self.assertEqual(speed, {'ecu.vehicle_speed_kph': 112, 'ecu.baro_kpa': 86, 'ecu.oil_temp_c': 95,
                                 'ecu.oil_pressure_kpa': 400.0, 'ecu.fuel_pressure_kpa': 300.0, 'ecu.coolant_c': -8})
        ign = self.values(3, (-10, 1), (60, 1), (112, 1), (204, 1), (845, 2), (0, 2))
        self.assertEqual((ign['ecu.spark_deg'], ign['ecu.dwell_ms'], ign['ecu.lambda1'], ign['ecu.lambda_correction_pct'], ign['ecu.egt1_c']),
                         (-5.0, 3.0, 0.875, 102.0, 845))
        self.assertEqual(self.values(4, (3, 1), (45, 1), (511, 2), (0, 4))['ecu.battery_v'], 511 * 0.027)
        self.assertEqual(self.values(1, (512, 2), (0, 6))['ecu.analog1_v'], 2.5)

    def test_flags(self):
        flags = self.values(4, (0, 1), (0, 1), (0, 2), (0b10000001, 1), (0b00000100, 1), (0b10000100, 1), (85, 1))
        self.assertEqual((flags['ecu.error_clt'], flags['ecu.knocking'], flags['ecu.error_fuel_pressure'], flags['ecu.error_iat'],
                          flags['ecu.launch_control'], flags['ecu.brake_pedal'], flags['ecu.ethanol_pct']), (1, 1, 1, 0, 1, 1, 85))
        self.assertEqual(self.values(7, (220, 2), (0, 1), (0x13, 1), (95, 1), (0, 1), (1234, 2))['ecu.dsg_mode'], 3)


def be(*parts):
    """Big-endian fields, as Speeduino's highByte/lowByte pairs."""
    out = b''
    for value, size in parts:
        out += int(value).to_bytes(size, 'big', signed=value < 0)
    return out


class SpeeduinoProfileTests(unittest.TestCase):
    """Frames built the way Speeduino's DashMessage() fills them (comms_CAN.cpp, 97ef8e8),
    from its own internal values, and read back through the profile."""

    def setUp(self):
        self.before = protocol.ECU, protocol.OWNED
        protocol.use(ecu.load('speeduino'), protocol.owned_ranges())   # 0x360-0x3E0: clear of every module

    def tearDown(self):
        protocol.use(*self.before)

    def values(self, can_id, data):
        return {k: v.value for k, v in protocol.decode(can_id, data).items()}

    def test_engine_readings(self):
        # RPM 4200, MAP 180 kPa (x10), TPS 37.5% (0.5% steps x5).
        self.assertEqual(self.values(0x360, be((4200, 2), (1800, 2), (75 * 5, 2), (0, 2))),
                         {'ecu.rpm': 4200, 'ecu.map_kpa': 180.0, 'ecu.throttle_pct': 37.5})
        # Fuel 43 psi, oil 60 psi: div100(psi * 6894) + 1013.
        pressures = self.values(0x361, be((43 * 6894 // 100 + 1013, 2), (60 * 6894 // 100 + 1013, 2), (950, 2), (0, 2)))
        self.assertAlmostEqual(pressures['ecu.fuel_pressure_kpa'], 296.4, places=6)
        self.assertAlmostEqual(pressures['ecu.oil_pressure_kpa'], 413.6, places=6)
        self.assertEqual(self.values(0x362, be((45, 2), (0, 2), (-8 * 10, 2), (0, 2))), {'ecu.injector_duty_pct': 45, 'ecu.spark_deg': -8.0})
        self.assertEqual(self.values(0x364, be((3250, 2), (3250, 2), (0, 4)))['ecu.pw1_ms'], 3.25)          # Microseconds
        self.assertEqual(self.values(0x368, be((147 * 1000 // 147, 2), (130 * 1000 // 147, 2), (0, 4))),
                         {'ecu.lambda1': 1.0, 'ecu.lambda2': 0.884})                                        # AFR 13.0 on petrol
        self.assertEqual(self.values(0x370, be((885, 2), (0, 1), (3, 1), (-50, 2), (0, 2)))['ecu.cam1_intake_deg'], -5.0)
        self.assertEqual(self.values(0x372, be((138, 2), (0, 2), (2000, 2), (850, 2))),
                         {'ecu.battery_v': 13.8, 'ecu.boost_target_kpa': 200.0, 'ecu.baro_kpa': 85.0})
        temps = self.values(0x3E0, be(((92 + 273) * 10, 2), ((-10 + 273) * 10, 2), ((30 + 273) * 10, 2), (0, 2)))
        self.assertEqual((temps['ecu.coolant_c'], temps['ecu.iat_c'], temps['ecu.fuel_temp_c']), (92.0, -10.0, 30.0))
        self.assertFalse(protocol.is_ecu(0x369))       # Declared but never filled by Speeduino


class HaltechProfileTests(unittest.TestCase):
    """Frames built from the Haltech ECU Broadcast CAN Protocol v2.0 table (big-endian;
    pressures absolute, temperatures in 0.1 K) and read back through the profile."""

    def setUp(self):
        self.before = protocol.ECU, protocol.OWNED
        protocol.use(ecu.load('haltech'), protocol.owned_ranges())    # 0x360-0x3E5: clear of every module

    def tearDown(self):
        protocol.use(*self.before)

    def values(self, can_id, *parts):
        return {k: v.value for k, v in protocol.decode(can_id, be(*parts)).items()}

    def test_engine_readings(self):
        # The document's own example: throttle raw 456 is 45.6 %.
        engine = self.values(0x360, (6200, 2), (2013, 2), (456, 2), (2013, 2))
        self.assertEqual((engine['ecu.rpm'], engine['ecu.map_kpa'], engine['ecu.throttle_pct']), (6200, 201.3, 45.6))
        self.assertAlmostEqual(engine['ecu.coolant_pressure_kpa'], 100.0)
        pressures = self.values(0x361, (4013, 2), (5013, 2), (0, 4))
        self.assertAlmostEqual(pressures['ecu.fuel_pressure_kpa'], 300.0)          # 401.3 kPa absolute
        self.assertAlmostEqual(pressures['ecu.oil_pressure_kpa'], 400.0)
        self.assertEqual(self.values(0x362, (0, 4), (-25, 2), (0, 2))['ecu.spark_deg'], -2.5)
        self.assertEqual(self.values(0x368, (850, 2), (1000, 2), (0, 4))['ecu.lambda1'], 0.85)
        speed = self.values(0x370, (1234, 2), (2, 1), (4, 1), (-55, 2), (0, 2))
        self.assertEqual((speed['ecu.vehicle_speed_kph'], speed['ecu.gear_selector'], speed['ecu.gear'], speed['ecu.cam1_intake_deg']),
                         (123.4, 2, 4, -5.5))
        self.assertEqual(self.values(0x372, (138, 2), (0, 2), (2500, 2), (850, 2)),
                         {'ecu.battery_v': 13.8, 'ecu.boost_target_kpa': 250.0, 'ecu.baro_kpa': 85.0})
        temps = self.values(0x3E0, (3652, 2), (2632, 2), (3032, 2), (3782, 2))
        for key, celsius in (('coolant_c', 92.05), ('iat_c', -9.95), ('fuel_temp_c', 30.05), ('oil_temp_c', 105.05)):
            self.assertAlmostEqual(temps[f'ecu.{key}'], celsius, places=6)

    def test_status_bits(self):
        bits = self.values(0x3E4, (0, 1), (0b00000101, 1), (0b10000000, 1), (0b01000001, 1), (0, 3), (0b10000010, 1))
        self.assertEqual((bits['ecu.brake_pedal'], bits['ecu.oil_pressure_light'], bits['ecu.launch_control'],
                          bits['ecu.traction_control_active'], bits['ecu.fan1'], bits['ecu.check_engine'], bits['ecu.hand_brake'],
                          bits['ecu.clutch_switch']), (1, 1, 1, 1, 1, 1, 1, 0))

    def test_it_runs_at_1_mbit(self):
        self.assertEqual(ecu.load('haltech').bitrate, 1000000)


class HolleyProfileTests(unittest.TestCase):
    """Frames as the Holley EFI 1st Party CAN protocol (rev 1) describes them: 29-bit IDs with
    the ECU's serial in the low 11 bits, a big-endian float value and a status byte."""

    SERIAL = 123

    def setUp(self):
        self.before = protocol.ECU, protocol.OWNED
        protocol.use(ecu.load('holley'), protocol.owned_ranges())

    def tearDown(self):
        protocol.use(*self.before)

    def frame(self, channel, value, status=0):
        ident = int(next(f for f in ecu.load('holley').data['frames'] if f['name'] == channel)['ids'][0], 16)
        return ident | self.SERIAL, struct.pack('>f', value) + bytes([0, 0, 0, status])

    def value(self, channel, value):
        ident, data = self.frame(channel, value)
        return {k: v.value for k, v in protocol.decode(ident, data, extended=True).items()}

    def test_the_documents_example_id(self):
        # "CAN ID = 0x1e02107b": target serial (channel) 8, source ECU, serial 123.
        self.assertEqual(0x1E02107B & 0x1FFFF800, 0x1E021000)
        self.assertEqual(self.frame('RPM', 0)[0] & 0x7FF, 123)

    def test_channels_converted_to_the_dash_units(self):
        self.assertEqual(self.value('RPM', 3450.0)['ecu.rpm'], 3450.0)
        self.assertAlmostEqual(self.value('CTS', 212.0)['ecu.coolant_c'], 100.0, places=5)
        self.assertAlmostEqual(self.value('MAT', -40.0)['ecu.iat_c'], -40.0, places=5)
        self.assertAlmostEqual(self.value('Oil_Pressure', 50.0)['ecu.oil_pressure_kpa'], 344.7379, places=3)
        self.assertAlmostEqual(self.value('Speed', 60.0)['ecu.vehicle_speed_kph'], 96.56064, places=4)
        self.assertAlmostEqual(self.value('AirFuel_Ratio', 12.5)['ecu.afr'], 12.5, places=5)
        self.assertEqual(self.value('Battery', 13.75)['ecu.battery_v'], 13.75)

    def test_it_is_read_from_29_bit_frames_only(self):
        ident, data = self.frame('RPM', 3000.0)
        self.assertEqual(protocol.decode(ident, data), {})                    # The same number as an 11-bit ID: not Holley's
        from hardware.frogdash.state import State
        state = State('socketcan', clock=lambda: 50.0, wall=lambda: 1794000000.0)
        state.connected = True
        state.ingest(ident, data, extended=True)
        self.assertEqual(state.snapshot()['values']['ecu.rpm']['value'], 3000.0)
        state.ingest(0x1E005000 | 7, data, extended=True)                     # Another Holley ECU's serial: still read
        state.ingest(0x18FF0000, bytes(8), extended=True)                     # Someone else's 29-bit frame: ignored
        self.assertEqual(state.ignored, 1)

    def test_sniper_has_its_own_ids(self):
        sniper, tx = ecu.load('holley_sniper'), ecu.load('holley')
        sniper_map = next(int(f['ids'][0], 16) for f in sniper.data['frames'] if f['name'] == 'MAP')
        self.assertEqual(tx.decode(sniper_map, struct.pack('>f', 1.0) + bytes(4)).keys(), {'ecu.knock_retard_deg', 'ecu.holley_status_knock_retard_deg'})


class AemProfileTests(unittest.TestCase):
    """Frames built from AEM's CAN data stream table (AEMnet v150609): 29-bit, big-endian, SI scalings."""

    def setUp(self):
        self.before = protocol.ECU, protocol.OWNED
        protocol.use(ecu.load('aem'), protocol.owned_ranges())

    def tearDown(self):
        protocol.use(*self.before)

    def values(self, can_id, *parts):
        return {k: v.value for k, v in protocol.decode(can_id, be(*parts), extended=True).items()}

    def test_engine_readings(self):
        engine = self.values(0x01F0A000, (7680, 2), (0, 2), (32768, 2), (-5, 1), (88, 1))
        self.assertAlmostEqual(engine['ecu.rpm'], 3000.0, places=0)                       # 7680 x 0.39063
        self.assertAlmostEqual(engine['ecu.throttle_pct'], 50.0, places=1)
        self.assertEqual((engine['ecu.iat_c'], engine['ecu.coolant_c']), (-5, 88))
        mix = self.values(0x01F0A003, (128, 1), (0, 1), (15908, 2), (3, 1), (85, 1), (57026, 2))
        self.assertEqual(mix['ecu.lambda1'], 1.0)                                         # 128 / 256 + 0.5
        self.assertAlmostEqual(mix['ecu.vehicle_speed_kph'], 100.0, places=1)
        self.assertAlmostEqual(mix['ecu.spark_deg'], 12.88, places=2)                     # 85 x 0.35156 - 17
        self.assertAlmostEqual(mix['ecu.battery_v'], 14.0, places=2)
        infinity = self.values(0x01F0A004, (1500, 2), (85, 1), (75, 1), (100, 1), (115, 1), (0b01000010, 1), (0b00001000, 1))
        self.assertEqual(infinity['ecu.map_kpa'], 150.0)
        self.assertAlmostEqual(infinity['ecu.fuel_pressure_kpa'], 75 * 0.580151 * 6.894757, places=3)
        self.assertEqual((infinity['ecu.fan1'], infinity['ecu.check_engine'], infinity['ecu.sync'], infinity['ecu.fuel_pump']), (1, 1, 1, 0))


class FuelTechProfileTests(unittest.TestCase):
    """Simplified packets as FTCAN 2.0 describes them: signed 16-bit big-endian measures with the
    MeasureID table's multipliers, 29-bit IDs for the FT500 and the FT600/550/450."""

    def setUp(self):
        self.before = protocol.ECU, protocol.OWNED
        protocol.use(ecu.load('fueltech'), protocol.owned_ranges())

    def tearDown(self):
        protocol.use(*self.before)

    def values(self, can_id, *parts):
        return {k: v.value for k, v in protocol.decode(can_id, be(*parts), extended=True).items()}

    def test_both_families(self):
        for base in (0x14000600, 0x14080600):
            first = self.values(base, (455, 2), (1850, 2), (-55, 2), (920, 2))     # TPS 45.5 %, MAP 1.850 bar
            self.assertEqual((first['ecu.throttle_pct'], first['ecu.iat_c'], first['ecu.coolant_c']), (45.5, -5.5, 92.0))
            self.assertAlmostEqual(first['ecu.map_kpa'], 185.0)
        pressures = self.values(0x14080601, (4500, 2), (3000, 2), (1200, 2), (-1, 2))
        self.assertAlmostEqual(pressures['ecu.oil_pressure_kpa'], 450.0)
        self.assertEqual(pressures['ecu.gear'], -1)                                   # Note 2: reverse
        engine = self.values(0x14080602, (870, 2), (6500, 2), (1052, 2), (0, 2))
        self.assertEqual((engine['ecu.lambda1'], engine['ecu.rpm'], engine['ecu.oil_temp_c']), (0.87, 6500, 105.2))
        self.assertEqual(self.values(0x14080607, (0, 2), (125, 2), (850, 2), (0, 2))['ecu.pw1_ms'], 8.5)

    def test_runs_at_1_mbit_with_29_bit_ids(self):
        profile = ecu.load('fueltech')
        self.assertEqual((profile.bitrate, profile.extended), (1000000, True))
        self.assertEqual(protocol.decode(0x14080600, bytes(8)), {})                   # Not as an 11-bit frame


class DecoderTests(unittest.TestCase):
    def test_each_layout(self):
        signals = [{'key': 'ecu.a', 'layout': 'u16le@0'}, {'key': 'ecu.b', 'layout': 's16le@2'},
                   {'key': 'ecu.c', 'layout': 'bit@4.7'}, {'key': 'ecu.d', 'layout': 'nib@5.4'},
                   {'key': 'ecu.e', 'layout': 's8@6', 'scale': 0.5, 'offset': -40}, {'key': 'ecu.f', 'layout': 'u8@7', 'scale': 2}]
        loaded = ecu.Profile(profile(frames=[frame(signals=signals)]))
        values = loaded.decode(0x360, bytes([0x34, 0x12, 0xFE, 0xFF, 0x80, 0xA5, 0xF6, 3]))
        self.assertEqual(values, {'ecu.a': 0x1234, 'ecu.b': -2, 'ecu.c': 1, 'ecu.d': 0xA, 'ecu.e': -45.0, 'ecu.f': 6})
        loaded = ecu.Profile(profile(frames=[frame(length=8, signals=[{'key': 'ecu.x', 'layout': 's32le@4', 'scale': 0.001}])]))
        self.assertEqual(loaded.decode(0x360, bytes(4) + (-1500).to_bytes(4, 'little', signed=True)), {'ecu.x': -1.5})

    def test_a_29_bit_ecu(self):
        loaded = ecu.Profile(profile(extended=True, frames=[frame(ids=['0x14080600'], signals=[{'key': 'ecu.rpm', 'layout': 'u16@0'}])]))
        self.assertTrue(loaded.is_ecu(0x14080600))
        with self.assertRaises(ecu.ProfileError):
            ecu.Profile(profile(frames=[frame(ids=['0x14080600'])]))     # Too big for 11 bits

    def test_a_profile_that_is_wrong_is_refused_saying_why(self):
        for data, said in ((profile(bitrate=300000), 'Bit rate'),
                           (profile(frames=[frame(signals=[{'key': 'ecu.rpm', 'layout': 'u32@6'}])]), 'runs past'),
                           (profile(frames=[frame(signals=[{'key': 'ecu.rpm', 'layout': 'u17@0'}])]), 'Layout'),
                           (profile(frames=[frame(signals=[{'key': 'vehicle.speed_kph', 'layout': 'u8@0'}])]), 'ecu.<name>'),
                           (profile(frames=[frame(), frame()]), 'listed twice'),
                           (profile(frames=[frame(signals=[{'key': 'ecu.rpm', 'layout': 'u8@0', 'scale': 0}])]), 'scale'),
                           (profile(frames=[]), 'at least one frame'),
                           (profile(id='Bad Name'), 'id'),
                           (profile(status='works great'), 'status')):
            with self.assertRaises(ecu.ProfileError) as caught:
                ecu.Profile(data)
            self.assertIn(said, str(caught.exception))

    def test_a_profile_may_not_take_the_modules_ids(self):
        for ids, claims in ((['0x300'], []), (['0x681'], []), (['0x360'], [['0x100', '0x1FF']])):
            loaded = ecu.Profile(profile(frames=[frame(ids=ids)], claims=claims))
            self.assertTrue(protocol.clashes(loaded))
            with self.assertRaises(ecu.ProfileError):
                protocol.use(loaded)
        self.assertEqual(protocol.ECU.id, 'megasquirt')               # Unchanged

    def test_another_ecu_is_read_and_megasquirt_frames_no_longer_are(self):
        other = ecu.Profile(profile(frames=[frame(ids=['0x360'], signals=[{'key': 'ecu.rpm', 'layout': 'u16@0'},
                                                                          {'key': 'ecu.map_kpa', 'layout': 'u16@2', 'scale': 0.1}])],
                                    timeout_s=0.5))
        before = protocol.ECU
        protocol.use(other)
        try:
            self.assertEqual({k: s.value for k, s in protocol.decode(0x360, bytes([0x0B, 0xB8, 0x03, 0xE8, 0, 0, 0, 0])).items()},
                             {'ecu.rpm': 3000, 'ecu.map_kpa': 100.0})
            self.assertEqual(protocol.decode(0x5E8, bytes(8)), {})
            self.assertEqual(protocol.timeout(0x360), 0.5)
            self.assertEqual(protocol.decode(0x300, bytes([1, 0, 0, 0, 0, 0, 0, 0]))['meth.state'].value, 'ARMED')   # Modules unchanged
        finally:
            protocol.use(before)

    def test_an_unknown_choice_falls_back_to_megasquirt_and_says_so(self):
        with self.assertRaises(ecu.ProfileError):
            ecu.load('../../etc/passwd')
        with self.assertRaises(ecu.ProfileError) as caught:
            ecu.load('no-such-ecu')
        self.assertIn('megasquirt', str(caught.exception))

    def test_the_profile_file_is_plain_json_others_can_copy(self):
        text = (ecu.BUILT_IN / 'megasquirt.json').read_text(encoding='utf-8')
        data = json.loads(text)
        self.assertEqual(data['id'], 'megasquirt')
        self.assertTrue(all(isinstance(i, str) and i.startswith('0x') for f in data['frames'] for i in f['ids']))


if __name__ == '__main__':
    unittest.main()
