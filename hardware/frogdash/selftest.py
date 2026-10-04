"""One-press system check: every subsystem as a pass / warning / fail line with a fix.

Read-only: it inspects what the dash already knows (CAN statistics, module frames,
GPS, cameras, helpers, storage and power) and never transmits on the bus.
"""
import json
import time

from . import cancheck

OK, WARN, FAIL, SKIP = 'ok', 'warn', 'fail', 'skip'


def line(group, name, status, detail, fix=''):
    return {'group': group, 'name': name, 'status': status, 'detail': detail, 'fix': fix if status in (WARN, FAIL) else ''}


def helper_status(folder, name):
    try:
        return json.loads((folder / name).read_text(encoding='utf-8'))
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def report(state, folder=None, wall=time.time):
    out = []
    health = state.health.status if state.health else {}
    module, can = health.get('can_module') or {}, health.get('can') or {}

    # --- CAN interface ---
    if not module:
        out.append(line('CAN bus', 'CAN module (MCP2515)', SKIP, 'Needs the Pi'))
    elif not module.get('present'):
        out.append(line('CAN bus', 'CAN module (MCP2515)', FAIL, 'Not detected at boot', 'Check SPI wiring, 3.3 V, the mcp2515 overlay and oscillator value'))
    elif not module.get('up'):
        out.append(line('CAN bus', 'CAN module (MCP2515)', FAIL, 'Found, but can0 is down', 'sudo systemctl enable --now frogdash-can.service'))
    else:
        out.append(line('CAN bus', 'CAN module (MCP2515)', OK, f"{module.get('spi') or 'SPI'} · can0 up at {can.get('bitrate') or '?'} bit/s"))
    bus_state = can.get('state')
    if bus_state:
        counters = can.get('error_counters') or {}
        errors = f"TX err {counters.get('tx', '?')}, RX err {counters.get('rx', '?')}"
        status = OK if bus_state == 'ERROR-ACTIVE' else FAIL if bus_state == 'BUS-OFF' else WARN
        out.append(line('CAN bus', 'Bus health', status, f'{bus_state} · {errors}',
                        'Check CAN-H/CAN-L, 60 ohm termination with power off, and 500 kbit/s on every node'))
    out.append(line('CAN bus', 'Traffic', OK if state.received else FAIL,
                    f'{state.received} frames received, {state.malformed} rejected',
                    'Nothing received: no other node is powered or the bus is not connected'))

    # --- Modules (from the CAN check) ---
    rows = cancheck.report(state)['rows']
    for name in ('Taillights', 'Comfort gateway', 'Water/meth', 'MicroSquirt'):
        mine = [r for r in rows if r['module'] == name]
        good = [r for r in mine if r['status'] == 'ok']
        bad = [r for r in mine if r['status'] in ('fault', 'rejected')]
        if bad:
            note = next((n for r in bad for n in r['notes'] if 'Fault bit' in n or 'firmware' in n or 'Sensor faults' in n), bad[0]['summary'])
            out.append(line('Modules', name, FAIL if any(r['status'] == 'rejected' for r in bad) else WARN,
                            f"{bad[0]['id']}: {note}", 'See Sensors > CAN check for each message'))
        elif good:
            missing = [r['id'] for r in mine if r['status'] in ('missing', 'stopped')]
            optional = name == 'MicroSquirt' or all(i == '0x103' for i in missing)
            out.append(line('Modules', name, OK if not missing or optional else WARN,
                            f"{len(good)} of {len(mine)} messages arriving" + (f" (not seen: {', '.join(missing)})" if missing else ''),
                            'A missing message usually means older module firmware or a feature switched off'))
        else:
            out.append(line('Modules', name, FAIL, 'No messages received',
                            'Module off, not on the bus, or (MicroSquirt) broadcasting not enabled in TunerStudio'))

    # --- Dash functions on the bus ---
    runtime = state.runtime.snapshot()
    out.append(line('Dash on the bus', 'Engine RPM for water/meth (0x309)',
                    FAIL if runtime['conflict'] else OK if runtime['tx_count'] else SKIP if not runtime['enabled'] else WARN,
                    runtime['status'], 'Another node also sends 0x309, or nothing acknowledges frames from the Pi'))
    tail = state.taillight.snapshot()
    out.append(line('Dash on the bus', 'Taillight settings link',
                    OK if tail['supported'] and tail['complete'] else WARN,
                    'Settings read back from the taillights' if tail['supported'] and tail['complete'] else
                    'Reading settings…' if tail['supported'] else 'No settings status (0x103)',
                    'Flash the taillight PCB firmware with CAN settings (esp32-s3-pcb)'))
    wheel = state.wheel.snapshot(state.connected and state.mode == 'socketcan')
    out.append(line('Dash on the bus', 'Steering wheel buttons', OK if wheel['status'] == 'ready' else WARN,
                    {'ready': 'Receiving button reports', 'release buttons': 'A button reads as held: release all buttons',
                     'unavailable': 'No button reports (0x501)'}[wheel['status']],
                    'Check the gateway is running and no button input is stuck (Sensors > CAN check, 0x501)'))
    interior = [state.controls.live(f'interior.{side}.brightness', 0x503, 1) for side in ('upper', 'lower')]
    out.append(line('Dash on the bus', 'Interior lights', OK if any(v is not None for v in interior) else WARN,
                    'Gateway reports both light zones' if all(v is not None for v in interior) else 'No interior light state (0x503)',
                    'Needs the comfort module sensor-gateway firmware'))

    # --- GPS and clock ---
    if state.gps:
        fix = state.gps.mode in (2, 3)
        out.append(line('GPS and time', 'USB GPS', OK if fix else WARN, state.gps.status,
                        'Needs sky view; check gpsd and the USB receiver if it never gets a fix'))
        out.append(line('GPS and time', 'GPS broadcast to the bus (0x203)', FAIL if state.gps.conflict else OK, state.gps.tx_status,
                        'Another node also sends 0x203; disable its GPS transmit'))
    else:
        out.append(line('GPS and time', 'USB GPS', SKIP, 'Not enabled (--gpsd)'))
    year = time.gmtime(wall()).tm_year
    out.append(line('GPS and time', 'Clock', OK if year >= 2026 else FAIL, time.strftime('%Y-%m-%d %H:%M', time.localtime(wall())),
                    'Clock not set: install the GPS clock (docs/reliability.md, Clock from GPS)'))

    # --- Cameras ---
    for name, camera, hint in (('Reverse camera', state.camera, 'Check the ribbon cable: rpicam-hello --list-cameras'),
                               ('Dash cam', state.dashcam, 'Check the dash cam is on and the USB Wi-Fi is joined to it')):
        if not camera:
            out.append(line('Cameras', name, SKIP, 'Not enabled'))
        else:
            status = camera.status()
            out.append(line('Cameras', name, FAIL if status['error'] else OK,
                            status['error'] or ('Streaming' if status['running'] else 'Ready (starts when opened)'), hint))

    # --- Pi health ---
    power = health.get('power') or {}
    if power:
        bad = power.get('undervoltage_now') or power.get('throttled_now')
        past = power.get('undervoltage_since_boot')
        out.append(line('Pi', 'Power supply', FAIL if bad else WARN if past else OK,
                        'Undervoltage now' if bad else 'Undervoltage seen since boot' if past else 'No undervoltage',
                        'Use a 5 V 3 A supply with short, thick wires; undervoltage causes crashes and SD corruption'))
    if health.get('cpu_c') is not None:
        out.append(line('Pi', 'Temperature', OK if health['cpu_c'] < 75 else WARN, f"{health['cpu_c']:.0f} °C", 'Add airflow or a heatsink above 75 °C'))
    disk = health.get('disk') or {}
    if disk:
        free = disk['free_bytes'] / 2 ** 30
        out.append(line('Pi', 'Storage', OK if free > 2 else WARN if free > .5 else FAIL, f'{free:.1f} GiB free', 'Delete old logs in Sensors > Saved data logs'))
    recording = state.recorder.status if state.recorder else {'state': 'disabled'}
    out.append(line('Pi', 'Data logging', {'recording': OK, 'error': FAIL}.get(recording.get('state'), SKIP),
                    recording.get('error') or recording.get('state', 'disabled'), 'Check the log directory is writable and not full'))

    # --- Helpers ---
    update, wifi = helper_status(folder, 'update-status.json'), helper_status(folder, 'wifi-status.json')
    out.append(line('Updates', 'Internet', OK if wifi and wifi.get('internet') else WARN,
                    f"{wifi.get('connected') or 'Not connected'}" + (' · internet OK' if wifi.get('internet') else ' · no internet') if wifi else 'Wi-Fi not checked yet',
                    'Controls > Wi-Fi > Internet: Scan and Connect (only needed for updates)'))
    out.append(line('Updates', 'Last update', FAIL if update and update.get('state') == 'failed' else OK if update else SKIP,
                    f"{update['message']} · version {update.get('version', '?')}" if update else 'Update not run yet',
                    'Dash management > Support > Update now, with internet connected'))

    counts = {s: sum(1 for item in out if item['status'] == s) for s in (OK, WARN, FAIL, SKIP)}
    return {'lines': out, 'counts': counts, 'time_ms': int(wall() * 1000)}
