"""TunerStudio on the dash screen (docs/tunerstudio.md).

TunerStudio is a desktop program, so it cannot be a page of this UI. The kiosk launcher
(tools/launch_kiosk.py) already runs in the screen's own session as the normal kiosk
user; it starts TunerStudio over the dash and closes it again. This object is only the
mailbox between the two: the dash asks, the launcher reports every 2 s and collects the
request. Nothing here starts a program, and the dash service needs no extra rights.
"""
from .parking import rolling

KIOSK_TIMEOUT = 8.0  # The launcher reports every 2 s; silent for this long means no kiosk.
STATES = ('idle', 'running', 'failed')


class Tune:
    def __init__(self, state):
        self.state = state
        self.want = None
        self.kiosk = None
        self.seen = float('-inf')
        self.wheel_seen = 0  # Last steering-wheel event already considered.

    def linked(self):
        return self.kiosk is not None and self.state.clock() - self.seen < KIOSK_TIMEOUT

    def snapshot(self):
        moving = rolling(self.state)
        if not self.linked():
            return {'available': False, 'state': 'unavailable', 'moving': moving,
                    'message': 'Only on the dash screen in the car: the kiosk starts TunerStudio'}
        if not self.kiosk['installed']:
            return {'available': False, 'state': 'missing', 'moving': moving,
                    'message': 'TunerStudio is not installed on the Pi (docs/tunerstudio.md)'}
        opening = self.want == 'open' and self.kiosk['state'] != 'running'
        return {'available': True, 'state': 'starting' if opening else self.kiosk['state'], 'moving': moving,
                'message': 'Starting TunerStudio…' if opening else self.kiosk['message']}

    def request(self, action):
        """Ask the kiosk to open or close TunerStudio; ValueError carries the reason it cannot."""
        if action not in ('open', 'close'):
            raise ValueError('Unknown TunerStudio action')
        status = self.snapshot()
        if action == 'open':
            if not status['available']:
                raise ValueError(status['message'])
            # Only a known speed blocks it: tuning at idle in a garage has no GPS fix.
            if status['moving']:
                raise ValueError('Stop the car first: TunerStudio covers the gauges')
        self.want = action
        return self.snapshot()

    def report(self, data):
        """The launcher's 2 s report. Returns the action it should take now, or None."""
        state, message, installed = data.get('state'), data.get('message', ''), data.get('installed')
        if state not in STATES or type(installed) is not bool or not isinstance(message, str) or len(message) > 300:
            raise ValueError('Invalid kiosk report')
        self.kiosk, self.seen = {'state': state, 'message': message, 'installed': installed}, self.state.clock()
        action, self.want = self.want, None
        # Holding OFF (the wheel's "home") closes TunerStudio: a way back without a keyboard.
        events = list(self.state.wheel.events)
        home = any(e['action'] == 'home' and e['id'] > self.wheel_seen for e in events)
        if events:
            self.wheel_seen = max(self.wheel_seen, events[-1]['id'])
        if home and state == 'running' and action is None:
            action = 'close'
        return action
