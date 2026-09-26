import math
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.driving import Driving, DEFAULTS, CHANNELS, validate_settings
from hardware.frogdash.health import Health, throttled_flags
from hardware.frogdash.state import State
from hardware.frogdash.server import create_app
from hardware.frogdash.connectivity import TransferPortal
from hardware.frogdash.log_channels import CHANNELS as LOG_CHANNELS, row_values


class DrivingTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.state = State(clock=lambda: self.now, wall=lambda: 1700000000 + self.now)
        self.drive = self.state.driving
        self.values = {'engine.rpm': 2500, 'engine.oil_pressure_psi': 50, 'engine.boost_kpa': 50,
                       'engine.afr': 12.4, 'ecu.afr_target': 12.5, 'engine.coolant_c': 90,
                       'meth.fault_flags': 0, 'meth.state': 'OFF', 'meth.flow': 'NO_FLOW',
                       'knock.warning': False, 'knock.critical': False}

    def sample(self, t, **changes):
        self.now = t
        self.values.update(changes)
        snapshot = {'timestamp_ms': int((1700000000 + t) * 1000), 'values': {
            k: {'value': v, 'quality': 'live' if v is not None else 'stale'} for k, v in self.values.items()},
            'recording': {'state': 'disabled'}}
        self.drive.sample(snapshot)
        return snapshot

    def test_oil_debounce_latch_acknowledge_rearm_and_unknown(self):
        self.sample(0, **{'engine.oil_pressure_psi': 10})
        self.sample(.5)
        self.assertFalse(self.drive.alerts['oil']['active'])
        self.sample(1.1)
        self.assertTrue(self.drive.alerts['oil']['active'])
        self.assertEqual(self.drive.marker_seq, 1)
        self.sample(2, **{'engine.oil_pressure_psi': None})
        self.assertTrue(self.drive.alerts['oil']['active'])
        self.assertEqual(self.drive.alerts['oil']['condition'], 'unknown')
        self.drive.acknowledge('oil')
        self.assertTrue(self.drive.alerts['oil']['latched'])
        self.sample(3, **{'engine.oil_pressure_psi': 10})
        self.assertEqual(self.drive.marker_seq, 1)
        self.sample(4, **{'engine.rpm': 800})
        self.sample(5.1)
        self.assertFalse(self.drive.alerts['oil']['latched'])
        self.sample(6, **{'engine.rpm': 2500})
        self.sample(7.1)
        self.assertEqual(self.drive.marker_seq, 2)
        self.assertFalse(self.drive.alerts['oil']['acknowledged'])

    def test_recovered_alert_stays_visible_until_ack(self):
        self.sample(0, **{'knock.warning': True}); self.sample(.3)
        self.sample(1, **{'knock.warning': False}); self.sample(2.1)
        self.assertFalse(self.drive.alerts['knock']['active'])
        self.assertTrue(self.drive.alerts['knock']['latched'])
        self.drive.acknowledge('all')
        self.assertFalse(self.drive.alerts['knock']['latched'])

    def test_lean_requires_live_target_rpm_boost_and_duration(self):
        self.sample(0, **{'engine.afr': 16, 'engine.boost_kpa': -20}); self.sample(2)
        self.assertFalse(self.drive.alerts['lean']['active'])
        self.sample(3, **{'engine.boost_kpa': 50, 'ecu.afr_target': None}); self.sample(5)
        self.assertFalse(self.drive.alerts['lean']['active'])
        self.sample(6, **{'ecu.afr_target': 12.5}); self.sample(6.9)
        self.assertTrue(self.drive.alerts['lean']['active'])
        self.assertEqual(self.drive.current['events'][-1]['context']['engine.afr']['value'], 16)

    def test_meth_flow_only_while_spraying_and_fault_bits_independent(self):
        self.sample(0, **{'meth.state': 'TEST'}); self.sample(2)
        self.assertFalse(self.drive.alerts['meth']['active'])
        self.sample(3, **{'meth.state': 'SPRAYING'}); self.sample(4.1)
        self.assertTrue(self.drive.alerts['meth']['active'])
        self.assertEqual(self.drive.current['events'][-1]['rule'], 'meth')

    def test_settings_validation_is_atomic_and_rejects_extra_fields(self):
        for key, value in [('oil_rpm', True), ('lean_delta', float('nan')), ('coolant_c', 500), ('chime', 1)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.drive.configure({**DEFAULTS, key: value})
        self.assertEqual(self.drive.settings, DEFAULTS)
        with self.assertRaises(ValueError): validate_settings({**DEFAULTS, 'shutdown': True})

    def test_bookmark_capture_and_log_channel_and_rate_limit(self):
        snap = self.sample(0)
        event = self.drive.bookmark('Hesitation', snapshot=snap)
        self.assertEqual(event['t'], 0)
        self.assertIsNone(event['log'])
        self.sample(1, **{'engine.rpm': 3000})
        self.assertEqual(event['context']['engine.rpm']['value'], 2500)
        self.drive.bookmark('Second', snapshot=snap)
        with self.assertRaises(ValueError): self.drive.bookmark('Too soon')
        with self.assertRaises(ValueError): self.drive.bookmark('Bad\nlabel')
        data = row_values(self.state.snapshot(), 1)
        index = next(i for i, c in enumerate(LOG_CHANNELS) if c.key == 'dash.bookmark_id')
        self.assertEqual(data[3 + index * 2], 2)

    def test_session_points_peaks_quality_and_engine_stop(self):
        self.sample(0)
        self.sample(1, **{'engine.boost_kpa': 85, 'engine.afr': None})
        d = self.drive.current
        self.assertEqual(d['stats']['engine.boost_kpa'], 85)
        self.assertIsNone(d['points'][-1][1 + CHANNELS.index('engine.afr')])
        self.sample(2, **{'engine.rpm': 0}); self.sample(122.1)
        self.assertIsNone(self.drive.current)
        self.assertEqual(self.drive.finished[0]['status'], 'complete')

    def test_graph_and_event_memory_bounded(self):
        for i in range(11000): self.sample(i / 2)
        self.assertLessEqual(len(self.drive.current['points']), 10800)
        self.assertEqual(self.drive.current['sample_seconds'], 1)
        for i in range(300):
            self.now += 1
            self.drive.bookmark('Repeated marker')
        self.assertEqual(len(self.drive.current['events']), 250)
        self.assertEqual(self.drive.current['event_count'], 300)

    def test_error_frames_and_read_only_power_flags(self):
        self.state.ingest(0x40, bytes(8), error=True)
        self.state.ingest(0x100, bytes(8), error=True)
        self.assertEqual(self.state.can_errors, {'frames': 2, 'bus_off': 1, 'restarts': 1})
        flags = throttled_flags('throttled=0x50005\n')
        self.assertTrue(all(flags[k] for k in ('undervoltage_now', 'throttled_now', 'undervoltage_since_boot', 'throttled_since_boot')))
        health = Health(self.state)
        with patch('hardware.frogdash.health.os.name', 'nt'):
            data = health.collect()
        self.assertIsNone(data['power'])
        self.assertIsNone(data['can'])
        self.assertGreater(data['disk']['free_bytes'], 0)

    def test_linux_health_parses_iproute_and_unavailable_is_not_zero(self):
        health = Health(self.state)
        link = [{'linkinfo': {'info_data': {'state': 'BUS-OFF', 'bittiming': {'bitrate': 500000},
                                           'berr_counter': {'tx': 128, 'rx': 4}}},
                 'stats64': {'rx': {'errors': 4, 'dropped': 1}, 'tx': {'errors': 8, 'dropped': 0}}}]
        with patch('hardware.frogdash.health.os.name', 'posix'), \
             patch('hardware.frogdash.health.Path') as path, \
             patch('hardware.frogdash.health.shutil.which', side_effect=lambda name: '/usr/bin/' + name), \
             patch('hardware.frogdash.health.command', side_effect=['throttled=0x10000', json.dumps(link)]) as command:
            path.return_value.read_text.return_value = '51000'
            result = health.collect()
        self.assertEqual(result['cpu_c'], 51)
        self.assertEqual(result['can']['state'], 'BUS-OFF')
        self.assertEqual(result['can']['tx_errors'], 8)
        self.assertFalse(result['power']['undervoltage_now'])
        self.assertTrue(result['power']['undervoltage_since_boot'])
        self.assertEqual(command.call_args_list[1].args, ('/usr/bin/ip', '-j', '-details', '-statistics', 'link', 'show', 'dev', 'can0'))
        with patch('hardware.frogdash.health.os.name', 'posix'), \
             patch('hardware.frogdash.health.Path') as path, \
             patch('hardware.frogdash.health.shutil.which', return_value='/usr/bin/tool'), \
             patch('hardware.frogdash.health.command', side_effect=PermissionError()):
            path.return_value.read_text.side_effect = PermissionError()
            result = health.collect()
        self.assertIsNone(result['cpu_c'])
        self.assertIsNone(result['power'])
        self.assertIsNone(result['can'])


class DrivingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistence_checkpoint_recovery_retention_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State()
            drive = state.driving = Driving(state, directory)
            drive.configure({**DEFAULTS, 'oil_psi': 22})
            drive.bookmark('Checkpoint')
            name = drive.current['name']
            await drive.save(force=True)
            restart = Driving(state, directory)
            self.assertEqual(restart.settings['oil_psi'], 22)
            self.assertEqual((await restart.get_review(name))['status'], 'interrupted')
            sentinel = Path(directory) / 'drives' / 'keep.json'; sentinel.write_text('keep')
            for i in range(23):
                drive.finish('Test ended')
                drive.start_drive(state.snapshot())
                await drive.save(force=True)
            self.assertLessEqual(len(drive.disk_files()), 20)
            self.assertEqual(sentinel.read_text(), 'keep')
            self.assertFalse(list(Path(directory).rglob('*.tmp')))
            self.assertEqual((await drive.get_reviews())[0]['status'], 'recording')

    async def test_local_settings_markers_and_portal_read_only_authentication(self):
        state = State()
        async with TestClient(TestServer(create_app(state))) as client:
            response = await client.post('/drive/settings', json={**DEFAULTS, 'oil_psi': 20})
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['settings']['oil_psi'], 20)
            self.assertEqual((await client.post('/drive/settings', json=DEFAULTS, headers={'Origin': 'https://evil.example'})).status, 403)
            self.assertEqual((await client.post('/drive/mark', json={'label': 'Test marker'})).status, 200)
            self.assertEqual((await client.post('/drive/ack', json={'key': 'all'})).status, 200)
            self.assertEqual((await client.post('/drive/ack', json={'key': 'nope'})).status, 400)
            drives = (await (await client.get('/drives')).json())['drives']
            name = drives[0]['name']
            data = await (await client.get('/drives/' + name)).json()
            self.assertEqual(data['events'][0]['label'], 'Test marker')
            self.assertEqual((await client.get('/drives/not-a-review.json')).status, 404)
            portal = TransferPortal(state)
            async with TestClient(TestServer(portal.app('127.0.0.0/8'))) as phone:
                self.assertEqual((await phone.get('/api/drives')).status, 401)
                self.assertEqual((await phone.get('/review.js')).status, 200)
                origin = str(phone.make_url('/')).rstrip('/')
                self.assertEqual((await phone.post('/session', json={'code': portal.code}, headers={'Origin': origin})).status, 200)
                self.assertEqual((await phone.get('/api/drives/' + name)).status, 200)
                self.assertEqual((await phone.post('/drive/ack', json={'key': 'all'}, headers={'Origin': origin})).status, 404)
                self.assertEqual((await phone.get('/api/drives/not-a-review.json')).status, 404)
                await portal.close()
                self.assertEqual((await phone.get('/api/drives/' + name)).status, 401)

    async def test_settings_and_storage_failure_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            block = Path(directory) / 'file'; block.write_text('occupied')
            state = State()
            drive = Driving(state, block)
            drive.configure(DEFAULTS); drive.bookmark('Test')
            await drive.save(force=True)
            self.assertTrue(drive.storage_error)
            self.assertTrue(drive.settings_error)
