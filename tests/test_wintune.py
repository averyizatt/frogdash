"""Windows tuning: USB routes, the kiosk mailbox, Wine's COM ports and the USB stick helper."""
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from hardware.frogdash import wintune
from hardware.frogdash.state import State


def device(root, busid, vendor, product, name, interfaces):
    d = root / busid
    d.mkdir(parents=True)
    (d / 'idVendor').write_text(vendor)
    (d / 'idProduct').write_text(product)
    (d / 'product').write_text(name)
    (d / 'bDeviceClass').write_text('00')
    drivers = root.parent / 'drivers'
    for n, (cls, driver, tty) in enumerate(interfaces):
        i = d / f'{busid}:1.{n}'
        i.mkdir()
        (i / 'bInterfaceClass').write_text(cls)
        if driver:
            (drivers / driver).mkdir(parents=True, exist_ok=True)
            os.symlink(drivers / driver, i / 'driver', target_is_directory=True)
        if tty:
            (i / tty).mkdir()


@unittest.skipIf(os.name == 'nt' and not hasattr(os, 'symlink'), 'needs symlinks')
class UsbRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'devices'
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def routes(self):
        return {d['busid']: d['route'] for d in wintune.usb_devices(self.root)}

    def test_serial_vendor_shared_and_not_tuning(self):
        try:
            device(self.root, '1-1', '0403', '6001', 'FT232R', [('ff', 'ftdi_sio', 'ttyUSB0')])
            device(self.root, '1-2', '1234', 'abcd', 'ECU', [('ff', None, None)])
            device(self.root, '1-3', '046d', 'c52b', 'Receiver', [('03', 'usbhid', None)])
            device(self.root, '1-4', '1d50', '606f', 'candleLight', [('ff', 'gs_usb', None)])
            device(self.root, '1-5', '1234', 'abce', 'ECU 2', [('ff', 'usbip-host', None)])
        except OSError:
            self.skipTest('symlinks not allowed here')
        self.assertEqual(self.routes(), {'1-1': 'serial', '1-2': 'driver', '1-5': 'shared'})
        serial = next(d for d in wintune.usb_devices(self.root) if d['busid'] == '1-1')
        self.assertEqual((serial['ttys'], serial['id']), (['ttyUSB0'], '0403:6001'))


class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.state = State(clock=lambda: self.now)
        self.win = self.state.wintune

    def report(self, **extra):
        return self.win.report({'ready': True, 'state': 'idle', 'message': 'Ready', 'programs': [{'name': 'Tuner', 'path': '/p/Tuner.lnk'}],
                                'installers': [{'name': 'setup.exe', 'path': '/opt/frogdash-wine/installers/setup.exe'}], 'ports': [], **extra})

    def test_without_the_kiosk_nothing_can_be_asked(self):
        self.assertFalse(self.win.snapshot()['available'])
        with self.assertRaises(ValueError):
            self.win.request('open', '/p/Tuner.lnk')

    def test_open_and_install_only_what_the_kiosk_listed(self):
        self.report()
        with self.assertRaises(ValueError):
            self.win.request('open', '/somewhere/else.lnk')
        with self.assertRaises(ValueError):
            self.win.request('install', '/tmp/evil.exe')
        self.win.request('install', '/opt/frogdash-wine/installers/setup.exe')
        self.assertEqual(self.report(), {'action': 'install', 'target': '/opt/frogdash-wine/installers/setup.exe'})
        self.assertIsNone(self.report())

    def test_not_ready_says_why(self):
        self.win.report({'ready': False, 'why': 'Box64 is not installed', 'state': 'idle', 'message': ''})
        self.assertEqual(self.win.snapshot()['message'], 'Box64 is not installed')

    def test_a_silent_kiosk_is_gone(self):
        self.report()
        self.now += 20
        self.assertFalse(self.win.snapshot()['kiosk'])


class WineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = {'FROGDASH_WINE_ROOT': str(base / 'opt'), 'WINEPREFIX': str(base / 'prefix'),
                    'FROGDASH_SERIAL_DIR': str(base / 'by-id'), 'FROGDASH_DEV': str(base / 'dev')}
        with mock.patch.dict(os.environ, self.env):
            import tools.frogdash_wine as wine
            self.wine = importlib.reload(wine)
        self.base = base

    def tearDown(self):
        self.tmp.cleanup()

    def test_installed_programs_without_uninstallers(self):
        menu = self.base / 'prefix' / 'drive_c/ProgramData/Microsoft/Windows/Start Menu/Programs/Maker'
        menu.mkdir(parents=True)
        for name in ('Tuner.lnk', 'Uninstall Tuner.lnk', 'Readme.lnk'):
            (menu / name).write_text('')
        self.assertEqual([p['name'] for p in self.wine.programs()], ['Tuner'])

    def test_only_installers_from_the_stick_folder_and_installed_links_run(self):
        (self.base / 'opt' / 'installers').mkdir(parents=True)
        setup = self.base / 'opt' / 'installers' / 'setup.exe'
        setup.write_text('')
        with mock.patch.object(self.wine, 'box64', return_value='/usr/bin/box64'):
            self.assertEqual(self.wine.argv('install', str(setup))[2:], [str(setup)])
            with self.assertRaises(ValueError):
                self.wine.argv('install', str(self.base / 'elsewhere.exe'))
            with self.assertRaises(ValueError):
                self.wine.argv('run', str(self.base / 'not-in-prefix.lnk'))
        self.assertEqual([i['name'] for i in self.wine.installers()], ['setup.exe'])

    def test_serial_ports_become_com_ports(self):
        dev = self.base / 'dev'
        dev.mkdir()
        for name in ('ttyUSB0', 'ttyACM0'):
            (dev / name).write_text('')
        try:
            mapped = self.wine.map_ports()
        except OSError:
            self.skipTest('symlinks not allowed here')
        self.assertEqual([m[0] for m in mapped], ['COM1', 'COM2'])
        self.assertTrue((self.base / 'prefix' / 'dosdevices' / 'com1').is_symlink())

    def test_not_ready_without_box64_or_wine(self):
        with mock.patch.object(self.wine, 'box64', return_value=None):
            self.assertIn('Box64', self.wine.available()[1])


class StickTests(unittest.TestCase):
    def test_a_disk_in_use_is_never_taken_for_a_stick(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for disk in ('sda', 'sdb'):
                (base / 'block' / disk / f'{disk}1').mkdir(parents=True)
            (base / 'mounts').write_text('/dev/sda1 / ext4 rw 0 0\n')
            with mock.patch.dict(os.environ, {'FROGDASH_SYS_BLOCK': str(base / 'block'), 'FROGDASH_PROC_MOUNTS': str(base / 'mounts')}):
                import tools.frogdash_tuning as tuning
                tuning = importlib.reload(tuning)
                with mock.patch.object(tuning.os.path, 'realpath', side_effect=lambda p: '/sys/devices/usb1/' + str(p)):
                    self.assertEqual(tuning.stick(), '/dev/sdb1')       # sda holds the running system

    def test_copy_only_an_installer_from_the_stick(self):
        import tools.frogdash_tuning as tuning
        with self.assertRaises(ValueError):
            tuning.usb_copy('../../etc/shadow')


if __name__ == '__main__':
    unittest.main()
