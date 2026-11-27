"""The advisory alert catalogue (hardware/ui/alert-rules.json) and how each rule is checked.

One file describes every alert, for the Pi and for the screen: its code, words, severity,
the reading it shows, its thresholds with their limits and defaults, how long it must last,
and its condition. A condition is a list of clauses that must all hold, each a signal
compared with a number, a threshold, or a sum of those and other signals; or a 'special'
worked out below (modules, the Pi, knock and water/meth flags, ignition sync).

Settings (alerts.json, and the 'alerts' part of a backup), version 2:
    {"version": 2, "chime": false, "rules": {"oil": {"enabled": true, "delay": 1.0, "psi": 15, "rpm": 1500}, ...},
     "custom": [{"key": "u1", "name": "Trans temp high", "signal": "ecu.transmission_temp_c", "op": ">",
                 "limit": 110, "severity": "warning", "running": false}]}
The flat version 1 (oil_psi, oil_enabled, ...) is still read, and becomes version 2.

`custom` are the owner's own alerts (the alert builder, alerts.js): any reading above or below
a limit, optionally only with the engine running. Each becomes a rule like the built-in ones
(custom_rule; alerts.js builds the same), so it is checked, latched, logged and shown the same
way, and its limit, delay and on/off are in `rules` like theirs.
"""
import json
import math
import re
import time
from pathlib import Path

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / 'ui' / 'alert-rules.json'
CATALOGUE = json.loads(CATALOGUE_PATH.read_text(encoding='utf-8'))
RULES = {rule['key']: rule for rule in CATALOGUE['rules']}
DELAY_LIMITS = (0, 60)
CUSTOM_KEY = re.compile(r'u\d{1,3}')
CUSTOM_SIGNAL = re.compile(r'[a-z][a-z0-9_]{0,30}\.[a-z0-9_.]{1,60}')
MAX_CUSTOM = 24
CUSTOM_LIMIT = 1e9
RUNNING_RPM = 400
# The units a custom alert's limit is shown and typed in (alerts.js KINDS), from its reading's name.
CUSTOM_KINDS = (('_c', 'temp'), ('_psi', 'pressure'), ('_kpa', 'boost'), ('_kph', 'speed'), ('_pct', 'pct'), ('_v', 'volt'), ('rpm', 'rpm'))
# Version 1 settings: (rule, field) for each flat key.
V1 = {'oil_enabled': ('oil', 'enabled'), 'oil_psi': ('oil', 'psi'), 'oil_rpm': ('oil', 'rpm'),
      'lean_enabled': ('lean', 'enabled'), 'lean_delta': ('lean', 'delta'), 'lean_boost_kpa': ('lean', 'boost'),
      'lean_rpm': ('lean', 'rpm'), 'coolant_enabled': ('coolant', 'enabled'), 'coolant_c': ('coolant', 'c'),
      'meth_enabled': ('meth', 'enabled')}
OPS = {'<': lambda a, b: a < b, '<=': lambda a, b: a <= b, '>': lambda a, b: a > b, '>=': lambda a, b: a >= b,
       '==': lambda a, b: a == b, '!=': lambda a, b: a != b, # A MegaSquirt-style correction, 100 % for none: further from 100 than b either way.
       'trim>': lambda a, b: abs(a - 100) > b}


def rule_defaults(rule):
    return {'enabled': rule['enabled'], 'delay': float(rule['delay']), **{p['key']: p['default'] for p in rule['params']}}


def custom_kind(signal):
    return next((kind for end, kind in CUSTOM_KINDS if signal.endswith(end)), 'plain')


def custom_rule(definition):
    """One of the owner's own alerts as a catalogue rule (alerts.js customRule is the same)."""
    key, signal, op = definition['key'], definition['signal'], definition['op']
    when = [[signal, op, {'param': 'limit'}]]
    if definition['running']:
        when.insert(0, ['engine.rpm', '>=', RUNNING_RPM])
    return {'key': key, 'code': f'USR-{int(key[1:]):02d}', 'title': definition['name'].upper(), 'name': definition['name'],
            'group': 'custom', 'severity': definition['severity'], 'custom': True,
            'about': f'{signal} {"above" if op == ">" else "below"} the limit{", with the engine running" if definition["running"] else ""}. Made in the alert builder.',
            'check': 'Set by you: check what this reading means for your car.',
            'show': [signal, custom_kind(signal)], 'enabled': True, 'delay': 2.0,
            'params': [{'key': 'limit', 'label': 'Above' if op == '>' else 'Below', 'kind': custom_kind(signal),
                        'min': -CUSTOM_LIMIT, 'max': CUSTOM_LIMIT, 'step': 0.001, 'default': definition['limit']}],
            'when': when}


