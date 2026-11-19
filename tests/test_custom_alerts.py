"""Alerts of the owner's own (the alert builder): any reading above or below a limit, checked,
latched and shown like the built-in ones, saved in the alert settings."""
import unittest

from hardware.frogdash import alerts
from hardware.frogdash.driving import Driving
from hardware.frogdash.state import State

TRANS = {'key': 'u1', 'name': 'Trans hot', 'signal': 'ecu.transmission_temp_c', 'op': '>', 'limit': 110,
         'severity': 'warning', 'running': True}


def snapshot(**values):
    return {'timestamp_ms': 1, 'mode': 'socketcan', 'values': {k: {'value': v, 'quality': 'live'} for k, v in values.items()}}


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class SettingsTests(unittest.TestCase):
    def test_an_alert_of_your_own_becomes_a_rule(self):
        settings = alerts.validate_settings({'version': 2, 'rules': {}, 'custom': [TRANS]})
        self.assertEqual(settings['rules']['u1'], {'enabled': True, 'delay': 2.0, 'limit': 110})
        rule = alerts.all_rules(settings)['u1']
        self.assertEqual((rule['code'], rule['title'], rule['group'], rule['show']), ('USR-01', 'TRANS HOT', 'custom', ['ecu.transmission_temp_c', 'temp']))
        self.assertEqual(rule['when'][0], ['engine.rpm', '>=', alerts.RUNNING_RPM])     # Only with the engine running

    def test_its_limit_and_delay_are_set_like_the_built_in_ones(self):
        settings = alerts.validate_settings({'version': 2, 'rules': {'u1': {'limit': 95.5, 'delay': 5, 'enabled': False}}, 'custom': [TRANS]})
        self.assertEqual(settings['rules']['u1'], {'enabled': False, 'delay': 5, 'limit': 95.5})
        with self.assertRaises(ValueError):          # Settings for an alert that is not there
            alerts.validate_settings({'version': 2, 'rules': {'u2': {'limit': 1}}, 'custom': [TRANS]})

    def test_bad_definitions_are_refused(self):
        for bad in ({**TRANS, 'op': '=='}, {**TRANS, 'signal': 'no dots'}, {**TRANS, 'key': 'x1'}, {**TRANS, 'name': ''},
                    {**TRANS, 'limit': float('nan')}, {**TRANS, 'severity': 'loud'}, {**TRANS, 'running': 'yes'}, {**TRANS, 'extra': 1}):
            with self.assertRaises(ValueError, msg=bad):
                alerts.validate_settings({'version': 2, 'rules': {}, 'custom': [bad]})
        with self.assertRaises(ValueError):
            alerts.validate_settings({'version': 2, 'rules': {}, 'custom': [TRANS, TRANS]})          # The same key twice
        with self.assertRaises(ValueError):
            alerts.validate_settings({'version': 2, 'rules': {}, 'custom': [{**TRANS, 'key': f'u{n}'} for n in range(1, 26)]})

    def test_old_settings_have_none(self):
        self.assertEqual(alerts.validate_settings({'version': 2, 'rules': {}})['custom'], [])


class DrivingTests(unittest.TestCase):
    def test_it_goes_off_after_its_delay_and_goes_away_when_deleted(self):
        clock = Clock()
        driving = Driving(State(clock=clock, wall=lambda: 1000.0))
        driving.configure({'version': 2, 'rules': {}, 'custom': [TRANS]})
        hot = snapshot(**{'engine.rpm': 2000, 'ecu.transmission_temp_c': 120})
        driving.evaluate(hot)
        self.assertFalse(driving.alerts['u1']['active'])
        clock.now += 2.5
        driving.evaluate(hot)
        alert = driving.alerts['u1']
        self.assertTrue(alert['active'])
        self.assertEqual((alert['code'], alert['value']), ('USR-01', 120))
        self.assertEqual(driving.history[-1]['label'], 'TRANS HOT')                      # Marked in the log
        driving.evaluate(snapshot(**{'engine.rpm': 0, 'ecu.transmission_temp_c': 120}))    # Engine off: not with running
        self.assertEqual(driving.alerts['u1']['condition'], 'normal')
        driving.configure({'version': 2, 'rules': {}, 'custom': []})
        self.assertNotIn('u1', driving.alerts)
        self.assertNotIn('u1', {a['key'] for a in driving.snapshot()['alerts']})

    def test_below_a_limit(self):
        clock = Clock()
        driving = Driving(State(clock=clock, wall=lambda: 1000.0))
        low = {**TRANS, 'key': 'u3', 'name': 'Low boost', 'signal': 'engine.boost_kpa', 'op': '<', 'limit': 10, 'running': False}
        driving.configure({'version': 2, 'rules': {'u3': {'delay': 0}}, 'custom': [low]})
        driving.evaluate(snapshot(**{'engine.boost_kpa': 5}))
        self.assertTrue(driving.alerts['u3']['active'])
        self.assertEqual(alerts.all_rules(driving.settings)['u3']['code'], 'USR-03')


if __name__ == '__main__':
    unittest.main()
