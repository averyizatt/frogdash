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
            '--disable-session-crashed-bubble']
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


def supervise(args, port, token):
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
            if watch.frozen(time.monotonic(), backend_alive, rendered):
                print('Frogdash kiosk: render heartbeat stopped; restarting browser', flush=True)
                return 1
            time.sleep(2)
        return process.returncode
    except KeyboardInterrupt:
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous)
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
    raise SystemExit(supervise(command, args.port, token))


if __name__ == '__main__':
    main()
