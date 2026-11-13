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
QUERY, BEGIN, BLOCK_END, END, ABORT, CONFIRM, RESTART = 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86
INFO, ACK = 1, 2
OK, RESEND, BUSY = 0, 1, 7
STATUS = {0: 'accepted', 1: 'asked for the block again', 2: 'was not expecting it', 3: 'has no room for it',
          4: 'could not write its flash', 5: 'found the image damaged', 6: 'is running a different build',
          7: 'is in use and will not update now'}
ON_TRIAL, UPDATING = 1, 2
BLOCK_BYTES, FRAMES_PER_BLOCK = 448, 64
TARGET_GATEWAY = 1
# name (file and API name), label (in sentences), title (on buttons), target, what to tell the driver first,
# and optionally what silence means for this module when that is not simply "old firmware".
MODULES = (
    ('gateway', 'Gateway', 'Gateway firmware', 1,
     'Speed, fuel, wheel buttons and interior lights pause for about a minute.'),
    ('taillights', 'Taillight controller', 'Taillight firmware', 2,
     'Lights off and foot off the brake: the taillights stay dark for a few minutes, and any light switched on stops the update.'),
    # Only the ESP32 water/meth board answers. The Arduino Nano board it replaces cannot
    # take firmware over CAN, and says nothing here: that is not a fault. Which board is
    # fitted is known from its own setting reports (Firmware.meth_board, METH_SILENT).
    ('watermeth', 'Water/meth controller', 'Water/meth firmware', 3,
     'Engine off: injection is off for about a minute, and the controller stops the update if boost comes up.',
     ('not answering',
      "Not answering. Check the ESP32 board's power and CAN wiring (the Nano board never answers here; it is updated by USB)")),
)
# What the water/meth controller's silence means, by the board its setting reports say is
# fitted (None: not heard, or not reported yet). Since November 2026 the ESP32 board is the
# one in the car, so its silence is a fault to show, not the Nano's normal.
METH_SILENT = {
    'nano': ('no answer (normal with the Nano board)',
             'No answer. That is normal with the Nano board, which is updated by USB; the ESP32 board answers here once it is fitted'),
    'esp32': ('ESP32 board not answering firmware commands',
              'The ESP32 board is on the bus but does not answer firmware commands, so it cannot be updated from here. '
              'Flash esp32s3_water_meth to it once by USB'),
}
MAX_IMAGE = 0x330000
QUERY_EVERY_S = 20
BLOCK_TRIES = 8
# How fast a block goes out: (frames back to back, pause after them). Each module reads the
# bus through an MCP2515 with two receive buffers, so too many in a row can be lost. The
# pace drops a step when the module misses frames and climbs back after clean blocks; a
# pace that failed is tried again only after twice as many clean blocks. (It used to drop
# for good: one missed frame left the rest of the update, and every later one until the
# dash restarted, at one frame per 8 ms, about ten times slower.)
PACES = ((4, .001), (2, .001), (1, .001), (1, .002), (1, .004), (1, .008))
START_PACE, CLEAN_TO_SPEED_UP = 1, 16
# At most this many clean blocks before trying a faster pace again. It was 256: after a few
# misses the taillight update (2,300 blocks) sat at the slowest pace, 0.6 KB/s and 30 minutes
# for 1 MB (November 2026). A pace that is too fast costs one block now and then; one that is
# too slow costs every block.
MOST_CLEAN_TO_SPEED_UP = 32
# A block end with no answer: asked again (one frame) after this long, before all 64 frames
# go out again. The module answers a block it already has with OK, so a lost answer costs a
# frame, not a block; a module still writing its flash gets the longer second wait.
FIRST_ANSWER_S, SECOND_ANSWER_S = .4, 1.5


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


def duration(seconds):
    seconds = round(seconds)
    return f'{seconds // 60} min {seconds % 60} s' if seconds >= 60 else f'{seconds} s'


def pace_text(sent, total, elapsed):
    """' · 9.5 KB/s · about 2 min left', once there is enough to tell."""
    if elapsed < 3 or sent <= 0:
        return ''
    rate = sent / elapsed
    return f' · {rate / 1024:.1f} KB/s · about {duration((total - sent) / rate)} left'


class Failure(Exception):
    pass


