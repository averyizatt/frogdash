"""Launch the local kiosk as soon as HTTP is ready, without waiting for sensors."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from uuid import uuid4
import urllib.error
import urllib.request


def wait_ready(probe, timeout=30, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    while clock() < deadline:
        if probe():
            return
        sleep(min(.1, max(0, deadline - clock())))
    raise TimeoutError(f'Local Frogdash HTTP service did not become ready within {timeout:g} seconds')


def http_probe(port):
    # A proxy configured for general browsing must not intercept loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def probe():
        try:
            with opener.open(f'http://127.0.0.1:{port}/health', timeout=.5) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            return False
    return probe


def browser_args(binary, port=8080, wayland=False, profile=None, allow_audio=False):
    args = [binary, '--kiosk', '--no-first-run', '--no-default-browser-check',
            '--disable-session-crashed-bubble',
            # A local-only dashboard needs no sync, update or push-registration traffic.
            '--disable-background-networking', '--disable-component-update', '--disable-sync',
            '--disable-breakpad', '--disable-features=Translate,MediaRouter,OptimizationHints']
    if wayland:
        args.append('--ozone-platform=wayland')
    if profile:
        args.append(f'--user-data-dir={profile}')
        # This dedicated local dashboard profile has no website logins. Avoid
        # a desktop keyring prompt/timeout in an unattended console session.
        args.append('--password-store=basic')
    if allow_audio:
        args.append('--autoplay-policy=no-user-gesture-required')
    return args + [f'http://127.0.0.1:{port}/']


def boot_stamp():
    try:
        return f'boot+{float(Path("/proc/uptime").read_text().split()[0]):.2f}s'
    except (OSError, ValueError, IndexError):
        return 'uptime unavailable'


def heartbeat_probe(port, token):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def probe():
        try:
            with opener.open(f'http://127.0.0.1:{port}/ui/heartbeat/{token}', timeout=1) as response:
                return json.load(response).get('alive') is True
        except (OSError, ValueError, urllib.error.URLError):
            return False
    return probe


class RenderWatchdog:
    def __init__(self, now, grace=30):
        self.deadline = now + grace

    def frozen(self, now, backend_alive, rendered):
        # Backend is recovered separately by systemd; give the browser time to reconnect.
        if not backend_alive or rendered:
            self.deadline = now + 20
        return now > self.deadline


def find_tunerstudio(env=os.environ, home=None):
    """The TunerStudio start script: FROGDASH_TUNERSTUDIO, or the usual install folders."""
    override = env.get('FROGDASH_TUNERSTUDIO')
    home = home or Path.home()
    folders = [Path(override)] if override else [home / 'TunerStudioMS', Path('/opt/TunerStudioMS'), Path('/usr/local/TunerStudioMS')]
    for folder in folders:
        script = folder if folder.suffix == '.sh' else folder / 'TunerStudio.sh'
        if script.is_file():
            return script
    return None


def group_alive(pid):
    # The start script may hand over to Java and exit; the session it started lives on.
    try:
        os.killpg(pid, 0)
        return True
    except OSError:
        return False


def stop_group(process, alive=group_alive, sleep=time.sleep):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except OSError:
            return
        for _ in range(25):
            process.poll()  # Reap the start script so the group can disappear.
            if not alive(process.pid):
                return
            sleep(.2)


class Tuner:
    """Opens TunerStudio over the dash when the dash asks (hardware/frogdash/tune.py).

    This runs in the kiosk session as the normal screen user, so TunerStudio gets the
    display, keyboard and mouse without the dash service needing any extra rights.
    """
    READY = 'Ready. Opens over the dash; needs a keyboard and mouse'
    OPEN = 'TunerStudio is open. Exit it (File > Exit), or hold OFF on the wheel, to return to the dash'

    def __init__(self, port, find=find_tunerstudio, popen=subprocess.Popen, alive=group_alive, stop=stop_group,
                 clock=time.monotonic, env=os.environ, post=None):
        self.find, self.popen, self.alive, self.stop, self.clock, self.env = find, popen, alive, stop, clock, env
        self.post = post or self.http_post(port)
        self.process, self.started, self.note, self.failed = None, 0, '', False

    @staticmethod
    def http_post(port):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def post(report):
            request = urllib.request.Request(f'http://127.0.0.1:{port}/tune/kiosk', json.dumps(report).encode(),
                                             {'Content-Type': 'application/json'})
            with opener.open(request, timeout=1) as response:
                return json.load(response).get('action')
        return post

    def running(self):
        return self.process is not None and (self.process.poll() is None or self.alive(self.process.pid))

    def open(self, script):
        if self.running():
            return
        if not self.env.get('DISPLAY'):
            # Java draws through X11; Cage provides it only when Xwayland is installed.
            self.failed, self.note = True, ('The screen has no X display for TunerStudio (xwayland). Press Update now with internet: '
                                           'the dash installs it and restarts the screen')
            return
        try:
            self.process = self.popen(['/bin/bash', str(script)], cwd=str(script.parent), stdin=subprocess.DEVNULL, start_new_session=True,
                                      # Java windows stay blank under a compositor like Cage without this.
                                      env={**self.env, '_JAVA_AWT_WM_NONREPARENTING': '1'})
        except OSError as error:
            self.failed, self.note = True, f'Could not start TunerStudio: {error}'
            return
        self.started, self.failed, self.note = self.clock(), False, ''
        print('Frogdash kiosk: TunerStudio started', flush=True)

    def close(self):
        if self.running():
            self.stop(self.process)
        if self.process is not None:
            self.process, self.failed, self.note = None, False, 'TunerStudio closed'
            print('Frogdash kiosk: TunerStudio closed', flush=True)

    def step(self):
        """One 2 s turn: notice an exit, report to the dash, do what it asks."""
        if self.process is not None and not self.running():
            code = self.process.returncode
            quick = bool(code) and self.clock() - self.started < 20  # A clean exit is just the user closing it.
            self.process, self.failed = None, quick
            self.note = (f'TunerStudio closed right after starting (exit code {code}). Java (default-jre) may be missing: press Update now with internet '
                         'and look at System check > Updates') if quick else 'TunerStudio closed'
            print(f'Frogdash kiosk: TunerStudio exited ({code})', flush=True)
        script = self.find()
        state = 'running' if self.running() else 'failed' if self.failed else 'idle'
        message = self.OPEN if state == 'running' else self.note or self.READY
        try:
            action = self.post({'installed': script is not None, 'state': state, 'message': message})
        except (OSError, ValueError, urllib.error.URLError):
            return  # Dash service restarting; an open TunerStudio is left alone.
        if action == 'open' and script is not None:
            self.open(script)
        elif action == 'close':
            self.close()


def supervise(args, port, token, tuner=None):
    launched = time.monotonic()
    process = subprocess.Popen(args, start_new_session=True)
    watch = RenderWatchdog(launched)
    first_render = False
    backend, render = http_probe(port), heartbeat_probe(port, token)
    def stop(*_):
        raise KeyboardInterrupt()
    previous = signal.signal(signal.SIGTERM, stop)
    try:
        while process.poll() is None:
            backend_alive, rendered = backend(), render()
            if rendered and not first_render:
                first_render = True
                print(f'Frogdash kiosk: first render heartbeat observed ({boot_stamp()}; '
                      f'{time.monotonic() - launched:.2f}s after browser launch)', flush=True)
            if tuner:
                try:
                    tuner.step()
                except Exception as error:  # Never let the optional tuner take the dash screen down.
                    print(f'Frogdash kiosk: TunerStudio helper error: {error}', flush=True)
            # The dash is covered while TunerStudio is open, so it stops drawing: not a freeze.
            if watch.frozen(time.monotonic(), backend_alive, rendered or bool(tuner and tuner.running())):
                print('Frogdash kiosk: render heartbeat stopped; restarting browser', flush=True)
                return 1
            time.sleep(2)
        return process.returncode
    except KeyboardInterrupt:
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous)
        if tuner:
            tuner.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wayland', action='store_true')
    parser.add_argument('--dedicated-profile', action='store_true', help='Use ~/.config/frogdash-chromium; keep preferences on disk')
    parser.add_argument('--allow-audio', action='store_true', help='Allow enabled warning chimes without a startup tap in this kiosk')
    parser.add_argument('--browser', help='Chromium executable; otherwise discover chromium/chromium-browser')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1–65535')
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        parser.error('Run the kiosk as a normal user, not root')
    binary = shutil.which(args.browser) if args.browser else shutil.which('chromium') or shutil.which('chromium-browser')
    if not binary:
        parser.error('Chromium not found; install it or specify --browser')
    if args.wayland and not os.environ.get('WAYLAND_DISPLAY'):
        parser.error('--wayland requires a running Wayland compositor (such as Cage)')
    profile = Path.home() / '.config' / 'frogdash-chromium' if args.dedicated_profile else None
    if profile:
        profile.mkdir(parents=True, exist_ok=True)
    print(f'Frogdash kiosk: waiting for local HTTP ({boot_stamp()})', flush=True)
    try:
        wait_ready(http_probe(args.port))
    except TimeoutError as exc:
        parser.exit(1, f'{exc}; systemd will retry. Check journalctl -u frogdash.\n')
    print(f'Frogdash kiosk: HTTP ready; launching Chromium ({boot_stamp()})', flush=True)
    token = uuid4().hex
    command = browser_args(binary, args.port, args.wayland, profile, args.allow_audio)
    command[-1] += '?kiosk=' + token
    raise SystemExit(supervise(command, args.port, token, Tuner(args.port)))


if __name__ == '__main__':
    main()
