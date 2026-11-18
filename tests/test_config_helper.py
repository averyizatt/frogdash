"""tools/frogdash_config.py: the setup wizard's Apply, run as root on the Pi."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def helper(state):
    with mock.patch.dict(os.environ, {'FROGDASH_STATE': str(state), 'FROGDASH_REPO': str(ROOT)}):
        spec = importlib.util.spec_from_file_location('frogdash_config_under_test', ROOT / 'tools' / 'frogdash_config.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class ConfigHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.etc, self.state = Path(self.tmp.name) / 'etc', Path(self.tmp.name) / 'state'
        self.state.mkdir()
        self.config = helper(self.state)
        self.config.profiles.write(self.config.profiles.preset('foxbody'), self.etc)

    def tearDown(self):
        self.tmp.cleanup()

    def saved(self):
        return json.loads((self.etc / 'frogdash' / 'system.json').read_text(encoding='utf-8'))

    def test_the_choices_are_saved_marked_configured_and_the_old_profile_kept(self):
        before = (self.etc / 'frogdash' / 'system.json').read_text(encoding='utf-8')
        wanted = self.config.profiles.preset('generic')
        wanted['ecu'].update(profile='haltech', bitrate=1000000)
        profile, reboot = self.config.apply({'profile': wanted}, self.etc, run_setup=False)
        self.assertTrue(profile['configured'])
        self.assertEqual(self.saved()['preset'], 'generic')
        self.assertEqual(self.saved()['ecu'], {'profile': 'haltech', 'bitrate': 1000000})
        self.assertEqual((self.etc / 'frogdash' / 'system.json.bak').read_text(encoding='utf-8'), before)
        self.assertIn('FD_CAN_BITRATE=', (self.etc / 'frogdash' / 'system.env').read_text(encoding='utf-8'))
        self.assertEqual(reboot, ['screen'])     # foxbody forces 1920x720, generic does not

    def test_a_bad_profile_changes_nothing(self):
        before = (self.etc / 'frogdash' / 'system.json').read_text(encoding='utf-8')
        wanted = self.config.profiles.preset('generic')
        wanted['hotspot_name'] = 'no;semicolons'
        with self.assertRaises(self.config.profiles.ProfileError):
            self.config.apply({'profile': wanted}, self.etc, run_setup=False)
        with self.assertRaises(self.config.profiles.ProfileError):
            self.config.apply({'nothing': 1}, self.etc, run_setup=False)
        self.assertEqual((self.etc / 'frogdash' / 'system.json').read_text(encoding='utf-8'), before)
        self.assertFalse((self.etc / 'frogdash' / 'system.json.bak').exists())

    def test_a_custom_ecu_profile_is_saved_with_the_old_one_kept(self):
        folder = self.etc / 'frogdash' / 'ecu'
        folder.mkdir(parents=True)
        (folder / 'custom.json').write_text('{"old": 1}', encoding='utf-8')
        mine = {'id': 'custom', 'label': 'Mine', 'frames': [{'ids': ['0x360'], 'signals': [{'key': 'ecu.rpm', 'layout': 'u16@0'}]}]}
        wanted = self.config.profiles.preset('generic')
        wanted['ecu']['profile'] = 'custom'
        self.config.apply({'profile': wanted, 'custom': mine}, self.etc, run_setup=False)
        self.assertEqual(json.loads((folder / 'custom.json').read_text(encoding='utf-8')), mine)
        self.assertEqual((folder / 'custom.json.bak').read_text(encoding='utf-8'), '{"old": 1}')
        self.assertEqual(self.saved()['ecu']['profile'], 'custom')

    def test_a_bad_custom_profile_changes_nothing(self):
        before = (self.etc / 'frogdash' / 'system.json').read_text(encoding='utf-8')
        with self.assertRaises(self.config.profiles.ProfileError):
            self.config.apply({'profile': self.config.profiles.preset('generic'), 'custom': {'id': 'custom', 'frames': []}}, self.etc, run_setup=False)
        self.assertEqual((self.etc / 'frogdash' / 'system.json').read_text(encoding='utf-8'), before)
        self.assertFalse((self.etc / 'frogdash' / 'ecu' / 'custom.json').exists())

    def test_a_changed_can_board_asks_for_a_restart(self):
        wanted = self.config.profiles.preset('foxbody')
        wanted['can_hat']['oscillator'] = 16000000
        _, reboot = self.config.apply({'profile': wanted}, self.etc, run_setup=False)
        self.assertEqual(reboot, ['can_hat'])

    def test_main_reads_and_removes_the_request_and_reports(self):
        (self.state / 'config-request.json').write_text('{"profile": {"hotspot_name": "bad;name"}}', encoding='utf-8')
        self.assertEqual(self.config.main(), 1)
        self.assertFalse((self.state / 'config-request.json').exists())
        status = json.loads((self.state / 'config-status.json').read_text(encoding='utf-8'))
        self.assertEqual(status['state'], 'failed')
        self.assertIn('Nothing was changed', status['message'])


if __name__ == '__main__':
    unittest.main()
