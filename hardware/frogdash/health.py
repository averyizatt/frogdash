"""Read-only Linux/Pi diagnostics, sampled off the telemetry loop. No GPIO access."""
import asyncio
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


def throttled_flags(value):
    flags = int(value.strip().split('=')[-1], 16)
    return {'raw': flags, 'undervoltage_now': bool(flags & 1), 'throttled_now': bool(flags & 4),
            'undervoltage_since_boot': bool(flags & (1 << 16)), 'throttled_since_boot': bool(flags & (1 << 18))}


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=2, check=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.stdout


def read_ups(path=Path('/run/frogdash-power/status.json'), now=None):
    """Read the broker's public status only; never expose its privileged socket."""
    now = time.monotonic() if now is None else now
    unknown = {'available': False, 'battery_percent': None, 'battery_volts': None,
               'charging': None, 'auto_power_on': None, 'input_present': None}
    try:
        if path.stat().st_size > 16384:
            raise ValueError('Oversized UPS status')
        data = json.loads(path.read_text(encoding='utf-8'))
        age = now - data['monotonic']
        if not math.isfinite(age) or not 0 <= age <= 3:
            raise ValueError('UPS monitor status is stale')
        result = {**unknown, 'available': True, 'state': data.get('state'),
                  'error': data.get('error'), 'dry_run': data.get('dry_run') is True}
        present = data.get('input_present')
        result['input_present'] = present if type(present) is bool else None
        remaining = data.get('remaining_seconds')
        result['remaining_seconds'] = remaining if type(remaining) in (int, float) and math.isfinite(remaining) and 0 <= remaining <= 10 else None
        ups = data.get('ups', {})
        telemetry_age = now - ups.get('sampled_monotonic', -100)
        if math.isfinite(telemetry_age) and 0 <= telemetry_age <= 15:
            for key, maximum in (('battery_percent', 100), ('battery_volts', 6)):
                value = ups.get(key)
                if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum:
                    result[key] = value
            for key in ('charging', 'auto_power_on'):
                if type(ups.get(key)) is bool:
                    result[key] = ups[key]
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return unknown


class Health:
    def __init__(self, state, interface='can0', directory=None):
        self.state, self.interface = state, interface
        self.directory = Path(directory) if directory else Path.cwd()
        self.status = {'status': 'waiting', 'cpu_c': None, 'power': None, 'disk': None, 'can': None}
        self.stopping = False

    def collect(self):
        data = {'status': 'sampled', 'timestamp_ms': int(time.time() * 1000), 'cpu_c': None,
                'power': None, 'disk': None, 'can': None, 'notes': [], 'ups': read_ups(),
                'shutdown': self.state.shutdown_history.snapshot() if self.state.shutdown_history else None}
        try:
            path = self.directory
            while not path.exists() and path.parent != path:
                path = path.parent
            usage = shutil.disk_usage(path)
            data['disk'] = {'free_bytes': usage.free, 'total_bytes': usage.total}
        except OSError:
            data['notes'].append('Storage usage unavailable')
        if os.name != 'posix':
            data['notes'].append('Pi and SocketCAN diagnostics require Linux hardware')
            return data
        try:
            data['cpu_c'] = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
        except (OSError, ValueError):
            data['notes'].append('CPU temperature unavailable')
        vcgencmd = shutil.which('vcgencmd')
        try:
            if not vcgencmd:
                raise FileNotFoundError()
            data['power'] = throttled_flags(command(vcgencmd, 'get_throttled'))
        except (OSError, ValueError, subprocess.SubprocessError):
            data['notes'].append('Pi voltage/throttling status unavailable to this service')
        ip = shutil.which('ip')
        try:
            if not ip or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', self.interface):
                raise ValueError()
            links = json.loads(command(ip, '-j', '-details', '-statistics', 'link', 'show', 'dev', self.interface))
            link = links[0]
            info = link.get('linkinfo', {}).get('info_data', {})
            stats = link.get('stats64', link.get('stats', {}))
            data['can'] = {'interface': self.interface, 'state': info.get('state', link.get('operstate')),
                           'bitrate': info.get('bittiming', {}).get('bitrate'),
                           'error_counters': info.get('berr_counter'),
                           'rx_errors': stats.get('rx', {}).get('errors'), 'tx_errors': stats.get('tx', {}).get('errors'),
                           'rx_dropped': stats.get('rx', {}).get('dropped'), 'tx_dropped': stats.get('tx', {}).get('dropped')}
        except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError):
            data['notes'].append('CAN interface diagnostics unavailable')
        return data

    async def run(self):
        while not self.stopping:
            self.status = await asyncio.to_thread(self.collect)
            for _ in range(50):
                if self.stopping:
                    break
                await asyncio.sleep(.1)
