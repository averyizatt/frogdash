#!/usr/bin/env python3
"""After an update: the dash's diagnostics and its newest drive, to the owner's GitHub
repository (run as root by tools/frogdash_update.sh while the Pi is online).

By the owner's choice this is the public frogdash repository itself, on its own branch
(pi-logs), so nothing lands on main: no test runs, no mixing with the code. Recordings
contain GPS positions; the owner is fine with them being public. Wi-Fi passwords and
network names, the hotspot password and the phone page's code are blanked out of every
text that goes up (secrets()).

Connected once on the dash (Software & power > Reports to GitHub > Connect GitHub: a code
typed on the phone, hardware/frogdash/github_link.py), or with a token on the phone page;
either way saved in log-upload.json in the dash's state folder. docs/log-uploads.md.

What goes up, every time, whatever the connection:
  - pi/<date>/<time>-events.txt: what went wrong on the dash, and when, since the last
    report (hardware/frogdash/eventlog.py): the GPS losing its fix or its receiver, a
    position without a speed, the CAN bus and each module, ignition, voltage, heat;
  - pi/<date>/<time>-diagnostics.json: the dash's self check and live state, every
    helper's status, the update and screen reports, the last failed start, and raw
    evidence: what gpsd hears (gpspipe), its ports and USB devices, the CAN link counters
    and two seconds of CAN traffic, the module firmware;
  - pi/<date>/<time>-boot.txt: tools/boot_report.py (boot timing, kiosk start, display);
  - pi/<date>/<time>-journal.txt: since the Pi started, the dash's, GPS, Wi-Fi and power
    services, warnings from everything, and the end of the start before (how it shut
    down; the setup keeps the journal across restarts);
  - the newest drive's recordings, gzip-compressed, as files of a GitHub release named
    after the drive, so the repository's history does not grow with them.

The reports are made after every update even with uploads not set up, and kept on the Pi
(reports/, the newest 10) until they can go up, so the evidence from before the token was
added is not lost.

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
REPORTS, EVENTS = STATE / 'reports', STATE / 'events'
KEEP_REPORTS = 10
FIRST_EVENTS_S = 14 * 86400    # The first report reaches back this far
MAX_EVENT_BYTES = 2 << 20
UNITS = Path(os.environ.get('FROGDASH_UNITS', '/etc/systemd/system'))
API, UPLOADS = 'https://api.github.com', 'https://uploads.github.com'
NAME = re.compile(r'frogdash-(?:live|replay)-(\d{8}T\d{6}Z)-[0-9a-f]{12}\.mlg')
BRANCH = 'pi-logs'
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
    def __init__(self, repo, token, opener=None, branch=BRANCH):
        self.repo, self.token, self.branch = repo, token, branch
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
                                 {'message': message, 'content': base64.b64encode(content).decode(), 'branch': self.branch})
        if status not in (200, 201):
            raise RuntimeError(f'GitHub refused {path} ({status}{": " + body.get("message", "") if isinstance(body, dict) else ""})')

    def release(self, tag, title, notes):
        status, body = self.call('GET', f'{API}/repos/{self.repo}/releases/tags/{tag}')
        if status == 200:
            return body
        status, body = self.call('POST', f'{API}/repos/{self.repo}/releases',
                                 {'tag_name': tag, 'target_commitish': self.branch, 'name': title, 'body': notes,
                                  'draft': False, 'prerelease': True})
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


def read_text(path, limit=20000):
    try:
        return Path(path).read_text(errors='replace')[-limit:]
    except OSError as error:
        return f'{path}: {error.strerror}'


def gps_evidence():
    """What the GPS service hears, raw: a speed of nothing starts here."""
    return {'services': text_of('systemctl', 'is-active', 'gpsd.socket', 'gpsd.service').split(),
            'gpsd_config': read_text('/etc/default/gpsd'),
            'serial_ports': text_of('ls', '-l', '/dev/serial/by-id/'),
            'usb': text_of('lsusb'),
            # TPV carries mode (fix), speed and track; SKY the satellites; DEVICES the port.
            'gpspipe': text_of('timeout', '8', 'gpspipe', '-w', '-n', '25', timeout=12)}


def can_evidence():
    return {'link': text_of('ip', '-details', '-statistics', 'link', 'show', 'can0'),
            'traffic_2s': text_of('timeout', '2', 'candump', '-t', 'a', '-n', '400', 'can0', timeout=6)[-60000:]}


def journal():
    """The parts of the system log that explain a problem, each under its own heading."""
    base = ('journalctl', '--no-pager', '-o', 'short-iso')
    parts = [('This start: the dash, GPS, Wi-Fi and power services',
              base + ('-b', '-n', '3000', '-u', 'frogdash*', '-u', 'gpsd*', '-u', 'NetworkManager*', '-u', 'pisugar*', '-u', 'chrony*')),
             ('This start: warnings and errors from everything', base + ('-b', '-p', 'warning', '-n', '1500')),
             ('The start before this one: its last lines (how it shut down)', base + ('-b', '-1', '-n', '400'))]
    return ''.join(f'===== {title} =====\n{text_of(*command, timeout=60)}\n' for title, command in parts)


def events_since(since):
    """The dash's problem record after `since` (Unix time) as readable lines, and the time
    of the last one (eventlog.py writes one JSON line per event, a file a day)."""
    lines, last = [], since
    for path in sorted(EVENTS.glob('*.jsonl')) if EVENTS.is_dir() else []:
        for line in read_text(path, 50 << 20).splitlines():
            try:
                entry = json.loads(line)
                when = float(entry['t'])
            except (ValueError, KeyError, TypeError):
                continue
            if when <= since:
                continue
            last = max(last, when)
            text = (f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(when))} UTC  {str(entry.get('level', 'info')).upper():5}  "
                    f"{str(entry.get('area', '')):8} {entry.get('text', '')}")
            if entry.get('detail'):
                text += '  ' + json.dumps(entry['detail'], separators=(',', ':'), default=str)
            lines.append(text)
    body = '\n'.join(lines) + ('\n' if lines else '')
    if len(body) > MAX_EVENT_BYTES:
        body = '(older lines left out: too many)\n' + body[-MAX_EVENT_BYTES:]
    return body, last


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
            'state': local('/state'), 'firmware': local('/firmware'),
            'gps': gps_evidence(), 'can': can_evidence(),
            'helpers': {name: read_json(name) for name in STATUS_FILES}, 'update_failure_log': failure,
            'uptime_s': float((Path('/proc/uptime').read_text().split() or ['0'])[0]) if Path('/proc/uptime').exists() else None,
            'throttled': text_of('vcgencmd', 'get_throttled').strip(), 'disk': text_of('df', '-h', '/', str(STATE)).strip()}


def secrets(config):
    """Everything that must not go up: (text, replacement). Saved Wi-Fi passwords and
    network names (NetworkManager), the dash's hotspot password, the phone page's code
    and session, and the upload token itself."""
    found = {}
    names = text_of('nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show')
    for line in names.splitlines():
        name, _, kind = line.rpartition(':')
        if kind != '802-11-wireless' or not name:
            continue
        name = name.replace('\\:', ':')
        psk = text_of('nmcli', '-s', '-g', '802-11-wireless-security.psk', 'connection', 'show', name).strip()
        ssid = text_of('nmcli', '-g', '802-11-wireless.ssid', 'connection', 'show', name).strip()
        if psk:
            found[psk] = '(password hidden)'
        for label in (ssid, name):
            if label and label not in ('dashcam', 'preconfigured'):
                found.setdefault(label, '(Wi-Fi network)')
    for path in (Path('/etc/frogdash/hotspot.json'), STATE / 'hotspot-resume.json'):
        values = load(path, {})
        for key, value in (values.items() if isinstance(values, dict) else []):
            if isinstance(value, str) and any(word in key.lower() for word in ('pass', 'psk', 'code', 'session', 'secret')):
                found[value] = '(hidden)'
    if config.get('token'):
        found[config['token']] = '(hidden)'
    # Longest first, so a password containing a network name is blanked whole.
    return sorted(((k, v) for k, v in found.items() if len(k) >= 4), key=lambda kv: -len(kv[0]))


def scrub(text, hidden):
    for secret, replacement in hidden:
        text = text.replace(secret, replacement)
    return text


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


def make_report(now, config, since):
    """This moment's report: {file name: bytes}, secrets blanked; and the time of its last event."""
    hidden = secrets(config)
    events, until = events_since(since)
    files = {'events.txt': scrub(events or '(no events since the last report)\n', hidden).encode(errors='replace'),
             'diagnostics.json': scrub(json.dumps(diagnostics(now), indent=1, default=str), hidden).encode()}
    user = kiosk_user()
    boot = text_of(sys.executable, str(REPO_DIR / 'tools/boot_report.py'), *(['--user', user] if user else []), timeout=90)
    files['boot.txt'] = scrub(boot, hidden).encode(errors='replace')
    files['journal.txt'] = scrub(journal(), hidden).encode(errors='replace')[-3_000_000:]
    return files, until


