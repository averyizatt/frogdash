"""Persistent GPS trip counters and explicitly calibrated fuel estimates."""
import asyncio
from copy import deepcopy
import json
import math
from pathlib import Path

from .driving import atomic_write

DEFAULTS = dict(enabled=False, capacity_l=15.4 * 3.785411784, reserve_l=3, injector_cc_min=440,
                injectors=4, pw2_injectors=0, pulses_per_rev=.5, dead_ms=0, correction=1)
LIMITS = dict(capacity_l=(0, 250), reserve_l=(0, 50), injector_cc_min=(0, 5000),
              injectors=(0, 16), pw2_injectors=(0, 16), pulses_per_rev=(0, 8), dead_ms=(0, 5), correction=(.25, 4))
SIGNALS = {'trip.a_km': 'km', 'trip.b_km': 'km', 'trip.total_km': 'km',
           'fuel.flow_lph': 'L/h', 'fuel.remaining_l': 'L', 'fuel.range_km': 'km',
           'fuel.instant_mpg': 'US mpg', 'fuel.average_mpg': 'US mpg'}
MPG = 235.214583  # US MPG = constant / L per 100 km


def number(value, low=0, high=1e12):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate(data):
    if not isinstance(data, dict) or set(data) != set(DEFAULTS) or type(data['enabled']) is not bool:
        raise ValueError('Expected all fuel calibration fields')
    for key, (low, high) in LIMITS.items():
        if not number(data[key], low, high):
            raise ValueError(f'{key} must be between {low} and {high}')
    if int(data['injectors']) != data['injectors']:
        raise ValueError('Injector count must be a whole number')
    if int(data['pw2_injectors']) != data['pw2_injectors'] or data['pw2_injectors'] > data['injectors']:
        raise ValueError('PW2 injector count must be a whole number within total count')
    if data['capacity_l'] and data['reserve_l'] >= data['capacity_l']:
        raise ValueError('Reserve must be smaller than tank capacity')
    if data['enabled'] and (data['injector_cc_min'] <= 0 or data['injectors'] < 1 or data['pulses_per_rev'] <= 0):
        raise ValueError('Enter injector flow, count and pulses per revolution before enabling fuel estimates')
    return dict(data)


def bucket():
    return dict(km=0., moving_s=0., engine_s=0., fuel_l=0., paired_km=0., paired_l=0., missing_s=0.)


