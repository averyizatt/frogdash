import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from hardware.power.monitor import LossTimer, Monitor, PiSugar, ProtocolError, request_poweroff, write_status


class PowerTimerTests(unittest.TestCase):
    def advance(self, timer, start, end, present=False):
        for step in range(int((end - start) * 2) + 1):
            result = timer.update(present, start + step / 2)
        return result

    def test_cranking_does_not_accumulate_between_dips(self):
        timer = LossTimer()
        self.assertEqual(self.advance(timer, 0, 6)['state'], 'on_battery')
        self.assertEqual(timer.update(True, 6.5)['state'], 'external_power')
        self.assertEqual(self.advance(timer, 7, 14.5)['remaining_seconds'], .5)
        self.assertEqual(timer.update(False, 15)['state'], 'shutdown_due')

    def test_restoration_at_deadline_cancels_and_boot_on_battery_counts(self):
        timer = LossTimer()
        self.advance(timer, 0, 7.5)
        self.assertEqual(timer.update(True, 8)['state'], 'external_power')
        self.assertEqual(timer.update(False, 8.5)['remaining_seconds'], 8)
        self.assertEqual(self.advance(LossTimer(5), 0, 5)['state'], 'shutdown_due')
        self.assertEqual(self.advance(LossTimer(10), 0, 9.5)['state'], 'on_battery')

    def test_unknown_and_sampling_stall_require_new_continuous_interval(self):
        timer = LossTimer()
        self.advance(timer, 0, 7)
        self.assertEqual(timer.update(None, 7.5)['state'], 'unavailable')
        self.assertEqual(timer.update(False, 8)['remaining_seconds'], 8)
        self.assertEqual(timer.update(False, 80)['remaining_seconds'], 8)
        self.assertEqual(timer.update(False, 1)['remaining_seconds'], 8)

    def test_config_rejects_bad_delays(self):
        for delay in (0, -1, 4.9, 10.1, float('nan'), float('inf')):
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                LossTimer(delay)

    def test_dry_run_never_shuts_down_and_restoration_still_cancels(self):
        client, shutdown = Mock(), Mock()
        client.input_present.return_value = False
        monitor = Monitor(client, shutdown=shutdown)
        with patch('hardware.power.monitor.time.monotonic') as clock:
            for moment in range(11):
                clock.return_value = moment
                status = monitor.tick()
            self.assertEqual(status['state'], 'would_shutdown')
            shutdown.assert_not_called()
            client.input_present.return_value = True
            self.assertEqual(monitor.tick()['state'], 'external_power')

    def test_shutdown_commits_once_even_if_input_returns(self):
        client, shutdown = Mock(), Mock()
        client.input_present.return_value = False
        monitor = Monitor(client, execute=True, shutdown=shutdown)
        with patch('hardware.power.monitor.time.monotonic') as clock:
            for moment in range(9):
                clock.return_value = moment
                status = monitor.tick()
            self.assertEqual(status['state'], 'shutdown_requested')
            client.input_present.return_value = True
            self.assertEqual(monitor.tick()['state'], 'shutdown_requested')
            shutdown.assert_called_once_with()

    def test_failed_shutdown_retries_and_read_error_is_not_absence(self):
        client, shutdown = Mock(), Mock(side_effect=[OSError('dbus unavailable'), None])
        client.input_present.return_value = False
        monitor = Monitor(client, execute=True, shutdown=shutdown)
        with patch('hardware.power.monitor.time.monotonic') as clock:
            for moment in range(9):
                clock.return_value = moment
                status = monitor.tick()
            self.assertEqual(status['state'], 'shutdown_failed')
            clock.return_value = 9
            monitor.tick()
            self.assertEqual(shutdown.call_count, 1)
            clock.return_value = 10
            self.assertEqual(monitor.tick()['state'], 'shutdown_requested')
            self.assertEqual(shutdown.call_count, 2)
        monitor = Monitor(client, execute=True, shutdown=shutdown)
        client.input_present.side_effect = OSError('I2C unavailable')
        self.assertEqual(monitor.tick()['state'], 'unavailable')
        self.assertIsNone(monitor.timer.since)

    def test_normal_systemd_request_and_atomic_runtime_status(self):
        with patch('hardware.power.monitor.subprocess.run') as run:
            request_poweroff()
            self.assertEqual(run.call_args.args[0], ['/usr/bin/systemctl', '--no-block', 'poweroff'])
            self.assertTrue(run.call_args.kwargs['check'])
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'status.json'
            write_status(path, {'state': 'on_battery', 'remaining_seconds': 3})
            write_status(path, {'state': 'external_power', 'remaining_seconds': None})
            self.assertEqual(json.loads(path.read_text())['state'], 'external_power')
            self.assertFalse(path.with_suffix('.tmp').exists())


