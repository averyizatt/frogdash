#!/usr/bin/env python3
"""One command from the dash's Terminal tab, run as the screen user, so sudo works as it
does at the keyboard or over SSH.

Started as root by frogdash-terminal.socket, once per connection, with the connection on
stdin and stdout. The first line says what is wanted:
  {"mode": "session"}   an interactive shell in a terminal device (pty): everything sent
                        afterwards is typed into it, everything it prints comes back. So a
                        password prompt (sudo, nmcli --ask) waits for the answer. The shell
                        ends when the connection closes, or after 30 minutes untouched.
  {"command": "..."}    one command, answered with one JSON line {"exit", "output", "user"}. Only members of the group
frogdash-terminal can connect; the setup gives the dash service that group only while
--terminal is in /etc/default/frogdash, and the dash only takes commands from its own
screen (loopback). The phone page never offers it.

A one-off command gets no input and is stopped after 60 seconds. In a session the shell
is a plain terminal (TERM=dumb): prompts and questions work, full-screen programs (nano,
top) do not draw properly.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

UNITS = Path(os.environ.get('FROGDASH_UNITS', '/etc/systemd/system'))
TIMEOUT_S = 60
IDLE_S = 30 * 60
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
    env = environment(entry, user)
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


def environment(entry, user):
    return {'HOME': entry.pw_dir, 'USER': user, 'LOGNAME': user, 'TERM': 'dumb', 'LANG': 'C.UTF-8',
            'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'}


def session(user, inbound=0, outbound=1, idle=IDLE_S):
    """An interactive shell as `user` in a pty, joined to the connection until either ends."""
    import pty
    import pwd
    import select
    import time
    entry = pwd.getpwnam(user)
    pid, master = pty.fork()
    if pid == 0:   # The child: a session leader with the pty as its terminal.
        try:
            os.chdir(entry.pw_dir)
            os.execve(RUNUSER, [RUNUSER, '-u', user, '--', '/bin/bash', '-i'], environment(entry, user))
        finally:
            os._exit(127)
    last = time.monotonic()
    try:
        while True:
            ready, _, _ = select.select([inbound, master], [], [], 5)
            if not ready and time.monotonic() - last > idle:
                os.write(outbound, b'\r\n[closed after 30 minutes untouched]\r\n')
                break
            if inbound in ready:
                data = os.read(inbound, 4096)
                if not data:
                    break          # The dash closed the page or the session.
                os.write(master, data)
                last = time.monotonic()
            if master in ready:
                try:
                    data = os.read(master, 4096)
                except OSError:
                    data = b''      # The shell has exited.
                if not data:
                    os.write(outbound, b'\r\n[the shell has ended]\r\n')
                    break
                os.write(outbound, data)
    finally:
        for sig in (signal.SIGHUP, signal.SIGKILL):
            try:
                os.killpg(pid, sig)
            except OSError:
                pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
        os.close(master)


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
    try:
        wanted = json.loads(line)
    except ValueError:
        wanted = {}
    if isinstance(wanted, dict) and wanted.get('mode') == 'session':
        user = screen_user()
        if not user:
            os.write(1, b'The dash screen service is not installed, so there is no user to run as.\r\n')
            return
        session(user)
        return
    sys.stdout.write(json.dumps(handle(line)) + '\n')
    sys.stdout.flush()


if __name__ == '__main__':
    main()
