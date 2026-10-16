#!/usr/bin/env python3
"""One command from the dash's Terminal tab, run as the screen user, so sudo works as it
does at the keyboard or over SSH.

Started as root by frogdash-terminal.socket, once per connection, with the connection on
stdin and stdout: reads one JSON line {"command": "..."} and writes one JSON line
{"exit": n, "output": "...", "user": "..."} back. Only members of the group
frogdash-terminal can connect; the setup gives the dash service that group only while
--terminal is in /etc/default/frogdash, and the dash only takes commands from its own
screen (loopback). The phone page never offers it.

Not interactive: a command gets no input and is stopped after 60 seconds, so editors and
`top` do not work; `sudo` works when the user's sudo needs no password (the Raspberry Pi
OS default), as at the keyboard.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

UNITS = Path(os.environ.get('FROGDASH_UNITS', '/etc/systemd/system'))
TIMEOUT_S = 60
LIMIT = 100_000
RUNUSER = os.environ.get('FROGDASH_RUNUSER', '/usr/sbin/runuser')


def screen_user():
    """The user the dash screen runs as: the name after frogdash-console@."""
    for link in sorted(UNITS.glob('*.wants/frogdash-console@*.service')):
        return link.name.split('@', 1)[1].rsplit('.', 1)[0]
    return None


def run(command, user, timeout=TIMEOUT_S):
    import pwd   # Unix only; the tests that need it run on Linux
    entry = pwd.getpwnam(user)
    env = {'HOME': entry.pw_dir, 'USER': user, 'LOGNAME': user, 'TERM': 'dumb', 'LANG': 'C.UTF-8',
           'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'}
    # A plain shell, not a login shell: the user's profile is not run, so a mistake in it
    # does not end up in every command's output.
    process = subprocess.Popen([RUNUSER, '-u', user, '--', '/bin/bash', '-c', command], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, cwd=entry.pw_dir,
                               start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
        code, note = process.returncode, b''
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)   # The whole command, not only runuser
        output, _ = process.communicate()
        code, note = 124, f'\n[stopped after {timeout} s]'.encode()
    text = (output + note).decode('utf-8', 'replace')
    if len(text) > LIMIT:
        text = '[earlier output trimmed]\n' + text[-LIMIT:]
    return code, text


def handle(line):
    try:
        command = json.loads(line).get('command')
        if not isinstance(command, str) or not command.strip() or len(command) > 2000:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        return {'exit': 2, 'output': 'Expected one command (up to 2000 characters)'}
    user = screen_user()
    if not user:
        return {'exit': 2, 'output': 'The dash screen service is not installed, so there is no user to run as'}
    try:
        code, text = run(command, user)
    except (KeyError, OSError) as error:
        return {'exit': 2, 'output': f'Could not run it as {user}: {error}'}
    return {'exit': code, 'output': text, 'user': user}


def main():
    line = sys.stdin.buffer.readline(8192)
    sys.stdout.write(json.dumps(handle(line)) + '\n')
    sys.stdout.flush()


if __name__ == '__main__':
    main()
