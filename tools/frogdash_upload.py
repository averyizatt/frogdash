#!/usr/bin/env python3
"""After an update: the dash's diagnostics and its newest drive, to the owner's private
GitHub repository (run as root by tools/frogdash_update.sh while the Pi is online).

Set up once on the phone page (Logs, faults & updates > Uploads): a GitHub token that can
write only to that repository, saved in log-upload.json in the dash's state folder.

What goes up, every time, whatever the connection:
  - pi/<date>/<time>-diagnostics.json: the dash's self check, every helper's status, the
    update and screen reports, the last failed start;
  - pi/<date>/<time>-boot.txt: tools/boot_report.py (boot timing, kiosk start, display);
  - pi/<date>/<time>-journal.txt: the dash's own service logs since the Pi started;
  - the newest drive's recordings, gzip-compressed, as files of a GitHub release named
    after the drive, so the repository's history does not grow with them.
The repository must be private: recordings contain GPS positions.

Prints one line for the update's status message. Never prints the token.
"""
import base64
import calendar
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

STATE = Path(os.environ.get('FROGDASH_STATE') or os.path.realpath('/var/lib/frogdash'))
REPO_DIR = Path(os.environ.get('FROGDASH_REPO', '/opt/frogdash'))
CONFIG, STATUS = STATE / 'log-upload.json', STATE / 'upload-status.json'
LOGS = STATE / 'logs'
UNITS = Path(os.environ.get('FROGDASH_UNITS', '/etc/systemd/system'))
API, UPLOADS = 'https://api.github.com', 'https://uploads.github.com'
NAME = re.compile(r'frogdash-(?:live|replay)-(\d{8}T\d{6}Z)-[0-9a-f]{12}\.mlg')
DRIVE_GAP_S = 10 * 60          # Recordings further apart than this belong to different drives
MAX_DRIVE_BYTES = 400 << 20    # Compressed; GitHub takes up to 2 GB a file
STATUS_FILES = ('update-status.json', 'setup-status.json', 'gps-status.json', 'wifi-status.json', 'screen-status.json')


def port():
    try:
        found = re.findall(r'--port[ =](\d+)', Path('/etc/default/frogdash').read_text())
        return int(found[-1]) if found else 8080
    except OSError:
        return 8080


