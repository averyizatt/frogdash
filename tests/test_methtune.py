"""Water/meth pulse tuning: settings mirror, validation, presets, tank mixes and the flow maths."""
import random
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash import methtune
from hardware.frogdash.methtune import (DEFAULTS, FLUIDS, KEYS, PRESETS, SETTINGS, TIMING_NAMES, apply_setting, fuel_g_min,
                                        plan, relay_on_ms, valid)
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

METH_OFF = bytes.fromhex('0000640000282800')


class Controller:
    """Stand-in for the water/meth controller: applies settings with the firmware's rules."""
    def __init__(self, state):
        self.state, self.values, self.revision, self.unsaved, self.saved = state, dict(DEFAULTS), 0, False, dict(DEFAULTS)
        self.commands = []
        self.silent = False
        self.on_ms = 0

    def status(self):
        self.state.ingest(0x30F, bytes([3, self.revision, 1 if self.unsaved else 0, 0 if self.on_ms else 1])
                          + self.on_ms.to_bytes(2, 'big') + self.values['period_ms'].to_bytes(2, 'big'))

    async def send(self, identifier, data):
        self.commands.append((identifier, bytes(data)))
        if identifier != 0x301 or self.silent:
            return
        if data[0] == 0x10:
            name = SETTINGS[data[1]][0]
            requested = int.from_bytes(data[2:4], 'big')
            applied = apply_setting(self.values, name, requested)
            self.revision, self.unsaved = (self.revision + 1) % 256, True
            self.state.ingest(0x30F, bytes([1, 0x10, 0 if applied == requested else 3, data[1]]) + applied.to_bytes(2, 'big') + bytes([self.revision, 0]))
        elif data[0] == 0x11:
            if data[1] == 0:
                self.saved, self.unsaved = dict(self.values), False
            elif data[1] == 1:
                self.values, self.unsaved, self.revision = dict(self.saved), False, (self.revision + 1) % 256
            elif data[1] == 2:
                self.values, self.unsaved, self.revision = dict(DEFAULTS), True, (self.revision + 1) % 256
            elif data[1] == 3:
                for key, (name, _, _, _) in SETTINGS.items():
                    self.state.ingest(0x30F, bytes([2, key]) + self.values[name].to_bytes(2, 'big') + bytes([self.revision, 0, 0, 0]))
            self.state.ingest(0x30F, bytes([1, 0x11, 0, data[1], 0, 0, self.revision, 0]))
        self.status()


