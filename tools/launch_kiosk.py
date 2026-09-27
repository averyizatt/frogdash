"""Launch the local kiosk as soon as HTTP is ready, without waiting for sensors."""
import argparse
import os
from pathlib import Path
import shutil
import time
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


def browser_args(binary, port=8080, wayland=False, profile=None):
    args = [binary, '--kiosk', '--no-first-run', '--no-default-browser-check',
            '--disable-session-crashed-bubble']
    if wayland:
        args.append('--ozone-platform=wayland')
    if profile:
        args.append(f'--user-data-dir={profile}')
    return args + [f'http://127.0.0.1:{port}/']


def boot_stamp():
    try:
        return f'boot+{float(Path("/proc/uptime").read_text().split()[0]):.2f}s'
    except (OSError, ValueError, IndexError):
        return 'uptime unavailable'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wayland', action='store_true')
    parser.add_argument('--dedicated-profile', action='store_true', help='Use ~/.config/frogdash-chromium; keep preferences on disk')
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
    # Preserve process supervision and argument boundaries, including spaces in profiles.
    os.execv(binary, browser_args(binary, args.port, args.wayland, profile))


if __name__ == '__main__':
    main()
