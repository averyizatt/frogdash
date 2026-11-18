"""The custom ECU editor's back end: any run of bits as a DBC file numbers them, the unit an
ECU sends a reading in, a custom profile checked as the dash loads it, DBC import, and
/system/custom with Apply carrying the profile."""
import json
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash import ecu, sysconfig
from hardware.frogdash.ecu import dbc
from hardware.frogdash.paint import Paint
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

DBC = '''VERSION ""
BO_ 864 DATA1: 8 ECU
 SG_ RPM : 7|16@0+ (1,0) [0|20000] "rpm" Vector__XXX
 SG_ MAP : 23|16@0+ (0.1,0) [0|600] "kPa" Vector__XXX
 SG_ TPS : 39|16@0- (0.1,0) [-10|110] "%" Vector__XXX
 SG_ CoolantTemp : 55|12@0+ (1,-40) [-40|200] "degF" Vector__XXX
BO_ 865 DATA2: 8 ECU
 SG_ Battery_Voltage : 0|16@1+ (0.01,0) [0|20] "V" Vector__XXX
 SG_ OilPressure : 16|16@1+ (0.1,0) [0|150] "psi" Vector__XXX
 SG_ Mode M : 32|8@1+ (1,0) [0|255] "" Vector__XXX
 SG_ Muxed m1 : 40|8@1+ (1,0) [0|255] "" Vector__XXX
 SG_ FanOn : 48|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ Mystery : 52|4@1+ (1,0) [0|15] "" Vector__XXX
BO_ 2365563366 OTHER: 8 ECU
 SG_ Thing : 0|8@1+ (1,0) [0|255] "" Vector__XXX
BO_ 866 FD: 64 ECU
 SG_ Big : 0|8@1+ (1,0) [0|255] "" Vector__XXX
'''


class LayoutTests(unittest.TestCase):
    def test_bits_in_intel_and_motorola_order(self):
        frame = bytes.fromhex('12340ABC00F0FF00')
        self.assertEqual(ecu.reader('ube@7:16', 8)(frame), 0x1234)             # Motorola from the top of byte 0
        self.assertEqual(ecu.reader('ule@0:16', 8)(frame), 0x3412)             # Intel from the bottom of byte 0
        self.assertEqual(ecu.reader('ube@19:12', 8)(frame), 0xABC)             # 12 bits, top bit 3 of byte 2
        self.assertEqual(ecu.reader('sle@44:12', 8)(frame), -1)                # Signed, across bytes 5 and 6
        self.assertEqual(ecu.reader('ule@44:12', 8)(frame), 0xFFF)

    def test_bits_outside_the_frame_are_refused(self):
        for layout, length in (('ule@60:8', 8), ('ube@7:16', 1), ('ule@0:33', 8), ('ube@3:12', 1)):
            with self.assertRaises(ecu.ProfileError):
                ecu.reader(layout, length)

    def test_the_unit_an_ecu_sends_is_converted(self):
        self.assertAlmostEqual(ecu.converter({'scale': 0.1, 'from': 'degF'})(2120), 100)
        self.assertAlmostEqual(ecu.converter({'from': 'psi'})(10), 68.94757293168361)
        self.assertAlmostEqual(ecu.converter({'offset': -273.15 + 273.15, 'from': 'K'})(373.15), 100)
        with self.assertRaises(ecu.ProfileError):
            ecu.converter({'from': 'furlongs'})


class CustomProfileTests(unittest.TestCase):
    def profile(self, **extra):
        return {'id': 'custom', 'label': 'My ECU', 'bitrate': 500000,
                'frames': [{'ids': ['0x360'], 'length': 8, 'signals': [{'key': 'ecu.rpm', 'layout': 'u16@0'}]}], **extra}

    def test_a_profile_from_the_editor_decodes(self):
        found = ecu.custom(self.profile())
        self.assertEqual(found.decode(0x360, bytes.fromhex('0BB8000000000000')), {'ecu.rpm': 3000})

    def test_only_a_plain_custom_profile(self):
        for bad in (self.profile(id='haltech'), self.profile(type='obd2'), self.profile(base={'default': '0x360'}),
                    self.profile(frames=[]), 'text'):
            with self.assertRaises(ecu.ProfileError):
                ecu.custom(bad)


