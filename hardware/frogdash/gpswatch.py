"""GPS recovery: when there is no position, try what a person would, in order.

Two different problems need different remedies:

- Nothing is reporting (service down, receiver not found): restart the GPS service,
  look for the receiver on every USB port and point the service at it, then reset the
  receiver's USB connection. These need root, so the dash asks a small helper
  (tools/frogdash_gps.sh, started by frogdash-gps.path) by leaving a one-word request.
- The receiver reports but has no position: restart its satellite search, then clear
  its memory and start again. A u-blox receiver takes these commands through gpsd;
  for other makes the USB reset stands in. After that nothing in software can help:
  it is reception, and the dash says so.

Every step is announced so the driver sees what is being tried.
"""
import asyncio
import json

SILENT = ('no-gpsd', 'silent')
NO_FIX = ('deaf', 'weak', 'searching')
# (seconds to wait before this step, action, what the driver is told)
SILENT_STEPS = [(15, 'restart', 'Restarting the GPS service'),
                (25, 'repin', 'Looking for the receiver on the USB ports'),
                (25, 'usb', 'Resetting the receiver USB connection')]
NO_FIX_STEPS = [(120, 'warm', 'Restarting the receiver satellite search'),
                (180, 'cold', 'Clearing the receiver memory and starting again')]
NO_SERVICE_S = 5        # The service not answering at all gets its restart sooner.
SILENT_RETRY_S = 300    # Then go round again: a receiver plugged in later should be found.
NO_FIX_RETRY_S = 900    # Clearing the memory again too soon only makes a weak signal worse.
ANNOUNCE_S = 20
HELPER_WAIT_S = 8       # A request still lying there after this long means no helper.


class GpsRecovery:
    def __init__(self, gps, folder, clock):
        self.gps, self.folder, self.clock = gps, folder, clock
        self.kind = None          # 'silent', 'no-fix' or None while all is well
        self.index = 0
        self.next_at = None
        self.trying = None        # {'text', 'at', 'step', 'steps'}
        self.tried = 0            # Steps taken since the last position
        self.cleared = False      # The receiver's memory has been cleared since the last position
        self.helper = 'unknown'   # 'ok', 'missing' or 'unknown'
        self.requested_at = None
        self.last = None          # The helper's last answer
        self.stopping = False

    def steps(self):
        return SILENT_STEPS if self.kind == 'silent' else NO_FIX_STEPS

    def step(self):
        """One look at the receiver; takes the next recovery step when it is due."""
        now = self.clock()
        state = self.gps.diagnosis()['state']
        kind = 'silent' if state in SILENT else 'no-fix' if state in NO_FIX else None
        self.check_helper(now)
        if kind != self.kind:
            self.kind, self.index = kind, 0
            self.next_at = now + (NO_SERVICE_S if state == 'no-gpsd' else self.steps()[0][0]) if kind else None
            if kind is None and state == 'fix':
                self.trying, self.tried, self.cleared = None, 0, False
        if kind is None or now < self.next_at:
            return
        steps = self.steps()
        if self.index >= len(steps):
            self.index = 0  # A full round done and still nothing: start over.
        _, action, text = steps[self.index]
        if action == 'cold':
            if self.cleared:  # Once is enough: clearing it again throws away what it has since learned.
                _, action, text = steps[0]
            self.cleared = True
        self.trying = {'text': text, 'at': now, 'step': self.index + 1, 'steps': len(steps)}
        self.tried += 1
        self.act(action, now)
        self.index += 1
        wait = steps[self.index][0] if self.index < len(steps) else (SILENT_RETRY_S if kind == 'silent' else NO_FIX_RETRY_S)
        self.next_at = now + wait

    def act(self, action, now):
        if action in ('warm', 'cold'):
            try:
                if self.gps.restart_receiver(cold=action == 'cold'):
                    return
            except OSError:
                pass
            action = 'usb'  # Not a u-blox, or gpsd would not pass it on: replug it instead.
        self.ask_helper(action, now)

    def ask_helper(self, action, now):
        if self.folder is None:
            self.helper = 'missing'
            return
        try:
            (self.folder / 'gps-request').write_text(action, encoding='utf-8')
            self.requested_at = now
        except OSError:
            self.helper = 'missing'

    def check_helper(self, now):
        if self.folder is None:
            return
        if self.requested_at is not None:
            if not (self.folder / 'gps-request').exists():
                self.helper, self.requested_at = 'ok', None
            elif now - self.requested_at > HELPER_WAIT_S:
                self.helper, self.requested_at = 'missing', None
                try:
                    (self.folder / 'gps-request').unlink()
                except OSError:
                    pass
        try:
            self.last = json.loads((self.folder / 'gps-status.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass

    def snapshot(self):
        now = self.clock()
        announce = self.trying if self.trying and now - self.trying['at'] <= ANNOUNCE_S else None
        steps = self.steps() if self.kind else []
        return {'kind': self.kind,
                'trying': {'text': announce['text'], 'step': announce['step'], 'steps': announce['steps']} if announce else None,
                'tried': self.tried, 'helper': self.helper,
                'exhausted': bool(self.kind) and self.index >= len(steps) and not announce,
                'next_in_s': max(0, round(self.next_at - now)) if self.kind and self.next_at is not None else None,
                'last': self.last.get('message') if isinstance(self.last, dict) else None,
                'first_fix_s': self.gps.first_fix_s}

    async def run(self):
        while not self.stopping:
            await asyncio.to_thread(self.step)
            await asyncio.sleep(1)
