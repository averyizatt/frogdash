import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from hardware.frogdash.gps import GPS
from hardware.frogdash.nav import Navigator, RoadMap, bearing, distance_m
from hardware.frogdash.state import State


class Clock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now


# An L-shaped road: 222 m north along -108.5990, then east along 39.0030.
ROADS = {'bounds': [39.0, -108.6, 39.1, -108.5], 'scale': 100000, 'names': [''],
         'ways': [[3, 0, [100, 100, 200, 0]], [3, 0, [300, 100, 0, 400]], [5, 0, [50, 50, 10, 10]]]}


class Rig:
    """A State with a USB GPS and a sensor gateway, stepped at 10 Hz."""
    def __init__(self, folder, roads=True, saved=None):
        self.clock = Clock()
        self.state = State(clock=self.clock)
        self.state.connected = True
        self.state.gps = GPS(clock=self.clock)
        self.state.gps.connected = True
        maps = Path(folder) / 'maps'
        maps.mkdir(exist_ok=True)
        if roads:
            (maps / 'index.json').write_text(json.dumps([{'name': 'test'}]))
            (maps / 'test.json').write_text(json.dumps(ROADS))
        self.state.nav = Navigator(self.clock, self.state.wall, saved, maps)
        self.values = {}

    def run(self, seconds, wheel_kph=None, fix=None, wheel_valid=True):
        for _ in range(round(seconds * 10)):
            if wheel_kph is not None:
                self.state.ingest(0x500, round(wheel_kph * 10).to_bytes(2, 'big') + bytes(4) + bytes([255, 1 if wheel_valid else 0]))
            if fix:
                lat, lon, kph, track = fix
                self.state.gps.update({'class': 'TPV', 'mode': 3, 'lat': lat, 'lon': lon, 'speed': kph / 3.6, 'track': track, 'device': '/dev/ttyACM0'})
            else:
                self.state.gps.update({'class': 'TPV', 'mode': 1, 'device': '/dev/ttyACM0'})
            self.values = self.state.snapshot()['values']
            self.clock.now += .1
        return self.values


