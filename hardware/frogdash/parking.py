"""Stationary confirmation shared by setup and actuator test gates."""
import math
from .protocol import TIMEOUTS


def _fresh(state, name):
    if name == 'vehicle.speed_kph' and state.gps:
        sample = state.gps.values().get(name, {})
    else:
        samples = [v for (key, source), v in state.samples.items() if key == name and
                   state.connected and 0 <= state.clock() - v['seen'] <= TIMEOUTS.get(source, .5) and v['quality'] == 'live']
        sample = max(samples, key=lambda s: s['seen']) if samples else {}
    value = sample.get('value')
    return value if sample.get('quality') == 'live' and type(value) in (int, float) and math.isfinite(value) else None


def parked(state):
    fresh = lambda name: _fresh(state, name)
    speed = fresh('vehicle.speed_kph')
    if speed is not None:
        return 0 <= speed < 1
    rpm = fresh('ecu.rpm')
    if rpm is None:
        rpm = fresh('tach.rpm')
    return rpm == 0


def moving(state, threshold_kph=5):
    """True when driving: fresh speed above the threshold, or no stationary evidence at all.

    The threshold ignores GPS jitter at a standstill; missing data counts as moving (fail safe).
    """
    speed = _fresh(state, 'vehicle.speed_kph')
    if speed is not None:
        return speed > threshold_kph
    return not parked(state)


def rolling(state, threshold_kph=5):
    """True only when a fresh speed reading says the car is moving.

    Unlike moving(), a missing speed does not count: for conveniences that are fine in
    a garage with no GPS fix, such as opening TunerStudio at idle.
    """
    speed = _fresh(state, 'vehicle.speed_kph')
    return speed is not None and speed > threshold_kph


def require_parked(state):
    if not parked(state):
        raise ValueError('Park first: need fresh stationary GPS or a fresh engine-off RPM signal')