def local(path, method='GET', timeout=10):
    """The dash's own HTTP service on this Pi."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f'http://127.0.0.1:{port()}{path}', method=method, data=b'{}' if method == 'POST' else None,
                                     headers={'Content-Type': 'application/json'})
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


class GitHub:
    def __init__(self, repo, token, opener=None):
        self.repo, self.token = repo, token
        self.opener = opener or urllib.request.build_opener()

    def call(self, method, url, body=None, data=None, content_type='application/json', timeout=60):
        headers = {'Authorization': f'Bearer {self.token}', 'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'fox-body-dash'}
        if body is not None:
            data = json.dumps(body).encode()
        if data is not None:
            headers['Content-Type'] = content_type
            if hasattr(data, 'read'):
                headers['Content-Length'] = str(os.fstat(data.fileno()).st_size)
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                text = response.read()
                return response.status, (json.loads(text) if text else None)
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read() or b'{}')
            except ValueError:
                detail = {}
            return error.code, detail

    def put_file(self, path, content, message):
        status, body = self.call('PUT', f'{API}/repos/{self.repo}/contents/{path}',
                                 {'message': message, 'content': base64.b64encode(content).decode()})
        if status not in (200, 201):
            raise RuntimeError(f'GitHub refused {path} ({status}{": " + body.get("message", "") if isinstance(body, dict) else ""})')

    def release(self, tag, title, notes):
        status, body = self.call('GET', f'{API}/repos/{self.repo}/releases/tags/{tag}')
        if status == 200:
            return body
        status, body = self.call('POST', f'{API}/repos/{self.repo}/releases',
                                 {'tag_name': tag, 'name': title, 'body': notes, 'draft': False, 'prerelease': False})
        if status != 201:
            raise RuntimeError(f'GitHub refused the release ({status}{": " + body.get("message", "") if isinstance(body, dict) else ""})')
        return body

    def upload_asset(self, release, name, path):
        with open(path, 'rb') as stream:
            status, body = self.call('POST', f'{UPLOADS}/repos/{self.repo}/releases/{release["id"]}/assets?name={name}',
                                     data=stream, content_type='application/gzip', timeout=900)
        if status == 422 and isinstance(body, dict) and 'already_exists' in json.dumps(body):
            return   # Sent by an earlier run that stopped before writing it down.
        if status != 201:
            raise RuntimeError(f'GitHub refused {name} ({status})')


def started(name):
    found = NAME.fullmatch(name)
    return calendar.timegm(time.strptime(found.group(1), '%Y%m%dT%H%M%SZ')) if found else None


def newest_drive(files, active=(), gap=DRIVE_GAP_S):
    """The recordings of the most recent drive: (name, start, end, bytes), oldest first.
    `files` is (name, end time, bytes); a file still being written is left out."""
    done = sorted(((name, started(name), end, size) for name, end, size in files
                   if name not in active and started(name) is not None), key=lambda f: f[1])
    drive = []
    for item in reversed(done):
        if drive and drive[0][1] - item[2] > gap:
            break
        drive.insert(0, item)
    return drive


def text_of(*args, timeout=30):
    try:
        result = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, env={**os.environ, 'LC_ALL': 'C'})
        return result.stdout + (result.stderr if result.returncode else '')
    except (OSError, subprocess.TimeoutExpired) as error:
        return f'{args[0]}: {error}\n'


def kiosk_user():
    for link in UNITS.glob('*.wants/frogdash-console@*.service'):
        return link.name.split('@', 1)[1].rsplit('.', 1)[0]
    return None


def diagnostics(now):
    def read_json(name):
        try:
            return json.loads((STATE / name).read_text())
        except (OSError, ValueError):
            return None
    try:
        failure = (STATE / 'update-failure.log').read_text(errors='replace')[-20000:]
    except OSError:
        failure = None
    return {'format': 'pi-diagnostics', 'version': 1, 'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)),
            'version_installed': text_of('git', '-C', str(REPO_DIR), 'log', '-1', '--format=%h %s').strip(),
            'selftest': local('/selftest'), 'health': local('/health'), 'logs': local('/logs'),
            'helpers': {name: read_json(name) for name in STATUS_FILES}, 'update_failure_log': failure,
            'uptime_s': float((Path('/proc/uptime').read_text().split() or ['0'])[0]) if Path('/proc/uptime').exists() else None,
            'throttled': text_of('vcgencmd', 'get_throttled').strip(), 'disk': text_of('df', '-h', '/', str(STATE)).strip()}


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_status(body):
    tmp = STATUS.with_suffix('.tmp')
    tmp.write_text(json.dumps(body))
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATUS)


def run(now=None, github=None, wait=time.sleep):
    now = now or time.time()
    config = load(CONFIG, {})
    repo, token = config.get('repo', ''), config.get('token', '')
    if not repo or not token:
        return 'Uploads not set up (phone page, Uploads)'
    github = github or GitHub(repo, token)
    sent = load(STATUS, {}).get('sent', [])
    stamp = time.strftime('%Y-%m-%d/%H%M%S', time.gmtime(now))
    message = f'Pi report {time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now))}'

    # The reports first: small, and the most useful when something went wrong.
    github.put_file(f'pi/{stamp}-diagnostics.json', json.dumps(diagnostics(now), indent=1, default=str).encode(), message)
    user = kiosk_user()
    boot = text_of(sys.executable, str(REPO_DIR / 'tools/boot_report.py'), *(['--user', user] if user else []), timeout=90)
    github.put_file(f'pi/{stamp}-boot.txt', boot.encode(errors='replace'), message)
    journal = text_of('journalctl', '-b', '--no-pager', '-o', 'short-monotonic', '-n', '3000',
                      '-u', 'frogdash*', timeout=60)
    github.put_file(f'pi/{stamp}-journal.txt', journal.encode(errors='replace')[-3_000_000:], message)

    # Then the newest drive. The file being recorded is finished first, so a drive that
    # has just ended is complete.
    local('/logs/finish', 'POST')
    wait(3)
    listing = local('/logs') or {}
    active = {f['name'] for f in listing.get('files', []) if f.get('active')}
    files = [(p.name, p.stat().st_mtime, p.stat().st_size) for p in LOGS.glob('frogdash-*.mlg')] if LOGS.is_dir() else []
    drive = [f for f in newest_drive(files, active) if f[0] not in sent]
    uploaded, skipped = [], 0
    if drive:
        first = drive[0][1]
        tag = 'drive-' + time.strftime('%Y%m%d-%H%M', time.gmtime(first))
        release = github.release(tag, 'Drive ' + time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(first)),
                                 f'Recordings from the dash, uploaded {time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now))}. '
                                 'Each file is a gzip-compressed MLG: gunzip, then open it in MegaLogViewer.')
        total = 0
        with tempfile.TemporaryDirectory() as work:
            for name, _, _, size in drive:
                packed = Path(work) / (name + '.gz')
                with open(LOGS / name, 'rb') as source, gzip.open(packed, 'wb', compresslevel=6) as target:
                    shutil.copyfileobj(source, target, 1 << 20)
                total += packed.stat().st_size
                if total > MAX_DRIVE_BYTES:
                    skipped += 1
                    continue
                github.upload_asset(release, packed.name, packed)
                uploaded.append(name)
                packed.unlink()
    sent = (sent + uploaded)[-500:]
    result = (f'Uploaded the diagnostics and {len(uploaded)} recording{"" if len(uploaded) == 1 else "s"} of the newest drive'
              if uploaded else 'Uploaded the diagnostics (no new drive to send)')
    if skipped:
        result += f'; {skipped} more too large for one upload'
    save_status({'time': int(now), 'state': 'done', 'message': result, 'repo': repo, 'sent': sent})
    return result


def main():
    try:
        said = run()
    except Exception as error:   # One line for the update message; the update itself carries on.
        said = f'Upload failed: {str(error)[:160]}'
        status = load(STATUS, {})
        save_status({**status, 'time': int(time.time()), 'state': 'failed', 'message': said})
    print(said)


if __name__ == '__main__':
    main()
