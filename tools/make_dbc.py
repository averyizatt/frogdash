"""Write hardware/can_contract/frogdash.dbc: every CAN message the dash knows, for SavvyCAN,
cantools and other CAN tools.

The layouts mirror hardware/frogdash/protocol.py (what the dash decodes) and the
schema in hardware/can_contract (what the modules send). tests/test_dbc.py decodes random
frames with both this file and the dash's own decoder and checks they agree, and that the
file is up to date with this script. Run after a protocol change:

    python tools/make_dbc.py

Needs cantools (requirements-tools.lock). The Pi does not: it only serves the file.
"""
from pathlib import Path
import sys

from cantools.database.can import Database, Message, Node, Signal
from cantools.database.conversion import BaseConversion

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'hardware/can_contract/frogdash.dbc'

LIGHT = 'OFF RUNNING BRAKE TURN REVERSE BRAKE_TURN HAZARD CUSTOM SHOW'
METH_STATE = 'OFF ARMED SPRAYING FAULT TEST'
FLOW = 'UNKNOWN OK LOW_FLOW NO_FLOW'
COMFORT = 'BOOT RUN WARN FAULT CONFIG'
HOLD = 'NONE DISARMED BELOW_BOOST RPM_LOW RPM_MISSING AIR_COLD TEMP_SENSOR RESTING TANK_LOW FAULT DOSE_LIMIT'
METH_COMMANDS = {1: 'ARM', 2: 'PUMP_TEST', 3: 'PUMP_STOP', 4: 'BOOST_START', 6: 'CLEAR_FAULTS', 7: 'RESTART',
                 0x10: 'SETTING', 0x11: 'TUNE_ACTION', 0x40: 'KNOCK_ENABLE', 0x41: 'KNOCK_THRESHOLD',
                 0x42: 'KNOCK_MULTIPLIER', 0x43: 'KNOCK_MIN_RPM', 0x44: 'KNOCK_MIN_MAP', 0x45: 'KNOCK_HOLD',
                 0x46: 'KNOCK_LEVEL_GAIN', 0x47: 'KNOCK_CENTER', 0x48: 'KNOCK_BANDWIDTH', 0x49: 'KNOCK_AUTO_FREQUENCY',
                 0x4A: 'KNOCK_CLEAR_EVENTS', 0x4B: 'KNOCK_AMP_GAIN'}
FW_OPS = {0x80: 'QUERY', 0x81: 'BEGIN', 0x82: 'BLOCK_END', 0x83: 'END', 0x84: 'ABORT', 0x85: 'CONFIRM', 0x86: 'RESTART'}
FW_TARGETS = {1: 'GATEWAY', 2: 'TAILLIGHTS', 3: 'WATER_METH'}
TEMP = (1 / 18, -160 / 9)     # MegaSquirt temperatures: tenths of a degree F, shown in degrees C


def names(text):
    return dict(enumerate(text.split()))


# A signal: (name, layout, scale, offset, unit, dash key or None, choices or None, multiplexer ids or None)
# Layouts: u8@b s8@b (byte b), u16@b s16@b s32@b (big-endian from byte b), u16le@b, bit@b.n (bit n of byte b),
# nib@b.n (four bits from bit n). Signals must not overlap, or cantools cannot decode the message.
def sig(name, layout, scale=1, offset=0, unit='', key=None, choices=None, mux=None):
    return (name, layout, scale, offset, unit, key, choices, mux)


def same(prefix, *fields, start=0, mux=None):
    """Plain bytes from `start`, each its own signal under the dash key prefix.field."""
    return [sig(name, f'u8@{start + i}', key=f'{prefix}.{name}', mux=mux) for i, name in enumerate(fields)]


def bits(byte, prefix, *fields, mux=None):
    return [sig(name, f'bit@{byte}.{n}', key=f'{prefix}.{name}' if prefix else None, mux=mux)
            for n, name in enumerate(fields) if name]


