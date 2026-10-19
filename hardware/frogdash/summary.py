"""The drive summary: what this drive was, shown while the Pi shuts down after the key goes off.

A drive starts the first time the engine runs (1 s at 300 RPM or more) and ends when the
PiSugar reports the ignition gone (the shutdown countdown starts), or when the dash stops.
On the way it keeps: distance (the trip odometer), time, top speed, peak boost, highest
RPM and coolant, lowest oil pressure above 1,500 RPM, seconds the water/meth pump sprayed,
knock events, alerts raised, and problems the event log noted. The ended drive is saved
(last-drive.json in the data folder) and written to the event log, so it goes up with the
report after the next update; the screen shows it during the countdown (summary.js).
"""
import asyncio
import json
import math
import os
from pathlib import Path
import time

SAMPLE_S = .5
START_RPM = 300
START_HOLD_S = 1.0


def live(values, key):
    sample = values.get(key) or {}
    value = sample.get('value')
    if sample.get('quality') != 'live' or value is None or isinstance(value, bool):
        return None
    return value if not isinstance(value, float) or math.isfinite(value) else None


class DriveSummary:
    def __init__(self, state, folder, clock=time.monotonic, wall=time.time):
        self.state, self.path, self.clock, self.wall = state, Path(folder) / 'last-drive.json', clock, wall
        self.current = None
        self.last = self.load()
        self.running_since = None
        self.previous = None        # (clock, values) of the last sample
        self.knocking = False
        self.alerting = set()
        self.ended_by_key = False   # The drive just ended because the ignition went off
        self.stopping = False

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) and 'started' in data else None
        except (OSError, ValueError):
            return None

    def odometer(self):
        try:
            return float(self.state.trip.snapshot().get('odometer_km'))
        except (AttributeError, TypeError, ValueError):
            return None

    def start(self, now):
        self.current = {'started': round(self.wall(), 1), 'ended': None, 'duration_s': 0, 'distance_km': 0.0,
                        'top_speed_kph': None, 'peak_boost_kpa': None, 'max_rpm': None, 'max_coolant_c': None,
                        'min_oil_psi': None, 'meth_spray_s': 0.0, 'knock_events': 0, 'alerts': 0, 'problems': 0,
                        'ended_by': None}
        self.start_odometer = self.odometer()
        self.started_clock = now
        self.knocking, self.alerting, self.ended_by_key = False, set(), False

    def finish(self, reason):
        if not self.current:
            return
        d = self.current
        d['ended'], d['ended_by'] = round(self.wall(), 1), reason
        log = getattr(self.state, 'eventlog', None)
        if log:
            d['problems'] = sum(1 for e in log.recent if e.get('t', 0) >= d['started'] and e.get('level') in ('warn', 'error'))
        self.last, self.current = d, None
        self.running_since = None
        try:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(d), encoding='utf-8')
            os.replace(tmp, self.path)
        except OSError:
            pass
        if log:
            miles = d['distance_km'] / 1.609344
            parts = [f"{miles:.1f} mi", f"{round(d['duration_s'] / 60)} min"]
            if d['top_speed_kph'] is not None:
                parts.append(f"top {d['top_speed_kph'] / 1.609344:.0f} mph")
            if d['peak_boost_kpa'] is not None:
                parts.append(f"peak boost {d['peak_boost_kpa'] * .1450377:.1f} psi")
            parts.append(f"meth {d['meth_spray_s']:.0f} s")
            if d['knock_events']:
                parts.append(f"{d['knock_events']} knock")
            log.write('info', 'drive', 'Drive ended: ' + ', '.join(parts), d)

    def sample(self, snapshot):
        now = self.clock()
        values = snapshot.get('values') or {}
        rpm = live(values, 'engine.rpm')
        ups = ((snapshot.get('system') or {}).get('ups') or {})
        key_off = ups.get('available') is True and ups.get('input_present') is False
        if self.current is None:
            if key_off:
                return
            if rpm is not None and rpm >= START_RPM:
                self.running_since = self.running_since if self.running_since is not None else now
                if now - self.running_since >= START_HOLD_S:
                    self.start(now)
            else:
                self.running_since = None
            if self.current is None:
                return
        d = self.current
        dt = 0.0 if self.previous is None else min(2.0, max(0.0, now - self.previous))
        self.previous = now
        d['duration_s'] = round(now - self.started_clock)
        odometer = self.odometer()
        if odometer is not None and self.start_odometer is not None:
            d['distance_km'] = round(max(0.0, odometer - self.start_odometer), 3)
        elif odometer is not None:
            self.start_odometer = odometer
        for key, field in (('vehicle.speed_kph', 'top_speed_kph'), ('engine.boost_kpa', 'peak_boost_kpa'),
                           ('engine.rpm', 'max_rpm'), ('engine.coolant_c', 'max_coolant_c')):
            value = live(values, key)
            if value is not None and (d[field] is None or value > d[field]):
                d[field] = round(value, 1)
        oil = live(values, 'engine.oil_pressure_psi')
        if oil is not None and rpm is not None and rpm >= 1500 and (d['min_oil_psi'] is None or oil < d['min_oil_psi']):
            d['min_oil_psi'] = round(oil, 1)
        if (values.get('meth.state') or {}).get('value') == 'SPRAYING' or (snapshot.get('meth_tune') or {}).get('pump_on'):
            d['meth_spray_s'] = round(d['meth_spray_s'] + dt, 1)
        knocking = any((values.get(key) or {}).get('quality') == 'live' and (values.get(key) or {}).get('value') is True
                       for key in ('knock.warning', 'knock.critical'))
        if knocking and not self.knocking:
            d['knock_events'] += 1
        self.knocking = knocking
        active = {a.get('key') for a in ((snapshot.get('drive') or {}).get('alerts') or []) if isinstance(a, dict) and a.get('active')}
        d['alerts'] += len(active - self.alerting)
        self.alerting = active
        if key_off:
            self.ended_by_key = True
            self.finish('ignition off')

    def snapshot(self):
        ups = ((self.state.health.status if getattr(self.state, 'health', None) else {}) or {}).get('ups') or {}
        countdown = ups.get('available') is True and ups.get('input_present') is False
        return {'current': dict(self.current) if self.current else None, 'last': dict(self.last) if self.last else None,
                'shutting_down': countdown or ups.get('state') == 'shutdown_requested',
                'remaining_s': ups.get('remaining_seconds') if countdown else None}

    async def run(self):
        while not self.stopping:
            try:
                self.sample(self.state.snapshot())
            except Exception:   # The summary must never take the dash down.
                pass
            await asyncio.sleep(SAMPLE_S)
