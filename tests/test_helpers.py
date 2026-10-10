"""The dash notices a root helper that is not installed and asks the updater to add it."""
from pathlib import Path
import tempfile
import unittest

from hardware.frogdash import selftest
from hardware.frogdash.helpers import Helpers, TRIES, missing, shipped
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]


class HelperInstallTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        base = Path(self.folder.name)
        self.repo, self.system, self.data = base / 'repo', base / 'system', base / 'data'
        for folder in (self.repo, self.system / 'multi-user.target.wants', self.data):
            folder.mkdir(parents=True)
        for name in ('frogdash-update', 'frogdash-wifi', 'frogdash-gps'):
            (self.repo / f'{name}.path').write_text('path')
            (self.repo / f'{name}.service').write_text('service')
        (self.repo / 'frogdash.service').write_text('the dash itself: not a helper')
        (self.repo / 'frogdash-kiosk.service').write_text('no path unit: not a helper')
        self.helpers = Helpers(self.data, self.repo, self.system)
        self.request = self.data / 'update-request'

    def tearDown(self):
        self.folder.cleanup()

    def install(self, name, enabled=True):
        (self.system / f'{name}.path').write_text('path')
        (self.system / f'{name}.service').write_text('service')
        if enabled:
            (self.system / 'multi-user.target.wants' / f'{name}.path').write_text('')

    def test_this_version_ships_the_three_helpers_as_pairs(self):
        self.assertEqual(shipped(ROOT / 'hardware/systemd'), ['frogdash-gps', 'frogdash-update', 'frogdash-wifi'])

    def test_a_missing_helper_is_asked_for_and_the_request_is_only_the_word(self):
        self.install('frogdash-update')
        self.install('frogdash-wifi', enabled=False)       # Copied but never enabled counts as missing.
        self.assertEqual(missing(self.repo, self.system), ['frogdash-gps', 'frogdash-wifi'])
        self.assertTrue(self.helpers.step())
        self.assertEqual(self.request.read_text(), 'helpers')
        self.assertEqual(self.helpers.snapshot(), {'state': 'installing', 'missing': ['gps', 'wifi']})
        self.request.unlink()                              # The updater collected it and did the work.
        self.install('frogdash-gps')
        self.install('frogdash-wifi')
        self.assertFalse(self.helpers.step())
        self.assertEqual(self.helpers.snapshot(), {'state': 'ok', 'missing': []})
        self.assertFalse(self.request.exists())

    def test_an_update_the_driver_asked_for_is_never_replaced(self):
        self.install('frogdash-update')
        self.request.write_text('requested')
        self.assertTrue(self.helpers.step())
        self.assertEqual(self.request.read_text(), 'requested')
        for _ in range(TRIES):
            self.helpers.step()
        self.assertEqual(self.helpers.state, 'failed')
        self.assertEqual(self.request.read_text(), 'requested')

    def test_it_gives_up_and_leaves_no_request_behind(self):
        self.install('frogdash-update')
        for _ in range(TRIES):
            self.assertTrue(self.helpers.step())
        self.assertFalse(self.helpers.step())
        self.assertEqual(self.helpers.state, 'failed')
        self.assertFalse(self.request.exists())            # Would otherwise keep the Update button waiting.

    def test_without_the_update_helper_nothing_is_requested_and_system_check_says_what_to_do(self):
        self.assertFalse(self.helpers.step())
        self.assertEqual(self.helpers.state, 'no-updater')
        self.assertFalse(self.request.exists())
        state = State()
        state.helpers = self.helpers
        line = next(l for l in selftest.report(state)['lines'] if l['name'] == 'Dash helpers')
        self.assertEqual(line['status'], 'fail')
        self.assertIn('frogdash-update.path', line['fix'])
        self.install('frogdash-update')
        self.helpers.step()
        line = next(l for l in selftest.report(state)['lines'] if l['name'] == 'Dash helpers')
        self.assertEqual((line['status'], line['detail']), ('warn', 'Installing: gps, wifi'))


if __name__ == '__main__':
    unittest.main()
