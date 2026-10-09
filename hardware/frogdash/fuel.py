"""Fuel gauge damping for a tank with no baffles.

The sender reports the float position several times a second. In a moving car the fuel
sloshes, so the raw reading swings, and a worn sender can drop out for a moment when
its wiper lifts. This turns that into a gauge a driver can read:

- a short median removes single wild readings,
- a slow average follows the level while driving (about 45 s) and a quick one while
  parked or with the engine off, so a fill-up shows within seconds,
- a brief loss of the sender keeps showing the last good level instead of blanking.

The undamped reading stays available as fuel.sender_pct for diagnosis and logs.
"""
import math
from collections import deque
from statistics import median

HOLD_S = 30.0        # Keep the last good level through a sender dropout this long.
TAU_MOVING_S = 45.0  # Time constant while driving or when speed is unknown.
TAU_STILL_S = 4.0    # Parked or engine off: follow the sender quickly.
SAMPLE_S = 0.25      # One reading into the median every quarter second...
WINDOW = 13          # ...over about three seconds.


class FuelGauge:
    def __init__(self, clock):
        self.clock = clock
        self.samples = deque(maxlen=WINDOW)
        self.level = None
        self.last_sample = float('-inf')
        self.last_good = float('-inf')
        self.updated = None

    def step(self, signal, still):
        """signal: the sender's fuel level sample (value, quality...); still: car parked or engine off."""
        now = self.clock()
        live = (signal is not None and signal.get('quality') == 'live' and isinstance(signal.get('value'), (int, float))
                and math.isfinite(signal['value']))
        sender = {**(signal or {}), 'source': 'Fuel sender (undamped)'} if signal else None
        if live:
            if now - self.last_sample >= SAMPLE_S or not self.samples:
                self.samples.append(signal['value'])
                self.last_sample = now
            target = median(self.samples)
            if self.level is None:
                self.level = target
            else:
                elapsed = min(max(now - self.updated, 0), 5)
                tau = TAU_STILL_S if still else TAU_MOVING_S
                self.level += (target - self.level) * (1 - math.exp(-elapsed / tau))
            self.updated = self.last_good = now
            return {'vehicle.fuel_pct': {**signal, 'value': round(self.level, 1)}, 'fuel.sender_pct': sender}
        if self.level is not None and now - self.last_good <= HOLD_S:
            # A dropout: show the last good level. The quality stays live so the gauge and
            # the range estimate do not flicker, and the source says what is happening.
            held = {'value': round(self.level, 1), 'quality': 'live', 'source': 'Fuel level held (sender dropout)',
                    'source_id': (signal or {}).get('source_id'), 'timestamp_ms': (signal or {}).get('timestamp_ms')}
            self.updated = now
            return {'vehicle.fuel_pct': held, 'fuel.sender_pct': sender or {**held, 'value': None, 'quality': 'unavailable'}}
        # Gone for good (or never seen): report it as it is, and start afresh when it returns.
        self.samples.clear()
        self.level = None
        missing = {'value': None, 'quality': 'unavailable', 'source_id': None, 'timestamp_ms': None}
        return {'vehicle.fuel_pct': dict(signal) if signal else missing, 'fuel.sender_pct': sender or missing}
