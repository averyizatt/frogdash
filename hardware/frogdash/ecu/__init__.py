"""ECU profiles: which CAN frames an engine computer broadcasts, and what is in them.

A profile is a JSON file in profiles/ (built in) or, later, one the user made. It lists
the ECU's frames by ID, and in each frame its signals: where the bits are (layout), how
they become a value (scale, offset, or a named conversion) and which dash value they are
(key, always in the `ecu.` namespace and in fixed units: degrees C, kPa, volts). The rest
of the dash only knows those keys, so gauges, alerts, logs and modules work with any ECU,
and a reading a profile does not have stays "unavailable".

The profile in use is the system profile's `ecu.profile` (sysconfig.py), chosen when
protocol.py is first imported. Only what a manufacturer has published goes in a built-in
profile: its `source` names the document and version, and `status` says how far it has
been checked: `car` (running in a car), `simulated` (frames built from the document and
decoded in tests), or `documented` (written from the document only).

Layouts, byte numbers from 0:
  u8@B s8@B                 one byte
  u16@B s16@B u32@B s32@B   big-endian (Motorola) from byte B
  u16le@B s16le@B u32le@B s32le@B   little-endian (Intel)
  f32@B f32le@B             a 32-bit IEEE float, big- or little-endian
  bit@B.b                   one bit (b = 0 is the lowest)
  nib@B.b                   four bits from bit b
  ule@S:L sle@S:L           L bits from start bit S, Intel order, as a DBC file numbers them
  ube@S:L sbe@S:L           the same in Motorola order (S is the most significant bit)

A signal may say what unit the ECU sends it in, `from` (one of FROM_UNITS), when that is not
the dash's own: the value after scale and offset is converted (a temperature in F to C).

Frames are found by `ids`, or, for an ECU whose broadcast can be moved, by `offsets` from a
`base`: {"default": "0x200", "setting": "where it is set in the ECU's software"}. The base
used is the system profile's ecu.base_id, or the default when that is 0.

An ECU that puts its own serial number in the low bits of every ID (Holley) gives an
`id_mask`: a received ID is matched to a frame after AND with the mask.
"""
import json
import struct
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
BUILT_IN = HERE / 'profiles'
# A profile the owner wrote for an ECU with no built-in one: /etc/frogdash/ecu/custom.json.
USER = Path(__import__('os').environ.get('FROGDASH_ETC', '/etc')) / 'frogdash' / 'ecu'
CUSTOM = 'custom'
# The ECU's logo for the setup wizard, if one is there: hardware/ui/ecu-logos/<id>.svg or .png
# (the makers' own logos are theirs: add them only as their terms allow).
LOGOS = HERE.parents[1] / 'ui' / 'ecu-logos'
# Car signals and GPS an ECU may broadcast (inputs.ECU_KEYS, state.FROM_ECU): the wizard
# offers "from the ECU" only for what the chosen profile has.
OFFERS = ('ecu.turn_left', 'ecu.turn_right', 'ecu.brake_pedal', 'ecu.headlights', 'ecu.reverse', 'ecu.fuel_level_pct',
          'ecu.gps_latitude', 'ecu.gps_longitude', 'ecu.vehicle_speed_kph')
DEFAULT = 'megasquirt'
STATUSES = ('car', 'simulated', 'documented')

