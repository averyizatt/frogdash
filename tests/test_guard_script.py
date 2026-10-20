"""The recovery guard (tools/frogdash_guard.sh), run for real against a throwaway git
repository, with systemctl, curl, sleep and journalctl replaced by stand-ins. The
stand-in dash answers unless the state folder has a file named 'down'; an update is
running while it has 'updating'."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/frogdash_guard.sh'
SHELL = shutil.which('sh')
SHIMS = {
    'systemctl': 'echo "$@" >> "$FROGDASH_STATE/systemctl.log"\n'
                 'case "$*" in *"is-active --quiet frogdash-update.service"*) [ -f "$FROGDASH_STATE/updating" ] || exit 3;; esac\nexit 0\n',
    'curl': '[ -f "$FROGDASH_STATE/down" ] && exit 7\nexit 0\n',
    'sleep': 'exit 0\n',
    'journalctl': 'echo "ModuleNotFoundError: No module named pyubx2"\n',
}


@unittest.skipUnless(SHELL and shutil.which('git'), 'needs sh and git')
class GuardTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        base = Path(self.folder.name)
        self.repo, self.state, bin_dir, self.units = base / 'repo', base / 'state', base / 'bin', base / 'units'
        for folder in (self.repo, self.state, bin_dir, self.units):
            folder.mkdir()
        for name, body in SHIMS.items():
            (bin_dir / name).write_text('#!/bin/sh\n' + body, newline='\n')
            (bin_dir / name).chmod(0o755)
        self.env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
                    'FROGDASH_REPO': self.repo.as_posix(), 'FROGDASH_STATE': self.state.as_posix(),
                    'FROGDASH_UNITS': self.units.as_posix(), 'FROGDASH_BUSY': (self.state / 'busy').as_posix(),
                    'FROGDASH_HEALTH_URL': 'http://127.0.0.1:1/health',
                    'FROGDASH_GUARD_GOOD_AFTER': '10', 'FROGDASH_GUARD_BAD_AFTER': '15', 'FROGDASH_GUARD_TICK': '5',
                    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull,
                    'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
        self.git('init', '--quiet', '--initial-branch=main')
        self.first = self.commit('version one')

    def tearDown(self):
        self.folder.cleanup()

    def git(self, *args):
        return subprocess.run(['git', '-C', self.repo.as_posix(), *args], check=True, env=self.env, capture_output=True, text=True).stdout.strip()

    def commit(self, text):
        (self.repo / 'dash.txt').write_text(text)
        self.git('add', '-A')
        self.git('commit', '--quiet', '-m', text)
        return self.git('rev-parse', 'HEAD')

    def guard(self, rounds):
        subprocess.run([SHELL, SCRIPT.as_posix()], env={**self.env, 'FROGDASH_GUARD_ROUNDS': str(rounds)},
                       capture_output=True, text=True, timeout=120)

    def read(self, name):
        path = self.state / name
        return path.read_text().strip() if path.exists() else ''

    def test_a_version_that_ran_is_remembered_and_put_back_when_the_next_does_not_start(self):
        self.guard(rounds=1)
        self.assertEqual(self.read('last-good'), '')                 # Five seconds is not yet proof
        self.guard(rounds=2)
        self.assertEqual(self.read('last-good'), self.first)         # Ten seconds answering: this one runs
        # An update installs a version that does not start, and the key goes off before
        # the updater has put the old one back: the Pi starts on the broken version.
        bad = self.commit('version two, broken')
        (self.state / 'down').write_text('')
        self.guard(rounds=2)
        self.assertEqual(self.git('rev-parse', 'HEAD'), bad)          # Ten seconds down: not yet
        self.guard(rounds=3)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.first)   # Fifteen: back on the one that ran
        self.assertEqual(self.read('update-bad'), bad)                # And the updater will not install it again
        status = json.loads(self.read('update-status.json'))
        self.assertEqual(status['state'], 'rolledback')
        self.assertIn('Recovered by itself', status['message'])
        self.assertIn('restart frogdash.service', self.read('systemctl.log'))
        self.assertIn('pyubx2', self.read('update-failure.log'))
        events = (self.state / 'events').glob('*.jsonl')
        self.assertIn('Recovered by itself', ''.join(path.read_text() for path in events))
        self.assertFalse((self.state / 'busy').exists())

    def test_nothing_is_done_while_an_update_is_running(self):
        self.guard(rounds=2)
        bad = self.commit('version two')
        (self.state / 'down').write_text('')
        (self.state / 'updating').write_text('')                      # The updater is in charge
        self.guard(rounds=10)
        self.assertEqual(self.git('rev-parse', 'HEAD'), bad)
        self.assertNotIn('restart', self.read('systemctl.log'))

    def test_with_nothing_to_go_back_to_the_dash_is_restarted_once_and_left_to_the_rescue_screen(self):
        self.guard(rounds=2)                                          # This version ran
        (self.state / 'down').write_text('')
        self.guard(rounds=12)                                         # Down for a minute
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.first)
        self.assertEqual(self.read('systemctl.log').count('restart frogdash.service'), 1)
        self.assertIn('rescue screen', json.loads(self.read('update-status.json'))['message'])


if __name__ == '__main__':
    unittest.main()
