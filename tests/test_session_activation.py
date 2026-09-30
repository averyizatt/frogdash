import subprocess
import unittest
from unittest.mock import Mock, mock_open, patch
from tools.activate_kiosk import confirm_active, registered_session, wait_for_session


class SessionActivationTests(unittest.TestCase):
    def test_activation_waits_for_registration_not_a_fixed_sleep(self):
        now = [0.]
        probe = Mock(side_effect=[None, None, 'c4'])
        select = Mock()
        session = wait_for_session(probe, select, clock=lambda: now[0],
                                   sleep=lambda n: now.__setitem__(0, now[0] + n))
        self.assertEqual(session, 'c4')
        self.assertAlmostEqual(now[0], .2)
        select.assert_called_once_with('c4')
        wait_for_session(lambda: 'c5', select, sleep=lambda _: self.fail('Unnecessary wait'))

    def test_missing_session_times_out_without_switching_some_other_session(self):
        now = [0.]
        select = Mock()
        with self.assertRaises(TimeoutError):
            wait_for_session(lambda: None, select, timeout=.3, clock=lambda: now[0],
                             sleep=lambda n: now.__setitem__(0, now[0] + n))
        select.assert_not_called()

    def test_session_must_match_process_user_terminal_and_pam_service(self):
        fields = dict(Name='foxbody', TTY='tty7', Service='frogdash-kiosk', Leader='123', State='online')
        def probe(data):
            def loginctl(args, **kwargs):
                # loginctl v252 treats each -p argument as ONE property name;
                # unlike systemctl it does not split comma-separated names.
                requested = [arg.split('=', 1)[1] for arg in args if arg.startswith('--property=')]
                return Mock(stdout='\n'.join(f'{key}={data[key]}' for key in requested if key in data))
            with patch('pathlib.Path.open', mock_open(read_data=b'XDG_SESSION_ID=c4\0')), \
                 patch('tools.activate_kiosk.subprocess.run', side_effect=loginctl):
                return registered_session(123, 'foxbody', 'tty7')
        self.assertEqual(probe(fields), 'c4')
        for key, value in [('Name','other'), ('TTY','tty1'), ('Service','sshd'), ('Leader','456'), ('State','closing')]:
            self.assertIsNone(probe({**fields, key:value}))

    def test_process_not_yet_executed_and_disappearing_process_are_retryable(self):
        for data in (b'HOME=/root\0', b'XDG_SESSION_ID=--help\0', b'XDG_SESSION_ID=c4\0' + b'x' * 65536):
            with patch('pathlib.Path.open', mock_open(read_data=data)), \
                 patch('tools.activate_kiosk.subprocess.run') as run:
                self.assertIsNone(registered_session(123, 'foxbody', 'tty7'))
                run.assert_not_called()
        with patch('pathlib.Path.open', side_effect=FileNotFoundError()):
            self.assertIsNone(registered_session(123, 'foxbody', 'tty7'))

    def test_activation_failure_is_reported_not_retried_as_success(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            wait_for_session(lambda: 'c4', Mock(side_effect=subprocess.TimeoutExpired('loginctl',2)))



class ConfirmActiveTests(unittest.TestCase):
    def fake_clock(self):
        now = [0.0]
        return (lambda: now[0]), (lambda seconds: now.__setitem__(0, now[0] + seconds))

    def test_already_active_returns_immediately_without_reactivating(self):
        clock, sleep = self.fake_clock()
        calls = []
        self.assertEqual(confirm_active('c1', lambda s: True, calls.append, clock=clock, sleep=sleep), 0)
        self.assertEqual(calls, [])

    def test_lost_activation_is_requested_again_each_second(self):
        clock, sleep = self.fake_clock()
        calls = []
        took = confirm_active('c1', lambda s: len(calls) >= 2, calls.append, clock=clock, sleep=sleep)
        self.assertEqual(calls, ['c1', 'c1'])
        self.assertLess(took, 2.2)

    def test_never_active_gives_up_before_cage_timeout(self):
        clock, sleep = self.fake_clock()
        calls = []
        self.assertIsNone(confirm_active('c1', lambda s: False, calls.append, clock=clock, sleep=sleep))
        self.assertLess(clock(), 10)
        self.assertGreaterEqual(len(calls), 7)


if __name__ == '__main__':
    unittest.main()
