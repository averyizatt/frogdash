import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.state import State
from hardware.frogdash.trip import Trip, DEFAULTS, validate
from hardware.frogdash.server import create_app
from hardware.frogdash.log_channels import CHANNELS


class TripTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.state = State(clock=lambda: self.now)
        self.trip = self.state.trip
        self.trip.configure({**DEFAULTS, 'enabled': True, 'pulses_per_rev': 1, 'dead_ms': 1, 'pw2_injectors': 2})
        self.values = {'vehicle.speed_kph': 100, 'engine.rpm': 3000, 'ecu.pw1_ms': 6, 'ecu.pw2_ms': 8}

    def sample(self, time, **changes):
        self.now = time
        self.values.update(changes)
        self.trip.sample({'values': {key: {'value': value, 'quality': 'live' if value is not None else 'stale'} for key, value in self.values.items()}})

    def test_analytic_distance_two_banks_fuel_and_range(self):
        self.trip.set_fuel(40)
        for t in range(61):
            self.sample(t)
        view = self.trip.snapshot()
        # Two injectors at 25% effective duty and two at 35%.
        flow = 440 * (2 * .25 + 2 * .35) * .06
        self.assertAlmostEqual(view['flow_lph'], flow)
        self.assertAlmostEqual(view['counters']['a']['km'], 100 / 60)
        self.assertAlmostEqual(view['counters']['a']['fuel_l'], flow / 60)
        self.assertAlmostEqual(view['remaining_l'], 40 - flow / 60)
        self.assertAlmostEqual(view['range_km'], (40 - flow / 60 - 3) * 100 / flow)
        self.assertAlmostEqual(view['instant_mpg'], 100 / flow * 3.785411784 / 1.609344)
        self.assertAlmostEqual(view['average_mpg'], view['instant_mpg'])
        self.assertEqual(view['counters']['a']['engine_s'], 60)

    def test_gaps_never_bridge_distance_or_preserve_manual_range(self):
        self.sample(0); self.trip.set_fuel(40); self.sample(1)
        distance = self.trip.counters['a']['km']
        self.sample(20)
        self.assertEqual(self.trip.counters['a']['km'], distance)
        self.assertIsNone(self.trip.snapshot()['remaining_l'])
        self.sample(21, **{'vehicle.speed_kph': None, 'ecu.pw2_ms': None})
        self.sample(22)
        self.assertEqual(self.trip.counters['a']['km'], distance)
        self.assertIsNone(self.trip.snapshot()['flow_lph'])
        self.sample(23, **{'vehicle.speed_kph': 100, 'ecu.pw2_ms': 8})
        self.assertEqual(self.trip.counters['a']['km'], distance)
        self.sample(24)
        self.assertGreater(self.trip.counters['a']['km'], distance)

    def test_idle_coast_disabled_and_impossible_duty(self):
        self.sample(0, **{'vehicle.speed_kph': 0}); self.sample(1)
        self.assertGreater(self.trip.counters['a']['fuel_l'], 0)
        self.assertEqual(self.trip.counters['a']['km'], 0)
        self.assertIsNone(self.trip.snapshot()['instant_mpg'])
        self.sample(2, **{'vehicle.speed_kph': 100, 'ecu.pw1_ms': 0, 'ecu.pw2_ms': 0})
        self.assertTrue(self.trip.snapshot()['coasting'])
        self.sample(3, **{'ecu.pw1_ms': 99})
        self.assertIsNone(self.trip.snapshot()['flow_lph'])
        self.trip.configure({**DEFAULTS})
        self.sample(4)
        self.assertIsNone(self.trip.snapshot()['flow_lph'])

    def test_reset_is_independent_and_total_cannot_reset(self):
        self.sample(0); self.sample(1)
        total = self.trip.counters['total']['km']
        self.trip.reset('a')
        self.assertEqual(self.trip.counters['a']['km'], 0)
        self.assertEqual(self.trip.counters['b']['km'], total)
        self.assertEqual(self.trip.counters['total']['km'], total)
        with self.assertRaises(ValueError): self.trip.reset('total')

    def test_sender_priority_and_reserve_floor_and_stale_sampler(self):
        for t in range(61): self.sample(t)
        self.trip.set_fuel(40)
        self.sample(61, **{'vehicle.fuel_pct': 1})
        self.assertEqual(self.trip.snapshot()['fuel_source'], 'CAN fuel sender')
        self.assertEqual(self.trip.snapshot()['range_km'], 0)
        self.sample(62, **{'vehicle.fuel_pct': None})
        self.assertTrue(self.trip.snapshot()['fuel_source'].startswith('Manual'))
        self.now = 64
        self.assertIsNone(self.trip.snapshot()['remaining_l'])
        self.assertIsNone(self.trip.snapshot()['instant_mpg'])

    def test_validation_and_calibration_change(self):
        for key, value in [('enabled', 1), ('capacity_l', float('nan')), ('pw2_injectors', 9), ('injectors', 3.5), ('correction', float('inf')), ('pulses_per_rev', 0)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate({**self.trip.settings, key: value})
        with self.assertRaises(ValueError): self.trip.set_fuel(True)
        with self.assertRaises(ValueError): self.trip.set_fuel(100)
        for t in range(61): self.sample(t)
        self.trip.set_fuel(40)
        self.trip.configure({**self.trip.settings, 'correction': 1.1})
        self.assertIsNone(self.trip.snapshot()['average_mpg'])
        self.assertIsNone(self.trip.snapshot()['remaining_l'])
        self.assertGreater(self.trip.counters['a']['km'], 1)

    def test_log_schema_exposes_estimates_with_unavailable_quality(self):
        self.assertIn('fuel.range_km', {c.key for c in CHANNELS})
        self.assertEqual(self.state.snapshot()['values']['fuel.range_km']['quality'], 'unavailable')
        self.assertEqual(self.state.snapshot()['values']['trip.a_km']['value'], 0)

    def test_persistence_restart_does_not_invent_travel_or_fuel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trip.json'
            self.trip.path = path
            self.sample(0); self.sample(1); self.trip.set_fuel(40)
            asyncio.run(self.trip.save(force=True))
            trip = Trip(self.state, path)
            self.assertEqual(trip.counters, self.trip.counters)
            self.assertEqual(trip.settings, self.trip.settings)
            self.assertIsNone(trip.snapshot()['remaining_l'])
            self.assertEqual(trip.snapshot()['last_manual_l'], 40)
            data = json.loads(path.read_text())
            data['settings'].update(enabled=False, pulses_per_rev=0)
            path.write_text(json.dumps(data))
            migrated = Trip(self.state, path)
            self.assertEqual(migrated.settings['pulses_per_rev'], .5)
            self.assertFalse(migrated.settings['enabled'])
            self.assertEqual(migrated.counters, trip.counters)
            path.write_text('{broken')
            self.assertTrue(Trip(self.state, path).error)


class TripAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_local_settings_reset_inventory_and_validation(self):
        state = State()
        async with TestClient(TestServer(create_app(state))) as client:
            response = await client.get('/trip')
            data = await response.json()
            self.assertEqual(data['settings']['injector_cc_min'], 440)
            self.assertEqual(data['settings']['pulses_per_rev'], .5)
            self.assertFalse(data['settings']['enabled'])
            response = await client.post('/trip', json={'settings': {**DEFAULTS, 'enabled': True, 'pulses_per_rev': 1}})
            self.assertEqual(response.status, 200)
            self.assertEqual((await client.post('/trip', json={'remaining_l': 20})).status, 200)
            self.assertEqual((await client.post('/trip', json={'reset': 'a'})).status, 200)
            for body in ({'reset': 'total'}, {'remaining_l': -1}, {'settings': {}}, {'reset': 'b', 'extra': True}, []):
                self.assertEqual((await client.post('/trip', json=body)).status, 400)
            self.assertEqual((await client.post('/trip', json={'reset': 'a'}, headers={'Origin': 'https://example.com'})).status, 403)


if __name__ == '__main__':
    unittest.main()
