"""Car signals from Pi pins, an ADS1115, any CAN frame or the ECU (hardware/frogdash/inputs.py)."""
import copy
import unittest

from hardware.frogdash import sysconfig
from hardware.frogdash.inputs import FLASH_HOLD_S, Inputs
from hardware.frogdash.state import State


def signals(**chosen):
    out = copy.deepcopy(sysconfig.preset('generic')['signals'])
    for name, spec in chosen.items():
        out[name].update(spec)
    return out


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class InputsTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()

    def make(self, **chosen):
        return Inputs(signals(**chosen), clock=self.clock)

    def test_a_bit_of_any_can_frame(self):
        inputs = self.make(brake={'source': 'can', 'can_id': 0x3A0, 'bit': 13}, reverse={'source': 'can', 'can_id': 0x3A0, 'bit': 0})
        inputs.ingest(0x3A0, bytes([0x00, 0x20, 0, 0]))
        out = inputs.values({}, 1)
        self.assertEqual((out['lighting.brake']['value'], out['lighting.brake']['quality']), (True, 'live'))
        self.assertEqual(out['lighting.reverse']['value'], False)
        self.clock.now += 2
        self.assertEqual(inputs.values({}, 1)['lighting.brake']['quality'], 'stale')

    def test_fuel_from_a_can_byte(self):
        inputs = self.make(fuel={'source': 'can', 'can_id': 0x18FEFC17, 'byte': 1, 'full_raw': 255})
        inputs.ingest(0x18FEFC17, bytes([0, 51, 0]))
        self.assertEqual(inputs.values({}, 1)['vehicle.fuel_pct']['value'], 20.0)

    def test_pins_active_low_and_high(self):
        inputs = self.make(brake={'source': 'gpio', 'pin': 17, 'active_low': True}, lights={'source': 'gpio', 'pin': 27, 'active_low': False})
        self.assertEqual(inputs.pins(), {17: True, 27: False})
        inputs.gpio({17: False, 27: True})
        out = inputs.values({}, 1)
        self.assertTrue(out['lighting.brake']['value'])
        self.assertTrue(out['lighting.running']['value'])
        inputs.gpio({17: True, 27: False})
        out = inputs.values({}, 1)
        self.assertFalse(out['lighting.brake']['value'])
        self.assertFalse(out['lighting.running']['value'])

    def test_a_flashing_turn_signal_stays_on_between_flashes(self):
        inputs = self.make(turn_left={'source': 'gpio', 'pin': 5, 'active_low': True})
        inputs.gpio({5: False})                       # Lamp on
        self.clock.now += 0.35
        inputs.gpio({5: True})                        # Flasher off time
        self.assertTrue(inputs.values({}, 1)['lighting.turn_left']['value'])
        self.clock.now += FLASH_HOLD_S + 0.1
        inputs.gpio({5: True})
        self.assertFalse(inputs.values({}, 1)['lighting.turn_left']['value'])

    def test_fuel_sender_volts_to_percent_averaged(self):
        inputs = self.make(fuel={'source': 'adc', 'adc_channel': 1, 'empty_mv': 3000, 'full_mv': 500})   # Falls as it fills
        inputs.adc(3000)
        self.assertEqual(inputs.values({}, 1)['vehicle.fuel_pct']['value'], 0.0)
        for _ in range(40):
            inputs.adc(1750)
        self.assertEqual(inputs.values({}, 1)['vehicle.fuel_pct']['value'], 50.0)
        inputs.adc(9000)                              # One wild reading barely moves it, and never past full
        self.assertLess(inputs.values({}, 1)['vehicle.fuel_pct']['value'], 50.0)

    def test_from_the_ecu(self):
        inputs = self.make(brake={'source': 'ecu'}, fuel={'source': 'ecu'})
        values = {'ecu.brake_pedal': {'value': 1, 'quality': 'live', 'source_id': 0x3E4, 'timestamp_ms': 1},
                  'ecu.fuel_level_pct': {'value': 41.5, 'quality': 'live', 'source_id': 0x207, 'timestamp_ms': 1}}
        out = inputs.values(values, 1)
        self.assertEqual((out['lighting.brake']['value'], out['lighting.brake']['source']), (True, 'ECU'))
        self.assertEqual(out['vehicle.fuel_pct']['value'], 41.5)
        self.assertEqual(inputs.values({}, 1)['lighting.brake']['quality'], 'unavailable')

    def test_module_and_none_are_left_alone(self):
        inputs = Inputs(sysconfig.preset('foxbody')['signals'], clock=self.clock)
        self.assertEqual(inputs.values({}, 1), {})
        self.assertEqual(Inputs(signals(), clock=self.clock).values({}, 1), {})

    def test_a_reader_that_fails_says_why(self):
        inputs = self.make(brake={'source': 'gpio', 'pin': 17})
        inputs.failed(['brake'], 'python3-libgpiod is not installed yet')
        self.assertEqual(inputs.view()['brake']['problem'], 'python3-libgpiod is not installed yet')
        inputs.gpio({17: False})
        self.assertIsNone(inputs.view()['brake']['problem'])

    def test_the_dash_shows_them_as_the_boards_readings(self):
        state = State(clock=self.clock, wall=lambda: 1000.0)
        state.inputs = Inputs(signals(reverse={'source': 'can', 'can_id': 0x6A1, 'bit': 7}), clock=self.clock)
        state.ingest(0x6A1, bytes([0x80]))
        values = state.snapshot()['values']
        self.assertEqual((values['lighting.reverse']['value'], values['lighting.reverse']['quality']), (True, 'live'))


