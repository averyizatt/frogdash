"""Schema 2 + fuel extension receiver. Sources: docs/can-compatibility.md.

All pressure/temperature conversions are explicit; no vehicle-specific IDs are
guessed. Unknown traffic remains available in the bounded raw-frame inspector.
"""
from dataclasses import dataclass
from functools import reduce
from operator import xor


@dataclass(frozen=True)
class Signal:
    value: object
    quality: str = "live"


LENGTHS = {0x100: 7, 0x102: 4, 0x200: 8, 0x202: 8, 0x203: 8, 0x204: 3, 0x205: 3,
           0x300: 8, 0x302: 4, 0x303: 8, 0x304: 8, 0x305: 1,
           0x306: 4, 0x307: 8, 0x308: 4, 0x309: 4, 0x30A: 4,
           0x30B: 8, 0x30C: 8, 0x30D: 8}
TIMEOUTS = {0x100: .5, 0x200: 1.5, 0x202: .5, 0x203: 2, 0x204: 2, 0x205: .35,
            0x300: .5, 0x303: 1.5, 0x304: 3, 0x307: .5,
            0x309: .5, 0x30B: 1, 0x30C: 5, 0x30D: 5}
EVENT_IDS = {0x102, 0x302, 0x308, 0x305, 0x306, 0x30A}
ANALOG_BITS = {"engine.oil_pressure_psi": 0, "engine.fuel_pressure_psi": 1,
               "meth.pressure_psi": 2, "engine.boost_ref_psi": 3,
               "engine.iat_c": 4, "engine.bay_c": 5,
               "environment.ambient_c": 6, "environment.cabin_c": 7}