MESSAGES = [
    # (id, name, length, sender, comment, signals)
    (0x100, 'TAILLIGHT_STATE', 7, 'TAILLIGHTS', 'Taillight controller state, both sides', [
        sig('left_state', 'u8@0', key='lighting.left_state', choices=names(LIGHT)),
        sig('right_state', 'u8@1', key='lighting.right_state', choices=names(LIGHT)),
        # Each side's inputs, bit by bit (the dash also keeps the bytes: lighting.driver_inputs, passenger_inputs).
        sig('driver_brake', 'bit@2.0'), sig('driver_running', 'bit@2.1'), sig('turn_left', 'bit@2.2', key='lighting.turn_left'),
        sig('driver_reverse', 'bit@2.3'), sig('driver_other', 'nib@2.4'),
        sig('passenger_brake', 'bit@3.0'), sig('passenger_running', 'bit@3.1'), sig('turn_right', 'bit@3.2', key='lighting.turn_right'),
        sig('passenger_reverse', 'bit@3.3'), sig('passenger_other', 'nib@3.4'),
        *same('lighting', 'brightness', 'die_c', 'thermal_derate', start=4)]),
    (0x102, 'TAILLIGHT_FAULT', 4, 'TAILLIGHTS', 'Last taillight fault or start report', same('lighting.last_fault', 'code', 'severity', 'data0', 'data1')),
    (0x103, 'TAILLIGHT_REPORT', 8, 'TAILLIGHTS', 'Taillight settings extension: acknowledgements and reports', [
        sig('kind', 'u8@0', key='taillight.report_kind', choices={1: 'ACK', 2: 'SETTING', 3: 'COLOR', 4: 'TEXT', 5: 'STATUS'}),
        sig('ack_command', 'u8@1', key='taillight.ack_command', mux=[1]), sig('ack_status', 'u8@2', key='taillight.ack_status', mux=[1]),
        sig('revision', 'u8@1', key='taillight.revision', mux=[5]), sig('flags', 'u8@2', key='taillight.flags', mux=[5]),
        sig('show_anim', 'u8@3', key='taillight.show_anim', mux=[5]), sig('profiles', 'u8@4', key='taillight.profiles', mux=[5]),
        sig('phase_ms', 'u16@5', 16, unit='ms', key='taillight.phase_ms', mux=[5])]),
    (0x200, 'COMFORT_STATUS', 8, 'CCM', 'Comfort control module heartbeat', [
        sig('state', 'u8@0', key='comfort.state', choices=names(COMFORT)), sig('page', 'u8@1', key='comfort.page'),
        sig('input_flags', 'u8@2', key='comfort.input_flags'),
        sig('cabin_c', 'u8@3', offset=-40, unit='C', key='comfort.cabin_c'), sig('ambient_c', 'u8@4', offset=-40, unit='C', key='comfort.ambient_c'),
        sig('battery_v', 'u8@5', .1, unit='V', key='comfort.battery_v'), sig('fault_flags', 'u8@6', key='comfort.fault_flags'),
        sig('uptime_s_mod256', 'u8@7', unit='s', key='comfort.uptime_s_mod256')]),
    (0x202, 'TACH', 8, 'CCM', 'Tachometer output', [
        sig('rpm', 'u16@0', unit='rpm', key='tach.rpm'), sig('generated_hz', 'u16@2', .1, unit='Hz', key='tach.generated_hz'),
        sig('source', 'u8@4', key='tach.source'), sig('status_flags', 'u8@5', key='tach.status_flags'),
        sig('pulses_per_rev', 'u8@6', .1, key='tach.pulses_per_rev')]),
    (0x203, 'GPS', 8, 'FROGDASH', 'GPS speed and fix, from the dash (or the CCM)', [
        sig('speed_kph', 'u16@0', .1, unit='km/h', key='vehicle.speed_kph'), sig('altitude_m', 's16@2', unit='m', key='gps.altitude_m'),
        *same('gps', 'satellites', 'fix_type', 'status_flags', 'satellites_in_view', start=4)]),
    (0x204, 'FUEL_LEVEL', 3, 'GATEWAY', 'Fuel level (docs/fuel-can.md)', [
        sig('fuel_pct', 'u16@0', .1, unit='%', key='vehicle.fuel_pct'), sig('level_status', 'u8@2', key='fuel.level_status')]),
    (0x205, 'WHEEL_BUTTONS', 3, 'GATEWAY', 'Steering wheel buttons', [*same('wheel', 'buttons_mask', 'sequence'), sig('version', 'u8@2')]),
    (0x301, 'METH_COMMAND', 8, 'FROGDASH', 'Commands to the water/meth and knock controller, acknowledged on 0x30A or 0x30F', [
        sig('command', 'u8@0', choices=METH_COMMANDS), sig('value', 'u8@1'), sig('value_hi', 'u16@2')]),
    (0x300, 'METH_STATE', 8, 'WATERMETH', 'Water/meth controller state', [
        sig('state', 'u8@0', key='meth.state', choices=names(METH_STATE)), sig('duty_pct', 'u8@1', unit='%', key='meth.duty_pct'),
        sig('tank_pct', 'u8@2', unit='%', key='meth.tank_pct'), sig('flow', 'u8@3', key='meth.flow', choices=names(FLOW)),
        sig('boost_kpa', 'u8@4', unit='kPa', key='engine.boost_kpa'),
        sig('iat_c', 'u8@5', offset=-40, unit='C', key='engine.iat_c'), sig('bay_c', 'u8@6', offset=-40, unit='C', key='engine.bay_c'),
        sig('fault_flags', 'u8@7', key='meth.fault_flags')]),
    (0x302, 'METH_FAULT', 4, 'WATERMETH', 'Last water/meth fault', same('meth.last_fault', 'code', 'severity', 'data0', 'data1')),
    (0x303, 'ENGINE_SENSORS', 8, 'WATERMETH', 'Engine sensors on the water/meth controller', [
        sig('oil_pressure_psi', 'u8@0', .5, unit='psi', key='engine.oil_pressure_psi'),
        sig('fuel_pressure_psi', 'u8@1', .5, unit='psi', key='engine.fuel_pressure_psi'),
        sig('meth_pressure_psi', 'u8@2', .5, unit='psi', key='meth.pressure_psi'),
        sig('boost_ref_psi', 'u8@3', .5, unit='psi', key='engine.boost_ref_psi'),
        sig('ambient_c', 'u8@4', offset=-40, unit='C', key='environment.ambient_c'),
        sig('cabin_c', 'u8@5', offset=-40, unit='C', key='environment.cabin_c'),
        sig('fault_flags', 'u16le@6', key='sensors.fault_flags')]),
    (0x304, 'METH_CONFIG', 8, 'CCM', 'Water/meth settings broadcast by the CCM (byte 7: XOR of bytes 0-6)', [
        *same('meth.config', 'version', 'desired_armed', 'ratio_pct', 'boost_trigger_kpa'),
        sig('iat_threshold_c', 'u8@4', offset=-40, unit='C', key='meth.config.iat_threshold_c'),
        *same('meth.config', 'max_duty_pct', 'failsafe_flags', 'checksum', start=5)]),
    (0x305, 'CONFIG_REQUEST', 1, 'WATERMETH', 'The controller asks for its settings', [sig('request_reason', 'u8@0', key='config.request_reason')]),
    (0x306, 'METH_CONFIG_ACK', 4, 'WATERMETH', 'Answer to 0x304', same('meth.ack', 'version', 'status', 'reject_reason', 'ratio_pct')),
    (0x307, 'KNOCK', 8, 'WATERMETH', 'Knock detector', [
        *same('knock', 'energy', 'baseline', 'threshold', 'event_count', start=1),
        sig('last_rpm', 'u8@5', 100, unit='rpm', key='knock.last_rpm'), sig('last_boost_kpa', 'u8@6', unit='kPa', key='knock.last_boost_kpa'),
        sig('band_share', 'u8@7', key='knock.reserved'),   # 0..255: how much of the signal is at the knock frequency
        # The status byte (knock.status_flags on the dash), bit by bit.
        *bits(0, 'knock', 'enabled', 'signal_valid', 'warning', 'critical', 'learned', 'sensor_fault', 'clipping'),
        sig('status_bit7', 'bit@0.7')]),
    (0x308, 'KNOCK_FAULT', 4, 'WATERMETH', 'Last knock fault', same('knock.last_fault', 'code', 'severity', 'data0', 'data1')),
    (0x309, 'ENGINE_RUNTIME', 4, 'FROGDASH', 'Engine speed and MAP from the ECU, re-sent by the dash', [
        sig('rpm', 'u16le@0', unit='rpm', key='runtime.rpm'), sig('map_kpa', 'u8@2', unit='kPa', key='runtime.map_kpa'),
        sig('valid_flags', 'u8@3', key='runtime.valid_flags')]),
    (0x30A, 'ENGINE_ACK', 4, 'WATERMETH', 'Answer to a 0x301 command (status 0 ok, 1 unsupported, 2 bad length, 3 clamped, 4 busy)', [
        sig('command', 'u8@0', key='engine.ack.command', choices=METH_COMMANDS),
        sig('status', 'u8@1', key='engine.ack.status', choices={0: 'OK', 1: 'UNSUPPORTED', 2: 'BAD_LENGTH', 3: 'CLAMPED', 4: 'BUSY'}),
        *same('engine.ack', 'applied_value', 'schema', start=2)]),
    (0x30B, 'KNOCK_HOOK', 8, 'WATERMETH', 'Knock detector inner values', [
        *same('knock.hook', 'flags', 'rms', 'threshold', 'baseline', 'event_count'),
        sig('bias_adc', 'u8@5', 16, key='knock.hook.bias_adc'), sig('raw_adc', 'u8@6', 16, key='knock.hook.raw_adc'),
        sig('envelope', 'u8@7', key='knock.hook.envelope')]),
    (0x30C, 'KNOCK_CONFIG_1', 8, 'WATERMETH', 'Knock settings, part 1', [
        *same('knock.config', 'flags', 'threshold_offset'), sig('multiplier', 'u8@2', .1, key='knock.config.multiplier'),
        sig('min_rpm', 'u8@3', 100, unit='rpm', key='knock.config.min_rpm'), sig('min_map_kpa', 'u8@4', unit='kPa', key='knock.config.min_map_kpa'),
        sig('debounce_ms', 'u8@5', 10, unit='ms', key='knock.config.debounce_ms'), sig('gain', 'u8@6', .1, key='knock.config.gain'),
        sig('center_hz', 'u8@7', 100, unit='Hz', key='knock.config.center_hz')]),
    (0x30D, 'KNOCK_CONFIG_2', 8, 'WATERMETH', 'Knock settings, part 2', [
        sig('bandwidth_hz', 'u8@0', 100, unit='Hz', key='knock.config.bandwidth_hz'),
        sig('sample_rate_hz', 'u8@1', 100, unit='Hz', key='knock.config.sample_rate_hz'),
        sig('samples_per_update', 'u8@2', key='knock.config.samples_per_update'),
        sig('bias_alpha', 'u8@3', .001, key='knock.config.bias_alpha'), sig('rms_alpha', 'u8@4', .01, key='knock.config.rms_alpha'),
        sig('envelope_alpha', 'u8@5', .01, key='knock.config.envelope_alpha'), sig('bore_mm', 'u8@6', unit='mm', key='knock.config.bore_mm'),
        sig('reserved', 'u8@7', key='knock.config.reserved')]),
    (0x30E, 'KNOCK_DETAIL', 8, 'WATERMETH', 'ESP32 knock detail (extension 6): amplifier, frequency, last pass, spectra', [
        sig('kind', 'u8@0', choices={1: 'AMPLIFIER', 2: 'FREQUENCY', 3: 'TONES', 4: 'LISTEN', 5: 'SPECTRUM', 6: 'SPECTRUM_NORMAL'}),
        *bits(1, 'knock.amp', 'automatic', 'ineffective', 'overloaded', 'silent', 'fixed', mux=[1]),
        sig('amp_gain', 'u8@2', .1, key='knock.amp.gain', mux=[1]), sig('amp_step', 'u8@3', key='knock.amp.step', mux=[1]),
        sig('amp_top_step', 'u8@4', key='knock.amp.top_step', mux=[1]),
        sig('amp_rest_mv', 'u8@5', 16, unit='mV', key='knock.amp.rest_mv', mux=[1]),
        sig('amp_swing_mv', 'u8@6', 8, unit='mV', key='knock.amp.swing_mv', mux=[1]),
        sig('amp_room_mv', 'u8@7', 16, unit='mV', key='knock.amp.room_mv', mux=[1]),
        *bits(1, 'knock.freq', 'learning', 'learned', 'second_active', mux=[2]),
        sig('filter_hz', 'u16@2', unit='Hz', key='knock.freq.filter_hz', mux=[2]),
        sig('found_hz', 'u16@4', unit='Hz', key='knock.freq.found_hz', mux=[2]),
        sig('agreement_pct', 'u8@6', unit='%', key='knock.freq.agreement_pct', mux=[2]), sig('votes', 'u8@7', key='knock.freq.votes', mux=[2]),
        sig('bore_hz', 'u16@1', unit='Hz', key='knock.freq.bore_hz', mux=[3]), sig('tone_hz', 'u16@3', unit='Hz', key='knock.freq.tone_hz', mux=[3]),
        sig('knock_sample_rate_hz', 'u16@5', unit='Hz', key='knock.freq.sample_rate_hz', mux=[3]),
        *bits(1, 'knock.listen', 'notable', 'confirmed', mux=[4]),
        sig('second', 'u8@2', key='knock.listen.second', mux=[4]), sig('second_normal', 'u8@3', key='knock.listen.second_normal', mux=[4]),
        sig('background', 'u8@4', key='knock.listen.background', mux=[4]), sig('crest', 'u8@5', .1, key='knock.listen.crest', mux=[4]),
        sig('first_bin', 'u8@1', mux=[5, 6]), *[sig(f'bin{n}', f'u8@{n + 2}', mux=[5, 6]) for n in range(6)]]),
    (0x30F, 'METH_TUNING', 8, 'WATERMETH', 'Water/meth pulse tuning (extension 4): acknowledgements, settings, status, air temperatures', [
        sig('kind', 'u8@0', choices={1: 'ACK', 2: 'SETTING', 3: 'STATUS', 4: 'AIR_TEMPS'}),
        sig('ack_command', 'u8@1', mux=[1]), sig('ack_status', 'u8@2', mux=[1]), sig('ack_setting', 'u8@3', mux=[1]),
        sig('ack_value', 'u16@4', mux=[1]),
        sig('pump_on', 'bit@2.4', key='meth.pump_on', mux=[3]), sig('hold', 'u8@3', key='meth.hold', choices=names(HOLD), mux=[3]),
        sig('on_ms', 'u16@4', unit='ms', key='meth.on_ms', mux=[3]), sig('period_ms', 'u16@6', unit='ms', key='meth.period_ms', mux=[3]),
        sig('pre_temp_c', 's16@1', .1, unit='C', key='meth.pre_temp_c', mux=[4]),
        sig('post_temp_c', 's16@3', .1, unit='C', key='meth.post_temp_c', mux=[4]), sig('temps_valid', 'u8@5', mux=[4])]),
    (0x500, 'GATEWAY_SENSORS', 8, 'GATEWAY', 'Sensor gateway: speed, engine speed, fuel', [
        sig('speed_kph', 'u16@0', .1, unit='km/h', key='vehicle.speed_kph'), sig('rpm', 'u16@2', unit='rpm', key='gateway.rpm'),
        sig('fuel_raw', 'u16@4', key='gateway.fuel_raw'), sig('fuel_pct', 'u8@6', unit='%', key='vehicle.fuel_pct'),
        *bits(7, None, 'speed_valid', 'rpm_valid', 'fuel_valid')]),
    (0x501, 'GATEWAY_BUTTONS', 4, 'GATEWAY', 'Cruise control buttons', [
        sig('cruise_pressed', 'u8@0', key='wheel.cruise_pressed'), sig('cruise_enabled', 'u8@1', key='wheel.cruise_enabled'),
        sig('cruise_sequence', 'u8@2', key='wheel.cruise_sequence'), sig('version', 'u8@3')]),
    (0x503, 'INTERIOR_LIGHT', 7, 'GATEWAY', 'Interior light channel (1 upper, 2 lower)', [
        sig('channel', 'u8@0', choices={1: 'UPPER', 2: 'LOWER'}), sig('red', 'u8@1'), sig('green', 'u8@2'), sig('blue', 'u8@3'),
        sig('brightness', 'u8@4'), sig('version', 'u8@5'), sig('commanded', 'u8@6')]),
    (0x680, 'FIRMWARE_COMMAND', 8, 'FROGDASH', 'Firmware updates and restarts (firmware_update.h); ops below 0x80 are data frames', [
        sig('op', 'u8@0', choices=FW_OPS), sig('target', 'u8@1', choices=FW_TARGETS)]),
    (0x681, 'FIRMWARE_REPLY', 8, 'CCM', 'Module answers to 0x680 (kind 1 INFO, 2 ACK)', [
        sig('kind', 'u8@0', choices={1: 'INFO', 2: 'ACK'}), sig('target', 'u8@1', choices=FW_TARGETS),
        sig('build', 'u32@2'), sig('flags', 'u8@6')]),
]

