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

        gps = snapshot.get('gps')
        if gps:
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
