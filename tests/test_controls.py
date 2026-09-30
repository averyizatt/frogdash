import asyncio
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.controls import COMMANDS
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 10
        self.state = State(clock=lambda: self.now)
        self.state.connected = True
        self.controls = self.state.controls
        self.sent = []
        self.ack_status = 0
        self.reply = True

        async def sender(identifier, data):
            self.sent.append((identifier, data))
            if identifier == 0x301 and self.reply:
                self.state.ingest(0x30A, bytes([data[0], self.ack_status, data[1] if len(data) > 1 else 0, 2]))
        self.controls.attach(sender)
        self.controls.ready_at = 0
        self.refresh()

    def refresh(self, mode=0, tank=100, flags=0):
        self.state.samples['ecu.rpm', 1520] = dict(value=0, quality='live', seen=self.now, source_id=1520, timestamp_ms=0)
        self.state.ingest(0x300, bytes([mode, 0, tank, 0, 0, 40, 40, flags]))
        self.state.ingest(0x307, bytes([19, 20, 15, 180, 0, 0, 0, 0]))
        self.state.ingest(0x100, bytes([1, 1, 2, 2, 255, 60, 0]))

    async def asyncTearDown(self):
        await self.controls.close()

    async def test_supported_payloads_acknowledgements_and_lighting_no_ack(self):
        for name, (identifier, code, low, high, ack) in COMMANDS.items():
            if name == 'meth.test': continue
            if name in ('lighting.setting', 'lighting.color', 'lighting.text', 'lighting.action', 'interior.light'): continue  # test_gateway_taillight
            self.now += 2
            self.refresh()
            value = low if low is not None else None
            result = await self.controls.execute(name, value)
            payload = {'lighting.mode': b'\x05\x00\x00', 'lighting.show': b'\x05\x02\x00', 'lighting.demo': b'\x05\x03\x00',
                       'lighting.override': b'\x02\x00\x00', 'lighting.clear': b'\x03',
                       'lighting.custom': b'\x04\x01\x00\x00\x00\x00'}.get(name) or (bytes([code]) if value is None else bytes([code, value]))
            self.assertEqual(self.sent[-1], (identifier, payload), name)
            self.assertEqual(result['status'], 'acknowledged' if ack else 'sent', name)

    async def test_rejects_invalid_ranges_types_and_arbitrary_frames(self):
        for action, value in [('raw', 0), ('meth.test', 0), ('meth.boost', 251),
                              ('meth.arm', True), ('meth.arm', 1.0), ('meth.arm', '1'),
                              ('lighting.mode', 2), ('meth.stop', 0), ('knock.threshold', -1)]:
            with self.assertRaises(ValueError):
                await self.controls.execute(action, value, owner=self)
        self.assertEqual(self.sent, [])

    async def test_replay_offline_stale_fault_low_tank_and_armed_test_gates(self):
        self.state.mode = 'replay'
        with self.assertRaises(ValueError): await self.controls.execute('meth.arm', 1)
        self.state.mode = 'socketcan'
        self.state.connected = False
        with self.assertRaises(ValueError): await self.controls.execute('meth.arm', 0)
        self.state.connected = True
        self.now += 1
        with self.assertRaises(ValueError): await self.controls.execute('meth.arm', 1)
        for kwargs in ({'tank': 0}, {'flags': 2}, {'mode': 3}):
            self.refresh(**kwargs)
            with self.assertRaises(ValueError): await self.controls.execute('meth.arm', 1)
        self.refresh(mode=1)
        with self.assertRaises(ValueError): await self.controls.execute('meth.test', 10, owner=self)
        self.assertEqual(self.sent, [])

    async def test_config_owner_conflict_blocks_arm_but_allows_disarm(self):
        # Use a valid checksum for the captured configuration.
        from functools import reduce
        from operator import xor
        payload = bytes([1, 1, 50, 114, 90, 100, 3])
        self.state.ingest(0x304, payload + bytes([reduce(xor, payload)]))
        with self.assertRaisesRegex(ValueError, 'CCM'): await self.controls.execute('meth.arm', 1)
        result = await self.controls.execute('meth.arm', 0)
        self.assertIn('re-arm', result['message'])

    async def test_test_stops_on_session_loss_and_enforces_cooldown(self):
        result = await self.controls.execute('meth.test', 10, owner=self)
        self.assertEqual(result['status'], 'acknowledged')
        with self.assertRaisesRegex(ValueError, 'Stop the pump test'):
            await self.controls.execute('meth.arm', 1)
        await self.controls.release(self)
        self.assertEqual(self.sent[-1], (0x301, b'\x03'))
        self.assertIsNone(self.controls.test_owner)
        with self.assertRaisesRegex(ValueError, 'cooldown'): await self.controls.execute('meth.test', 10, owner=self)

    async def test_test_auto_stops_at_deadline_and_stale_telemetry(self):
        await self.controls.execute('meth.test', 10, owner=self)
        self.now += 3.1
        self.refresh()
        await asyncio.sleep(.15)
        self.assertEqual(self.sent[-1], (0x301, b'\x03'))
        self.now += 4
        self.refresh()
        await self.controls.execute('meth.test', 10, owner=self)
        self.now += .6
        await asyncio.sleep(.15)
        self.assertEqual(self.sent[-1], (0x301, b'\x03'))
        self.assertIsNone(self.controls.test_owner)

    async def test_ack_rejection_and_timeout_never_report_success_or_retry(self):
        self.ack_status = 1
        result = await self.controls.execute('meth.arm', 1)
        self.assertEqual(result['status'], 'rejected')
        self.now += 2
        self.refresh()
        self.reply = False
        result = await self.controls.execute('meth.arm', 1)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(len(self.sent), 2)
        with self.assertRaisesRegex(ValueError, 'late'): await self.controls.execute('meth.arm', 1)

    async def test_stop_preempts_pending_arm(self):
        self.reply = False
        start = asyncio.create_task(self.controls.execute('meth.arm', 1))
        await asyncio.sleep(0)
        self.reply = True
        stop = await self.controls.execute('meth.arm', 0)
        self.assertEqual(stop['status'], 'acknowledged')
        self.assertEqual((await start)['status'], 'unknown')
        self.assertIsNone(self.controls.pending)

    async def test_wrong_ack_and_other_writer(self):
        self.reply = False
        task = asyncio.create_task(self.controls.execute('meth.boost', 25))
        await asyncio.sleep(0)
        self.state.ingest(0x30A, bytes([4, 0, 26, 2]))
        self.assertFalse(self.controls.pending['future'].done())
        self.state.ingest(0x301, b'\x01\x01')
        self.assertEqual((await task)['status'], 'unknown')

    async def test_websocket_control_and_no_duplicate_resend(self):
        async with TestClient(TestServer(create_app(self.state))) as client:
            ws = await client.ws_connect('/state')
            message = {'type': 'command', 'request_id': 'one', 'action': 'meth.arm', 'value': 1}
            await ws.send_json(message)
            async def result():
                while True:
                    response = await ws.receive_json()
                    if response['type'] == 'command_result': return response
            self.assertEqual((await result())['status'], 'acknowledged')
            await ws.send_json(message)
            self.assertEqual((await result())['status'], 'rejected')
            self.assertEqual(len(self.sent), 1)
            await ws.close()


