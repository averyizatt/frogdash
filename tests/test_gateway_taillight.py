"""Sensor gateway (0x500-0x503) and taillight settings extension (0x103) on the dashboard side."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from hardware.frogdash.protocol import decode
from hardware.frogdash.state import State
from hardware.frogdash.wheel import SteeringWheel


class GatewayDecodeTests(unittest.TestCase):
    def test_sensor_state(self):
        v = decode(0x500, bytes.fromhex('02f4 0d7a 0400 32 07'.replace(' ', '')))
        self.assertEqual(v['vehicle.speed_kph'].value, 75.6)
        self.assertEqual(v['gateway.rpm'].value, 3450)
        self.assertEqual(v['vehicle.fuel_pct'].value, 50)
        missing = decode(0x500, bytes.fromhex('0000000000ff0000'))
        self.assertEqual(missing['vehicle.speed_kph'].quality, 'unavailable')
        self.assertIsNone(missing['vehicle.fuel_pct'].value)
        for bad in ('0000000000006500', '0000000000000008'):
            with self.assertRaises(ValueError):
                decode(0x500, bytes.fromhex(bad))

    def test_buttons_and_lights(self):
        self.assertEqual(decode(0x501, bytes([8, 31, 4, 1]))['wheel.cruise_pressed'].value, 8)
        for bad in ([8, 31, 4, 2], [32, 31, 0, 1], [8, 7, 0, 1]):
            with self.assertRaises(ValueError):
                decode(0x501, bytes(bad))
        light = decode(0x503, bytes([2, 255, 128, 0, 35, 1, 1]))
        self.assertEqual(light['interior.lower.color'].value, '#ff8000')
        self.assertTrue(light['interior.lower.commanded'].value)
        with self.assertRaises(ValueError):
            decode(0x503, bytes([0, 0, 0, 0, 0, 1, 0]))


class CruiseButtonTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.wheel = SteeringWheel(lambda: self.now)

    def press(self, bits, seconds=.08):
        self.wheel.observe_gateway(bytes([bits, 31, 0, 1]))
        self.now += seconds
        self.wheel.tick()

    def actions(self):
        return [e['action'] for e in self.wheel.events]

    def test_mapping_repeat_and_timeout(self):
        self.press(0)  # Released first arms input.
        self.press(8); self.press(0)       # SET ACCEL
        self.press(4); self.press(0)       # COAST
        self.press(16); self.press(0)      # RESUME
        self.press(1); self.press(0)       # ON
        self.press(2); self.press(0)       # OFF
        self.assertEqual(self.actions(), ['up', 'down', 'right', 'ok', 'back'])
        self.wheel.events.clear()
        for _ in range(12):
            self.press(8)                  # Held SET ACCEL repeats after 0.45 s.
        self.assertGreaterEqual(self.actions().count('up'), 3)
        self.now += .6
        self.wheel.tick()                  # Silence beyond 500 ms releases everything.
        self.assertEqual(self.wheel.snapshot(True)['status'], 'unavailable')

    def test_long_holds_go_home_once(self):
        self.press(0)
        for _ in range(45):                # ON held 3.6 s: back at 0.8 s, home at 3 s.
            self.press(1)
        self.press(0)
        self.assertEqual(self.actions(), ['back', 'home'])
        self.wheel.events.clear()
        for _ in range(25):                # OFF held 2 s: back at once, home at 1.5 s.
            self.press(2)
        self.press(0)
        self.assertEqual(self.actions(), ['back', 'home'])
        self.wheel.events.clear()
        self.press(2); self.press(0)       # A tap of OFF is still just back.
        self.assertEqual(self.actions(), ['back'])

    def test_on_held_goes_back_and_chords_cancel(self):
        self.press(0)
        for _ in range(12):
            self.press(1)
        self.press(0)
        self.assertEqual(self.actions(), ['back'])
        self.wheel.events.clear()
        self.press(1 | 8); self.press(0); self.press(0)
        self.assertEqual(self.actions(), [])


class TaillightSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 10
        self.state = State(clock=lambda: self.now)
        self.state.connected = True
        self.sent = []
        self.ack = 0

        async def sender(identifier, data):
            self.sent.append((identifier, bytes(data)))
            if identifier == 0x101 and self.ack is not None:
                self.state.ingest(0x103, bytes([1, data[0], self.ack, data[1] if len(data) > 1 else 0, 0, 7, 3, 2]))
        self.state.controls.attach(sender)
        self.state.controls.ready_at = 0
        self.refresh()

    async def asyncTearDown(self):
        await self.state.controls.close()

    def refresh(self, revision=3):
        self.state.samples['ecu.rpm', 1520] = dict(value=0, quality='live', seen=self.now, source_id=1520, timestamp_ms=0)
        self.state.ingest(0x100, bytes([1, 1, 2, 2, 255, 60, 0]))
        self.state.ingest(0x103, bytes([5, revision, 1, 7, 0b101, 0, 10, 0]))

    def report(self, revision=3):
        from hardware.frogdash.taillight import SETTINGS
        for key, (_, low, _) in SETTINGS.items():
            self.state.ingest(0x103, bytes([2, key, low >> 8, low & 255, revision, 0, 0, 0]))
        for which in range(4):
            self.state.ingest(0x103, bytes([3, which, 255, which * 50, 0, revision, 0, 0]))
        self.state.ingest(0x103, bytes([4, 0]) + b'FOXBOD')
        self.state.ingest(0x103, bytes([4, 6]) + b'Y\0\0\0\0\0')

    async def test_mirror_status_report_and_resync(self):
        snap = self.state.taillight.snapshot()
        self.assertTrue(snap['supported'] and snap['unsaved'] and not snap['complete'])
        self.assertEqual((snap['show_anim'], snap['phase_ms'], snap['profiles'][:3]), (7, 160, [True, False, True]))
        await self.state.controls.sync_taillight()
        self.assertEqual(self.sent[-1], (0x101, bytes([0x09, 3, 0])))  # Asked for a full report.
        self.report()
        snap = self.state.taillight.snapshot()
        self.assertTrue(snap['complete'])
        self.assertEqual((snap['text'], snap['colors']['turn'], snap['settings']['frame_ms']), ('FOXBODY', '#ff3200', 10))
        self.sent.clear()
        await self.state.controls.sync_taillight()
        self.assertEqual(self.sent, [])  # Up to date: nothing requested.
        self.refresh(revision=4)  # Changed elsewhere (for example a profile load).
        await self.state.controls.sync_taillight()
        self.assertEqual(self.sent, [(0x101, bytes([0x09, 3, 0]))])

    async def test_settings_commands_are_validated_packed_and_acknowledged(self):
        cases = [('lighting.setting', (13 << 16) | 5, bytes([6, 13, 0, 5])),
                 ('lighting.color', (0 << 24) | 0xFF0000, bytes([7, 0, 255, 0, 0])),
                 ('lighting.action', 0, bytes([9, 0, 0])),
                 ('lighting.action', (4 << 8) | 5, bytes([9, 4, 5]))]
        for action, value, frame in cases:
            self.now += 1; self.refresh()
            result = await self.state.controls.execute(action, value)
            self.assertEqual(self.sent[-1], (0x101, frame), action)
            self.assertEqual(result['status'], 'acknowledged', action)
        for action, value in [('lighting.setting', (1 << 16) | 5), ('lighting.setting', 22 << 16),
                              ('lighting.color', 4 << 24), ('lighting.action', (4 << 8) | 6), ('lighting.action', (0 << 8) | 1)]:
            with self.assertRaises(ValueError, msg=(action, value)):
                await self.state.controls.execute(action, value)
        self.now += 1; self.refresh(); self.ack = 3
        result = await self.state.controls.execute('lighting.setting', (11 << 16) | 10)
        self.assertEqual(result['status'], 'adjusted')

    async def test_show_text_is_chunked(self):
        await self.state.controls.execute('lighting.text', 'FOXBODY MUSTANG')
        self.assertEqual(self.sent, [(0x101, b'\x08\x00FOXBOD'), (0x101, b'\x08\x06Y MUST'), (0x101, b'\x08\x0cANG')])
        self.sent.clear(); self.now += 1; self.refresh()
        await self.state.controls.execute('lighting.text', 'ABCDEF')
        self.assertEqual(self.sent, [(0x101, b'\x08\x00ABCDEF'), (0x101, b'\x08\x06')])  # Explicit end chunk.
        with self.assertRaises(ValueError):
            await self.state.controls.execute('lighting.text', 'bad\n')

    async def test_show_mode_setting_is_parked_only_and_old_firmware_refused(self):
        self.state.samples['vehicle.speed_kph', 0x203] = dict(value=40, quality='live', seen=self.now, source_id=0x203, timestamp_ms=0)
        with self.assertRaisesRegex(ValueError, 'Park first'):
            await self.state.controls.execute('lighting.setting', (21 << 16) | 1)
        await self.state.controls.execute('lighting.setting', 21 << 16)  # Turning a show off is always allowed.
        self.now += 5  # Status reports stop: firmware without the extension.
        self.state.ingest(0x100, bytes([1, 1, 2, 2, 255, 60, 0]))
        with self.assertRaisesRegex(ValueError, 'settings extension'):
            await self.state.controls.execute('lighting.color', 0)


class InteriorLightTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_keepalive_and_persistence(self):
        now = [10]
        state = State(clock=lambda: now[0])
        state.connected = True
        sent = []

        async def sender(identifier, data):
            sent.append((identifier, bytes(data)))
        state.controls.attach(sender)
        state.controls.ready_at = 0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'interior.json'
            state.controls.load_interior(path)
            with self.assertRaisesRegex(ValueError, 'offline'):
                await state.controls.execute('interior.light', 0)
            state.ingest(0x503, bytes([1, 0, 0, 0, 0, 1, 0]))
            await state.controls.execute('interior.light', (0 << 32) | (0xFFFFFF << 8) | 35)
            self.assertEqual(sent[-1], (0x502, bytes([0, 255, 255, 255, 35, 1])))
            self.assertEqual(json.loads(path.read_text())['2'], [255, 255, 255, 35])
            sent.clear()
            now[0] += .6
            state.ingest(0x503, bytes([1, 255, 255, 255, 35, 1, 1]))
            await state.controls.refresh_interior()
            self.assertEqual([frame[0] for _, frame in sent], [1, 2])  # Both channels kept alive.
            restored = State(clock=lambda: now[0])
            restored.controls.load_interior(path)
            self.assertEqual(restored.controls.interior[1], [255, 255, 255, 35])
            await restored.controls.close()
        await state.controls.close()


if __name__ == '__main__':
    unittest.main()
