"""Schema 2 + fuel extension receiver. Sources: docs/can-compatibility.md.

All pressure/temperature conversions are explicit; no vehicle-specific IDs are
guessed. Unknown traffic remains available in the bounded raw-frame inspector.
"""
from dataclasses import dataclass
from functools import reduce
from operator import xor

from . import ecu as ecu_profiles


@dataclass(frozen=True)
class Signal:
    value: object
    quality: str = "live"


LENGTHS = {0x100: 7, 0x102: 4, 0x103: 8, 0x200: 8, 0x202: 8, 0x203: 8, 0x204: 3, 0x205: 3,
           0x500: 8, 0x501: 4, 0x503: 7,
           0x300: 8, 0x302: 4, 0x303: 8, 0x304: 8, 0x305: 1,
           0x306: 4, 0x307: 8, 0x308: 4, 0x309: 4, 0x30A: 4,
           0x30B: 8, 0x30C: 8, 0x30D: 8, 0x30E: 8, 0x30F: 8,
           0x310: 8}   # The ESP32 water/meth board's black box (extension 9): put together in blackbox.py
TIMEOUTS = {0x100: .5, 0x103: 1.5, 0x200: 1.5, 0x202: .5, 0x203: 2, 0x204: 2, 0x205: .35,
            0x500: .5, 0x501: .5, 0x503: .5,
            0x300: .5, 0x303: 1.5, 0x304: 3, 0x307: .5,
            0x309: .5, 0x30B: 1, 0x30C: 5, 0x30D: 5, 0x30E: 2, 0x30F: 1.5}
# MicroSquirt broadcast groups can run at a few Hz; allow 1 s before calling them stale.
# Another ECU's profile says its own (timeout() below).
ECU_TIMEOUT = 1.0
EVENT_IDS = {0x102, 0x302, 0x308, 0x305, 0x306, 0x30A}
ANALOG_BITS = {"engine.oil_pressure_psi": 0, "engine.fuel_pressure_psi": 1,
               "meth.pressure_psi": 2, "engine.boost_ref_psi": 3,
               "engine.iat_c": 4, "engine.bay_c": 5,
               "environment.ambient_c": 6, "environment.cabin_c": 7}


# The IDs of each Frogdash module, and those the dash itself sends. An ECU profile may not
# use the IDs of a module the car has (that module's frames would be taken for the ECU's),
# nor those the dash sends. The IDs of modules the car does not have are free: a rusEFI
# broadcasting at its default 0x200 is fine in a car without the comfort module.
MODULE_RANGES = {'taillights': ((0x100, 0x10F),),
                 'gateway': ((0x200, 0x20F), (0x500, 0x50F)),
                 'watermeth': ((0x300, 0x31F),)}
DASH_SENDS = {0x680, 0x681}           # Module firmware updates and restarts
GPS_ID = 0x203                        # The dash's GPS on CAN (gps.transmit_on_can)


def owned_ranges(settings=None):
    """The ID ranges taken in this car, from the system profile (all of them by default)."""
    if settings is None:
        return [r for ranges in MODULE_RANGES.values() for r in ranges] + [(i, i) for i in sorted(DASH_SENDS)]
    out = [r for name, ranges in MODULE_RANGES.items() if settings['modules'].get(name) for r in ranges]
    out += [(i, i) for i in sorted(DASH_SENDS)]
    if settings['gps']['enabled'] and settings['gps']['transmit_on_can']:
        out.append((GPS_ID, GPS_ID))
    return out


def clashes(profile, owned=None):
    """The taken IDs a profile would use, if any."""
    owned = owned_ranges() if owned is None else owned
    taken = sorted(f'0x{i:03X}' for i in profile.frames if any(a <= i <= b for a, b in owned))
    taken += [f'0x{a:03X}-0x{b:03X}' for a, b in profile.claims for ra, rb in owned if a <= rb and ra <= b]
    return taken


def use(profile, owned=None):
    """Read the engine computer with this ECU profile from now on (ecu/__init__.py)."""
    global ECU, ECU_PROBLEM, OWNED
    owned = OWNED if owned is None else owned
    taken = clashes(profile, owned)
    if taken:
        raise ecu_profiles.ProfileError(f'{profile.label} would use IDs this car\'s modules or the dash use: '
                                        f'{", ".join(taken)}. Move its broadcast (ecu.base_id) if it can be moved')
    ECU, ECU_PROBLEM, OWNED = profile, None, owned


def is_ecu(can_id, extended=False):
    """The engine computer's frame: an ID of its profile, in the ID format it uses (11 or
    29 bits), and for 11-bit IDs not one this car's modules use."""
    if extended != ECU.extended or not ECU.is_ecu(can_id):
        return False
    return extended or not any(a <= can_id <= b for a, b in OWNED)