# MegaSquirt dash broadcast. Simplified set at 0x5E8..0x5EB.
ECU_SIMPLE = [
    [sig('map_kpa', 's16@0', .1, unit='kPa', key='ecu.map_kpa'), sig('rpm', 'u16@2', unit='rpm', key='ecu.rpm'),
     sig('coolant_c', 's16@4', *TEMP, unit='C', key='ecu.coolant_c'), sig('throttle_pct', 's16@6', .1, unit='%', key='ecu.throttle_pct')],
    [sig('pw1_ms', 'u16@0', .001, unit='ms', key='ecu.pw1_ms'), sig('pw2_ms', 'u16@2', .001, unit='ms', key='ecu.pw2_ms'),
     sig('iat_c', 's16@4', *TEMP, unit='C', key='ecu.iat_c'), sig('spark_deg', 's16@6', .1, unit='deg', key='ecu.spark_deg')],
    [sig('afr_target', 'u8@0', .1, key='ecu.afr_target'), sig('afr', 'u8@1', .1, key='ecu.afr'),
     sig('ego_correction_pct', 's16@2', .1, unit='%', key='ecu.ego_correction_pct'), sig('pwseq1_ms', 's16@6', .001, unit='ms', key='ecu.pwseq1_ms')],
    [sig('battery_v', 's16@0', .1, unit='V', key='ecu.battery_v'), sig('sensor1', 's16@2', .1, key='ecu.sensor1'),
     sig('sensor2', 's16@4', .1, key='ecu.sensor2'), sig('knock_retard_deg', 'u8@6', .1, unit='deg', key='ecu.knock_retard_deg')],
]


