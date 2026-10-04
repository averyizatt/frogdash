import importlib.util
import json
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('make_map', ROOT / 'tools' / 'make_map.py')
make_map = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_map)


class MapBuildTests(unittest.TestCase):
    def test_build_classifies_names_and_delta_encodes(self):
        data = {'elements': [
            {'type': 'way', 'tags': {'highway': 'primary', 'name': 'North Avenue'}, 'geometry': [{'lat': 39.08, 'lon': -108.56}, {'lat': 39.08, 'lon': -108.55}]},
            {'type': 'way', 'tags': {'highway': 'footway'}, 'geometry': [{'lat': 39.08, 'lon': -108.56}, {'lat': 39.09, 'lon': -108.56}]},
            {'type': 'way', 'tags': {'highway': 'service', 'service': 'driveway'}, 'geometry': [{'lat': 39.08, 'lon': -108.56}, {'lat': 39.09, 'lon': -108.56}]},
            {'type': 'way', 'tags': {'waterway': 'river', 'name': 'Colorado River'}, 'geometry': [{'lat': 39.06, 'lon': -108.56}, {'lat': 39.06, 'lon': -108.57}]}]}
        result = make_map.build(data, (39.0, -108.72, 39.15, -108.40), 'Test')
        self.assertEqual([(w[0], result['names'][w[1]]) for w in result['ways']], [(5, 'Colorado River'), (1, 'North Avenue')])
        road = result['ways'][1][2]
        self.assertEqual(road, [8000, 16000, 0, 1000])  # First point relative to the south-west corner, then deltas.

    def test_bundled_grand_junction_map_is_valid(self):
        index = json.loads((ROOT / 'hardware' / 'maps' / 'index.json').read_text(encoding='utf-8'))
        data = json.loads((ROOT / 'hardware' / 'maps' / f"{index[0]['name']}.json").read_text(encoding='utf-8'))
        self.assertIn('OpenStreetMap', data['attribution'])
        self.assertIn('Main Street', data['names'])
        self.assertGreater(len(data['ways']), 5000)
        south, west, north, east = data['bounds']
        self.assertTrue(south < 39.0672 < north and west < -108.5645 < east)  # Downtown is inside.


class MapRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_map_files_are_served_and_names_are_restricted(self):
        async with TestClient(TestServer(create_app(State()))) as client:
            self.assertEqual((await client.get('/maps/index.json')).status, 200)
            self.assertEqual((await client.get('/maps/grand-junction.json')).status, 200)
            self.assertEqual((await client.get('/maps/..%2Fui%2Fapp.js')).status, 404)
            self.assertEqual((await client.get('/map.js')).status, 200)


if __name__ == '__main__':
    unittest.main()
