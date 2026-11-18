"""What this Pi has: the system profile, /etc/frogdash/system.json.

One file says which parts of Frogdash this car uses: the ECU, the CAN board, GPS, cameras,
the modules on the bus, the power board, time zone, hotspot name, where reports go. It is
kept on the Pi, outside the repository, so an update never changes it and a choice made on
the Pi never blocks an update. It starts from a preset (presets/*.json): `generic` for a
new install, `foxbody` for the car this project was built in. A profile names its preset
and is read on top of it, so a field added in a later version takes the preset's value.

Everything else follows from it:
  - the dash's options (FROGDASH_ARGS in /etc/default/frogdash) come from to_args();
  - tools/frogdash_setup.sh installs or leaves out each part. It reads system.env, written
    here next to system.json: plain shell assignments, so the setup needs no JSON parser;
  - the installer writes the first one (init); a Pi installed before profiles existed gets
    one from the `foxbody` preset at its next update (sync), with the same options it had.

    python -m hardware.frogdash.sysconfig sync [--etc /etc]
    python -m hardware.frogdash.sysconfig init --preset generic [--set can_hat.oscillator=8000000]
    python -m hardware.frogdash.sysconfig get gps.enabled
    python -m hardware.frogdash.sysconfig args
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
PRESETS = ROOT / 'presets'
ETC = Path(os.environ.get('FROGDASH_ETC', '/etc'))
VERSION = 1

# The checks on each field that is not plain true/false or a whole number.
PATTERNS = {
    'preset': r'[a-z0-9-]{1,32}',
    'ecu.profile': r'[a-z0-9_-]{1,40}',
    'power': r'pisugar3|none',
    'locale.timezone': r'(|[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2})',
    'locale.wifi_country': r'(|[A-Z]{2})',
    'hotspot_name': r'[A-Za-z0-9 _.-]{1,32}',
    'uploads.repo': r'(|[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100})',
    'screen.mode': r'auto|\d{3,4}x\d{3,4}',     # A size to force at boot (tools/frogdash_screen.py), or the screen's own
    'screen.size': r'auto|\d{3,4}x\d{3,4}',     # The screen the owner said they have (the wizard's Screen page)
    'locale.units': r'us|metric',
    'interface': r'[a-z0-9]{1,15}',
    'can_hat.board': r'waveshare|other',     # The Waveshare RS485 CAN HAT (12 MHz, GPIO 25), or one set by hand
    'gps.source': r'usb|can|none',           # A USB receiver (gpsd), position from an ECU on the CAN bus, or none
    **{f'signals.{name}.source': r'module|ecu|gpio|can|none' for name in ('turn_left', 'turn_right', 'brake', 'lights', 'reverse')},
    'signals.fuel.source': r'module|ecu|adc|can|none',
}
# Car signals (inputs.py): where each comes from. module: the reference car's own boards;
# ecu: the ECU profile's reading; gpio: a Pi pin (through an optocoupler: never 12 V on a
# pin); adc: an ADS1115 on I2C (the fuel sender); can: a bit (or, for fuel, a byte) of any
# CAN frame; none: not shown.
SIGNALS = ('turn_left', 'turn_right', 'brake', 'lights', 'reverse', 'fuel')
# Pins a car signal may not use: I2C (2, 3), SPI0 for the CAN HAT (7-11) and the UART (14, 15).
RESERVED_PINS = {2, 3, 7, 8, 9, 10, 11, 14, 15}
RANGES = {
    'ecu.bitrate': (125000, 1000000),
    'ecu.base_id': (0, 0x1FFFFFFF),     # The ECU's first CAN ID where it can be moved (0: its profile's default)
    'can_hat.oscillator': (8000000, 40000000),
    'can_hat.interrupt': (0, 27),
    'can_hat.spi_hz': (100000, 10000000),
    'camera.rotate': (0, 180),
    **{f'signals.{name}.pin': (0, 27) for name in ('turn_left', 'turn_right', 'brake', 'lights', 'reverse')},
    **{f'signals.{name}.can_id': (0, 0x1FFFFFFF) for name in ('turn_left', 'turn_right', 'brake', 'lights', 'reverse', 'fuel')},
    **{f'signals.{name}.bit': (0, 63) for name in ('turn_left', 'turn_right', 'brake', 'lights', 'reverse')},
    'signals.fuel.adc_channel': (0, 3),
    'signals.fuel.empty_mv': (0, 5000),
    'signals.fuel.full_mv': (0, 5000),
    'signals.fuel.byte': (0, 7),
    'signals.fuel.full_raw': (1, 255),
}
# Extra options for the dash, one word each (e.g. --camera-size 1280x720): the characters
# the options step in tools/frogdash_setup.sh accepts.
EXTRA_WORD = re.compile(r'[A-Za-z0-9._/:=,-]{1,80}')
LOG_DIR = '/var/lib/frogdash/logs'


class ProfileError(ValueError):
    pass


def preset_names():
    return sorted(p.stem for p in PRESETS.glob('*.json'))


def preset(name):
    path = PRESETS / f'{name}.json'
    if not re.fullmatch(PATTERNS['preset'], name or '') or not path.is_file():
        raise ProfileError(f'No preset named {name!r} (there are: {", ".join(preset_names())})')
    data = json.loads(path.read_text(encoding='utf-8'))
    data['preset'] = name
    return data


def merged(base, over):
    """`over` on top of `base`, field by field; a field `base` does not have is refused."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if key not in base:
            raise ProfileError(f'Unknown field {key!r}')
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ProfileError(f'{key} should be a group of fields')
            out[key] = merged(base[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def flat(profile, prefix=''):
    for key, value in profile.items():
        if isinstance(value, dict):
            yield from flat(value, f'{prefix}{key}.')
        else:
            yield f'{prefix}{key}', value


def validate(profile):
    """The profile with every field checked against the generic preset's: the same kind of
    value, and in range. Raises ProfileError naming the first field that is wrong."""
    template = dict(flat(preset('generic')))
    seen = dict(flat(profile))
    for key, value in seen.items():
        if key not in template:
            raise ProfileError(f'Unknown field {key!r}')
        kind = template[key]
        if key in PATTERNS:
            if not isinstance(value, str) or not re.fullmatch(PATTERNS[key], value):
                raise ProfileError(f'{key}: {value!r} is not allowed')
        elif isinstance(kind, bool):
            if not isinstance(value, bool):
                raise ProfileError(f'{key} should be true or false')
        elif isinstance(kind, int):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ProfileError(f'{key} should be a whole number')
            low, high = RANGES.get(key, (0, 10 ** 9))
            if not low <= value <= high:
                raise ProfileError(f'{key} should be from {low} to {high}')
        elif isinstance(kind, list):
            if not isinstance(value, list) or not all(isinstance(w, str) and EXTRA_WORD.fullmatch(w) for w in value):
                raise ProfileError(f'{key}: each word may use only letters, digits and . _ / : = , -')
    missing = set(template) - set(seen)
    if missing:
        raise ProfileError(f'Missing field {sorted(missing)[0]!r}')
    if profile['camera']['rotate'] not in (0, 180):
        raise ProfileError('camera.rotate should be 0 or 180')
    pins = {}
    for name in SIGNALS[:-1]:
        signal = profile['signals'][name]
        if signal['source'] != 'gpio':
            continue
        pin = signal['pin']
        if pin in RESERVED_PINS or (profile['can_hat']['present'] and pin == profile['can_hat']['interrupt']):
            raise ProfileError(f'signals.{name}: GPIO {pin} is used by the CAN board, I2C or the serial port')
        if pin in pins:
            raise ProfileError(f'signals.{name}: GPIO {pin} is already {pins[pin]}')
        pins[pin] = name
    fuel = profile['signals']['fuel']
    if fuel['source'] == 'adc' and fuel['empty_mv'] == fuel['full_mv']:
        raise ProfileError('signals.fuel: empty and full should be different voltages')
    preset(profile['preset'])   # It must name a preset that exists
    return profile


def complete(saved):
    """A saved profile read on top of the preset it names (new fields get the preset's value)."""
    if not isinstance(saved, dict):
        raise ProfileError('The profile should be a JSON object')
    saved = {k: v for k, v in saved.items() if k != 'version'}
    return validate(merged(preset(saved.get('preset', 'generic')), saved))


def path(etc=None):
    return Path(etc or ETC) / 'frogdash' / 'system.json'


def load(etc=None, fallback='foxbody'):
    """This Pi's profile. Without one (a Pi set up before profiles, or the profile damaged),
    the `fallback` preset: the car's own, so nothing changes until a profile is written."""
    try:
        return complete(json.loads(path(etc).read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return validate(preset(fallback))


def get(profile, key):
    value = profile
    for part in key.split('.'):
        if not isinstance(value, dict) or part not in value:
            raise ProfileError(f'Unknown field {key!r}')
        value = value[part]
    return value


def to_args(profile):
    """FROGDASH_ARGS for this profile, in the order the options list had (so the car's own
    line stays exactly '--interface can0 --gpsd --log-dir /var/lib/frogdash/logs --terminal')."""
    words = ['--interface', profile['interface']]
    if profile['gps']['enabled']:
        words.append('--gpsd')
        if not profile['gps']['transmit_on_can']:
            words.append('--gps-no-transmit')
    if profile['recording']:
        words += ['--log-dir', LOG_DIR]
    if profile['terminal']:
        words.append('--terminal')
    if profile['camera']['enabled']:
        words.append('--camera')
        if profile['camera']['rotate']:
            words += ['--camera-rotate', str(profile['camera']['rotate'])]
    if profile['dashcam']['enabled']:
        words.append('--dashcam')
    # 0x309 (engine RPM for the water/meth board) is only sent onto a bus that has the board.
    if not profile['modules']['watermeth']:
        words.append('--no-engine-runtime')
    words += profile['extra_args']
    return ' '.join(words)


def ui_features(profile):
    """Which of the dash's screens to show (the snapshot's `features`): the map and race
    timer as chosen, and each module's own screens only when the car has that module."""
    modules = profile['modules']
    return {'map': profile['features']['map'], 'race': profile['features']['race'],
            'knock': modules['watermeth'], 'watermeth': modules['watermeth'], 'taillights': modules['taillights'],
            'units': profile['locale']['units']}


def shell(profile):
    """system.env: what tools/frogdash_setup.sh reads. Every value has passed validate(), so
    none holds a quote; each is single-quoted anyway."""
    yes = lambda value: '1' if value else '0'
    values = {
        'FD_PRESET': profile['preset'],
        'FD_CONFIGURED': yes(profile['configured']),
        'FD_GPS': yes(profile['gps']['enabled']),
        'FD_CAN_HAT': yes(profile['can_hat']['present']),
        'FD_CAN_OSC': profile['can_hat']['oscillator'],
        'FD_CAN_INT': profile['can_hat']['interrupt'],
        'FD_CAN_SPI_HZ': profile['can_hat']['spi_hz'],
        'FD_CAN_BITRATE': profile['ecu']['bitrate'],
        'FD_POWER': profile['power'],
        'FD_GATEWAY': yes(profile['modules']['gateway']),
        'FD_TAILLIGHTS': yes(profile['modules']['taillights']),
        'FD_WATERMETH': yes(profile['modules']['watermeth']),
        'FD_TUNERSTUDIO': yes(profile['tunerstudio']),
        'FD_WINDOWS_TUNER': yes(profile['windows_tuner']),
        'FD_GPIO_INPUTS': yes(any(profile['signals'][n]['source'] == 'gpio' for n in SIGNALS[:-1])),
        'FD_ADC_INPUTS': yes(profile['signals']['fuel']['source'] == 'adc'),
        'FD_TIMEZONE': profile['locale']['timezone'],
        'FD_WIFI_COUNTRY': profile['locale']['wifi_country'],
        'FD_HOTSPOT_NAME': profile['hotspot_name'],
        'FD_SCREEN': profile['screen']['mode'],
        'FD_ARGS': to_args(profile),
    }
    lines = ['# Written by hardware/frogdash/sysconfig.py from system.json: change that, not this.']
    lines += [f"{key}='{value}'" for key, value in values.items()]
    return '\n'.join(lines) + '\n'


def changes(profile, base):
    """The fields of `profile` that differ from `base` (its preset)."""
    out = {}
    for key, value in profile.items():
        if isinstance(value, dict):
            inner = changes(value, base.get(key, {}))
            if inner:
                out[key] = inner
        elif base.get(key) != value:
            out[key] = value
    return out


def write(profile, etc=None):
    """system.json and system.env, each replaced whole (never half written). system.json keeps
    only the preset's name and what differs from it, so a change to the preset in the
    repository (presets/foxbody.json) reaches the car at its next update, as the options
    list in the repository did, while the choices made on the Pi stay as they were made."""
    profile = validate(profile)
    target = path(etc)
    target.parent.mkdir(parents=True, exist_ok=True)
    saved = {'version': VERSION, 'preset': profile['preset'], **changes(profile, preset(profile['preset']))}
    for file, text in ((target, json.dumps(saved, indent=2) + '\n'),
                       (target.with_suffix('.env'), shell(profile))):
        tmp = file.with_name(file.name + '.tmp')
        tmp.write_text(text, encoding='utf-8', newline='\n')
        os.chmod(tmp, 0o644)
        os.replace(tmp, file)
    return profile


def legacy_install(etc=None):
    """A Pi set up before profiles: the dash's options are already in /etc/default/frogdash."""
    try:
        text = (Path(etc or ETC) / 'default' / 'frogdash').read_text(encoding='utf-8')
    except OSError:
        return False
    return bool(re.search(r'^FROGDASH_ARGS=', text, re.M))


def sync(etc=None):
    """The setup's first step: (result, detail). A Pi without a profile gets one (the car's
    own preset where the dash was already set up, else generic); system.env is brought in
    line with system.json either way."""
    target = path(etc)
    if not target.exists():
        name = 'foxbody' if legacy_install(etc) else 'generic'
        profile = validate(preset(name))
        if name == 'foxbody':
            profile['configured'] = True   # Set up long before the wizard existed
        write(profile, etc)
        return 'done', f'Made from the {name} preset'
    try:
        profile = complete(json.loads(target.read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        return 'failed', f'system.json cannot be used ({exc}): the dash keeps the options it has'
    env = target.with_suffix('.env')
    try:
        current = env.read_text(encoding='utf-8')
    except OSError:
        current = None
    if current == shell(profile):
        return 'ok', f'Preset {profile["preset"]}'
    write(profile, etc)
    return 'done', f'Preset {profile["preset"]}: setup values written again'


def assignment(text, profile):
    """'key=value' from the command line, the value read as JSON where it parses
    (true, 8000000, ["--x"]) and as text otherwise."""
    key, sep, raw = text.partition('=')
    if not sep:
        raise ProfileError(f'Expected key=value, not {text!r}')
    get(profile, key)   # The field must exist
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    target = profile
    parts = key.split('.')
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--etc', type=Path, default=None)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('sync')
    init = sub.add_parser('init')
    init.add_argument('--preset', default='generic')
    init.add_argument('--set', action='append', default=[], metavar='KEY=VALUE')
    init.add_argument('--force', action='store_true', help='Replace a profile that is already there')
    sub.add_parser('get').add_argument('key')
    sub.add_parser('args')
    sub.add_parser('presets')
    args = parser.parse_args(argv)
    try:
        if args.command == 'sync':
            result, detail = sync(args.etc)
            print(f'{result}: {detail}')
            return 1 if result == 'failed' else 0
        if args.command == 'init':
            if path(args.etc).exists() and not args.force:
                print(f'ok: {path(args.etc)} is already there (--force replaces it)')
                return 0
            profile = validate(preset(args.preset))
            for text in args.set:
                assignment(text, profile)
            write(profile, args.etc)
            print(f'done: preset {args.preset}')
            return 0
        if args.command == 'presets':
            print(' '.join(preset_names()))
            return 0
        profile = load(args.etc)
        if args.command == 'get':
            value = get(profile, args.key)
            print(json.dumps(value) if not isinstance(value, str) else value)
        else:
            print(to_args(profile))
        return 0
    except ProfileError as exc:
        print(f'failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
