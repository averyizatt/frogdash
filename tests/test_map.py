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

    async def test_a_map_downloaded_for_where_the_car_is(self):
        import tempfile
        from unittest import mock
        from hardware.frogdash.paint import Paint
        road = {'elements': [{'type': 'way', 'tags': {'highway': 'primary', 'name': 'High Street'},
                              'geometry': [{'lat': 51.75, 'lon': -1.26}, {'lat': 51.76, 'lon': -1.25}]}]}
        with tempfile.TemporaryDirectory() as folder:
            state = State()
            state.paint = Paint(Path(folder) / 'appearance-paint.json')
            async with TestClient(TestServer(create_app(state))) as client:
                with mock.patch.object(make_map, 'download', return_value=road),                      mock.patch('importlib.util.spec_from_file_location', return_value=spec),                      mock.patch('importlib.util.module_from_spec', return_value=make_map),                      mock.patch.object(spec.loader, 'exec_module', lambda module: None):
                    response = await client.post('/maps/download', json={'lat': 51.752, 'lon': -1.258})
                self.assertEqual(response.status, 200, await response.text())
                name = (await response.json())['name']
                maps = await (await client.get('/maps/index.json')).json()
                self.assertEqual(maps[0]['name'], name)                                   # The Pi's own first
                self.assertIn('grand-junction', [m['name'] for m in maps])
                south, west, north, east = maps[0]['bounds']
                self.assertTrue(south < 51.752 < north and west < -1.258 < east)
                data = await (await client.get(f'/maps/{name}.json')).json()
                self.assertIn('High Street', data['names'])
                self.assertEqual((await client.post('/maps/download', json={'lat': 'x'})).status, 409)


if __name__ == '__main__':
    unittest.main()
