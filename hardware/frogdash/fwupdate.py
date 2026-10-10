"""New firmware for the car's modules, sent over the CAN bus (can_contract/firmware_update.h).

The dash sends the image in blocks of 64 frames, waits for the module to accept each
block, and repeats a block the module asks for again. The module checks the whole image
before restarting into it, and keeps it only when the dash then confirms it is talking
to the new build: otherwise the module goes back to the firmware it had.

The image and its manifest are downloaded by the Pi setup during Update now
(tools/frogdash_setup.sh) into <data>/firmware/. Nothing is sent while the car is moving.

Adding a module: give it the next target number in firmware_update.h and use the
header's Receiver in its firmware; add a row to MODULES below and a line to the Pi
setup's download list. The screens, the phone page and System check follow the table.
"""
import asyncio
import hashlib
import json
import zlib

from .parking import rolling

ID_COMMAND, ID_REPLY = 0x680, 0x681
QUERY, BEGIN, BLOCK_END, END, ABORT, CONFIRM = 0x80, 0x81, 0x82, 0x83, 0x84, 0x85
INFO, ACK = 1, 2
OK, RESEND, BUSY = 0, 1, 7
STATUS = {0: 'accepted', 1: 'asked for the block again', 2: 'was not expecting it', 3: 'has no room for it',
          4: 'could not write its flash', 5: 'found the image damaged', 6: 'is running a different build',
          7: 'is in use and will not update now'}
ON_TRIAL, UPDATING = 1, 2
BLOCK_BYTES, FRAMES_PER_BLOCK = 448, 64
TARGET_GATEWAY = 1
# name (file and API name), label (in sentences), title (on buttons), target, and what to tell the driver first.
MODULES = (
    ('gateway', 'Gateway', 'Gateway firmware', 1,
     'Speed, fuel, wheel buttons and interior lights pause for about a minute.'),
    ('taillights', 'Taillight controller', 'Taillight firmware', 2,
     'Lights off and foot off the brake: the taillights stay dark for a few minutes, and any light switched on stops the update.'),
)
MAX_IMAGE = 0x330000
QUERY_EVERY_S = 20
BLOCK_TRIES = 8


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE, as the module computes it over each block."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1) & 0xFFFF
    return crc


def command(op, target, payload=b''):
    return (bytes([op, target]) + payload).ljust(8, b'\x00')


def data_frames(chunk):
    return [bytes([index]) + chunk[offset:offset + 7].ljust(7, b'\xff')
            for index, offset in enumerate(range(0, len(chunk), 7))]


def load_image(folder, name):
    """(manifest, bytes) for a downloaded image that matches its manifest, else (None, reason)."""
    try:
        manifest = json.loads((folder / f'{name}.json').read_text(encoding='utf-8'))
        data = (folder / f'{name}.bin').read_bytes()
        build = int(manifest['build'], 16)
    except (OSError, ValueError, KeyError, TypeError):
        return None, 'No firmware file yet: press Update now with Wi-Fi connected'
    if not 0 < len(data) <= MAX_IMAGE or len(data) != manifest.get('size') or hashlib.sha256(data).hexdigest() != manifest.get('sha256'):
        return None, 'The firmware file is damaged: press Update now to download it again'
    if not 0 < build <= 0xFFFFFFFF:
        return None, 'The firmware file has no build number'
    return {**manifest, 'build': f'{build:08x}'}, data


class Failure(Exception):
    pass


