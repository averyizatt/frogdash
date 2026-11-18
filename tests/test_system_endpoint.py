"""/system: what the setup wizard reads, and its Apply (a request file for frogdash-config.path)."""
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash import ecu, sysconfig
from hardware.frogdash.paint import Paint
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State


class SystemEndpointTests(unittest.IsolatedAsyncioTestCase):
    def test_a_car_without_a_module_hides_its_screens(self):
        generic = sysconfig.validate(sysconfig.preset('generic'))
        self.assertEqual(sysconfig.ui_features(generic), {'map': True, 'race': True, 'knock': False, 'watermeth': False,
                                                          'taillights': False, 'units': 'us'})
        car = sysconfig.ui_features(sysconfig.validate(sysconfig.preset('foxbody')))
        self.assertTrue(all(car[k] for k in ('map', 'race', 'knock', 'watermeth', 'taillights')))

    async def test_the_wizard_reads_the_profile_presets_and_ecu_profiles_and_applies_by_request(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State()
            state.paint = Paint(Path(folder) / 'appearance-paint.json')
            state.connected = True
            state.ingest(0x5E8, bytes.fromhex('03840D7A08020000'))          # A MicroSquirt frame on the bus
            async with TestClient(TestServer(create_app(state))) as client:
                # The screens to show go out with every snapshot (the car: everything).
                self.assertEqual(state.snapshot()['features'], sysconfig.ui_features(sysconfig.load()))
                data = await (await client.get('/system')).json()
                self.assertEqual(set(data['presets']), set(sysconfig.preset_names()))
                self.assertEqual(sorted(p['id'] for p in data['ecu']['profiles']), ecu.built_in())
                self.assertIn('configured', data['profile'])
                self.assertEqual(data['bus']['ecu_ids_heard'], 1)
                matches = {p['id']: p['matches'] for p in data['ecu']['profiles']}
                self.assertEqual(matches['megasquirt'], 1)
                self.assertEqual(matches['haltech'], 0)
                self.assertFalse(data['pending'])
                # The connection test: the MicroSquirt frame is heard; Haltech's 1 Mbit/s is not the bus's.
                ms = await (await client.get('/system/check?ecu=megasquirt')).json()
                self.assertEqual(ms['state'], 'ok', ms)
                haltech = await (await client.get('/system/check?ecu=haltech')).json()
                self.assertEqual(haltech['state'], 'wrong_speed', haltech)
                self.assertEqual((await (await client.get('/system/check?ecu=nope')).json())['state'], 'no_profile')
                # Listening at Haltech's speed: a request for the root helper; a speed CAN does not use is refused.
                self.assertEqual((await client.post('/system/check', json={'bitrate': 12345})).status, 409)
                self.assertEqual((await client.post('/system/check', json={'bitrate': 1000000})).status, 200)
                trial = json.loads((Path(folder) / 'tuning-request.json').read_text(encoding='utf-8'))
                self.assertEqual(trial, {'action': 'can_try', 'arg': '1000000'})
                self.assertEqual((await client.post('/system/check', json={'bitrate': 1000000})).status, 409)   # Busy
                self.assertEqual((await (await client.get('/system/check?ecu=haltech')).json())['trial'], {'starting': True})
                (Path(folder) / 'tuning-request.json').unlink()

                wanted = sysconfig.preset('generic')
                wanted['ecu'].update(profile='haltech', bitrate=1000000)
                self.assertEqual((await client.post('/system', json={'profile': wanted})).status, 200)
                request = json.loads((Path(folder) / 'config-request.json').read_text(encoding='utf-8'))
                self.assertEqual(request['profile']['ecu']['profile'], 'haltech')
                self.assertTrue(request['profile']['configured'])
                self.assertTrue((await (await client.get('/system')).json())['pending'])

                (Path(folder) / 'config-request.json').unlink()
                for bad in ({'profile': {**wanted, 'hotspot_name': 'a;b'}}, {'profile': {**wanted, 'ecu': {'profile': 'nope'}}}, {'nothing': 1}):
                    self.assertEqual((await client.post('/system', json=bad)).status, 400, bad)
                self.assertFalse((Path(folder) / 'config-request.json').exists())


if __name__ == '__main__':
    unittest.main()
