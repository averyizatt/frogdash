"""Mirror of the water/meth controller's pulse tuning, kept in sync from its 0x30F reports.

The pump is switched directly by a mechanical relay, so flow is set by how long the pump
runs in each slow cycle (at least half a second on, at least half a second off, or on
continuously). The controller owns the settings, enforces their hard limits and saves
them; this module mirrors what it reports, validates requests the same way, keeps the
presets and works out what the flow means next to the engine's fuel use.

Ranges and defaults match meth_tune.h in the DIYWaterMethInjection firmware and the
key numbers match can_protocol.h meth_tune_setting (extension 4).
"""
import json

from .driving import atomic_write

# key: (name, minimum, maximum, conservative default)
SETTINGS = {
    1: ('period_ms', 1000, 10000, 4000), 2: ('min_on_ms', 500, 10000, 1000), 3: ('max_on_ms', 500, 10000, 2000),
    4: ('start_psi_x10', 10, 300, 50), 5: ('full_psi_x10', 20, 350, 100), 6: ('min_rpm', 0, 8000, 2500),
    7: ('max_spray_s', 1, 120, 12), 8: ('rest_s', 0, 60, 6), 9: ('ramp_ms', 0, 5000, 500),
    10: ('min_pre_temp_c', 0, 120, 0), 11: ('overboost_assist', 0, 1, 0),
    12: ('meth_pct', 0, 100, 0), 13: ('nozzle_ml_min', 20, 1000, 60), 14: ('max_dose_pct', 0, 40, 10),
    15: ('early_rpm', 0, 8000, 3500), 16: ('hot_start_c', 0, 145, 0), 17: ('hot_full_c', 20, 150, 70)}
KEYS = {name: key for key, (name, _, _, _) in SETTINGS.items()}
NAMES = [SETTINGS[key][0] for key in sorted(SETTINGS)]
DEFAULTS = {name: default for name, _, _, default in SETTINGS.values()}
HOLDS = 'NONE DISARMED BELOW_BOOST RPM_LOW RPM_MISSING AIR_COLD TEMP_SENSOR RESTING TANK_LOW FAULT DOSE_LIMIT'.split()
FLAGS = {'unsaved': 1, 'rpm_ok': 2, 'pre_valid': 4, 'post_valid': 8, 'pump_on': 16, 'early_start': 32, 'hot_air': 64, 'ecu_temp': 128}
ACTIONS = {'save': 0, 'revert': 1, 'defaults': 2, 'report': 3}
STATUS_TIMEOUT = 1.5
REPORT_RETRY = 2.0
USER_SLOTS = ('Custom 1', 'Custom 2', 'Custom 3')
# What is in the tank, the nozzle fitted and the extra triggers (early start at high
# RPM, more for hot intake air) are separate from the flow presets.
FLUID_NAMES = ('meth_pct', 'max_dose_pct')
TRIGGER_NAMES = ('early_rpm', 'hot_start_c', 'hot_full_c')
TIMING_NAMES = [name for name in NAMES if name not in (*FLUID_NAMES, *TRIGGER_NAMES, 'nozzle_ml_min')]
TIMING_DEFAULTS = {name: DEFAULTS[name] for name in TIMING_NAMES}
# Flow presets, all on a 4 s cycle so the relay switches at most once every 4 s.
# Standard reaches the pump on continuously at full boost (no switching at all there).
PRESETS = {
    'Conservative': dict(TIMING_DEFAULTS),
    'Mild': {**TIMING_DEFAULTS, 'min_on_ms': 1500, 'max_on_ms': 3000, 'start_psi_x10': 45, 'full_psi_x10': 90,
             'max_spray_s': 20, 'rest_s': 5, 'ramp_ms': 1000},
    'Standard': {**TIMING_DEFAULTS, 'min_on_ms': 2000, 'max_on_ms': 4000, 'start_psi_x10': 40, 'full_psi_x10': 80,
                 'max_spray_s': 30, 'rest_s': 4, 'ramp_ms': 2000},
}
# Tank mixes by methanol volume, each with a dose limit (most fluid as a share of fuel).
# Methanol burns, so the engine tolerates more fluid as the methanol share rises.
FLUIDS = {
    'Water': {'meth_pct': 0, 'max_dose_pct': 10},
    '18% meth': {'meth_pct': 18, 'max_dose_pct': 12},
    '36% meth': {'meth_pct': 36, 'max_dose_pct': 15},
    '53% meth': {'meth_pct': 53, 'max_dose_pct': 18},
}
# Fuel flow estimate, the same one the controller uses for its dose limit (meth_tune.h):
# grams per minute per (RPM x kPa manifold absolute). 2.3 L, 85% VE, 50 C charge, 12:1.
FUEL_G_PER_MIN_PER_RPM_KPA = 8.79e-4
SHORTEST_PULSE_MS = SHORTEST_GAP_MS = 500