class Trip:
    def __init__(self, state, path=None):
        self.state, self.path = state, Path(path) if path else None
        self.settings = dict(DEFAULTS)
        self.counters = {key: bucket() for key in ('a', 'b', 'total')}
        self.learned = dict(km=0., litres=0.)
        self.manual_l = None
        self.manual_valid = False
        self.previous = None
        self.current = (None, None, None, None)
        self.error = ''
        self.load_error = ''
        self.stopping = False
        self.last_save = float('-inf')
        self.lock = asyncio.Lock()
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                settings = validate(data['settings'])
                # Earlier installations saved zero as an unconfigured pulse rate.
                # The supplied tune confirms 2 squirts, alternating, four-stroke.
                if not settings['enabled'] and settings['pulses_per_rev'] == 0:
                    settings['pulses_per_rev'] = DEFAULTS['pulses_per_rev']
                counters = data['counters']
                if data['version'] != 1 or set(counters) != {'a', 'b', 'total'}:
                    raise ValueError('Invalid trip file')
                for item in counters.values():
                    if set(item) != set(bucket()) or not all(number(v) for v in item.values()):
                        raise ValueError('Invalid counters')
                learned = data['learned']
                if set(learned) != {'km', 'litres'} or not all(number(v) for v in learned.values()):
                    raise ValueError('Invalid economy history')
                manual = data.get('manual_l')
                if manual is not None and not number(manual, 0, settings['capacity_l']):
                    raise ValueError('Invalid tank amount')
                self.settings, self.counters, self.learned, self.manual_l = settings, counters, learned, manual
                # Fuel could have been used while this service was stopped.
            except (OSError, ValueError, TypeError, KeyError):
                self.error = self.load_error = 'Could not read trip storage; counters start at zero'

    @staticmethod
    def value(snapshot, key, high):
        sample = snapshot.get('values', {}).get(key, {})
        value = sample.get('value')
        return value if sample.get('quality') == 'live' and number(value, 0, high) else None

    def inputs(self, snapshot):
        speed = self.value(snapshot, 'vehicle.speed_kph', 360)
        speed = 0 if speed is not None and speed < 1 else speed
        rpm = self.value(snapshot, 'engine.rpm', 12000)
        level = self.value(snapshot, 'vehicle.fuel_pct', 100)
        flow = None
        p = self.settings
        if p['enabled'] and rpm is not None:
            if rpm == 0:
                flow = 0.
            else:
                total = 0.
                for signal, count in [('ecu.pw1_ms', p['injectors'] - p['pw2_injectors']), ('ecu.pw2_ms', p['pw2_injectors'])]:
                    if not count:
                        continue
                    pw = self.value(snapshot, signal, 100)
                    if pw is None or pw * rpm * p['pulses_per_rev'] / 60000 > 1:
                        break
                    total += count * max(0, pw - p['dead_ms']) * rpm * p['pulses_per_rev'] / 60000
                else:
                    flow = p['injector_cc_min'] * total * .06 * p['correction']
        return speed, rpm, flow, level

    def sample(self, snapshot):
        now = self.state.clock()
        speed, rpm, flow, level = self.inputs(snapshot)
        self.current = (speed, rpm, flow, level)
        previous, self.previous = self.previous, (now, speed, rpm, flow)
        if previous is None:
            return
        t, old_speed, old_rpm, old_flow = previous
        dt = now - t
        if dt <= 0:
            return
        if dt > 1:
            self.manual_valid = False
            for item in self.counters.values():
                item['missing_s'] += dt
            return
        distance = (speed + old_speed) * dt / 7200 if speed is not None and old_speed is not None else None
        fuel = (flow + old_flow) * dt / 7200 if flow is not None and old_flow is not None else None
        running = rpm is not None and old_rpm is not None and rpm >= 300 and old_rpm >= 300
        stationary_engine = rpm == old_rpm == 0
        for item in self.counters.values():
            item['km'] += distance or 0
            item['moving_s'] += dt if distance is not None and distance > 0 else 0
            item['engine_s'] += dt if running else 0
            item['fuel_l'] += fuel or 0
            if distance is not None and fuel is not None:
                item['paired_km'] += distance
                item['paired_l'] += fuel
            elif not stationary_engine:
                item['missing_s'] += dt
        if distance is not None and fuel is not None:
            self.learned['km'] += distance
            self.learned['litres'] += fuel
        if self.manual_valid:
            if fuel is not None:
                self.manual_l = max(0, self.manual_l - fuel)
            elif not stationary_engine:
                self.manual_valid = False

    def configure(self, data):
        settings = validate(data)
        if settings != self.settings:
            self.learned = dict(km=0., litres=0.)
            self.manual_valid = False
            self.manual_l = None
            self.previous = None
            self.current = (None, None, None, None)
        self.settings = settings

    def reset(self, name):
        if name not in ('a', 'b'):
            raise ValueError('Only Trip A and Trip B can be reset')
        self.counters[name] = bucket()

    def set_fuel(self, litres):
        if not self.settings['enabled'] or self.settings['capacity_l'] <= 0:
            raise ValueError('Enable calibrated fuel estimation and set tank capacity first')
        if not number(litres, 0, self.settings['capacity_l']):
            raise ValueError('Fuel amount must be between zero and tank capacity')
        self.manual_l, self.manual_valid = litres, True

    def snapshot(self):
        speed, rpm, flow, level = self.current
        # A paused sampler must not leave instantaneous estimates looking live.
        fresh = self.previous is not None and 0 <= self.state.clock() - self.previous[0] <= 1
        if not fresh:
            speed = flow = level = None
        p = self.settings
        remaining = None
        source = 'No fuel amount'
        if p['capacity_l'] > 0 and level is not None:
            remaining, source = level * p['capacity_l'] / 100, 'Calibrated fuel sender'
        elif self.manual_valid and fresh:
            remaining, source = self.manual_l, 'Manual amount minus estimated use'
        elif self.manual_l is not None:
            source = 'Confirm remaining fuel after restart or missing fuel data'
        learned = self.learned
        economy = learned['litres'] * 100 / learned['km'] if learned['km'] >= 1 and learned['litres'] >= .02 else None
        range_km = max(0, remaining - p['reserve_l']) * 100 / economy if remaining is not None and economy else None
        instant = speed / flow * MPG / 100 if speed is not None and speed >= 1 and flow is not None and flow > .01 else None
        counters = deepcopy(self.counters)
        for item in counters.values():
            item['mpg'] = item['paired_km'] / item['paired_l'] * MPG / 100 if item['paired_km'] >= 1 and item['paired_l'] >= .02 else None
        return dict(settings=dict(p), counters=counters, learned=dict(learned), flow_lph=flow,
                    instant_mpg=instant, average_mpg=MPG / economy if economy else None,
                    range_km=range_km, remaining_l=remaining, last_manual_l=self.manual_l,
                    fuel_source=source, coasting=speed is not None and speed >= 1 and flow == 0,
                    gps_live=speed is not None, fuel_live=flow is not None,
                    error=self.error, estimated=True)

    def values(self):
        view = self.snapshot()
        data = {'trip.a_km': self.counters['a']['km'], 'trip.b_km': self.counters['b']['km'],
                'trip.total_km': self.counters['total']['km']}
        data.update({'fuel.' + key: view[key] for key in ('flow_lph', 'remaining_l', 'range_km', 'instant_mpg', 'average_mpg')})
        return {key: dict(value=value, quality='live' if value is not None else 'unavailable',
                          source_id=None, source='Trip computer (fuel estimated)', timestamp_ms=int(self.state.wall() * 1000)) for key, value in data.items()}

    async def save(self, force=False):
        if not self.path:
            return
        async with self.lock:
            now = self.state.clock()
            if not force and now - self.last_save < 15:
                return
            data = deepcopy(dict(version=1, settings=self.settings, counters=self.counters,
                                 learned=self.learned, manual_l=self.manual_l))
            self.last_save = now
            try:
                await asyncio.to_thread(atomic_write, self.path, data)
                self.error = self.load_error
            except OSError:
                self.error = 'Trip changes are in memory only; could not save to disk'

    async def run(self):
        while not self.stopping:
            self.sample(self.state.snapshot())
            await self.save()
            await asyncio.sleep(.1)
        await self.save(force=True)