# Conversions a scale and offset cannot give exactly.
CONVERT = {
    # MegaSquirt temperatures: tenths of a degree F. Computed as the dash always has, so a
    # value is the same to the last bit as before profiles.
    'degF_tenths_to_C': lambda raw: raw / 10 * 5 / 9 - 32 * 5 / 9,
    # Holley sends degrees F as a float.
    'degF_to_C': lambda raw: (raw - 32) * 5 / 9,
}
# Units an ECU may send that the dash keeps in another (the key's): value after scale and offset.
FROM_UNITS = {
    'degF': lambda v: (v - 32) * 5 / 9, 'K': lambda v: v - 273.15,
    'psi': lambda v: v * 6.894757293168361, 'bar': lambda v: v * 100,
    'mph': lambda v: v * 1.609344,
}
# The readings a custom profile can fill, for its editor: (key, what it is, the dash's unit,
# then the other units an ECU may send it in). Other ecu.<name> keys are kept in the logs.
TEMPERATURE, PRESSURE, SPEED = ('°C', 'degF', 'K'), ('kPa', 'psi', 'bar'), ('km/h', 'mph')
CATALOG = (
    ('Engine', [('ecu.rpm', 'Engine speed', 'rpm'), ('ecu.map_kpa', 'Manifold pressure (MAP)', *PRESSURE),
                ('ecu.baro_kpa', 'Barometric pressure', *PRESSURE), ('ecu.throttle_pct', 'Throttle position', '%'),
                ('ecu.pedal_pct', 'Accelerator pedal', '%'), ('ecu.coolant_c', 'Coolant temperature', *TEMPERATURE),
                ('ecu.iat_c', 'Intake air temperature', *TEMPERATURE), ('ecu.battery_v', 'Battery voltage', 'V'),
                ('ecu.spark_deg', 'Ignition timing', '°'), ('ecu.knock_retard_deg', 'Knock retard', '°'),
                ('ecu.idle_target_rpm', 'Idle target', 'rpm'), ('ecu.boost_target_kpa', 'Boost target', *PRESSURE)]),
    ('Fuel', [('ecu.afr', 'Air-fuel ratio', 'AFR'), ('ecu.afr_target', 'AFR target', 'AFR'), ('ecu.lambda1', 'Lambda', 'λ'),
              ('ecu.lambda_target', 'Lambda target', 'λ'), ('ecu.pw1_ms', 'Injector pulse width', 'ms'),
              ('ecu.injector_duty_pct', 'Injector duty', '%'), ('ecu.ve1', 'Volumetric efficiency', '%'),
              ('ecu.ego_correction_pct', 'O2 correction', '%'), ('ecu.ethanol_pct', 'Ethanol content', '%'),
              ('ecu.fuel_pressure_kpa', 'Fuel pressure', *PRESSURE), ('ecu.fuel_temp_c', 'Fuel temperature', *TEMPERATURE),
              ('ecu.fuel_level_pct', 'Fuel level', '%')]),
    ('Oil and drivetrain', [('ecu.oil_pressure_kpa', 'Oil pressure', *PRESSURE), ('ecu.oil_temp_c', 'Oil temperature', *TEMPERATURE),
                            ('ecu.transmission_temp_c', 'Transmission temperature', *TEMPERATURE),
                            ('ecu.vehicle_speed_kph', 'Vehicle speed', *SPEED), ('ecu.gear', 'Gear', ''),
                            ('ecu.egt1_c', 'Exhaust gas temperature', *TEMPERATURE)]),
    ('Switches (1 = on)', [('ecu.check_engine', 'Check engine light', 'on/off'), ('ecu.fan1', 'Cooling fan', 'on/off'),
                           ('ecu.launch_control', 'Launch control', 'on/off'), ('ecu.turn_left', 'Left turn signal', 'on/off'),
                           ('ecu.turn_right', 'Right turn signal', 'on/off'), ('ecu.brake_pedal', 'Brake pedal', 'on/off'),
                           ('ecu.headlights', 'Headlights', 'on/off'), ('ecu.reverse', 'Reverse', 'on/off')]),
    ('GPS', [('ecu.gps_latitude', 'GPS latitude', '°'), ('ecu.gps_longitude', 'GPS longitude', '°'),
             ('ecu.gps_heading_deg', 'GPS heading', '°')]),
)
GENERAL = re.compile(r'([us])(le|be)@(\d{1,2}):(\d{1,2})')
LAYOUT = re.compile(r'(u8|s8|u16|s16|u32|s32|u16le|s16le|u32le|s32le)@(\d)|(bit|nib)@(\d)\.(\d)|(f32|f32le)@(\d)')
KEY = re.compile(r'ecu\.[a-z0-9_]{1,48}')


