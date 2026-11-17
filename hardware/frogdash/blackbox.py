"""The ESP32 water/meth board's black box (can_protocol.h extension 9).

The board keeps its last ten seconds, one sample per 100 ms, in memory a reset does not
clear (DIYWaterMethInjection include/black_box.h). After a reset nobody asked for (a crash,
a watchdog, a supply dip, a restart over a silent CAN bus) it sends that record once it is
back: a header frame, then the samples' bytes seven to a frame on 0x310. It sends it again
every 5 s until it hears 0x301 0x13 from the dash.

The record is put back together here, written to the event log in words with every sample
(the event log goes up with each report, so it can be read after the drive), shown on the
Water / meth tab, and answered.

The board does not measure its own supply, so each sample is given the MicroSquirt's battery
voltage at that moment: the dash keeps the last minute of it, and the board's reset is put at
the last 0x300 heartbeat before its latest silence (within about one heartbeat). That is the
car's voltage at the ECU, not at the end of the board's own feed: it shows a dip the whole
car saw (the pump starting on a weak battery), not a bad connection on the board's wire.
"""
from collections import deque

from .eventlog import RESET_REASONS
from .methtune import HOLDS

ID = 0x310
HEADER, VERSION, SAMPLE_BYTES, PER_FRAME = 0xFF, 1, 10, 7
SUPPLY_KEEP_S = 60     # The MicroSquirt's battery voltage kept for lining up with a record
QUIET_S = 0.3          # A heartbeat silence this long is a restart (the board sends 0x300 every 50 ms)
NEAREST_S = 0.25       # A voltage reading this close to a sample counts for it
RECEIVED = bytes([0x13])          # meth_tune_command::BLACK_BOX_RECEIVED
# black_box.h: kState's upper bits and kEvents.
ARMED, SOFT_START, PUMP_TEST, CRASH_HOLD = 16, 32, 64, 128
ECU_FRESH, CAN_ONLINE, PUMP_STARTED, PUMP_STOPPED = 1, 2, 4, 8
CAN_SET_UP, CAN_SEND_FAILED, KEEPER, TANK_LOW = 16, 32, 64, 128
COLUMNS = ['t_s', 'duty_pct', 'duty_max_pct', 'map_kpa', 'rpm', 'hold', 'state', 'events',
           'rx_age_ms', 'loop_gap_ms', 'pre_c', 'heap_kb', 'ecu_battery_v']


def rows_of(payload, window_ms):
    """One row per sample, oldest first; t_s is seconds before the last sample (0)."""
    count = len(payload) // SAMPLE_BYTES
    rows = []
    for i in range(count):
        s = payload[i * SAMPLE_BYTES:(i + 1) * SAMPLE_BYTES]
        hold = s[4] & 15
        rows.append([round((i - count + 1) * window_ms / 1000, 1), s[0] / 2, s[1] / 2, s[2] or None, s[3] * 32 or None,
                     HOLDS[hold] if hold < len(HOLDS) else hold, s[4] & 0xF0, s[5], s[6] * 10, s[7],
                     s[8] - 40 if s[8] else None, s[9] * 2, None])
    return rows


def summary(rows, reason, window_ms):
    """What the record says, in a line: the end of it first, then what led there."""
    column = {name: index for index, name in enumerate(COLUMNS)}
    get = lambda row, name: row[column[name]]
    last, n = rows[-1], len(rows)
    ago = lambda index: (n - 1 - index) * window_ms / 1000
    find = lambda bit, field='events': next((i for i in range(n - 1, -1, -1) if get(rows[i], field) & bit), None)
    parts = []
    duty = get(last, 'duty_pct')
    if duty:
        started = find(PUMP_STARTED)
        parts.append(f"pump on at {duty:g}%" + (f", started {ago(started):.1f} s before the end" if started is not None else ', on the whole time') +
                     (' (still in its soft start)' if get(last, 'state') & SOFT_START else ''))
    else:
        stopped = find(PUMP_STOPPED)
        peak = max(get(row, 'duty_max_pct') for row in rows)
        parts.append('pump off' + (f", stopped {ago(stopped):.1f} s before the end (up to {peak:g}%)" if stopped is not None and peak else ''))
    if get(last, 'map_kpa'):
        parts.append(f"{get(last, 'map_kpa')} kPa, {get(last, 'rpm') or 0} rpm")
    else:
        parts.append('no fresh MicroSquirt data at the end')
    silent = get(last, 'rx_age_ms')
    parts.append(f"nothing heard on CAN for the last {silent / 1000:.1f} s{' or more' if silent >= 2550 else ''}" if silent >= 500
                 else 'CAN heard to the end')
    setups = sum(1 for row in rows if get(row, 'events') & CAN_SET_UP)
    if setups:
        parts.append(f"CAN set up again in {setups} of the windows")
    fails = sum(1 for row in rows if get(row, 'events') & CAN_SEND_FAILED)
    if fails:
        parts.append(f"frames not getting out in {fails} of the windows")
    gap = max(get(row, 'loop_gap_ms') for row in rows)
    parts.append(f"longest control gap {gap}{' or more' if gap >= 255 else ''} ms")
    if any(get(row, 'events') & KEEPER for row in rows):
        parts.append('the pump keeper had to switch the pump off')
    if any(get(row, 'state') & CRASH_HOLD for row in rows):
        parts.append('resting after crashes')
    if any(get(row, 'state') & PUMP_TEST for row in rows):
        parts.append('a pump test was running')
    parts.append(f"least free memory {min(get(row, 'heap_kb') for row in rows)} KB")
    volts = [(i, get(row, 'ecu_battery_v')) for i, row in enumerate(rows) if get(row, 'ecu_battery_v') is not None]
    if volts:
        low = min(volts, key=lambda pair: pair[1])
        parts.append(f"MicroSquirt battery {volts[-1][1]:.1f} V at the end, lowest {low[1]:.1f} V"
                     + (' at the end' if low[0] == volts[-1][0] else f" {ago(low[0]):.1f} s before the end"))
    return f"({RESET_REASONS.get(reason, f'reset reason {reason}')}), the {n * window_ms / 1000:.1f} s before it: " + '; '.join(parts)