def check_custom(given):
    """The owner's alert definitions, checked, or ValueError with the reason."""
    if not isinstance(given, list) or len(given) > MAX_CUSTOM:
        raise ValueError(f'custom must be a list of at most {MAX_CUSTOM} alerts')
    out, seen = [], set()
    for item in given:
        if not isinstance(item, dict) or set(item) != {'key', 'name', 'signal', 'op', 'limit', 'severity', 'running'}:
            raise ValueError('Each alert of your own needs key, name, signal, op, limit, severity and running')
        key, name = item['key'], item['name']
        if not isinstance(key, str) or not CUSTOM_KEY.fullmatch(key) or key in seen:
            raise ValueError(f'Alert of your own: bad or repeated key {key!r}')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or any(ord(c) < 32 for c in name):
            raise ValueError(f'{key}: the name should be 1-40 printable characters')
        if not isinstance(item['signal'], str) or not CUSTOM_SIGNAL.fullmatch(item['signal']):
            raise ValueError(f'{name}: not a reading the dash has')
        if item['op'] not in ('<', '>') or item['severity'] not in ('warning', 'critical') or type(item['running']) is not bool:
            raise ValueError(f'{name}: op should be < or >, severity warning or critical, running true or false')
        if not number(item['limit']) or abs(item['limit']) > CUSTOM_LIMIT:
            raise ValueError(f'{name}: the limit should be a number')
        seen.add(key)
        out.append({**item, 'name': name.strip()})
    return out


def all_rules(settings=None):
    """The built-in rules and the owner's own, by key."""
    rules = dict(RULES)
    for definition in (settings or {}).get('custom', ()):
        rules[definition['key']] = custom_rule(definition)
    return rules


def defaults(custom=()):
    rules = all_rules({'custom': custom})
    return {'version': 2, 'chime': False, 'rules': {key: rule_defaults(rule) for key, rule in rules.items()}, 'custom': list(custom)}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


# Alerts that have been removed. Settings saved before then still mention them; refusing
# those would put every alert back to its defaults, so they are skipped instead.
#   cold_boost (BST-02, boost on a cold engine): removed at the owner's request, 2026-11-27.
RETIRED = {'cold_boost'}


def validate_settings(data):
    """Complete version 2 settings from version 1 or 2, or ValueError with the reason.
    A rule that is not mentioned keeps its defaults; an unknown one is refused."""
    if not isinstance(data, dict):
        raise ValueError('Expected the alert settings as an object')
    if 'rules' not in data:   # Version 1: flat keys
        unknown = set(data) - set(V1) - {'chime'}
        if unknown:
            raise ValueError(f'Unknown alert settings: {", ".join(sorted(unknown))}')
        rules = {}
        for flat, (rule, field) in V1.items():
            if flat in data:
                rules.setdefault(rule, {})[field] = data[flat]
        data = {'version': 2, 'chime': data.get('chime', False), 'rules': rules}
    if set(data) - {'version', 'chime', 'rules', 'custom'}:
        raise ValueError('Unknown fields in the alert settings')
    if type(data.get('chime', False)) is not bool:
        raise ValueError('chime must be true or false')
    if not isinstance(data.get('rules'), dict):
        raise ValueError('rules must be an object')
    custom = check_custom(data.get('custom', []))
    rules = all_rules({'custom': custom})
    result = defaults(custom)
    result['chime'] = data.get('chime', False)
    for key, given in data['rules'].items():
        if key in RETIRED:
            continue   # An alert since removed: its saved settings are dropped, the rest kept
        rule = rules.get(key)
        if rule is None:
            raise ValueError(f'Unknown alert: {key}')
        if not isinstance(given, dict):
            raise ValueError(f'{key}: expected an object')
        limits = {p['key']: (p['min'], p['max']) for p in rule['params']}
        limits['delay'] = DELAY_LIMITS
        for field, value in given.items():
            if field == 'enabled':
                if type(value) is not bool:
                    raise ValueError(f'{key}.enabled must be true or false')
            elif field in limits:
                low, high = limits[field]
                if not number(value) or not low <= value <= high:
                    raise ValueError(f'{rule["name"]}: {field} must be between {low} and {high}')
            else:
                raise ValueError(f'{key}: unknown setting {field}')
            result['rules'][key][field] = value
    return result


def live(snapshot, key):
    sample = (snapshot.get('values') or {}).get(key) or {}
    value = sample.get('value')
    if sample.get('quality') != 'live' or value is None or isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def ecu_off_without_gps_motion(values):
    """Missing ECU data is expected while parked. Only fresh GPS proves motion;
    wheel fallback and held GPS speed must not turn it into a missing-data alarm.
    Ignore up to 3 km/h of GPS drift at rest.
    """
    if any(key.startswith('ecu.') and sample.get('quality') == 'live' for key, sample in values.items()):
        return False
    speed = values.get('vehicle.speed_kph') or {}
    moving = (speed.get('quality') == 'live'
              and (speed.get('source') == 'gpsd' or speed.get('source_id') == 0x203)
              and number(speed.get('value')) and speed['value'] > 3)
    return not moving