def keep(now, files):
    """Hold a report on the Pi until uploads work; the newest KEEP_REPORTS are kept."""
    folder = REPORTS / time.strftime('%Y-%m-%d_%H%M%S', time.gmtime(now))
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(REPORTS, 0o700)
    for name, content in files.items():
        (folder / name).write_bytes(content)
    for old in sorted(p for p in REPORTS.iterdir() if p.is_dir())[:-KEEP_REPORTS]:
        shutil.rmtree(old, ignore_errors=True)


def held():
    """Reports kept on the Pi, oldest first: (folder, Unix time)."""
    found = []
    for folder in sorted(REPORTS.iterdir()) if REPORTS.is_dir() else []:
        try:
            found.append((folder, calendar.timegm(time.strptime(folder.name, '%Y-%m-%d_%H%M%S'))))
        except ValueError:
            continue
    return found


def send_report(github, when, files):
    stamp = time.strftime('%Y-%m-%d/%H%M%S', time.gmtime(when))
    message = f'Pi report {time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(when))}'
    # The record of what went wrong first: small, and the most useful.
    for name in sorted(files, key=lambda n: (n != 'events.txt', n != 'diagnostics.json', n)):
        github.put_file(f'pi/{stamp}-{name}', files[name], message)


def run(now=None, github=None, wait=time.sleep):
    now = now or time.time()
    config = load(CONFIG, {})
    repo, token = config.get('repo', ''), config.get('token', '')
    status = load(STATUS, {})
    since = status.get('events_until') or now - FIRST_EVENTS_S
    files, until = make_report(now, config, since)
    if not repo or not token:
        keep(now, files)
        save_status({**status, 'time': int(now), 'state': 'held', 'events_until': until, 'held': len(held()),
                     'message': 'Report kept on the Pi: uploads not set up'})
        return f'Uploads not set up; report kept on the Pi ({len(held())} waiting)'
    github = github or GitHub(repo, token, branch=config.get('branch') or BRANCH)
    sent = status.get('sent', [])
    # Reports kept from before (uploads not yet set up, or offline at the time) go first.
    earlier = 0
    for folder, when in held():
        send_report(github, when, {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()})
        shutil.rmtree(folder, ignore_errors=True)
        earlier += 1
    try:
        send_report(github, now, files)
    except Exception:
        keep(now, files)   # Sent next time, with its events.
        save_status({**status, 'events_until': until, 'held': len(held())})
        raise
    status = {**status, 'events_until': until}

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
    if earlier:
        result += f', and {earlier} earlier report{"" if earlier == 1 else "s"} kept on the Pi'
    if skipped:
        result += f'; {skipped} more too large for one upload'
    save_status({'time': int(now), 'state': 'done', 'message': result, 'repo': repo, 'sent': sent, 'events_until': until,
                 'held': len(held())})
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