class NavigatorTests(unittest.TestCase):
    def test_wheel_speed_is_calibrated_then_fills_gps_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            rig = Rig(folder, roads=False)
            values = rig.run(30, wheel_kph=90, fix=(39.0012, -108.5990, 100, 0))   # Wheel reads 10% low.
            self.assertEqual((values['nav.source']['value'], values['nav.speed_source']['value']), ('gps', 'gps'))
            self.assertAlmostEqual(rig.state.nav.scale, 100 / 90, delta=.01)
            values = rig.run(1, wheel_kph=45)                                        # Fix lost.
            speed = values['vehicle.speed_kph']
            self.assertEqual((speed['quality'], speed['source'], values['nav.speed_source']['value']), ('live', 'Wheel speed (GPS lost)', 'wheel'))
            self.assertAlmostEqual(speed['value'], 50, delta=.6)
            self.assertEqual(values['gps.latitude']['quality'], 'unavailable')       # Raw GPS stays honest.

    def test_dead_reckoning_straight_without_a_map_and_snaps_back(self):
        with tempfile.TemporaryDirectory() as folder:
            rig = Rig(folder, roads=False)
            rig.run(2, wheel_kph=36, fix=(39.05, -108.55, 36, 90))
            values = rig.run(10, wheel_kph=36)                                       # 10 m/s east for 10 s.
            self.assertEqual(values['nav.source']['value'], 'estimated')
            here = (values['nav.latitude']['value'], values['nav.longitude']['value'])
            self.assertAlmostEqual(distance_m((39.05, -108.55), here), 100, delta=3)
            self.assertAlmostEqual(bearing((39.05, -108.55), here), 90, delta=1)
            self.assertGreater(values['nav.accuracy_m']['value'], 20)                # Off-map estimate: low confidence.
            values = rig.run(.2, wheel_kph=36, fix=(39.0501, -108.5488, 36, 90))
            self.assertEqual((values['nav.source']['value'], values['nav.latitude']['value']), ('gps', 39.0501))
            self.assertEqual(rig.state.nav.since_fix_m, 0)

    def test_follows_the_road_round_a_corner(self):
        with tempfile.TemporaryDirectory() as folder:
            rig = Rig(folder)
            rig.run(2, wheel_kph=50, fix=(39.0012, -108.59901, 50, 2))               # Northbound, 200 m before the corner.
            values = rig.run(20, wheel_kph=50)                                       # 278 m with no GPS.
            self.assertTrue(rig.state.nav.on_road)
            self.assertAlmostEqual(values['nav.latitude']['value'], 39.0030, delta=.00005)
            self.assertAlmostEqual(values['nav.longitude']['value'], -108.5981, delta=.0002)
            self.assertAlmostEqual(values['nav.track_deg']['value'], 90, delta=2)
            self.assertLess(values['nav.accuracy_m']['value'], 40)

    def test_stopped_holds_position_and_unknown_wheel_speed_is_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            rig = Rig(folder, roads=False)
            rig.run(2, wheel_kph=40, fix=(39.05, -108.55, 40, 0))
            values = rig.run(5, wheel_kph=0, wheel_valid=False)                      # No pulses: stopped.
            self.assertEqual((values['vehicle.speed_kph']['value'], values['nav.latitude']['value']), (0, 39.05))
            fresh = Rig(folder, roads=False)
            values = fresh.run(2, wheel_kph=0, wheel_valid=False)                    # Sensor never seen working.
            self.assertEqual((values['vehicle.speed_kph']['quality'], values['nav.source']['value']), ('unavailable', 'none'))

    def test_without_wheel_speed_brief_dropouts_are_bridged_then_it_stops_guessing(self):
        with tempfile.TemporaryDirectory() as folder:
            rig = Rig(folder, roads=False)
            rig.run(2, fix=(39.05, -108.55, 72, 0))                                  # 20 m/s north, no speed sensor at all.
            values = rig.run(2)
            speed = values["vehicle.speed_kph"]
            self.assertEqual((speed["quality"], speed["value"], values["nav.speed_source"]["value"]), ("live", 72, "held"))
            self.assertEqual(values["nav.source"]["value"], "estimated")
            self.assertGreater(values["nav.latitude"]["value"], 39.0502)             # Carried on northwards.
            values = rig.run(6)                                                      # Longer than the hold: no more guessing.
            self.assertEqual((values["vehicle.speed_kph"]["quality"], values["nav.source"]["value"]), ("unavailable", "last-known"))
            frozen = values["nav.latitude"]["value"]
            self.assertEqual(rig.run(3)["nav.latitude"]["value"], frozen)

    def test_last_position_and_calibration_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            saved = Path(folder) / 'nav.json'
            rig = Rig(folder, roads=False, saved=saved)
            rig.run(30, wheel_kph=90, fix=(39.07, -108.56, 100, 270))
            asyncio.run(rig.state.nav.save())
            again = Rig(folder, roads=False, saved=saved)
            values = again.run(1)
            self.assertEqual((values['nav.source']['value'], values['nav.latitude']['quality']), ('last-known', 'stale'))
            self.assertAlmostEqual(again.state.nav.scale, 100 / 90, delta=.01)
            values = again.run(10, wheel_kph=32.4)                                   # Drives off before the first fix.
            self.assertEqual(values['nav.source']['value'], 'estimated')
            self.assertLess(values['nav.longitude']['value'], -108.56)               # Heading 270: west.

    def test_bundled_map_loads_and_snaps(self):
        nav = Navigator(Clock(), lambda: 0)
        roads = nav.load_roads()
        self.assertIsInstance(roads, RoadMap)
        way = max(roads.ways, key=len)
        middle = way[len(way) // 2]
        self.assertIsNotNone(roads.snap(middle, bearing(way[len(way) // 2 - 1], middle)))


class GpsInputTests(unittest.TestCase):
    def test_follows_a_receiver_that_reappears_under_a_new_name(self):
        clock = Clock()
        gps = GPS(clock=clock)
        gps.connected = True

        def fix(device):
            return {"class": "TPV", "mode": 3, "lat": 39.0, "lon": -108.5, "speed": 5, "device": device}

        gps.update(fix("/dev/ttyACM0"))
        clock.now += 3
        gps.update(fix("/dev/ttyACM1"))                 # Another receiver while the first is still recent: ignored.
        self.assertEqual(gps.device, "/dev/ttyACM0")
        clock.now += 11
        gps.update(fix("/dev/ttyACM1"))                 # The first has been silent for over 10 s: follow the new name.
        self.assertEqual((gps.device, gps.values()["gps.latitude"]["quality"]), ("/dev/ttyACM1", "live"))
        named = GPS(clock=clock, device="/dev/ttyUSB0")
        named.update(fix("/dev/ttyUSB0"))
        clock.now += 30
        named.update(fix("/dev/ttyACM1"))
        self.assertEqual(named.device, "/dev/ttyUSB0")  # A receiver named by the user is never replaced.


if __name__ == "__main__":
    unittest.main()
