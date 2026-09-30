import unittest
from unittest.mock import patch, Mock

from tools.launch_kiosk import browser_args, http_probe, wait_ready, supervise


class KioskTests(unittest.TestCase):
    def test_delayed_server_launches_without_fixed_boot_delay(self):
        now, attempts = [0.], [0]
        def probe():
            attempts[0] += 1
            return attempts[0] == 3
        wait_ready(probe, clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0] + n))
        self.assertAlmostEqual(now[0], .2)
        # Already-ready service introduces no sleep.
        wait_ready(lambda: True, sleep=lambda _: self.fail('Unnecessary startup delay'))

    def test_unavailable_service_times_out_for_supervisor_retry(self):
        now = [0.]
        with self.assertRaises(TimeoutError):
            wait_ready(lambda: False, timeout=.3, clock=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0] + n))
        self.assertAlmostEqual(now[0], .3)

    def test_chromium_keeps_sandbox_and_profile_arguments_intact(self):
        args = browser_args('/usr/bin/chromium', wayland=True, profile='/home/dash user/profile')
        self.assertIn('--user-data-dir=/home/dash user/profile', args)
        self.assertIn('--ozone-platform=wayland', args)
        self.assertIn('--password-store=basic', args)
        self.assertFalse(any(arg.startswith('--password-store') for arg in browser_args('chromium')))
        self.assertNotIn('--no-sandbox', args)
        for flag in ('--disable-background-networking', '--disable-component-update', '--disable-sync'):
            self.assertIn(flag, args)
        self.assertNotIn('--incognito', args)
        self.assertEqual(args[-1], 'http://127.0.0.1:8080/')
        self.assertFalse(any(arg.startswith('--user-data-dir') for arg in browser_args('chromium')))
        self.assertNotIn('--autoplay-policy=no-user-gesture-required', args)
        self.assertIn('--autoplay-policy=no-user-gesture-required', browser_args('chromium', allow_audio=True))

    def test_health_probe_ignores_proxy_and_retries_connection_errors(self):
        with patch('tools.launch_kiosk.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = ConnectionRefusedError()
            probe = http_probe(8080)
            self.assertFalse(probe())
            handler = opener.call_args.args[0]
            self.assertEqual(handler.proxies, {})
            opener.return_value.open.side_effect = None
            opener.return_value.open.return_value.__enter__.return_value.status = 200
            self.assertTrue(probe())
            opener.return_value.open.assert_called_with('http://127.0.0.1:8080/health', timeout=.5)

    def test_first_render_is_logged_once_only_after_browser_heartbeat(self):
        process = Mock()
        process.poll.side_effect = [None, None, None, 0, 0]
        process.returncode = 0
        with patch('tools.launch_kiosk.subprocess.Popen', return_value=process), \
             patch('tools.launch_kiosk.signal.signal'), \
             patch('tools.launch_kiosk.http_probe', return_value=lambda: True), \
             patch('tools.launch_kiosk.heartbeat_probe', return_value=Mock(side_effect=[False, True, True])), \
             patch('tools.launch_kiosk.time.monotonic', return_value=10), \
             patch('tools.launch_kiosk.time.sleep'), \
             patch('tools.launch_kiosk.boot_stamp', return_value='boot+12.00s'), \
             patch('builtins.print') as log:
            self.assertEqual(supervise(['chromium'], 8080, 'a' * 32), 0)
        messages = [call.args[0] for call in log.call_args_list]
        self.assertEqual(len(messages), 1)
        self.assertIn('first render heartbeat observed (boot+12.00s;', messages[0])

    def test_no_render_success_is_reported_when_browser_never_renders(self):
        process = Mock()
        process.poll.side_effect = [None, 0, 0]
        process.returncode = 0
        with patch('tools.launch_kiosk.subprocess.Popen', return_value=process), \
             patch('tools.launch_kiosk.signal.signal'), \
             patch('tools.launch_kiosk.http_probe', return_value=lambda: True), \
             patch('tools.launch_kiosk.heartbeat_probe', return_value=lambda: False), \
             patch('tools.launch_kiosk.time.monotonic', return_value=10), \
             patch('tools.launch_kiosk.time.sleep'), \
             patch('builtins.print') as log:
            self.assertEqual(supervise(['chromium'], 8080, 'a' * 32), 0)
        log.assert_not_called()


if __name__ == '__main__':
    unittest.main()