class HighBeamAndParkingBrakeTests(unittest.TestCase):
    """No board gives them: from a pin, a CAN bit or the ECU, shown only where set up."""
    def setUp(self):
        self.clock = Clock()

    def test_from_a_pin_a_can_bit_and_the_ecu(self):
        inputs = Inputs(signals(highbeam={'source': 'gpio', 'pin': 22, 'active_low': True},
                                parking_brake={'source': 'can', 'can_id': 0x3B0, 'bit': 9}), clock=self.clock)
        inputs.gpio({22: False})
        inputs.ingest(0x3B0, bytes([0, 0x02]))
        out = inputs.values({}, 1)
        self.assertEqual((out['lighting.highbeam']['value'], out['lighting.parking_brake']['value']), (True, True))
        ecu = Inputs(signals(highbeam={'source': 'ecu'}, parking_brake={'source': 'ecu'}), clock=self.clock)
        out = ecu.values({'ecu.high_beam': {'value': 0, 'quality': 'live'}, 'ecu.parking_brake': {'value': 1, 'quality': 'live'}}, 1)
        self.assertEqual((out['lighting.highbeam']['value'], out['lighting.parking_brake']['value']), (False, True))

    def test_the_dash_shows_them_only_where_set_up(self):
        profile = sysconfig.preset('generic')
        self.assertEqual({k: sysconfig.ui_features(profile)[k] for k in ('highbeam', 'parking_brake')},
                         {'highbeam': False, 'parking_brake': False})
        profile['signals'] = signals(parking_brake={'source': 'gpio', 'pin': 23})
        self.assertTrue(sysconfig.ui_features(sysconfig.validate(profile))['parking_brake'])
        car = sysconfig.validate(sysconfig.preset('foxbody'))
        self.assertFalse(sysconfig.ui_features(car)['highbeam'])

    def test_no_board_gives_them_and_their_pins_are_checked(self):
        for name in ('highbeam', 'parking_brake'):
            profile = sysconfig.preset('generic')
            profile['signals'] = signals(**{name: {'source': 'module'}})
            with self.assertRaises(sysconfig.ProfileError):
                sysconfig.validate(profile)
        profile = sysconfig.preset('generic')
        profile['signals'] = signals(brake={'source': 'gpio', 'pin': 17}, highbeam={'source': 'gpio', 'pin': 17})
        with self.assertRaises(sysconfig.ProfileError):
            sysconfig.validate(profile)

    def test_a_saved_profile_without_them_gets_none(self):
        saved = sysconfig.preset('foxbody')
        for name in ('highbeam', 'parking_brake'):
            del saved['signals'][name]
        self.assertEqual(sysconfig.complete(saved)['signals']['highbeam']['source'], 'none')

    def test_driving_with_the_parking_brake_on_alerts(self):
        from hardware.frogdash import alerts
        rule = alerts.RULES['parking_brake']
        snapshot = lambda kph, on: {'values': {'vehicle.speed_kph': {'value': kph, 'quality': 'live'},
                                               'lighting.parking_brake': {'value': on, 'quality': 'live'}}}
        settings = alerts.rule_defaults(rule)
        self.assertTrue(alerts.clauses(rule, settings, snapshot(30, True)))
        self.assertFalse(alerts.clauses(rule, settings, snapshot(3, True)))
        self.assertFalse(alerts.clauses(rule, settings, snapshot(30, False)))


class SignalProfileTests(unittest.TestCase):
    def profile(self, **chosen):
        p = sysconfig.preset('generic')
        p['signals'] = signals(**chosen)
        return p

    def test_pins_the_can_board_or_i2c_use_are_refused(self):
        for pin in (25, 2, 3, 8, 14):
            with self.assertRaises(sysconfig.ProfileError, msg=pin):
                sysconfig.validate(self.profile(brake={'source': 'gpio', 'pin': pin}))
        sysconfig.validate(self.profile(brake={'source': 'gpio', 'pin': 17}))

    def test_one_pin_one_signal(self):
        with self.assertRaises(sysconfig.ProfileError):
            sysconfig.validate(self.profile(brake={'source': 'gpio', 'pin': 17}, reverse={'source': 'gpio', 'pin': 17}))

    def test_sources_are_checked(self):
        with self.assertRaises(sysconfig.ProfileError):
            sysconfig.validate(self.profile(brake={'source': 'adc'}))       # The ADS1115 is for the fuel level
        with self.assertRaises(sysconfig.ProfileError):
            sysconfig.validate(self.profile(fuel={'source': 'adc', 'empty_mv': 1000, 'full_mv': 1000}))

    def test_setup_is_told_what_to_install(self):
        env = sysconfig.shell(sysconfig.validate(self.profile(brake={'source': 'gpio', 'pin': 17}, fuel={'source': 'adc'})))
        self.assertIn("FD_GPIO_INPUTS='1'", env)
        self.assertIn("FD_ADC_INPUTS='1'", env)
        car = sysconfig.shell(sysconfig.validate(sysconfig.preset('foxbody')))
        self.assertIn("FD_GPIO_INPUTS='0'", car)


if __name__ == '__main__':
    unittest.main()
