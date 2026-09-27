"""Stable MLG schema for every currently decoded channel, plus familiar TS names."""
from dataclasses import dataclass
from hashlib import sha1
import math

from .mlg import Field
from .protocol import LENGTHS, decode
from .state import ALIASES, UNAVAILABLE
from .trip import SIGNALS as TRIP_SIGNALS

QUALITY = {'unavailable': 0, 'live': 1, 'stale': 2, 'fault': 3}
ENUMS = {
    'race.phase': 'idle armed running complete stopped invalid'.split(),
    'meth.state': 'OFF ARMED SPRAYING FAULT TEST'.split(),
    'meth.flow': 'UNKNOWN OK LOW_FLOW NO_FLOW'.split(),
    'comfort.state': 'BOOT RUN WARN FAULT CONFIG'.split(),
    'lighting.left_state': 'OFF RUNNING BRAKE TURN REVERSE BRAKE_TURN HAZARD CUSTOM'.split(),
    'lighting.right_state': 'OFF RUNNING BRAKE TURN REVERSE BRAKE_TURN HAZARD CUSTOM'.split(),
}


def short(name):
    return name if len(name) <= 33 else name[:26] + '_' + sha1(name.encode()).hexdigest()[:6]


@dataclass(frozen=True)
class Channel:
    key: str
    name: str
    units: str = ''
    factor: float = 1
    offset: float = 0
    digits: int = 2

    def sample(self, values):
        sample = values.get(self.key, {})
        quality = QUALITY.get(sample.get('quality'), 0)
        value = sample.get('value')
        if quality != 1:
            return math.nan, quality
        if self.key in ENUMS:
            try:
                value = ENUMS[self.key].index(value)
            except ValueError:
                return math.nan, 3
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return math.nan, 3 if value is not None else 0
        value = value * self.factor + self.offset
        if not math.isfinite(value) or abs(value) > 3.4e38:
            return math.nan, 3
        return value, quality