def decode(can_id, data):
    """Return normalized signals, {} for unknown IDs; reject malformed known IDs."""
    d = data
    ecu = 0x5E8 <= can_id <= 0x5EC or 0x5F0 <= can_id <= 0x62F or 0x700 <= can_id <= 0x73F
    expected = 8 if ecu else LENGTHS.get(can_id)
    if expected is None:
        return {}
    if len(d) != expected:
        raise ValueError(f"0x{can_id:03X}: expected DLC {expected}, got {len(d)}")
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
            enum("lighting." + side + "_state", d[index], "OFF RUNNING BRAKE TURN REVERSE BRAKE_TURN HAZARD CUSTOM")
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
    elif can_id == 0x30C:
        fields("knock.config", "flags threshold_offset multiplier min_rpm min_map_kpa debounce_ms gain center_hz",
               [d[0], d[1], d[2] / 10, d[3] * 100, d[4], d[5] * 10, d[6] / 10, d[7] * 100])
    elif can_id == 0x30D:
        fields("knock.config", "bandwidth_hz sample_rate_hz samples_per_update bias_alpha rms_alpha envelope_alpha bore_mm reserved",
               [d[0] * 100, d[1] * 100, d[2], d[3] / 1000, d[4] / 100, d[5] / 100, d[6], d[7]])
    elif ecu:
        # Keep ECU sources separate: an unrelated frame cannot refresh a gauge.
        if can_id <= 0x5EC:
            group = can_id - 0x5E8
            if group == 0:
                fields("ecu", "map_kpa rpm coolant_c throttle_pct", [s(0) / 10, u(2), c(4), s(6) / 10])
            elif group == 1:
                fields("ecu", "pw1_ms pw2_ms iat_c spark_deg", [u(0) / 1000, u(2) / 1000, c(4), s(6) / 10])
            elif group == 2:
                fields("ecu", "afr_target afr ego_correction_pct", [d[0] / 10, d[1] / 10, s(2) / 10])
                put("ecu.pwseq1_ms", s(6) / 1000)
            elif group == 3:
                fields("ecu", "battery_v sensor1 sensor2 knock_retard_deg", [s(0) / 10, s(2) / 10, s(4) / 10, d[6] / 10])
        else:
            group = can_id - (0x700 if can_id >= 0x700 else 0x5F0)
            if group == 0:
                fields("ecu", "seconds pw1_ms pw2_ms rpm", [u(0), u(2) / 1000, u(4) / 1000, u(6)])
            elif group == 1:
                fields("ecu", "spark_deg injection_flags engine_flags afr_target afr2_target", [s(0) / 10, d[2], d[3], d[4] / 10, d[5] / 10])
            elif group == 2:
                fields("ecu", "baro_kpa map_kpa iat_c coolant_c", [s(0) / 10, s(2) / 10, c(4), c(6)])
            elif group == 3:
                fields("ecu", "throttle_pct battery_v afr afr2", [s(i) / 10 for i in (0, 2, 4, 6)])
            elif group == 4:
                fields("ecu", "knock_pct ego_correction_pct ego2_correction_pct air_correction_pct", [s(i) / 10 for i in (0, 2, 4, 6)])
            elif group == 5:
                fields("ecu", "warmup_correction_pct tps_accel_pct tps_fuel_cut_pct baro_correction_pct", [s(i) / 10 for i in (0, 2, 4, 6)])
            elif group == 6:
                fields("ecu", "total_correction_pct ve1 ve2", [s(i) / 10 for i in (0, 2, 4)])
                put("ecu.idle_output_raw", s(6))
            elif group == 7:
                fields("ecu", "cold_advance_deg tps_rate_pct_s map_rate_kpa_s rpm_rate_rpm_s",
                       [s(0) / 10, s(2) / 10, s(4), s(6) * 10])
            elif group == 8:
                fields("ecu", "maf_load fuel_load flex_fuel_correction_pct maf_g_s",
                       [s(0) / 10, s(2) / 10, s(4) / 10, s(6) / 100])
            elif group == 11:
                fields("ecu", "fuel_load2 ignition_load ignition_load2 estimated_iat_c",
                       [s(0) / 10, s(2) / 10, s(4) / 10, c(6)])
            elif group == 9:
                fields("ecu", "ego1_v ego2_v dwell_ms trailing_dwell_ms", [s(0) / 100, s(2) / 100, u(4) / 10, u(6) / 10])
            elif group == 10:
                fields("ecu", "status1 status2 status3 status4 status5 status6 status7", [*d[:4], s(4), d[6], d[7]])
            elif group == 12:
                fields("ecu", "wall_fuel1_us wall_fuel2_us", [int.from_bytes(d[i:i + 4], "big", signed=True) / 100 for i in (0, 4)])
            elif group in (13, 14):
                for i in range(4):
                    put(f"ecu.sensor{(group - 13) * 4 + i + 1}", s(i * 2) / 10)
            elif group == 15:
                fields("ecu", "sensor9 sensor10", [s(0) / 10, s(2) / 10])
            elif group == 17:
                fields("ecu", "boost_target_kpa boost_duty_pct maf_v", [s(0) / 10, d[4], s(6) / 1000])
            elif group == 18:
                for i in range(4):
                    put(f"ecu.pwseq{i + 1}_ms", s(i * 2) / 1000)
            elif group == 26:
                fields("ecu", "nitrous_added_pw_ms nitrous_retard_deg", [s(4) / 1000, s(6) / 10])
            elif group == 27:
                for i in range(4):
                    put(f"ecu.can_pwm_period{i + 1}", s(i * 2))
            elif group == 28:
                fields("ecu", "idle_target_rpm tps_adc eae_load afr_load", [u(0), s(2), s(4) / 10, s(6) / 10])
            elif group == 29:
                fields("ecu", "eae_correction1_pct eae_correction2_pct", [u(0) / 10, u(2) / 10])
            elif group == 43:
                fields("ecu", "sync_loss_count sync_loss_reason timing_error_pct", [d[0], d[1], int.from_bytes(d[7:], "big", signed=True)])
    return out
