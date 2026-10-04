"""Five-button input edges, hold actions and bounded delivery to the local UI."""
from collections import deque
from uuid import uuid4

CAN_ID = 0x205
GATEWAY_ID = 0x501
TIMEOUT = .35
GATEWAY_TIMEOUT = .5  # gateway_protocol.h: consumers expire button state after 500 ms.
DIRECTIONS = {1: 'up', 2: 'down', 4: 'left', 8: 'right'}
BACK = 32
HOLD_BACK = .8       # Hold OK this long: back.
HOLD_HOME_OK = 3.0   # Keep holding OK: close every menu (home).
HOLD_HOME_BACK = 1.5 # Hold the back button (cruise OFF): home.
# Cruise-control buttons (gateway bits 0..4) to navigation bits.
CRUISE = {1: 16, 2: BACK, 4: 2, 8: 1, 16: 8}  # ON=OK, OFF=back, COAST=down, SET ACCEL=up, RESUME=right


class SteeringWheel:
    def __init__(self, clock):
        self.clock = clock
        self.session = uuid4().hex
        self.events = deque(maxlen=32)
        self.event_seq = 0
        self.sequence = None
        self.seen = None
        self.mask = 0
        self.armed = False
        self.started = self.repeat_at = 0
        self.long_sent = self.home_sent = False
        self.timeout = TIMEOUT

    def reset(self):
        self.sequence = self.seen = None
        self.mask = 0
        self.armed = False
        self.events.clear()

    def emit(self, action):
        self.event_seq += 1
        self.events.append({'id': self.event_seq, 'action': action, 'at': self.clock()})

    def tick(self):
        now = self.clock()
        if self.seen is None or now - self.seen > self.timeout:
            self.reset()
            return
        if not self.armed:
            return
        held = now - self.started
        if self.mask == 16 and not self.long_sent and held >= HOLD_BACK:
            self.emit('back')
            self.long_sent = True
        elif self.mask in (16, BACK) and not self.home_sent and held >= (HOLD_HOME_OK if self.mask == 16 else HOLD_HOME_BACK):
            self.emit('home')  # A long hold always gets out, however deep the menu.
            self.home_sent = True
        elif self.mask in DIRECTIONS and now >= self.repeat_at:
            self.emit(DIRECTIONS[self.mask])
            self.repeat_at = now + .15  # Never catch up a backlog of repeats.

    def observe_gateway(self, data):
        """Cruise buttons from the sensor gateway (0x501): a repeated current-state report.

        Unlike 0x205 the sequence only changes on transitions, so every valid report
        refreshes freshness; silence for 500 ms releases everything.
        """
        now = self.clock()
        if self.seen is not None and now - self.seen > GATEWAY_TIMEOUT:
            self.reset()
        self.timeout = GATEWAY_TIMEOUT
        self.seen = now
        mask = 0
        for bit, nav in CRUISE.items():
            if data[0] & bit:
                mask |= nav
        self.apply(mask, now)

    def observe(self, data):
        # Called only for a validated standard data frame on the live bus.
        now = self.clock()
        if self.seen is not None and now - self.seen > TIMEOUT:
            self.reset()
        self.timeout = TIMEOUT
        mask, sequence, _ = data
        if self.sequence is not None:
            delta = (sequence - self.sequence) & 255
            if delta == 0:
                return  # Duplicates cannot prolong a held button.
            if delta > 127:
                self.reset()  # Restart/out-of-order: require released buttons.
        self.sequence, self.seen = sequence, now
        self.apply(mask, now)

    def apply(self, mask, now):
        if mask and mask & (mask - 1):
            self.mask = 0
            self.armed = False  # Chords cancel the current gesture.
            return
        if not self.armed:
            self.mask = 0
            self.armed = mask == 0
            return
        previous = self.mask
        if mask == previous:
            self.tick()
            return
        if previous == 16 and mask == 0 and not self.long_sent:
            self.emit('back' if now - self.started >= HOLD_BACK else 'ok')
        if mask == BACK:
            self.emit('back')  # OFF is a dedicated back button: no hold needed.
        self.mask = mask
        self.started = now
        self.repeat_at = now + .45
        self.long_sent = self.home_sent = False
        if mask in DIRECTIONS:
            self.emit(DIRECTIONS[mask])

    def snapshot(self, connected):
        if not connected:
            self.reset()
        self.tick()
        now = self.clock()
        return {'session': self.session, 'seq': self.event_seq,
                'status': 'unavailable' if self.seen is None else 'ready' if self.armed else 'release buttons',
                'events': [{'id': e['id'], 'action': e['action'], 'age_ms': int((now - e['at']) * 1000)}
                           for e in self.events if now - e['at'] <= .75]}
