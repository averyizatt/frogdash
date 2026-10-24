"""Is the Pi on Wi-Fi, and does it reach the internet: the indicator on the Software card.

Wi-Fi from NetworkManager (each adapter that is connected, by network name), else from the
adapters' link state; the internet is GitHub answering, which is what an update needs. Both
are looked at no more than every CHECK_S, so a screen polling it costs nothing.
"""
from pathlib import Path
import socket
import subprocess
import time

CHECK_S = 10
NET = Path('/sys/class/net')
_last = {'at': float('-inf'), 'value': None}


def wifi_networks():
    """Names of the Wi-Fi networks joined now; [''] when an adapter is up but unnamed."""
    try:
        out = subprocess.run(['nmcli', '-t', '-f', 'TYPE,STATE,CONNECTION', 'device'],
                             capture_output=True, text=True, timeout=3).stdout
        names = []
        for line in out.splitlines():
            kind, _, rest = line.partition(':')
            state, _, name = rest.partition(':')
            if kind == 'wifi' and state == 'connected':
                names.append(name.replace('\\:', ':'))
        return names
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return ['' for adapter in NET.iterdir() if (adapter / 'wireless').exists()
                and (adapter / 'operstate').read_text().strip() == 'up']
    except OSError:
        return []


def internet(host='github.com', port=443):
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def check(clock=time.monotonic):
    if clock() - _last['at'] >= CHECK_S or _last['value'] is None:
        _last['value'] = {'wifi': wifi_networks(), 'internet': internet()}
        _last['at'] = clock()
    return _last['value']
