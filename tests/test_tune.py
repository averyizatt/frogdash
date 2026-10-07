"""TunerStudio over the dash: the dash-side mailbox and the kiosk launcher's side."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from tools.launch_kiosk import Tuner, find_tunerstudio, supervise

READY = {'installed': True, 'state': 'idle', 'message': 'Ready'}


class MailboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_request_reaches_the_kiosk_once_and_status_follows_its_reports(self):
        now = [100.0]
        state = State(clock=lambda: now[0])
        async with TestClient(TestServer(create_app(state))) as client:
            status = await (await client.get('/tune')).json()
            self.assertEqual((status['available'], status['state']), (False, 'unavailable'))
            refused = await client.post('/tune', json={'action': 'open'})
            self.assertEqual(refused.status, 409)  # No kiosk: nothing could start it.
            # Kiosk without TunerStudio installed.
            self.assertIsNone((await (await client.post('/tune/kiosk', json={**READY, 'installed': False})).json())['action'])
            self.assertEqual((await (await client.get('/tune')).json())['state'], 'missing')
            self.assertEqual((await client.post('/tune', json={'action': 'open'})).status, 409)
            # Installed: the request is handed over exactly once.
            await client.post('/tune/kiosk', json=READY)
            status = await (await client.post('/tune', json={'action': 'open'})).json()
            self.assertEqual((status['available'], status['state']), (True, 'starting'))
            self.assertEqual((await (await client.post('/tune/kiosk', json=READY)).json())['action'], 'open')
            self.assertIsNone((await (await client.post('/tune/kiosk', json={**READY, 'state': 'running', 'message': 'Open'})).json())['action'])
            self.assertEqual(state.snapshot()['tune']['state'], 'running')
            await client.post('/tune', json={'action': 'close'})
            self.assertEqual((await (await client.post('/tune/kiosk', json={**READY, 'state': 'running'})).json())['action'], 'close')
            # A silent kiosk is no longer offered.
            now[0] += 9
            self.assertFalse((await (await client.get('/tune')).json())['available'])
            for bad in ({'action': 'reboot'}, {}):
                self.assertEqual((await client.post('/tune', json=bad)).status, 409)
            for bad in ({'installed': True, 'state': 'rooted', 'message': ''}, {'installed': 1, 'state': 'idle'}, {'installed': True, 'state': 'idle', 'message': 'x' * 301}):
                self.assertEqual((await client.post('/tune/kiosk', json=bad)).status, 400)

    def test_opens_while_the_car_is_moving(self):
        # The owner removed the stopped-only check: road tuning with TunerStudio open.
        state = State(clock=lambda: 10)
        state.connected = True
        state.samples['vehicle.speed_kph', 0x203] = dict(value=90, quality='live', seen=10, source_id=0x203, timestamp_ms=0)
        state.tune.report(READY)
        self.assertEqual(state.tune.request('open')['state'], 'starting')
        self.assertEqual(state.tune.report(READY), 'open')
        self.assertNotIn('moving', state.snapshot()['tune'])

    def test_holding_off_on_the_wheel_closes_tunerstudio(self):
        state = State(clock=lambda: 10)
        running = {**READY, 'state': 'running'}
        state.wheel.emit('home')  # Before TunerStudio was open: must not close it later.
        self.assertIsNone(state.tune.report(READY))
        self.assertIsNone(state.tune.report(running))
        state.wheel.emit('down')
        self.assertIsNone(state.tune.report(running))
        state.wheel.emit('home')
        self.assertEqual(state.tune.report(running), 'close')
        self.assertIsNone(state.tune.report(running))  # Once per hold.


class Process:
    def __init__(self, pid=4242):
        self.pid, self.returncode = pid, None

    def poll(self):
        return self.returncode


class KioskTunerTests(unittest.TestCase):
    def make(self, actions, env=None, script=Path('/home/pi/TunerStudioMS/TunerStudio.sh')):
        self.now, self.reports, self.alive = [0.0], [], [True]
        self.process = Process()
        self.popen = Mock(return_value=self.process)
        queue = list(actions)
        def post(report):
            self.reports.append(report)
            return queue.pop(0) if queue else None
        def stop(process):
            process.returncode, self.alive[0] = -15, False
        return Tuner(8080, find=lambda: script, popen=self.popen, alive=lambda pid: self.alive[0], stop=stop,
                     clock=lambda: self.now[0], env={'DISPLAY': ':0', 'HOME': '/home/pi'} if env is None else env, post=post)

    def test_opens_reports_and_closes_on_request(self):
        tuner = self.make([None, 'open', None, 'close'])
        tuner.step()
        self.assertEqual((self.reports[-1]['installed'], self.reports[-1]['state']), (True, 'idle'))
        self.popen.assert_not_called()
        tuner.step()
        command, options = self.popen.call_args.args[0], self.popen.call_args.kwargs
        self.assertEqual(command, ['/bin/bash', str(Path('/home/pi/TunerStudioMS/TunerStudio.sh'))])
        self.assertEqual(options['cwd'], str(Path('/home/pi/TunerStudioMS')))
        self.assertTrue(options['start_new_session'])
        self.assertEqual((options['env']['DISPLAY'], options['env']['_JAVA_AWT_WM_NONREPARENTING']), (':0', '1'))
        self.assertTrue(tuner.running())
        tuner.step()
        self.assertEqual(self.reports[-1]['state'], 'running')
        tuner.step()  # 'close'
        self.assertFalse(tuner.running())
        tuner.step()
        self.assertEqual((self.reports[-1]['state'], self.reports[-1]['message']), ('idle', 'TunerStudio closed'))

    def test_start_script_that_hands_over_to_java_still_counts_as_running(self):
        tuner = self.make(['open'])
        tuner.step()
        self.process.returncode = 0  # The script exited; Java lives on in its session.
        self.assertTrue(tuner.running())
        self.alive[0] = False
        self.now[0] = 300
        tuner.step()
        self.assertEqual(self.reports[-1]['state'], 'idle')

    def test_quick_failure_explains_itself_and_a_clean_quick_exit_does_not(self):
        tuner = self.make(['open'])
        tuner.step()
        self.process.returncode, self.alive[0], self.now[0] = 127, False, 3
        tuner.step()
        self.assertEqual(self.reports[-1]['state'], 'failed')
        self.assertIn('default-jre', self.reports[-1]['message'])
        self.assertLessEqual(len(self.reports[-1]['message']), 300)
        tuner = self.make(['open'])
        tuner.step()
        self.process.returncode, self.alive[0], self.now[0] = 0, False, 3
        tuner.step()
        self.assertEqual(self.reports[-1]['state'], 'idle')

    def test_missing_x_display_or_missing_install_never_starts_anything(self):
        tuner = self.make(['open', None], env={'WAYLAND_DISPLAY': 'wayland-0'})
        tuner.step(); tuner.step()
        self.popen.assert_not_called()
        self.assertEqual(self.reports[-1]['state'], 'failed')
        self.assertIn('xwayland', self.reports[-1]['message'])
        tuner = self.make(['open', None], script=None)
        tuner.step(); tuner.step()
        self.popen.assert_not_called()
        self.assertFalse(self.reports[-1]['installed'])

    def test_dash_restart_leaves_an_open_tunerstudio_alone(self):
        tuner = self.make(['open'])
        tuner.step()
        tuner.post = Mock(side_effect=OSError('connection refused'))
        tuner.step()
        self.assertTrue(tuner.running())

    def test_finds_the_usual_install_folders_and_an_override(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            self.assertIsNone(find_tunerstudio({}, home) if not Path('/opt/TunerStudioMS/TunerStudio.sh').exists() else None)
            (home / 'TunerStudioMS').mkdir()
            (home / 'TunerStudioMS/TunerStudio.sh').write_text('#!/bin/bash\n')
            self.assertEqual(find_tunerstudio({}, home), home / 'TunerStudioMS/TunerStudio.sh')
            (home / 'elsewhere').mkdir()
            (home / 'elsewhere/TunerStudio.sh').write_text('#!/bin/bash\n')
            self.assertEqual(find_tunerstudio({'FROGDASH_TUNERSTUDIO': str(home / 'elsewhere')}, home), home / 'elsewhere/TunerStudio.sh')
            self.assertEqual(find_tunerstudio({'FROGDASH_TUNERSTUDIO': str(home / 'elsewhere/TunerStudio.sh')}, home), home / 'elsewhere/TunerStudio.sh')
            self.assertIsNone(find_tunerstudio({'FROGDASH_TUNERSTUDIO': str(home / 'nowhere')}, home))


class CoveredDashTests(unittest.TestCase):
    def run_supervise(self, tuner, polls, rendered, clock):
        browser = Mock()
        browser.poll.side_effect = polls
        browser.returncode = 0
        with ExitStack() as stack:
            for target, options in [('subprocess.Popen', {'return_value': browser}), ('signal.signal', {}),
                                    ('http_probe', {'return_value': lambda: True}),
                                    ('heartbeat_probe', {'return_value': lambda: rendered}),
                                    ('time.monotonic', clock), ('time.sleep', {}), ('boot_stamp', {'return_value': 'boot'}),
                                    ('os.killpg', {'create': True})]:  # killpg is absent on Windows test machines.
                stack.enter_context(patch('tools.launch_kiosk.' + target, **options))
            stack.enter_context(patch('builtins.print'))
            return supervise(['chromium'], 8080, 'a' * 32, tuner)

    def covered(self, tuner_running):
        tuner = Mock()
        tuner.running.return_value = tuner_running
        ticks = iter(range(0, 4000, 5))  # Time passes; the covered dash never draws.
        return self.run_supervise(tuner, [None] * 40 + [0, 0], False, {'side_effect': lambda: next(ticks)}), tuner

    def test_watchdog_does_not_restart_the_browser_while_tunerstudio_covers_it(self):
        code, tuner = self.covered(True)
        self.assertEqual(code, 0)
        self.assertGreater(tuner.step.call_count, 30)
        tuner.close.assert_called_once()  # TunerStudio never outlives the kiosk session.

    def test_watchdog_still_restarts_a_frozen_browser_when_tunerstudio_is_closed(self):
        self.assertEqual(self.covered(False)[0], 1)

    def test_a_tuner_error_never_takes_the_screen_down(self):
        tuner = Mock()
        tuner.step.side_effect = RuntimeError('boom')
        tuner.running.return_value = False
        self.assertEqual(self.run_supervise(tuner, [None, None, 0, 0], True, {'return_value': 10}), 0)
        self.assertEqual(tuner.step.call_count, 2)


if __name__ == '__main__':
    unittest.main()
