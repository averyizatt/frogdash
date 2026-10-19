"""The drive summary (summary.py): a drive starts when the engine runs, keeps its figures,
and ends when the PiSugar reports the key off; it is saved and written to the event log."""
import json
from pathlib import Path
import tempfile
import unittest

from hardware.frogdash.eventlog import EventLog
from hardware.frogdash.summary import DriveSummary


class Clock:
    def __init__(self):
        self.now = 1792060000.0

    def __call__(self):
        return self.now


class Trip:
    def __init__(self):
        self.km = 1000.0

    def snapshot(self):
        return {'odometer_km': self.km}


class FakeState:
    def __init__(self, folder, clock):
        self.trip = Trip()
        self.eventlog = EventLog(self, Path(folder) / 'events', wall=clock, clock=clock)
        self.health = None


def snap(rpm=None, speed=None, boost=None, coolant=None, oil=None, meth='ARMED', knock=False, key=True, alerts=()):
    v = lambda value: {'value': value, 'quality': 'live'}
    values = {'meth.state': v(meth), 'knock.warning': v(knock), 'knock.critical': v(False)}
    for key_name, value in (('engine.rpm', rpm), ('vehicle.speed_kph', speed), ('engine.boost_kpa', boost),
                            ('engine.coolant_c', coolant), ('engine.oil_pressure_psi', oil)):
        if value is not None:
            values[key_name] = v(value)
    return {'values': values, 'system': {'ups': {'available': True, 'input_present': key}},
            'drive': {'alerts': [{'key': name, 'active': True} for name in alerts]}}


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.state = FakeState(self.folder.name, self.clock)
        self.summary = DriveSummary(self.state, self.folder.name, clock=self.clock, wall=self.clock)

    def tearDown(self):
        self.folder.cleanup()

    def run_for(self, seconds, **kwargs):
        for _ in range(int(seconds * 2)):
            self.summary.sample(snap(**kwargs))
            self.clock.now += .5

    def test_a_drive_from_engine_start_to_key_off(self):
        self.run_for(5)                                                       # Key on, engine off: no drive
        self.assertIsNone(self.summary.current)
        self.run_for(2, rpm=850, speed=0, coolant=60, oil=45)
        self.assertIsNotNone(self.summary.current)
        self.state.trip.km += 12.5
        self.run_for(3, rpm=4200, speed=96, boost=52, coolant=94, oil=38, meth='SPRAYING', knock=True)
        self.run_for(2, rpm=2000, speed=70, boost=10, coolant=97, oil=35, alerts=('knock',))
        self.run_for(1, rpm=1800, speed=60, knock=True)                       # A second knock event
        self.state.eventlog.write('warn', 'gps', 'GPS has a position but no speed')
        self.summary.sample(snap(rpm=800, speed=0, key=False))                 # Key off: the PiSugar countdown
        d = self.summary.last
        self.assertIsNone(self.summary.current)
        self.assertEqual((d['distance_km'], d['top_speed_kph'], d['peak_boost_kpa'], d['max_rpm'], d['max_coolant_c']),
                         (12.5, 96, 52, 4200, 97))
        self.assertEqual((d['min_oil_psi'], d['meth_spray_s'], d['knock_events'], d['alerts'], d['problems'], d['ended_by']),
                         (35, 3.0, 2, 1, 1, 'ignition off'))
        self.assertEqual(json.loads((Path(self.folder.name) / 'last-drive.json').read_text())['max_rpm'], 4200)
        logged = [e for e in self.state.eventlog.recent if e['area'] == 'drive']
        self.assertEqual(logged[-1]['text'], 'Drive ended: 7.8 mi, 0 min, top 60 mph, peak boost 7.5 psi, meth 3 s, 2 knock')
        # Back on, engine off: the ended drive stays as the last one; a new one needs the engine.
        self.run_for(3, key=True)
        self.assertIsNone(self.summary.current)
        self.assertEqual(DriveSummary(self.state, self.folder.name).last['max_rpm'], 4200)   # Kept across restarts

    def test_a_blip_of_rpm_is_not_a_drive_and_the_dash_stopping_ends_one(self):
        self.summary.sample(snap(rpm=900))
        self.clock.now += .5
        self.summary.sample(snap(rpm=0))
        self.assertIsNone(self.summary.current)
        self.run_for(2, rpm=900)
        self.summary.finish('dash stopped')
        self.assertEqual(self.summary.last['ended_by'], 'dash stopped')


if __name__ == '__main__':
    unittest.main()