def timeout(can_id):
    """How long a reading from this ID stays live."""
    return ECU.timeout_s if is_ecu(can_id) or is_ecu(can_id, True) else TIMEOUTS.get(can_id, .5)


def _start():
    """The system profile's ECU and modules, read once at start (before log_channels lists
    its channels). A profile that cannot be used leaves MegaSquirt, saying why."""
    global ECU, ECU_PROBLEM, OWNED
    ECU, ECU_PROBLEM, OWNED = ecu_profiles.load(ecu_profiles.DEFAULT), None, owned_ranges()
    profile, problem = ecu_profiles.chosen()
    try:
        from . import sysconfig
        owned = owned_ranges(sysconfig.load())
    except Exception:   # pragma: no cover (sysconfig falls back by itself)
        owned = owned_ranges()
    try:
        use(profile, owned)
        ECU_PROBLEM = problem
    except ecu_profiles.ProfileError as exc:
        ECU_PROBLEM = f'{exc}; reading {ecu_profiles.DEFAULT} instead'


_start()


def decode(can_id, data, extended=False):
    """Return normalized signals, {} for unknown IDs; reject malformed known IDs. A 29-bit
    frame is only ever the ECU's (the modules use 11-bit IDs)."""
    d = data
    ecu = is_ecu(can_id, extended)
    if extended and not ecu:
        return {}
    expected = ECU.length(can_id) if ecu else LENGTHS.get(can_id)
    if expected is None:
        return {}
    if len(d) != expected:
        raise ValueError(f"0x{can_id:03X}: expected DLC {expected}, got {len(d)}")
    if ecu:
        # The engine computer, read with its profile (ecu/profiles/), before any module's
        # decoder. Each ECU source stays separate: an unrelated frame cannot refresh a gauge.
        return {key: Signal(value) for key, value in ECU.decode(can_id, d).items()}
    out = {}

    def put(key, value, quality="live"):
        out[key] = Signal(value, quality)

    def fields(prefix, names, values):
        for name, value in zip(names.split(), values):
            put(prefix + "." + name, value)

    def enum(key, value, names):
        choices = names.split()
        put(key, choices[value] if value < len(choices) else f"UNKNOWN({value})",
            "live" if value < len(choices) else "fault")

    def u(i): return int.from_bytes(d[i:i + 2], "big")
    def s(i): return int.from_bytes(d[i:i + 2], "big", signed=True)
    def c(i): return s(i) / 10 * 5 / 9 - 32 * 5 / 9

    if can_id == 0x100:
        for side, index in (("left", 0), ("right", 1)):
            enum("lighting." + side + "_state", d[index], "OFF RUNNING BRAKE TURN REVERSE BRAKE_TURN HAZARD CUSTOM SHOW")
            put("lighting.turn_" + side, bool(d[index + 2] & 4))
        fields("lighting", "driver_inputs passenger_inputs brightness die_c thermal_derate", d[2:])
        for name, mask in (("brake", 1), ("running", 2), ("reverse", 8)):
            put("lighting." + name, bool((d[2] | d[3]) & mask))
    elif can_id in (0x102, 0x302, 0x308):
        prefix = {0x102: "lighting", 0x302: "meth", 0x308: "knock"}[can_id]
        fields(prefix + ".last_fault", "code severity data0 data1", d)
    elif can_id == 0x200:
        enum("comfort.state", d[0], "BOOT RUN WARN FAULT CONFIG")
        fields("comfort", "page input_flags cabin_c ambient_c battery_v fault_flags uptime_s_mod256",
               [d[1], d[2], d[3] - 40, d[4] - 40, d[5] / 10, d[6], d[7]])
    elif can_id == 0x202:
        q = "live" if d[5] & 1 and not d[5] & 2 and d[4] < 2 else "unavailable"
        put("tach.rpm", u(0), q)
        fields("tach", "generated_hz source status_flags pulses_per_rev", [u(2) / 10, d[4], d[5], d[6] / 10])
    elif can_id == 0x203:
        # fix_type=1 can mean either a real GPS fix or merely valid sentences.
        # RX + fix-quality flags are required; dead reckoning is not live GPS.
        q = "live" if d[6] & 0x11 == 0x11 and not d[6] & 0x20 else "unavailable"
        put("vehicle.speed_kph", u(0) / 10, q)
        put("gps.altitude_m", s(2), q)
        fields("gps", "satellites fix_type status_flags satellites_in_view", d[4:])
    elif can_id == 0x204:
        # Frogdash fuel-controller contract; docs/fuel-can.md. Calibration,
        # resistance conversion and slosh filtering belong to the transmitter.
        q = 'unavailable' if d[2] == 0 else 'live' if d[2] == 1 and u(0) <= 1000 else 'fault'
        put('vehicle.fuel_pct', u(0) / 10 if q == 'live' else None, q)
        put('fuel.level_status', d[2])
    elif can_id == 0x205:
        if d[2] != 1 or d[0] & ~0x1F:
            raise ValueError("0x205 invalid wheel input version or reserved bits")
        fields("wheel", "buttons_mask sequence", d[:2])
    elif can_id == 0x103:
        # CustomTaillights settings extension: acknowledgements and reports share one ID.
        kind = d[0]
        if kind not in (1, 2, 3, 4, 5):
            raise ValueError("0x103 unknown taillight report kind")
        put("taillight.report_kind", kind)
        if kind == 1:
            put("taillight.ack_command", d[1]); put("taillight.ack_status", d[2])
        elif kind == 5:
            put("taillight.revision", d[1]); put("taillight.flags", d[2])
            put("taillight.show_anim", d[3]); put("taillight.profiles", d[4])
            put("taillight.phase_ms", u(5) * 16)
    elif can_id == 0x500:
        # DIYComfortControlModule headless sensor gateway (gateway_protocol.h version 1).
        if d[7] & ~7 or (d[6] > 100 and d[6] != 255):
            raise ValueError("0x500 invalid gateway validity bits or fuel percent")
        put("vehicle.speed_kph", u(0) / 10, "live" if d[7] & 1 else "unavailable")
        put("gateway.rpm", u(2), "live" if d[7] & 2 else "unavailable")
        put("gateway.fuel_raw", u(4))
        fuel_ok = d[7] & 4 and d[6] <= 100
        put("vehicle.fuel_pct", d[6] if fuel_ok else None, "live" if fuel_ok else "unavailable")
    elif can_id == 0x501:
        if d[3] != 1 or d[0] & ~31 or d[1] & ~31 or d[0] & ~d[1]:
            raise ValueError("0x501 invalid gateway button version or bits")
        put("wheel.cruise_pressed", d[0])
        put("wheel.cruise_enabled", d[1])
        put("wheel.cruise_sequence", d[2])
    elif can_id == 0x503:
        if d[0] not in (1, 2) or d[5] != 1:
            raise ValueError("0x503 invalid interior light channel or version")
        side = "upper" if d[0] == 1 else "lower"
        put(f"interior.{side}.color", f"#{d[1]:02x}{d[2]:02x}{d[3]:02x}")
        put(f"interior.{side}.brightness", d[4])
        put(f"interior.{side}.commanded", bool(d[6]))
    elif can_id == 0x300:
        enum("meth.state", d[0], "OFF ARMED SPRAYING FAULT TEST")
        for key, value in (("meth.duty_pct", d[1]), ("meth.tank_pct", d[2])):
            put(key, value, "live" if value <= 100 else "fault")
        enum("meth.flow", d[3], "UNKNOWN OK LOW_FLOW NO_FLOW")
        fields("engine", "boost_kpa iat_c bay_c", [d[4], d[5] - 40, d[6] - 40])
        put("meth.fault_flags", d[7])
    elif can_id == 0x303:
        for i, key in enumerate(list(ANALOG_BITS)[:4]):
            put(key, d[i] / 2)
        fields("environment", "ambient_c cabin_c", [d[4] - 40, d[5] - 40])
        put("sensors.fault_flags", d[6] | d[7] << 8)
    elif can_id == 0x304:
        if reduce(xor, d[:7], 0) != d[7]:
            raise ValueError("0x304 checksum mismatch")
        fields("meth.config", "version desired_armed ratio_pct boost_trigger_kpa iat_threshold_c max_duty_pct failsafe_flags checksum",
               [*d[:4], d[4] - 40, *d[5:]])
    elif can_id == 0x305:
        put("config.request_reason", d[0])
    elif can_id == 0x306:
        fields("meth.ack", "version status reject_reason ratio_pct", d)
    elif can_id == 0x307:
        fields("knock", "status_flags energy baseline threshold event_count last_rpm last_boost_kpa reserved",
               [*d[:5], d[5] * 100, d[6], d[7]])
        # The spare byte: how much of the sensor signal sits at the knock frequency (0..255).
        # Firmware that predates the knock-band detector sends 0 here.
        put("knock.band_share_pct", round(d[7] * 100 / 255))
        q = "fault" if d[0] & 0x60 else ("live" if d[0] & 3 == 3 else "unavailable")
        for key in ("energy", "baseline", "threshold"):
            put("knock." + key, out["knock." + key].value, q)
        for key, bit in (("enabled", 0), ("signal_valid", 1), ("warning", 2), ("critical", 3), ("learned", 4), ("sensor_fault", 5), ("clipping", 6)):
            put("knock." + key, bool(d[0] & (1 << bit)))
    elif can_id == 0x309:
        put("runtime.rpm", int.from_bytes(d[:2], "little"), "live" if d[3] & 1 else "unavailable")
        put("runtime.map_kpa", d[2], "live" if d[3] & 2 else "unavailable")
        put("runtime.valid_flags", d[3])
    elif can_id == 0x30A:
        if d[3] != 2:
            raise ValueError("0x30A incompatible schema")
        fields("engine.ack", "command status applied_value schema", d)
    elif can_id == 0x30B:
        fields("knock.hook", "flags rms threshold baseline event_count bias_adc raw_adc envelope",
               [*d[:5], d[5] * 16, d[6] * 16, d[7]])
    elif can_id == 0x30E:
        # Knock detail from the ESP32 controller (extension 6): its amplifier, the knock
        # frequency it has found, how the last pass sounded, and two spectra. The
        # spectra are put together in knockview.py.
        kind = d[0]
        if kind == 1:
            for name, bit in (("automatic", 1), ("ineffective", 2), ("overloaded", 4), ("silent", 8), ("fixed", 16)):
                put("knock.amp." + name, bool(d[1] & bit))
            fields("knock.amp", "gain step top_step rest_mv swing_mv room_mv", [d[2] / 10, d[3], d[4], d[5] * 16, d[6] * 8, d[7] * 16])
        elif kind == 2:
            for name, bit in (("learning", 1), ("learned", 2), ("second_active", 4)):
                put("knock.freq." + name, bool(d[1] & bit))
            put("knock.freq.filter_hz", u(2))
            # 0: the votes have not agreed on a frequency yet.
            put("knock.freq.found_hz", u(4) or None, "live" if u(4) else "unavailable")
            fields("knock.freq", "agreement_pct votes", [d[6], d[7]])
        elif kind == 3:
            put("knock.freq.bore_hz", u(1))
            put("knock.freq.tone_hz", u(3))   # 0: no steady tone near the knock frequency.
            put("knock.freq.sample_rate_hz", u(5))
        elif kind == 4:
            put("knock.listen.notable", bool(d[1] & 1))
            put("knock.listen.confirmed", bool(d[1] & 2))
            fields("knock.listen", "second second_normal background crest", [d[2], d[3], d[4], d[5] / 10])
        elif kind in (5, 6):
            if d[1] % 6 or d[1] > 30:
                raise ValueError("0x30E knock spectrum chunk out of place")
        else:
            raise ValueError("0x30E unknown knock detail report kind")
    elif can_id == 0x30F:
        # Water/meth pulse tuning (extension 4): acknowledgements, settings, status and
        # the two intake air temperatures share one ID. Settings are mirrored in methtune.py.
        kind = d[0]
        if kind not in (1, 2, 3, 4):
            raise ValueError("0x30F unknown water/meth tuning report kind")
        if kind == 3:
            enum("meth.hold", d[3], "NONE DISARMED BELOW_BOOST RPM_LOW RPM_MISSING AIR_COLD TEMP_SENSOR RESTING TANK_LOW FAULT DOSE_LIMIT")
            fields("meth", "on_ms period_ms", [u(4), u(6)])
            put("meth.pump_on", bool(d[2] & 16))
        elif kind == 4:
            pre, post = s(1) / 10, s(3) / 10
            put("meth.pre_temp_c", pre if d[5] & 1 else None, "live" if d[5] & 1 else "unavailable")
            put("meth.post_temp_c", post if d[5] & 2 else None, "live" if d[5] & 2 else "unavailable")
            both = d[5] & 3 == 3
            put("meth.temp_drop_c", round(pre - post, 1) if both else None, "live" if both else "unavailable")
    elif can_id == 0x310:
        # The ESP32 board's black box after a restart (extension 9): which frame of the record
        # (255: its header). The record itself is put together in blackbox.py.
        put("meth.black_box.frame", d[0])
    elif can_id == 0x30C:
        fields("knock.config", "flags threshold_offset multiplier min_rpm min_map_kpa debounce_ms gain center_hz",
               [d[0], d[1], d[2] / 10, d[3] * 100, d[4], d[5] * 10, d[6] / 10, d[7] * 100])
    elif can_id == 0x30D:
        fields("knock.config", "bandwidth_hz sample_rate_hz samples_per_update bias_alpha rms_alpha envelope_alpha bore_mm reserved",
               [d[0] * 100, d[1] * 100, d[2], d[3] / 1000, d[4] / 100, d[5] / 100, d[6], d[7]])
    return out
