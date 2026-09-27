"""Setup, portable configuration, support reports and maintenance records."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import sys
from uuid import uuid4

from .driving import atomic_write, validate_settings
from .fuel import validate as validate_sender
from .parking import parked, require_parked
from .trip import validate as validate_trip, bucket, number
from .race import Race

UI_KEYS = {'frogdash.appearance.v1', 'frogdash.driving.v1', 'frogdash.units.v1'}
VERSION = (Path(__file__).resolve().parents[2] / 'VERSION').read_text().strip()
CHECKS = {'boot', 'crank', 'gps_loss', 'can_loss', 'storage', 'recording', 'display', 'controls'}


def validate_ui(ui):
    if not isinstance(ui, dict) or not set(ui) <= UI_KEYS or len(json.dumps(ui, allow_nan=False)) > 4500000:
        raise ValueError('Invalid display preferences')
    for key, value in ui.items():
        if not isinstance(value, dict):
            raise ValueError('Display preferences must be objects')
    return deepcopy(ui)


def validate_maintenance(items):
    if not isinstance(items, list) or len(items) > 30:
        raise ValueError('At most 30 maintenance reminders')
    for item in items:
        if not isinstance(item, dict) or set(item) != {'id', 'name', 'km', 'hours', 'days', 'baseline_km', 'baseline_hours', 'baseline_ms', 'history'}:
            raise ValueError('Invalid maintenance reminder')
        if not isinstance(item['id'], str) or not re.fullmatch('[0-9a-f]{32}', item['id']):
            raise ValueError('Invalid reminder ID')
        if not isinstance(item['name'], str) or not 1 <= len(item['name'].strip()) <= 60 or any(ord(c) < 32 for c in item['name']):
            raise ValueError('Reminder name must be 1–60 printable characters')
        for key in ('km', 'hours', 'days', 'baseline_km', 'baseline_hours', 'baseline_ms'):
            if not number(item[key], 0, 1e15 if key == 'baseline_ms' else 1e12):
                raise ValueError('Invalid maintenance interval')
        if not any(item[k] > 0 for k in ('km', 'hours', 'days')):
            raise ValueError('Set at least one maintenance interval')
        if not isinstance(item['history'], list) or len(item['history']) > 50 or any(not isinstance(h, dict) or set(h) != {'km', 'hours', 'timestamp_ms'} or not all(number(v, 0, 1e15 if k == 'timestamp_ms' else 1e12) for k, v in h.items()) for h in item['history']):
            raise ValueError('Invalid service history')
    if len({item['id'] for item in items}) != len(items):
        raise ValueError('Duplicate reminder ID')
    return deepcopy(items)


def validate_ops(data):
    if not isinstance(data, dict) or set(data) != {'ui', 'maintenance', 'checks'}:
        raise ValueError('Invalid setup data')
    checks = data['checks']
    if not isinstance(checks, dict) or not set(checks) <= CHECKS or any(not number(v, 0, 1e15) for v in checks.values()):
        raise ValueError('Invalid acceptance checks')
    return dict(ui=validate_ui(data['ui']), maintenance=validate_maintenance(data['maintenance']), checks=dict(checks))


class Operations:
    def __init__(self, state, directory=None):
        self.state, self.directory = state, Path(directory) if directory else None
        self.data = dict(ui={}, maintenance=[], checks={})
        self.error = ''
        self.lock = asyncio.Lock()
        self.restoring = False
        self.heartbeats = {}
        self.events = []
        try:
            self.os_name = platform.freedesktop_os_release().get('PRETTY_NAME', platform.system())
        except OSError:
            self.os_name = platform.system()
        try:
            self.model = Path('/proc/device-tree/model').read_text().strip('\0\n')
        except OSError:
            self.model = platform.machine()
        if self.directory and (self.directory / 'operations.json').exists():
            try:
                self.data = validate_ops(json.loads((self.directory / 'operations.json').read_text()))
            except (OSError, ValueError, TypeError, KeyError):
                self.error = 'Setup data could not be loaded'

    async def save(self):
        if self.directory:
            await asyncio.to_thread(atomic_write, self.directory / 'operations.json', deepcopy(self.data))

    def event(self, message):
        self.events.append(dict(timestamp_ms=int(self.state.wall() * 1000), message=str(message)[:200]))
        self.events = self.events[-100:]

    def maintenance(self):
        total = self.state.trip.counters['total']
        result = []
        for item in self.data['maintenance']:
            elapsed = dict(km=max(0, total['km'] - item['baseline_km']),
                           hours=max(0, total['engine_s'] / 3600 - item['baseline_hours']),
                           days=max(0, (self.state.wall() * 1000 - item['baseline_ms']) / 86400000))
            remaining = {key: item[key] - elapsed[key] for key in elapsed if item[key] > 0}
            result.append({**item, 'remaining': remaining, 'due': any(n <= 0 for n in remaining.values())})
        return result

    def status(self):
        return dict(version=VERSION, os=self.os_name, model=self.model, python=sys.version.split()[0], parked=parked(self.state),
                    maintenance=self.maintenance(), checks=self.data['checks'], error=self.error,
                    restore_pending=self.restoring,
                    capabilities=[
                        dict(module='Water / meth', command='Acknowledged by 0x30A', readback='Live mode/duty/faults', persistence='Not guaranteed by current firmware'),
                        dict(module='Knock', command='Acknowledged by 0x30A', readback='Configuration refresh supported', persistence='Not guaranteed by current firmware'),
                        dict(module='Taillights', command='Sent only; no ACK defined', readback='Lighting state and brightness telemetry', persistence='Not confirmed'),
                        dict(module='Fuel sender', command='Local read-only ADC', readback=self.state.fuel.snapshot()['message'], persistence='Calibration stored on Pi')])

    async def change(self, body):
        require_parked(self.state)
        if self.restoring:
            raise ValueError('Restore recovery pending; restart service to finish')
        if not isinstance(body, dict) or len(body) != 1:
            raise ValueError('Expected one setup action')
        async with self.lock:
            require_parked(self.state)
            if self.restoring:
                raise ValueError('Restore recovery pending; restart service to finish')
            before = deepcopy(self.data)
            try:
                if set(body) == {'ui'}:
                    self.data['ui'] = validate_ui(body['ui'])
                elif set(body) == {'check'} and body['check'] in CHECKS:
                    self.data['checks'][body['check']] = int(self.state.wall() * 1000)
                elif set(body) == {'maintenance'}:
                    action = body['maintenance']
                    if not isinstance(action, dict):
                        raise ValueError('Invalid maintenance action')
                    total = self.state.trip.counters['total']
                    baseline = dict(baseline_km=total['km'], baseline_hours=total['engine_s'] / 3600, baseline_ms=int(self.state.wall() * 1000))
                    if set(action) == {'name', 'km', 'hours', 'days'}:
                        item = {**action, 'id': uuid4().hex, **baseline, 'history': []}
                        self.data['maintenance'] = validate_maintenance([*self.data['maintenance'], item])
                    elif set(action) in ({'complete'}, {'delete'}):
                        key = next(iter(action))
                        item = next((i for i in self.data['maintenance'] if i['id'] == action[key]), None)
                        if not item:
                            raise ValueError('Unknown reminder')
                        if key == 'delete':
                            self.data['maintenance'].remove(item)
                        else:
                            item['history'] = [*item['history'], dict(km=total['km'], hours=total['engine_s'] / 3600, timestamp_ms=baseline['baseline_ms'])][-50:]
                            item.update(baseline)
                    else:
                        raise ValueError('Invalid maintenance fields')
                else:
                    raise ValueError('Unknown setup action')
                await self.save()
                self.error = ''
            except Exception:
                self.data = before
                raise

    def backup(self, ui=None):
        trip = self.state.trip
        return deepcopy(dict(format='frogdash-backup', version=1, software=VERSION,
             created_ms=int(self.state.wall() * 1000), operations={**self.data, 'ui': validate_ui(ui) if ui is not None else self.data['ui']},
             alerts=self.state.driving.settings, sender=self.state.fuel.settings,
             trip=dict(settings=trip.settings, counters=trip.counters, learned=trip.learned, manual_l=trip.manual_l),
             race=dict(gate=self.state.race.gate, history=self.state.race.history)))

    def validate_backup(self, data):
        if not isinstance(data, dict) or set(data) != {'format', 'version', 'software', 'created_ms', 'operations', 'alerts', 'sender', 'trip', 'race'} or data['format'] != 'frogdash-backup' or data['version'] != 1:
            raise ValueError('Unsupported Frogdash backup')
        if len(json.dumps(data, allow_nan=False)) > 6000000:
            raise ValueError('Backup too large')
        result = deepcopy(data)
        result['operations'] = validate_ops(data['operations'])
        result['alerts'] = validate_settings(data['alerts'])
        result['sender'] = validate_sender(data['sender'])
        trip = result['trip']
        if not isinstance(trip, dict) or set(trip) != {'settings', 'counters', 'learned', 'manual_l'}:
            raise ValueError('Invalid trip backup')
        trip['settings'] = validate_trip(trip['settings'])
        if not isinstance(trip['counters'], dict) or set(trip['counters']) != {'a', 'b', 'total'}:
            raise ValueError('Invalid trip counters')
        for item in trip['counters'].values():
            if not isinstance(item, dict) or set(item) != set(bucket()) or not all(number(v) for v in item.values()):
                raise ValueError('Invalid trip counters')
        if not isinstance(trip['learned'], dict) or set(trip['learned']) != {'km', 'litres'} or not all(number(v) for v in trip['learned'].values()):
            raise ValueError('Invalid economy history')
        if trip['manual_l'] is not None and not number(trip['manual_l'], 0, trip['settings']['capacity_l']):
            raise ValueError('Invalid fuel inventory')
        race = result['race']
        if not isinstance(race, dict) or set(race) != {'gate', 'history'} or (race['gate'] is not None and not Race.position(race['gate'])) or not isinstance(race['history'], list) or len(race['history']) > 50 or any(not isinstance(r, dict) for r in race['history']):
            raise ValueError('Invalid race history')
        return result

    async def restore(self, data, recovery=False):
        if not recovery:
            require_parked(self.state)
            if self.state.race.phase in ('armed', 'running') or self.state.controls.test_owner:
                raise ValueError('Stop race timing and pump tests before restoring')
        data = self.validate_backup(data)
        async with self.lock:
            if not recovery:
                require_parked(self.state)
                if self.state.race.phase in ('armed', 'running') or self.state.controls.test_owner:
                    raise ValueError('Stop race timing and pump tests before restoring')
            self.restoring = True
            if self.directory and not recovery:
                try:
                    await asyncio.to_thread(atomic_write, self.directory / 'restore-pending.json', data)
                except Exception:
                    self.restoring = False
                    raise
            try:
                self.data = data['operations']
                self.state.driving.configure(data['alerts'])
                self.state.fuel.configure(data['sender'])
                trip = self.state.trip
                trip.configure(data['trip']['settings'])
                trip.counters = data['trip']['counters']
                trip.learned = data['trip']['learned']
                trip.manual_l = data['trip']['manual_l']
                trip.manual_valid = False
                trip.previous = None
                self.state.race.history = data['race']['history']
                self.state.race.gate = data['race']['gate']
                self.state.race.dirty = True
                await self.save()
                await trip.save(force=True)
                await self.state.driving.save(force=True)
                if trip.error or self.state.driving.settings_error:
                    raise OSError('Could not persist restored settings')
                if self.directory:
                    await asyncio.to_thread(atomic_write, self.directory / 'sender.json', data['sender'])
                async with self.state.race.save_lock:
                    if self.state.race.path:
                        await asyncio.to_thread(atomic_write, self.state.race.path, dict(version=1, **data['race']))
                    self.state.race.dirty = False
                    self.state.race.storage_error = ''
                if self.directory:
                    (self.directory / 'restore-pending.json').unlink(missing_ok=True)
                self.restoring, self.error = False, ''
                self.event('Configuration restored; manual fuel amount requires confirmation')
            except Exception:
                self.error = 'Restore interrupted; restart service to finish from the saved recovery file'
                raise
        return self.data['ui']

    async def recover(self):
        if self.directory and (self.directory / 'restore-pending.json').exists():
            data = json.loads((self.directory / 'restore-pending.json').read_text())
            await self.restore(data, recovery=True)

    def diagnostic(self):
        snapshot = self.state.snapshot()
        # Deliberately omit raw CAN, GPS coordinates, logs, Wi-Fi secrets and artwork.
        return dict(format='frogdash-diagnostics', version=1, timestamp=datetime.now(timezone.utc).isoformat(),
                    software=self.status(), transport=snapshot['transport'], modules=snapshot['modules'],
                    health=snapshot['system'], gps=snapshot['gps'], recording=snapshot['recording'], can_errors=snapshot['can_errors'],
                    sender=self.state.fuel.snapshot(), trip_quality={k: snapshot['trip'][k] for k in ('gps_live', 'fuel_live', 'fuel_source', 'error')},
                    signal_quality={k: v['quality'] for k, v in snapshot['values'].items()},
                    controller_capabilities=self.status()['capabilities'], recent_controller_result=self.state.controls.last,
                    alert_settings=self.state.driving.settings, fuel_estimate_settings=self.state.trip.settings,
                    recent_events=self.events)