class ModuleFirmware:
    """One module's firmware: what it runs, what is available, and installing it."""

    def __init__(self, state, folder, name='gateway', label='Gateway', target=TARGET_GATEWAY, sleep=asyncio.sleep,
                 title=None, warning='', silent=None):
        self.state, self.folder, self.name, self.label, self.target, self.sleep = state, folder, name, label, target, sleep
        self.title, self.warning = title or f'{label} firmware', warning
        # (short, note) shown while the module does not answer.
        self.silent = silent or ('not answering', f'The {label.lower()} is not answering. '
                                 'Firmware from before this feature must be replaced once by USB')
        # What an install attempt says when it gets no answer.
        self.no_answer = (f'The {label.lower()}: {silent[1][0].lower()}{silent[1][1:]}' if silent else
                          f'The {label.lower()} did not answer. Its firmware may be from before this feature: flash it once by USB')
        self.blocked = lambda: False   # Set by Firmware: another module is being updated.
        self.installed = None        # Build the module reports, as 8 hex digits
        self.flags = 0
        self.heard = None            # When it last answered
        self.replies = asyncio.Queue()
        self.job = {'state': 'idle', 'message': '', 'progress': 0.0}
        self.task = None
        self.took = None             # Seconds the last transfer took
        self.pace, self.clean, self.need = START_PACE, 0, CLEAN_TO_SPEED_UP
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

    @property
    def burst(self):
        return PACES[self.pace][0]

    @property
    def gap(self):
        return PACES[self.pace][1]

    def slower(self):
        self.pace, self.clean = min(self.pace + 1, len(PACES) - 1), 0
        self.need = min(self.need * 2, MOST_CLEAN_TO_SPEED_UP)

    def trouble(self):
        """For the event log: what slowed a transfer down, so a report shows where the time went."""
        missed = {k: v for k, v in getattr(self, 'missed', {}).items() if v}
        if not missed:
            return ''
        return ' · ' + ', '.join(f'{v} block{"s" if v != 1 else ""} {k}' for k, v in missed.items()) +             f' · ended at {PACES[self.pace][0]} frame(s) per {PACES[self.pace][1] * 1000:g} ms'

    def log(self, level, text):
        if self.state.eventlog:
            self.state.eventlog.write(level, 'firmware', text)

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
            short, note = self.silent
        elif not manifest:
            note, short = reason, f'build {self.installed}, no newer file on the Pi'
        elif new:
            note, short = f'Build {manifest["build"]} is ready to install', f'build {self.installed}, {manifest["build"]} ready to install'
        else:
            note, short = 'Up to date', f'build {self.installed}, up to date'
        return {'name': self.name, 'label': self.label, 'title': self.title, 'warning': self.warning,
                'installed': self.installed if answered else None,
                'can_restart': answered and not self.busy() and not self.blocked(),
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
        except TimeoutError:
            raise Failure('CAN send failed: the bus took no frames for half a second (is another module connected and on?)') from None
        except OSError as exc:
            raise Failure(f'CAN send failed: {exc}') from None

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

    # ---- restarting (CAN extension 7) ----
    def start_restart(self):
        """Ask the module to restart. Returns an error text, or None when asked."""
        if self.busy() or self.blocked():
            return 'A module is being updated or restarted'
        if self.state.mode != 'socketcan' or not self.state.connected or not self.state.controls.sender:
            return 'CAN is disconnected'
        if rolling(self.state):
            return 'Stop the car first: a module is out of action for a moment while it restarts'
        while not self.replies.empty():
            self.replies.get_nowait()
        self.job = {'state': 'running', 'kind': 'restart', 'message': f'Asking the {self.label.lower()} to restart', 'progress': 0.0}
        self.task = asyncio.create_task(self.restart())
        return None

    async def restart(self):
        label = self.label.lower()
        try:
            reply = await self.ask(command(RESTART, self.target), lambda r: r[0] == ACK and r[2] == RESTART, 1.0, tries=2)
            if not reply:
                raise Failure(f'The {label} did not answer: its firmware is from before restarting over CAN. Install the current one first')
            if reply[3] == BUSY:
                raise Failure(f'The {label} is in use and did not restart (a light is on, or it is injecting). Try again parked, lights off')
            if reply[3] != OK:
                raise Failure(f'The {label} {STATUS.get(reply[3], "refused")}')
            self.job = {**self.job, 'message': f'The {label} is restarting', 'progress': .5}
            await self.sleep(1.0)
            for _ in range(20):
                reply = await self.ask(command(QUERY, self.target), lambda r: r[0] == INFO, 1.0, tries=1)
                if reply:
                    self.installed, self.flags, self.heard = reply[2:6].hex(), reply[6], self.state.clock()
                    self.job = {'state': 'done', 'kind': 'restart', 'message': f'{self.label} restarted and answering again', 'progress': 1.0}
                    return
                await self.sleep(.5)
            raise Failure(f'The {label} restarted but has not answered since. If it stays silent, turn the key off and on')
        except Failure as failure:
            self.job = {'state': 'failed', 'kind': 'restart', 'message': str(failure), 'progress': 0.0}
        except asyncio.CancelledError:
            self.job = {'state': 'failed', 'kind': 'restart', 'message': 'Stopped: the dash is shutting down', 'progress': 0.0}
            raise

    async def restart_nano(self):
        """The Nano water/meth board takes no firmware commands: its own restart command on
        0x301 instead (it turns the pump off, answers and restarts; busy while pumping)."""
        try:
            result = await self.state.controls.execute('meth.restart')
        except ValueError as error:
            self.job = {'state': 'failed', 'kind': 'restart', 'message': str(error), 'progress': 0.0}
            return
        if result.get('status') == 'acknowledged':
            self.job = {'state': 'done', 'kind': 'restart',
                        'message': 'The Nano restarted: back in a few seconds, and armed again if you had it armed', 'progress': 1.0}
        else:
            self.job = {'state': 'failed', 'kind': 'restart', 'message': result.get('message') or 'The Nano did not restart', 'progress': 0.0}

    async def install(self, manifest, data):
        target, build = self.target, manifest['build']
        info = lambda reply: reply[0] == INFO
        ack = lambda op: (lambda reply: reply[0] == ACK and reply[2] == op)
        try:
            if not await self.ask(command(QUERY, target), info, 1.0):
                raise Failure(self.no_answer)
            reply = await self.ask(command(BEGIN, target, len(data).to_bytes(3, 'big') + b'FW'), ack(BEGIN), 6.0, tries=2)
            if not reply:
                raise Failure(f'The {self.label.lower()} did not accept the update')
            if reply[3] == BUSY:
                raise Failure(f'The {self.label.lower()} is in use and did not start the update. {self.warning}')
            if reply[3] != OK:
                raise Failure(f'The {self.label.lower()} {STATUS.get(reply[3], "refused")}')
            blocks = -(-len(data) // BLOCK_BYTES)
            self.pace, self.clean, self.need = START_PACE, 0, CLEAN_TO_SPEED_UP
            self.missed = {'resent': 0, 'asked again': 0, 'silent': 0}
            began = self.state.clock()
            for number in range(blocks):
                if rolling(self.state):
                    raise Failure('The car started moving: update stopped, the old firmware is still running')
                await self.block(number, data[number * BLOCK_BYTES:(number + 1) * BLOCK_BYTES])
                sent = min(len(data), (number + 1) * BLOCK_BYTES)
                self.progress(f'Sending: {sent // 1024} of {len(data) // 1024} KB{pace_text(sent, len(data), self.state.clock() - began)}',
                              (number + 1) / blocks * .9)
            self.took = self.state.clock() - began
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
            speed = f' (sent in {duration(self.took)}, {len(data) / 1024 / max(self.took, .001):.1f} KB/s)' if self.took else ''
            self.job = {'state': 'done', 'message': f'{self.label} updated to build {build}{speed}', 'progress': 1.0}
            self.log('info', self.job['message'] + self.trouble())
        except Failure as failure:
            self.job = {'state': 'failed', 'message': str(failure), 'progress': self.job['progress']}
            self.log('error', f'{self.label} update failed: {failure}' + self.trouble())
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
            while not self.replies.empty():   # A late answer to an earlier block must not be read as this one's.
                self.replies.get_nowait()
            burst, gap = self.burst, self.gap
            full = self.state.tx_full
            for index, frame in enumerate(frames, 1):
                await self.send(frame)
                if index % burst == 0:
                    await self.sleep(gap)
            await self.send(end)
            reply = await self.expect(answered, FIRST_ANSWER_S)
            if reply is None:
                self.missed['asked again'] += 1
                await self.send(end)          # Its answer, or our block end, may be all that was lost.
                reply = await self.expect(answered, SECOND_ANSWER_S)
            if reply is None:
                self.missed['silent'] += 1
                self.slower()                 # Our frames or its answers were lost: sent again, a step slower.
                continue
            if reply[3] == BUSY:
                raise Failure(f'The {self.label.lower()} stopped the update because it was needed; its old firmware is still running. {self.warning}')
            if reply[3] == OK:
                # A block that had to wait for room in the send queue is not a reason to go
                # faster: the Pi's CAN controller is already the limit.
                self.clean = self.clean + 1 if self.state.tx_full == full else 0
                if self.clean >= self.need and self.pace > 0:
                    self.pace, self.clean = self.pace - 1, 0
                return
            if reply[3] == RESEND:            # It missed frames: a step slower.
                self.missed['resent'] += 1
                self.slower()
                continue
            raise Failure(f'The {self.label.lower()} {STATUS.get(reply[3], "refused a block")} (block {number})')
        raise Failure(f'Block {number} could not be delivered: check the CAN wiring')


# The dash's module names (snapshot['modules'], state.GAP_WATCH) each firmware target
# speaks for: while it is updated or restarted they are quiet on purpose.
QUIET = {'gateway': ('comfort', 'sensor gateway'), 'taillights': ('taillights',), 'watermeth': ('watermeth', 'knock', 'water/meth')}


class Firmware:
    """Every module that takes firmware over CAN. One update at a time."""

    def __init__(self, state, folder, sleep=asyncio.sleep, modules=MODULES):
        self.sleep = sleep
        self.modules = {name: ModuleFirmware(state, folder, name, label, target, sleep, title, warning, *silent)
                        for name, label, title, target, warning, *silent in modules}
        for module in self.modules.values():
            module.blocked = lambda module=module: any(other.busy() for other in self.modules.values() if other is not module)

    def observe(self, data):
        for module in self.modules.values():   # Each takes only the answers that name it.
            module.observe(data)

    def busy(self):
        return any(module.busy() for module in self.modules.values())

    def quiet(self):
        """The dash's names for the modules being updated or restarted now."""
        return {name for target, module in self.modules.items() if module.busy() for name in QUIET.get(target, ())}

    def snapshot(self):
        return {name: module.snapshot() for name, module in self.modules.items()}

    def start(self, name):
        module = self.modules.get(name) if isinstance(name, str) else None
        return module.start() if module else 'Unknown module'

    @staticmethod
    def meth_board(module):
        """The water/meth board on the bus, from its own setting reports: 'esp32' (PWM pump
        drive), 'nano' (relay), or None while it is not heard or has not reported yet."""
        state = module.state
        if module.name != 'watermeth' or state.controls.live('meth.state', 0x300, 3) is None:
            return None
        tune = state.meth_tune
        return ('esp32' if tune.pwm else 'nano') if tune.values else None

    def nano_fitted(self, module):
        """The Nano water/meth board: it reports a relay pump and takes no firmware commands.
        (It used to be any water/meth controller that did not answer them: an ESP32 board
        whose updater stopped answering was then offered the Nano's restart.)"""
        return module.snapshot()['installed'] is None and self.meth_board(module) == 'nano'

    def restart(self, name):
        """Restart a module (two presses on the dash, car stopped). An error text, or None."""
        module = self.modules.get(name) if isinstance(name, str) else None
        if not module:
            return 'Unknown module'
        if self.nano_fitted(module):
            if self.busy() or module.busy():
                return 'A module is being updated or restarted'
            if rolling(module.state):
                return 'Stop the car first: the water/meth controller is out of action for a moment while it restarts'
            module.job = {'state': 'running', 'kind': 'restart', 'message': 'Asking the Nano to restart', 'progress': 0.0}
            module.task = asyncio.create_task(module.restart_nano())
            return None
        return module.start_restart()

    def snapshot_with_nano(self):
        """The snapshot, with the water/meth controller's silence explained for the board fitted."""
        result = self.snapshot()
        for name, module in self.modules.items():
            if name != 'watermeth':
                continue
            shown, board = result[name], self.meth_board(module)
            shown['board'] = board
            if shown['installed'] is None and board in METH_SILENT:
                shown['short'], shown['note'] = METH_SILENT[board]
            if self.nano_fitted(module):
                shown['nano'] = True
                shown['can_restart'] = not module.busy() and not self.busy()
        return result

    async def run(self):
        await self.sleep(5)
        while True:
            for module in self.modules.values():
                if not self.busy():
                    await module.query()
                    await self.sleep(.3)
            await self.sleep(QUERY_EVERY_S)
