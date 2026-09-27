import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.state import State
from hardware.frogdash.fuel import DEFAULTS, validate, resistance, percentage, read_ads1115
from hardware.frogdash.operations import Operations
from hardware.frogdash.parking import parked
from hardware.frogdash.server import create_app
from hardware.frogdash.trip import Trip
from hardware.frogdash.driving import Driving
from hardware.frogdash.race import Race
from hardware.frogdash.backlight import Backlight
from tools.launch_kiosk import RenderWatchdog
from tools.install_release import activate, manifest, replace_link, release_name


def stationary(state):
    state.connected = True
    state.samples['ecu.rpm', 1520] = dict(value=0, quality='live', seen=state.clock(), timestamp_ms=0, source_id=1520)


class SenderTests(unittest.TestCase):
    def test_linux_adc_register_configuration_and_signed_conversion(self):
        fcntl = SimpleNamespace(ioctl=Mock())
        with patch.dict('sys.modules', {'fcntl': fcntl}), patch('hardware.frogdash.fuel.os.open', return_value=42), \
                patch('hardware.frogdash.fuel.os.close') as close, patch('hardware.frogdash.fuel.os.write') as write, \
                patch('hardware.frogdash.fuel.os.read', side_effect=[b'\x80\0', b'\xff\xff', b'\x80\0', b'\x67\x20']):
            voltage, supply = read_ads1115(1, 72)
        self.assertAlmostEqual(voltage, -.000125)
        self.assertAlmostEqual(supply, 3.3)
        self.assertIn(((42, b'\x01\xc3\x83'),), write.call_args_list)
        self.assertIn(((42, b'\x01\xd3\x83'),), write.call_args_list)
        fcntl.ioctl.assert_called_once_with(42, 0x0703, 72)
        close.assert_called_once_with(42)

    def test_resistance_endpoints_supply_compensation_and_tank_curve(self):
        for supply in (3, 3.3, 3.5):
            for ohms, percent in ((16, 0), (87, 50), (158, 100)):
                reading = resistance(supply * ohms / (100 + ohms), supply, 100)
                self.assertAlmostEqual(reading, ohms)
                self.assertAlmostEqual(percentage(reading, DEFAULTS['points']), percent)
        self.assertEqual(percentage(87, [[16, 0], [87, 30], [158, 100]]), 30)
        for voltage, supply in ((0, 3.3), (3.3, 3.3), (1, 5), (float('nan'), 3.3)):
            with self.assertRaises(ValueError): resistance(voltage, supply, 100)
        for points in ([[158, 0], [16, 100]], [[16, 5], [158, 100]], [[16, 0], [20, 60], [30, 40], [158, 100]]):
            with self.assertRaises(ValueError): validate({**DEFAULTS, 'points': points})

    def test_smoothing_fault_staleness_and_reconfiguration(self):
        now = [0.]
        state = State(clock=lambda: now[0])
        sender = state.fuel
        self.assertEqual(sender.values(), {})
        sender.configure({**DEFAULTS, 'enabled': True})
        sender.feed(3.3 * 16 / 116, 3.3)
        self.assertAlmostEqual(sender.ohms, 16)
        self.assertAlmostEqual(sender.level, 0)
        now[0] = .5
        sender.feed(3.3 * 158 / 258, 3.3)
        self.assertAlmostEqual(sender.ohms, 158)
        self.assertGreater(sender.level, 0)
        self.assertLess(sender.level, 10)
        self.assertEqual(state.snapshot()['values']['vehicle.fuel_pct']['quality'], 'live')
        now[0] = 4
        self.assertEqual(sender.values()['vehicle.fuel_pct']['quality'], 'stale')
        sender.feed(0, 3.3)
        self.assertIsNone(sender.level)
        self.assertEqual(sender.snapshot()['quality'], 'fault')
        sender.configure(DEFAULTS)
        self.assertEqual(sender.values(), {})

    def test_parking_rejects_motion_even_with_engine_off_and_stale_data(self):
        state = State(clock=lambda: 1)
        self.assertFalse(parked(state))
        stationary(state)
        self.assertTrue(parked(state))
        state.samples['vehicle.speed_kph', 515] = dict(value=25, quality='live', seen=1)
        self.assertFalse(parked(state))
        state.samples['vehicle.speed_kph', 515]['value'] = 0
        self.assertTrue(parked(state))
        state.connected = False
        self.assertFalse(parked(state))

    def test_watchdog_distinguishes_backend_loss_and_render_freeze(self):
        watch = RenderWatchdog(0)
        self.assertFalse(watch.frozen(29, True, False))
        self.assertTrue(watch.frozen(31, True, False))
        self.assertFalse(watch.frozen(40, False, False))
        self.assertFalse(watch.frozen(59, True, False))
        self.assertFalse(watch.frozen(60, True, True))
        self.assertTrue(watch.frozen(81, True, False))

    def test_backlight_explicit_device_and_bounded_values(self):
        with tempfile.TemporaryDirectory() as directory:
            device = Path(directory) / 'lcd'; device.mkdir()
            (device / 'max_brightness').write_text('255')
            (device / 'brightness').write_text('255')
            control = Backlight('lcd', directory)
            control.set(50)
            self.assertEqual((device / 'brightness').read_text(), '128')
            for value in (0, 101, True, float('nan')):
                with self.assertRaises(ValueError): control.set(value)
            with self.assertRaises(ValueError): Backlight(None, directory).set(50)


class OperationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_backup_restore_roundtrip_and_validation_before_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(clock=lambda: 0)
            stationary(state)
            path = Path(directory)
            state.operations = Operations(state, path)
            state.trip = Trip(state, path / 'trip.json')
            state.driving = Driving(state, path)
            state.race = Race(path / 'race.json')
            ops = state.operations
            await ops.change({'maintenance': dict(name='Oil', km=5000, hours=100, days=180)})
            state.trip.counters['total']['km'] = 5100
            self.assertTrue(ops.status()['maintenance'][0]['due'])
            identifier = ops.data['maintenance'][0]['id']
            await ops.change({'maintenance': {'complete': identifier}})
            self.assertFalse(ops.status()['maintenance'][0]['due'])
            self.assertEqual(len(ops.data['maintenance'][0]['history']), 1)
            backup = ops.backup({'frogdash.units.v1': {'system': 'metric'}})
            bad = deepcopy(backup); bad['trip']['counters']['a']['km'] = -1
            with self.assertRaises(ValueError): await ops.restore(bad)
            self.assertFalse((path / 'restore-pending.json').exists())
            state.trip.counters['total']['km'] = 0
            restored = await ops.restore(backup)
            self.assertEqual(state.trip.counters['total']['km'], 5100)
            self.assertEqual(restored['frogdash.units.v1']['system'], 'metric')
            self.assertFalse(state.trip.manual_valid)
            self.assertFalse((path / 'restore-pending.json').exists())
            self.assertEqual(Trip(state, path / 'trip.json').counters, state.trip.counters)
            self.assertEqual(Operations(state, path).data, ops.data)
            report = ops.diagnostic()
            self.assertIn('sender', report)
            self.assertNotIn('raw', report)

    async def test_interrupted_restore_has_recovery_journal_and_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State(clock=lambda: 0); stationary(state)
            ops = state.operations = Operations(state, directory)
            backup = ops.backup()
            with patch.object(ops, 'save', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): await ops.restore(backup)
            self.assertTrue(ops.restoring)
            self.assertTrue((Path(directory) / 'restore-pending.json').exists())
            with self.assertRaises(ValueError): await ops.change({'check': 'boot'})
            await ops.recover()
            self.assertFalse(ops.restoring)
            self.assertFalse((Path(directory) / 'restore-pending.json').exists())

    async def test_local_api_motion_gate_report_and_heartbeat(self):
        state = State(clock=lambda: 0)
        async with TestClient(TestServer(create_app(state))) as client:
            self.assertEqual((await client.post('/operations/sender', json=DEFAULTS)).status, 400)
            stationary(state)
            self.assertEqual((await client.post('/operations/sender', json=DEFAULTS)).status, 200)
            self.assertEqual((await client.post('/operations/settings', json={'check': 'boot'})).status, 200)
            self.assertEqual((await client.get('/operations/diagnostic')).status, 200)
            self.assertEqual((await client.post('/operations/settings', json={'check': 'crank'}, headers={'Origin': 'https://evil.example'})).status, 403)
            token = 'a' * 32
            self.assertFalse((await (await client.get('/ui/heartbeat/' + token)).json())['alive'])
            self.assertEqual((await client.post('/ui/heartbeat/' + token)).status, 200)
            self.assertTrue((await (await client.get('/ui/heartbeat/' + token)).json())['alive'])
            state.operations.restoring = True
            self.assertEqual((await client.post('/trip', json={'reset': 'a'})).status, 503)
            state.operations.restoring = False


class InstallerTests(unittest.TestCase):
    def test_manifest_is_deterministic_and_versions_change_with_source(self):
        root = Path(__file__).resolve().parents[1]
        contents = manifest(root)
        name = release_name(root, contents)
        self.assertEqual(name, release_name(root, contents))
        self.assertNotEqual(name, release_name(root, {**contents, 'extra': 'changed'}))

    @unittest.skipIf(__import__('sys').platform == 'win32', 'Linux symlink deployment')
    def test_failed_start_restores_previous_release_and_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old, target = root / 'old', root / 'new'
            old.mkdir(); (target / 'hardware/systemd').mkdir(parents=True)
            (target / 'VERSION').write_text('0.4.0')
            (target / 'hardware/systemd/frogdash.service').write_text('new unit')
            current, previous, unit = root / 'current', root / 'previous', root / 'frogdash.service'
            replace_link(current, old); unit.write_text('old unit')
            calls = []
            def run(args, **kwargs): calls.append(args)
            with self.assertRaises(RuntimeError): activate(target, current, previous, unit, run=run, probe=lambda _: False)
            self.assertEqual(current.resolve(), old)
            self.assertEqual(unit.read_text(), 'old unit')
            self.assertFalse(previous.exists())
            activate(target, current, previous, unit, run=run, probe=lambda _: True)
            self.assertEqual(current.resolve(), target)
            self.assertEqual(previous.resolve(), old)
