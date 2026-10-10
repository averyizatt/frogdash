"""GPS start-up, the reasons for no speed as the real connection loop produces them, the
recovery watchdog's steps, and the root helper run against a stand-in system."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest

from hardware.frogdash.gps import GPS, UBX_COLD_START, UBX_WARM_START, send_to_receiver, ubx
from hardware.frogdash.gpswatch import GpsRecovery, NO_FIX_RETRY_S, SILENT_RETRY_S
from hardware.frogdash.state import State
from hardware.frogdash import selftest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tools/frogdash_gps.sh'
SHELL = shutil.which('sh')
UBLOX = 'usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00'
CABLE = 'usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0'


class ReceiverCommandTests(unittest.TestCase):
    def test_restart_commands_are_the_published_u_blox_frames(self):
        self.assertEqual(UBX_WARM_START.hex(' '), 'b5 62 06 04 04 00 01 00 02 00 11 6c')
        self.assertEqual(UBX_COLD_START.hex(' '), 'b5 62 06 04 04 00 ff ff 02 00 0e 61')
        self.assertEqual(ubx(0x06, 0x04, bytes([0, 0, 2, 0])).hex(' '), 'b5 62 06 04 04 00 00 00 02 00 10 68')  # Hot start

    def test_they_reach_the_receiver_as_a_gpsd_device_command(self):
        server = socket.create_server(('127.0.0.1', 0))
        got = []

        def serve():
            link, _ = server.accept()
            with link:
                got.append(link.recv(4096))
                link.sendall(b'{"class":"DEVICE","path":"/dev/ttyACM0"}\n')

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            send_to_receiver('/dev/ttyACM0', UBX_WARM_START, port=server.getsockname()[1])
        finally:
            thread.join(5)
            server.close()
        self.assertEqual(got, [b'?DEVICE={"path":"/dev/ttyACM0","hexdata":"b5620604040001000200116c"}\n'])

    def test_only_a_u_blox_receiver_is_sent_them(self):
        sent = []
        gps = GPS(clock=lambda: 0, wall=lambda: 0)
        self.assertFalse(gps.restart_receiver(send=lambda *a: sent.append(a)))       # Nothing known yet.
        gps.update({'class': 'DEVICES', 'devices': [{'path': '/dev/ttyUSB0', 'driver': 'NMEA0183'}]})
        self.assertFalse(gps.restart_receiver(send=lambda *a: sent.append(a)))       # Another make: left alone.
        gps.update({'class': 'DEVICE', 'path': '/dev/ttyACM0', 'driver': 'u-blox', 'activated': '2026-10-09T00:00:00Z'})
        gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 1})
        self.assertEqual(gps.driver(), 'u-blox')
        self.assertTrue(gps.restart_receiver(send=lambda *a: sent.append(a)))
        self.assertTrue(gps.restart_receiver(cold=True, send=lambda *a: sent.append(a)))
        self.assertEqual(sent, [('/dev/ttyACM0', UBX_WARM_START), ('/dev/ttyACM0', UBX_COLD_START)])


class ConnectionLoopDiagnosisTests(unittest.TestCase):
    """The dash reopens a silent gpsd connection every 10 s; the reason must survive that."""
    def setUp(self):
        self.now = 0.0
        self.gps = GPS(clock=lambda: self.now, wall=lambda: 0)

    def link(self, ok=True):
        # What gpsd() does around each connection attempt.
        if self.gps.started is None:
            self.gps.started = self.now
        if ok:
            self.gps.connected, self.gps.gpsd_ok, self.gps.gpsd_error = True, True, None
            self.gps.linked_at = self.now
        else:
            self.gps.connected, self.gps.gpsd_ok, self.gps.gpsd_error = False, False, 'Connection refused'

    def test_start_up_then_a_receiver_that_never_reports(self):
        self.assertEqual(self.gps.diagnosis()['state'], 'starting')
        self.link()
        self.now = 5
        self.assertEqual(self.gps.diagnosis()['state'], 'starting')     # Not an error in the first seconds.
        for self.now in (12, 23, 34, 45):                                # Reconnect after reconnect, never a report.
            self.gps.connected = False
            self.link()
            found = self.gps.diagnosis()
            self.assertEqual(found['state'], 'starting' if self.now <= 15 else 'silent', self.now)
        self.assertIn('no port at all', found['text'])
        self.gps.update({'class': 'DEVICES', 'devices': [{'path': '/dev/ttyUSB0', 'driver': None}]})
        self.assertIn('/dev/ttyUSB0', self.gps.diagnosis()['text'])      # Says which port gpsd is watching.

    def test_gpsd_not_reachable_and_time_to_first_position(self):
        self.link(ok=False)
        found = self.gps.diagnosis()
        self.assertEqual(found['state'], 'no-gpsd')
        self.assertIn('Connection refused', found['text'])
        self.now = 3
        self.link()
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 1})
        self.assertIsNone(self.gps.first_fix_s)
        self.now = 41.5
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 3, 'speed': 0.0})
        self.assertEqual(self.gps.first_fix_s, 41.5)
        self.now = 500
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': 3, 'speed': 0.0})
        self.assertEqual(self.gps.first_fix_s, 41.5)                     # Only the first one counts.


class Receiver:
    """A GPS object whose state the test sets directly."""
    def __init__(self):
        self.state, self.first_fix_s, self.ublox, self.restarts = 'starting', None, True, []

    def diagnosis(self):
        return {'state': self.state, 'text': self.state, 'fix': 'move the receiver'}

    def restart_receiver(self, cold=False):
        if self.ublox:
            self.restarts.append('cold' if cold else 'warm')
        return self.ublox


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name)
        self.now = 0.0
        self.receiver = Receiver()
        self.watch = GpsRecovery(self.receiver, self.path, lambda: self.now)
        self.asked = []

    def tearDown(self):
        self.folder.cleanup()

    def run_for(self, seconds, helper=True):
        """A second at a time; a stand-in helper picks up each request as the real one would."""
        for _ in range(int(seconds)):
            self.now += 1
            self.watch.step()
            request = self.path / 'gps-request'
            if helper and request.exists():
                self.asked.append(request.read_text())
                request.unlink()
                (self.path / 'gps-status.json').write_text(json.dumps({'action': self.asked[-1], 'result': 'ok', 'message': f'did {self.asked[-1]}'}))

    def test_nothing_reporting_restart_then_find_then_usb_reset_then_round_again(self):
        self.run_for(30)
        self.assertEqual((self.asked, self.watch.snapshot()['kind']), ([], None))     # Starting up: nothing to fix yet.
        self.receiver.state = 'silent'
        self.run_for(14)
        self.assertEqual(self.asked, [])                                             # Given 15 s first.
        self.run_for(2)
        self.assertEqual(self.asked, ['restart'])
        shown = self.watch.snapshot()
        self.assertEqual((shown['kind'], shown['trying']), ('silent', {'text': 'Restarting the GPS service', 'step': 1, 'steps': 3}))
        self.run_for(26)
        self.assertEqual(self.asked, ['restart', 'repin'])
        self.run_for(26)
        self.assertEqual(self.asked, ['restart', 'repin', 'usb'])
        self.assertEqual((self.watch.snapshot()['helper'], self.watch.snapshot()['last']), ('ok', 'did usb'))
        self.run_for(40)
        shown = self.watch.snapshot()
        self.assertTrue(shown['exhausted'])
        self.assertIsNone(shown['trying'])
        self.assertGreater(shown['next_in_s'], 200)
        self.run_for(SILENT_RETRY_S)
        self.assertEqual(self.asked[3], 'restart')                                   # A receiver plugged in later is still found.

    def test_receiver_with_no_position_gets_a_warm_then_a_cold_restart_and_then_is_left_alone(self):
        self.receiver.state = 'weak'
        self.run_for(119)
        self.assertEqual(self.receiver.restarts, [])                                 # Two minutes to find satellites by itself.
        self.run_for(2)
        self.assertEqual(self.receiver.restarts, ['warm'])
        self.receiver.state = 'deaf'                                                 # Still the same kind of problem.
        self.run_for(181)
        self.assertEqual(self.receiver.restarts, ['warm', 'cold'])
        self.run_for(NO_FIX_RETRY_S - 10)
        self.assertEqual(self.receiver.restarts, ['warm', 'cold'])                   # Then left alone for a quarter of an hour.
        self.assertTrue(self.watch.snapshot()['exhausted'])
        self.run_for(20 + 185)
        self.assertEqual(self.receiver.restarts, ['warm', 'cold', 'warm', 'warm'])   # Its memory is cleared only once.
        self.assertEqual(self.watch.snapshot()['trying']['text'], 'Restarting the receiver satellite search')
        self.assertEqual(self.asked, [])                                             # A u-blox needs no root helper for this.
        self.receiver.state = 'fix'
        self.run_for(5)
        self.receiver.state = 'searching'                                            # Lost again later: a fresh start.
        self.run_for(120 + 181)
        self.assertEqual(self.receiver.restarts[-2:], ['warm', 'cold'])

    def test_a_service_that_is_not_answering_is_restarted_within_seconds(self):
        self.receiver.state = 'no-gpsd'
        self.run_for(4)
        self.assertEqual(self.asked, [])
        self.run_for(2)
        self.assertEqual(self.asked, ['restart'])

    def test_other_makes_get_a_usb_reset_instead(self):
        self.receiver.ublox = False
        self.receiver.state = 'searching'
        self.run_for(125)
        self.assertEqual((self.receiver.restarts, self.asked), ([], ['usb']))

    def test_a_position_stops_everything_and_a_new_loss_starts_from_the_first_step(self):
        self.receiver.state = 'silent'
        self.run_for(45)
        self.assertEqual(self.asked, ['restart', 'repin'])
        self.receiver.state = 'fix'
        self.receiver.first_fix_s = 52.0
        self.run_for(600)
        shown = self.watch.snapshot()
        self.assertEqual((self.asked, shown['kind'], shown['trying'], shown['tried'], shown['first_fix_s']), (['restart', 'repin'], None, None, 0, 52.0))
        self.receiver.state = 'silent'
        self.run_for(17)
        self.assertEqual(self.asked[-1], 'restart')

    def test_no_helper_installed_is_noticed_and_said(self):
        self.receiver.state = 'silent'
        self.run_for(30, helper=False)
        self.assertEqual(self.watch.snapshot()['helper'], 'missing')
        self.assertFalse((self.path / 'gps-request').exists())                       # A stale request is not left to fire later.

    def test_dash_reports_it_and_system_check_explains(self):
        state = State(clock=lambda: self.now)
        gps = GPS(clock=lambda: self.now, wall=lambda: 0)
        gps.gpsd_ok, gps.started = True, 0.0
        state.gps = gps
        state.gps_recovery = GpsRecovery(gps, self.path, lambda: self.now)
        self.now = 40
        state.gps_recovery.step()
        self.now = 56
        state.gps_recovery.step()
        shown = state.snapshot()['gps']
        self.assertEqual(shown['diagnosis']['state'], 'silent')
        self.assertEqual(shown['recovery']['trying']['text'], 'Restarting the GPS service')
        self.now = 70
        state.gps_recovery.step()
        lines = {l['name']: l for l in selftest.report(state)['lines']}
        self.assertEqual(lines['GPS recovery helper']['status'], 'warn')
        self.assertIn('frogdash-gps.path', lines['GPS recovery helper']['fix'])
        self.assertEqual(lines['Time to first position']['status'], 'skip')
        gps.first_fix_s = 95.0
        self.assertEqual({l['name']: l for l in selftest.report(state)['lines']}['Time to first position']['status'], 'warn')


@unittest.skipUnless(SHELL, 'needs sh')
class HelperScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        base = Path(self.folder.name)
        self.state, self.serial, self.sys, bin_dir = base / 'state', base / 'by-id', base / 'sys', base / 'bin'
        for folder in (self.state, self.serial, bin_dir, self.sys / 'class/tty', base / 'dev'):
            folder.mkdir(parents=True)
        self.config = base / 'gpsd'
        self.config.write_text('START_DAEMON="true"\nDEVICES="/dev/ttyUSB0"\nUSBAUTO="true"\nGPSD_OPTIONS=""\n')
        # sleep records the receiver's switch at each pause, so the test sees it go off and come back.
        sleep = 'cat "$FROGDASH_SYS"/class/tty/*u-blox*/authorized >> "$FROGDASH_STATE/sleep.log" 2>/dev/null\nexit 0\n'
        for name, body in {'systemctl': 'echo "$@" >> "$FROGDASH_STATE/systemctl.log"\nexit 0\n', 'sleep': sleep}.items():
            (bin_dir / name).write_text('#!/bin/sh\n' + body, newline='\n')
            (bin_dir / name).chmod(0o755)
        self.env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'], 'FROGDASH_STATE': self.state.as_posix(),
                    'FROGDASH_SERIAL_DIR': self.serial.as_posix(), 'FROGDASH_GPSD_DEFAULT': self.config.as_posix(), 'FROGDASH_SYS': self.sys.as_posix()}
        self.dev = base / 'dev'

    def tearDown(self):
        self.folder.cleanup()

    def plug(self, name, tty):
        (self.dev / tty).write_text('')
        (self.serial / name).write_text('')   # Stands in for the by-id link.

    def run_helper(self, *args, request=None):
        if request is not None:
            (self.state / 'gps-request').write_text(request)
        subprocess.run([SHELL, HELPER.as_posix(), *args], env=self.env, capture_output=True, text=True, timeout=60)
        return json.loads((self.state / 'gps-status.json').read_text())

    def calls(self):
        log = self.state / 'systemctl.log'
        return log.read_text() if log.exists() else ''

    def test_restart_comes_from_the_request_file_and_anything_else_is_refused(self):
        status = self.run_helper(request='restart')
        self.assertEqual((status['action'], status['result']), ('restart', 'ok'))
        self.assertIn('restart gpsd.socket gpsd.service', self.calls())
        self.assertFalse((self.state / 'gps-request').exists())
        before = self.calls()
        for bad in ('reboot', 'restart; rm -rf /', '', '../../etc/passwd', 'RESTART'):
            status = self.run_helper(request=bad)
            self.assertEqual((status['action'], status['result']), ('unknown', 'failed'), bad)
        self.assertEqual(self.calls(), before)        # Nothing was run for any of them.
        self.assertEqual(self.config.read_text().count('DEVICES="/dev/ttyUSB0"'), 1)

    def test_repin_points_gpsd_at_the_one_obvious_receiver_and_never_at_a_plain_serial_cable(self):
        self.plug(CABLE, 'ttyUSB0')
        status = self.run_helper('repin')
        self.assertEqual(status['result'], 'failed')
        self.assertIn('No GPS receiver recognised', status['message'])
        self.assertIn('FTDI', status['message'])       # Tells the owner what is plugged in.
        self.assertIn('DEVICES="/dev/ttyUSB0"', self.config.read_text())   # Untouched.
        self.plug(UBLOX, 'ttyACM0')
        status = self.run_helper('repin')
        self.assertEqual(status['result'], 'ok', status)
        text = self.config.read_text()
        self.assertIn(f'DEVICES="{(self.serial / UBLOX).as_posix()}"', text)
        self.assertIn('USBAUTO="false"', text)
        self.assertIn('GPSD_OPTIONS="-n"', text)
        self.assertIn('START_DAEMON="true"', text)     # Other lines are kept.
        self.assertEqual(text.count('DEVICES='), 1)
        self.assertIn('USBAUTO="true"', Path(str(self.config) + '.frogdash-bak').read_text())   # The original is kept once.
        self.assertIn('enable gpsd.service', self.calls())
        again = self.run_helper('repin')
        self.assertIn('already points at', again['message'])
        self.plug('usb-GlobalSat_BU-353-if00-port0', 'ttyUSB1')
        self.assertIn('More than one', self.run_helper('repin')['message'])

    def test_usb_reset_toggles_only_the_receivers_own_port(self):
        self.assertEqual(self.run_helper('usb')['result'], 'failed')      # Nothing plugged in: nothing touched.
        self.plug(CABLE, 'ttyUSB0')
        # The tuning cable's USB device, as /sys lays it out: device/ is the serial interface, its parent the USB device.
        cable = self.sys / 'class/tty' / CABLE
        (cable / 'device').mkdir(parents=True)
        (cable / 'idVendor').write_text('0403\n')
        (cable / 'authorized').write_text('1\n')
        self.assertIn('No GPS receiver recognised', self.run_helper('usb')['message'])
        self.assertFalse((self.state / 'sleep.log').exists())             # The cable was never switched off.
        self.plug(UBLOX, 'ttyACM0')
        receiver = self.sys / 'class/tty' / UBLOX
        (receiver / 'device').mkdir(parents=True)
        (receiver / 'idVendor').write_text('1546\n')
        (receiver / 'authorized').write_text('1\n')
        status = self.run_helper('usb')
        self.assertEqual(status['result'], 'ok', status)
        self.assertEqual((self.state / 'sleep.log').read_text().split(), ['0', '1'])   # Off, a pause, back on.
        self.assertEqual((receiver / 'authorized').read_text().strip(), '1')
        self.assertEqual((cable / 'authorized').read_text().strip(), '1')
        self.assertIn('restart gpsd.socket gpsd.service', self.calls())


if __name__ == '__main__':
    unittest.main()
