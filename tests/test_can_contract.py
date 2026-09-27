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
        compiled = subprocess.run([COMPILER, '-std=c++11', '-Wall', '-Wextra', '-Werror',
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
                  'knock.threshold':20, 'knock.multiplier':24, 'lighting.brightness':128, 'lighting.mode':1}
        for action in COMMANDS:
            state = State(clock=lambda: 10)
            state.connected = True
            state.samples['ecu.rpm', 1520] = dict(value=0,quality='live',seen=10,source_id=1520,timestamp_ms=0)
            for identifier, data in [(0x300, '0000640000282800'), (0x307, '13140fb400000000'), (0x100, '01010202ff3c00')]:
                state.ingest(identifier, bytes.fromhex(data))
            sent = []
            async def send(identifier, data):
                sent.append((identifier,data))
                if identifier == 0x301:
                    state.ingest(0x30A,bytes([data[0],0,data[1] if len(data)>1 else 0,2]))
            state.controls.attach(send); state.controls.ready_at=0
            try:
                await state.controls.execute(action,values.get(action),owner=self)
                self.assertEqual(sent[0],vectors()[action],action)
            finally:
                await state.controls.close()

    async def test_usb_gps_transmitter_matches_shared_gps_builder(self):
        gps=GPS(clock=lambda: 0,wall=lambda: 0); gps.connected=True
        gps.update({'class':'TPV','device':'gps','mode':3,'speed':21,'altMSL':-10})
        gps.update({'class':'SKY','device':'gps','satellites':[{'used':True},{'used':False}]})
        self.assertEqual((0x203,gps.frame()),vectors()['gps'])


if __name__ == '__main__':
    unittest.main()
