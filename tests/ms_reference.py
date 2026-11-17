"""The MegaSquirt decoder as it was written by hand in hardware/frogdash/protocol.py before
ECU profiles (November 2026), kept only so tests/test_ecu_profiles.py can prove the profile
decodes every frame exactly as it did."""


def reference(can_id, data):
    d = data
    out = {}

    def put(key, value):
        out[key] = value

    def fields(prefix, names, values):
        for name, value in zip(names.split(), values):
            put(prefix + "." + name, value)

    def u(i): return int.from_bytes(d[i:i + 2], "big")
    def s(i): return int.from_bytes(d[i:i + 2], "big", signed=True)
    def c(i): return s(i) / 10 * 5 / 9 - 32 * 5 / 9

    if True:
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
