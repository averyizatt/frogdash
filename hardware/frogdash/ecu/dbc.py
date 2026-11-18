"""A DBC file's frames as a custom ECU profile: the custom ECU editor's Import.

Many ECU makers publish their CAN broadcast as a DBC file. This reads the part of the format
a dash needs (BO_ frames and their SG_ signals) with no package beyond Python's own, and
gives back the frames as the profile format (ecu/__init__.py) has them: each signal's bits as
a layout, its scale and offset, and the unit converted to the dash's own where it says one
the dash knows (F to C, psi to kPa, mph to km/h). The reading each signal fills is a guess
from its name (RPM, CLT, MAP…); the editor shows every guess to be checked, and a signal
nobody could guess keeps its own name (ecu.<name>, kept in the logs).

Left out, with the reason: multiplexed signals, CAN FD frames longer than 8 bytes, and
frames of the other ID kind than most of the file (a profile is 11-bit or 29-bit).
"""
import re

from . import CATALOG, ProfileError, reader

FRAME = re.compile(r'^\s*BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+\S+')
SIGNAL = re.compile(r'^\s*SG_\s+(\w+)\s*(M|m\d+M?)?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*'
                    r'\(\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\)\s*\[[^\]]*\]\s*"([^"]*)"')
# Which reading a signal is, guessed from its name (letters and digits only, lower case).
GUESSES = (
    (r'rpm|enginespeed|engspeed', 'ecu.rpm'),
    (r'coolant|^clt|^ect|watertemp|enginetemp', 'ecu.coolant_c'),
    (r'^iat|^mat|airtemp|intakeair|inlettemp|manifoldairtemp', 'ecu.iat_c'),
    (r'oiltemp|^eot', 'ecu.oil_temp_c'),
    (r'oilpres|^eop', 'ecu.oil_pressure_kpa'),
    (r'fuelpres', 'ecu.fuel_pressure_kpa'),
    (r'fueltemp', 'ecu.fuel_temp_c'),
    (r'fuellevel', 'ecu.fuel_level_pct'),
    (r'baro', 'ecu.baro_kpa'),
    (r'boosttarget|boosttgt|targetboost', 'ecu.boost_target_kpa'),
    (r'^map(kpa)?$|manifoldpres|manifoldabs', 'ecu.map_kpa'),
    (r'^tps|throttle', 'ecu.throttle_pct'),
    (r'pedal', 'ecu.pedal_pct'),
    (r'batt|vbat|supplyvolt', 'ecu.battery_v'),
    (r'lambdatarget|lambdatgt|targetlambda', 'ecu.lambda_target'),
    (r'afrtarget|afrtgt|targetafr', 'ecu.afr_target'),
    (r'lambda', 'ecu.lambda1'),
    (r'^afr|^o2', 'ecu.afr'),
    (r'ignition(timing|angle|adv)|^ignadv|^ignangle|spark|^timing$|^advance', 'ecu.spark_deg'),
    (r'knockretard|knockret', 'ecu.knock_retard_deg'),
    (r'injduty|injectorduty|dutycycle', 'ecu.injector_duty_pct'),
    (r'pulsewidth|^pw1?$|^injpw|injectorpw', 'ecu.pw1_ms'),
    (r'^ve1?$', 'ecu.ve1'),
    (r'vss|vehiclespeed|groundspeed|^speed$', 'ecu.vehicle_speed_kph'),
    (r'^gear', 'ecu.gear'),
    (r'ethanol|flexfuel', 'ecu.ethanol_pct'),
    (r'^egt1?$', 'ecu.egt1_c'),
    (r'checkengine|^cel$|^mil$', 'ecu.check_engine'),
)
# The unit a DBC file gives, as the dash's conversion (FROM_UNITS) or None for the dash's own.
UNITS = {'f': 'degF', '°f': 'degF', 'degf': 'degF', 'deg f': 'degF', 'k': 'K', 'kelvin': 'K',
         'psi': 'psi', 'psig': 'psi', 'bar': 'bar', 'mph': 'mph'}
