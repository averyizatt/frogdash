"""The system profile (hardware/frogdash/sysconfig.py): what this Pi has, kept outside the
repository, and the dash's options and the setup's values made from it."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from hardware.frogdash import sysconfig
from hardware.frogdash.github_link import GitHubLink

CAR_ARGS = '--interface can0 --gpsd --log-dir /var/lib/frogdash/logs --terminal'


class SysconfigTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.etc = Path(self.folder.name)

    def test_the_cars_preset_gives_exactly_the_options_it_runs(self):
        # What the car's Pi ran before profiles (config/frogdash-options, November 2026).
        car = sysconfig.validate(sysconfig.preset('foxbody'))
        self.assertEqual(sysconfig.to_args(car), CAR_ARGS)
        self.assertEqual((car['uploads']['repo'], car['hotspot_name'], car['locale']['timezone']),
                         ('averyizatt/frogdash', 'Foxbody Dash', 'America/Denver'))

    def test_a_new_car_sends_nothing_onto_its_bus_it_was_not_asked_to(self):
        generic = sysconfig.validate(sysconfig.preset('generic'))
        args = sysconfig.to_args(generic)
        self.assertNotIn('--gpsd', args)                 # No 0x203 GPS frames
        self.assertIn('--no-engine-runtime', args)       # No 0x309 without the water/meth board
        self.assertNotIn('--terminal', args)
        self.assertEqual(generic['uploads']['repo'], '')
        gps = sysconfig.validate(sysconfig.preset('generic'))
        gps['gps'] = {'enabled': True, 'transmit_on_can': False}
        gps['camera'] = {'enabled': True, 'rotate': 180}
        self.assertEqual(sysconfig.to_args(gps), '--interface can0 --gpsd --gps-no-transmit --log-dir /var/lib/frogdash/logs '
                                                 '--camera --camera-rotate 180 --no-engine-runtime')

    def test_a_profile_that_is_wrong_is_refused_naming_the_field(self):
        good = sysconfig.validate(sysconfig.preset('generic'))
        for change, said in ((('gps', 'enabled', 'yes'), 'gps.enabled should be true or false'),
                             (('can_hat', 'oscillator', 1), 'can_hat.oscillator should be from'),
                             (('locale', 'timezone', 'Europe/Berlin; reboot'), 'locale.timezone'),
                             (('hotspot_name', None, "it's"), 'hotspot_name'),
                             (('extra_args', None, ['--x', 'a b']), 'extra_args'),
                             (('uploads', 'repo', 'not a repo'), 'uploads.repo')):
            profile = json.loads(json.dumps(good))
            group, key, value = change
            if key:
                profile[group][key] = value
            else:
                profile[group] = value
            with self.assertRaises(sysconfig.ProfileError) as caught:
                sysconfig.validate(profile)
            self.assertIn(said, str(caught.exception))
        with self.assertRaises(sysconfig.ProfileError):
            sysconfig.complete({'preset': 'generic', 'warp_drive': True})
        with self.assertRaises(sysconfig.ProfileError):
            sysconfig.preset('../etc/passwd')

    def test_a_pi_set_up_before_profiles_keeps_what_it_had(self):
        (self.etc / 'default').mkdir()
        (self.etc / 'default/frogdash').write_text(f'FROGDASH_ARGS="{CAR_ARGS}"\n')
        self.assertEqual(sysconfig.sync(self.etc), ('done', 'Made from the foxbody preset'))
        profile = sysconfig.load(self.etc)
        self.assertEqual((profile['preset'], profile['configured'], sysconfig.to_args(profile)), ('foxbody', True, CAR_ARGS))
        env = (self.etc / 'frogdash/system.env').read_text()
        self.assertIn(f"FD_ARGS='{CAR_ARGS}'\n", env)
        self.assertIn("FD_HOTSPOT_NAME='Foxbody Dash'\n", env)
        self.assertEqual(sysconfig.sync(self.etc), ('ok', 'Preset foxbody'))

    def test_a_new_pi_starts_generic_and_its_setup_values_follow_its_profile(self):
        self.assertEqual(sysconfig.sync(self.etc), ('done', 'Made from the generic preset'))
        self.assertFalse(sysconfig.load(self.etc)['configured'])           # The wizard has not run
        saved = json.loads((self.etc / 'frogdash/system.json').read_text())
        self.assertEqual(saved, {'version': 1, 'preset': 'generic'})        # Only what differs from the preset
        saved['gps'] = {'enabled': True}                                    # Changed in the dash's Setup
        (self.etc / 'frogdash/system.json').write_text(json.dumps(saved))
        self.assertEqual(sysconfig.sync(self.etc), ('done', 'Preset generic: setup values written again'))
        self.assertIn("FD_GPS='1'", (self.etc / 'frogdash/system.env').read_text())

    def test_a_field_added_later_takes_its_presets_value(self):
        (self.etc / 'frogdash').mkdir()
        (self.etc / 'frogdash/system.json').write_text(json.dumps({'version': 1, 'preset': 'foxbody', 'terminal': False}))
        profile = sysconfig.load(self.etc)
        self.assertEqual((profile['terminal'], profile['gps']['enabled'], profile['hotspot_name']), (False, True, 'Foxbody Dash'))

    def test_the_car_follows_its_preset_in_the_repository_except_where_chosen_on_the_pi(self):
        car = sysconfig.validate(sysconfig.preset('foxbody'))
        car['camera']['enabled'] = True                       # Chosen on the Pi
        sysconfig.write(car, self.etc)
        self.assertEqual(json.loads((self.etc / 'frogdash/system.json').read_text()),
                         {'version': 1, 'preset': 'foxbody', 'camera': {'enabled': True}})
        # The preset changed in the repository (a later update): the car gets it, the camera stays on.
        original = sysconfig.preset
        def newer(name):
            data = original(name)
            if name == 'foxbody':
                data['dashcam']['enabled'] = True
            return data
        sysconfig.preset = newer
        try:
            profile = sysconfig.load(self.etc)
        finally:
            sysconfig.preset = original
        self.assertEqual((profile['camera']['enabled'], profile['dashcam']['enabled']), (True, True))

    def test_the_command_line_the_installer_uses(self):
        self.assertEqual(sysconfig.main(['--etc', str(self.etc), 'init', '--preset', 'generic',
                                         '--set', 'can_hat.oscillator=8000000', '--set', 'power=none']), 0)
        profile = sysconfig.load(self.etc)
        self.assertEqual((profile['can_hat']['oscillator'], profile['power']), (8000000, 'none'))
        self.assertEqual(sysconfig.main(['--etc', str(self.etc), 'init', '--preset', 'foxbody']), 0)   # Kept
        self.assertEqual(sysconfig.load(self.etc)['preset'], 'generic')
        self.assertEqual(sysconfig.main(['--etc', str(self.etc), 'init', '--set', 'nonsense=1', '--force']), 2)

    def test_reports_go_only_where_the_profile_says(self):
        link = GitHubLink(self.folder.name, client_id='Ov23test', repo='')
        self.assertFalse(link.status()['ready'])
        with self.assertRaises(ValueError) as caught:
            asyncio.run(link.connect())
        self.assertIn('Choose the GitHub repository', str(caught.exception))
        self.assertTrue(GitHubLink(self.folder.name, client_id='Ov23test', repo='someone/their-car').status()['ready'])


if __name__ == '__main__':
    unittest.main()
