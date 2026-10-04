#!/usr/bin/env python3
"""Join a Wi-Fi network for internet (updates), on request from the dash.

Run as root by frogdash-wifi.service when the dash writes wifi-request.json into its
state directory (Controls > Wi-Fi > Internet). Only three fixed actions are accepted:
scan, connect (SSID + password) and disconnect. It uses the Pi's built-in Wi-Fi so a
USB adapter stays on the dash cam. The password is passed to NetworkManager, which
stores it; the request file is deleted as soon as it is read.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

STATE = Path(os.path.realpath('/var/lib/frogdash'))
REQUEST, STATUS = STATE / 'wifi-request.json', STATE / 'wifi-status.json'
SSID = re.compile(r'[\x20-\x7E]{1,32}')
PASSWORD = re.compile(r'[\x20-\x7E]{8,63}')


def nmcli(*args, timeout=45):
    result = subprocess.run(['/usr/bin/nmcli', *args], capture_output=True, text=True, timeout=timeout, env={**os.environ, 'LC_ALL': 'C'})
    return result.returncode, result.stdout, result.stderr.strip()


def interface():
    """The built-in Wi-Fi (not USB); the USB adapter is left for the dash cam."""
    devices = sorted(p.name for p in Path('/sys/class/net').glob('wlan*'))
    builtin = [d for d in devices if 'usb' not in os.path.realpath(f'/sys/class/net/{d}/device')]
    return (builtin or devices or ['wlan0'])[0]


def split(line):
    """Split one nmcli -t line on unescaped colons."""
    return [part.replace('\\:', ':').replace('\\\\', '\\') for part in re.split(r'(?<!\\):', line)]


def survey(device):
    saved = {split(line)[0] for line in nmcli('-t', '-f', 'NAME,TYPE', 'con', 'show')[1].splitlines() if line.endswith(':802-11-wireless')}
    networks = {}
    for line in nmcli('-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list', 'ifname', device)[1].splitlines():
        used, ssid, signal, security = (split(line) + ['', '', '', ''])[:4]
        if not SSID.fullmatch(ssid) or ssid.startswith('DC-'):
            continue  # Hidden networks and the dash cam's own access point.
        entry = {'ssid': ssid, 'signal': int(signal or 0), 'secure': bool(security and security != '--'),
                 'saved': ssid in saved or f'frogdash-{ssid}' in saved, 'connected': used == '*'}
        if ssid not in networks or entry['signal'] > networks[ssid]['signal'] or entry['connected']:
            networks[ssid] = entry
    current = next((n['ssid'] for n in networks.values() if n['connected']), None)
    address = nmcli('-g', 'IP4.ADDRESS', 'dev', 'show', device)[1].split('/')[0].strip() or None
    online = nmcli('networking', 'connectivity', 'check')[1].strip() == 'full'
    return {'interface': device, 'connected': current, 'address': address, 'internet': online,
            'networks': sorted(networks.values(), key=lambda n: -n['signal'])[:20]}


def write(state, message, device):
    body = {'state': state, 'message': message, 'time': int(time.time()), **survey(device)}
    temporary = STATUS.with_suffix('.tmp')
    temporary.write_text(json.dumps(body), encoding='utf-8')
    temporary.chmod(0o644)
    temporary.replace(STATUS)


def main():
    device = interface()
    try:
        request = json.loads(REQUEST.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        request = {'action': 'scan'}
    finally:
        REQUEST.unlink(missing_ok=True)
    action, ssid, password = request.get('action'), request.get('ssid'), request.get('password') or ''
    if action == 'connect':
        if not isinstance(ssid, str) or not SSID.fullmatch(ssid) or (password and not PASSWORD.fullmatch(password)):
            return write('failed', 'Invalid network name or password (8 to 63 characters)', device)
        name = f'frogdash-{ssid}'
        if password:
            nmcli('con', 'delete', name)
            code, _, error = nmcli('--wait', '30', 'dev', 'wifi', 'connect', ssid, 'password', password, 'ifname', device, 'name', name)
        else:
            code, _, error = nmcli('--wait', '30', 'con', 'up', name, 'ifname', device)
            if code:
                code, _, error = nmcli('--wait', '30', 'dev', 'wifi', 'connect', ssid, 'ifname', device, 'name', name)
        if code:
            wrong = 'Secrets were required' in error or '802-11-wireless-security' in error
            return write('failed', 'Wrong password' if wrong else f'Could not join {ssid}: {error[:120]}', device)
        nmcli('con', 'modify', name, 'connection.autoconnect', 'yes', 'connection.autoconnect-priority', '10')
        return write('connected', f'Joined {ssid}', device)
    if action == 'disconnect':
        nmcli('dev', 'disconnect', device)
        return write('idle', 'Disconnected', device)
    nmcli('dev', 'wifi', 'rescan', 'ifname', device)
    time.sleep(3)
    write('idle', 'Scan complete', device)


if __name__ == '__main__':
    main()