class RulesTests(unittest.TestCase):
    def test_presets_respect_the_relay_and_the_default_is_the_most_careful(self):
        self.assertEqual(SETTINGS[1][1], 1000)   # The cycle can never be set below 1000 ms.
        self.assertEqual(SETTINGS[2][1], 500)    # The pump never runs for less than half a second.
        for name, timing in PRESETS.items():
            values = {**DEFAULTS, **timing}
            self.assertEqual(set(timing), set(TIMING_NAMES), name)
            self.assertTrue(valid(values), name)
            self.assertGreaterEqual(values['period_ms'], 4000, name)  # At most one pump start every 4 s.
            self.assertGreaterEqual(values['min_on_ms'], 1000, name)  # On for a second or more.
            gap = values['period_ms'] - values['max_on_ms']
            self.assertTrue(gap == 0 or gap >= 1000, name)            # Off for a second or more, or continuous.
            self.assertGreaterEqual(values['min_rpm'], 2000, name)
            self.assertEqual(values['overboost_assist'], 0, name)
            self.assertGreater(values['rest_s'], 0, name)
        self.assertEqual({**DEFAULTS, **PRESETS['Conservative']}, DEFAULTS)
        self.assertLessEqual(DEFAULTS['max_on_ms'] / DEFAULTS['period_ms'], .5)
        for other in ('Mild', 'Standard'):
            self.assertLess(DEFAULTS['max_on_ms'], PRESETS[other]['max_on_ms'])

    def test_tank_mixes_are_the_owners_ratios_with_rising_dose_limits(self):
        self.assertEqual([mix['meth_pct'] for mix in FLUIDS.values()], [0, 18, 36, 53])
        doses = [mix['max_dose_pct'] for mix in FLUIDS.values()]
        self.assertEqual(doses, sorted(doses))
        self.assertEqual((doses[0], DEFAULTS['max_dose_pct'], DEFAULTS['meth_pct']), (10, 10, 0))  # Water is the default.
        self.assertTrue(all(0 < dose <= 20 for dose in doses))

    def test_one_setting_never_raises_another(self):
        values = dict(DEFAULTS)
        self.assertEqual(apply_setting(values, 'min_on_ms', 3900), 2000)  # Stops at the maximum.
        self.assertEqual(values['max_on_ms'], 2000)
        self.assertEqual(apply_setting(values, 'max_on_ms', 9000), 4000)  # Stops at the cycle length.
        self.assertEqual(apply_setting(values, 'period_ms', 200), 1000)
        self.assertEqual((values['max_on_ms'], values['min_on_ms']), (1000, 1000))  # Shrunk with the cycle.
        self.assertEqual(apply_setting(values, 'min_on_ms', 100), 500)
        self.assertEqual(apply_setting(values, 'start_psi_x10', 250), 90)
        self.assertEqual(apply_setting(values, 'full_psi_x10', 10), 100)
        self.assertEqual(apply_setting(values, 'max_dose_pct', 99), 40)
        self.assertTrue(valid(values))

    def test_plan_reaches_any_valid_target_from_any_valid_start(self):
        rng = random.Random(7)
        def some():
            while True:
                values = {name: rng.randint(low, high) for name, low, high, _ in SETTINGS.values()}
                values['max_on_ms'] = min(values['max_on_ms'], values['period_ms'])
                values['min_on_ms'] = min(values['min_on_ms'], values['max_on_ms'])
                if valid(values):
                    return values
        candidates = [{**DEFAULTS, **timing} for timing in PRESETS.values()] + [some() for _ in range(60)]
        for start in candidates:
            for target in candidates:
                steps = plan(start, target)
                self.assertIsNotNone(steps)
                controller = dict(start)
                for key, value in steps:
                    self.assertEqual(apply_setting(controller, SETTINGS[key][0], value), value, 'a planned change was clamped')
                self.assertEqual(controller, target)
        self.assertEqual(plan(DEFAULTS, DEFAULTS), [])
        # A tank mix touches only the blend and the dose limit.
        self.assertEqual(plan(DEFAULTS, FLUIDS['36% meth']), [(KEYS['meth_pct'], 36), (KEYS['max_dose_pct'], 15)])

    def test_flow_maths_matches_the_engine_and_the_nozzle(self):
        # 2.3 L at 5500 RPM and 10 psi over 85 kPa of air: about 744 g of fuel a minute.
        self.assertAlmostEqual(fuel_g_min(5500, 154), 744.5, delta=1)
        self.assertAlmostEqual(60 / fuel_g_min(5500, 154) * 100, 8.1, delta=.1)   # Nozzle flat out: 8% of fuel.
        self.assertAlmostEqual(60 / fuel_g_min(2500, 119.5) * 100, 22.8, delta=.2)  # Low airflow: far more.
        self.assertEqual([relay_on_ms(on, 4000) for on in (300, 500, 2000, 3800, 4000, 9000)], [0, 500, 2000, 3500, 4000, 4000])
        self.assertEqual(relay_on_ms(900, 1000), 500)


class TuningTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        self.now = [100.0]
        state = State(clock=lambda: self.now[0])
        state.connected = True
        state.ingest(0x300, METH_OFF)
        controller = Controller(state)
        state.controls.attach(controller.send)
        state.controls.ready_at = 0
        return state, controller

    def tick(self, state, controller, seconds=.3):
        """Time passes; the controller keeps sending its telemetry and status."""
        self.now[0] += seconds
        state.ingest(0x300, METH_OFF)
        if not controller.silent:
            controller.status()

    async def sync(self, state, controller):
        controller.status()
        await state.controls.sync_meth_tune()
        self.tick(state, controller)

    async def test_mirror_reads_back_and_follows_changes(self):
        state, controller = self.make()
        try:
            self.assertFalse(state.meth_tune.supported)
            self.assertIn('flash', state.controls.reason('meth.setting'))
            await self.sync(state, controller)
            self.assertEqual(controller.commands[-1], (0x301, bytes([0x11, 3])))
            mirror = state.snapshot()['meth_tune']
            self.assertEqual((mirror['supported'], mirror['complete'], mirror['preset'], mirror['fluid']), (True, True, 'Conservative', 'Water'))
            self.assertEqual(mirror['settings'], DEFAULTS)
            result = await state.controls.execute('meth.setting', (KEYS['max_on_ms'] << 16) | 2500)
            self.assertEqual(result['status'], 'acknowledged')
            self.assertEqual(controller.commands[-1], (0x301, bytes([0x10, 3, 0x09, 0xC4])))
            self.assertFalse(state.meth_tune.complete())  # Revision moved: values are re-read.
            await self.sync(state, controller)
            mirror = state.snapshot()['meth_tune']
            self.assertEqual((mirror['settings']['max_on_ms'], mirror['unsaved'], mirror['preset'], mirror['fluid']), (2500, True, None, 'Water'))
            # The controller limits a value; the dash reports it instead of pretending.
            result = await state.controls.execute('meth.setting', (KEYS['max_on_ms'] << 16) | 9000)
            self.assertEqual((result['status'], result['message']), ('adjusted', 'Water/meth controller limited the value to 4000'))
            self.tick(state, controller)
            result = await state.controls.execute('meth.tune_action', methtune.ACTIONS['save'])
            self.assertEqual(result['status'], 'acknowledged')
            self.assertFalse(state.snapshot()['meth_tune']['unsaved'])
            # Settings can follow each other quickly: no 1.5 s quiet time for these.
            self.tick(state, controller)
            self.assertEqual((await state.controls.execute('meth.setting', (KEYS['min_rpm'] << 16) | 3000))['status'], 'acknowledged')
            self.tick(state, controller)
            self.assertEqual((await state.controls.execute('meth.setting', (KEYS['nozzle_ml_min'] << 16) | 100))['status'], 'acknowledged')
            for bad in ((15 << 16) | 5, (KEYS['period_ms'] << 16) | 500, (KEYS['min_on_ms'] << 16) | 200, (KEYS['min_rpm'] << 16) | 9000,
                        (KEYS['max_dose_pct'] << 16) | 41, 5):
                with self.assertRaises(ValueError):
                    await state.controls.execute('meth.setting', bad)
            with self.assertRaises(ValueError):
                await state.controls.execute('meth.tune_action', 4)
        finally:
            await state.controls.close()

    async def test_presets_and_tank_mixes_apply_save_and_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            state, controller = self.make()
            path = Path(folder) / 'meth-presets.json'
            state.meth_tune.load(path)
            import hardware.frogdash.server as server
            real_pause = server.preset_pause
            async def pause():  # The stand-in clock moves instead of the test waiting.
                self.tick(state, controller)
            server.preset_pause = pause
            try:
                async with TestClient(TestServer(create_app(state))) as client:
                    listing = await (await client.get('/meth/presets')).json()
                    self.assertEqual([p['name'] for p in listing['presets']], ['Conservative', 'Mild', 'Standard'])
                    self.assertEqual([f['name'] for f in listing['fluids']], ['Water', '18% meth', '36% meth', '53% meth'])
                    self.assertEqual((await client.post('/meth/presets', json={'action': 'apply', 'name': 'Standard'})).status, 409)  # Not read back yet.
                    await self.sync(state, controller)
                    controller.commands.clear()
                    reply = await client.post('/meth/presets', json={'action': 'apply', 'name': 'Standard'})
                    self.assertEqual(reply.status, 200, await reply.text())
                    self.assertEqual(controller.values, {**DEFAULTS, **PRESETS['Standard']})
                    sent = [SETTINGS[data[1]][0] for identifier, data in controller.commands if data[0] == 0x10]
                    self.assertLess(sent.index('max_on_ms'), sent.index('min_on_ms'))  # Raising: maximum first.
                    self.assertNotIn('period_ms', sent)  # Unchanged settings are not re-sent.
                    self.assertFalse({'meth_pct', 'max_dose_pct', 'nozzle_ml_min'} & set(sent))  # A flow preset leaves the tank mix alone.
                    await self.sync(state, controller)
                    self.assertEqual(state.snapshot()['meth_tune']['preset'], 'Standard')
                    # A tank mix changes the blend and the dose limit, nothing else.
                    controller.commands.clear()
                    reply = await client.post('/meth/presets', json={'action': 'fluid', 'name': '53% meth'})
                    self.assertEqual(reply.status, 200, await reply.text())
                    self.assertEqual([(data[1], int.from_bytes(data[2:4], 'big')) for identifier, data in controller.commands if data[0] == 0x10],
                                     [(KEYS['meth_pct'], 53), (KEYS['max_dose_pct'], 18)])
                    await self.sync(state, controller)
                    mirror = state.snapshot()['meth_tune']
                    self.assertEqual((mirror['preset'], mirror['fluid']), ('Standard', '53% meth'))
                    # And back down again (every ordering case is covered by the plan test above).
                    self.assertEqual((await client.post('/meth/presets', json={'action': 'apply', 'name': 'Conservative'})).status, 200)
                    self.assertEqual(controller.values, {**DEFAULTS, **FLUIDS['53% meth']})
                    await self.sync(state, controller)
                    already = await (await client.post('/meth/presets', json={'action': 'apply', 'name': 'Conservative'})).json()
                    self.assertIn('already set', already['message'])
                    # The owner's own flow preset: timing only, so it works with any tank mix.
                    self.tick(state, controller)
                    await state.controls.execute('meth.setting', (KEYS['max_on_ms'] << 16) | 2600)
                    await self.sync(state, controller)
                    saved = await (await client.post('/meth/presets', json={'action': 'save', 'name': 'Custom 2'})).json()
                    custom = {**PRESETS['Conservative'], 'max_on_ms': 2600}
                    self.assertEqual(saved['presets'][-1], {'name': 'Custom 2', 'builtin': False, 'values': custom})
                    self.assertEqual(state.snapshot()['meth_tune']['preset'], 'Custom 2')
                    for bad in ({'action': 'save', 'name': 'Standard'}, {'action': 'save', 'name': 'Mine'}, {'action': 'apply', 'name': 'Custom 1'},
                                {'action': 'delete', 'name': 'Custom 3'}, {'action': 'explode'}, {'action': 'apply', 'name': 7},
                                {'action': 'fluid', 'name': '70% meth'}, {'action': 'apply', 'name': 'Water'}):
                        self.assertEqual((await client.post('/meth/presets', json=bad)).status, 409, bad)
                    # A controller that stops answering: the preset stops part-way and says so.
                    self.tick(state, controller)
                    controller.silent = True
                    partial = await client.post('/meth/presets', json={'action': 'apply', 'name': 'Mild'})
                    self.assertEqual(partial.status, 409)
                    self.assertIn('Stopped after 0 of', await partial.text())
                restarted = State(clock=lambda: 0)
                restarted.meth_tune.load(path)
                self.assertEqual(restarted.meth_tune.user, {'Custom 2': custom})
                path.write_text('{"Custom 1": {"period_ms": 5}}')  # Damaged or hand-edited file.
                restarted.meth_tune.load(path)
                self.assertEqual(restarted.meth_tune.user, {})
            finally:
                server.preset_pause = real_pause
                await state.controls.close()

    async def test_live_flow_and_share_of_fuel(self):
        state, controller = self.make()
        try:
            await self.sync(state, controller)
            values = state.snapshot()['values']
            self.assertEqual((values['meth.flow_ml_min']['value'], values['meth.dose_pct']['quality']), (0, 'unavailable'))  # Pump off, no engine data.
            # 2 s in every 4 s through the 60 ml/min nozzle is 30 ml/min.
            controller.on_ms = 2000
            self.tick(state, controller)
            for key, value in (('ecu.rpm', 5500), ('ecu.map_kpa', 154.0)):
                state.samples[key, 0x5E8] = dict(value=value, quality='live', seen=self.now[0], source_id=0x5E8, timestamp_ms=0)
            values = state.snapshot()['values']
            self.assertEqual(values['meth.flow_ml_min']['value'], 30)
            self.assertAlmostEqual(values['meth.dose_pct']['value'], 4.0, delta=.1)   # 30 of 744 g/min.
            # The same pulse at low airflow is a much bigger share: this is what the dose limit watches.
            state.samples['ecu.rpm', 0x5E8]['value'], state.samples['ecu.map_kpa', 0x5E8]['value'] = 2500, 119.5
            self.assertAlmostEqual(state.snapshot()['values']['meth.dose_pct']['value'], 11.4, delta=.2)
        finally:
            await state.controls.close()

    async def test_older_firmware_is_reported_plainly(self):
        state, controller = self.make()
        try:
            mirror = state.snapshot()['meth_tune']
            self.assertEqual((mirror['supported'], mirror['settings'], mirror['preset'], mirror['fluid'], mirror['hold']), (False, {}, None, None, None))
            with self.assertRaisesRegex(ValueError, 'flash the current firmware'):
                await state.controls.execute('meth.setting', (KEYS['min_rpm'] << 16) | 3000)
            self.assertEqual(controller.commands, [])
        finally:
            await state.controls.close()


if __name__ == '__main__':
    unittest.main()