MAX_FRAMES = 64
# The units each known reading may be sent in (CATALOG): only those are converted.
ACCEPTS = {key: units for _, items in CATALOG for key, _, *units in items}


def guess(name, taken):
    plain = re.sub(r'[^a-z0-9]', '', name.lower())
    for pattern, key in GUESSES:
        if re.search(pattern, plain) and key not in taken:
            return key, True
    own = 'ecu.' + (re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_') or 'signal')[:44]
    while own in taken:
        own += '_2'
    return own, False


def layout(start, size, intel, signed, length):
    """The simplest layout for a DBC signal's bits (a byte, a word…), else the general one."""
    u = 's' if signed else 'u'
    if size == 1:
        return f'bit@{start // 8}.{start % 8}'
    if intel and start % 8 == 0 and size in (8, 16, 32):
        return f'{u}{size}{"le" if size > 8 else ""}@{start // 8}'
    if not intel and start % 8 == 7 and size in (8, 16, 32):
        return f'{u}{size}@{start // 8}'
    if intel and size == 4 and start % 8 in (0, 4) and not signed:
        return f'nib@{start // 8}.{start % 8}'
    return f'{u}{"le" if intel else "be"}@{start}:{size}'


def number(text):
    value = float(text)
    return int(value) if value.is_integer() and abs(value) < 1e15 else value


def read(text):
    """{'extended', 'frames': [...], 'skipped': [why...]} from a DBC file's text."""
    frames, skipped, current = [], [], None
    for line in str(text).splitlines():
        frame = FRAME.match(line)
        if frame:
            ident, length = int(frame[1]), int(frame[3])
            extended = bool(ident & 0x80000000)
            current = {'name': frame[2], 'id': ident & 0x1FFFFFFF, 'extended': extended, 'length': length, 'signals': []}
            if length > 8 or length < 1:
                skipped.append(f'{frame[2]}: {length} bytes (CAN FD), not read')
                current = None
            else:
                frames.append(current)
            continue
        signal = SIGNAL.match(line)
        if not signal or current is None:
            continue
        if signal[2]:
            skipped.append(f'{current["name"]}.{signal[1]}: multiplexed, not read')
            continue
        current['signals'].append(signal)
    if not frames:
        raise ProfileError('No frames found: is it a DBC file?')
    extended = sum(f['extended'] for f in frames) * 2 > len(frames)
    out, taken = [], set()
    for f in frames:
        if f['extended'] != extended:
            skipped.append(f'{f["name"]}: {"29" if f["extended"] else "11"}-bit ID, unlike the rest')
            continue
        signals = []
        for name, _, start, size, order, sign, scale, offset, unit in (s.groups() for s in f['signals']):
            spec = {'name': name, 'layout': layout(int(start), int(size), order == '1', sign == '-', f['length']),
                    'scale': number(scale), 'offset': number(offset)}
            try:
                reader(spec['layout'], f['length'])
            except ProfileError as exc:
                skipped.append(f'{f["name"]}.{name}: {exc}')
                continue
            if spec['scale'] == 0:
                skipped.append(f'{f["name"]}.{name}: a scale of 0')
                continue
            spec['key'], spec['guessed'] = guess(name, taken)
            taken.add(spec['key'])
            converted = UNITS.get(unit.strip().lower())
            if converted and converted in ACCEPTS.get(spec['key'], ()):
                spec['from'] = converted
            if unit.strip():
                spec['unit'] = unit.strip()
            signals.append(spec)
        if not signals:
            skipped.append(f'{f["name"]}: no signals to read')
            continue
        if len(out) == MAX_FRAMES:
            skipped.append(f'{f["name"]} and the rest: more than {MAX_FRAMES} frames')
            break
        out.append({'name': f['name'], 'ids': [f'0x{f["id"]:03X}'], 'length': f['length'], 'signals': signals})
    if not out:
        raise ProfileError('No frame in the file could be read: ' + '; '.join(skipped[:3]))
    return {'extended': extended, 'frames': out, 'skipped': skipped}
