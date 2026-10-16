"""Exact 1920 x 720 on the dash screen (tools/frogdash_screen.py): the EDID, the boot files,
and the trial that goes back by itself, against a stand-in Pi in a temporary folder."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.paint import Paint
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.gps import GPS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
REAL_RUN = subprocess.run   # The stand-in Pi replaces it; every test puts it back.
CMDLINE = 'console=serial0,115200 console=tty1 root=PARTUUID=672ec752-02 rootfstype=ext4 fsck.repair=yes rootwait quiet\n'
PROC_CMDLINE = ('coherent_pool=1M video=HDMI-A-1:1920x1080M@60D video=HDMI-A-2:1920x1080M@60 smsc95xx.macaddr=D8:3A:DD:00:00:00 '
                + CMDLINE.strip())
CONFIG = 'dtoverlay=vc4-kms-v3d\nmax_framebuffers=2\n\n[cm4]\notg_mode=1\n\n[all]\narm_boost=1\n'


def panel_edid(with_720=True):
    """A panel's EDID like the cheap ones: a 1920 x 1080 timing first, the real 1920 x 720 second."""
    import frogdash_screen as s
    edid = bytearray(s.build_edid(s.cvt_rb_1920x720()))
    edid[8:10] = bytes.fromhex('4c2d')   # Another maker
    dtd_1080 = bytes.fromhex('023a801871382d40582c4500c48e2100001e')
    edid[54:72] = dtd_1080
    edid[72:90] = bytes.fromhex('011d8018711c1620582c2500c48e2100009e') if not with_720 else \
        bytes([0x58, 0x22, 0x80, 0xA0, 0x70, 0xD0, 0x1E, 0x20, 0x30, 0x20, 0x35, 0x00, 0x24, 0x6E, 0x00, 0x00, 0x00, 0x1A])
    edid[127] = -sum(edid[:127]) % 256
    return bytes(edid)


class Pi:
    """A stand-in Pi: boot partition, /proc, /sys/class/drm, /lib/firmware and the dash's state."""
    def __init__(self, base, panel=None, model='Raspberry Pi 4 Model B Rev 1.5'):
        self.base = Path(base)
        self.boot, self.proc, self.drm, self.firmware, self.state = (self.base / n for n in ('boot', 'proc', 'drm', 'firmware', 'state'))
        for folder in (self.boot, self.proc / 'device-tree/chosen/bootloader', self.proc / 'sys/kernel/random', self.firmware, self.state):
            folder.mkdir(parents=True)
        (self.boot / 'config.txt').write_text(CONFIG)
        (self.boot / 'cmdline.txt').write_text(CMDLINE)
        (self.proc / 'cmdline').write_text(PROC_CMDLINE)
        (self.proc / 'device-tree/model').write_text(model + '\0')
        self.new_boot()
        port = self.drm / 'card1-HDMI-A-1'
        port.mkdir(parents=True)
        (port / 'status').write_text('connected\n')
        (port / 'edid').write_bytes(panel or b'')
        (port / 'modes').write_text('1920x1080\n1920x1080\n1280x720\n' if panel else '1920x1080\n1024x768\n800x600\n')
        (self.drm / 'card1-HDMI-A-2').mkdir()
        (self.drm / 'card1-HDMI-A-2/status').write_text('disconnected\n')
        self.reboots = []

    def new_boot(self, tryboot=False, cmdline=None):
        (self.proc / 'sys/kernel/random/boot_id').write_text(os.urandom(8).hex())
        (self.proc / 'device-tree/chosen/bootloader/tryboot').write_bytes((1 if tryboot else 0).to_bytes(4, 'big'))
        if cmdline:
            (self.proc / 'cmdline').write_text(cmdline)

    def load(self):
        os.environ.update(FROGDASH_BOOT=str(self.boot), FROGDASH_PROC=str(self.proc), FROGDASH_DRM=str(self.drm),
                          FROGDASH_FIRMWARE=str(self.firmware), FROGDASH_STATE=str(self.state))
        import frogdash_screen
        module = importlib.reload(frogdash_screen)
        module.subprocess.run = lambda args, **kw: (self.reboots.append(args) if args[0].endswith('reboot') else None) or type('R', (), {'stdout': '', 'returncode': 0})()
        return module

    def config(self):
        return (self.boot / 'config.txt').read_text()

    def status(self):
        return json.loads((self.state / 'screen-status.json').read_text())


