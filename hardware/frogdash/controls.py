"""Typed CAN controls. No arbitrary frame injection or automatic command retries."""
import asyncio


# action: (CAN ID, command byte, minimum, maximum, requires ACK)
COMMANDS = {
    "meth.arm": (0x301, 0x01, 0, 1, True),
    "meth.test": (0x301, 0x02, 1, 100, True),
    "meth.stop": (0x301, 0x03, None, None, True),
    "meth.boost": (0x301, 0x04, 0, 250, True),
    "meth.clear_faults": (0x301, 0x06, None, None, True),
    "knock.enable": (0x301, 0x40, 0, 1, True),
    "knock.threshold": (0x301, 0x41, 0, 200, True),
    "knock.multiplier": (0x301, 0x42, 12, 38, True),
    "knock.clear_events": (0x301, 0x4A, None, None, True),
    "knock.refresh": (0x305, 0x40, None, None, False),
    "lighting.brightness": (0x101, 0x01, 0, 255, False),
    "lighting.mode": (0x101, 0x05, 0, 1, False),
}
LABELS = {
    'meth.arm': 'water/meth mode', 'meth.test': 'pump test', 'meth.stop': 'pump test stop',
    'meth.boost': 'boost start', 'meth.clear_faults': 'fault clear request',
    'knock.enable': 'knock monitor mode', 'knock.threshold': 'knock threshold offset',
    'knock.multiplier': 'knock multiplier', 'knock.clear_events': 'knock event reset',
}


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
                if self.live('meth.fault_flags', 0x300) != 0 or mode == 'FAULT':
                    return 'Resolve the water/meth fault before enabling the pump'
                tank = self.live('meth.tank_pct', 0x300)
                if tank is None or tank <= 10: return 'Water/meth tank is low or unavailable'
            if action in ('meth.test', 'meth.boost') and mode != 'OFF':
                return 'Disarm water/meth first'
            if action == 'meth.test':
                if self.test_owner is not None: return 'A pump test is already active'
                if self.state.clock() - self.last_stop < 3: return 'Pump test cooldown (3 seconds)'
        elif action.startswith('knock.'):
            if self.live('knock.status_flags', 0x307) is None: return 'Knock controller is offline'
        elif action.startswith('lighting.'):
            if self.live('lighting.brightness', 0x100) is None: return 'Taillight controller is offline'
        return None

    def status(self):
        reasons = {name: self.reason(name, 1 if name == 'meth.arm' else None) for name in COMMANDS}
        reasons['meth.disarm'] = self.reason('meth.arm', 0)
        return {'reasons': reasons, 'pending': self.pending['action'] if self.pending else None,
                'test_active': self.test_owner is not None, 'last_result': self.last,
                'meth_config_conflict': self.conflict()}

    def observe(self, can_id, data):
        pending = self.pending
        if not pending or pending['future'].done(): return
        if can_id == 0x301:
            pending['future'].set_result(('unknown', 'Another controller sent a command; outcome cannot be attributed'))
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
        if low is None:
            if value is not None: raise ValueError('This command has no value')
        elif type(value) is not int or not low <= value <= high:
            raise ValueError(f'Value must be an integer from {low} to {high}')
        stop = action == 'meth.stop' or (action == 'meth.arm' and value == 0)
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
        payload = bytes([code]) if value is None else bytes([code, value])
        if action == 'lighting.mode': payload += b'\0'  # Show option, unused for STOCK/SEQUENTIAL.
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
            await self.sender(identifier, payload)
            if ack:
                try:
                    status, message = await asyncio.wait_for(future, 1.5)
                except TimeoutError:
                    status, message = 'unknown', 'No controller acknowledgement; check live telemetry'
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
            return result
        except (OSError, TimeoutError) as exc:
            self.last = {'action': action, 'status': 'unknown', 'message': f'Transmission failed; outcome unknown: {exc}'}
            if action == 'meth.test': await self.stop_test('Pump test transmission failed')
            return self.last
        finally:
            if self.pending is pending: self.pending = None

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
                    self.live('meth.fault_flags', 0x300) != 0 or self.conflict()):
                await self.stop_test('Pump test ended')
                return
            await asyncio.sleep(.1)

    async def release(self, owner):
        if self.test_owner is owner: await self.stop_test('Control page disconnected')

    async def close(self):
        self.closing = True
        await self.stop_test('Dashboard shutting down')
        if self.watchdog:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
