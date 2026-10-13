"""Cross-language CAN tests against pinned firmware builders (no hardware/network)."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from hardware.frogdash.controls import COMMANDS
from hardware.frogdash.gps import GPS
from hardware.frogdash.protocol import decode
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'hardware/can_contract'
COMPILER = shutil.which('g++') or shutil.which('clang++')


@lru_cache(maxsize=1)
def vectors():
    with tempfile.TemporaryDirectory() as directory:
        exe = Path(directory) / 'vectors.exe'
        # can_protocol.h must stay C++11 (water/meth Nano). The gateway header needs
        # C++14 and is only used by ESP32 builds, so the combined vectors use C++17.
        header_only = Path(directory) / 'cxx11.cpp'
        header_only.write_text('#include "can_contract/can_protocol.h"\nint main() { return 0; }\n')
        compiled = subprocess.run([COMPILER, '-std=c++11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                        '-I', str(PACKAGE / 'include'), str(header_only), '-o', str(exe)], capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)
        compiled = subprocess.run([COMPILER, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                        '-I', str(PACKAGE / 'include'), str(ROOT / 'tests/can_contract_vectors.cpp'),
                        '-o', str(exe)], capture_output=True, text=True)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)
        output = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    return {name: (int(identifier, 16), bytes.fromhex(data))
            for name, identifier, data in (line.split() for line in output.splitlines())}


class ProvenanceTests(unittest.TestCase):
    def test_extension_preserves_the_exact_existing_schema_two_contract(self):
        header = (PACKAGE / 'include/can_contract/can_protocol.h').read_text()
        base = re.sub(r'// BEGIN FROGDASH ADDITIVE EXTENSION.*?// END FROGDASH ADDITIVE EXTENSION\n\n', '', header, flags=re.S)
        manifest = json.loads((PACKAGE / 'sources.json').read_text())
        self.assertEqual(hashlib.sha256(base.encode()).hexdigest(), manifest['upstream_header_sha256'])


@unittest.skipUnless(COMPILER, 'C++ compiler required for firmware wire-contract checks')
class WireTests(unittest.IsolatedAsyncioTestCase):
    async def test_firmware_telemetry_builders_decode_to_engineering_values(self):
        expected = {
            'lights': {'lighting.brake':True, 'lighting.running':True, 'lighting.turn_left':True, 'lighting.turn_right':False, 'lighting.die_c':70},
            'meth': {'meth.state':'SPRAYING', 'meth.duty_pct':50, 'engine.iat_c':-10, 'engine.boost_kpa':85},
            'sensors': {'engine.oil_pressure_psi':62.5, 'engine.fuel_pressure_psi':39.5, 'sensors.fault_flags':256},
            'runtime': {'runtime.rpm':3450, 'runtime.map_kpa':100},
            'knock': {'knock.energy':20, 'knock.last_rpm':3400},
            'hook': {'knock.hook.bias_adc':512, 'knock.hook.raw_adc':640},
            'knock_config1': {'knock.config.multiplier':2.4, 'knock.config.min_rpm':1500, 'knock.config.center_hz':6500},
            'knock_config2': {'knock.config.bandwidth_hz':1500, 'knock.config.sample_rate_hz':20000, 'knock.config.bias_alpha':.01},
            'meth_config': {'meth.config.version':7, 'meth.config.ratio_pct':50, 'meth.config.iat_threshold_c':50},
            'meth_config_ack': {'meth.ack.version':7, 'meth.ack.ratio_pct':50},
            'command_ack': {'engine.ack.command':65, 'engine.ack.applied_value':20, 'engine.ack.schema':2},
            'knock_fault': {'knock.last_fault.severity':2},
            # Knock detail from the ESP32 controller (extension 6). Millivolts are sent in steps of 16 and 8.
            'knock_amplifier': {'knock.amp.automatic':True, 'knock.amp.fixed':False, 'knock.amp.gain':8.0, 'knock.amp.step':21,
                                'knock.amp.top_step':30, 'knock.amp.rest_mv':816, 'knock.amp.swing_mv':144, 'knock.amp.room_mv':800},
            'knock_amplifier_fixed': {'knock.amp.automatic':False, 'knock.amp.fixed':True, 'knock.amp.overloaded':True, 'knock.amp.gain':1.0},
            'knock_frequency': {'knock.freq.learning':True, 'knock.freq.learned':True, 'knock.freq.second_active':True,
                                'knock.freq.filter_hz':6250, 'knock.freq.found_hz':6262, 'knock.freq.agreement_pct':84, 'knock.freq.votes':120},
            'knock_engine': {'knock.freq.bore_hz':5966, 'knock.freq.tone_hz':6000, 'knock.freq.sample_rate_hz':38460},
            'knock_listening': {'knock.listen.notable':True, 'knock.listen.confirmed':True, 'knock.listen.second':44,
                                'knock.listen.second_normal':12, 'knock.listen.background':9, 'knock.listen.crest':3.1},
            'wheel': {'wheel.buttons_mask':8, 'wheel.sequence':255},
            'fuel': {'vehicle.fuel_pct':50}, 'gps': {'vehicle.speed_kph':75.6, 'gps.altitude_m':-10},
        }
        for name, values in expected.items():
            signals = decode(*vectors()[name])
            for key, value in values.items():
                self.assertEqual(signals[key].value, value, (name,key))
        for name, quality in [('fuel_fault','fault'), ('fuel_unavailable','unavailable')]:
            sample = decode(*vectors()[name])['vehicle.fuel_pct']
            self.assertIsNone(sample.value); self.assertEqual(sample.quality,quality)

    async def test_actual_dashboard_commands_match_firmware_builders(self):
        values = {'meth.arm':1, 'meth.test':25, 'meth.boost':40, 'knock.enable':1,
                  'knock.threshold':20, 'knock.multiplier':24, 'lighting.brightness':128, 'lighting.mode':1,
                  'lighting.show':7, 'lighting.override':0x23, 'lighting.custom':2,
                  'lighting.setting':(13 << 16) | 5, 'lighting.color':(1 << 24) | 0xFF6400,
                  'lighting.text':'FOX', 'lighting.action':(5 << 8) | 2,
                  'meth.setting':(3 << 16) | 1500, 'meth.tune_action':0,
                  'knock.min_rpm':25, 'knock.min_map':120, 'knock.hold':30, 'knock.level_gain':15, 'knock.center':62,
                  'knock.bandwidth':9, 'knock.auto_frequency':1, 'knock.amp_gain':13, 'knock.bore':96,
                  'interior.light':(1 << 32) | (0xFFFFFF << 8) | 35}
        for action in COMMANDS:
            state = State(clock=lambda: 10)
            state.connected = True
            state.samples['ecu.rpm', 1520] = dict(value=0,quality='live',seen=10,source_id=1520,timestamp_ms=0)
            for identifier, data in [(0x300, '0000640000282800'), (0x307, '13140fb400000000'), (0x100, '01010202ff3c00'),
                                     (0x103, '0501000000000000'),  # Taillight firmware with the settings extension.
                                     (0x30F, '03000001000003e8'),  # Water/meth firmware with pulse tuning.
                                     (0x30E, '0101501e33123200'[:16]),  # The ESP32 controller's knock detail.
                                     (0x503, '01000000000100')]:  # Sensor gateway interior lights online.
                state.ingest(identifier, bytes.fromhex(data))
            sent = []
            async def send(identifier, data):
                sent.append((identifier,data))
                if identifier == 0x301 and data[0] in (0x10, 0x11):
                    state.ingest(0x30F,bytes([1,data[0],0,data[1],*(data[2:4] if len(data) == 4 else b'\x00\x00'),1,0]))
                elif identifier == 0x301:
                    state.ingest(0x30A,bytes([data[0],0,data[1] if len(data)>1 else 0,2]))
                if identifier == 0x101:
                    state.ingest(0x103,bytes([1,data[0],0,0,0,0,1,2]))
            state.controls.attach(send); state.controls.ready_at=0
            try:
                await state.controls.execute(action,values.get(action),owner=self)
                self.assertEqual(sent[0],vectors()[action],action)
            finally:
                await state.controls.close()

    def test_knock_spectra_are_put_back_together_from_their_chunks(self):
        from hardware.frogdash import knockview
        now = [50.0]
        state = State(clock=lambda: now[0])
        state.connected = True
        self.assertEqual(state.snapshot()['knock_detail'], {'supported': False, 'start_hz': 2000, 'step_hz': 300, 'normal': None, 'burst': None})
        state.ingest(*vectors()['knock_amplifier'])
        detail = state.snapshot()['knock_detail']
        self.assertEqual((detail['supported'], detail['normal']), (True, None))       # Heard from, but no spectrum yet.
        # The firmware's own chunk: points 12..17 of the normal spectrum, bytes 30 33 60 150 255 0.
        state.ingest(*vectors()['knock_spectrum_normal'])
        self.assertIsNone(state.snapshot()['knock_detail']['normal'])                 # Not shown until it is whole.
        for first in range(0, knockview.POINTS, knockview.PER_FRAME):
            if first != 12:
                state.ingest(0x30E, bytes([knockview.NORMAL, first, 90, 90, 90, 90, 90, 90]))
        normal = state.snapshot()['knock_detail']['normal']
        self.assertEqual(len(normal), 36)
        self.assertEqual(normal[12:18], [0.0, 1.0, 10.0, 40.0, 75.0, -10.0])           # (byte / 3) - 10 dB
        self.assertEqual((normal[0], normal[35]), (20.0, 20.0))
        self.assertIsNone(state.snapshot()['knock_detail']['burst'])                  # The other spectrum is separate.
        state.ingest(*vectors()['knock_spectrum_burst'])                              # Points 30..35.
        for first in range(0, 30, knockview.PER_FRAME):
            state.ingest(0x30E, bytes([knockview.BURST, first, 120, 120, 120, 120, 120, 120]))
        self.assertEqual(state.snapshot()['knock_detail']['burst'][28:32], [30.0, 30.0, 0.0, 1.0])
        # A chunk that does not sit on a frame boundary is refused, not written somewhere odd.
        with self.assertRaises(ValueError):
            decode(0x30E, bytes([knockview.NORMAL, 13, 0, 0, 0, 0, 0, 0]))
        with self.assertRaises(ValueError):
            decode(0x30E, bytes([9, 0, 0, 0, 0, 0, 0, 0]))
        # No frequency found yet is "unavailable", not zero hertz.
        found = decode(0x30E, bytes([2, 1, 0x17, 0x4E, 0, 0, 0, 0]))['knock.freq.found_hz']
        self.assertEqual((found.value, found.quality), (None, 'unavailable'))
        # The controller goes quiet (or the Nano is fitted): the page falls back.
        now[0] += 5
        self.assertEqual(state.snapshot()['knock_detail'], {'supported': False, 'start_hz': 2000, 'step_hz': 300, 'normal': None, 'burst': None})

    async def test_knock_settings_for_the_esp32_controller_are_refused_for_the_nano(self):
        state = State(clock=lambda: 10)
        state.connected = True
        state.samples['ecu.rpm', 1520] = dict(value=0, quality='live', seen=10, source_id=1520, timestamp_ms=0)
        state.ingest(0x307, bytes.fromhex('13140fb400000000'))
        sent = []
        async def send(identifier, data):
            sent.append((identifier, data))
            state.ingest(0x30A, bytes([data[0], 0, data[1] if len(data) > 1 else 0, 2]))
        state.controls.attach(send); state.controls.ready_at = 0
        try:
            for action, value in (('knock.amp_gain', 5), ('knock.bore', 96), ('knock.relearn', None)):
                with self.assertRaisesRegex(ValueError, 'needs the ESP32'):
                    await state.controls.execute(action, value)
            self.assertEqual(sent, [])
            # Settings the Nano has too still go out.
            self.assertEqual((await state.controls.execute('knock.min_rpm', 25))['status'], 'acknowledged')
            self.assertEqual(sent, [vectors()['knock.min_rpm']])
            for action, value in (('knock.min_rpm', 81), ('knock.center', 29), ('knock.center', 91), ('knock.hold', 9), ('knock.bore', 39), ('knock.amp_gain', 101)):
                with self.assertRaises(ValueError):
                    await state.controls.execute(action, value)
        finally:
            await state.controls.close()
        # Knock calibration is not changed while the car is moving.
        state.samples['vehicle.speed_kph', 0x203] = dict(value=40, quality='live', seen=10, source_id=0x203, timestamp_ms=0)
        self.assertIn('Stop the car', state.controls.reason('knock.min_map', 120) or '')

    async def test_water_meth_tuning_reports_decode_and_fill_the_mirror(self):
        state = State(clock=lambda: 10)
        state.connected = True
        for name in ('meth_tune_ack', 'meth_tune_setting', 'meth_tune_status', 'meth_tune_temps'):
            state.ingest(*vectors()[name])
        mirror = state.meth_tune.snapshot()
        self.assertEqual((mirror['supported'], mirror['revision'], mirror['hold']), (True, 7, 'DOSE_LIMIT'))
        self.assertEqual((mirror['unsaved'], mirror['pump_on'], mirror['rpm_ok'], mirror['pre_valid']), (True, True, True, False))
        self.assertEqual((mirror['early_start'], mirror['hot_air']), (True, False))
        self.assertEqual((mirror['on_ms'], mirror['period_ms'], mirror['settings']), (1500, 4000, {'min_rpm': 2500}))
        # A setting report from the PWM board says so; one from the relay board does not.
        self.assertEqual(mirror['drive'], 'relay')
        state.ingest(*vectors()['meth_tune_setting_pwm'])
        mirror = state.meth_tune.snapshot()
        self.assertEqual((mirror['drive'], mirror['settings']), ('pwm', {'min_rpm': 2500, 'max_duty_pct': 50}))
        state.ingest(*vectors()['meth_tune_setting'])
        mirror = state.meth_tune.snapshot()
        self.assertEqual(mirror['last_ack'], {'command': 0x10, 'status': 3, 'subject': 3, 'value': 2000, 'revision': 7})
        values = state.snapshot()['values']
        self.assertEqual([values[key]['value'] for key in ('meth.pre_temp_c', 'meth.post_temp_c', 'meth.temp_drop_c', 'meth.hold', 'meth.on_ms')],
                         [61.2, -3.5, 64.7, 'DOSE_LIMIT', 1500])
        signals = decode(*vectors()['meth_tune_temps_pre_only'])
        self.assertEqual((signals['meth.pre_temp_c'].value, signals['meth.post_temp_c'].quality, signals['meth.temp_drop_c'].value), (61.2, 'unavailable', None))
        with self.assertRaises(ValueError):
            decode(0x30F, bytes([9, 0, 0, 0, 0, 0, 0, 0]))

    async def test_firmware_update_frames_match_the_module_side(self):
        import zlib
        from hardware.frogdash import fwupdate as fw
        part = bytes(range(1, 11))
        frames = fw.data_frames(part)
        built = {
            'fw_query': fw.command(fw.QUERY, 1),
            'fw_begin': fw.command(fw.BEGIN, 1, (0x05A1B2).to_bytes(3, 'big') + b'FW'),
            'fw_data_full': frames[0], 'fw_data_last': frames[1],
            'fw_block_end': fw.command(fw.BLOCK_END, 1, (0x0123).to_bytes(2, 'big') + fw.crc16(part).to_bytes(2, 'big') + bytes([2])),
            'fw_end': fw.command(fw.END, 1, zlib.crc32(part).to_bytes(4, 'big')),
            'fw_abort': fw.command(fw.ABORT, 1),
            'fw_confirm': fw.command(fw.CONFIRM, 1, bytes.fromhex('1a2b3c4d')),
        }
        for name, payload in built.items():
            self.assertEqual((fw.ID_COMMAND, payload), vectors()[name], name)
        # The module's answers, as the dash reads them.
        state = State('socketcan', clock=lambda: 10)
        state.connected = True
        state.firmware = fw.Firmware(state, None)
        state.ingest(*vectors()['fw_info'])
        self.assertEqual(vectors()['fw_info'][0], fw.ID_REPLY)
        gateway = state.firmware.modules['gateway']
        self.assertEqual((gateway.installed, gateway.flags & fw.ON_TRIAL), ('1a2b3c4d', fw.ON_TRIAL))
        self.assertIsNone(state.firmware.modules['taillights'].installed)   # Answers are told apart by the module they name.
        ack = vectors()['fw_ack'][1]
        self.assertEqual((ack[0], ack[2], ack[3], ack[4:6]), (fw.ACK, fw.BLOCK_END, fw.RESEND, bytes.fromhex('0123')))
        self.assertEqual(state.malformed, 0)

    async def test_usb_gps_transmitter_matches_shared_gps_builder(self):
        gps=GPS(clock=lambda: 0,wall=lambda: 0); gps.connected=True
        gps.update({'class':'TPV','device':'gps','mode':3,'speed':21,'altMSL':-10})
        gps.update({'class':'SKY','device':'gps','satellites':[{'used':True},{'used':False}]})
        self.assertEqual((0x203,gps.frame()),vectors()['gps'])


if __name__ == '__main__':
    unittest.main()
