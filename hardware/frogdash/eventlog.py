"""What went wrong on the dash, and when: a running record kept on the Pi.

The system journal shows the moment of an update; most problems happen on a drive. This
watches the dash's own state every couple of seconds and writes a line whenever something
changes: the GPS losing its fix or its receiver, a fix without a speed, the CAN bus and
each module going quiet or coming back, the ignition, under-voltage, heat, recording
errors, and the engine starting and stopping (to place the rest in time).

One file a day, events/YYYY-MM-DD.jsonl in the dash's data folder, kept 30 days and at
most 20 MB. tools/frogdash_upload.py sends the lines since the last upload with the
diagnostics after each update; GET /events shows the latest.
"""
import asyncio
from collections import deque
import json
from pathlib import Path
import time

WATCH_S = 2
HOLD_S = 4                 # A change has to last this long to be written (no one-sample blips)
KEEP_DAYS = 30
MAX_BYTES = 20 << 20
ALWAYS = {'engine', 'ignition', 'gps-recovery'}   # Written even when first seen
METH_BITS = {0: 'tank level low', 1: 'no manifold pressure', 2: 'overboost assist', 3: 'overboost emergency',
             4: 'invalid setting', 5: 'dash commands timed out'}
SENSOR_BITS = {0: 'oil pressure', 1: 'fuel pressure', 2: 'meth pressure', 3: 'boost reference', 4: 'intake air temp',
               5: 'engine bay temp', 6: 'ambient temp', 7: 'cabin temp'}
EVENT_SOURCES = {0x102: 'taillights', 0x302: 'water/meth', 0x308: 'knock'}
# CustomTaillights src/faults.h
TAILLIGHT_FAULTS = {1: 'running hot', 2: 'too hot: lights cut back', 3: 'CAN bus off', 4: 'a light input was on at start-up',
                    5: 'restarted by a watchdog', 6: 'crashed and restarted', 7: 'restarted after a supply dip (brownout)'}
RESET_REASONS = {1: 'power-on or reset button', 3: 'software restart', 4: 'crash', 5: 'watchdog', 6: 'watchdog',
                 7: 'watchdog', 9: 'brownout (supply dip)', 14: 'power glitch', 15: 'processor lock-up'}


def module_event(event):
    """(level, text) for a fault report a module sent itself on 0x102/0x302/0x308."""
    source = EVENT_SOURCES[event['id']]
    values = event.get('values') or {}
    pick = lambda end: next((v for k, v in values.items() if k.endswith(end)), None)
    code, data0, data1 = pick('code'), pick('data0'), pick('data1')
    if event['id'] == 0x102 and code == 8:   # Each start of the taillights (0x08, severity info)
        flags = data1 or 0
        notes = [text for bit, text in ((1, 'after its restart on settled power'), (2, 'after its restart following a brownout'),
                                        (4, 'SAFE MODE: dimmed after repeated faults'), (8, 'new firmware on trial'),
                                        (16, 'brake or reverse was on, so no restart on settled power')) if flags & bit]
        return 'info', f"taillights started ({RESET_REASONS.get(data0, f'reset reason {data0}')}){': ' + ', '.join(notes) if notes else ''}"
    if event['id'] == 0x102 and code in TAILLIGHT_FAULTS:
        return ('info' if code == 1 else 'warn'), f'taillights: {TAILLIGHT_FAULTS[code]}'
    return 'warn', f'{source} reported fault code {code}'
GPS_LEVEL = {'fix': 'info', 'starting': 'info', 'searching': 'info', 'deaf': 'warn', 'weak': 'warn',
             'silent': 'error', 'no-gpsd': 'error'}


def installed_version(repo=Path(__file__).resolve().parents[2]):
    """The commit the dash runs, read from git's files (no git command at start-up)."""
    try:
        head = (repo / '.git' / 'HEAD').read_text().strip()
        if head.startswith('ref: '):
            ref = head[5:]
            path = repo / '.git' / ref
            if path.exists():
                head = path.read_text().strip()
            else:
                packed = (repo / '.git' / 'packed-refs').read_text().splitlines()
                head = next(line.split()[0] for line in packed if line.endswith(' ' + ref))
        return head[:7]
    except (OSError, StopIteration, IndexError):
        return ''