class DbcTests(unittest.TestCase):
    def setUp(self):
        self.got = dbc.read(DBC)
        self.signals = {s['name']: s for f in self.got['frames'] for s in f['signals']}

    def test_frames_and_simple_layouts(self):
        self.assertFalse(self.got['extended'])
        self.assertEqual([f['ids'] for f in self.got['frames']], [['0x360'], ['0x361']])
        self.assertEqual({n: s['layout'] for n, s in self.signals.items()},
                         {'RPM': 'u16@0', 'MAP': 'u16@2', 'TPS': 's16@4', 'CoolantTemp': 'ube@55:12',
                          'Battery_Voltage': 'u16le@0', 'OilPressure': 'u16le@2', 'FanOn': 'bit@6.0', 'Mystery': 'nib@6.4'})

    def test_readings_guessed_and_units_converted(self):
        keys = {n: s['key'] for n, s in self.signals.items()}
        self.assertEqual(keys['RPM'], 'ecu.rpm')
        self.assertEqual(keys['CoolantTemp'], 'ecu.coolant_c')
        self.assertEqual(keys['OilPressure'], 'ecu.oil_pressure_kpa')
        self.assertEqual(keys['Mystery'], 'ecu.mystery')                      # Not guessed: its own name, to check
        self.assertFalse(self.signals['Mystery']['guessed'])
        self.assertEqual(self.signals['CoolantTemp']['from'], 'degF')
        self.assertEqual(self.signals['OilPressure']['from'], 'psi')
        self.assertNotIn('from', self.signals['MAP'])

    def test_what_is_left_out_says_why(self):
        skipped = ' '.join(self.got['skipped'])
        for why in ('multiplexed', 'CAN FD', '29-bit'):
            self.assertIn(why, skipped)

    def test_the_import_is_a_profile_the_dash_decodes(self):
        found = ecu.custom({'id': 'custom', 'frames': self.got['frames']})
        values = found.decode(0x360, bytes.fromhex('0BB803E8FF9C0D40'))
        self.assertEqual(values['ecu.rpm'], 3000)
        self.assertEqual(values['ecu.map_kpa'], 100)
        self.assertEqual(values['ecu.throttle_pct'], -10)
        self.assertAlmostEqual(values['ecu.coolant_c'], (0x0D4 - 40 - 32) * 5 / 9)      # Top 12 bits of 0D40, in F

    def test_not_a_dbc(self):
        with self.assertRaises(ecu.ProfileError):
            dbc.read('hello')


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_import_and_apply_with_the_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State()
            state.paint = Paint(Path(folder) / 'appearance-paint.json')
            async with TestClient(TestServer(create_app(state))) as client:
                data = await (await client.get('/system')).json()
                self.assertIn('Engine', [group for group, _ in data['catalog']])
                mine = {'id': 'custom', 'label': 'Mine', 'frames': [{'ids': ['0x360'], 'signals': [{'key': 'ecu.rpm', 'layout': 'u16@0'}]}]}
                self.assertEqual((await (await client.post('/system/custom/check', json={'profile': mine})).json())['summary']['label'], 'Mine')
                # The taillight board's 0x100 in a car that has it: refused, saying which.
                clash = {**mine, 'frames': [{'ids': ['0x100'], 'signals': [{'key': 'ecu.rpm', 'layout': 'u16@0'}]}]}
                response = await client.post('/system/custom/check', json={'profile': clash})
                self.assertEqual(response.status, 400)
                self.assertIn('0x100', await response.text())
                imported = await (await client.post('/system/custom/dbc', json={'text': DBC})).json()
                self.assertEqual(len(imported['frames']), 2)
                self.assertEqual((await client.post('/system/custom/dbc', json={'text': 'nothing'})).status, 400)

                wanted = sysconfig.preset('foxbody')                        # With the taillight board on 0x100
                wanted['ecu']['profile'] = 'custom'
                self.assertEqual((await client.post('/system', json={'profile': wanted, 'custom': clash})).status, 400)
                self.assertFalse((Path(folder) / 'config-request.json').exists())
                self.assertEqual((await client.post('/system', json={'profile': wanted, 'custom': mine})).status, 200)
                request = json.loads((Path(folder) / 'config-request.json').read_text(encoding='utf-8'))
                self.assertEqual(request['custom'], mine)


if __name__ == '__main__':
    unittest.main()