def term(value, settings, snapshot):
    """A clause's right-hand side: a number or text, a threshold, a signal or a sum. None if unknown."""
    if not isinstance(value, dict):
        return value
    if 'sum' in value:
        parts = [term(part, settings, snapshot) for part in value['sum']]
        return None if any(part is None for part in parts) else sum(parts)
    base = settings[value['param']] if 'param' in value else live(snapshot, value['signal'])
    return None if base is None else base * value.get('scale', 1)


def clauses(rule, settings, snapshot):
    """True when every clause holds, False as soon as one does not (even with others
    unknown), None when none fails but one cannot be told."""
    unknown = False
    for signal, op, right in rule['when']:
        left, right = live(snapshot, signal), term(right, settings, snapshot)
        if left is None or right is None:
            unknown = True
            continue
        try:
            if not OPS[op](left, right):
                return False
        except TypeError:          # A number against text: the reading is not what it should be
            unknown = True
    return None if unknown else True


class Specials:
    """Conditions that are not a comparison of readings. Some keep a little memory."""
    def __init__(self, clock=time.monotonic):
        self.sync_count = None
        self.clock, self.running_since = clock, None

    def check(self, name, settings, snapshot):
        if name == 'knock':
            warning, critical = live(snapshot, 'knock.warning'), live(snapshot, 'knock.critical')
            return None if warning is None or critical is None else bool(warning or critical)
        if name == 'meth':
            flags, mode, flow = live(snapshot, 'meth.fault_flags'), live(snapshot, 'meth.state'), live(snapshot, 'meth.flow')
            if flags is not None and ecu_off_without_gps_motion(snapshot.get('values') or {}):
                reported_flags = snapshot['values']['meth.fault_flags'].get('raw', flags)
                flags &= ~2   # Missing MicroSquirt MAP while parked, not another controller fault.
                # FAULT mode arrives before the debounced bits. Use the raw reason
                # so an ECU-off start cannot briefly trigger and latch this alert.
                if reported_flags == 2 and mode == 'FAULT':
                    return False
            if flags is not None and flags != 0 or mode == 'FAULT':
                return True
            if flags is None or mode is None:
                return None
            if mode != 'SPRAYING':
                return False
            return None if flow not in ('OK', 'LOW_FLOW', 'NO_FLOW') else flow != 'OK'
        if name.startswith('module:'):
            return module_quiet(snapshot, name.split(':', 1)[1])
        if name == 'pi_power':
            power = (snapshot.get('system') or {}).get('power') or {}
            return bool(power['undervoltage_now']) if 'undervoltage_now' in power else None
        if name == 'pi_heat':
            cpu = (snapshot.get('system') or {}).get('cpu_c')
            return None if not number(cpu) else cpu > settings['c']
        if name == 'charging':
            # Not charging: the battery below the limit once the engine has run for the set
            # minutes. Right after a start the MicroSquirt and the alternator take a while to
            # bring it above 13 V; it went off on every drive (November 2026).
            rpm, volts = live(snapshot, 'engine.rpm'), live(snapshot, 'vehicle.battery_v')
            if rpm is None:
                return None
            if rpm < 500:
                self.running_since = None
                return False
            if self.running_since is None:
                self.running_since = self.clock()
            if self.clock() - self.running_since < settings['grace'] * 60:
                return False
            return None if volts is None else volts < settings['v']
        if name == 'sync':
            count = live(snapshot, 'ecu.sync_loss_count')
            if count is None:
                return None
            rose = self.sync_count is not None and count > self.sync_count
            self.sync_count = count
            return rose
        raise ValueError(f'Unknown special alert {name}')


def module_quiet(snapshot, name):
    """A module silent while others are heard on the bus (and not being updated)."""
    modules = snapshot.get('modules') or {}
    if snapshot.get('mode') != 'socketcan' or not (snapshot.get('transport') or {}).get('connected'):
        return None
    if name not in modules:
        return None   # A module this car does not have (system profile): never "not responding"
    others = [other for other in ('taillights', 'comfort', 'watermeth') if other != name and other in modules]
    if not any(modules.get(other) == 'live' for other in others):
        return None   # Nothing heard at all: the bus, not this module.
    if name in (snapshot.get('updating') or ()):
        return None   # Being updated or restarted from the dash: quiet on purpose
    return modules.get(name) != 'live'


def reading(rule, snapshot):
    """The value a rule's widget shows now, in the signal's own units (or text)."""
    key, _ = rule['show']
    if key.startswith('module:'):
        return (snapshot.get('modules') or {}).get(key.split(':', 1)[1])
    if key == 'pi:cpu_c':
        return (snapshot.get('system') or {}).get('cpu_c')
    if key == 'pi:power':
        power = (snapshot.get('system') or {}).get('power') or {}
        return None if 'undervoltage_now' not in power else ('LOW' if power['undervoltage_now'] else 'OK')
    return live(snapshot, key)
