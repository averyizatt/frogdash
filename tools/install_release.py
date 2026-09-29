"""Stage a versioned Linux release, switch atomically, and roll back failed starts.

Defaults to a read-only plan. Run from a reviewed checkout on the Pi with --apply.
Does not configure hardware, networking, kiosk login, or vehicle power services.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FILES = ('hardware', 'tools/launch_kiosk.py', 'tools/boot_report.py', 'tools/install_release.py', 'VERSION', 'requirements.txt', 'requirements.lock')


def manifest(source):
    result = {}
    for name in FILES:
        path = source / name
        paths = sorted(path.rglob('*')) if path.is_dir() else [path]
        for item in paths:
            if '__pycache__' in item.parts or item.suffix == '.pyc':
                continue
            if item.is_symlink():
                raise ValueError(f'Release source contains a symlink: {item}')
            if item.is_file():
                result[item.relative_to(source).as_posix()] = sha256(item.read_bytes()).hexdigest()
        if not path.exists():
            raise ValueError(f'Missing release source: {name}')
    return result


def release_name(source, contents):
    version = (source / 'VERSION').read_text().strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('VERSION must be major.minor.patch')
    digest = sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest()[:12]
    return f'{version}-{digest}'


def replace_link(link, target):
    if link.exists() and not link.is_symlink():
        raise ValueError(f'{link} is a regular directory/file. Follow the documented legacy migration first.')
    temporary = link.with_name(link.name + '.next')
    if temporary.exists() or temporary.is_symlink():
        raise ValueError(f'Unexpected staging link {temporary}; inspect before retrying')
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, link)


def validate_release(path, releases):
    path = path.resolve(strict=True)
    if path.parent != releases.resolve() or not (path / 'release.json').is_file():
        raise ValueError('Target is not a managed release')
    data = json.loads((path / 'release.json').read_text())
    if data.get('complete') is not True or data.get('schema') != 1 or data.get('files') != manifest(path):
        raise ValueError('Release is incomplete or its source checksum changed')
    if not (path / '.venv/bin/python').is_file():
        raise ValueError('Release virtual environment is missing')
    return path


def local_json(route):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:8080' + route, timeout=1) as response:
        return json.load(response)


def require_stationary():
    try:
        data = local_json('/operations/status')
    except OSError:
        # An older running version cannot attest stationary state. Stop it explicitly.
        if subprocess.run(['systemctl', 'is-active', '--quiet', 'frogdash.service']).returncode == 0:
            raise ValueError('Running service cannot confirm stationary state. Park, then stop frogdash.service before updating.')
        return
    if data.get('parked') is not True or data.get('restore_pending'):
        raise ValueError('Park with live stationary telemetry and finish any pending restore before updating')


def ready(expected):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        try:
            if local_json('/operations/status').get('version') == expected:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    return False


def activate(target, current, previous, unit, run=subprocess.run, probe=ready):
    old = current.resolve() if current.is_symlink() else None
    old_unit = unit.read_bytes() if unit.exists() else None
    unit.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Stop first: old code cannot write data during the switch.
        run(['systemctl', 'stop', 'frogdash.service'], check=True)
        replace_link(current, target)
        unit.write_bytes((target / 'hardware/systemd/frogdash.service').read_bytes())
        run(['systemctl', 'daemon-reload'], check=True)
        run(['systemctl', 'start', 'frogdash.service'], check=True)
        if not probe((target / 'VERSION').read_text().strip()):
            raise RuntimeError('New service did not become healthy within 35 seconds')
    except Exception:
        run(['systemctl', 'stop', 'frogdash.service'], check=False)
        if old:
            replace_link(current, old)
        elif current.is_symlink():
            current.unlink()
        if old_unit is None:
            unit.unlink(missing_ok=True)
        else:
            unit.write_bytes(old_unit)
        run(['systemctl', 'daemon-reload'], check=False)
        if old:
            run(['systemctl', 'start', 'frogdash.service'], check=False)
        raise
    if old and old != target:
        replace_link(previous, old)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'rollback'])
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    source = args.source.resolve()
    releases, current, previous = Path('/opt/frogdash-releases'), Path('/opt/frogdash'), Path('/opt/frogdash-previous')
    unit = Path('/etc/systemd/system/frogdash.service')
    try:
        if current.exists() and not current.is_symlink():
            raise ValueError('Legacy /opt/frogdash directory found. Follow docs/ownership-and-service.md migration; no files were changed.')
        if previous.exists() and not previous.is_symlink():
            raise ValueError('Unexpected regular file/directory at /opt/frogdash-previous')
        if args.action == 'install':
            contents = manifest(source)
            target = releases / release_name(source, contents)
        else:
            if not previous.is_symlink():
                raise ValueError('No previous managed release')
            target = validate_release(previous, releases)
        print(json.dumps(dict(action=args.action, source=str(source), target=str(target), current=str(current),
                              unit=str(unit), data='/var/lib/frogdash (preserved)', apply=args.apply), indent=2))
        if not args.apply:
            return
        if sys.platform != 'linux' or os.geteuid() != 0 or sys.version_info < (3, 11):
            raise ValueError('Apply requires Linux, root, Python 3.11+ and systemd')
        require_stationary()
        if current.is_symlink():
            validate_release(current, releases)
        if args.action == 'install' and not target.exists():
            target.mkdir(parents=True)
            # No active paths change until every copy and dependency install succeeds.
            for name in contents:
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, dest)
            subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages', str(target / '.venv')], check=True)
            subprocess.run([str(target / '.venv/bin/python'), '-m', 'pip', 'install', '-r', str(target / 'requirements.lock')], check=True)
            if manifest(target) != contents:
                raise ValueError('Source changed while staging; inactive release left for inspection')
            (target / 'release.json').write_text(json.dumps(dict(schema=1, complete=True, files=contents), indent=2))
        validate_release(target, releases)
        activate(target, current, previous, unit)
        subprocess.run(['systemctl', 'enable', 'frogdash.service'], check=True)
        print('Release active. Reload/restart the kiosk to load its matching UI. Previous release remains available for rollback.')
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