class EdidTests(unittest.TestCase):
    def setUp(self):
        import frogdash_screen
        self.s = frogdash_screen

    def test_the_edid_offers_exactly_one_mode(self):
        s = self.s
        edid = s.build_edid(s.cvt_rb_1920x720())
        self.assertTrue(s.edid_ok(edid))
        self.assertEqual(len(edid), 256)
        modes = s.timings(edid)
        self.assertEqual([(t['h'], t['v']) for _, t in modes], [(1920, 720)])
        t = modes[0][1]
        self.assertAlmostEqual(t['clock_khz'] * 1000 / ((t['h'] + t['hblank']) * (t['v'] + t['vblank'])), 60, delta=.3)
        self.assertEqual(edid[35:38], b'\0\0\0')                 # No established timings
        self.assertEqual(edid[38:54], b'\x01\x01' * 8)            # No standard timings
        tags = [edid[o + 3] for o in (72, 90, 108)]
        self.assertNotIn(0xFD, tags)                              # No range limits: Linux would infer modes from one
        self.assertEqual(edid[24] & 1, 0)                         # No GTF either
        cea = edid[128:]
        self.assertEqual((cea[0], cea[1]), (2, 3))
        blocks, offset = [], 4
        while offset < cea[2]:
            blocks.append((cea[offset] >> 5, bytes(cea[offset + 1:offset + 1 + (cea[offset] & 31)])))
            offset += 1 + (cea[offset] & 31)
        kinds = [kind for kind, _ in blocks]
        self.assertNotIn(2, kinds)                                # No video data block: no other modes
        self.assertIn(1, kinds)                                   # Audio, so sound through the screen still works
        self.assertIn((3, bytes.fromhex('030c001000')), blocks)   # HDMI, not DVI
        self.assertTrue(cea[3] & 0x40)

    def test_the_panels_own_1920x720_timing_is_used_when_it_has_one(self):
        s = self.s
        panel = panel_edid()
        native = s.native_1920x720(panel)
        self.assertEqual(s.parse_dtd(native)['h'], 1920)
        self.assertEqual(s.parse_dtd(native)['clock_khz'], 87920)
        self.assertIsNone(s.native_1920x720(panel_edid(with_720=False)))
        self.assertIsNone(s.native_1920x720(b'garbage'))

    def test_boot_file_editing_is_reversible_and_repeatable(self):
        s = self.s
        once = s.with_block(CONFIG, 'boot', s.BOOT_CONFIG)
        self.assertEqual(s.with_block(once, 'boot', s.BOOT_CONFIG), once)
        self.assertTrue(once.rstrip().endswith('[all]\n# frogdash-boot end'))
        self.assertEqual(s.with_block(once, 'boot', None), CONFIG)
        self.assertEqual(s.forced_connectors(PROC_CMDLINE), ['HDMI-A-1'])
        line = s.screen_cmdline(CMDLINE, ['HDMI-A-1'])
        self.assertEqual(s.screen_cmdline(line, ['HDMI-A-1']), line)
        self.assertIn('drm.edid_firmware=edid/frogdash-1920x720.bin', line)
        self.assertIn('video=HDMI-A-1:1920x720@60D', line)
        self.assertEqual(s.plain_cmdline(line), CMDLINE)


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saved = dict(os.environ), list(sys.argv)

    def tearDown(self):
        subprocess.run = REAL_RUN
        os.environ.clear()
        os.environ.update(self.saved[0])
        sys.argv[:] = self.saved[1]
        self.folder.cleanup()

    def test_install_takes_out_the_boot_settings_that_turned_the_screen_red(self):
        pi = Pi(self.folder.name, panel=panel_edid())
        s = pi.load()
        with_block = s.with_block(CONFIG, 'boot', s.BOOT_CONFIG)
        (pi.boot / 'config.txt').write_text(with_block)
        self.assertEqual(s.install()[0], 'done')
        self.assertEqual(pi.config(), CONFIG)

    def test_install_puts_the_files_in_place_and_changes_no_screen_setting(self):
        pi = Pi(self.folder.name, panel=panel_edid())
        s = pi.load()
        self.assertEqual(s.install()[0], 'done')
        edid = (pi.firmware / 'edid/frogdash-1920x720.bin').read_bytes()
        self.assertEqual(edid, (pi.boot / 'frogdash-1920x720.bin').read_bytes())
        self.assertEqual(s.parse_dtd(edid[54:72])['clock_khz'], 87920)      # The panel's own timing
        self.assertNotIn('boot_delay', pi.config())                     # The panel needs the boot delay
        self.assertNotIn('edid', pi.config())                                # The mode only through a trial
        self.assertEqual((pi.boot / 'cmdline.txt').read_text(), CMDLINE)
        self.assertEqual(s.install(), ('ok', 'Ready: try exact 1920 x 720 under Dash management, Support'))
        survey = s.survey()
        self.assertEqual(survey['connectors'][0]['name'], 'HDMI-A-1')
        self.assertTrue(survey['connectors'][0]['panel_1920x720'])
        self.assertNotIn('D8:3A', survey['cmdline'])                         # The MAC address stays on the Pi

    def run_trial(self, pi, s):
        (pi.state / 'screen-request').write_text('trial')
        s.main_request = None
        sys.argv = ['frogdash_screen.py']
        s.main()
        self.assertEqual(pi.reboots[-1], ['/usr/sbin/reboot', '0 tryboot'])
        self.assertIn('[tryboot]\ncmdline=frogdash-cmdline-trial.txt', pi.config())
        tryboot = (pi.boot / 'tryboot.txt').read_text()            # Some firmware reads this instead
        self.assertIn('[all]\ncmdline=frogdash-cmdline-trial.txt\ndisable_fw_kms_setup=1', tryboot)
        self.assertIn('arm_boost=1', tryboot)                       # The rest of config.txt as it is
        self.assertEqual((pi.boot / 'cmdline.txt').read_text(), CMDLINE)        # The normal start is untouched
        trial = (pi.boot / 'frogdash-cmdline-trial.txt').read_text()
        pi.new_boot(tryboot=True, cmdline=trial)
        return pi.load()

    def test_a_trial_that_is_kept_becomes_the_normal_start(self):
        pi = Pi(self.folder.name)
        s = self.run_trial(pi, pi.load())
        asked = []

        def wait(seconds):
            if seconds == 45:
                return
            asked.append(pi.status()['state'])
            (pi.state / 'screen-request').write_text('keep')    # The driver presses KEEP
            sys.argv = ['frogdash_screen.py']
            s.main()
        s.after_start(wait=wait)
        self.assertEqual(asked, ['trial'])
        self.assertEqual(pi.status()['state'], 'kept')
        self.assertIn('drm.edid_firmware=edid/frogdash-1920x720.bin', (pi.boot / 'cmdline.txt').read_text())
        self.assertIn('video=HDMI-A-1:1920x720@60D', (pi.boot / 'cmdline.txt').read_text())   # Still forced on
        self.assertNotIn('[tryboot]', pi.config())
        self.assertFalse((pi.boot / 'tryboot.txt').exists())
        self.assertIn('# frogdash-screen begin\n[all]\ndisable_fw_kms_setup=1', pi.config())
        self.assertEqual(pi.reboots, [['/usr/sbin/reboot', '0 tryboot']])                   # No second restart
        # And back to the screen's own modes, with one restart.
        pi.new_boot(cmdline=(pi.boot / 'cmdline.txt').read_text())
        s = pi.load()
        (pi.state / 'screen-request').write_text('revert')
        s.main()
        self.assertEqual((pi.boot / 'cmdline.txt').read_text(), CMDLINE)
        self.assertNotIn('frogdash-screen', pi.config())
        self.assertEqual(pi.reboots[-1], ['/usr/sbin/reboot'])

    def test_no_answer_goes_back_by_itself(self):
        pi = Pi(self.folder.name)
        s = self.run_trial(pi, pi.load())
        clock = iter(range(0, 1000, 5))
        s.after_start(wait=lambda seconds: None, clock=lambda: next(clock))
        self.assertEqual(pi.reboots[-1], ['/usr/sbin/reboot'])
        self.assertEqual(pi.status()['state'], 'reverting')
        self.assertNotIn('tryboot', pi.config())
        self.assertFalse((pi.boot / 'tryboot.txt').exists())
        self.assertEqual((pi.boot / 'cmdline.txt').read_text(), CMDLINE)
        # The normal start after it says what happened.
        pi.new_boot(cmdline=PROC_CMDLINE)
        s = pi.load()
        s.after_start(wait=lambda seconds: None)
        self.assertEqual(pi.status()['state'], 'original')
        self.assertIn('was not kept', pi.status()['message'])

    def test_a_bootloader_without_trial_starts_changes_nothing(self):
        pi = Pi(self.folder.name)
        s = pi.load()
        (pi.state / 'screen-request').write_text('trial')
        sys.argv = ['frogdash_screen.py']
        s.main()
        pi.new_boot(tryboot=False, cmdline=PROC_CMDLINE)      # It started normally
        s = pi.load()
        s.after_start(wait=lambda seconds: None)
        self.assertEqual(pi.status()['state'], 'failed')
        self.assertNotIn('tryboot', pi.config())
        self.assertEqual(len(pi.reboots), 1)

    def test_a_tryboot_txt_that_is_not_ours_is_left_alone(self):
        pi = Pi(self.folder.name)
        (pi.boot / 'tryboot.txt').write_text('boot_partition=3\n')
        s = pi.load()
        s.request_trial()
        self.assertEqual(pi.status()['state'], 'failed')
        self.assertEqual((pi.boot / 'tryboot.txt').read_text(), 'boot_partition=3\n')
        self.assertEqual(pi.reboots, [])

    def test_keep_is_refused_outside_a_trial_and_old_pis_are_refused(self):
        pi = Pi(self.folder.name, model='Raspberry Pi 3 Model B Plus Rev 1.3')
        s = pi.load()
        s.request_keep()
        self.assertNotIn('frogdash-screen', pi.config())
        s.request_trial()
        self.assertEqual(pi.status()['state'], 'failed')
        self.assertEqual(pi.reboots, [])


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_dash_asks_and_shows_the_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State()
            state.paint = Paint(Path(folder) / 'appearance-paint.json')
            async with TestClient(TestServer(create_app(state))) as client:
                self.assertEqual((await (await client.get('/screen')).json())['state'], 'idle')
                self.assertEqual((await client.post('/screen', json={'action': 'trial'})).status, 200)
                self.assertEqual((Path(folder) / 'screen-request').read_text(), 'trial')
                self.assertTrue((await (await client.get('/screen')).json())['pending'])
                self.assertEqual((await client.post('/screen', json={'action': 'rm -rf'})).status, 400)
                (Path(folder) / 'screen-status.json').write_text(json.dumps(
                    {'state': 'trial', 'message': 'Trying', 'started': 5, 'deadline_s': 90, 'cmdline': 'secret', 'connectors': []}))
                body = await (await client.get('/screen')).json()
                self.assertEqual((body['state'], body['deadline_s']), ('trial', 90))
                self.assertNotIn('cmdline', body)          # The full survey is only in the diagnostics download
                state.ingest(0x5E8, bytes.fromhex('07080D7A080201F4'))
                state.gps = GPS(transmit=False)
                state.gps.connected = True
                state.gps.update({'class': 'TPV', 'mode': 3, 'speed': 20})
                self.assertEqual((await client.post('/screen', json={'action': 'revert'})).status, 409)   # Moving
                self.assertEqual((await client.post('/screen', json={'action': 'keep'})).status, 200)     # KEEP always works


if __name__ == '__main__':
    unittest.main()
