"""Gateway firmware over CAN: the dash's sender against the module's real receiver code.

The receiver is the shared header compiled for this computer (tests/firmware_receiver_harness.cpp),
so both ends of the protocol are exercised together, including lost frames and answers,
a module that goes back to its old firmware, and one that never comes back.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

from hardware.frogdash import fwupdate
from hardware.frogdash.fwupdate import ModuleFirmware, crc16, data_frames, load_image
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]
COMPILER = shutil.which('g++') or shutil.which('clang++')
OLD, NEW = '0a0b0c0d', '1a2b3c4d'
_harness = {}


def harness():
    if 'exe' not in _harness:
        folder = Path(tempfile.mkdtemp())
        exe = folder / 'receiver.exe'
        done = subprocess.run([COMPILER, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'hardware/can_contract/include'),
                               str(ROOT / 'tests/firmware_receiver_harness.cpp'), '-o', str(exe)], capture_output=True, text=True)
        if done.returncode:
            raise AssertionError(done.stderr)
        _harness['exe'] = exe
    return _harness['exe']


class Module:
    """The gateway on the bus: the real receiver in a child process, restarted as it would restart."""
    def __init__(self, test, build=OLD, out=None, **options):
        self.test, self.out, self.options = test, out, options
        self.process = None
        self.sent = []                 # Every frame the dash put on the bus
        self.lose_frames = set()       # Indexes into `sent` that never arrive
        self.lose_replies = set()      # Reply counts that never reach the dash
        self.replies = 0
        self.after_restart = NEW       # Build that answers after a restart; None = silent; OLD = went back
        self.restarts = 0
        self.silent = False
        self.boot(build, trial=False)

    def boot(self, build, trial):
        self.stop()
        args = [str(harness()), '--build', build]
        if trial:
            args.append('--trial')
        if self.out:
            args += ['--out', str(self.out)]
        for name, value in self.options.items():
            args += [f'--{name.replace("_", "-")}'] + ([] if value is True else [str(value)])
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def stop(self):
        if self.process:
            self.process.stdin.close()
            self.process.wait(5)
            self.process.stdout.close()
            self.process = None

    def line(self, text):
        self.process.stdin.write(text + '\n')
        self.process.stdin.flush()
        return self.process.stdout.readline().strip()

    async def sender(self, identifier, data):
        self.test.assertEqual((identifier, len(data)), (fwupdate.ID_COMMAND, 8))
        index = len(self.sent)
        self.sent.append(bytes(data))
        if self.silent or index in self.lose_frames:
            return
        answer = self.line('F ' + bytes(data).hex())
        if not answer.startswith('R '):
            return
        _, payload, action = answer.split()
        self.replies += 1
        if self.replies not in self.lose_replies:
            self.test.firmware.observe(bytes.fromhex(payload))
        if action == 'RESTART':
            self.restarts += 1
            if self.after_restart is None:
                self.silent = True
            else:
                self.boot(self.after_restart, trial=self.after_restart == NEW)


@unittest.skipUnless(COMPILER, 'C++ compiler required to run the real receiver')
class FirmwareUpdateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.image = random.Random(7).randbytes(448 * 9 + 201)         # Nine full blocks and a part block
        self.publish(self.image, NEW)
        self.now = 0.0
        self.state = State('socketcan', clock=lambda: self.now)
        self.state.connected = True
        self.firmware = ModuleFirmware(self.state, self.folder, sleep=self.sleep)
        self.state.firmware = self.firmware
        self.module = Module(self, out=self.folder / 'received.bin')
        self.state.controls.attach(self.module.sender)
        self.addCleanup(lambda: self.module.stop())   # Whichever module the test ended with.
        self.addCleanup(self.temp.cleanup)

    async def sleep(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)

    def publish(self, image, build):
        (self.folder / 'gateway.bin').write_bytes(image)
        (self.folder / 'gateway.json').write_text(json.dumps(
            {'build': build, 'size': len(image), 'sha256': hashlib.sha256(image).hexdigest(), 'commit': build + '0' * 32}))

    async def install(self, timeout=30):
        error = self.firmware.start()
        self.assertIsNone(error)
        await asyncio.wait_for(self.firmware.task, timeout)
        return self.firmware.job

    async def test_the_whole_image_arrives_is_checked_restarted_into_and_confirmed(self):
        await self.firmware.query()
        shown = self.firmware.snapshot()
        self.assertEqual((shown['installed'], shown['available'], shown['new'], shown['can_install']), (OLD, NEW, True, True))
        job = await self.install()
        self.assertEqual((job['state'], job['message'], job['progress']), ('done', f'Gateway updated to build {NEW}', 1.0))
        self.assertEqual((self.folder / 'received.bin').read_bytes(), self.image)   # Byte for byte what was published.
        self.assertEqual(self.module.restarts, 1)
        shown = self.firmware.snapshot()
        self.assertEqual((shown['installed'], shown['new'], shown['on_trial'], shown['note']), (NEW, False, False, 'Up to date'))
        self.assertEqual(self.module.line('F ' + fwupdate.command(fwupdate.QUERY, 1).hex()).split()[1][12:14], '00')   # No longer on trial.
        # Data frames carry seven bytes each, two at a time with a pause between.
        self.assertEqual(len(data_frames(self.image[:448])), 64)
        self.assertEqual(crc16(b'123456789'), 0x29B1)

    async def test_lost_frames_and_lost_answers_only_cost_a_repeat(self):
        self.module.lose_frames = {7, 150, 151, 400}          # Data frames that never arrive
        self.module.lose_replies = {4, 9}                     # Answers that never reach the dash
        original = fwupdate.ModuleFirmware.expect
        async def quick(firmware, match, timeout):            # Do not sit out real 1.5 s waits for the lost answers.
            return await original(firmware, match, min(timeout, .05))
        fwupdate.ModuleFirmware.expect = quick
        try:
            job = await self.install()
        finally:
            fwupdate.ModuleFirmware.expect = original
        self.assertEqual(job['state'], 'done', job)
        self.assertEqual((self.folder / 'received.bin').read_bytes(), self.image)
        self.assertEqual((self.firmware.burst, self.firmware.gap > .001), (1, True))   # It slowed down after the misses.

    async def test_a_module_that_goes_back_to_its_old_firmware_is_reported(self):
        self.module.after_restart = OLD                       # The new image did not start: the bootloader went back.
        job = await self.install()
        self.assertEqual(job['state'], 'failed')
        self.assertIn(f'went back to its previous firmware (build {OLD})', job['message'])
        self.assertNotIn(bytes([fwupdate.CONFIRM, 1]), [frame[:2] for frame in self.module.sent])   # Never confirmed.
        self.assertTrue(self.firmware.snapshot()['can_install'])   # And it can be tried again.

    async def test_a_module_that_never_comes_back_is_not_confirmed(self):
        self.module.after_restart = None
        original = fwupdate.ModuleFirmware.expect
        async def quick(firmware, match, timeout):
            return await original(firmware, match, min(timeout, .01))
        fwupdate.ModuleFirmware.expect = quick
        try:
            job = await self.install()
        finally:
            fwupdate.ModuleFirmware.expect = original
        self.assertEqual(job['state'], 'failed')
        self.assertIn('returns to its previous firmware by itself', job['message'])
        self.assertNotIn(bytes([fwupdate.CONFIRM, 1]), [frame[:2] for frame in self.module.sent])

    async def test_refusals_leave_the_running_firmware_alone(self):
        # Too big for the module's slot.
        self.module.stop()
        self.module = Module(self, capacity=1000)
        self.state.controls.attach(self.module.sender)
        job = await self.install()
        self.assertEqual((job['state'], job['message']), ('failed', 'The gateway has no room for it'))
        self.assertEqual(self.module.restarts, 0)
        # The image fails the module's own check at the end.
        self.module.stop()
        self.module = Module(self, fail_finish=True)
        self.state.controls.attach(self.module.sender)
        job = await self.install()
        self.assertEqual(job['state'], 'failed')
        self.assertIn('found the image damaged: its old firmware is still running', job['message'])
        self.assertEqual(self.module.restarts, 0)

    async def test_nothing_is_sent_when_it_should_not_be(self):
        self.state.connected = False
        self.assertEqual(self.firmware.start(), 'CAN is disconnected')
        self.state.connected = True
        (self.folder / 'gateway.bin').write_bytes(self.image + b'x')              # Damaged download.
        self.assertIn('damaged', self.firmware.start())
        self.assertIsNone(load_image(self.folder, 'gateway')[0])
        self.publish(self.image, NEW)
        # Moving: refused, and nothing reaches the bus.
        self.state.samples['vehicle.speed_kph', 0x203] = dict(value=40, quality='live', seen=self.now, source_id=0x203, timestamp_ms=0)
        self.assertIn('Stop the car first', self.firmware.start())
        self.assertEqual(self.module.sent, [])
        # An old firmware without the receiver never answers: said plainly, nothing started.
        del self.state.samples['vehicle.speed_kph', 0x203]
        self.module.silent = True
        job = await self.install()
        self.assertEqual(job['state'], 'failed')
        self.assertIn('flash it once by USB', job['message'])
        self.assertEqual({frame[0] for frame in self.module.sent}, {fwupdate.QUERY, fwupdate.ABORT})
        self.assertIn('not answering', self.firmware.snapshot()['note'])

    async def test_driving_off_mid_transfer_stops_it_and_the_module_carries_on(self):
        original = self.firmware.block
        async def block(number, chunk):
            await original(number, chunk)
            if number == 2:                                   # The car starts rolling after the third block.
                self.state.samples['vehicle.speed_kph', 0x203] = dict(value=30, quality='live', seen=self.now, source_id=0x203, timestamp_ms=0)
        self.firmware.block = block
        job = await self.install()
        self.assertEqual(job['state'], 'failed')
        self.assertIn('started moving', job['message'])
        self.assertEqual(self.module.sent[-1][:2], bytes([fwupdate.ABORT, 1]))
        self.assertEqual(self.module.restarts, 0)
        self.assertEqual(self.module.line('F ' + fwupdate.command(fwupdate.QUERY, 1).hex()).split()[1][12:14], '00')   # Not updating any more.

    async def test_the_dash_asks_which_build_is_running_and_routes_serve_it(self):
        from aiohttp.test_utils import TestClient, TestServer
        from hardware.frogdash.server import create_app
        self.state.ingest(fwupdate.ID_REPLY, bytes.fromhex('01 01 0a0b0c0d 01 01'.replace(' ', '')))
        self.assertEqual(self.state.snapshot()['firmware']['gateway']['installed'], OLD)
        self.assertTrue(self.state.snapshot()['firmware']['gateway']['on_trial'])
        self.state.ingest(fwupdate.ID_REPLY, bytes.fromhex('0102' + '00' * 6))              # Another module's answer: not ours.
        self.assertEqual(self.firmware.installed, OLD)
        async with TestClient(TestServer(create_app(self.state))) as client:
            shown = await (await client.get('/firmware')).json()
            self.assertEqual((shown['gateway']['installed'], shown['gateway']['available']), (OLD, NEW))
            self.assertEqual((await client.post('/firmware', json={'module': 'nano', 'action': 'install'})).status, 400)
            self.assertEqual((await client.post('/firmware', json={'module': 'gateway', 'action': 'erase'})).status, 400)
            response = await client.post('/firmware', json={'module': 'gateway', 'action': 'install'})
            self.assertEqual(response.status, 200)
            await asyncio.wait_for(self.firmware.task, 30)
            shown = await (await client.get('/firmware')).json()
            self.assertEqual(shown['gateway']['job']['state'], 'done')


if __name__ == '__main__':
    unittest.main()