def read(folder, since=0.0, limit=2000):
    """Entries newer than `since` (Unix time), oldest first, at most `limit` (the newest)."""
    folder = Path(folder)
    found = deque(maxlen=limit)
    if not folder.is_dir():
        return []
    for path in sorted(folder.glob('*.jsonl')):
        try:
            day_end = time.mktime(time.strptime(path.stem, '%Y-%m-%d')) + 2 * 86400   # Generous for time zones
        except ValueError:
            continue
        if day_end < since:
            continue
        try:
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and isinstance(entry.get('t'), (int, float)) and entry['t'] > since:
                found.append(entry)
    return list(found)


def as_text(entries):
    """One readable line each: when (UTC), how bad, what part, what happened."""
    out = []
    for entry in entries:
        when = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(entry['t']))
        line = f"{when} UTC  {entry.get('level', 'info').upper():5}  {entry.get('area', ''):8} {entry.get('text', '')}"
        if entry.get('detail'):
            line += '  ' + json.dumps(entry['detail'], separators=(',', ':'), default=str)
        out.append(line)
    return '\n'.join(out) + ('\n' if out else '')


class EventLog:
    def __init__(self, state, folder, wall=time.time, clock=time.monotonic):
        self.state, self.folder, self.wall, self.clock = state, Path(folder), wall, clock
        self.shown = {}            # key -> value last written
        self.pending = {}          # key -> (value, since): a change waiting out HOLD_S
        self.recent = deque(maxlen=200)
        self.stopping = False
        self.error = None
        self.gaps_seen = 0.0       # Wall time of the last module gap written
        self.events_seen = None    # Timestamp of the last module fault event written
        self.last_event = None     # (payload, timestamp) of the last one, to skip a repeat
        self.brief = None          # (count at the start of this minute, when)

    def write(self, level, area, text, detail=None):
        entry = {'t': round(self.wall(), 1), 'level': level, 'area': area, 'text': text}
        if detail:
            entry['detail'] = detail
        self.recent.append(entry)
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / (time.strftime('%Y-%m-%d', time.gmtime(entry['t'])) + '.jsonl')
            with open(path, 'a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, separators=(',', ':'), default=str) + '\n')
            self.error = None
        except OSError as error:
            self.error = f'Event log could not be saved: {error}'

    def note(self, key, value, level, area, text, detail=None, hold=HOLD_S):
        """Write when `value` changes and the change has lasted `hold` seconds."""
        if self.shown.get(key, object()) == value:
            self.pending.pop(key, None)
            return
        now = self.clock()
        waiting = self.pending.get(key)
        if not waiting or waiting[0] != value:
            self.pending[key] = (value, now)
            if hold > 0:
                return
        elif now - waiting[1] < hold:
            return
        self.pending.pop(key, None)
        first = key not in self.shown
        self.shown[key] = value
        if level is None or (first and level == 'info' and key not in ALWAYS):
            return   # How things stand at start is not news; a problem at start is.
        self.write(level, area, text, detail)

    def watch(self, snapshot):
        values = snapshot.get('values', {})

        def live(name):
            sample = values.get(name) or {}
            return sample.get('value') if sample.get('quality') == 'live' else None

        transport = snapshot.get('transport') or {}
        bus_up = snapshot.get('mode') != 'socketcan' or bool(transport.get('connected'))
        if snapshot.get('mode') == 'socketcan':
            self.note('can', bus_up, 'info' if bus_up else 'error', 'can',
                      'CAN bus connected' if bus_up else f"CAN bus lost: {transport.get('status')}")
        system = snapshot.get('system') or {}
        bus = (system.get('can') or {}).get('state')
        if bus:
            bad = bus.upper() in ('ERROR-PASSIVE', 'BUS-OFF', 'STOPPED')
            self.note('can-state', bus, 'error' if bad else 'info', 'can', f'CAN controller {bus}',
                      {k: (system['can'] or {}).get(k) for k in ('error_counters', 'rx_errors', 'tx_errors')} if bad else None)
        if bus_up:   # With the bus down every module is quiet: that is one problem, not five.
            for name, quality in (snapshot.get('modules') or {}).items():
                here = quality == 'live'
                self.note('module:' + name, here, 'info' if here else 'warn', 'module',
                          f'{name} module answering' if here else f'{name} module not heard ({quality})')

        for name, text in (snapshot.get('faults') or {}).items():
            self.note('fault:' + name, text, 'error', 'dash', f'{name} failed: {text}', hold=0)
        for gap in snapshot.get('gaps') or []:
            if gap['t'] > self.gaps_seen:
                self.gaps_seen = gap['t']
                self.write('warn', 'module', f"{gap['module']} silent for {gap['seconds']} s (0x{gap['id']:03X}), then back: "
                           'a restart of the module, or a dropout', {'id': f"0x{gap['id']:03X}"})
        for name, key, bits, area in (('meth.fault_flags', 'meth-flags', METH_BITS, 'meth'),
                                      ('sensors.fault_flags', 'sensor-flags', SENSOR_BITS, 'sensors')):
            sample = values.get(name) or {}
            if sample.get('quality') == 'live':
                raw = sample.get('raw', sample.get('value')) or 0
                names = ', '.join(bits.get(bit, f'bit {bit}') for bit in range(16) if raw >> bit & 1)
                self.note(key, raw, 'warn' if raw else 'info', area,
                          f'{area} faults reported: {names}' if raw else f'{area} faults cleared', hold=0)
        # Fault reports the modules send themselves (a watchdog restart, a brown-out, a stuck input).
        for event in snapshot.get('events') or []:
            if event.get('id') not in EVENT_SOURCES:
                continue
            if self.events_seen is None or event['timestamp_ms'] > self.events_seen:
                # The taillights send their start report twice (CAN up, then the dash heard): once is enough.
                repeat = self.last_event and self.last_event[0] == event['data'] and event['timestamp_ms'] - self.last_event[1] < 30000
                self.last_event = (event['data'], event['timestamp_ms'])
                if self.events_seen is not None and not repeat:
                    level, text = module_event(event)
                    self.write(level, 'module', text, {'frame': f"0x{event['id']:03X}#{event['data']}"})
        stamps = [e['timestamp_ms'] for e in snapshot.get('events') or [] if e.get('id') in EVENT_SOURCES]
        if stamps:
            self.events_seen = max(stamps + [self.events_seen or 0])
        elif self.events_seen is None:
            self.events_seen = 0
        for alert in (snapshot.get('drive') or {}).get('alerts') or []:
            if isinstance(alert, dict) and alert.get('key'):
                self.note('alert:' + alert['key'], bool(alert.get('active')), 'warn' if alert.get('active') else None, 'alert',
                          f"Alert shown: {alert.get('title')}", {k: v.get('value') for k, v in (alert.get('context') or {}).items()
                                                                  if isinstance(v, dict) and v.get('value') not in (None, 0, False)} or None, hold=0)
        rearm = (snapshot.get('controls') or {}).get('meth_rearm')
        self.note('meth-rearm', rearm, 'info' if rearm else None, 'meth', rearm or '', hold=0)
        mode = (values.get('lighting.left_state') or {}).get('value')
        if mode is not None:
            unusual = mode in ('SHOW', 'CUSTOM')
            self.note('tail-mode', mode if unusual else 'normal', 'warn' if unusual else 'info', 'lights',
                      f'Taillights in {mode} mode (brake from the inputs is overridden)' if unusual else 'Taillights back to normal')

        gps = snapshot.get('gps')
        if gps:
            count = gps.get('brief_losses') or 0
            now = self.clock()
            if self.brief is None:
                self.brief = (count, now)
            elif now - self.brief[1] >= 60:
                if count > self.brief[0]:
                    self.write('info', 'gps', f'GPS said "no fix" for a single report {count - self.brief[0]} times in the last minute '
                               '(ridden through; a real loss lasts longer)')
                self.brief = (count, now)
            diagnosis = gps.get('diagnosis') or {}
            kind = diagnosis.get('state')
            if kind:
                self.note('gps', kind, GPS_LEVEL.get(kind, 'warn'), 'gps', diagnosis.get('text') or kind,
                          {'fix': diagnosis['fix']} if diagnosis.get('fix') else None)
            speed = values.get('vehicle.speed_kph') or {}
            # The signature of a speed shown as nothing: a position, but no speed with it.
            no_speed = kind == 'fix' and speed.get('quality') != 'live'
            self.note('gps-speed', no_speed, 'warn' if no_speed else 'info' if kind == 'fix' else None, 'gps',
                      'GPS has a position but no speed' if no_speed else 'GPS speed back',
                      {'speed': speed, 'status': gps.get('status')} if no_speed else None)
            aid = gps.get('satellite_data')
            self.note('gps-aid', aid, 'info' if aid else None, 'gps', aid or '', hold=0)
            setup = gps.get('receiver_setup')
            self.note('gps-setup', setup, 'info' if setup else None, 'gps', setup or '', hold=0)
            trying = (gps.get('recovery') or {}).get('trying') if isinstance(gps.get('recovery'), dict) else None
            text = trying.get('text') if isinstance(trying, dict) else None
            self.note('gps-recovery', text, 'info' if text else None, 'gps', f'GPS recovery: {text}', hold=0)

        rpm = live('engine.rpm')
        if rpm is not None or values.get('engine.rpm'):
            running = bool(rpm and rpm >= 300)
            self.note('engine', running, 'info', 'engine', 'Engine started' if running else 'Engine stopped')
        ups = system.get('ups') or {}
        if ups.get('available') and isinstance(ups.get('input_present'), bool):
            on = ups['input_present']
            self.note('ignition', on, 'info', 'power', 'Ignition power on' if on else 'Ignition power off: on the battery')
        power = system.get('power') or {}
        if 'undervoltage_now' in power:
            low = bool(power['undervoltage_now'])
            self.note('voltage', low, 'error' if low else 'info', 'power',
                      'Pi supply under-voltage' if low else 'Pi supply voltage good again')
        cpu = system.get('cpu_c')
        if isinstance(cpu, (int, float)):
            hot = cpu >= 80
            self.note('heat', hot, 'warn' if hot else 'info', 'pi', f'Pi hot: {cpu:.0f} °C' if hot else f'Pi temperature normal: {cpu:.0f} °C')
        recording = snapshot.get('recording') or {}
        problem = recording.get('error') or (recording.get('state') == 'error' and recording.get('message'))
        self.note('recording', problem or None, 'error' if problem else 'info', 'logging',
                  f'Recording problem: {problem}' if problem else 'Recording working again')

    def prune(self):
        files = sorted(self.folder.glob('*.jsonl')) if self.folder.is_dir() else []
        cutoff = time.strftime('%Y-%m-%d', time.gmtime(self.wall() - KEEP_DAYS * 86400))
        total = sum(p.stat().st_size for p in files)
        for path in files[:-1]:
            if path.stem < cutoff or total > MAX_BYTES:
                total -= path.stat().st_size
                path.unlink(missing_ok=True)

    async def run(self):
        version = await asyncio.to_thread(installed_version)
        self.write('info', 'dash', 'Dash started' + (f' ({version})' if version else ''))
        await asyncio.to_thread(self.prune)
        while not self.stopping:
            try:
                self.watch(self.state.snapshot())
            except Exception as error:   # The record must never take the dash down.
                self.error = f'Event watch failed: {error}'
            await asyncio.sleep(WATCH_S)

    def snapshot(self):
        return {'recent': list(self.recent)[-50:], 'error': self.error}
