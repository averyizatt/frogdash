"""The Pi setup script, run for real against a stand-in system: nothing is typed over SSH.

systemctl, dpkg, apt-get, usermod, id, getent, chown, curl and git are small stand-ins that
record what was asked and keep their "installed" state in a folder, so the script's own
logic runs unchanged. The units, GPS helper and chrony file are the repository's own.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from hardware.frogdash.helpers import stamp

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/frogdash_setup.sh'
SHELL = shutil.which('sh')
UBLOX = 'usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00'
LAST = 'for a; do last=$a; done\n'
SHIMS = {
    'systemctl': 'echo "$@" >> "$FAKE/systemctl.log"\n' + LAST +
                 'case "$1" in is-enabled) [ -f "$FROGDASH_UNITS/enabled-$last" ] || exit 1;;\n'
                 'enable) touch "$FROGDASH_UNITS/enabled-$last";; esac\nexit 0\n',
    'dpkg': '[ -f "$FAKE/pkg-$2" ] || exit 1\necho "Status: install ok installed"\n',
    'apt-get': 'echo "$@" >> "$FAKE/apt.log"\n[ "$1" = install ] || exit 0\n[ -f "$FAKE/apt-fails" ] && exit 100\n'
               'for a; do case "$a" in -*|install) ;; *) touch "$FAKE/pkg-$a";; esac; done\n',
    'usermod': 'echo "$@" >> "$FAKE/usermod.log"\ntouch "$FAKE/dialout"\n',
    'id': 'if [ -f "$FAKE/dialout" ]; then echo "$2 video dialout"; else echo "$2 video"; fi\n',
    'getent': 'echo "$2:x:1000:1000::$FAKE_HOME:/bin/sh"\n',
    'chown': 'echo "$@" >> "$FAKE/chown.log"\n',
    'curl': 'while [ $# -gt 0 ]; do case "$1" in -o) out=$2; shift;; esac; shift; done\n'
            '[ -f "$FAKE/download" ] || exit 22\ncp "$FAKE/download" "$out"\n',
    'git': '[ -f "$FAKE/internet" ] || exit 2\n',
    'sleep': 'exit 0\n',
}


@unittest.skipUnless(SHELL, 'needs sh')
class SetupScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        base = Path(self.folder.name)
        self.fake, self.state, self.units, self.etc, self.opt, self.serial = (base / n for n in ('fake', 'state', 'units', 'etc', 'opt', 'by-id'))
        bin_dir = base / 'bin'
        for folder in (self.fake / 'home', self.state, self.units / 'multi-user.target.wants', self.etc / 'default', self.opt, self.serial, bin_dir, base / 'sys'):
            folder.mkdir(parents=True)
        for name, body in SHIMS.items():
            (bin_dir / name).write_text('#!/bin/sh\n' + body, newline='\n')
            (bin_dir / name).chmod(0o755)
        # A Pi as it is today: the update helper and the screen service by hand, gpsd on auto-detect.
        for name in ('frogdash-update.path', 'frogdash-update.service'):
            shutil.copy(ROOT / 'hardware/systemd' / name, self.units / name)
        (self.units / 'enabled-frogdash-update.path').write_text('')
        (self.units / 'multi-user.target.wants/frogdash-console@foxbody.service').write_text('')
        self.gpsd = self.etc / 'default/gpsd'
        self.gpsd.write_text('DEVICES=""\nGPSD_OPTIONS=""\nUSBAUTO="true"\n', newline='\n')
        (self.serial / UBLOX).write_text('')
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as tar:
            for name, text in (('TunerStudioMS/TunerStudio.sh', b'#!/bin/sh\n'), ('TunerStudioMS/TunerStudioMS.jar', b'jar')):
                info = tarfile.TarInfo(name)
                info.size = len(text)
                tar.addfile(info, io.BytesIO(text))
        self.archive = archive.getvalue()
        # A passwd line is split on colons, so the home folder is given without a drive letter's colon.
        home = (self.fake / 'home').as_posix()
        home = f'/{home[0].lower()}{home[2:]}' if home[1:2] == ':' else home
        self.env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'], 'FAKE': self.fake.as_posix(), 'FAKE_HOME': home,
                    'FROGDASH_REPO': ROOT.as_posix(), 'FROGDASH_STATE': self.state.as_posix(), 'FROGDASH_UNITS': self.units.as_posix(),
                    'FROGDASH_ETC': self.etc.as_posix(), 'FROGDASH_OPT': self.opt.as_posix(), 'FROGDASH_SERIAL_DIR': self.serial.as_posix(),
                    'FROGDASH_SYS': (base / 'sys').as_posix(), 'FROGDASH_TS_URL': 'https://example.invalid/ts.tar.gz',
                    'FROGDASH_TS_SHA': hashlib.sha256(self.archive).hexdigest()}

    def tearDown(self):
        self.folder.cleanup()

    def run_setup(self, *args):
        done = subprocess.run([SHELL, SCRIPT.as_posix(), *args], env=self.env, capture_output=True, text=True, timeout=120)
        status = json.loads((self.state / 'setup-status.json').read_text())
        return done.stdout.strip(), status, {s['name']: (s['result'], s['detail']) for s in status['steps']}

    def log(self, name):
        path = self.fake / name
        return path.read_text() if path.exists() else ''

    def test_first_run_without_internet_does_all_it_can_and_names_what_waits(self):
        said, status, steps = self.run_setup('offline')
        self.assertEqual((status['stamp'], status['running']), (stamp(SCRIPT), False))   # The dash recognises this run.
        self.assertEqual(steps['Dash helpers'], ('done', 'Installed: gps wifi netkeeper'))
        for unit in ('frogdash-gps.path', 'frogdash-gps.service', 'frogdash-wifi.path', 'frogdash-wifi.service', 'frogdash-netkeeper.service'):
            self.assertTrue((self.units / unit).is_file(), unit)
        self.assertIn('enable --now frogdash-gps.path', self.log('systemctl.log'))
        self.assertIn('enable --now frogdash-netkeeper.service', self.log('systemctl.log'))
        self.assertFalse((self.units / 'frogdash-netkeeper.path').exists())
        self.assertFalse((self.units / 'frogdash-kiosk.service').exists())               # Only the listed services.
        # gpsd is pointed at the receiver alone, so it can never open the tuning cable.
        self.assertEqual(steps['GPS service'][0], 'done')
        text = self.gpsd.read_text()
        self.assertIn(f'DEVICES="{(self.serial / UBLOX).as_posix()}"', text)
        self.assertIn('USBAUTO="false"', text)
        self.assertIn('GPSD_OPTIONS="-n"', text)
        self.assertEqual(steps['TunerStudio: serial port'], ('done', 'foxbody can now open the tuning cable'))
        self.assertIn('-aG dialout foxbody', self.log('usermod.log'))
        self.assertIn('try-restart frogdash-console@foxbody.service', self.log('systemctl.log'))
        for name in ('Clock from GPS', 'TunerStudio: Java and display', 'TunerStudio: program'):
            self.assertEqual(steps[name][0], 'waiting', name)
            self.assertIn('press Update now', steps[name][1])
        self.assertEqual((self.log('apt.log'), list(self.fake.glob('home/*'))), ('', []))  # Nothing was fetched.
        self.assertEqual(said, 'Set up: Dash helpers, GPS service, TunerStudio: serial port')

    def test_with_internet_the_rest_is_installed_and_a_second_run_changes_nothing(self):
        (self.fake / 'download').write_bytes(self.archive)
        said, _, steps = self.run_setup('online')
        self.assertEqual(steps['TunerStudio: Java and display'], ('done', 'Installed xwayland default-jre'))
        self.assertIn('install -y -q xwayland default-jre', self.log('apt.log'))
        self.assertEqual(steps['Clock from GPS'][0], 'done')
        self.assertEqual((self.etc / 'chrony/conf.d/frogdash-gps.conf').read_bytes(), (ROOT / 'hardware/chrony/frogdash-gps.conf').read_bytes())
        self.assertIn('restart chrony', self.log('systemctl.log'))
        self.assertEqual(steps['TunerStudio: program'][0], 'done')
        self.assertTrue((self.fake / 'home/TunerStudioMS/TunerStudio.sh').is_file())   # Where the screen's launcher looks.
        self.assertIn('foxbody:', self.log('chown.log'))
        self.assertEqual(self.log('apt.log').count('update'), 1)
        self.assertNotIn('failed', [result for result, _ in steps.values()])
        logs = [self.log(name) for name in ('apt.log', 'usermod.log', 'chown.log')]
        calls = self.log('systemctl.log')
        said, _, steps = self.run_setup('online')
        self.assertEqual(said, '')
        self.assertEqual({result for result, _ in steps.values()}, {'ok'})
        self.assertEqual([self.log(name) for name in ('apt.log', 'usermod.log', 'chown.log')], logs)
        new = self.log('systemctl.log')[len(calls):]
        self.assertTrue(all(line.startswith('is-enabled') for line in new.splitlines()), new)   # It only looked.

    def test_a_download_that_is_not_the_expected_file_is_never_unpacked(self):
        (self.fake / 'download').write_bytes(self.archive + b'tampered')
        _, _, steps = self.run_setup('online')
        self.assertEqual(steps['TunerStudio: program'], ('failed', 'The download is not the expected file, so it was not installed'))
        self.assertEqual(list(self.fake.glob('home/*')), [])
        (self.fake / 'download').unlink()
        self.assertEqual(self.run_setup('online')[2]['TunerStudio: program'], ('failed', 'Download failed from tunerstudio.com'))
        (self.fake / 'apt-fails').write_text('')
        (self.fake / 'pkg-xwayland').unlink()
        self.assertEqual(self.run_setup('online')[2]['TunerStudio: Java and display'], ('failed', 'Could not install xwayland'))

    def test_an_unrecognised_receiver_is_left_on_auto_detect(self):
        (self.serial / UBLOX).unlink()
        (self.serial / 'usb-Prolific_Technology_Inc._USB-Serial_Controller-if00-port0').write_text('')
        before = self.gpsd.read_text()
        _, _, steps = self.run_setup('offline')
        self.assertEqual(steps['GPS service'][0], 'waiting')
        self.assertIn('No GPS receiver recognised', steps['GPS service'][1])
        self.assertEqual(self.gpsd.read_text(), before)       # Pinning nothing would switch a working receiver off.

    def test_asked_by_the_dash_it_finds_out_about_the_internet_itself(self):
        self.assertEqual(self.run_setup()[2]['TunerStudio: Java and display'][0], 'waiting')
        (self.fake / 'internet').write_text('')
        (self.fake / 'download').write_bytes(self.archive)
        _, _, steps = self.run_setup()
        self.assertEqual((steps['TunerStudio: Java and display'][0], steps['TunerStudio: program'][0]), ('done', 'done'))


if __name__ == '__main__':
    unittest.main()
