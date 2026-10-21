"""The advisory alert catalogue (hardware/ui/alert-rules.json) and how each rule is checked.

One file describes every alert, for the Pi and for the screen: its code, words, severity,
the reading it shows, its thresholds with their limits and defaults, how long it must last,
and its condition. A condition is a list of clauses that must all hold, each a signal
compared with a number, a threshold, or a sum of those and other signals; or a 'special'
worked out below (modules, the Pi, knock and water/meth flags, ignition sync).

Settings (alerts.json, and the 'alerts' part of a backup), version 2:
    {"version": 2, "chime": false, "rules": {"oil": {"enabled": true, "delay": 1.0, "psi": 15, "rpm": 1500}, ...}}
The flat version 1 (oil_psi, oil_enabled, ...) is still read, and becomes version 2.
"""
import json
import math
from pathlib import Path

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / 'ui' / 'alert-rules.json'
CATALOGUE = json.loads(CATALOGUE_PATH.read_text(encoding='utf-8'))
RULES = {rule['key']: rule for rule in CATALOGUE['rules']}
DELAY_LIMITS = (0, 60)
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


def defaults():
    return {'version': 2, 'chime': False, 'rules': {key: rule_defaults(rule) for key, rule in RULES.items()}}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


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
    if set(data) - {'version', 'chime', 'rules'}:
        raise ValueError('Unknown fields in the alert settings')
    if type(data.get('chime', False)) is not bool:
        raise ValueError('chime must be true or false')
    if not isinstance(data.get('rules'), dict):
        raise ValueError('rules must be an object')
    result = defaults()
    result['chime'] = data.get('chime', False)
    for key, given in data['rules'].items():
        rule = RULES.get(key)
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
    def __init__(self):
        self.sync_count = None

    def check(self, name, settings, snapshot):
        if name == 'knock':
            warning, critical = live(snapshot, 'knock.warning'), live(snapshot, 'knock.critical')
            return None if warning is None or critical is None else bool(warning or critical)
        if name == 'meth':
            flags, mode, flow = live(snapshot, 'meth.fault_flags'), live(snapshot, 'meth.state'), live(snapshot, 'meth.flow')
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
    others = [other for other in ('taillights', 'comfort', 'watermeth') if other != name]
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
