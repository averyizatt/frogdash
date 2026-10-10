"""Problems from the first drives: a fuel gauge that blanked and sloshed, a pump test that
needed a GPS fix, and a GPS line that did not say why there was no speed."""
import unittest

from hardware.frogdash.fuel import HOLD_S, FuelGauge
from hardware.frogdash.gps import GPS
from hardware.frogdash.state import State
from hardware.frogdash import selftest


def sender(value, quality='live'):
    return {'value': value, 'quality': quality, 'source_id': 0x500, 'timestamp_ms': 0}


class FuelGaugeTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.gauge = FuelGauge(lambda: self.now)

    def run_for(self, seconds, value, still=False, quality='live', step=.1):
        shown = None
        for _ in range(round(seconds / step)):
            self.now += step
            shown = self.gauge.step(sender(value(self.now) if callable(value) else value, quality), still)
        return shown

    def test_first_reading_shows_at_once_and_slosh_is_damped(self):
        shown = self.run_for(.1, 50)
        self.assertEqual(shown['vehicle.fuel_pct']['value'], 50)
        # Fuel swinging between 30% and 70% once a second around a true 50%.
        low = high = 50
        for _ in range(600):
            self.now += .1
            value = 70 if int(self.now) % 2 else 30
            level = self.gauge.step(sender(value), False)['vehicle.fuel_pct']['value']
            low, high = min(low, level), max(high, level)
        self.assertGreater(low, 45)
        self.assertLess(high, 55)
        # The undamped reading is still there for diagnosis.
        self.assertIn(self.gauge.step(sender(30), False)['fuel.sender_pct']['value'], (30, 70))

    def test_follows_a_real_change_slowly_while_driving_and_quickly_when_parked(self):
        self.run_for(5, 60)
        driving = self.run_for(20, 40)['vehicle.fuel_pct']['value']
        self.assertGreater(driving, 46)          # 20 s into a 45 s time constant: partway there.
        self.assertLess(driving, 56)
        settled = self.run_for(240, 40)['vehicle.fuel_pct']['value']
        self.assertAlmostEqual(settled, 40, delta=.5)
        # A fill-up while parked shows within seconds.
        parked = self.run_for(15, 95, still=True)['vehicle.fuel_pct']['value']
        self.assertGreater(parked, 90)

    def test_single_wild_readings_are_ignored(self):
        self.run_for(10, 50)
        for _ in range(100):
            self.now += .25
            spike = int(self.now * 4) % 10 == 0   # One reading in ten jumps to 100%.
            level = self.gauge.step(sender(100 if spike else 50), False)['vehicle.fuel_pct']['value']
            self.assertAlmostEqual(level, 50, delta=.5)

    def test_sender_dropout_keeps_the_last_level_then_gives_up(self):
        self.run_for(10, 62)
        for quality in ('unavailable', 'stale'):
            shown = self.run_for(2, None, quality=quality)
            self.assertEqual((shown['vehicle.fuel_pct']['value'], shown['vehicle.fuel_pct']['quality']), (62, 'live'))
            self.assertIn('held', shown['vehicle.fuel_pct']['source'])
            self.assertEqual(shown['fuel.sender_pct']['quality'], quality)   # The sender itself is reported honestly.
            self.run_for(1, 62)
        gone = self.run_for(HOLD_S + 1, None, quality='unavailable')
        self.assertEqual((gone['vehicle.fuel_pct']['value'], gone['vehicle.fuel_pct']['quality']), (None, 'unavailable'))
        back = self.run_for(.2, 35)
        self.assertEqual(back['vehicle.fuel_pct']['value'], 35)   # A fresh start, not a slow crawl from 62.

    def test_dash_applies_it_to_the_gateway_sender_only(self):
        now = [10.0]
        state = State(clock=lambda: now[0])
        state.connected = True
        def gateway(percent, valid=7):
            state.ingest(0x500, bytes([0, 0, 0, 0, 0, 0, percent, valid]))
        gateway(80)
        self.assertEqual(state.snapshot()['values']['vehicle.fuel_pct']['value'], 80)
        for _ in range(40):                      # Ten seconds of slosh between 60 and 100.
            now[0] += .25
            gateway(100 if _ % 2 else 60)
            level = state.snapshot()['values']['vehicle.fuel_pct']['value']
            self.assertGreater(level, 74)
            self.assertLess(level, 86)
        # The sender reports itself invalid for a moment (wiper lift): the gauge does not blank.
        now[0] += .25
        gateway(255, valid=3)
        values = state.snapshot()['values']
        self.assertEqual(values['vehicle.fuel_pct']['quality'], 'live')
        self.assertGreater(values['vehicle.fuel_pct']['value'], 74)
        self.assertEqual(values['fuel.sender_pct']['quality'], 'unavailable')
        # A separate fuel controller (0x204) already filters its own value: passed through untouched.
        other = State(clock=lambda: now[0])
        other.connected = True
        other.ingest(0x204, bytes.fromhex('01f401'))
        self.assertEqual(other.snapshot()['values']['vehicle.fuel_pct']['value'], 50)
        other.ingest(0x204, bytes.fromhex('03e801'))
        self.assertEqual(other.snapshot()['values']['vehicle.fuel_pct']['value'], 100)
        self.assertNotIn('fuel.sender_pct', other.snapshot()['values'])


class GpsDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.gps = GPS(clock=lambda: self.now, wall=lambda: 0)

    def sky(self, strengths, used=0):
        self.gps.update({'class': 'SKY', 'device': '/dev/ttyACM0',
                         'satellites': [{'ss': s, 'used': i < used} for i, s in enumerate(strengths)]})

    def test_each_reason_for_no_speed_is_named(self):
        self.assertEqual(self.gps.diagnosis()['state'], 'starting')     # Not tried yet: not an error.
        self.gps.gpsd_ok, self.gps.gpsd_error = False, 'Connection refused'
        self.assertEqual(self.gps.diagnosis()['state'], 'no-gpsd')
        self.gps.gpsd_ok = True
        self.assertEqual(self.gps.diagnosis()['state'], 'silent')       # gpsd up, nothing from a receiver.
        self.assertIn('wrong port', self.gps.diagnosis()['fix'])
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 1})
        found = self.gps.diagnosis()
        self.assertEqual(found['state'], 'deaf')                        # Talking, hears nothing.
        self.assertIn('/dev/ttyACM0', found['text'])
        self.sky([0, 0, 0])
        self.assertEqual(self.gps.diagnosis()['state'], 'deaf')
        self.sky([14, 19, 22, 17])
        found = self.gps.diagnosis()
        self.assertEqual(found['state'], 'weak')                        # The radio-noise signature.
        self.assertIn('22 dB', found['text'])
        self.assertIn('USB 3', found['fix'])
        self.sky([38, 41, 33, 29, 36])
        self.assertEqual(self.gps.diagnosis()['state'], 'searching')
        self.sky([38, 41, 33, 29, 36], used=5)
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 3, 'speed': 10.0})
        found = self.gps.diagnosis()
        self.assertEqual((found['state'], found['fix']), ('fix', ''))
        self.assertIn('5 satellites', found['text'])
        self.now += 20                                                   # Receiver unplugged.
        self.assertEqual(self.gps.diagnosis()['state'], 'silent')

    def test_a_named_port_that_no_longer_matches_is_called_out(self):
        gps = GPS(clock=lambda: self.now, wall=lambda: 0, device='/dev/ttyACM0')
        gps.gpsd_ok = True
        gps.update({'class': 'TPV', 'device': '/dev/ttyACM1', 'mode': 3, 'speed': 5.0})   # Came back under another name.
        found = gps.diagnosis()
        self.assertEqual(found['state'], 'silent')
        self.assertIn('/dev/ttyACM1', found['text'])
        self.assertIn('--gps-device', found['fix'])

    def test_system_check_and_snapshot_carry_it(self):
        state = State(clock=lambda: self.now)
        state.gps = self.gps
        self.gps.gpsd_ok = True
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 1})
        self.sky([15, 20])
        self.assertEqual(state.snapshot()['gps']['diagnosis']['state'], 'weak')
        line = next(l for l in selftest.report(state)['lines'] if l['name'] == 'USB GPS')
        self.assertEqual(line['status'], 'warn')
        self.assertIn('all weak', line['detail'])
        self.now += 30
        line = next(l for l in selftest.report(state)['lines'] if l['name'] == 'USB GPS')
        self.assertEqual(line['status'], 'fail')
        self.assertIn('No receiver is reporting', line['detail'])


class PumpTestWithoutGpsTests(unittest.IsolatedAsyncioTestCase):
    def make(self, rpm, flags=0):
        self.now = 50.0
        state = State(clock=lambda: self.now)
        state.connected = True
        state.ingest(0x300, bytes([0, 0, 100, 0, 0, 40, 40, flags]))
        state.samples['ecu.rpm', 1520] = dict(value=rpm, quality='live', seen=self.now, source_id=1520, timestamp_ms=0)
        self.sent = []
        async def sender(identifier, data):
            self.sent.append((identifier, bytes(data)))
            if identifier == 0x301:
                state.ingest(0x30A, bytes([data[0], 0, data[1] if len(data) > 1 else 0, 2]))
        state.controls.attach(sender)
        state.controls.ready_at = 0
        return state

    async def test_engine_running_with_no_gps_fix_can_test_the_pump(self):
        state = self.make(rpm=900)
        try:
            self.assertIsNone(state.controls.reason('meth.test'))
            result = await state.controls.execute('meth.test', 100, owner=self)
            self.assertEqual((result['status'], self.sent[0]), ('acknowledged', (0x301, bytes([0x02, 100]))))
            await state.controls.stop_test('done')
            # Knock calibration in the garage with the engine running works too.
            self.now += 5
            state.ingest(0x307, bytes([19, 20, 15, 180, 0, 0, 0, 0]))
            self.assertIsNone(state.controls.reason('knock.threshold'))
        finally:
            await state.controls.close()

    async def test_a_speed_reading_that_says_moving_still_refuses(self):
        state = self.make(rpm=3000)
        try:
            state.samples['vehicle.speed_kph', 0x203] = dict(value=60, quality='live', seen=self.now, source_id=0x203, timestamp_ms=0)
            self.assertIn('Stop the car first', state.controls.reason('meth.test'))
            self.assertIn('Stop the car first', state.controls.reason('knock.threshold'))
            state.samples['vehicle.speed_kph', 0x203]['value'] = 0
            self.assertIsNone(state.controls.reason('meth.test'))
        finally:
            await state.controls.close()

    async def test_information_bits_do_not_block_but_real_faults_do(self):
        for flags, blocked in ((32, False), (4, False), (36, False), (1, True), (2, True), (33, True)):
            state = self.make(rpm=0, flags=flags)
            try:
                reason = state.controls.reason('meth.test')
                self.assertEqual(reason is not None, blocked, (flags, reason))
            finally:
                await state.controls.close()


if __name__ == '__main__':
    unittest.main()
