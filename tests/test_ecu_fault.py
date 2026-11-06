"""Missing MicroSquirt MAP is an advisory fault only with confirmed GPS motion."""
import unittest

from hardware.frogdash.gps import GPS
from hardware.frogdash.state import State


class MissingECUTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.state = State(clock=lambda: self.now, wall=lambda: 1700000000 + self.now)
        self.state.connected = True
        self.state.gps = GPS(clock=lambda: self.now, wall=lambda: 1700000000 + self.now, transmit=False)
        self.state.gps.connected = True
        self.report()  # Start the existing fault-bit debounce.
        self.now = 2

    def report(self, flags=2, mode=3):
        self.state.ingest(0x300, bytes([mode, 0, 100, 0, 0, 60, 60, flags]))
        return self.state.snapshot()

    def gps(self, speed, mode=3):
        self.state.gps.update({'class': 'TPV', 'mode': mode, 'speed': speed / 3.6})

    def assert_missing_fault(self, expected):
        snapshot = self.report()
        self.assertEqual(snapshot['values']['engine.boost_kpa']['quality'], 'fault' if expected else 'unavailable')
        self.assertEqual(self.state.driving.conditions(snapshot)['meth'], expected)
        # The controller's real fault stays available to diagnostics and controls.
        self.assertEqual(snapshot['values']['meth.fault_flags']['value'], 2)
        self.assertEqual(snapshot['values']['meth.state']['value'], 'FAULT')
        return snapshot

    def test_off_while_parked_then_moving_and_stopped(self):
        self.assert_missing_fault(False)  # Never had GPS or ECU data.
        for speed in (0, 1, 3):
            self.gps(speed)
            self.assert_missing_fault(False)
        self.gps(3.1)
        self.assert_missing_fault(True)
        self.gps(50)
        self.assert_missing_fault(True)
        self.gps(0)
        self.assert_missing_fault(False)

    def test_missing_fault_obeys_the_existing_alert_delay(self):
        self.gps(40)
        self.state.driving.sample(self.report())
        self.assertFalse(self.state.driving.alerts['meth']['active'])
        self.now += 1.1
        self.gps(40)
        self.state.driving.sample(self.report())
        self.assertTrue(self.state.driving.alerts['meth']['active'])

    def test_ecu_off_start_does_not_latch_before_fault_bits_finish_debouncing(self):
        for now in (0, 1.1, 1.6, 2):
            self.now = now
            snapshot = self.report()
            self.assertFalse(self.state.driving.conditions(snapshot)['meth'])
            self.state.driving.sample(snapshot)
            self.assertFalse(self.state.driving.alerts['meth']['latched'])
        # A new, additional fault still warns even before its bit is debounced.
        snapshot = self.report(flags=3)
        self.assertTrue(self.state.driving.conditions(snapshot)['meth'])

    def test_stale_no_fix_and_wheel_speed_do_not_prove_gps_motion(self):
        self.gps(50)
        self.assert_missing_fault(True)
        self.now += 4
        self.assert_missing_fault(False)
        self.gps(50, mode=1)
        self.assert_missing_fault(False)
        snapshot = self.report()
        for source in ('Wheel speed (GPS lost)', 'GPS speed held (brief dropout)'):
            snapshot['values']['vehicle.speed_kph'] = {'value': 50, 'quality': 'live', 'source': source}
            self.assertFalse(self.state.driving.conditions(snapshot)['meth'])
        # A gateway's wheel speed alone also cannot enable the missing-ECU fault.
        self.state.gps = None
        self.state.samples['vehicle.speed_kph', 0x500] = {
            'value': 50, 'quality': 'live', 'source_id': 0x500,
            'timestamp_ms': 1, 'seen': self.now}
        self.assert_missing_fault(False)

    def test_can_gps_supported_but_usb_gps_remains_authoritative(self):
        self.state.ingest(0x203, bytes.fromhex('01F400000B03110E'))  # 50 km/h, valid GPS.
        self.assert_missing_fault(False)  # USB GPS is configured and has no fix.
        self.state.gps = None
        self.assert_missing_fault(True)
        self.now += 2.1
        self.assert_missing_fault(False)

    def test_live_ecu_fault_remains_visible_and_recovers_when_map_returns(self):
        self.gps(0)
        self.state.ingest(0x5F0, bytes.fromhex('0001000000000384'))
        self.assert_missing_fault(True)  # ECU is on, but the controller cannot see MAP.
        self.now += 1.1
        self.assert_missing_fault(False)  # ECU switched off.
        self.state.ingest(0x5F2, bytes.fromhex('03F503F504D80488'))
        snapshot = self.report(flags=0, mode=1)
        self.assertEqual(snapshot['values']['engine.boost_kpa']['quality'], 'live')
        self.assertEqual(snapshot['values']['engine.boost_kpa']['value'], 0)
        self.assertFalse(self.state.driving.conditions(snapshot)['meth'])

    def test_other_sensor_controller_and_flow_faults_still_warn_while_parked(self):
        self.gps(0)
        self.report(flags=3)  # Missing MAP plus low tank.
        self.state.ingest(0x303, bytes.fromhex('7D4F00003C410100'))  # Oil sender fault.
        self.now += 2
        self.state.ingest(0x303, bytes.fromhex('7D4F00003C410100'))
        snapshot = self.report(flags=3)
        self.assertTrue(self.state.driving.conditions(snapshot)['meth'])
        self.assertEqual(snapshot['values']['engine.oil_pressure_psi']['quality'], 'fault')
        self.assertEqual(snapshot['values']['engine.boost_kpa']['quality'], 'unavailable')
        snapshot = self.report(flags=0)  # FAULT mode without a known reason still warns.
        self.assertTrue(self.state.driving.conditions(snapshot)['meth'])
        snapshot = self.report(mode=2)  # No flow while spraying is independent of missing MAP.
        snapshot['values']['meth.flow']['value'] = 'NO_FLOW'
        self.assertTrue(self.state.driving.conditions(snapshot)['meth'])


if __name__ == '__main__':
    unittest.main()
