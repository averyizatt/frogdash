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
    # A file per published name (dl-<name>); the TunerStudio archive is "download". Anything else: 404.
    'curl': 'while [ $# -gt 0 ]; do case "$1" in -o) out=$2; shift;; *) url=$1;; esac; shift; done\n'
            'name=${url##*/}\nif [ -f "$FAKE/dl-$name" ]; then src="$FAKE/dl-$name"\n'
            'elif [ "$name" = ts.tar.gz ] && [ -f "$FAKE/download" ]; then src="$FAKE/download"\nelse exit 22\nfi\n'
            'cp "$src" "$out"\n',
    'git': '[ -f "$FAKE/internet" ] || exit 2\n',
    # Wi-Fi adapters as NetworkManager reports them: wlan0 built in, wlan1 on the dash cam.
    'nmcli': 'echo "$@" >> "$FAKE/nmcli.log"\ncase "$*" in\n'
             '*"connection.interface-name con show dashcam"*) [ -f "$FAKE/no-dashcam" ] || echo wlan1;;\n'
             '*"DEVICE,TYPE dev"*) [ -f "$FAKE/one-adapter" ] || echo wlan0:wifi; echo wlan1:wifi; echo eth0:ethernet;;\n'
             '*"WIFI-PROPERTIES.AP device show"*) [ -f "$FAKE/no-ap" ] && echo no || echo yes;;\nesac\n',
    # Stands in for tools/setup_hotspot.py, which only runs as root on the Pi.
    'python3': 'echo "$@" >> "$FAKE/python.log"\ncase "$*" in *setup_hotspot.py*) mkdir -p "$FROGDASH_ETC/frogdash" && echo "{}" > "$FROGDASH_ETC/frogdash/hotspot.json";; esac\n',
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
        # The phone hotspot: made on the adapter the dash cam does not use, helper and permission installed.
        self.assertEqual(steps['Phone hotspot'][0], 'done')
        self.assertIn('setup_hotspot.py --interface wlan0 --ssid Foxbody Dash', self.log('python.log'))
        self.assertTrue((self.units / 'frogdash-hotspot.service').is_file())
        self.assertIn('enable --now frogdash-hotspot.service', self.log('systemctl.log'))
        self.assertEqual((self.units / 'frogdash.service.d/hotspot.conf').read_bytes(), (ROOT / 'config/hotspot-service.conf').read_bytes())
        self.assertTrue(self.log('systemctl.log').rstrip().endswith('restart frogdash.service'))   # Last: its new permission.
        self.assertIn('-aG dialout foxbody', self.log('usermod.log'))
        self.assertIn('try-restart frogdash-console@foxbody.service', self.log('systemctl.log'))
        for name in ('Gateway firmware file', 'Clock from GPS', 'TunerStudio: Java and display', 'TunerStudio: program'):
            self.assertEqual(steps[name][0], 'waiting', name)
            self.assertIn('press Update now', steps[name][1])
        self.assertEqual((self.log('apt.log'), list(self.fake.glob('home/*'))), ('', []))  # Nothing was fetched.
        self.assertEqual(said, 'Set up: Dash helpers, GPS service, TunerStudio: serial port, Phone hotspot')

    def publish_firmware(self, image=b'gateway firmware image', build='1a2b3c4d'):
        (self.fake / 'dl-gateway-firmware.bin').write_bytes(image)
        (self.fake / 'dl-gateway-firmware.json').write_text(json.dumps(
            {'build': build, 'size': len(image), 'sha256': hashlib.sha256(image).hexdigest()}))

    def test_the_newest_gateway_firmware_is_kept_on_the_pi_for_the_dash_to_install(self):
        from hardware.frogdash.fwupdate import load_image
        folder = self.state / 'firmware'
        _, _, steps = self.run_setup('online')
        self.assertEqual(steps['Gateway firmware file'], ('waiting', 'No gateway firmware has been published yet'))
        self.assertFalse(folder.exists())
        self.publish_firmware()
        _, _, steps = self.run_setup('online')
        self.assertEqual(steps['Gateway firmware file'][0], 'done')
        self.assertIn('Downloaded build 1a2b3c4d', steps['Gateway firmware file'][1])
        manifest, image = load_image(folder, 'gateway')        # Exactly what the dash's installer accepts.
        self.assertEqual((manifest['build'], image), ('1a2b3c4d', b'gateway firmware image'))
        self.assertEqual(self.run_setup('online')[2]['Gateway firmware file'], ('ok', 'Build 1a2b3c4d is the newest'))
        self.assertIn('no internet', self.run_setup('offline')[2]['Gateway firmware file'][1])
        # A newer build replaces it; one that does not match its checksum never does.
        self.publish_firmware(b'second build', '2b3c4d5e')
        self.assertEqual(self.run_setup('online')[2]['Gateway firmware file'][0], 'done')
        self.assertEqual(load_image(folder, 'gateway')[1], b'second build')
        self.publish_firmware(b'third build', '3c4d5e6f')
        (self.fake / 'dl-gateway-firmware.bin').write_bytes(b'tampered with')
        self.assertEqual(self.run_setup('online')[2]['Gateway firmware file'][0], 'failed')
        self.assertEqual(load_image(folder, 'gateway')[1], b'second build')

    def test_with_internet_the_rest_is_installed_and_a_second_run_changes_nothing(self):
        (self.fake / 'download').write_bytes(self.archive)
        self.publish_firmware()
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
        self.assertEqual(self.log('python.log').count('setup_hotspot.py'), 1)       # The profile is made once.
        self.assertEqual(self.log('systemctl.log').count('restart frogdash.service'), 1)
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

    def test_with_one_adapter_the_hotspot_shares_it_with_the_dash_cam(self):
        (self.fake / 'no-ap').write_text('')                  # No adapter can be an access point at all.
        _, _, steps = self.run_setup('offline')
        self.assertEqual(steps['Phone hotspot'][0], 'waiting')
        self.assertNotIn('setup_hotspot.py', self.log('python.log'))
        self.assertFalse((self.units / 'frogdash-hotspot.service').exists())
        self.assertNotIn('restart frogdash.service', self.log('systemctl.log'))
        (self.fake / 'no-ap').unlink()
        (self.fake / 'one-adapter').write_text('')            # Only wlan1, and the dash cam is on it:
        self.assertEqual(self.run_setup('offline')[2]['Phone hotspot'][0], 'done')
        self.assertIn('--interface wlan1', self.log('python.log'))   # the hotspot takes it while it is switched on.

    def test_asked_by_the_dash_it_finds_out_about_the_internet_itself(self):
        self.assertEqual(self.run_setup()[2]['TunerStudio: Java and display'][0], 'waiting')
        (self.fake / 'internet').write_text('')
        (self.fake / 'download').write_bytes(self.archive)
        _, _, steps = self.run_setup()
        self.assertEqual((steps['TunerStudio: Java and display'][0], steps['TunerStudio: program'][0]), ('done', 'done'))


if __name__ == '__main__':
    unittest.main()