class TaillightControlTests(unittest.IsolatedAsyncioTestCase):
    """Shows, demo, overrides and custom one-shots replace turn signals: parked-only, auto-cleared."""
    asyncSetUp, asyncTearDown, refresh = ControlTests.asyncSetUp, ControlTests.asyncTearDown, ControlTests.refresh

    def drive(self, kph):
        self.state.samples['vehicle.speed_kph', 0x203] = dict(value=kph, quality='live', seen=self.now, source_id=0x203, timestamp_ms=0)

    async def test_show_demo_override_custom_payloads(self):
        for action, value, payload in [('lighting.show', 32, b'\x05\x02\x20'), ('lighting.demo', None, b'\x05\x03\x00'),
                                       ('lighting.override', 0x26, b'\x02\x02\x06'),
                                       ('lighting.custom', 2, b'\x04\x02\x00\x00\x03\x96'),
                                       ('lighting.custom', (3 << 16) | (ord('V') << 8) | ord('8'), b'\x04\x03\x00\x00V8'),
                                       ('lighting.clear', None, b'\x03')]:
            self.now += 1
            self.refresh()
            await self.controls.execute(action, value)
            self.assertEqual(self.sent[-1], (0x101, payload), action)
        self.assertFalse(self.controls.lighting_active)  # Clear ends it.

    async def test_invalid_values_are_refused(self):
        for action, value in [('lighting.show', 33), ('lighting.override', 0x70), ('lighting.override', 0x07),
                              ('lighting.custom', 4), ('lighting.custom', (3 << 16) | 0x0A41), ('lighting.demo', 1)]:
            with self.assertRaises(ValueError, msg=(action, value)):
                await self.controls.execute(action, value)
        self.assertEqual(self.sent, [])

    async def test_parked_only_but_clear_and_modes_always_work(self):
        self.drive(40)
        for action, value in [('lighting.show', 0), ('lighting.demo', None), ('lighting.override', 0x33), ('lighting.custom', 1)]:
            with self.assertRaisesRegex(ValueError, 'Park first'):
                await self.controls.execute(action, value)
        await self.controls.execute('lighting.mode', 1)
        self.now += 1
        self.refresh(); self.drive(40)
        await self.controls.execute('lighting.clear')
        self.assertEqual([frame for _, frame in self.sent], [b'\x05\x01\x00', b'\x03'])

    async def test_moving_clears_an_active_show_after_one_second(self):
        await self.controls.execute('lighting.show', 5)
        self.assertTrue(self.controls.lighting_active)
        self.sent.clear()
        self.refresh(); self.drive(3)  # Creeping / GPS jitter below 5 km/h: no reset.
        await self.controls.check_lighting()
        self.now += 2
        self.refresh(); self.drive(3)
        await self.controls.check_lighting()
        self.assertEqual(self.sent, [])
        self.refresh(); self.drive(30)
        await self.controls.check_lighting()  # Moving starts the one-second debounce.
        self.now += .5
        self.refresh(); self.drive(30)
        await self.controls.check_lighting()
        self.assertEqual(self.sent, [])
        self.now += .6
        self.refresh(); self.drive(30)
        await self.controls.check_lighting()
        self.assertEqual(self.sent, [(0x101, b'\x03')])
        self.assertFalse(self.controls.lighting_active)
        self.assertIn('turn signals', self.controls.last['message'])

    async def test_shows_started_elsewhere_are_also_cleared_when_moving(self):
        # The taillight's own Wi-Fi page started a show: both sides report SHOW (8).
        self.state.ingest(0x100, bytes([8, 8, 0, 0, 255, 60, 0]))
        self.assertEqual(self.state.samples['lighting.left_state', 0x100]['value'], 'SHOW')
        self.assertEqual(self.state.samples['lighting.left_state', 0x100]['quality'], 'live')
        self.drive(50)
        await self.controls.check_lighting()
        self.now += 1.1
        self.state.ingest(0x100, bytes([8, 8, 0, 0, 255, 60, 0])); self.drive(50)
        await self.controls.check_lighting()
        self.assertEqual(self.sent, [(0x101, b'\x03')])
