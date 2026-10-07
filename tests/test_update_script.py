"""The updater's rollback, run for real against a throwaway git repository.

systemctl, curl, sleep, journalctl and nmcli are replaced by small stand-ins, so the
script's own logic runs unchanged: a version whose health check fails must be undone.
The stand-in dash is "broken" when the checked-out tree contains a file named BROKEN,
and has no screen when it contains NOSCREEN.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/frogdash_update.sh'
SHELL = shutil.which('sh')
SHIMS = {
    'systemctl': 'echo "$@" >> "$FROGDASH_STATE/systemctl.log"\ncase "$1" in show) echo 0;; esac\nexit 0\n',
    'curl': '[ -f "$FROGDASH_REPO/BROKEN" ] && exit 22\n'
            'if [ -f "$FROGDASH_REPO/NOSCREEN" ]; then echo \'{"mode": "socketcan", "ui_clients": 0}\'\n'
            'else echo \'{"mode": "socketcan", "ui_clients": 1}\'; fi\n',
    'sleep': 'exit 0\n',
    'journalctl': 'echo "Traceback: the new version crashed"\n',
    'nmcli': 'exit 0\n',
}


@unittest.skipUnless(SHELL and shutil.which('git'), 'needs sh and git')
class UpdateScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        base = Path(self.folder.name)
        self.origin, self.repo, self.state = base / 'origin', base / 'repo', base / 'state'
        bin_dir, units = base / 'bin', base / 'units'
        for folder in (self.origin, self.state, bin_dir, units):
            folder.mkdir()
        for name, body in SHIMS.items():
            (bin_dir / name).write_text('#!/bin/sh\n' + body, newline='\n')
            (bin_dir / name).chmod(0o755)
        self.env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
                    'FROGDASH_REPO': self.repo.as_posix(), 'FROGDASH_STATE': self.state.as_posix(),
                    'FROGDASH_UNITS': units.as_posix(), 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull,
                    'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
        self.git(self.origin, 'init', '--quiet', '--initial-branch=main')
        self.first = self.publish('dash.txt', 'version one')
        subprocess.run(['git', 'clone', '--quiet', self.origin.as_posix(), self.repo.as_posix()], check=True, env=self.env, capture_output=True)

    def tearDown(self):
        self.folder.cleanup()

    def git(self, folder, *args):
        return subprocess.run(['git', '-C', folder.as_posix(), *args], check=True, env=self.env, capture_output=True, text=True).stdout.strip()

    def publish(self, name, text):
        (self.origin / name).write_text(text)
        self.git(self.origin, 'add', '-A')
        self.git(self.origin, 'commit', '--quiet', '-m', name)
        return self.git(self.origin, 'rev-parse', 'HEAD')

    def run_script(self, *args, request=None):
        if request:
            (self.state / 'update-request').write_text(request)
        subprocess.run([SHELL, SCRIPT.as_posix(), *args], env=self.env, capture_output=True, text=True, timeout=120)
        return json.loads((self.state / 'update-status.json').read_text())

    def head(self):
        return self.git(self.repo, 'rev-parse', 'HEAD')

    def test_good_update_is_kept_and_can_be_undone_by_hand(self):
        second = self.publish('dash.txt', 'version two')
        status = self.run_script(request='requested')
        self.assertEqual((status['state'], self.head()), ('updated', second))
        self.assertEqual(status['previous'], self.first[:len(status['previous'])])
        self.assertFalse((self.state / 'update-request').exists())
        self.assertEqual(self.run_script()['state'], 'current')
        # Undo update: the request file carries the action.
        status = self.run_script(request='rollback')
        self.assertEqual((status['state'], self.head(), status['previous']), ('rolledback', self.first, ''))
        self.assertEqual(self.run_script('rollback')['state'], 'failed')  # Nothing further back is saved.
        # Update now returns to the newest: an undo by hand does not blacklist it.
        self.assertEqual((self.run_script()['state'], self.head()), ('updated', second))

    def test_version_that_does_not_start_is_rolled_back_and_not_retried(self):
        bad = self.publish('BROKEN', 'crashes on start')
        status = self.run_script()
        self.assertEqual((status['state'], self.head()), ('rolledback', self.first))
        self.assertIn('did not stay up', status['message'])
        self.assertEqual((self.state / 'update-bad').read_text().strip(), bad)
        self.assertIn('Traceback', (self.state / 'update-failure.log').read_text())
        restarts = (self.state / 'systemctl.log').read_text().count('restart frogdash.service')
        self.assertEqual(restarts, 2)  # Once into the new version, once back.
        # Pressing Update again must not reinstall the same broken commit.
        status = self.run_script()
        self.assertEqual((status['state'], self.head()), ('held', self.first))
        self.assertEqual((self.state / 'systemctl.log').read_text().count('restart frogdash.service'), restarts)
        # A newer, working version installs and clears the block.
        self.git(self.origin, 'rm', '--quiet', 'BROKEN')
        fixed = self.publish('dash.txt', 'version three')
        self.assertEqual((self.run_script()['state'], self.head()), ('updated', fixed))
        self.assertFalse((self.state / 'update-bad').exists())

    def test_screen_that_does_not_reconnect_is_rolled_back(self):
        self.publish('NOSCREEN', 'backend fine, page never loads')
        status = self.run_script()
        self.assertEqual((status['state'], self.head()), ('rolledback', self.first))
        self.assertIn('screen did not reconnect', status['message'])

    def test_changed_unit_files_follow_the_version_in_both_directions(self):
        unit = Path(self.env['FROGDASH_UNITS']) / 'frogdash.service'
        unit.write_text('old unit')
        (self.origin / 'hardware/systemd').mkdir(parents=True)
        (self.origin / 'hardware/systemd/frogdash.service').write_text('new unit')
        self.publish('dash.txt', 'version two')
        self.assertEqual(self.run_script()['state'], 'updated')
        self.assertEqual(unit.read_text(), 'new unit')
        self.assertIn('daemon-reload', (self.state / 'systemctl.log').read_text())
        # A broken version that also changed the unit: the rollback restores the unit file too.
        (self.origin / 'hardware/systemd/frogdash.service').write_text('broken unit')
        self.publish('BROKEN', 'crashes on start')
        self.assertEqual(self.run_script()['state'], 'rolledback')
        self.assertEqual(unit.read_text(), 'new unit')

if __name__ == '__main__':
    unittest.main()
