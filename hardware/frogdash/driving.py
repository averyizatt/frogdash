"""Advisory alerts, bookmarks and bounded drive reviews. Never controls power or CAN."""
import asyncio
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from . import alerts as catalogue
from .alerts import live, validate_settings   # validate_settings: also for backups (operations.py)

NAME = re.compile(r'^drive-[0-9a-f]{32}\.json$')
CHANNELS = ['engine.rpm', 'vehicle.speed_kph', 'engine.boost_kpa', 'engine.afr', 'ecu.afr_target',
            'engine.fuel_pressure_psi', 'engine.oil_pressure_psi', 'engine.coolant_c', 'engine.iat_c',
            'meth.duty_pct', 'meth.tank_pct', 'knock.energy']
# The readings kept with an alert when it goes off (what was happening).
CONTEXT = CHANNELS + ['meth.state', 'meth.flow', 'meth.fault_flags', 'knock.warning', 'knock.critical',
                      'vehicle.battery_v', 'vehicle.fuel_pct', 'ecu.iat_c', 'ecu.knock_retard_deg',
                      'engine.ego_correction_pct', 'ecu.sync_loss_count']
# Every alert, its words and its rules: hardware/ui/alert-rules.json (alerts.py).
RULES = catalogue.RULES


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, allow_nan=False, separators=(',', ':'))
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    if os.name == 'posix':
        fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class Driving:
    def __init__(self, state, directory=None):
        self.state, self.directory = state, Path(directory) if directory else None
        self.settings = catalogue.defaults()
        self.settings_error = self.storage_error = ''
        self.specials = catalogue.Specials()
        self.alerts = {key: {'key': key, 'code': rule['code'], 'title': rule['title'], 'severity': rule['severity'],
                             'group': rule['group'], 'active': False, 'latched': False, 'acknowledged': False,
                             'condition': 'unknown', 'since_ms': None, 'context': {}, 'value': None,
                             'count': 0, 'last_ms': None, 'last_context': {}} for key, rule in RULES.items()}
        self.pending, self.normal_since = {}, {}
        self.current, self.started, self.idle_since = None, 0, None
        self.last_point = self.last_save = float('-inf')
        self.last_manual = float('-inf')
        self.marker_seq = self.alert_seq = 0
        self.history = []
        self.finished = []
        self.stopping = False
        self.lock = asyncio.Lock()
        self.settings_dirty = False
        if self.directory:
            try:
                path = self.directory / 'alerts.json'
                if path.exists():
                    self.settings = validate_settings(json.loads(path.read_text(encoding='utf-8')))
            except (OSError, ValueError, TypeError):
                self.settings_error = 'Could not read alert settings; defaults are active'

    def configure(self, settings):
        self.settings = validate_settings(settings)
        self.pending.clear()
        self.settings_dirty = True

    def conditions(self, snapshot):
        """Each alert's condition now: True, False, or None when it cannot be told."""
        result = {}
        for key, rule in RULES.items():
            settings = self.settings['rules'][key]
            if not settings['enabled']:
                result[key] = False
            elif 'special' in rule:
                result[key] = self.specials.check(rule['special'], settings, snapshot)
            else:
                result[key] = catalogue.clauses(rule, settings, snapshot)
            self.alerts[key]['value'] = catalogue.reading(rule, snapshot)
        return result

    @staticmethod
    def taillight_condition(snapshot):
        """The taillights silent while other modules are heard on the bus."""
        return catalogue.module_quiet(snapshot, 'taillights')

    @staticmethod
    def meth_condition(snapshot):
        return catalogue.Specials().check('meth', {}, snapshot)

    def evaluate(self, snapshot):
        now = self.state.clock()
        for key, condition in self.conditions(snapshot).items():
            alert = self.alerts[key]
            alert['condition'] = 'unknown' if condition is None else 'active' if condition else 'normal'
            if condition is not True:
                self.pending.pop(key, None)
                if condition is None:
                    self.normal_since.pop(key, None)
                    continue  # Missing telemetry never clears an active incident.
                since = self.normal_since.setdefault(key, now)
                if now - since >= 1:
                    alert['active'] = False
                    if alert['acknowledged']:
                        alert['latched'] = False
                continue
            self.normal_since.pop(key, None)
            if alert['active']:
                continue
            since = self.pending.setdefault(key, now)
            if now - since < self.settings['rules'][key]['delay']:
                continue
            context = self.context(snapshot)
            alert.update(active=True, latched=True, acknowledged=False, since_ms=snapshot['timestamp_ms'], context=context,
                         count=alert['count'] + 1, last_ms=snapshot['timestamp_ms'], last_context=context)
            self.alert_seq += 1
            self.bookmark(alert['title'], 'alert', snapshot, key)

    def acknowledge(self, key):
        if key not in self.alerts and key != 'all':
            raise ValueError('Unknown alert')
        for name, alert in self.alerts.items():
            if key in (name, 'all'):
                alert['acknowledged'] = True
                if not alert['active']:
                    alert['latched'] = False

    def context(self, snapshot):
        result = {key: {'value': snapshot.get('values', {}).get(key, {}).get('value'),
                      'quality': snapshot.get('values', {}).get(key, {}).get('quality', 'unavailable')}
                for key in CONTEXT}
        for sample in result.values():
            if isinstance(sample['value'], float) and not math.isfinite(sample['value']):
                sample['value'], sample['quality'] = None, 'fault'
        return result

    def start_drive(self, snapshot):
        self.started = self.state.clock()
        self.last_point = float('-inf')
        self.idle_since = None
        self.current = {'version': 1, 'name': f'drive-{uuid4().hex}.json', 'started_ms': snapshot['timestamp_ms'],
                        'ended_ms': None, 'duration_s': 0, 'mode': self.state.mode, 'status': 'recording',
                        'channels': CHANNELS, 'points': [], 'sample_seconds': .5, 'events': [],
                        'event_count': 0, 'stats': {}, 'logs': [], 'race_results': []}

    def bookmark(self, label='Driver bookmark', kind='manual', snapshot=None, rule=None):
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80 or any(ord(c) < 32 for c in label):
            raise ValueError('Bookmark label must be 1–80 printable characters')
        now = self.state.clock()
        if kind == 'manual' and now - self.last_manual < 1:
            raise ValueError('Wait one second between bookmarks')
        snapshot = snapshot or self.state.snapshot()
        if self.current is None:
            self.start_drive(snapshot)
        if kind == 'manual':
            self.last_manual = now
        self.marker_seq += 1
        log = None
        recorder = self.state.recorder
        if recorder and recorder.writer.path:
            log = {'name': recorder.writer.path.name, 'time_s': max(0, time.monotonic() - recorder.writer.started)}
        event = {'id': self.marker_seq, 't': max(0, now - self.started), 'timestamp_ms': snapshot['timestamp_ms'],
                 'label': label.strip(), 'kind': kind, 'rule': rule, 'log': log, 'context': self.context(snapshot)}
        self.current['events'] = (self.current['events'] + [event])[-250:]
        self.current['event_count'] += 1
        self.history = (self.history + [event])[-50:]
        # Prompt checkpoint on the next service tick; MLG carries the same marker ID.
        self.last_save = float('-inf')
        return deepcopy(event)

    def sample(self, snapshot):
        now = self.state.clock()
        rpm, speed = live(snapshot, 'engine.rpm'), live(snapshot, 'vehicle.speed_kph')
        if self.current is None and ((rpm is not None and rpm >= 300) or (speed is not None and speed > 2)):
            self.start_drive(snapshot)
        self.evaluate(snapshot)
        if self.current is None:
            return
        d = self.current
        d['duration_s'] = max(0, now - self.started)
        if now - self.last_point >= d['sample_seconds']:
            d['points'].append([round(d['duration_s'], 3), *[live(snapshot, key) for key in CHANNELS]])
            self.last_point = now
            if len(d['points']) > 10800:
                d['points'] = d['points'][::2]
                d['sample_seconds'] *= 2
        for key in ('engine.rpm', 'engine.boost_kpa', 'engine.coolant_c', 'engine.iat_c', 'vehicle.speed_kph'):
            value = live(snapshot, key)
            if value is not None:
                d['stats'][key] = max(value, d['stats'].get(key, value))
        oil = live(snapshot, 'engine.oil_pressure_psi')
        if oil is not None and rpm is not None and rpm >= 1500:
            d['stats']['oil_min_above_1500'] = min(oil, d['stats'].get('oil_min_above_1500', oil))
        name = snapshot.get('recording', {}).get('file')
        if name and name not in d['logs']:
            d['logs'] = (d['logs'] + [name])[-100:]
        d['race_results'] = [entry for entry in self.state.race.history if entry['timestamp_ms'] >= d['started_ms']]
        stopped = rpm is not None and rpm < 300 and (speed is None or speed <= 2)
        if stopped:
            if self.idle_since is None:
                self.idle_since = now
            elif now - self.idle_since >= 120:
                self.finish('Engine stopped')
        else:
            self.idle_since = None

    def finish(self, reason):
        if self.current is None:
            return
        self.current['race_results'] = deepcopy([entry for entry in self.state.race.history
                                                if entry['timestamp_ms'] >= self.current['started_ms']])
        self.current.update(status='complete', ended_ms=int(self.state.wall() * 1000), reason=reason)
        self.finished.append(self.current)
        self.finished = self.finished[-20:]
        self.current = None

    def snapshot(self):
        """Sent to the screen with every update, so kept small: the readings captured when an
        alert went off only while it is shown (latched); all of it is in details()."""
        alerts = [{**{k: v for k, v in alert.items() if k not in ('context', 'last_context')},
                   'context': deepcopy(alert['context']) if alert['latched'] else {}} for alert in self.alerts.values()]
        return {'settings': deepcopy(self.settings), 'alerts': alerts,
                'alert_seq': self.alert_seq, 'marker_seq': self.marker_seq,
                'last_event': deepcopy(self.history[-1]) if self.history else None,
                'current': self.summary(self.current) if self.current else None,
                'error': self.storage_error or self.settings_error}

    def details(self):
        """The Alerts tab's full picture (GET /drive/alerts): the settings and every alert with
        the readings from the last time it went off."""
        return {'settings': deepcopy(self.settings), 'alerts': deepcopy(list(self.alerts.values())),
                'error': self.storage_error or self.settings_error}

    @staticmethod
    def summary(d):
        return {key: deepcopy(d.get(key)) for key in ('name', 'started_ms', 'ended_ms', 'duration_s', 'mode', 'status', 'stats', 'event_count')}

    def disk_files(self):
        directory = self.directory / 'drives' if self.directory else None
        if directory is None or not directory.exists():
            return []
        return [p for p in directory.iterdir() if NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()]

    def read(self, name):
        if not NAME.fullmatch(name):
            raise FileNotFoundError()
        if self.current and name == self.current['name']:
            return deepcopy(self.current)
        for entry in self.finished:
            if entry['name'] == name:
                return deepcopy(entry)
        return self.read_disk(name)

    def read_disk(self, name):
        if not NAME.fullmatch(name):
            raise FileNotFoundError()
        if not self.directory:
            raise FileNotFoundError()
        path = self.directory / 'drives' / name
        if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
            raise FileNotFoundError()
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1 or data.get('name') != name:
            raise ValueError('Invalid drive review')
        if any(type(data.get(k)) not in (int, float) or not math.isfinite(data[k]) or data[k] < 0 for k in ('started_ms', 'duration_s')):
            raise ValueError('Invalid drive timestamps')
        if not isinstance(data.get('stats'), dict) or any(not isinstance(data.get(k), list) for k in ('points', 'events', 'channels', 'race_results')):
            raise ValueError('Invalid drive content')
        json.dumps(data, allow_nan=False)
        if data.get('status') == 'recording':
            data['status'] = 'interrupted'  # Recovered checkpoint, never claimed complete.
        return data

    async def get_review(self, name):
        if (self.current and self.current['name'] == name) or any(d['name'] == name for d in self.finished):
            return self.read(name)  # Snapshot mutable in-memory records on their owning event loop.
        return await asyncio.to_thread(self.read_disk, name)

    async def get_reviews(self):
        def disk():
            results = {}
            for path in self.disk_files():
                try:
                    results[path.name] = self.summary(self.read_disk(path.name))
                except (OSError, ValueError, TypeError, KeyError):
                    continue
            return results
        entries = await asyncio.to_thread(disk)
        entries.update({d['name']: self.summary(d) for d in self.finished})
        if self.current:
            entries[self.current['name']] = self.summary(self.current)
        return sorted(entries.values(), key=lambda d: (d['status'] == 'recording', d['started_ms']), reverse=True)[:21]

    async def save(self, force=False):
        if not self.directory:
            return
        async with self.lock:
            if self.settings_dirty:
                settings = dict(self.settings)
                self.settings_dirty = False
                try:
                    await asyncio.to_thread(atomic_write, self.directory / 'alerts.json', settings)
                    self.settings_error = ''
                except OSError:
                    self.settings_dirty = True
                    self.settings_error = 'Alert settings applied but could not be saved'
            now = self.state.clock()
            if not force and now - self.last_save < 15:
                return
            self.last_save = now
            documents = deepcopy(self.finished + ([self.current] if self.current else []))
            active = self.current['name'] if self.current else None
            def write():
                for doc in documents:
                    atomic_write(self.directory / 'drives' / doc['name'], doc)
                files = sorted(self.disk_files(), key=lambda p: p.stat().st_mtime)
                total = sum(p.stat().st_size for p in files)
                count = len(files)
                for path in files:
                    if count <= 20 and total <= 64 * 1024 * 1024:
                        break
                    if path.name == active:
                        continue
                    total -= path.stat().st_size
                    path.unlink()
                    count -= 1
            try:
                await asyncio.to_thread(write)
                self.finished = [d for d in self.finished if d['name'] not in {saved['name'] for saved in documents}]
                self.storage_error = ''
            except OSError:
                self.storage_error = 'Drive review could not be saved; check disk space and permissions'

    async def run(self):
        while not self.stopping:
            self.sample(self.state.snapshot())
            await self.save()
            await asyncio.sleep(.1)
        self.finish('Dashboard service stopped')
        await self.save(force=True)
