"""GPS performance timing, independent of display clients and CAN commands."""
import asyncio
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import time

from .driving import atomic_write

MPH = .44704
ACTIVE = {'armed', 'running'}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def distance(a, b):
    lat1, lat2 = map(math.radians, (a[0], b[0]))
    dlat, dlon = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 12742000 * math.asin(math.sqrt(min(1, max(0, h))))


class Race:
    def __init__(self, path=None, clock=time.monotonic, wall=time.time):
        self.path = Path(path) if path else None
        self.clock, self.wall = clock, wall
        self.history, self.gate = [], None
        self.storage_error, self.dirty = '', False
        self.stopping = False
        self.save_lock = asyncio.Lock()
        self.sample = None
        self.pending_epoch, self.pending = None, {}
        self.received = float('-inf')
        self.interval = None
        self.gps_reason = 'Waiting for timestamped USB GPS speed'
        self.reset()
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                json.dumps(data, allow_nan=False)  # Reject non-finite values in a damaged file.
                if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('history'), list):
                    raise ValueError('Invalid race file')
                gate = data.get('gate')
                if gate is not None and not self.position(gate):
                    raise ValueError('Invalid start/finish point')
                self.history = [x for x in data['history'][-50:] if isinstance(x, dict)]
                self.gate = gate
            except (OSError, ValueError, TypeError):
                self.storage_error = 'Could not read saved race results'

    @staticmethod
    def position(p):
        return isinstance(p, (tuple, list)) and len(p) == 2 and all(finite(v) for v in p) and abs(p[0]) <= 90 and abs(p[1]) <= 180

    def reset(self):
        self.mode, self.phase = 'accel', 'idle'
        self.message = 'Choose acceleration or laps'
        self.start = self.rest_since = self.departure = self.last_lap = None
        self.elapsed = self.distance_m = 0.
        self.splits, self.laps = {}, []
        self.lap_count, self.best_lap = 0, None
        self.outside = False
        self.warnings = []
        self.max_interval = 0.

    def fresh(self):
        return self.sample is not None and not self.gps_reason and self.clock() - self.received <= 1.5

    def command(self, action):
        if action == 'clear_gate':
            if self.phase in ACTIVE:
                raise ValueError('Stop the session before clearing its start/finish')
            self.gate, self.dirty = None, True
            self.message = 'Start/finish cleared; manual lap timing available'
            return
        if action == 'stop':
            if self.phase in ACTIVE:
                self.finish('stopped', 'Session stopped; unfinished splits omitted')
            return
        if action == 'reset':
            if self.phase in ACTIVE:
                raise ValueError('Stop the session before resetting')
            self.reset()
            return
        if action not in {'accel', 'laps', 'gate', 'lap'}:
            raise ValueError('Unknown race action')
        if not self.fresh():
            raise ValueError(self.gps_reason or 'USB GPS sample is stale')
        t, speed, pos = self.sample
        if action == 'lap':
            if self.mode != 'laps' or self.phase != 'running':
                raise ValueError('Start a lap session first')
            if t - self.last_lap < 15:
                raise ValueError('Minimum lap time is 15 seconds')
            self.mark_lap(t, 'manual')
            return
        if self.phase in ACTIVE:
            raise ValueError('Stop the current session first')
        if action == 'gate':
            if pos is None:
                raise ValueError('A current GPS position is required')
            self.gate = list(pos)
            self.dirty = True
            self.message = 'Start/finish saved: 20 m radius, rearm beyond 40 m'
            return
        if action == 'accel' and speed > .5 * MPH:
            raise ValueError('Come to a stop before arming acceleration')
        if action == 'laps' and pos is None:
            raise ValueError('A current GPS position is required for laps')
        self.reset()
        self.mode, self.phase = action, 'armed'
        self.message = 'Hold stationary for one second, then launch' if action == 'accel' else 'Cross the saved start/finish to begin' if self.gate else 'Lap timer started; use Mark lap'
        if action == 'laps' and not self.gate:
            self.phase, self.start, self.last_lap = 'running', t, t

    def invalidate(self, reason):
        self.gps_reason = reason
        self.rest_since = self.departure = None
        if self.phase in ACTIVE:
            self.finish('invalid', reason)

    def feed(self, report):
        """One complete speed sample per receiver epoch; partial TPVs never reuse speed."""
        if report.get('class') != 'TPV':
            return
        if report.get('mode') not in (2, 3) or report.get('status') in (5, 6, 8):
            self.invalidate('GPS fix lost')
            return
        if 'time' not in report:
            return
        try:
            epoch = datetime.fromisoformat(report['time'].replace('Z', '+00:00'))
            if epoch.tzinfo is None:
                raise ValueError()
            t = epoch.timestamp()
        except (ValueError, TypeError, AttributeError, OverflowError):
            self.invalidate('Invalid GPS timestamp')
            return
        if t != self.pending_epoch:
            self.pending_epoch, self.pending = t, {}
        self.pending.update(report)
        if 'speed' not in self.pending:
            return
        speed = self.pending['speed']
        if not finite(speed) or not 0 <= speed <= 200:
            self.invalidate('Invalid GPS speed')
            return
        pos = (self.pending.get('lat'), self.pending.get('lon'))
        pos = pos if self.position(pos) else None
        previous = self.sample
        if previous and t == previous[0]:
            if pos is not None:
                self.sample = (previous[0], previous[1], pos)
            return  # gpsd may publish multiple TPVs for the same measurement.
        if previous and t < previous[0]:
            self.invalidate('GPS time moved backwards')
            self.sample = None
            return
        if self.mode == 'laps' and self.phase in ACTIVE and pos is None:
            # A later TPV for this epoch can supply position. Never reuse the
            # previous epoch's coordinates; the freshness watchdog bounds waiting.
            return
        self.sample, self.received = (t, speed, pos), self.clock()
        self.gps_reason = ''
        if previous is None:
            return
        dt = t - previous[0]
        self.interval = dt
        if self.phase not in ACTIVE:
            return
        if dt > 1.5 or dt < .02:
            self.invalidate('GPS sample gap or invalid update rate')
            return
        if abs(speed - previous[1]) / dt > 16:
            self.invalidate('Implausible GPS speed jump')
            return
        self.max_interval = max(self.max_interval, dt)
        if dt > .25 and 'Coarse GPS timing (below 4 Hz)' not in self.warnings:
            self.warnings.append('Coarse GPS timing (below 4 Hz)')
        if self.mode == 'laps':
            if pos is None or previous[2] is None:
                self.invalidate('GPS position missing during lap session')
                return
            if distance(previous[2], pos) > max(30, (speed + previous[1]) * dt / 2 + 25):
                self.invalidate('Implausible GPS position jump')
                return
            self.tick_laps(previous, self.sample)
            return
        if self.phase == 'armed':
            if speed <= .5 * MPH:
                if self.rest_since is None:
                    self.rest_since = t
                if t - self.rest_since >= 1:
                    self.departure = t
                    self.message = 'Ready for launch'
                return
            if self.departure is None:
                self.rest_since = None
                self.message = 'Come to a stop and hold for one second'
                return
            # Start at the last stationary GPS epoch, including the launch interval.
            self.start, self.phase = self.departure, 'running'
            self.message = 'Measuring acceleration'
        self.elapsed = t - self.start
        old_distance = self.distance_m
        self.distance_m += (previous[1] + speed) * .5 * dt
        for name, threshold in [('0_30', 30 * MPH), ('0_60', 60 * MPH), ('0_100kph', 100 / 3.6)]:
            if name not in self.splits and previous[1] < threshold <= speed:
                self.splits[name] = previous[0] - self.start + dt * (threshold - previous[1]) / (speed - previous[1])
        for name, target in [('eighth', 201.168), ('quarter', 402.336)]:
            if name not in self.splits and old_distance < target <= self.distance_m:
                # Solve integral of linearly changing speed for crossing time.
                accel = (speed - previous[1]) / dt
                remaining = target - old_distance
                tau = 2 * remaining / (previous[1] + math.sqrt(max(0, previous[1]**2 + 2 * accel * remaining)))
                self.splits[name] = previous[0] - self.start + tau
                self.splits[name + '_mph'] = (previous[1] + accel * tau) / MPH
        if 'quarter' in self.splits:
            self.elapsed = self.splits['quarter']
            self.distance_m = 402.336
            self.finish('complete', 'Quarter mile complete')
        elif self.elapsed > 180:
            self.finish('stopped', 'Acceleration session timed out')

    def tick_laps(self, previous, current):
        t, speed, pos = current
        if self.gate:
            d = distance(pos, self.gate)
            if d >= 40:
                self.outside = True
            if self.outside and d <= 20 and speed >= 2 * MPH:
                before = distance(previous[2], self.gate)
                crossing = previous[0] + (t - previous[0]) * min(1, max(0, (before - 20) / max(.001, before - d)))
                self.outside = False
                if self.phase == 'armed':
                    self.start = self.last_lap = crossing
                    self.phase, self.message = 'running', 'Lap timer running'
                elif crossing - self.last_lap >= 15:
                    self.mark_lap(crossing, 'gps')
        if self.phase == 'running':
            self.elapsed = t - self.last_lap

    def mark_lap(self, t, source):
        duration = t - self.last_lap
        self.best_lap = duration if self.best_lap is None else min(self.best_lap, duration)
        self.lap_count += 1
        self.laps.append({'number': self.lap_count, 'seconds': duration, 'source': source, 'delta': duration - self.best_lap})
        self.laps = self.laps[-50:]
        self.last_lap, self.elapsed, self.outside = t, 0, False
        self.message = f'Lap {self.lap_count} recorded ({source})'

    def finish(self, phase, message):
        self.phase, self.message = phase, message
        entry = {'timestamp_ms': int(self.wall() * 1000), 'mode': self.mode, 'phase': phase,
                 'message': message, 'splits': dict(self.splits), 'laps': deepcopy(self.laps),
                 'lap_count': self.lap_count, 'best_lap': self.best_lap,
                 'warnings': list(self.warnings), 'max_interval': self.max_interval}
        self.history = (self.history + [entry])[-50:]
        self.dirty = True

    def tick(self):
        if self.phase in ACTIVE and not self.fresh():
            self.invalidate('USB GPS sample is stale')

    def snapshot(self):
        return {'mode': self.mode, 'phase': self.phase, 'message': self.message,
                'elapsed': self.elapsed, 'distance_m': self.distance_m, 'splits': dict(self.splits),
                'laps': deepcopy(self.laps), 'lap_count': self.lap_count, 'best_lap': self.best_lap,
                'gate': self.gate, 'fresh': self.fresh(), 'gps_reason': self.gps_reason,
                'interval': self.interval, 'warnings': list(self.warnings),
                'history': [{k: deepcopy(v) for k, v in entry.items() if k != 'laps'} for entry in self.history[-10:]],
                'storage_error': self.storage_error}

    async def save(self):
        async with self.save_lock:
            if not self.dirty or not self.path:
                return
            data = {'version': 1, 'gate': self.gate, 'history': deepcopy(self.history)}
            self.dirty = False
            def write():
                atomic_write(self.path, data)
            try:
                await asyncio.to_thread(write)
                self.storage_error = ''
            except OSError:
                self.dirty = True
                self.storage_error = 'Could not save race results; check disk space and permissions'

    async def run(self):
        while not self.stopping:
            self.tick()
            await self.save()
            await asyncio.sleep(.1 if not self.storage_error else 1)
        if self.phase in ACTIVE:
            self.finish('stopped', 'Service stopped; session ended')
        await self.save()
