"""CAN brought back by itself when it stops receiving with the key on.

The MCP2515 on the Pi's SPI can stop passing frames on without the link going down: a
missed interrupt, or a supply dip while cranking. can0 still says it is up, the dash's
socket is still open, and every gauge goes stale until the Pi restarts. When nothing at
all has arrived for SILENT_S with the ignition on, the dash asks the root helper
(tools/frogdash_can.sh, started by frogdash-canreset.path) to take can0 down and up
again; the socket notices the link going down and opens again by itself. A few tries,
further apart each time, then it waits for frames to come back before trying again.
"""
import asyncio
import json

SILENT_S = 10
TRIES_AT_S = (SILENT_S, 60, 300)   # Silence at which each reset is asked for
HELPER_WAIT_S = 20


class CanWatch:
    def __init__(self, state, folder, clock=None, sleep=asyncio.sleep):
        self.state, self.folder, self.sleep = state, folder, sleep
        self.clock = clock or state.clock
        self.count = None        # state.received when last looked
        self.heard = None        # When a frame last arrived (or when watching began)
        self.ever = False        # A frame has arrived since the dash started
        self.tries = 0           # Resets asked for in this silence
        self.resets = 0
        self.requested_at = None
        self.helper = 'unknown'  # 'ok' once the helper has taken a request, 'missing' when it never did
        self.last = None         # The helper's last result (can-status.json)
        self.last_reset = None   # Wall time of the last reset asked for

    def key_off(self):
        ups = ((getattr(self.state.health, 'status', None) or {}).get('ups') or {}) if self.state.health else {}
        return ups.get('available') is True and ups.get('input_present') is False

    def log(self, level, text):
        if self.state.eventlog:
            self.state.eventlog.write(level, 'can', text)

    def check(self):
        now = self.clock()
        if self.count is None:
            self.count, self.heard = self.state.received, now
            return
        if self.state.received != self.count:
            self.count, self.heard = self.state.received, now
            if self.tries:
                self.log('info', 'CAN receiving again after the reset')
            self.ever, self.tries = True, 0
            return
        self.check_helper(now)
        if self.state.mode != 'socketcan' or self.key_off():
            self.heard = now      # Key off: a quiet bus is expected; count the silence from key-on
            return
        silent = now - self.heard
        if self.tries >= len(TRIES_AT_S) or silent < TRIES_AT_S[self.tries]:
            return
        self.tries += 1
        self.ask(now, silent)

    def ask(self, now, silent):
        if self.folder is None:
            return
        try:
            (self.folder / 'can-request').write_text('reset', encoding='utf-8')
        except OSError as exc:
            self.state.fault('CAN reset request', exc)
            return
        self.requested_at, self.resets, self.last_reset = now, self.resets + 1, self.state.wall()
        what = 'stopped receiving' if self.ever else 'has received nothing since the dash started'
        last = '' if self.tries < len(TRIES_AT_S) else ' Last try until frames come back.'
        self.log('warn', f'CAN {what} ({silent:.0f} s with the key on): resetting can0.{last}')

    def check_helper(self, now):
        if self.requested_at is not None:
            request = self.folder / 'can-request'
            if not request.exists():
                self.helper, self.requested_at = 'ok', None
            elif now - self.requested_at > HELPER_WAIT_S:
                self.helper, self.requested_at = 'missing', None
                self.log('error', 'The CAN reset helper did not answer: run Update now to install it')
                try:
                    request.unlink()
                except OSError:
                    pass
        try:
            self.last = json.loads((self.folder / 'can-status.json').read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            pass

    def snapshot(self):
        silent = None if self.heard is None else round(self.clock() - self.heard, 1)
        return {'silent_s': silent, 'resets': self.resets, 'tries': self.tries, 'helper': self.helper,
                'last_reset': self.last_reset, 'last_result': self.last}

    async def run(self):
        while True:
            self.check()
            await self.sleep(1)