class ModuleFirmware:
    """One module's firmware: what it runs, what is available, and installing it."""

    def __init__(self, state, folder, name='gateway', label='Gateway', target=TARGET_GATEWAY, sleep=asyncio.sleep,
                 title=None, warning=''):
        self.state, self.folder, self.name, self.label, self.target, self.sleep = state, folder, name, label, target, sleep
        self.title, self.warning = title or f'{label} firmware', warning
        self.blocked = lambda: False   # Set by Firmware: another module is being updated.
        self.installed = None        # Build the module reports, as 8 hex digits
        self.flags = 0
        self.heard = None            # When it last answered
        self.replies = asyncio.Queue()
        self.job = {'state': 'idle', 'message': '', 'progress': 0.0}
        self.task = None
        self.burst, self.gap = 2, .001
        self._image = (None, None, 'Firmware updates are not available here')   # (files' fingerprint, manifest, data or reason)
        self._looked = None

    # ---- what the dash knows ----
    def observe(self, data):
        if len(data) != 8 or data[1] != self.target or data[0] not in (INFO, ACK):
            return
        if data[0] == INFO:
            self.installed, self.flags, self.heard = data[2:6].hex(), data[6], self.state.clock()
        if self.busy():
            self.replies.put_nowait(bytes(data))

    def busy(self):
        return self.job['state'] == 'running'

    def available(self, fresh=False):
        """(manifest, image bytes), or (None, why not). The files are hashed only when they change."""
        if not self.folder:
            return None, 'Firmware updates are not available here'
        now = self.state.clock()
        if fresh or self._looked is None or now - self._looked >= 5:
            self._looked = now
            try:
                seen = tuple((stat.st_mtime_ns, stat.st_size) for stat in
                             ((self.folder / f'{self.name}.{kind}').stat() for kind in ('json', 'bin')))
            except OSError:
                seen = ()
            if seen != self._image[0]:
                self._image = (seen, *load_image(self.folder, self.name))
        return self._image[1], self._image[2]

    def snapshot(self):
        manifest, reason = self.available()
        answered = self.heard is not None and self.state.clock() - self.heard < 3 * QUERY_EVERY_S
        new = bool(manifest) and answered and manifest['build'] != self.installed
        if not answered:
            note = f'The {self.label.lower()} is not answering. Firmware from before this feature must be replaced once by USB'
            short = 'not answering'
        elif not manifest:
            note, short = reason, f'build {self.installed}, no newer file on the Pi'
        elif new:
            note, short = f'Build {manifest["build"]} is ready to install', f'build {self.installed}, {manifest["build"]} ready to install'
        else:
            note, short = 'Up to date', f'build {self.installed}, up to date'
        return {'name': self.name, 'label': self.label, 'title': self.title, 'warning': self.warning,
                'installed': self.installed if answered else None,
                'on_trial': bool(answered and self.flags & ON_TRIAL), 'available': manifest['build'] if manifest else None,
                'can_install': bool(manifest) and answered and not self.busy() and not self.blocked(),
                'new': new, 'note': note, 'short': short, 'job': dict(self.job)}

    # ---- talking to the module ----
    async def send(self, payload):
        sender = self.state.controls.sender
        if not sender or not self.state.connected:
            raise Failure('CAN is disconnected')
        try:
            await sender(ID_COMMAND, payload)
        except OSError as exc:
            raise Failure(f'CAN send failed: {exc or "timeout"}') from None

    async def expect(self, match, timeout):
        """The first reply that `match` accepts within the time, else None."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                reply = await asyncio.wait_for(self.replies.get(), remaining)
            except TimeoutError:
                return None
            if match(reply):
                return reply

    async def ask(self, payload, match, timeout, tries=3):
        for _ in range(tries):
            await self.send(payload)
            reply = await self.expect(match, timeout)
            if reply:
                return reply
        return None

    def progress(self, message, fraction=None):
        self.job = {'state': 'running', 'message': message, 'progress': self.job['progress'] if fraction is None else round(fraction, 3)}

    async def query(self):
        """Ask which build is running. Quiet when nothing can be sent."""
        if self.busy() or not self.state.controls.sender or not self.state.connected:
            return
        try:
            await self.state.controls.sender(ID_COMMAND, command(QUERY, self.target))
        except OSError:
            pass

    async def run(self):
        await self.sleep(5)
        while True:
            await self.query()
            await self.sleep(QUERY_EVERY_S)

    # ---- installing ----
    def start(self):
        """Begin installing the downloaded image. Returns an error text, or None when started."""
        if self.busy() or self.blocked():
            return 'An update is already running'
        if self.state.mode != 'socketcan' or not self.state.connected or not self.state.controls.sender:
            return 'CAN is disconnected'
        if rolling(self.state):
            return 'Stop the car first: the module does nothing else while it is being updated'
        manifest, data = self.available(fresh=True)
        if not manifest:
            return data
        while not self.replies.empty():
            self.replies.get_nowait()
        self.job = {'state': 'running', 'message': 'Starting', 'progress': 0.0}
        self.task = asyncio.create_task(self.install(manifest, data))
        return None

    async def install(self, manifest, data):
        target, build = self.target, manifest['build']
        info = lambda reply: reply[0] == INFO
        ack = lambda op: (lambda reply: reply[0] == ACK and reply[2] == op)
        try:
            if not await self.ask(command(QUERY, target), info, 1.0):
                raise Failure(f'The {self.label.lower()} did not answer. Its firmware may be from before this feature: flash it once by USB')
            reply = await self.ask(command(BEGIN, target, len(data).to_bytes(3, 'big') + b'FW'), ack(BEGIN), 6.0, tries=2)
            if not reply:
                raise Failure(f'The {self.label.lower()} did not accept the update')
            if reply[3] == BUSY:
                raise Failure(f'The {self.label.lower()} is in use and did not start the update. {self.warning}')
            if reply[3] != OK:
                raise Failure(f'The {self.label.lower()} {STATUS.get(reply[3], "refused")}')
            blocks = -(-len(data) // BLOCK_BYTES)
            for number in range(blocks):
                if rolling(self.state):
                    raise Failure('The car started moving: update stopped, the old firmware is still running')
                await self.block(number, data[number * BLOCK_BYTES:(number + 1) * BLOCK_BYTES])
                self.progress(f'Sending: {min(len(data), (number + 1) * BLOCK_BYTES) // 1024} of {len(data) // 1024} KB', (number + 1) / blocks * .9)
            self.progress('Checking the firmware', .92)
            reply = await self.ask(command(END, target, zlib.crc32(data).to_bytes(4, 'big')), ack(END), 20.0, tries=1)
            if not reply:
                raise Failure(f'The {self.label.lower()} did not answer after the transfer: its old firmware is still in place')
            if reply[3] != OK:
                raise Failure(f'The {self.label.lower()} {STATUS.get(reply[3], "refused the image")}: its old firmware is still running')
            # It restarts into the new image, on trial. Confirm it only once it answers as that build.
            self.progress(f'The {self.label.lower()} is restarting', .95)
            await self.sleep(1.5)
            running, other = None, 0
            for _ in range(40):
                reply = await self.ask(command(QUERY, target), info, 1.0, tries=1)
                if reply:
                    running = reply[2:6].hex()
                    if running == build:
                        break
                    other += 1
                    if other >= 5:   # Keeps answering as another build: the new one did not start.
                        raise Failure(f'The {self.label.lower()} went back to its previous firmware (build {running}): the new one did not start')
                    await self.sleep(1.0)
            if running != build:
                raise Failure(f'The {self.label.lower()} did not come back. If it stays silent it returns to its previous firmware by itself within two minutes')
            reply = await self.ask(command(CONFIRM, target, bytes.fromhex(build)), ack(CONFIRM), 1.0, tries=5)
            if not reply or reply[3] != OK:
                raise Failure(f'The {self.label.lower()} is running build {build} but did not take the confirmation; it will return to its previous firmware')
            self.flags &= ~ON_TRIAL   # Confirmed: it keeps this firmware.
            self.job = {'state': 'done', 'message': f'{self.label} updated to build {build}', 'progress': 1.0}
        except Failure as failure:
            self.job = {'state': 'failed', 'message': str(failure), 'progress': self.job['progress']}
            try:   # Tell the module to drop a transfer that is still open. Harmless otherwise.
                await self.state.controls.sender(ID_COMMAND, command(ABORT, target))
            except (OSError, TypeError):
                pass
        except asyncio.CancelledError:
            self.job = {'state': 'failed', 'message': 'Update stopped: the dash is shutting down', 'progress': self.job['progress']}
            raise

    async def block(self, number, chunk):
        frames = data_frames(chunk)
        end = command(BLOCK_END, self.target, number.to_bytes(2, 'big') + crc16(chunk).to_bytes(2, 'big') + bytes([len(frames)]))
        # An answer to this block, or the module calling the whole transfer off because it is needed.
        answered = lambda reply: reply[0] == ACK and (reply[3] == BUSY or (
            reply[2] == BLOCK_END and (reply[3] != OK or reply[4:6] == number.to_bytes(2, 'big'))))
        for _ in range(BLOCK_TRIES):
            # The module reads the bus with two buffers: a couple of frames, then a pause.
            for index, frame in enumerate(frames, 1):
                await self.send(frame)
                if index % self.burst == 0:
                    await self.sleep(self.gap)
            await self.send(end)
            reply = await self.expect(answered, 1.5)
            if reply is None:
                continue                      # Our frames or its answer were lost: the block is sent again.
            if reply[3] == BUSY:
                raise Failure(f'The {self.label.lower()} stopped the update because it was needed; its old firmware is still running. {self.warning}')
            if reply[3] == OK:
                return
            if reply[3] == RESEND:            # It missed frames: go slower from here on.
                self.burst, self.gap = 1, min(self.gap * 2, .008)
                continue
            raise Failure(f'The {self.label.lower()} {STATUS.get(reply[3], "refused a block")} (block {number})')
        raise Failure(f'Block {number} could not be delivered: check the CAN wiring')


class Firmware:
    """Every module that takes firmware over CAN. One update at a time."""

    def __init__(self, state, folder, sleep=asyncio.sleep, modules=MODULES):
        self.sleep = sleep
        self.modules = {name: ModuleFirmware(state, folder, name, label, target, sleep, title, warning)
                        for name, label, title, target, warning in modules}
        for module in self.modules.values():
            module.blocked = lambda module=module: any(other.busy() for other in self.modules.values() if other is not module)

    def observe(self, data):
        for module in self.modules.values():   # Each takes only the answers that name it.
            module.observe(data)

    def busy(self):
        return any(module.busy() for module in self.modules.values())

    def snapshot(self):
        return {name: module.snapshot() for name, module in self.modules.items()}

    def start(self, name):
        module = self.modules.get(name) if isinstance(name, str) else None
        return module.start() if module else 'Unknown module'

    async def run(self):
        await self.sleep(5)
        while True:
            for module in self.modules.values():
                if not self.busy():
                    await module.query()
                    await self.sleep(.3)
            await self.sleep(QUERY_EVERY_S)