class ProfileError(ValueError):
    pass


def number(text):
    """An ID written as a number or as "0x5E8"."""
    if isinstance(text, int) and not isinstance(text, bool):
        return text
    if isinstance(text, str) and re.fullmatch(r'0x[0-9A-Fa-f]{1,8}|\d{1,10}', text):
        return int(text, 0)
    raise ProfileError(f'{text!r} is not a CAN ID')


def reader(layout, length):
    """A function bytes -> raw integer for one layout, checked against the frame length."""
    general = GENERAL.fullmatch(layout or '')
    if general:
        return bits(general[1] == 's', general[2], int(general[3]), int(general[4]), length)
    match = LAYOUT.fullmatch(layout or '')
    if not match:
        raise ProfileError(f'Layout {layout!r} is not one of the kinds in ecu/__init__.py')
    if match.group(6):
        byte = int(match.group(7))
        if byte + 4 > length:
            raise ProfileError(f'Layout {layout} runs past the frame\'s {length} bytes')
        fmt = '<f' if match.group(6) == 'f32le' else '>f'
        return lambda d: struct.unpack(fmt, bytes(d[byte:byte + 4]))[0]
    if match.group(1):
        kind, byte = match.group(1), int(match.group(2))
        size = {'8': 1, '16': 2, '32': 4}[re.search(r'\d+', kind).group()]
        if byte + size > length:
            raise ProfileError(f'Layout {layout} runs past the frame\'s {length} bytes')
        order = 'little' if kind.endswith('le') else 'big'
        signed = kind.startswith('s')
        return lambda d: int.from_bytes(d[byte:byte + size], order, signed=signed)
    kind, byte, bit = match.group(3), int(match.group(4)), int(match.group(5))
    if byte >= length or bit > 7 or (kind == 'nib' and bit > 4):
        raise ProfileError(f'Layout {layout} is outside the frame')
    mask = 1 if kind == 'bit' else 15
    return lambda d: d[byte] >> bit & mask


def bits(signed, order, start, size, length):
    """Any run of bits, numbered as in a DBC file: Intel (le) from its lowest bit, Motorola
    (be) from its highest, where bit 7 of byte 0 is the frame's first."""
    if not 1 <= size <= 32 or start >= length * 8:
        raise ProfileError(f'{size} bits from bit {start} is not inside a {length}-byte frame')
    if order == 'le':
        shift, ends = start, start + size
    else:
        first = start // 8 * 8 + 7 - start % 8          # Counted from the frame's first bit
        shift, ends = length * 8 - first - size, first + size
    if ends > length * 8 or shift < 0:
        raise ProfileError(f"{size} bits from bit {start} run past the frame's {length} bytes")
    mask, top = (1 << size) - 1, 1 << (size - 1)
    endian = 'little' if order == 'le' else 'big'

    def read(d):
        raw = int.from_bytes(bytes(d[:length]), endian) >> shift & mask
        return raw - (1 << size) if signed and raw & top else raw
    return read


def converter(spec):
    """raw -> value. A scale that is one over a whole number divides, as the dash's own
    decoders did (123 / 10, not 123 * 0.1), so values match theirs exactly."""
    unit = spec.get('from')
    if unit is not None:
        if unit not in FROM_UNITS:
            raise ProfileError(f'Unknown unit {unit!r} (one of {", ".join(FROM_UNITS)})')
        plain, change = converter({k: v for k, v in spec.items() if k != 'from'}), FROM_UNITS[unit]
        return lambda raw: change(plain(raw))
    if 'convert' in spec:
        if spec['convert'] not in CONVERT:
            raise ProfileError(f"Unknown conversion {spec['convert']!r}")
        return CONVERT[spec['convert']]
    scale, offset = spec.get('scale', 1), spec.get('offset', 0)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (scale, offset)) or scale == 0:
        raise ProfileError('scale and offset should be numbers (scale not 0)')
    divisor = round(1 / scale) if abs(scale) < 1 else None
    if divisor and abs(1 / scale - divisor) < 1e-9:
        base = lambda raw: raw / divisor
    elif scale == 1:
        base = lambda raw: raw
    else:
        base = lambda raw: raw * scale
    return base if not offset else (lambda raw: base(raw) + offset)


