"""Typed CAN controls. No arbitrary frame injection or automatic command retries."""
import asyncio
import json
from .driving import atomic_write
from .parking import moving, parked
from .taillight import COLORS, PROFILE_COUNT, SETTINGS
from . import methtune


# CustomTaillights (dd4d971): 33 show animations, override states 0..6, custom one-shots 1..3.
SHOW_COUNT = 33
CUSTOM_BRAKE_CHECK, CUSTOM_FLASH_AMBER, CUSTOM_SCROLL_TWO = 1, 2, 3

# action: (CAN ID, command byte, minimum, maximum, requires ACK)
COMMANDS = {
    "meth.arm": (0x301, 0x01, 0, 1, True),
    "meth.test": (0x301, 0x02, 1, 100, True),
    "meth.stop": (0x301, 0x03, None, None, True),
    "meth.boost": (0x301, 0x04, 0, 250, True),
    "meth.clear_faults": (0x301, 0x06, None, None, True),
    # Pulse tuning (can_protocol.h extension 4), acknowledged on 0x30F. setting = key << 16 | value;
    # tune_action = 0 save, 1 revert, 2 defaults, 3 report.
    "meth.setting": (0x301, 0x10, 1 << 16, (14 << 16) | 0xFFFF, True),
    "meth.tune_action": (0x301, 0x11, 0, 3, True),
    "knock.enable": (0x301, 0x40, 0, 1, True),
    "knock.threshold": (0x301, 0x41, 0, 200, True),
    "knock.multiplier": (0x301, 0x42, 12, 38, True),
    "knock.clear_events": (0x301, 0x4A, None, None, True),
    "knock.refresh": (0x305, 0x40, None, None, False),
    "lighting.brightness": (0x101, 0x01, 0, 255, False),
    "lighting.mode": (0x101, 0x05, 0, 1, False),
    # Show/demo/override/custom replace the turn signals, so they are parked-only and
    # cleared automatically when the car moves. The firmware never suppresses brake/reverse.
    "lighting.show": (0x101, 0x05, 0, SHOW_COUNT - 1, False),
    "lighting.demo": (0x101, 0x05, None, None, False),
    "lighting.override": (0x101, 0x02, 0, 0x66, False),
    "lighting.clear": (0x101, 0x03, None, None, False),
    "lighting.custom": (0x101, 0x04, 1, 0x037E7E, False),
    # Settings extension (can_protocol.h extension 3). Values pack several fields:
    # setting = key << 16 | value; color = which << 24 | RGB; action = action << 8 | argument.
    "lighting.setting": (0x101, 0x06, 1 << 16, (21 << 16) | 0xFFFF, False),
    "lighting.color": (0x101, 0x07, 0, (3 << 24) | 0xFFFFFF, False),
    "lighting.text": (0x101, 0x08, None, None, False),
    "lighting.action": (0x101, 0x09, 0, (6 << 8) | 0xFF, False),
    # Sensor-gateway interior LEDs (gateway_protocol.h 0x502): channel << 32 | RGB << 8 | brightness.
    "interior.light": (0x502, None, 0, (2 << 32) | 0xFFFFFFFF, False),
}
INTERIOR_REFRESH = .5  # The gateway turns a channel off 5 s after its last command.
SHOW_MODE_KEY = 21
METH_TUNE = ('meth.setting', 'meth.tune_action')
PARKED_LIGHTING = ('lighting.show', 'lighting.demo', 'lighting.override', 'lighting.custom')
LABELS = {
    'meth.arm': 'water/meth mode', 'meth.test': 'pump test', 'meth.stop': 'pump test stop',
    'meth.boost': 'boost start', 'meth.clear_faults': 'fault clear request',
    'meth.setting': 'water/meth setting', 'meth.tune_action': 'water/meth settings action',
    'knock.enable': 'knock monitor mode', 'knock.threshold': 'knock threshold offset',
    'knock.multiplier': 'knock multiplier', 'knock.clear_events': 'knock event reset',
}