class BlackBox:
    def __init__(self, state):
        self.state = state
        self.header, self.chunks = None, {}
        self.last = None              # The latest record, for the Water / meth tab
        self.last_payload = None      # ...as received, so a record sent again is written once
        self.answer_due = False
        self.supply = deque()         # (dash clock, volts): the MicroSquirt's battery voltage
        self.heard = None             # The board's latest 0x300 heartbeat
        self.quiet_at = None          # ...and the last one before its latest silence

    def battery(self, now, volts):
        self.supply.append((now, volts))
        while self.supply and self.supply[0][0] < now - SUPPLY_KEEP_S:
            self.supply.popleft()

    def heartbeat(self, now):
        if self.heard is not None and now - self.heard >= QUIET_S:
            self.quiet_at = self.heard
        self.heard = now

    def reset_at(self, now):
        """When the board went quiet before this record, on the dash's clock (None: not seen)."""
        at = self.heard if self.heard is not None and now - self.heard >= QUIET_S else self.quiet_at
        return at if at is not None and now - at < SUPPLY_KEEP_S else None

    def add_supply(self, rows):
        end = self.reset_at(self.state.clock())
        if end is None or not self.supply:
            return
        index = len(COLUMNS) - 1
        for row in rows:
            when = end + row[0]
            nearest = min(self.supply, key=lambda pair: abs(pair[0] - when))
            if abs(nearest[0] - when) <= NEAREST_S:
                row[index] = nearest[1]

    def observe(self, data):
        if len(data) != 8:
            return
        if data[0] == HEADER:
            # A header starts a record, also part-way through another (the board sending it again).
            self.chunks = {}
            self.header = None if data[1] != VERSION else {
                'samples': data[2], 'window_ms': data[3] * 10, 'reason': data[4], 'frames': data[5], 'sum': data[6] << 8 | data[7]}
            return
        if self.header is None or data[0] >= self.header['frames']:
            return   # Frames of a record whose header was missed: the board sends it all again
        self.chunks[data[0]] = bytes(data[1:8])
        if len(self.chunks) == self.header['frames']:
            self.complete()

    def complete(self):
        header, chunks = self.header, self.chunks
        self.header, self.chunks = None, {}
        payload = b''.join(chunks[i] for i in range(header['frames']))[:header['samples'] * SAMPLE_BYTES]
        if len(payload) < SAMPLE_BYTES or sum(payload) & 0xFFFF != header['sum']:
            return   # Damaged on the way: not answered, so the board sends it again
        self.answer_due = True
        if payload == self.last_payload:
            return   # Sent again because the answer was lost: written once
        self.last_payload = payload
        rows = rows_of(payload, header['window_ms'])
        self.add_supply(rows)
        text = summary(rows, header['reason'], header['window_ms'])
        self.last = {'at': self.state.wall(), 'reason': header['reason'], 'text': text}
        if self.state.eventlog:
            self.state.eventlog.write('warn', 'module', f'water/meth black box {text}',
                                      {'window_ms': header['window_ms'], 'columns': COLUMNS, 'rows': rows})

    async def answer(self):
        """Tell the board the record arrived (from the controls loop, four times a second)."""
        sender = self.state.controls.sender
        if not self.answer_due or not sender or not self.state.connected or self.state.mode != 'socketcan':
            return
        self.answer_due = False
        try:
            await sender(0x301, RECEIVED)
        except (OSError, TimeoutError):
            self.answer_due = True

    def snapshot(self):
        return self.last
