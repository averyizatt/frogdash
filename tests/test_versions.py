"""The system version (VERSION): one number for the dash and every module (owner, November 2026).

The dash reads its own from git's files without running git: "1.1" on the release tag v1.1,
"1.1+" for a later commit. A module's version comes from the manifest its workflow publishes
beside the image, and is shown with the build it belongs to.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from hardware.frogdash.eventlog import installed_release, installed_version
from hardware.frogdash.fwupdate import ModuleFirmware
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which('git')


@unittest.skipUnless(GIT, 'needs git')
class DashVersionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.repo = Path(self.folder.name)
        self.env = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull,
                    'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
        self.git('init', '--quiet', '--initial-branch=main')

    def git(self, *args):
        return subprocess.run([GIT, '-C', str(self.repo), *args], check=True, env=self.env, capture_output=True, text=True).stdout.strip()

    def commit(self, name, text):
        (self.repo / name).write_text(text)
        self.git('add', '-A')
        self.git('commit', '--quiet', '-m', name)
        return self.git('rev-parse', 'HEAD')

    def test_the_release_on_its_tag_and_after_it(self):
        self.commit('dash.txt', 'one')
        self.assertEqual(installed_release(self.repo), '')               # Before there was a VERSION file
        first = self.commit('VERSION', '1.1\n')
        self.assertEqual(installed_version(self.repo), first[:7])
        self.assertEqual(installed_release(self.repo), '1.1+')           # Not tagged yet
        self.git('tag', 'v1.1')
        self.assertEqual(installed_release(self.repo), '1.1')            # On the release tag
        self.commit('dash.txt', 'two')
        self.assertEqual(installed_release(self.repo), '1.1+')           # A later commit
        self.git('pack-refs', '--all')                                    # Tags and branches packed, as git does over time
        self.assertEqual(installed_release(self.repo), '1.1+')
        self.git('checkout', '--quiet', 'v1.1')
        self.assertEqual(installed_release(self.repo), '1.1')

    def test_an_annotated_release_tag_counts_too(self):
        self.commit('VERSION', '1.2\n')
        self.git('tag', '-a', 'v1.2', '-m', 'Frogdash 1.2')
        self.assertEqual(installed_release(self.repo), '1.2')
        self.git('pack-refs', '--all')                                    # Packed: its commit is the "^" line
        self.assertEqual(installed_release(self.repo), '1.2')

    def test_this_repository_has_a_version(self):
        self.assertRegex((ROOT / 'VERSION').read_text(encoding='utf-8').strip(), r'^\d+\.\d+(\.\d+)?$')


class ModuleVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.state = State('socketcan', clock=lambda: 100.0)
        self.module = ModuleFirmware(self.state, self.folder, 'watermeth', 'Water/meth controller', 3)

    def publish(self, build, version=None):
        image = bytes(range(256)) * 4
        (self.folder / 'watermeth.bin').write_bytes(image)
        manifest = {'build': build, 'size': len(image), 'sha256': hashlib.sha256(image).hexdigest()}
        if version is not None:
            manifest['version'] = version
        (self.folder / 'watermeth.json').write_text(json.dumps(manifest))

    def heard(self, build):
        self.module.observe(bytes([1, 3]) + bytes.fromhex(build) + bytes([0, 2]))

    def test_a_version_is_shown_with_the_build_it_belongs_to(self):
        self.publish('1a2b3c4d', '1.1')
        self.heard('0a0b0c0d')
        shown = self.module.snapshot()
        self.assertEqual((shown['available_version'], shown['installed_version']), ('1.1', None))   # Running an older build
        self.assertEqual(shown['short'], 'build 0a0b0c0d, 1.1 (build 1a2b3c4d) ready to install')
        self.heard('1a2b3c4d')
        shown = self.module.snapshot()
        self.assertEqual((shown['installed_version'], shown['short'], shown['note']),
                         ('1.1', 'version 1.1, build 1a2b3c4d, up to date', 'Up to date'))

    def test_a_file_from_before_versions_shows_only_the_build(self):
        self.publish('1a2b3c4d')
        self.heard('1a2b3c4d')
        shown = self.module.snapshot()
        self.assertEqual((shown['installed_version'], shown['available_version'], shown['short']), (None, None, 'build 1a2b3c4d, up to date'))


if __name__ == '__main__':
    unittest.main()
