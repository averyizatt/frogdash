"""Five-button input edges, hold actions and bounded delivery to the local UI."""
from collections import deque
from uuid import uuid4

CAN_ID = 0x205
TIMEOUT = .35
DIRECTIONS = {1: 'up', 2: 'down', 4: 'left', 8: 'right'}


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
        self.long_sent = False

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
        if self.seen is None or now - self.seen > TIMEOUT:
            self.reset()
            return
        if not self.armed:
            return
        if self.mask == 16 and not self.long_sent and now - self.started >= .8:
            self.emit('back')
            self.long_sent = True
        elif self.mask in DIRECTIONS and now >= self.repeat_at:
            self.emit(DIRECTIONS[self.mask])
            self.repeat_at = now + .15  # Never catch up a backlog of repeats.

    def observe(self, data):
        # Called only for a validated standard data frame on the live bus.
        now = self.clock()
        if self.seen is not None and now - self.seen > TIMEOUT:
            self.reset()
        mask, sequence, _ = data
        if self.sequence is not None:
            delta = (sequence - self.sequence) & 255
            if delta == 0:
                return  # Duplicates cannot prolong a held button.
            if delta > 127:
                self.reset()  # Restart/out-of-order: require released buttons.
        self.sequence, self.seen = sequence, now
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
            self.emit('back' if now - self.started >= .8 else 'ok')
        self.mask = mask
        self.started = now
        self.repeat_at = now + .45
        self.long_sent = False
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
