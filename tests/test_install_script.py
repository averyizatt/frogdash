"""The fresh-install script: it parses, and everything it installs is in the repository."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/frogdash_install.sh'
SHELL = shutil.which('sh')


class InstallScriptTests(unittest.TestCase):
    @unittest.skipUnless(SHELL, 'needs sh')
    def test_parses(self):
        done = subprocess.run([SHELL, '-n', SCRIPT.as_posix()], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_everything_it_installs_is_in_the_repository(self):
        text = SCRIPT.read_text(encoding='utf-8')
        for unit in re.search(r'for unit in (frogdash\.service[^;]*); do\n\s+install', text).group(1).split():
            self.assertTrue((ROOT / 'hardware/systemd' / unit).is_file(), unit)
        for path in re.findall(r'\$REPO/((?:hardware|config|tools)/[\w./-]+)', text):
            self.assertTrue((ROOT / path).exists(), path)
        self.assertTrue((ROOT / 'requirements.lock').is_file())

    def test_the_can_overlay_matches_the_cars_board(self):
        # The car's MCP2515 reports a 4 MHz CAN clock: an 8 MHz crystal (the clock is half).
        text = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('oscillator=8000000', text)
        self.assertIn('interrupt=25', text)

    @unittest.skipUnless(SHELL and hasattr(os, 'geteuid') and os.geteuid() != 0, 'needs sh, not root')
    def test_asks_for_root(self):
        done = subprocess.run([SHELL, SCRIPT.as_posix(), '--check'], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn('Run as root', done.stdout)


if __name__ == '__main__':
    unittest.main()
