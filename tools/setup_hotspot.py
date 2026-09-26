"""Provision an OFF-by-default WPA2 hotspot on the Pi. Run with sudo after install.

Never runs on the development computer. Does not activate the AP or overwrite an
existing profile. Configure the correct WLAN country through raspi-config first.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from uuid import uuid4


def profile(identifier, interface, ssid, password):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', interface):
        raise ValueError('Invalid wireless interface name')
    if not re.fullmatch(r'[a-zA-Z0-9 _-]{1,32}', ssid):
        raise ValueError('SSID must be 1-32 ASCII letters, numbers, spaces, _ or -')
    if not re.fullmatch(r'[a-zA-Z0-9]{16,63}', password):
        raise ValueError('Use a generated 16-63 character alphanumeric password')
    return f'''[connection]
id=frogdash-hotspot
uuid={identifier}
type=wifi
interface-name={interface}
autoconnect=false

[wifi]
mode=ap
band=bg
ssid={ssid}
hidden=false

[wifi-security]
key-mgmt=wpa-psk
proto=rsn;
pairwise=ccmp;
group=ccmp;
psk={password}

[ipv4]
method=shared
address1=10.42.0.1/24
never-default=true

[ipv6]
method=disabled
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', default='wlan0')
    parser.add_argument('--ssid', default='Frogdash')
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() != 0:
        parser.error('Run with sudo on the Raspberry Pi')
    identifier = str(uuid4())
    password = ''.join(secrets.choice('abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(20))
    try:
        content = profile(identifier, args.interface, args.ssid, password)
    except ValueError as exc:
        parser.error(str(exc))
    ap = subprocess.run(['/usr/bin/nmcli', '-g', 'WIFI-PROPERTIES.AP', 'device', 'show', args.interface],
                        check=True, capture_output=True, text=True, env={**os.environ, 'LC_ALL': 'C'}).stdout.strip()
    if ap != 'yes':
        parser.error('This Wi-Fi adapter does not advertise AP/hotspot support')
    config = Path('/etc/frogdash/hotspot.json')
    connection = Path('/etc/NetworkManager/system-connections/frogdash-hotspot.nmconnection')
    if config.exists() or connection.exists():
        parser.error('Hotspot configuration already exists; preserve or remove it explicitly before reprovisioning')
    subprocess.run(['groupadd', '--system', '--force', 'frogdash-connect'], check=True)
    config.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.umask(0o077)
    with config.open('x') as output:
        json.dump({'uuid': identifier, 'ssid': args.ssid, 'password': password}, output)
    with connection.open('x') as output:
        output.write(content)
    subprocess.run(['/usr/bin/nmcli', 'connection', 'load', str(connection)], check=True)
    print('Created protected hotspot profile. It remains OFF. Install the helper unit and dashboard drop-in next.')


if __name__ == '__main__':
    main()