def apply_setting(values, name, requested):
    """Change one setting exactly as the controller does (meth_tune::set); returns the applied value."""
    _, low, high, _ = SETTINGS[KEYS[name]]
    value = min(max(requested, low), high)
    if name == 'min_on_ms':
        value = min(value, values['max_on_ms'])
    elif name == 'max_on_ms':
        value = max(min(value, values['period_ms']), values['min_on_ms'])
    elif name == 'start_psi_x10':
        value = min(value, values['full_psi_x10'] - 10)
    elif name == 'full_psi_x10':
        value = max(value, values['start_psi_x10'] + 10)
    elif name == 'hot_start_c' and value > 0:
        value = min(value, values['hot_full_c'] - 5)
    elif name == 'hot_full_c' and values['hot_start_c'] > 0:
        value = max(value, values['hot_start_c'] + 5)
    values[name] = value
    if name == 'period_ms':
        values['max_on_ms'] = min(values['max_on_ms'], value)
        values['min_on_ms'] = min(values['min_on_ms'], values['max_on_ms'])
    return value


def valid(values):
    if not isinstance(values, dict) or set(values) != set(NAMES):
        return False
    if any(type(values[name]) is not int or not low <= values[name] <= high for name, low, high, _ in SETTINGS.values()):
        return False
    return (values['min_on_ms'] <= values['max_on_ms'] <= values['period_ms']
            and values['full_psi_x10'] >= values['start_psi_x10'] + 10
            and (values['hot_start_c'] == 0 or values['hot_full_c'] >= values['hot_start_c'] + 5))


def plan(current, changes):
    """Commands, in a safe order, that apply changes (some or all settings) to the controller.

    The controller clamps each change against its partner (minimum against maximum,
    start against full), so the order depends on which way the pair is moving.
    """
    values, target, steps = dict(current), {**current, **changes}, []
    order = ['period_ms']
    after_period = dict(values)
    apply_setting(after_period, 'period_ms', target['period_ms'])
    order += ['max_on_ms', 'min_on_ms'] if target['max_on_ms'] >= after_period['min_on_ms'] else ['min_on_ms', 'max_on_ms']
    order += (['full_psi_x10', 'start_psi_x10'] if target['full_psi_x10'] >= values['start_psi_x10'] + 10
              else ['start_psi_x10', 'full_psi_x10'])
    order += (['hot_full_c', 'hot_start_c'] if values['hot_start_c'] == 0 or target['hot_full_c'] >= values['hot_start_c'] + 5
              else ['hot_start_c', 'hot_full_c'])
    order += [name for name in NAMES if name not in order]
    for name in order:
        if values[name] != target[name]:
            apply_setting(values, name, target[name])
            steps.append((KEYS[name], target[name]))
    return steps if values == target else None


