"""The dash notices that its version's Pi setup has not run and asks the updater for it."""
import json
from pathlib import Path
import tempfile
import unittest

from hardware.frogdash import selftest
from hardware.frogdash.helpers import Helpers, TRIES, stamp
from hardware.frogdash.state import State


class SetupRequestTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        base = Path(self.folder.name)
        self.data, self.script, self.updater = base / 'data', base / 'frogdash_setup.sh', base / 'frogdash-update.path'
        self.data.mkdir()
        self.script.write_bytes(b'#!/bin/sh\n# version one of the setup\n')
        self.updater.write_text('installed')
        self.now = 1000.0
        self.helpers = Helpers(self.data, self.script, self.updater, wall=lambda: self.now)
        self.request = self.data / 'update-request'

    def tearDown(self):
        self.folder.cleanup()

    def ran(self, running=False, steps=(), script=None, at=None):
        (self.data / 'setup-status.json').write_text(json.dumps({
            'stamp': stamp(script or self.script), 'running': running, 'time': self.now if at is None else at, 'steps': list(steps)}))

    def test_a_setup_that_has_not_run_is_asked_for_and_the_request_is_only_the_word(self):
        self.assertTrue(self.helpers.step())
        self.assertEqual(self.request.read_text(), 'setup')
        self.assertEqual(self.helpers.state, 'installing')
        self.request.unlink()                              # The updater collected it and ran the script.
        self.ran(steps=[{'name': 'Dash helpers', 'result': 'done', 'detail': 'Installed: gps'}])
        self.assertFalse(self.helpers.step())
        self.assertEqual(self.helpers.snapshot(), {'state': 'ok', 'steps': [{'name': 'Dash helpers', 'result': 'done', 'detail': 'Installed: gps'}]})
        self.assertFalse(self.request.exists())

    def test_an_update_that_changes_the_setup_is_noticed_and_one_that_does_not_is_left_alone(self):
        self.ran()
        self.assertFalse(Helpers(self.data, self.script, self.updater).step())
        self.assertFalse(self.request.exists())
        self.script.write_bytes(b'#!/bin/sh\n# version two: a new step\n')
        again = Helpers(self.data, self.script, self.updater)
        self.assertTrue(again.step())
        self.assertEqual(self.request.read_text(), 'setup')

    def test_a_long_install_is_waited_for_and_a_dead_one_is_asked_for_again(self):
        self.ran(running=True)
        for _ in range(TRIES * 3):                         # Java can take many minutes.
            self.assertTrue(self.helpers.step())
        self.assertEqual((self.helpers.state, self.request.exists()), ('installing', False))
        self.now += 2 * 3600                               # Still "running" two hours on: it was killed.
        self.assertTrue(self.helpers.step())
        self.assertEqual(self.request.read_text(), 'setup')

    def test_an_update_the_driver_asked_for_is_never_replaced(self):
        self.request.write_text('requested')
        for _ in range(TRIES + 1):
            self.helpers.step()
        self.assertEqual(self.helpers.state, 'failed')
        self.assertEqual(self.request.read_text(), 'requested')

    def test_it_gives_up_and_leaves_no_request_behind(self):
        for _ in range(TRIES):
            self.assertTrue(self.helpers.step())
        self.assertFalse(self.helpers.step())
        self.assertEqual(self.helpers.state, 'failed')
        self.assertFalse(self.request.exists())            # Would otherwise keep the Update button waiting.

    def test_system_check_lists_every_step_and_says_when_the_update_helper_is_missing(self):
        state = State()
        state.helpers = self.helpers
        self.updater.unlink()
        self.assertFalse(self.helpers.step())
        self.assertFalse(self.request.exists())
        lines = {l['name']: l for l in selftest.report(state)['lines']}
        self.assertEqual(lines['Pi setup']['status'], 'fail')
        self.assertIn('frogdash-update.path', lines['Pi setup']['fix'])
        self.updater.write_text('installed')
        self.ran(steps=[{'name': 'Dash helpers', 'result': 'ok', 'detail': 'All installed'},
                        {'name': 'TunerStudio: Java and display', 'result': 'waiting', 'detail': 'Missing default-jre: needs the internet'},
                        {'name': 'TunerStudio: program', 'result': 'failed', 'detail': 'Download failed'},
                        {'name': 'Clock from GPS', 'result': 'skipped', 'detail': 'Not a Debian system'}])
        self.helpers.step()
        lines = {l['name']: l for l in selftest.report(state)['lines']}
        self.assertEqual([lines[name]['status'] for name in ('Pi setup', 'Dash helpers', 'TunerStudio: Java and display', 'TunerStudio: program', 'Clock from GPS')],
                         ['ok', 'ok', 'warn', 'fail', 'skip'])
        self.assertIn('Update now', lines['TunerStudio: Java and display']['fix'])


if __name__ == '__main__':
    unittest.main()
