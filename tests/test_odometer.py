import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.trip import Trip

MI = 1.609344


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


def moving(kph):
    return {'values': {'vehicle.speed_kph': {'value': kph, 'quality': 'live'}}}


class OdometerTests(unittest.TestCase):
    def test_unset_until_entered_then_follows_distance_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = Clock()
            state = State(clock=clock)
            trip = Trip(state, Path(folder) / 'trip.json')
            self.assertIsNone(trip.snapshot()['odometer_km'])
            trip.set_odometer(67456 * MI)
            for _ in range(3601):                    # One hour at 96.56 km/h (60 mph).
                trip.sample(moving(60 * MI)); clock.now += 1
            self.assertAlmostEqual(trip.odometer_km / MI, 67516, delta=.1)
            asyncio.run(trip.save(force=True))
            self.assertIn('odometer_km', json.loads((Path(folder) / 'trip.json').read_text()))
            again = Trip(state, Path(folder) / 'trip.json')
            self.assertAlmostEqual(again.odometer_km / MI, 67516, delta=.1)
            with self.assertRaises(ValueError):
                trip.set_odometer(-5)

    def test_older_trip_file_without_odometer_still_loads(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State()
            first = Trip(state, Path(folder) / 'trip.json')
            first.counters['total']['km'] = 12.5
            asyncio.run(first.save(force=True))
            data = json.loads((Path(folder) / 'trip.json').read_text()); data.pop('odometer_km')
            (Path(folder) / 'trip.json').write_text(json.dumps(data))
            loaded = Trip(state, Path(folder) / 'trip.json')
            self.assertEqual((loaded.counters['total']['km'], loaded.odometer_km, loaded.error), (12.5, None, ''))


class OdometerRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_over_http(self):
        state = State()
        async with TestClient(TestServer(create_app(state))) as client:
            response = await client.post('/trip', json={'odometer_km': 1000})
            self.assertEqual((response.status, (await response.json())['odometer_km']), (200, 1000))
            self.assertEqual((await client.post('/trip', json={'odometer_km': 'far'})).status, 400)


if __name__ == '__main__':
    unittest.main()