class Profile:
    def __init__(self, data, origin='built in', base=None):
        if not isinstance(data, dict):
            raise ProfileError('A profile should be a JSON object')
        self.data, self.origin = data, origin
        self.id = data.get('id')
        if not isinstance(self.id, str) or not re.fullmatch(r'[a-z0-9_-]{1,40}', self.id):
            raise ProfileError('A profile needs an id (lower case letters, digits, - and _)')
        self.label = str(data.get('label') or self.id)
        self.bitrate = data.get('bitrate', 500000)
        if self.bitrate not in (125000, 250000, 500000, 1000000):
            raise ProfileError(f'Bit rate {self.bitrate!r} is not one CAN uses (125k, 250k, 500k, 1M)')
        self.extended = bool(data.get('extended', False))
        self.timeout_s = float(data.get('timeout_s', 1.0))
        if not 0.05 <= self.timeout_s <= 10:
            raise ProfileError('timeout_s should be from 0.05 to 10 seconds')
        self.status = data.get('status', 'documented')
        if self.status not in STATUSES:
            raise ProfileError(f'status should be one of {", ".join(STATUSES)}')
        self.base = None
        if data.get('base'):
            self.base = number(base) if base else number(data['base'].get('default'))
        self.frames = {}        # ID -> (length, [(key, reader, converter)])
        for frame in data.get('frames') or []:
            length = frame.get('length', 8)
            if length not in range(1, 9):
                raise ProfileError(f"Frame {frame.get('name')}: length should be 1 to 8")
            signals = []
            for spec in frame.get('signals') or []:
                key = spec.get('key')
                if not isinstance(key, str) or not KEY.fullmatch(key):
                    raise ProfileError(f'Signal key {key!r} should be ecu.<name>')
                signals.append((key, reader(spec.get('layout'), length), converter(spec)))
            idents = [number(i) for i in frame.get('ids') or []]
            if frame.get('offsets'):
                if self.base is None:
                    raise ProfileError(f"Frame {frame.get('name')}: offsets need a base")
                idents += [self.base + number(o) for o in frame['offsets']]
            for ident in idents:
                if ident in self.frames:
                    raise ProfileError(f'Frame 0x{ident:03X} is listed twice')
                self.frames[ident] = (length, signals)
        self.claims = [(number(a), number(b)) for a, b in data.get('claims') or []]
        # Generic OBD-II: the ECU answers requests (obd2.py); one decoder for every answer.
        self.obd2 = data.get('type') == 'obd2'
        if self.obd2:
            from .. import obd2
            self._obd2 = obd2
        self.mask = number(data['id_mask']) if data.get('id_mask') else None
        if not self.frames:
            raise ProfileError('A profile needs at least one frame')
        limit = 0x1FFFFFFF if self.extended else 0x7FF
        for ident in [*self.frames, *(n for pair in self.claims for n in pair)]:
            if not 0 <= ident <= limit:
                raise ProfileError(f'ID 0x{ident:X} is outside {"29" if self.extended else "11"}-bit CAN')

    def key(self, can_id):
        """The frame a received ID belongs to (its serial bits masked off, for an ECU with id_mask)."""
        return can_id & self.mask if self.mask is not None else can_id

    def is_ecu(self, can_id):
        """The ECU's ID: its frames, and the ranges it claims (whose other IDs decode to nothing)."""
        can_id = self.key(can_id)
        return can_id in self.frames or any(a <= can_id <= b for a, b in self.claims)

    def ids(self):
        """Every ID this profile reads, with its length: for the log's list of channels."""
        out = {i: 8 for a, b in self.claims for i in range(a, b + 1)}
        out.update({i: length for i, (length, _) in self.frames.items()})
        return out

    def length(self, can_id):
        can_id = self.key(can_id)
        return self.frames[can_id][0] if can_id in self.frames else 8

    def decode(self, can_id, data):
        """{key: value} for one frame of this ECU (the length already checked)."""
        frame = self.frames.get(self.key(can_id))
        if not frame:
            return {}
        if self.obd2:
            return self._obd2.decode(data)
        return {key: convert(read(data)) for key, read, convert in frame[1]}

    def checks(self):
        """[(ID, what it carries)]: the frames the CAN check looks for (the profile's `check`,
        else its first two frames)."""
        listed = self.data.get('check')
        if listed:
            at = lambda ident: self.base + number(ident[1:]) if str(ident).startswith('+') and self.base is not None else number(ident)
            return [(at(ident), str(purpose)) for ident, purpose in listed]
        return [(ident, 'ECU broadcast') for ident in sorted(self.frames)[:2]]

    def keys(self):
        if self.obd2:
            return self._obd2.keys()
        return sorted({key for _, signals in self.frames.values() for key, _, _ in signals})

    def summary(self):
        """What the dash shows about the profile (the setup wizard and System check)."""
        keep = ('id', 'label', 'manufacturer', 'models', 'firmware', 'bitrate', 'extended', 'status', 'type',
                'source', 'setup', 'notes', 'tuner')
        keys = set(self.keys())
        out = {**{k: self.data[k] for k in keep if k in self.data}, 'origin': self.origin, 'signals': len(keys),
               'offers': [k for k in OFFERS if k in keys]}
        logo = next((f'ecu-logos/{p.name}' for name in dict.fromkeys((self.id, self.id.split('_')[0]))
                     for p in (LOGOS / f'{name}.svg', LOGOS / f'{name}.png') if p.is_file()), None)
        if logo:
            out['logo'] = logo
        if self.base is not None:
            out['base'] = {**self.data['base'], 'used': f'0x{self.base:03X}'}
        return out