class PiSugarProtocolTests(unittest.TestCase):
    def transact(self, chunks, command='get battery_power_plugged'):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.recv.side_effect = chunks
        with patch('hardware.power.monitor.socket.socket', return_value=connection), \
             patch.object(socket, 'AF_UNIX', 1, create=True):
            result = PiSugar().request(command)
        connection.sendall.assert_called_once_with((command + '\n').encode())
        return result

    def test_fragmented_response_and_unsolicited_button(self):
        self.assertEqual(self.transact([b'single\n', b'battery_power_', b'plugged: false\r\n']), 'false')

    def test_malformed_eof_timeout_and_excess_output_are_not_false(self):
        for chunks in ([b''], [b'error: no I2C\n'], [TimeoutError('timed out')],
                       [b'x' * 1024] * 8):
            with self.subTest(chunks=str(chunks)[:60]), self.assertRaises((OSError, ProtocolError)):
                self.transact(chunks)
        client = PiSugar()
        client.request = Mock(return_value='I2C read failed')
        with self.assertRaises(ProtocolError):
            client.boolean('battery_power_plugged')
        client.request.return_value = 'PiSugar 2'
        with self.assertRaises(ProtocolError):
            client.input_present()

    def test_presence_does_not_query_charging_and_configuration_is_explicit(self):
        client = PiSugar()
        client.request = Mock(side_effect=['PiSugar 3', 'true'])
        self.assertTrue(client.input_present())
        self.assertEqual([call.args[0] for call in client.request.call_args_list],
                         ['get model', 'get battery_power_plugged'])
        client.request = Mock(side_effect=['PiSugar 3', 'false'])
        with self.assertRaises(ProtocolError):
            client.configure()
        self.assertTrue(all(call.args[0].startswith('get ') for call in client.request.call_args_list))

    def test_configuration_supports_old_vendor_command_names(self):
        client = PiSugar()
        calls = []
        def request(command):
            calls.append(command)
            if command == 'get model': return 'PiSugar 3'
            if command == 'get battery_power_plugged': return 'true'
            if command == 'get soft_poweroff_shell': return '/usr/bin/systemctl poweroff'
            if command.startswith('set_safe_'): raise ProtocolError('old server command')
            return 'done'
        client.request = request
        client.check = Mock(return_value={'auto_power_on': True, 'low_battery_percent': 10, 'low_battery_delay_seconds': 5})
        self.assertTrue(client.configure()['auto_power_on'])
        self.assertIn('safe_shutdown_level 10', calls)
        self.assertIn('safe_shutdown_delay 5', calls)
        self.assertNotIn('force_shutdown', calls)

    def test_check_rejects_disabled_restore_and_missing_battery_protection(self):
        client = PiSugar()
        readings = {'model': 'PiSugar 3', 'firmware_version': '1.4.0',
                    'battery_power_plugged': 'true', 'auto_power_on': 'true',
                    'soft_poweroff': 'true', 'safe_shutdown_level': '10',
                    'safe_shutdown_delay': '5'}
        client.request = lambda command: readings[command.removeprefix('get ')]
        self.assertEqual(client.check()['low_battery_percent'], 10)
        for field, value in (('auto_power_on', 'false'), ('soft_poweroff', 'false'),
                             ('safe_shutdown_level', '0'), ('safe_shutdown_delay', 'nan')):
            previous = readings[field]
            readings[field] = value
            with self.subTest(field=field), self.assertRaises(ProtocolError):
                client.check()
            readings[field] = previous

    @unittest.skipUnless(os.name == 'posix', 'Linux Unix socket transport')
    def test_real_unix_socket_transport(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / 'ups.sock')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(path)
                server.listen(1)
                def reply():
                    with server.accept()[0] as connection:
                        connection.recv(1024)
                        connection.sendall(b'battery_power_plugged: true\n')
                worker = threading.Thread(target=reply, daemon=True)
                worker.start()
                self.assertTrue(PiSugar(path).boolean('battery_power_plugged'))
                worker.join(2)
                self.assertFalse(worker.is_alive())


class LateCutoffTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'Linux shutdown shell hook')
    def test_cutoff_only_on_poweroff_or_halt(self):
        source = Path('hardware/power/frogdash-pisugar-poweroff').read_text()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            marker = root / 'called'
            binary = root / 'fake-poweroff'
            binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "' + str(marker) + '"\n')
            binary.chmod(0o755)
            hook = root / 'hook'
            hook.write_text(source.replace('/usr/bin/pisugar-poweroff', str(binary)))
            for action in ('reboot', 'kexec', 'unknown'):
                subprocess.run(['/bin/sh', str(hook), action], check=True)
                self.assertFalse(marker.exists())
            for action in ('poweroff', 'halt'):
                subprocess.run(['/bin/sh', str(hook), action], check=True)
                self.assertIn('PiSugar 3', marker.read_text())
                marker.unlink()
            binary.unlink()
            self.assertNotEqual(subprocess.run(['/bin/sh', str(hook), 'poweroff'], capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
