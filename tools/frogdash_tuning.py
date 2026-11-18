#!/usr/bin/env python3
"""Root's part of tuning with Windows software (Tuning page). Run by frogdash-tuning.service
when the dash writes tuning-request.json; the result goes to tuning-status.json.

  usb_scan        mount the first USB stick read-only at /run/frogdash-usb; list its installers
  usb_copy NAME   copy one installer to /opt/frogdash-wine/installers (readable by the screen)
  usb_eject       unmount the stick
  share BUSID     share a USB device (an ECU or tuning cable that needs its maker's Windows
                  driver) with a Windows PC on the dash's network, over USB/IP (port 3240)
  unshare BUSID   stop sharing it; it is the Pi's again
  can_try SPEED   run the CAN bus at another speed for 20 s while the wizard listens for an
                  ECU, then back to the system profile's speed

Sharing: the PC runs usbip-win2 and attaches the device (usbip attach -r <dash> -b <busid>);
Windows then loads the maker's own driver and the tuner works as if the cable were plugged
into the PC. The device is shared only while asked, and only the one chosen.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

STATE = Path(os.path.realpath(os.environ.get('FROGDASH_STATE', '/var/lib/frogdash')))
REQUEST, STATUS = STATE / 'tuning-request.json', STATE / 'tuning-status.json'
MOUNT = Path(os.environ.get('FROGDASH_USB_MOUNT', '/run/frogdash-usb'))
INSTALLERS = Path(os.environ.get('FROGDASH_WINE_ROOT', '/opt/frogdash-wine')) / 'installers'
SYS_BLOCK = Path(os.environ.get('FROGDASH_SYS_BLOCK', '/sys/block'))
BUSID = re.compile(r'\d+-\d+(\.\d+)*')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,150}\.(exe|msi)', re.I)
MAX_BYTES = 2 * 1024 ** 3


def run(*args, timeout=30):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return result.returncode, (result.stdout + result.stderr).strip()


PROC_MOUNTS = Path(os.environ.get('FROGDASH_PROC_MOUNTS', '/proc/mounts'))


def stick():
    """The first partition of a USB disk (/dev/sda1...) that nothing has mounted, or None.
    A disk with any partition in use (a Pi that boots from a USB SSD) is never touched."""
    in_use = PROC_MOUNTS.read_text(encoding='utf-8') if PROC_MOUNTS.exists() else ''
    for disk in sorted(SYS_BLOCK.glob('sd*')):
        if 'usb' not in os.path.realpath(disk):
            continue
        parts = sorted(p.name for p in disk.iterdir() if p.name.startswith(disk.name))
        if any(re.search(rf'^/dev/{name}\s', in_use, re.M) for name in [disk.name, *parts]):
            continue
        return f'/dev/{parts[0] if parts else disk.name}'
    return None


def files():
    found = []
    for path in sorted(MOUNT.rglob('*')) if MOUNT.is_dir() else []:
        if path.is_file() and NAME.fullmatch(path.name) and len(path.relative_to(MOUNT).parts) <= 3:
            found.append({'name': str(path.relative_to(MOUNT)), 'mb': round(path.stat().st_size / 1e6, 1)})
    return found[:50]


def mounted():
    return os.path.ismount(MOUNT)


def usb_scan():
    if not mounted():
        device = stick()
        if not device:
            return 'No USB stick found: plug it into the Pi and press Look again'
        MOUNT.mkdir(parents=True, exist_ok=True)
        code, said = run('mount', '-o', 'ro,nosuid,nodev,noexec', device, str(MOUNT))
        if code:
            return f'The USB stick could not be read: {said[:160]}'
    found = files()
    return f'{len(found)} installer{"" if len(found) == 1 else "s"} on the USB stick' if found else 'No .exe or .msi installer on the USB stick'


def usb_copy(name):
    source = (MOUNT / name).resolve()
    if not mounted() or MOUNT.resolve() not in source.parents or not NAME.fullmatch(source.name) or not source.is_file():
        raise ValueError('That installer is not on the USB stick')
    if source.stat().st_size > MAX_BYTES:
        raise ValueError('That file is too big for an installer')
    INSTALLERS.mkdir(parents=True, exist_ok=True)
    os.chmod(INSTALLERS, 0o755)
    target = INSTALLERS / source.name
    shutil.copyfile(source, target)
    os.chmod(target, 0o644)
    return f'{source.name} copied to the Pi: Install it on the Tuning page'


def usb_eject():
    if mounted():
        code, said = run('umount', str(MOUNT))
        if code:
            return f'Could not eject: {said[:160]}'
    return 'The USB stick can be pulled out'


def shared():
    code, said = run('usbip', 'list', '-l')
    if code:
        return []
    # Bound devices show their busid; the driver line says usbip-host.
    out, current = [], None
    for line in said.splitlines():
        found = re.search(r'busid\s+(\S+)', line)
        if found:
            current = found.group(1)
        if current and 'usbip-host' in line:
            out.append(current)
    return sorted(set(out))


def share(busid):
    if not BUSID.fullmatch(busid or ''):
        raise ValueError('Not a USB device')
    run('modprobe', 'usbip-host')
    code, _ = run('pgrep', '-x', 'usbipd')
    if code:
        subprocess.Popen(['usbipd', '-D'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1)
    code, said = run('usbip', 'bind', '-b', busid)
    if code and 'already bound' not in said:
        raise ValueError(f'Could not share it: {said[:200]}')
    return f'Shared: attach it from the Windows PC (usbip attach -r <dash address> -b {busid})'


def unshare(busid):
    if not BUSID.fullmatch(busid or ''):
        raise ValueError('Not a USB device')
    code, said = run('usbip', 'unbind', '-b', busid)
    if code and 'not bound' not in said and 'unbind' not in said:
        raise ValueError(f'Could not stop sharing: {said[:200]}')
    if not shared():
        run('pkill', '-x', 'usbipd')
    return 'No longer shared: the device is the Pi\'s again'


CAN_SPEEDS = (125000, 250000, 500000, 1000000)
CAN_TRY_S = 20
TRIAL = STATE / 'can-trial.json'


def can_try(bitrate, sleep=time.sleep):
    """The setup wizard's connection test for an ECU at another bus speed: can0 at that
    speed for CAN_TRY_S, while the dash listens (can-trial.json tells it the speed), then
    back to the profile's own speed through frogdash-can.service, which always uses it."""
    if not str(bitrate).isdigit() or int(bitrate) not in CAN_SPEEDS:
        raise ValueError('Not a CAN bus speed')
    bitrate = int(bitrate)
    tmp = TRIAL.with_name(TRIAL.name + '.tmp')
    tmp.write_text(json.dumps({'bitrate': bitrate, 'until': time.time() + CAN_TRY_S}) + chr(10), encoding='utf-8')
    os.chmod(tmp, 0o644)
    os.replace(tmp, TRIAL)
    try:
        run('ip', 'link', 'set', 'dev', 'can0', 'down')
        code, said = run('ip', 'link', 'set', 'dev', 'can0', 'up', 'type', 'can', 'bitrate', str(bitrate), 'restart-ms', '100')
        if code:
            raise ValueError(f'The CAN board could not run at {bitrate // 1000} kbit/s: {said[:160]}')
        sleep(CAN_TRY_S)
    finally:
        TRIAL.unlink(missing_ok=True)
        run('systemctl', 'restart', 'frogdash-can.service', timeout=30)
    return f'Listened at {bitrate // 1000} kbit/s for {CAN_TRY_S} s; the bus is back at its own speed'


ACTIONS = {'usb_scan': lambda arg: usb_scan(), 'usb_copy': usb_copy, 'usb_eject': lambda arg: usb_eject(), 'can_try': can_try,
           'share': share, 'unshare': unshare}


def report(message, ok=True):
    data = {'ok': ok, 'message': message, 'time': int(time.time()), 'usb': {'mounted': mounted(), 'files': files() if mounted() else []},
            'shared': shared() if shutil.which('usbip') else []}
    tmp = STATUS.with_name(STATUS.name + '.tmp')
    tmp.write_text(json.dumps(data) + '\n', encoding='utf-8')
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATUS)


def main():
    try:
        request = json.loads(REQUEST.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        request = {}
    REQUEST.unlink(missing_ok=True)
    action = request.get('action')
    try:
        if action not in ACTIONS:
            raise ValueError('Unknown tuning request')
        report(ACTIONS[action](request.get('arg')))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        report(str(exc), ok=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
