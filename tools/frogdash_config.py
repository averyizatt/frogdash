#!/usr/bin/env python3
"""Apply the setup wizard's choices: write the system profile, then run the Pi setup.

Run as root by frogdash-config.service when the dash writes config-request.json into its
state directory (the setup wizard's Apply, or Dash management > Setup). The request is the
whole profile the wizard shows; it is checked with sysconfig.validate before anything is
written. The profile it replaces is kept as /etc/frogdash/system.json.bak, so a choice that
turns out wrong can be put back. Then tools/frogdash_setup.sh installs or skips each part
to match, writing its steps to setup-status.json as after an update; this helper's own
progress goes to config-status.json.

A request may also hold `custom`, the custom ECU editor's profile: it is checked as the dash
would load it and saved as /etc/frogdash/ecu/custom.json (the old one kept as custom.json.bak).
The dash reads the system profile and the ECU profile when it starts, so it is restarted
once setup is done.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(os.environ.get('FROGDASH_REPO', Path(__file__).resolve().parents[1]))
STATE = Path(os.path.realpath(os.environ.get('FROGDASH_STATE', '/var/lib/frogdash')))
REQUEST, STATUS = STATE / 'config-request.json', STATE / 'config-status.json'


def load_profiles():
    """hardware/frogdash/sysconfig.py (stdlib only), loaded by path: Python has its own
    `sysconfig` module, often already imported."""
    spec = importlib.util.spec_from_file_location('frogdash_sysconfig', REPO / 'hardware' / 'frogdash' / 'sysconfig.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profiles = load_profiles()


def load_ecu():
    """hardware/frogdash/ecu (stdlib only), by path, to check a custom profile."""
    spec = importlib.util.spec_from_file_location('frogdash_ecu', REPO / 'hardware' / 'frogdash' / 'ecu' / '__init__.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save_custom(data, etc=None):
    """The custom ECU profile, checked, in /etc/frogdash/ecu/custom.json."""
    ecu = load_ecu()
    try:
        ecu.custom(data)
    except ecu.ProfileError as exc:
        raise profiles.ProfileError(f'Custom ECU profile: {exc}') from None
    folder = profiles.path(etc).parent / 'ecu'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'custom.json'
    if target.exists():
        shutil.copy2(target, target.with_name('custom.json.bak'))
    tmp = target.with_name('custom.json.tmp')
    tmp.write_text(json.dumps(data, indent=1) + '\n', encoding='utf-8')
    os.chmod(tmp, 0o644)
    os.replace(tmp, target)

# A change to these needs the Pi restarted: the CAN board's overlay and the screen's boot
# settings are read at boot.
NEEDS_REBOOT = ('can_hat', 'screen')


def report(state, message, **extra):
    data = {'state': state, 'message': message, 'time': int(time.time()), **extra}
    tmp = STATUS.with_name(STATUS.name + '.tmp')
    tmp.write_text(json.dumps(data) + '\n', encoding='utf-8')
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATUS)


def update_running():
    try:
        return subprocess.run(['systemctl', 'is-active', '--quiet', 'frogdash-update.service'], timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def apply(request, etc=None, run_setup=True):
    """The request written as this Pi's profile. Returns (profile, what needs a reboot)."""
    if not isinstance(request, dict) or not isinstance(request.get('profile'), dict):
        raise profiles.ProfileError('The request should hold a profile')
    wanted = profiles.complete({**request['profile'], 'configured': True})
    before = profiles.load(etc)
    if request.get('custom') is not None:
        save_custom(request['custom'], etc)
    target = profiles.path(etc)
    if target.exists():
        shutil.copy2(target, target.with_name('system.json.bak'))
    profiles.write(wanted, etc)
    reboot = [part for part in NEEDS_REBOOT if before.get(part) != wanted.get(part)]
    if run_setup:
        for _ in range(360):            # An update in progress runs setup itself: wait for it
            if not update_running():
                break
            time.sleep(5)
        subprocess.run(['/bin/sh', str(REPO / 'tools' / 'frogdash_setup.sh')], timeout=3600,
                       env={**os.environ, 'FROGDASH_REPO': str(REPO), 'FROGDASH_STATE': str(STATE)},
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # The dash reads the profiles as it starts: the ECU, car signals and features chosen.
        subprocess.run(['systemctl', 'try-restart', 'frogdash.service'], timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wanted, reboot


def main():
    try:
        request = json.loads(REQUEST.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        REQUEST.unlink(missing_ok=True)
        report('failed', f'The request could not be read: {exc}')
        return 1
    REQUEST.unlink(missing_ok=True)
    report('applying', 'Saving the choices and setting up the Pi to match')
    try:
        profile, reboot = apply(request)
    except profiles.ProfileError as exc:
        report('failed', f'Nothing was changed: {exc}')
        return 1
    except (OSError, subprocess.SubprocessError) as exc:
        report('failed', f'The choices were saved, but setup did not finish: {exc}')
        return 1
    note = ' Restart the Pi to finish (' + ' and '.join('CAN board' if p == 'can_hat' else p for p in reboot) + ').' if reboot else ''
    report('done', f'Set up as {profile["preset"]} with your choices.{note}', reboot=bool(reboot))
    return 0


if __name__ == '__main__':
    sys.exit(main())
