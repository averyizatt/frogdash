"""Plain-language CAN check: is each expected message arriving, valid and fault-free?

Built from per-ID statistics kept by State.ingest (count, last time, last payload and
the last decode error), so it works even when a module's frames are being rejected.
"""
from .protocol import ECU_TIMEOUT, LENGTHS, TIMEOUTS

# (module, id, what it carries, sent only on events/requests)
EXPECTED = [
    ('Taillights', 0x100, 'Lamp state and inputs', False),
    ('Taillights', 0x103, 'Settings status (PCB firmware with CAN settings)', False),
    ('Comfort gateway', 0x202, 'Tach status', False),
    ('Comfort gateway', 0x500, 'Speed, RPM and fuel', False),
    ('Comfort gateway', 0x501, 'Steering wheel buttons', False),
    ('Comfort gateway', 0x503, 'Interior light state', False),
    ('Water/meth', 0x300, 'Pump state, tank, flow and faults', False),
    ('Water/meth', 0x303, 'Pressure and temperature sensors', False),
    ('Water/meth', 0x307, 'Knock monitor', False),
    ('Water/meth', 0x30F, 'Pulse tuning status and intake air temperatures', False),
    ('MicroSquirt', 0x5E8, 'Dash broadcast (MAP, RPM, coolant, TPS)', False),
    ('MicroSquirt', 0x5F0, 'Realtime broadcast group 0', False),
    ('MicroSquirt', 0x5F2, 'Realtime group 2 (baro, MAP, temperatures)', False),
]
METH_FAULTS = [
    (1, 'Tank low (float switch) or low-fluid failsafe', 'Fill the tank or check the float switch wiring'),
    (2, 'MAP sensor reading invalid', "Check the water/meth controller's MAP sensor wiring and vacuum line"),
    (4, 'Overboost assist active', 'Information: extra injection for overboost'),
    (8, 'Overboost emergency or assist fault latched', 'Check boost control; clear faults once resolved'),
    (16, 'Invalid blend or boost configuration', 'Re-send the boost start setting from Controls'),
    (32, 'No command master seen for 3 s', 'Normal until the dash sends its first command or engine RPM (0x309)'),
]
SENSOR_BITS = ['Oil pressure', 'Fuel pressure', 'Meth pressure', 'Boost reference', 'Intake air temp',
               'Engine bay temp', 'Ambient temp', 'Cabin temp']
BUTTONS = [(1, 'ON'), (2, 'OFF'), (4, 'COAST'), (8, 'SET/ACCEL'), (16, 'RESUME')]
STATES = ['OFF', 'ARMED', 'SPRAYING', 'FAULT', 'TEST']
FLOWS = ['UNKNOWN', 'OK', 'LOW_FLOW', 'NO_FLOW']


def timeout(can_id):
    return ECU_TIMEOUT if 0x5E8 <= can_id <= 0x73F else TIMEOUTS.get(can_id, .5)


def meth_detail(data):
    """Explain a 0x300 payload byte by byte, including out-of-range values."""
    notes = []
    state = STATES[data[0]] if data[0] < len(STATES) else f'invalid state {data[0]}'
    notes.append(f'State {state}, pump {data[1]}%, tank {data[2]}%, flow {FLOWS[data[3]] if data[3] < len(FLOWS) else data[3]}')
    if data[1] > 100:
        notes.append(f'Pump duty byte is {data[1]} (must be 0-100): controller firmware does not match this dash')
    if data[2] > 100:
        notes.append(f'Tank byte is {data[2]} (must be 0-100): tank level sensor not connected, or firmware mismatch')
    if data[3] == 0:
        notes.append('Flow UNKNOWN is normal when the pump is not running')
    for bit, meaning, action in METH_FAULTS:
        if data[7] & bit:
            notes.append(f'Fault bit {bit}: {meaning}. {action}.')
    if data[7] & ~63:
        notes.append(f'Unknown fault bits 0x{data[7] & ~63:02X}: firmware newer or different from this dash')
    if not data[7] and data[0] != 3:
        notes.append('No faults reported')
    return notes


def sensor_detail(data):
    flags = data[6] | data[7] << 8
    bad = [name for bit, name in enumerate(SENSOR_BITS) if flags & (1 << bit)]
    return [f'Sensor faults: {", ".join(bad)} (unplugged or out of range)'] if bad else ['All analog sensors in range']


def report(state):
    now = state.clock()
    rows = []
    for module, can_id, purpose, _event in EXPECTED:
        seen = state.frames.get(can_id)
        row = {'module': module, 'id': f'0x{can_id:03X}', 'purpose': purpose, 'data': None, 'rate_hz': None, 'notes': []}
        if not seen:
            row['status'], row['summary'] = 'missing', 'Never received since the dash started'
            if can_id in (0x5F0, 0x5F2):
                alternate = state.frames.get(can_id + 0x110)  # Base 1792 (0x700) instead of 1520.
                if alternate:
                    seen, row['id'] = alternate, f'0x{can_id + 0x110:03X}'
            if not seen:
                rows.append(row)
                continue
        age = now - seen['seen']
        span = seen['seen'] - seen['first']
        row['data'] = seen['data']
        row['rate_hz'] = round((seen['count'] - 1) / span, 1) if span > 0 and seen['count'] > 1 else None
        data = bytes.fromhex(seen['data'])
        if seen['error'] and seen['error_at'] == seen['seen']:
            row['status'], row['summary'] = 'rejected', f'Arriving but rejected: {seen["error"]}'
            expected = LENGTHS.get(can_id, 8)
            if len(data) != expected:
                row['notes'].append(f'Length is {len(data)} bytes, this dash expects {expected}: the module firmware is a different version. Flash the current firmware.')
        elif age > max(2.0, timeout(can_id) * 2):
            row['status'], row['summary'] = 'stopped', f'Stopped {age:.0f} s ago (module off, unplugged, or bus fault)'
        else:
            row['status'], row['summary'] = 'ok', 'Arriving and valid'
        if can_id == 0x300 and len(data) == 8:
            row['notes'] += meth_detail(data)
            if row['status'] == 'ok' and (data[7] or data[0] == 3 or data[1] > 100 or data[2] > 100):
                row['status'], row['summary'] = 'fault', 'Arriving; the controller reports a fault'
        elif can_id == 0x303 and len(data) == 8:
            row['notes'] += sensor_detail(data)
        elif can_id == 0x501 and len(data) == 4:
            names = [name for bit, name in BUTTONS if data[0] & bit]
            row['notes'].append('Pressed now: ' + (' + '.join(names) if names else 'nothing') + f' · press count {data[2]}')
            row['notes'].append('ON = select, OFF = back, SET/ACCEL = up, COAST = down, RESUME = right. '
                                'If ON never shows here while pressed, the yellow wire is not reaching a HIGH level at the gateway pin.')
            if len(names) > 1:
                row['notes'].append('Two buttons at once cancel each other: if ON shows all the time, it is stuck high and blocks every other button.')
        elif can_id == 0x500 and len(data) == 8:
            row['notes'].append(f'Speed {int.from_bytes(data[0:2], "big") / 10:.1f} km/h, RPM {int.from_bytes(data[2:4], "big")}, '
                                f'fuel raw {int.from_bytes(data[4:6], "big")}, fuel ' + ('invalid' if data[6] == 255 else f'{data[6]}%'))
        rows.append(row)
    unknown = sorted(i for i in state.frames if not any(i == e[1] for e in EXPECTED))
    return {'rows': rows, 'other_ids': [f'0x{i:03X}' for i in unknown][:80],
            'received': state.received, 'malformed': state.malformed, 'status': state.status}
