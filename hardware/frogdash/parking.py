"""Stationary confirmation shared by setup and actuator test gates."""
import math
from .protocol import TIMEOUTS


def parked(state):
    def fresh(name):
        if name == 'vehicle.speed_kph' and state.gps:
            sample = state.gps.values().get(name, {})
        else:
            samples = [v for (key, source), v in state.samples.items() if key == name and
                       state.connected and 0 <= state.clock() - v['seen'] <= TIMEOUTS.get(source, .5) and v['quality'] == 'live']
            sample = max(samples, key=lambda s: s['seen']) if samples else {}
        value = sample.get('value')
        return value if sample.get('quality') == 'live' and type(value) in (int, float) and math.isfinite(value) else None
    speed = fresh('vehicle.speed_kph')
    if speed is not None:
        return 0 <= speed < 1
    rpm = fresh('ecu.rpm')
    if rpm is None:
        rpm = fresh('tach.rpm')
    return rpm == 0


def require_parked(state):
    if not parked(state):
        raise ValueError('Park first: need fresh stationary GPS or a fresh engine-off RPM signal')