def channels():
    # Labels match the supplied TS log where the same measurement is available.
    primary = [
        Channel('engine.rpm', 'RPM', 'RPM', digits=0),
        Channel('ecu.seconds', 'SecL', 's', digits=0),
        Channel('ecu.map_kpa', 'MAP', 'kPa'),
        Channel('engine.boost_kpa', 'Boost psi', 'psi', .145037738),
        Channel('ecu.throttle_pct', 'TPS', '%'),
        Channel('engine.afr', 'AFR', 'AFR'), Channel('ecu.afr2', 'AFR2', 'AFR'),
        Channel('ecu.afr_target', 'AFR Target 1', 'AFR'),
        Channel('engine.iat_c', 'MAT', 'F', 1.8, 32),
        Channel('engine.coolant_c', 'CLT', 'F', 1.8, 32),
        Channel('vehicle.battery_v', 'Batt V', 'V'),
        Channel('engine.ego_correction_pct', 'EGO cor1', '%'),
        Channel('ecu.ego2_correction_pct', 'EGO cor2', '%'),
        Channel('ecu.warmup_correction_pct', 'Fuel: Warmup cor', '%'),
        Channel('ecu.total_correction_pct', 'Fuel: Total cor', '%'),
        Channel('ecu.ve1', 'VE1', '%'), Channel('ecu.ve2', 'VE2', '%'),
        Channel('ecu.pw1_ms', 'PW', 'ms', digits=3), Channel('ecu.pw2_ms', 'PW2', 'ms', digits=3),
        Channel('ecu.spark_deg', 'SPK: Spark Advance', 'deg'),
        Channel('ecu.dwell_ms', 'Dwell', 'ms'), Channel('ecu.baro_kpa', 'Barometer', 'kPa'),
        Channel('ecu.fuel_load', 'Load'), Channel('ecu.ignition_load', 'Ign load'),
        Channel('engine.oil_pressure_psi', 'OilPressure', 'psi'),
        Channel('engine.fuel_pressure_psi', 'FuelPressure', 'psi'),
        Channel('vehicle.speed_kph', 'Vehicle Speed', 'MPH', 1 / 1.609344),
        Channel('gps.altitude_m', 'Altitude', 'm'),
        Channel('gps.latitude', 'Latitude', 'deg', digits=6),
        Channel('gps.longitude', 'Longitude', 'deg', digits=6),
        Channel('gps.track_deg', 'Heading', 'deg'),
        Channel('gps.satellites', 'GPS.SatelliteCount', digits=0),
        Channel('race.phase', 'Race state', digits=0),
        Channel('dash.bookmark_id', 'Bookmark ID', digits=0),
        Channel('race.elapsed_s', 'Race elapsed', 's'), Channel('race.distance_m', 'Race distance', 'm'),
        Channel('race.0_30', 'Race 0-30 MPH', 's'), Channel('race.0_60', 'Race 0-60 MPH', 's'),
        Channel('race.0_100kph', 'Race 0-100 KPH', 's'),
        Channel('race.eighth', 'Race eighth mile', 's'), Channel('race.quarter', 'Race quarter mile', 's'),
        Channel('race.eighth_mph', 'Race eighth crossing speed', 'MPH'), Channel('race.quarter_mph', 'Race quarter crossing speed', 'MPH'),
        Channel('race.lap_count', 'Race lap count', digits=0), Channel('race.best_lap_s', 'Race best lap', 's'),
    ]
    primary.extend(Channel(key, key, units) for key, units in TRIP_SIGNALS.items())
    # Enumerate the decoder's schema with valid, synthetic definition frames only.
    # Values from these frames NEVER enter a recording. This includes diagnostics,
    # config replies and fault/event channels even if they haven't arrived yet.
    keys = set(ALIASES) | set(UNAVAILABLE) | {'gps.satellites_in_view'}
    definitions = dict(LENGTHS)
    definitions.update({i: 8 for start, end in ((0x5E8, 0x5ED), (0x5F0, 0x630), (0x700, 0x740)) for i in range(start, end)})
    for can_id, length in definitions.items():
        frame = bytes(length) if can_id != 0x30A else bytes([0, 0, 0, 2])
        keys.update(decode(can_id, frame))
    covered = {c.key for c in primary}
    units = {'_c': 'C', '_kpa': 'kPa', '_psi': 'psi', '_pct': '%', '_ms': 'ms',
             '_hz': 'Hz', '_v': 'V', '_rpm': 'RPM', '_kph': 'km/h', '_mm': 'mm', '_deg': 'deg'}
    for key in sorted(keys - covered):
        unit = next((unit for suffix, unit in units.items() if key.endswith(suffix)), '')
        primary.append(Channel(key, short(key), unit))
    return tuple(primary)


CHANNELS = channels()
FIELDS = [Field('Time', 's', 'Time', digits=3), Field('CAN connected', category='Recorder', kind=0, digits=0),
          Field('Dropped samples', category='Recorder', kind=4, digits=0)]
for channel in CHANNELS:
    FIELDS.extend([Field(channel.name, channel.units, channel.key.split('.')[0], digits=channel.digits),
                   Field(short('Q ' + channel.name), category='Quality', kind=0, digits=0)])


def row_values(snapshot, elapsed, dropped=0):
    result = [elapsed, bool(snapshot['transport']['connected']), min(dropped, 0xFFFFFFFF)]
    for channel in CHANNELS:
        result.extend(channel.sample(snapshot['values']))
    return result


def info(mode, rate):
    return '\n'.join([
        f'Frogdash schema 6; source={mode}; sample rate={rate:g} Hz. Not a serial TunerStudio capture.',
        'trip.* = tracked GPS counters; fuel.level_status = MCU status; other fuel.* = calibrated estimates, MPG uses US gallons.',
        'Time = monotonic seconds since this file started. Q fields: 0=unavailable,1=live,2=stale,3=fault.',
        'Non-live values are IEEE NaN. Drop count is cumulative for this recorder process.',
        'Temperatures MAT/CLT in F; other *_c fields in C. GPS F32 precision is approximately one meter.',
        'Last fault/config/event fields retain the source protocol semantics; they are not current faults.',
        *[f'{key}: ' + ','.join(f'{i}={name}' for i, name in enumerate(names)) for key, names in ENUMS.items()],
        *[f'{c.name} <- {c.key}' for c in CHANNELS],
    ])