def tenths(*fields, units=None):
    units = units or [''] * len(fields)
    return [sig(name, f's16@{i * 2}', .1, unit=unit, key=f'ecu.{name}') for i, (name, unit) in enumerate(zip(fields, units)) if name]


# The real-time broadcast groups (base 0x5F0, or 0x700): group number -> signals.
ECU_GROUPS = {
    0: [sig('seconds', 'u16@0', unit='s', key='ecu.seconds'), sig('pw1_ms', 'u16@2', .001, unit='ms', key='ecu.pw1_ms'),
        sig('pw2_ms', 'u16@4', .001, unit='ms', key='ecu.pw2_ms'), sig('rpm', 'u16@6', unit='rpm', key='ecu.rpm')],
    1: [sig('spark_deg', 's16@0', .1, unit='deg', key='ecu.spark_deg'), sig('injection_flags', 'u8@2', key='ecu.injection_flags'),
        sig('engine_flags', 'u8@3', key='ecu.engine_flags'), sig('afr_target', 'u8@4', .1, key='ecu.afr_target'),
        sig('afr2_target', 'u8@5', .1, key='ecu.afr2_target')],
    2: [sig('baro_kpa', 's16@0', .1, unit='kPa', key='ecu.baro_kpa'), sig('map_kpa', 's16@2', .1, unit='kPa', key='ecu.map_kpa'),
        sig('iat_c', 's16@4', *TEMP, unit='C', key='ecu.iat_c'), sig('coolant_c', 's16@6', *TEMP, unit='C', key='ecu.coolant_c')],
    3: tenths('throttle_pct', 'battery_v', 'afr', 'afr2', units=['%', 'V', '', '']),
    4: tenths('knock_pct', 'ego_correction_pct', 'ego2_correction_pct', 'air_correction_pct', units=['%'] * 4),
    5: tenths('warmup_correction_pct', 'tps_accel_pct', 'tps_fuel_cut_pct', 'baro_correction_pct', units=['%'] * 4),
    6: [*tenths('total_correction_pct', 've1', 've2', units=['%', '%', '%']), sig('idle_output_raw', 's16@6', key='ecu.idle_output_raw')],
    7: [sig('cold_advance_deg', 's16@0', .1, unit='deg', key='ecu.cold_advance_deg'),
        sig('tps_rate_pct_s', 's16@2', .1, unit='%/s', key='ecu.tps_rate_pct_s'),
        sig('map_rate_kpa_s', 's16@4', unit='kPa/s', key='ecu.map_rate_kpa_s'),
        sig('rpm_rate_rpm_s', 's16@6', 10, unit='rpm/s', key='ecu.rpm_rate_rpm_s')],
    8: [*tenths('maf_load', 'fuel_load', 'flex_fuel_correction_pct', units=['', '', '%']),
        sig('maf_g_s', 's16@6', .01, unit='g/s', key='ecu.maf_g_s')],
    9: [sig('ego1_v', 's16@0', .01, unit='V', key='ecu.ego1_v'), sig('ego2_v', 's16@2', .01, unit='V', key='ecu.ego2_v'),
        sig('dwell_ms', 'u16@4', .1, unit='ms', key='ecu.dwell_ms'), sig('trailing_dwell_ms', 'u16@6', .1, unit='ms', key='ecu.trailing_dwell_ms')],
    10: [*same('ecu', 'status1', 'status2', 'status3', 'status4'), sig('status5', 's16@4', key='ecu.status5'),
         sig('status6', 'u8@6', key='ecu.status6'), sig('status7', 'u8@7', key='ecu.status7')],
    11: [*tenths('fuel_load2', 'ignition_load', 'ignition_load2'), sig('estimated_iat_c', 's16@6', *TEMP, unit='C', key='ecu.estimated_iat_c')],
    12: [sig('wall_fuel1_us', 's32@0', .01, unit='us', key='ecu.wall_fuel1_us'), sig('wall_fuel2_us', 's32@4', .01, unit='us', key='ecu.wall_fuel2_us')],
    13: tenths('sensor1', 'sensor2', 'sensor3', 'sensor4'),
    14: tenths('sensor5', 'sensor6', 'sensor7', 'sensor8'),
    15: tenths('sensor9', 'sensor10'),
    17: [sig('boost_target_kpa', 's16@0', .1, unit='kPa', key='ecu.boost_target_kpa'), sig('boost_duty_pct', 'u8@4', unit='%', key='ecu.boost_duty_pct'),
         sig('maf_v', 's16@6', .001, unit='V', key='ecu.maf_v')],
    18: [sig(f'pwseq{i + 1}_ms', f's16@{i * 2}', .001, unit='ms', key=f'ecu.pwseq{i + 1}_ms') for i in range(4)],
    26: [sig('nitrous_added_pw_ms', 's16@4', .001, unit='ms', key='ecu.nitrous_added_pw_ms'),
         sig('nitrous_retard_deg', 's16@6', .1, unit='deg', key='ecu.nitrous_retard_deg')],
    27: [sig(f'can_pwm_period{i + 1}', f's16@{i * 2}', key=f'ecu.can_pwm_period{i + 1}') for i in range(4)],
    28: [sig('idle_target_rpm', 'u16@0', unit='rpm', key='ecu.idle_target_rpm'), sig('tps_adc', 's16@2', key='ecu.tps_adc'),
         sig('eae_load', 's16@4', .1, key='ecu.eae_load'), sig('afr_load', 's16@6', .1, key='ecu.afr_load')],
    29: [sig('eae_correction1_pct', 'u16@0', .1, unit='%', key='ecu.eae_correction1_pct'),
         sig('eae_correction2_pct', 'u16@2', .1, unit='%', key='ecu.eae_correction2_pct')],
    43: [sig('sync_loss_count', 'u8@0', key='ecu.sync_loss_count'), sig('sync_loss_reason', 'u8@1', key='ecu.sync_loss_reason'),
         sig('timing_error_pct', 's8@7', unit='%', key='ecu.timing_error_pct')],
}