def built_in():
    return sorted(p.stem for p in BUILT_IN.glob('*.json'))


def load(name, base=None):
    """A built-in profile by name (base: where its broadcast starts, if it can be moved)."""
    if not re.fullmatch(r'[a-z0-9_-]{1,40}', name or ''):
        raise ProfileError(f'No ECU profile named {name!r}')
    path = BUILT_IN / f'{name}.json'
    if name == CUSTOM:
        path = USER / f'{name}.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        if name == CUSTOM:
            raise ProfileError(f'No custom ECU profile yet: write one to {path} (docs/ecu-support.md)') from None
        raise ProfileError(f'No ECU profile named {name!r} (there are: {", ".join(built_in())})') from None
    except ValueError as exc:
        raise ProfileError(f'{path.name} is not valid JSON: {exc}') from None
    profile = Profile(data, origin='yours' if name == CUSTOM else 'built in', base=base or None)
    if profile.id != name:
        raise ProfileError(f'{path.name} says its id is {profile.id!r}')
    return profile


def custom(data):
    """A custom profile from the setup wizard's editor, checked as the dash would load it."""
    if not isinstance(data, dict) or data.get('id') != CUSTOM:
        raise ProfileError('A custom profile has the id "custom"')
    if data.get('type') or data.get('base') or data.get('id_mask'):
        raise ProfileError('A custom profile lists its frames by ID')
    if len(json.dumps(data)) > 200000:
        raise ProfileError('The profile is too large')
    return Profile(data, origin='yours')


def chosen():
    """(profile, problem): the system profile's ECU, or MegaSquirt with what went wrong."""
    try:
        from .. import sysconfig
        settings = sysconfig.load()['ecu']
    except Exception as exc:   # pragma: no cover (sysconfig falls back by itself)
        return load(DEFAULT), f'System profile not read: {exc}'
    try:
        return load(settings['profile'], settings.get('base_id')), None
    except ProfileError as exc:
        return load(DEFAULT), f'{exc}; reading {DEFAULT} instead'
