"""Analog sensors on the ADS1115 (inputs.py, the system profile's `sensors`): straight-line
senders by two points, thermistors by three, a divider in front, and the profile's checks."""
import copy
import math
import unittest

from hardware.frogdash import sysconfig
from hardware.frogdash.inputs import Inputs, sensor_keys, sensor_value, steinhart
from hardware.frogdash.state import State

GM = [(9420, 0.0), (1459, 40.0), (177, 100.0)]      # A GM-style coolant sender's published table


def sensors(**chosen):
    out = copy.deepcopy(sysconfig.preset('generic')['sensors'])
    for channel, spec in chosen.items():
        out[channel].update(spec)
    return out


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


OIL = {'type': 'linear', 'reading': 'oil_pressure', 'v1_mv': 500, 'v1_value': 0.0, 'v2_mv': 4500, 'v2_value': 100.0}
COOLANT = {'type': 'thermistor', 'reading': 'coolant', 'pullup_ohm': 2200, 'supply_mv': 5000,
           'r1_ohm': 9420, 't1_c': 0.0, 'r2_ohm': 1459, 't2_c': 40.0, 'r3_ohm': 177, 't3_c': 100.0}


class ConversionTests(unittest.TestCase):
    def test_a_straight_line_sender(self):
        spec = sensors(a1=OIL)['a1']
        self.assertEqual(sensor_value(spec, 500), 0)
        self.assertEqual(sensor_value(spec, 2500), 50)
        self.assertEqual(sensor_value(spec, 4500), 100)

    def test_a_thermistor_gives_back_its_own_points(self):
        spec = sensors(a0=COOLANT)['a0']
        a, b, c = steinhart([(r, t) for r, t in GM])
        for ohms, celsius in GM:
            self.assertAlmostEqual(1 / (a + b * math.log(ohms) + c * math.log(ohms) ** 3) - 273.15, celsius, places=6)
            mv = 5000 * ohms / (ohms + 2200)                      # The voltage at the input, through the pull-up
            self.assertAlmostEqual(sensor_value(spec, mv), celsius, places=6)
        self.assertGreater(sensor_value(spec, 5000 * 667 / (667 + 2200)), 55)    # 60 degC on GM's table, between the points
        self.assertIsNone(sensor_value(spec, 4999.9))             # Open circuit: the pull-up's full voltage
        self.assertIsNone(sensor_value(spec, 0))                  # Shorted to ground


class InputsTests(unittest.TestCase):
    def test_the_dash_reading_through_a_divider(self):
        clock = Clock()
        inputs = Inputs({}, sensors(a2={**OIL, 'divider_pct': 66}), clock=clock)
        self.assertEqual(inputs.adc_inputs(), [2])
        for _ in range(3):
            inputs.analog('a2', 2500 * .66)                       # 2.5 V at the sender, 1.65 V at the input
        out = inputs.values({}, 1)
        self.assertEqual((round(out['engine.oil_pressure_psi']['value'], 3), out['engine.oil_pressure_psi']['quality']), (50, 'live'))
        view = inputs.view()['sensors']['a2']
        self.assertEqual((view['key'], view['volts']), ('engine.oil_pressure_psi', 2.5))
        clock.now += 5
        self.assertEqual(inputs.values({}, 1)['engine.oil_pressure_psi']['quality'], 'stale')

    def test_a_broken_wire_is_a_fault_and_custom_readings_have_their_own_key(self):
        inputs = Inputs({}, sensors(a0=COOLANT, a3={**OIL, 'reading': 'custom', 'unit': 'v'}))
        inputs.analog('a0', 4999.9)
        self.assertEqual(inputs.values({}, 1)['engine.coolant_c']['quality'], 'fault')
        self.assertEqual(sensor_keys(inputs.sensors), ['engine.coolant_c', 'sensor.a3_v'])
        self.assertEqual(sensor_keys(sensors(a1={**COOLANT, 'reading': 'custom'})), ['sensor.a1_c'])

    def test_fuel_and_sensors_share_the_ads1115(self):
        signals = copy.deepcopy(sysconfig.preset('generic')['signals'])
        signals['fuel'].update(source='adc', adc_channel=0)
        inputs = Inputs(signals, sensors(a1=OIL, a3=COOLANT))
        self.assertEqual(inputs.adc_inputs(), [0, 1, 3])

    def test_the_dash_shows_it(self):
        clock = Clock()
        state = State(clock=clock, wall=lambda: 1000.0)
        state.inputs = Inputs({}, sensors(a1=OIL), clock=clock)
        state.inputs.analog('a1', 1300)
        values = state.snapshot()['values']
        self.assertEqual((round(values['engine.oil_pressure_psi']['value'], 3), values['engine.oil_pressure_psi']['quality']), (20, 'live'))


class ProfileTests(unittest.TestCase):
    def profile(self, **chosen):
        p = sysconfig.preset('generic')
        p['sensors'] = sensors(**chosen)
        return p

    def test_a_good_profile_and_setup_is_told_to_switch_i2c_on(self):
        p = sysconfig.validate(self.profile(a0={**COOLANT, 't1_c': -40.0, 'r1_ohm': 100700}, a1=OIL))
        self.assertIn("FD_ADC_INPUTS='1'", sysconfig.shell(p))
        self.assertIn("FD_ADC_INPUTS='0'", sysconfig.shell(sysconfig.validate(sysconfig.preset('generic'))))

    def test_mistakes_are_refused(self):
        fuel = self.profile(a0=OIL)
        fuel['signals']['fuel'].update(source='adc', adc_channel=0)
        for bad in (fuel,                                                       # The fuel sender's input
                    self.profile(a0={**OIL, 'v2_mv': 500}),                     # Two points at one voltage
                    self.profile(a0={**COOLANT, 'reading': 'oil_pressure'}),    # A thermistor is a temperature
                    self.profile(a0={**COOLANT, 't2_c': 200.0}),                # Points not from cold to hot
                    self.profile(a0=OIL, a1=OIL),                               # The same reading twice
                    self.profile(a0={**OIL, 'v1_value': 'zero'}),
                    self.profile(a0={**OIL, 'divider_pct': 0}),
                    self.profile(a0={**OIL, 'name': 'no;semicolons'}),
                    self.profile(a0={**OIL, 'type': 'magic'})):
            with self.assertRaises(sysconfig.ProfileError):
                sysconfig.validate(bad)

    def test_an_older_profile_has_none(self):
        saved = sysconfig.preset('foxbody')
        del saved['sensors']
        self.assertEqual({s['type'] for s in sysconfig.complete(saved)['sensors'].values()}, {'none'})


if __name__ == '__main__':
    unittest.main()
