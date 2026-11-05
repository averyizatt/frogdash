#!/usr/bin/env python3
"""Join a Wi-Fi network for internet (updates), on request from the dash.

Run as root by frogdash-wifi.service when the dash writes wifi-request.json into its
state directory (Controls > Wi-Fi > Internet). Only three fixed actions are accepted:
scan, connect (SSID + password) and disconnect. It scans with every Wi-Fi adapter the
dash cam connection does not use, and joins with each adapter in turn (wlan0, wlan1)
until one works. The password is passed to NetworkManager, which stores it; the request
file is deleted as soon as it is read.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

STATE = Path(os.path.realpath('/var/lib/frogdash'))
REQUEST, STATUS = STATE / 'wifi-request.json', STATE / 'wifi-status.json'
PASSWORD = re.compile(r'[\x20-\x7E]{8,63}')


def valid_ssid(name):
    """A network name: 1 to 32 bytes, any printable characters. An iPhone names its
    hotspot "Avery’s iPhone" with a curly apostrophe; plain ASCII only hid it from the list
    and refused it on connect (October 2026)."""
    return isinstance(name, str) and 0 < len(name.encode('utf-8')) <= 32 and name.isprintable()


def nmcli(*args, timeout=45):
    # C.UTF-8: messages in English, and network names that are not plain ASCII come back intact.
    result = subprocess.run(['/usr/bin/nmcli', *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=timeout, env={**os.environ, 'LC_ALL': 'C.UTF-8'})
    return result.returncode, result.stdout, result.stderr.strip()


LOCK = Path('/run/frogdash-wifi.lock')
CHOICE = Path('/etc/frogdash/wifi-internet')  # Optional: the adapter to use for internet, e.g. wlan1.
LAST = STATE / 'wifi-adapter'                 # The adapter that last joined a network: tried first.


def dashcam_device():
    return nmcli('-g', 'connection.interface-name', 'con', 'show', 'dashcam')[1].strip()


def builtin(device):
    return 'usb' not in os.path.realpath(f'/sys/class/net/{device}/device')


def remembered(path):
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def adapters():
    """Every Wi-Fi adapter, in the order to try them for internet.

    /etc/frogdash/wifi-internet (the owner's choice) first, then the adapter that last
    joined a network, then the ones the dash cam does not use (built-in first), and the
    dash cam's own adapter last: it is borrowed and handed back. In the car the built-in
    Wi-Fi could not join the phone hotspot and wlan1 could (November 2026): one adapter
    that cannot reach a network must never be the end of it.
    """
    devices = sorted(p.name for p in Path('/sys/class/net').glob('wlan*'))
    dashcam = dashcam_device()
    order = sorted(devices, key=lambda d: (d == dashcam, not builtin(d), d))
    last, chosen = remembered(LAST), remembered(CHOICE)
    if last in order and last != dashcam:
        order.remove(last)
        order.insert(0, last)
    if chosen in order:
        order.remove(chosen)
        order.insert(0, chosen)
    return order or ['wlan0']


def interface():
    """The Wi-Fi adapter tried first for internet (see adapters)."""
    return adapters()[0]


def radio_on():
    """A fresh card can start with Wi-Fi switched off or blocked: then no scan finds anything."""
    for command in (['rfkill', 'unblock', 'wifi'], ['/usr/bin/nmcli', 'radio', 'wifi', 'on']):
        try:
            subprocess.run(command, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


def split(line):
    """Split one nmcli -t line on unescaped colons."""
    return [part.replace('\\:', ':').replace('\\\\', '\\') for part in re.split(r'(?<!\\):', line)]


def survey(devices):
    """What the adapters see, merged: each network once, at its best signal."""
    devices = [devices] if isinstance(devices, str) else list(devices)
    saved = {split(line)[0] for line in nmcli('-t', '-f', 'NAME,TYPE', 'con', 'show')[1].splitlines() if line.endswith(':802-11-wireless')}
    networks, on = {}, None
    for device in devices:
        for line in nmcli('-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'dev', 'wifi', 'list', 'ifname', device)[1].splitlines():
            used, ssid, signal, security = (split(line) + ['', '', '', ''])[:4]
            if not valid_ssid(ssid) or ssid.startswith('DC-'):
                continue  # Hidden networks and the dash cam's own access point.
            entry = {'ssid': ssid, 'signal': int(signal or 0), 'secure': bool(security and security != '--'),
                     'saved': ssid in saved or f'frogdash-{ssid}' in saved, 'connected': used == '*'}
            if entry['connected']:
                on = on or device
            known = networks.get(ssid)
            if not known or entry['connected'] or (entry['signal'] > known['signal'] and not known['connected']):
                networks[ssid] = entry
    current = next((n['ssid'] for n in networks.values() if n['connected']), None)
    device = on or devices[0]
    address = nmcli('-g', 'IP4.ADDRESS', 'dev', 'show', device)[1].split('/')[0].strip() or None
    online = nmcli('networking', 'connectivity', 'check')[1].strip() == 'full'
    return {'interface': device, 'connected': current, 'address': address, 'internet': online,
            'networks': sorted(networks.values(), key=lambda n: -n['signal'])[:20]}


def write(state, message, devices):
    body = {'state': state, 'message': message, 'time': int(time.time()), **survey(devices)}
    temporary = STATUS.with_suffix('.tmp')
    temporary.write_text(json.dumps(body), encoding='utf-8')
    temporary.chmod(0o644)
    temporary.replace(STATUS)


def main():
    try:
        request = json.loads(REQUEST.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        request = {'action': 'scan'}
    finally:
        REQUEST.unlink(missing_ok=True)
    radio_on()
    devices, dashcam = adapters(), dashcam_device()
    action = request.get('action')
    if action == 'connect':
        return connect(request.get('ssid'), request.get('password') or '', devices, dashcam)
    if action == 'disconnect':
        device = survey(devices)['interface']
        nmcli('dev', 'disconnect', device)
        return write('idle', 'Disconnected', device)
    # Scan with every adapter the dash cam is not using (its own only when it is the only one).
    free = [d for d in devices if d != dashcam] or devices
    for device in free:
        nmcli('dev', 'wifi', 'rescan', 'ifname', device)
    time.sleep(3)
    write('idle', 'Scan complete', free)


def connect(ssid, password, devices, dashcam):
    if not valid_ssid(ssid) or (password and not PASSWORD.fullmatch(password)):
        return write('failed', 'Invalid network name or password (8 to 63 characters)', devices)
    tried, error = [], ''
    for device in devices:
        borrowing = device == dashcam
        if borrowing:  # The dash cam's adapter: take it off the dash cam; the Wi-Fi keeper returns it.
            LOCK.touch()
            nmcli('con', 'down', 'dashcam')
        try:
            code, error = join(device, ssid, password)
            if not code:
                return joined(device, ssid, borrowing, tried)
        finally:
            if borrowing:
                LOCK.unlink(missing_ok=True)
        if 'Secrets were required' in error or '802-11-wireless-security' in error:
            return write('failed', 'Wrong password', devices)   # Another adapter would not help.
        tried.append(device)
    return write('failed', f'Could not join {ssid} with {" or ".join(tried)}: {error[:120]}', devices)


def join(device, ssid, password):
    """Join with one adapter: (0, '') when joined, else nmcli's exit code and error."""
    name = f'frogdash-{ssid}'
    nmcli('dev', 'wifi', 'rescan', 'ifname', device)
    time.sleep(2)
    if password:
        nmcli('con', 'delete', name)
        code, _, error = nmcli('--wait', '30', 'dev', 'wifi', 'connect', ssid, 'password', password, 'ifname', device, 'name', name)
        if code:
            # "Secrets were required" with a correct password: nmcli guessed the wrong
            # security mode (WPA2/WPA3 mixed routers). Create the profile explicitly.
            for key_mgmt in ('wpa-psk', 'sae'):
                nmcli('con', 'delete', name)
                nmcli('con', 'add', 'type', 'wifi', 'ifname', device, 'con-name', name, 'ssid', ssid,
                      'wifi-sec.key-mgmt', key_mgmt, 'wifi-sec.psk', password)
                code, _, error = nmcli('--wait', '30', 'con', 'up', name, 'ifname', device)
                if not code:
                    break
    else:
        code, _, error = nmcli('--wait', '30', 'con', 'up', name, 'ifname', device)
        if code:
            code, _, error = nmcli('--wait', '30', 'dev', 'wifi', 'connect', ssid, 'ifname', device, 'name', name)
    return code, error


def joined(device, ssid, borrowing, tried):
    name = f'frogdash-{ssid}'
    # Not tied to this adapter: at the next start NetworkManager joins it on whichever one sees it.
    nmcli('con', 'modify', name, 'connection.interface-name', '')
    also = f' (with {device}: {" and ".join(tried)} could not)' if tried else ''
    if borrowing:
        # Saved for updates; the adapter goes back to the dash cam afterwards.
        nmcli('con', 'modify', name, 'connection.autoconnect', 'no')
        write('connected', f'Saved {ssid} for updates (internet checked){also}. Returning to the dash cam', device)
        nmcli('con', 'down', name)
        return
    try:
        LAST.write_text(device, encoding='utf-8')
    except OSError:
        pass
    nmcli('con', 'modify', name, 'connection.autoconnect', 'yes', 'connection.autoconnect-priority', '10')
    return write('connected', f'Joined {ssid}{also}', device)


if __name__ == '__main__':
    main()