def ecu_messages():
    out = [(0x5E8 + n, f'MS_DASH_{n}', 8, 'ECU', 'MegaSquirt simplified dash broadcast', signals) for n, signals in enumerate(ECU_SIMPLE)]
    for base, label in ((0x5F0, 'MS_RT'), (0x700, 'MS_RT_ALT')):
        out += [(base + group, f'{label}_{group:02d}', 8, 'ECU', f'MegaSquirt real-time broadcast group {group} (base 0x{base:03X})', signals)
                for group, signals in ECU_GROUPS.items()]
    return out


def layout(text):
    """(start bit in DBC numbering, length, byte order, signed) for a layout string."""
    kind, place = text.split('@')
    if kind in ('bit', 'nib'):
        byte, bit = map(int, place.split('.'))
        return byte * 8 + bit, 1 if kind == 'bit' else 4, 'little_endian', False
    byte = int(place)
    if kind in ('u8', 's8'):
        return byte * 8, 8, 'little_endian', kind == 's8'
    if kind == 'u16le':
        return byte * 8, 16, 'little_endian', False
    length = {'u16': 16, 's16': 16, 'u32': 32, 's32': 32}[kind]
    return byte * 8 + 7, length, 'big_endian', kind.startswith('s')


def build():
    messages, nodes = [], set()
    for frame_id, name, length, sender, comment, signals in MESSAGES + ecu_messages():
        nodes.add(sender)
        muxed = any(s[7] for s in signals)
        built = []
        for index, (sname, text, scale, offset, unit, key, choices, mux) in enumerate(signals):
            start, size, order, signed = layout(text)
            built.append(Signal(sname, start, size, order, signed, unit=unit or None,
                                conversion=BaseConversion.factory(scale=scale, offset=offset, choices=choices),
                                comment=f'Dash: {key}' if key else None,
                                is_multiplexer=muxed and index == 0,
                                multiplexer_ids=mux, multiplexer_signal=signals[0][0] if mux else None))
        messages.append(Message(frame_id, name, length, built, comment=comment, senders=[sender]))
    database = Database(messages, [Node(n) for n in sorted(nodes)], version='frogdash')
    return database


def keys():
    """{frame id: [(signal name, dash key, multiplexer ids)]}: what tests/test_dbc.py compares."""
    return {frame_id: [(s[0], s[5], s[7]) for s in signals if s[5]] for frame_id, _, _, _, _, signals in MESSAGES + ecu_messages()}


def text():
    return build().as_dbc_string().replace('\r\n', '\n')


if __name__ == '__main__':
    OUT.write_text(text(), encoding='utf-8', newline='\n')
    print(f'Wrote {OUT.relative_to(ROOT)}: {len(build().messages)} messages')
    sys.exit(0)
