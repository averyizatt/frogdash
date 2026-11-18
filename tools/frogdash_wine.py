#!/usr/bin/env python3
"""Windows tuning software on the dash screen: Wine (x86-64) through Box64. Experimental.

Run by the kiosk launcher (tools/launch_kiosk.py) as the screen's own user, in its X
display, the way TunerStudio is. Setup (tools/frogdash_setup.sh, "Windows tuning") installs
Box64, a pinned Wine build in /opt/frogdash-wine/wine and, on a Pi 5, the 4K-page kernel
Box64 needs. Installers come from a USB stick through the root helper
(tools/frogdash_tuning.py), which copies them to /opt/frogdash-wine/installers.

USB: Wine cannot load a Windows USB driver (.sys). A tuning cable or ECU that Linux sees as
a serial port (FTDI, Silicon Labs, CH340, Prolific, or a USB serial ACM device) works: each
is mapped to a COM port (COM1, COM2...) before the tuner starts, in /dev/serial/by-id
order. One that needs its maker's own driver does not: share it with a Windows PC over the
network instead (frogdash_tuning.py share; the Tuning page explains).

  frogdash_wine.py status            JSON: wine there, programs, installers, COM ports
  frogdash_wine.py argv install FILE the command that runs an installer
  frogdash_wine.py argv run LINK     the command that starts an installed program
"""
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(os.environ.get('FROGDASH_WINE_ROOT', '/opt/frogdash-wine'))
WINE = ROOT / 'wine' / 'bin' / 'wine'
INSTALLERS = ROOT / 'installers'
PREFIX = Path(os.environ.get('WINEPREFIX') or Path.home() / '.frogdash-wine')
SERIAL = Path(os.environ.get('FROGDASH_SERIAL_DIR', '/dev/serial/by-id'))
DEV = Path(os.environ.get('FROGDASH_DEV', '/dev'))
INSTALLER_TYPES = ('.exe', '.msi')
START_MENUS = ('drive_c/ProgramData/Microsoft/Windows/Start Menu/Programs',
               'drive_c/users/*/AppData/Roaming/Microsoft/Windows/Start Menu/Programs',
               'drive_c/users/*/Start Menu/Programs')
SKIP = ('uninstall', 'readme', 'help', 'manual', 'website', 'license', 'release notes')


def box64():
    return shutil.which('box64')


def available():
    """(ready, why not)."""
    if not box64():
        return False, 'Box64 is not installed: choose Windows tuning in the setup wizard and run Update with internet'
    if not WINE.is_file():
        return False, 'Wine is not installed: run Update with internet (it downloads about 75 MB)'
    return True, ''


def serial_ports():
    """USB serial devices in a stable order: /dev/serial/by-id first, then any ttyUSB/ttyACM."""
    found = []
    if SERIAL.is_dir():
        found += [p.resolve() for p in sorted(SERIAL.iterdir())]
    for pattern in ('ttyUSB*', 'ttyACM*'):
        found += sorted(DEV.glob(pattern))
    seen, ports = set(), []
    for device in found:
        if device.name not in seen:
            seen.add(device.name)
            ports.append(device)
    return ports


def map_ports(prefix=PREFIX):
    """COM1, COM2... in the Wine prefix point at the USB serial devices. [(COMn, /dev/...)]"""
    dos = prefix / 'dosdevices'
    dos.mkdir(parents=True, exist_ok=True)
    for old in dos.glob('com*'):
        if old.is_symlink():
            old.unlink()
    mapped = []
    for n, device in enumerate(serial_ports(), 1):
        (dos / f'com{n}').symlink_to(device)
        mapped.append((f'COM{n}', str(device)))
    return mapped


def programs(prefix=PREFIX):
    """Installed programs: the Start Menu shortcuts in the Wine prefix, without uninstallers."""
    out = []
    for pattern in START_MENUS:
        for link in sorted(prefix.glob(pattern + '/**/*.lnk')):
            name = link.stem
            if not any(word in name.lower() for word in SKIP):
                out.append({'name': name, 'path': str(link)})
    return out


def installers():
    if not INSTALLERS.is_dir():
        return []
    return [{'name': p.name, 'path': str(p), 'mb': round(p.stat().st_size / 1e6, 1)}
            for p in sorted(INSTALLERS.iterdir()) if p.suffix.lower() in INSTALLER_TYPES and p.is_file()]


def environment(base=os.environ):
    return {**base, 'WINEPREFIX': str(PREFIX), 'WINEDEBUG': '-all', 'BOX64_LOG': '0', 'BOX64_NOBANNER': '1',
            'WINEDLLOVERRIDES': 'mscoree,mshtml='}       # No Mono/Gecko download prompts on the dash


def argv(kind, target):
    """The command for an installer or an installed program (the caller maps the ports first)."""
    path = Path(target)
    if kind == 'install':
        if path.parent != INSTALLERS or path.suffix.lower() not in INSTALLER_TYPES or not path.is_file():
            raise ValueError('Not an installer from the USB stick')
        if path.suffix.lower() == '.msi':
            return [box64(), str(WINE), 'msiexec', '/i', str(path)]
        return [box64(), str(WINE), str(path)]
    if kind == 'run':
        if path.suffix.lower() != '.lnk' or PREFIX not in path.parents or not path.is_file():
            raise ValueError('Not an installed program')
        return [box64(), str(WINE), 'start', '/wait', '/unix', str(path)]
    raise ValueError('Unknown Windows tuning action')


def status():
    ready, why = available()
    return {'ready': ready, 'why': why, 'programs': programs() if ready else [], 'installers': installers(),
            'ports': [{'com': f'COM{n}', 'device': str(d)} for n, d in enumerate(serial_ports(), 1)]}


def main(args):
    if args[:1] == ['status']:
        print(json.dumps(status()))
        return 0
    if len(args) == 3 and args[0] == 'argv':
        print(json.dumps(argv(args[1], args[2])))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
