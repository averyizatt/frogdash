import unittest
from unittest.mock import patch

from tools.launch_kiosk import browser_args, http_probe, wait_ready


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
        self.assertNotIn('--no-sandbox', args)
        self.assertNotIn('--incognito', args)
        self.assertEqual(args[-1], 'http://127.0.0.1:8080/')
        self.assertFalse(any(arg.startswith('--user-data-dir') for arg in browser_args('chromium')))

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


if __name__ == '__main__':
    unittest.main()