def relay_on_ms(on_ms, period_ms):
    """The relay's rules (meth_tune::relaySafeOnMs): no short blips, no short gaps."""
    if on_ms >= period_ms:
        return period_ms
    if period_ms - on_ms < SHORTEST_GAP_MS:
        on_ms = max(0, period_ms - SHORTEST_GAP_MS)
    return on_ms if on_ms >= SHORTEST_PULSE_MS else 0


def fuel_g_min(rpm, map_kpa):
    """Estimated fuel flow at this engine speed and manifold absolute pressure."""
    return rpm * map_kpa * FUEL_G_PER_MIN_PER_RPM_KPA


class Cooling:
    """Before and after from one sensor: the ECU's intake temperature around each spray.

    The last reading before injection starts is the "before"; the change is followed
    while injecting and the finished spray is kept for comparison. Boost heats the air
    at the same time, so this understates the cooling; two sensors, one each side of
    the nozzle, measure it properly.
    """
    def __init__(self, clock):
        self.clock = clock
        self.before = None      # Latest intake temperature while not injecting.
        self.active = None      # The spray in progress.
        self.last = None        # The most recent finished spray.
        self.seen = None

    def step(self, injecting, intake_c, flow_ml_min):
        now = self.clock()
        elapsed = 0 if self.seen is None else min(max(now - self.seen, 0), 1)
        self.seen = now
        if not injecting:
            if self.active:
                spray, self.active = self.active, None
                if spray['seconds'] >= 1:  # Anything shorter is not a measurement.
                    self.last = {'from_c': spray['from_c'], 'lowest_c': spray['lowest_c'], 'end_c': spray['now_c'],
                                 'change_c': round(spray['lowest_c'] - spray['from_c'], 1), 'seconds': round(spray['seconds'], 1),
                                 'flow_ml_min': round(spray['ml'] / spray['seconds'] * 60, 1)}
            if intake_c is not None:
                self.before = intake_c
            return None
        if self.active is None:
            if self.before is None or intake_c is None:
                return None  # No "before" reading: nothing to compare against.
            self.active = {'from_c': self.before, 'lowest_c': intake_c, 'now_c': intake_c, 'seconds': 0.0, 'ml': 0.0}
        spray = self.active
        spray['seconds'] += elapsed
        spray['ml'] += (flow_ml_min or 0) * elapsed / 60
        if intake_c is None:
            return None
        spray['now_c'] = intake_c
        spray['lowest_c'] = min(spray['lowest_c'], intake_c)
        return round(intake_c - spray['from_c'], 1)


