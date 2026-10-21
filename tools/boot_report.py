"""Read-only Linux boot/display report. No configuration changes or reboot.

Run: python3 /opt/frogdash/tools/boot_report.py --user foxbody
Use sudo only if journal access is denied. Paste the output for boot tuning.
"""
import argparse
import getpass
import os
from pathlib import Path
import re
import subprocess
import sys


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=8,
                                env={**os.environ, 'SYSTEMD_COLORS': '0', 'SYSTEMD_PAGER': 'cat', 'LC_ALL': 'C'})
        output = result.stdout.strip()
        if result.returncode:
            output += '\n' + (result.stderr.strip() or f'Exit status {result.returncode}')
        return output.strip() or '(no entries)'
    except FileNotFoundError:
        return f'{args[0]} unavailable'
    except subprocess.TimeoutExpired:
        return f'{args[0]} timed out after 8 seconds; continuing'
    except OSError as exc:
        return str(exc)


def section(title, value):
    print(f'\n--- {title} ---\n{value}', flush=True)


def usb_topology(root=Path('/sys/bus/usb/devices')):
    """Map kernel port names to devices, without serial numbers or network names."""
    lines = []
    for device in sorted(root.glob('*')):
        if not (device / 'idVendor').exists():
            continue
        fields = []
        for name in ('idVendor', 'idProduct', 'manufacturer', 'product', 'speed',
                     'power/control', 'power/runtime_status'):
            try:
                value = (device / name).read_text().strip().replace('\n', ' ')
                fields.append(f'{name}={value}')
            except OSError:
                pass
        drivers = sorted({p.resolve().name for p in root.glob(device.name + ':*/driver')})
        lines.append(f'{device.name}: ' + ', '.join(fields) + f'; drivers={",".join(drivers) or "none"}')
    return '\n'.join(lines) or 'No USB sysfs devices available'


def early_kiosk_lines(output):
    """Keep the first boot's timeline even after a software update restarts the kiosk."""
    lines = []
    for line in output.splitlines():
        match = re.match(r'\[\s*(\d+(?:\.\d+)?)\]', line)
        if match and float(match[1]) <= 60:
            lines.append((float(match[1]), line))
    return '\n'.join(line for _, line in sorted(lines)) or 'No kiosk milestones in the first 60 seconds'


def report(user):
    console = f'frogdash-console@{user}.service'
    print('Frogdash boot report (read-only; times start at kernel boot, not key-on)', flush=True)
    try:
        section('Operating system', Path('/etc/os-release').read_text())
    except OSError as exc:
        section('Operating system', str(exc))
    section('Architecture', command(['uname', '-m']))
    section('Default boot target', command(['systemctl', 'get-default']))
    section('Boot timing', command(['systemd-analyze', 'time']))
    section('Kernel version', command(['uname', '-r']))
    section('Slowest unit activation times (parallel durations do not add up)',
            '\n'.join(command(['systemd-analyze', 'blame', '--no-pager']).splitlines()[:20]))
    for unit in ('frogdash.service', console):
        section(f'Critical chain: {unit}', command(['systemd-analyze', 'critical-chain', unit, '--no-pager']))
    section('Dash, display manager, UPS and network waits', command([
        'systemctl', 'list-units', '--all', '--no-pager', '--plain',
        'frogdash*', 'display-manager*', '*wait-online*', 'pisugar*']))
    section('Enabled startup units', command([
        'systemctl', 'list-unit-files', '--no-pager',
        'frogdash*', 'display-manager*', '*wait-online*', 'pisugar*']))
    for unit in ('frogdash.service', console, 'display-manager.service'):
        section(f'Service timing and dependencies: {unit}', command([
            'systemctl', 'show', unit, '--no-pager',
            '--property=LoadState,ActiveState,SubState,ActiveEnterTimestampMonotonic,ExecMainStartTimestampMonotonic,After,Wants,Requires']))
    section('Kiosk launch and first render (current boot)', command([
        'journalctl', '-b', '--no-pager', '-o', 'short-monotonic', '-n', '30',
        '-u', console, '--grep=Frogdash kiosk:']))
    # Desktop kiosks are user units, so query their journal field as well.
    section('Desktop kiosk launch (if used)', command([
        'journalctl', '-b', '--no-pager', '-o', 'short-monotonic', '-n', '20',
        '_SYSTEMD_USER_UNIT=frogdash-kiosk.service', '--grep=Frogdash kiosk:']))
    # PAM/logind can move compositor/browser children into session scopes. A
    # unit-only journal query then misses the error causing the restart loop.
    uid = command(['id', '-u', user]).strip()
    if uid.isdecimal():
        section('First 60 seconds: kiosk timeline (all session scopes)', early_kiosk_lines(command([
            'journalctl', '-b', '--no-pager', '-o', 'short-monotonic',
            f'_UID={uid}', '--grep=Frogdash kiosk:'])))
        section('Kiosk user session logs (includes Cage/Chromium child processes)', command([
            'journalctl', '-b', '--no-pager', '-o', 'short-monotonic', '-n', '120', f'_UID={uid}']))
    section('Kiosk restart count and last exit', command([
        'systemctl', 'show', console, '--no-pager',
        '--property=NRestarts,Result,ExecMainCode,ExecMainStatus']))
    section('Recent console display errors', command([
        'journalctl', '-b', '--no-pager', '-o', 'short-monotonic', '-n', '20',
        '-p', 'warning', '-u', console]))
    connectors = []
    for status in sorted(Path('/sys/class/drm').glob('card*-*/status')):
        try:
            state = status.read_text().strip()
            modes = (status.parent / 'modes').read_text().strip()
            connectors.append(f'{status.parent.name}: {state}\nAdvertised modes (not proof of current mode):\n{modes or "none"}')
        except OSError as exc:
            connectors.append(f'{status.parent.name}: {exc}')
    section('Display connectors', '\n'.join(connectors) or 'No DRM connector information available')
    section('USB ports, devices, drivers and power state', usb_topology())
    section('USB topology reported by lsusb', command(['lsusb', '-t']))
    section('USB and graphics kernel warnings (current boot)', command([
        'journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic', '-n', '100',
        '--grep=error -71|clear tt|device descriptor|disconnect|reset .*USB|vc4|drm|under-voltage']))
    section('Pi voltage/throttling flags', command(['vcgencmd', 'get_throttled']))
    section('Memory', command(['free', '-m']))
    section('Browser files read early in boot (frogdash-warm)', command([
        'journalctl', '-b', '--no-pager', '-o', 'short-monotonic', '-n', '10', '-u', 'frogdash-warm.service']))
    section('Chromium as it runs (first processes, with their settings)',
            '\n'.join(line[:600] for line in command(['pgrep', '-a', 'chromium']).splitlines()[:3]))
    print('\nCompare with a video of key-on to visible gauges. A render heartbeat is a browser liveness observation, not proof the physical screen is lit.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', default=os.environ.get('SUDO_USER') or getpass.getuser(),
                        help='Normal Linux user running the console kiosk')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]*[$]?', args.user) or args.user == 'root':
        parser.error('--user must be the normal kiosk login, for example --user foxbody')
    if not sys.platform.startswith('linux'):
        parser.error('Run this report on the Linux Pi, not the development computer')
    report(args.user)


if __name__ == '__main__':
    main()
