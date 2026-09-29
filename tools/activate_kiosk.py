"""Activate only this kiosk's registered logind session, after PAM has finished.

Used as the privileged ExecStartPost helper of the console service. No hardware
configuration is changed. A bounded wait avoids both early chvt and Type=exec's
startup-notification hang observed with the Pi's PAM session handler.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import time


def registered_session(pid, user, tty):
    try:
        with Path(f'/proc/{pid}/environ').open('rb') as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            return None
        env = dict(item.split(b'=', 1) for item in data.split(b'\0') if b'=' in item)
        session = env.get(b'XDG_SESSION_ID', b'').decode('ascii')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', session):
            return None
        result = subprocess.run(['/usr/bin/loginctl', 'show-session', session, '--no-pager',
                                 '--property=Name', '--property=Service', '--property=TTY',
                                 '--property=Leader', '--property=State'],
                                capture_output=True, text=True, timeout=1, check=True)
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if (fields.get('Name') == user and fields.get('TTY') == tty
                and fields.get('Service') == 'frogdash-kiosk'
                and fields.get('Leader') == str(pid)
                and fields.get('State') in ('online', 'active')):
            return session
    except (OSError, UnicodeError, subprocess.SubprocessError):
        pass
    return None


def activate(session):
    subprocess.run(['/usr/bin/loginctl', 'activate', session, '--no-ask-password'],
                   check=True, timeout=2)


def wait_for_session(probe, select, timeout=8, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while clock() < deadline:
        session = probe()
        if session:
            select(session)
            return session
        sleep(min(.1, max(0, deadline - clock())))
    raise TimeoutError('No matching registered kiosk session within 8 seconds; inspect PAM/logind logs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--tty', default='tty7')
    args = parser.parse_args()
    if args.pid <= 1 or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]*[$]?', args.user) or args.user == 'root':
        parser.error('Expected kiosk main PID and a normal username')
    if not re.fullmatch(r'tty[1-9][0-9]?', args.tty):
        parser.error('Expected virtual terminal name, for example tty7')
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        parser.error('Run only as the privileged console service post-start helper')
    try:
        session = wait_for_session(lambda: registered_session(args.pid, args.user, args.tty), activate)
    except (OSError, TimeoutError, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Frogdash kiosk: session activation failed: {exc}\n')
    print(f'Frogdash kiosk: activated logind session {session} on {args.tty}', flush=True)


if __name__ == '__main__':
    main()