# Water/meth controller fault bits (methFaultFlagsFor in its firmware), most actionable first.
METH_FAULTS = [
    (1, 'the tank level sensor reads LOW. Fill the tank, or check the float switch wiring and polarity'),
    (2, "the controller's MAP sensor reading is invalid. Check its wiring and vacuum line"),
    (8, 'an overboost emergency is latched. Check boost control, then Clear faults'),
    (16, 'the blend or boost setting is invalid. Re-apply the boost start value'),
]


def meth_fault_reason(flags):
    for bit, text in METH_FAULTS:
        if flags and flags & bit:
            return f'Injection disabled: {text}'
    return 'Injection disabled: the water/meth controller reports a fault (see Sensors > CAN check)'


class Controls:
    def __init__(self, state):
        self.state = state
        self.sender = None
        self.ready_at = float('inf')
        self.pending = None
        self.test_owner = None
        self.test_deadline = 0
        self.last_stop = float('-inf')
        self.last_send = float('-inf')
        self.quiet_until = {}
        self.last = None
        self.watchdog = None
        self.closing = False
        self.lighting_active = False  # A show/demo/override/custom this dashboard started.
        self.lighting_reset_at = float('-inf')
        self.lighting_guard = None
        self.lighting_moving_since = None
        self.interior = {1: [0, 0, 0, 0], 2: [0, 0, 0, 0]}  # channel: R, G, B, brightness
        self.interior_path = None
        self.interior_sent = float('-inf')

    def load_interior(self, path):
        """Restore the last interior colors so they come back after a restart."""
        self.interior_path = path
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            for channel in (1, 2):
                values = saved[str(channel)]
                if len(values) == 4 and all(type(v) is int and 0 <= v <= 255 for v in values):
                    self.interior[channel] = values
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def attach(self, sender):
        self.sender = sender
        self.ready_at = self.state.clock() + 3

    def detach(self):
        self.sender = None
        self.ready_at = float('inf')
        if self.pending and not self.pending['future'].done():
            self.pending['future'].set_result(('unknown', 'CAN disconnected; command outcome unknown'))

    def live(self, name, source, timeout=.5):
        sample = self.state.samples.get((name, source))
        if not sample or sample['quality'] != 'live' or self.state.clock() - sample['seen'] > timeout:
            return None
        return sample['value']

    def conflict(self):
        return self.live('meth.config.version', 0x304, 3) is not None

    def reason(self, action, value=None):
        if self.state.mode != 'socketcan': return 'Controls are disabled during replay'
        if not self.state.connected or self.sender is None: return 'CAN is disconnected'
        stop = action == 'meth.stop' or (action == 'meth.arm' and value == 0)
        if stop: return None  # Always allow an explicit stop/disarm on an open bus.
        if self.state.operations.restoring: return 'Configuration restore recovery pending'
        if action in ('meth.boost', 'knock.threshold', 'knock.multiplier') and not parked(self.state):
            return 'Park first to change controller calibration'
        if self.closing: return 'Dashboard is shutting down'
        if self.state.clock() < self.ready_at: return 'Checking CAN control ownership'
        if self.pending: return 'Waiting for controller acknowledgement'
        if action.startswith('meth.'):
            if self.conflict(): return 'CCM is broadcasting meth settings; transfer meth control to Frogdash first'
            mode = self.live('meth.state', 0x300)
            if mode is None: return 'Water/meth telemetry is stale or unavailable'
            if action == 'meth.arm' and (mode == 'TEST' or self.test_owner is not None):
                return 'Stop the pump test before arming'
            if action in ('meth.arm', 'meth.test'):
                flags = self.live('meth.fault_flags', 0x300)
                if flags or mode == 'FAULT':
                    return meth_fault_reason(flags)
                tank = self.live('meth.tank_pct', 0x300)
                if tank is None or tank <= 10:
                    return 'Injection disabled: the tank level sensor reads LOW. Fill the tank or check the float switch'
            if action in METH_TUNE and not self.state.meth_tune.supported:
                return 'Water/meth firmware without pulse tuning: flash the current firmware'
            if action in ('meth.test', 'meth.boost') and mode != 'OFF':
                return 'Disarm water/meth first'
            if action == 'meth.test':
                if not parked(self.state): return 'Park first: pump tests require fresh stationary or engine-off telemetry'
                if self.test_owner is not None: return 'A pump test is already active'
                if self.state.clock() - self.last_stop < 3: return 'Pump test cooldown (3 seconds)'
        elif action.startswith('knock.'):
            if self.live('knock.status_flags', 0x307) is None: return 'Knock controller is offline'
        elif action == 'interior.light':
            if self.live('interior.upper.brightness', 0x503, 1) is None and self.live('interior.lower.brightness', 0x503, 1) is None:
                return 'Sensor gateway interior lights are offline'
        elif action.startswith('lighting.'):
            if self.live('lighting.brightness', 0x100) is None: return 'Taillight controller is offline'
            if action in PARKED_LIGHTING and not parked(self.state):
                return 'Park first: shows and overrides replace the turn signals'
            if action in ('lighting.setting', 'lighting.color', 'lighting.text', 'lighting.action') and not self.state.taillight.supported:
                return 'Taillight firmware without the settings extension'
            if action == 'lighting.setting' and value is not None and value >> 16 == SHOW_MODE_KEY and value & 0xFFFF and not parked(self.state):
                return 'Park first: shows and overrides replace the turn signals'
        return None

    def status(self):
        reasons = {name: self.reason(name, 1 if name == 'meth.arm' else None) for name in COMMANDS}
        reasons['meth.disarm'] = self.reason('meth.arm', 0)
        return {'reasons': reasons, 'pending': self.pending['action'] if self.pending else None,
                'interior': {'upper': self.interior[1], 'lower': self.interior[2]},
                'lighting_active': self.lighting_active,
                'test_active': self.test_owner is not None, 'last_result': self.last,
                'meth_config_conflict': self.conflict()}

    def observe(self, can_id, data):
        pending = self.pending
        if not pending or pending['future'].done(): return
        if can_id == 0x301:
            pending['future'].set_result(('unknown', 'Another controller sent a command; outcome cannot be attributed'))
        elif can_id == 0x103 and len(data) == 8 and data[0] == 1 and pending['action'].startswith('lighting.') and data[1] == pending['code']:
            status = data[2]
            applied = int.from_bytes(data[4:6], 'big')
            if status == 0:
                pending['future'].set_result(('acknowledged', 'Taillights applied the change'))
            elif status == 3:
                pending['future'].set_result(('adjusted', f'Taillights limited the value to {applied}'))
            elif status == 4:
                pending['future'].set_result(('rejected', 'Taillights could not save to memory'))
            elif status == 5:
                pending['future'].set_result(('rejected', 'That profile slot is empty'))
            else:
                pending['future'].set_result(('rejected', 'Taillights rejected the command: ' + ('unsupported' if status == 1 else 'invalid')))
        elif can_id == 0x30F and len(data) == 8 and data[0] == 1 and pending['action'] in METH_TUNE and data[1] == pending['code']:
            # Unlike 0x30A these name the setting, so they cannot be confused with a late reply.
            status, applied = data[2], int.from_bytes(data[4:6], 'big')
            if pending['action'] == 'meth.setting' and data[3] != pending['value'] >> 16:
                return
            if status == 0:
                pending['future'].set_result(('acknowledged', 'Water/meth controller applied the change'))
            elif status == 3:
                pending['future'].set_result(('adjusted', f'Water/meth controller limited the value to {applied}'))
            else:
                pending['future'].set_result(('rejected', 'Water/meth controller rejected the command: ' + ('unsupported' if status == 1 else 'invalid')))
        elif can_id == 0x304 and pending['action'].startswith('meth.'):
            pending['future'].set_result(('unknown', 'CCM meth settings may override this command'))
        elif can_id == 0x30A and len(data) == 4 and data[3] == 2 and data[0] == pending['code']:
            status, applied = data[1], data[2]
            if status == 0 and applied == pending['value']:
                pending['future'].set_result(('acknowledged', f'Controller accepted {LABELS[pending["action"]]}'))
            elif status == 3:
                rejected = pending['action'] == 'meth.test' and applied == 0
                pending['future'].set_result(('rejected' if rejected else 'adjusted', f'Controller applied value {applied}' + ('; test refused' if rejected else ' (clamped)')))
            elif status in (1, 2):
                pending['future'].set_result(('rejected', 'Controller rejected command: ' + ('unsupported' if status == 1 else 'invalid length')))
            elif status != 0:
                pending['future'].set_result(('unknown', f'Unknown acknowledgement status {status}'))

    async def execute(self, action, value=None, owner=None):
        if action not in COMMANDS: raise ValueError('Unknown control action')
        if action == 'meth.test' and owner is None: raise ValueError('Pump test requires a connected control session')
        identifier, code, low, high, ack = COMMANDS[action]
        if action == 'lighting.text':
            pass  # Validated below; sent as 6-character chunks.
        elif low is None:
            if value is not None: raise ValueError('This command has no value')
        elif type(value) is not int or not low <= value <= high:
            raise ValueError(f'Value must be an integer from {low} to {high}')
        if action == 'lighting.text':
            if not isinstance(value, str) or len(value) > 63 or any(not 0x20 <= ord(c) <= 0x7E for c in value):
                raise ValueError('Show text must be up to 63 plain characters')
        elif action in ('lighting.setting', 'lighting.color', 'lighting.action'):
            self.validate_setting(action, value)
        elif action == 'meth.setting':
            key, number = value >> 16, value & 0xFFFF
            if key not in methtune.SETTINGS:
                raise ValueError('Unknown water/meth setting')
            name, low, high, _ = methtune.SETTINGS[key]
            if not low <= number <= high:
                raise ValueError(f'{name} must be {low} to {high}')
        if action == 'lighting.override' and (value >> 4 > 6 or value & 15 > 6):
            raise ValueError('Override sides must each be a light state from 0 to 6')
        if action == 'lighting.custom' and not self.valid_custom(value):
            raise ValueError('Unknown custom animation')
        stop = action in ('meth.stop', 'lighting.clear') or (action == 'meth.arm' and value == 0)
        reason = self.reason(action, value)
        if reason: raise ValueError(reason)
        now = self.state.clock()
        if not stop and now < self.quiet_until.get(code, 0):
            raise ValueError('Waiting for late controller replies; try again shortly')
        if not stop and now - self.last_send < .25:
            raise ValueError('Please wait before sending another command')
        if stop:
            if self.pending and not self.pending['future'].done():
                self.pending['future'].set_result(('unknown', 'Superseded by stop/disarm'))
            self.test_owner = None
            self.last_stop = now
        payload = self.payload(action, code, value)
        # Firmware with the settings extension acknowledges every 0x101 command on 0x103.
        ack = ack or (identifier == 0x101 and self.state.taillight.supported)
        future = asyncio.get_running_loop().create_future()
        pending = {'future': future, 'code': code, 'value': value or 0, 'action': action}
        self.pending = pending
        self.last_send = now
        if action == 'meth.test':
            self.test_owner = owner
            self.test_deadline = now + 3
            if self.watchdog is None or self.watchdog.done():
                self.watchdog = asyncio.create_task(self.guard_test())
        try:
            if action == 'lighting.text':
                chunks = [value[i:i + 6] for i in range(0, len(value), 6)] or ['']
                if len(chunks[-1]) == 6:
                    chunks.append('')  # A short final chunk marks the end of the text.
                for offset, chunk in enumerate(chunks):
                    await self.sender(identifier, bytes([code, offset * 6]) + chunk.encode('ascii'))
            else:
                await self.sender(identifier, payload)
            if ack:
                try:
                    status, message = await asyncio.wait_for(future, 1.5)
                except TimeoutError:
                    status, message = 'unknown', 'No controller acknowledgement; check live telemetry'
                if identifier == 0x301 and action not in METH_TUNE:
                    # Late 0x30A replies are only matched by command byte. Taillight and
                    # water/meth tuning acknowledgements name their setting on their own
                    # ID, so settings can change quickly (for example while dragging a slider).
                    self.quiet_until[code] = self.state.clock() + 1.5
            else:
                status, message = 'sent', 'Sent; this controller has no command acknowledgement. Check live telemetry.'
            if self.conflict() and stop:
                message += ' CCM settings can re-arm the module until control ownership is transferred.'
            result = {'action': action, 'status': status, 'message': message}
            self.last = result
            # A missing ACK does not prove the test failed to start. Send STOP.
            if action == 'meth.test' and status != 'acknowledged':
                await self.stop_test('Pump test stopped after an unconfirmed request')
            if action == 'interior.light':
                channels = (1, 2) if value >> 32 == 0 else (value >> 32,)
                for channel in channels:
                    self.interior[channel] = [(value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF]
                self.interior_sent = self.state.clock()
                if self.interior_path:
                    await asyncio.to_thread(atomic_write, self.interior_path, {str(k): v for k, v in self.interior.items()})
            if action in PARKED_LIGHTING:
                self.lighting_active = True
            elif action in ('lighting.clear', 'lighting.mode'):
                self.lighting_active = False
            return result
        except (OSError, TimeoutError) as exc:
            self.last = {'action': action, 'status': 'unknown', 'message': f'Transmission failed; outcome unknown: {exc}'}
            if action == 'meth.test': await self.stop_test('Pump test transmission failed')
            return self.last
        finally:
            if self.pending is pending: self.pending = None

    @staticmethod
    def validate_setting(action, value):
        if type(value) is not int or value < 0:
            raise ValueError('Invalid taillight setting value')
        if action == 'lighting.setting':
            key, number = value >> 16, value & 0xFFFF
            if key not in SETTINGS:
                raise ValueError('Unknown taillight setting')
            _, low, high = SETTINGS[key]
            if not low <= number <= high:
                raise ValueError(f'{SETTINGS[key][0]} must be {low} to {high}')
        elif action == 'lighting.color' and value >> 24 >= len(COLORS):
            raise ValueError('Unknown taillight color')
        elif action == 'lighting.action':
            kind, argument = value >> 8, value & 0xFF
            if kind > 6 or (kind >= 4 and argument >= PROFILE_COUNT) or (kind < 4 and argument):
                raise ValueError('Invalid taillight settings action')

    @staticmethod
    def valid_custom(value):
        if type(value) is not int: return False
        kind = value >> 16
        if kind == CUSTOM_SCROLL_TWO:
            return all(0x20 <= c <= 0x7E for c in ((value >> 8) & 0xFF, value & 0xFF))
        return kind == 0 and value in (CUSTOM_BRAKE_CHECK, CUSTOM_FLASH_AMBER)

    @staticmethod
    def payload(action, code, value):
        if action == 'lighting.mode': return bytes([code, value, 0])  # Show option unused for STOCK/SEQUENTIAL.
        if action == 'lighting.show': return bytes([code, 2, value])
        if action == 'lighting.demo': return bytes([code, 3, 0])
        if action == 'lighting.override': return bytes([code, value >> 4, value & 15])
        if action == 'interior.light': return bytes([value >> 32, (value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF, 1])
        if action in ('lighting.setting', 'meth.setting'): return bytes([code, value >> 16, (value >> 8) & 0xFF, value & 0xFF])
        if action == 'lighting.color': return bytes([code, value >> 24, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF])
        if action == 'lighting.action': return bytes([code, value >> 8, value & 0xFF])
        if action == 'lighting.text': return b''
        if action == 'lighting.custom':
            if value >> 16 == CUSTOM_SCROLL_TWO:
                return bytes([code, CUSTOM_SCROLL_TWO, 0, 0, (value >> 8) & 0xFF, value & 0xFF])
            if value == CUSTOM_FLASH_AMBER:
                return bytes([code, CUSTOM_FLASH_AMBER, 0, 0, 3, 150])  # Three flashes, 150 ms apart.
            return bytes([code, value, 0, 0, 0, 0])
        return bytes([code]) if value is None else bytes([code, value])

    def start(self):
        if self.lighting_guard is None or self.lighting_guard.done():
            self.lighting_guard = asyncio.create_task(self.guard_lighting())

    async def guard_lighting(self):
        """Send 'clear' once the car is moving with a show/override/custom active.

        Covers shows started here and from the taillights' own Wi-Fi page (reported as
        SHOW/CUSTOM). Brake and reverse are protected by the taillight firmware itself.
        """
        while not self.closing:
            await asyncio.sleep(.25)
            await self.check_lighting()
            await self.sync_taillight()
            await self.sync_meth_tune()
            await self.refresh_interior()

    async def refresh_interior(self):
        """Keep lit interior channels alive; the gateway expires them after 5 s of silence."""
        now = self.state.clock()
        if (self.state.mode != 'socketcan' or not self.sender or not self.state.connected
                or self.pending or now - self.interior_sent < INTERIOR_REFRESH):
            return
        self.interior_sent = now
        for channel, (red, green, blue, brightness) in self.interior.items():
            if brightness:
                try:
                    await self.sender(0x502, bytes([channel, red, green, blue, brightness, 1]))
                except (OSError, TimeoutError):
                    return

    async def sync_taillight(self):
        """Ask for a full settings report whenever the controller's revision moved."""
        mirror = self.state.taillight
        if (self.state.mode != 'socketcan' or not self.sender or not self.state.connected
                or self.pending or not mirror.needs_report()):
            return
        mirror.requested()
        try:
            await self.sender(0x101, bytes([0x09, 3, 0]))
        except (OSError, TimeoutError):
            pass

    async def sync_meth_tune(self):
        """Ask the water/meth controller for its settings whenever its revision moved."""
        mirror = self.state.meth_tune
        if (self.state.mode != 'socketcan' or not self.sender or not self.state.connected
                or self.pending or not mirror.needs_report()):
            return
        mirror.requested()
        try:
            await self.sender(0x301, bytes([0x11, 3]))
        except (OSError, TimeoutError):
            pass

    async def check_lighting(self):
        sides = [self.live(f'lighting.{side}_state', 0x100, 1) for side in ('left', 'right')]
        active = self.lighting_active or any(s in ('SHOW', 'CUSTOM') for s in sides)
        if not active or not moving(self.state):
            self.lighting_moving_since = None
            return
        now = self.state.clock()
        if self.lighting_moving_since is None:
            self.lighting_moving_since = now
        if now - self.lighting_moving_since < 1 or now - self.lighting_reset_at < 2:
            return
        self.lighting_reset_at = now
        try:
            if self.state.mode != 'socketcan' or not self.sender or not self.state.connected:
                raise OSError('CAN disconnected')
            await self.sender(0x101, bytes([0x03]))
            self.lighting_active = False
            self.last = {'action': 'lighting.clear', 'status': 'sent', 'message': 'Vehicle moving: taillight show/override cleared so turn signals work'}
        except (OSError, TimeoutError):
            self.last = {'action': 'lighting.clear', 'status': 'unknown', 'message': 'Vehicle moving but the taillight clear could not be sent'}

    async def stop_test(self, reason):
        if self.test_owner is None: return
        self.test_owner = None
        self.last_stop = self.state.clock()
        try:
            if not self.sender or not self.state.connected: raise OSError('CAN disconnected')
            await self.sender(0x301, b'\x03')
            self.last = {'action': 'meth.stop', 'status': 'sent', 'message': reason + '; stop sent, check live pump duty'}
        except (OSError, TimeoutError):
            self.last = {'action': 'meth.stop', 'status': 'unknown', 'message': reason + '; stop could not be sent; controller timeout applies'}

    async def guard_test(self):
        while self.test_owner is not None:
            if (self.state.clock() >= self.test_deadline or not self.state.connected or
                    self.live('meth.state', 0x300) is None or
                    self.live('meth.fault_flags', 0x300) != 0 or self.conflict() or not parked(self.state)):
                await self.stop_test('Pump test ended')
                return
            await asyncio.sleep(.1)

    async def release(self, owner):
        if self.test_owner is owner: await self.stop_test('Control page disconnected')

    async def close(self):
        self.closing = True
        if self.lighting_guard:
            self.lighting_guard.cancel()
            await asyncio.gather(self.lighting_guard, return_exceptions=True)
        await self.stop_test('Dashboard shutting down')
        if self.watchdog:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