class MethTune:
    def __init__(self, clock):
        self.clock = clock
        self.user = {}  # The owner's flow presets by slot name.
        self.path = None
        self.cooling = Cooling(clock)
        self.reset()

    def reset(self):
        self.values = {}
        self.revision = self.flags = self.hold = self.on_ms = self.period_ms = None
        self.status_seen = None
        self.reported_revision = None  # Revision the current values belong to.
        self.requested_at = None
        self.requested_revision = None
        self.last_ack = None

    def load(self, path):
        """Restore the owner's presets; a damaged file just means none are saved."""
        self.path = path
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.user = {slot: saved[slot] for slot in USER_SLOTS
                         if slot in saved and isinstance(saved[slot], dict) and set(saved[slot]) == set(TIMING_NAMES)
                         and valid({**DEFAULTS, **saved[slot]})}
        except (OSError, ValueError, TypeError, AttributeError):
            self.user = {}

    @property
    def supported(self):
        """Firmware with pulse tuning reports its status every 500 ms."""
        return self.status_seen is not None and self.clock() - self.status_seen <= STATUS_TIMEOUT

    def observe(self, data):
        kind = data[0]
        if kind == 1:
            self.last_ack = {'command': data[1], 'status': data[2], 'subject': data[3],
                             'value': int.from_bytes(data[4:6], 'big'), 'revision': data[6]}
        elif kind == 2 and data[1] in SETTINGS:
            self.values[SETTINGS[data[1]][0]] = int.from_bytes(data[2:4], 'big')
            self.reported_revision = data[4]
        elif kind == 3:
            self.revision, self.flags, self.hold = data[1], data[2], data[3]
            self.on_ms, self.period_ms = int.from_bytes(data[4:6], 'big'), int.from_bytes(data[6:8], 'big')
            self.status_seen = self.clock()

    def complete(self):
        return len(self.values) == len(SETTINGS) and self.reported_revision == self.revision

    def needs_report(self):
        """True when the mirror is out of date and no report request is in flight."""
        if not self.supported or self.complete():
            return False
        if self.requested_revision != self.revision:
            return True  # Changed since the last request: ask again right away.
        return self.clock() - self.requested_at >= REPORT_RETRY

    def requested(self):
        self.requested_at = self.clock()
        self.requested_revision = self.revision

    def presets(self):
        return {**PRESETS, **self.user}

    def matching(self, choices):
        """Name of the preset or fluid whose values the controller's settings equal right now."""
        if not self.complete():
            return None
        return next((name for name, values in choices.items()
                     if all(self.values.get(key) == value for key, value in values.items())), None)

    def store(self, slot):
        if slot not in USER_SLOTS:
            raise ValueError('Presets can be saved to Custom 1, 2 or 3')
        if not self.complete() or not valid(self.values):
            raise ValueError('The controller has not reported its settings yet')
        self.user[slot] = {name: self.values[name] for name in TIMING_NAMES}

    def remove(self, slot):
        if slot not in self.user:
            raise ValueError('That preset slot is empty')
        del self.user[slot]

    def persist(self):
        if self.path:
            atomic_write(self.path, self.user)

    def derived(self, values, stamp_ms=0):
        """Flow right now and what share of the engine's fuel that is, for the dash and the logs."""
        def live(key):
            sample = values.get(key)
            return sample['value'] if sample and sample.get('quality') == 'live' and sample.get('value') is not None else None
        def signal(value):
            return {'value': value, 'quality': 'live' if value is not None else 'unavailable', 'source': 'Water/meth estimate',
                    'source_id': None, 'timestamp_ms': stamp_ms}
        flow = dose = None
        if self.supported and self.complete() and self.on_ms is not None and self.period_ms:
            # The average over a cycle: the nozzle flows while the pump runs.
            flow = round(self.values['nozzle_ml_min'] * min(self.on_ms, self.period_ms) / self.period_ms, 1)
            rpm, map_kpa = live('engine.rpm'), live('ecu.map_kpa')
            if rpm and map_kpa:
                dose = round(flow / fuel_g_min(rpm, map_kpa) * 100, 1)
        # Intake temperature change since this spray began, from the ECU's own sensor.
        change = self.cooling.step(live('meth.state') == 'SPRAYING', live('ecu.iat_c'), flow)
        return {'meth.flow_ml_min': signal(flow), 'meth.dose_pct': signal(dose), 'meth.iat_change_c': signal(change)}

    def snapshot(self):
        flags = self.flags or 0
        return {'supported': self.supported, 'complete': self.complete(), 'revision': self.revision,
                **{name: bool(flags & bit) for name, bit in FLAGS.items()},
                'hold': HOLDS[self.hold] if self.hold is not None and self.hold < len(HOLDS) else None,
                'on_ms': self.on_ms, 'period_ms': self.period_ms,
                'settings': dict(self.values), 'preset': self.matching(self.presets()), 'fluid': self.matching(FLUIDS),
                'last_spray': dict(self.cooling.last) if self.cooling.last else None, 'last_ack': self.last_ack}

    def preset_list(self):
        """For the tuning page: every flow preset, the tank mixes and the Custom slots (served on request)."""
        return {'presets': [{'name': name, 'builtin': name in PRESETS, 'values': values} for name, values in self.presets().items()],
                'fluids': [{'name': name, 'values': values} for name, values in FLUIDS.items()],
                'slots': list(USER_SLOTS)}
