#!/usr/bin/env python3
"""The rescue screen: shown instead of a black screen when the dash is not running.

The screen's launcher (tools/launch_kiosk.py) opens it when the dash has not answered
for half a minute, and goes back to the dash as soon as the dash answers. It says why the
dash is down (the end of its log) and has large buttons, used with the mouse or a touch,
for what can be done without a keyboard, Wi-Fi setup or SSH:

  restart the dash · go back to the version that last ran · undo the last update ·
  update to the newest version · finish the Pi setup (install what is missing) ·
  restart the Pi

Run as root by frogdash-rescue.service, from a copy in /usr/local/lib/frogdash that the
Pi setup puts there only from a version that has started, so a broken version cannot
break this too. Standard library only, so it needs nothing that an update could take
away. It listens on 127.0.0.1 only, accepts only its fixed actions, and only from its own
page (a header other pages cannot send without asking first, and its own host name).
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import urllib.request

PORT = 8090
REPO = Path(os.environ.get('FROGDASH_REPO', '/opt/frogdash'))
STATE = Path(os.environ.get('FROGDASH_STATE') or os.path.realpath('/var/lib/frogdash'))
UNITS = Path(os.environ.get('FROGDASH_UNITS', '/etc/systemd/system'))
BUSY = Path(os.environ.get('FROGDASH_BUSY', '/run/frogdash-busy'))
HEADER = 'X-Frogdash-Rescue'

ACTIONS = {
    'restart': ('Restart the dash', 'Starts the dash program again. Nothing else changes.'),
    'good': ('Go back to the version that last ran', 'Puts back the last version that started and ran for two minutes, then restarts the dash.'),
    'previous': ('Undo the last update', 'Returns to the version from before the last update, the way Undo update does.'),
    'update': ('Update to the newest version', 'Needs the internet: a saved Wi-Fi network or your phone hotspot in range. The new version is tried before it is used.'),
    'setup': ('Finish the Pi setup', 'Installs what this version needs that is missing (Python packages and the rest). Needs the internet for downloads.'),
    'reboot': ('Restart the Pi', 'The whole Pi starts again, as with the key off and on.'),
}


def run(*command, timeout=30):
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout + done.stderr).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return 1, str(error)


def read(path, default=''):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        return default


def dash_port():
    for line in read('/etc/default/frogdash').splitlines():
        if '--port' in line:
            parts = line.replace('=', ' ').replace('"', ' ').split()
            if '--port' in parts and parts.index('--port') + 1 < len(parts) and parts[parts.index('--port') + 1].isdigit():
                return int(parts[parts.index('--port') + 1])
    return 8080


def answering(port=None):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port or dash_port()}/health', timeout=2):
            return True
    except OSError:
        return False


class Internet:
    """Whether GitHub can be reached, looked up at most every 30 s."""
    def __init__(self):
        self.at, self.value = 0.0, None

    def __call__(self):
        if time.monotonic() - self.at > 30:
            self.at = time.monotonic()
            try:
                socket.create_connection(('github.com', 443), timeout=3).close()
                self.value = True
            except OSError:
                self.value = False
        return self.value


class Rescue:
    def __init__(self, runner=run, port=None):
        self.run, self.port = runner, port
        self.internet = Internet()
        self.action = {'name': None, 'state': 'idle', 'message': ''}
        self.lock = threading.Lock()

    def short(self, commit):
        if not commit:
            return ''
        code, out = self.run('git', '-C', str(REPO), 'rev-parse', '--short', commit)
        return out if code == 0 else commit[:7]

    def state(self):
        code, head = self.run('git', '-C', str(REPO), 'log', '-1', '--format=%h %cd %s', '--date=format:%d %b %H:%M')
        _, active = self.run('systemctl', 'is-active', 'frogdash.service')
        _, journal = self.run('journalctl', '-u', 'frogdash.service', '-n', '40', '--no-pager', '-o', 'cat')
        try:
            update = json.loads(read(STATE / 'update-status.json', '{}') or '{}')
        except ValueError:
            update = {}
        busy = run_busy(self.run)
        active = active if active.replace('-', '').isalpha() else 'unknown'   # One word from systemctl, or it did not answer
        return {'answering': answering(self.port), 'service': active or 'unknown', 'version': head if code == 0 else 'unknown',
                'good': self.short(read(STATE / 'last-good')), 'previous': self.short(read(STATE / 'update-previous')),
                'bad': self.short(read(STATE / 'update-bad')), 'update': update if isinstance(update, dict) else {},
                'internet': self.internet(), 'busy': busy, 'journal': journal[-6000:], 'action': dict(self.action),
                'actions': {name: {'title': t, 'detail': d, 'available': self.available(name)} for name, (t, d) in ACTIONS.items()}}

    def available(self, name):
        if name == 'good':
            good = read(STATE / 'last-good')
            code, head = self.run('git', '-C', str(REPO), 'rev-parse', 'HEAD')
            return bool(good) and (code != 0 or head != good)
        if name == 'previous':
            return bool(read(STATE / 'update-previous'))
        return True

    def start(self, name):
        if name not in ACTIONS:
            return 'Unknown action'
        if not self.available(name):
            return 'There is no earlier version saved to go back to'
        with self.lock:
            if self.action['state'] == 'running':
                return 'Already doing something: wait for it to finish'
            self.action = {'name': name, 'state': 'running', 'message': ACTIONS[name][0] + '…'}
        threading.Thread(target=self.do, args=(name,), daemon=True).start()
        return None

    def do(self, name):
        try:
            message = getattr(self, 'do_' + name)()
            self.action = {'name': name, 'state': 'done', 'message': message}
        except Exception as error:   # Whatever happens, the page keeps working and says so
            self.action = {'name': name, 'state': 'failed', 'message': str(error)[:300]}

    def request(self, word):
        """The updater (frogdash-update.service) runs on a request file, as from the dash."""
        path = STATE / 'update-request'
        path.write_text(word, encoding='utf-8')
        try:
            shutil.chown(path, *owner(STATE))
        except (OSError, LookupError, TypeError):
            pass
        code, _ = self.run('systemctl', 'start', '--no-block', 'frogdash-update.service')
        return code

    def do_restart(self):
        code, out = self.run('systemctl', 'restart', 'frogdash.service', timeout=60)
        if code:
            raise RuntimeError(out or 'systemctl failed')
        return 'Restarted. The screen goes back to the dash as soon as it answers'

    def do_good(self):
        good = read(STATE / 'last-good')
        _, head = self.run('git', '-C', str(REPO), 'rev-parse', 'HEAD')
        BUSY.touch()
        try:
            code, out = self.run('git', '-C', str(REPO), 'reset', '--keep', '--quiet', good)
            if code:
                code, out = self.run('git', '-C', str(REPO), 'reset', '--hard', '--quiet', good)
            if code:
                raise RuntimeError(out or 'git could not go back')
            (STATE / 'update-bad').write_text(head + '\n', encoding='utf-8')
            sync_units(self.run)
            self.run('systemctl', 'restart', 'frogdash.service', timeout=60)
        finally:
            BUSY.unlink(missing_ok=True)
        return f'Back on {self.short(good)}, the last version that ran. The screen returns to the dash as soon as it answers'

    def do_previous(self):
        self.request('rollback')
        return 'Undoing the last update: this takes a minute or two'

    def do_update(self):
        self.request('requested')
        return 'Updating: the new version is tried first, then used. A few minutes'

    def do_setup(self):
        self.request('setup')
        return 'Finishing the Pi setup: a few minutes, longer if it downloads'

    def do_reboot(self):
        self.run('systemctl', '--no-block', 'reboot')
        return 'Restarting the Pi'


def owner(path):
    stat = Path(path).stat()
    return stat.st_uid, stat.st_gid


def run_busy(runner):
    code, _ = runner('systemctl', 'is-active', '--quiet', 'frogdash-update.service')
    if code == 0:
        return True
    try:
        return time.time() - BUSY.stat().st_mtime < 20 * 60
    except OSError:
        return False


def sync_units(runner):
    """The unit files of the version now checked out, for the ones that are installed."""
    changed = False
    for unit in sorted((REPO / 'hardware/systemd').glob('*.service')) + sorted((REPO / 'hardware/systemd').glob('*.path')):
        target = UNITS / unit.name
        if target.exists() and target.read_bytes() != unit.read_bytes():
            shutil.copyfile(unit, target)
            changed = True
    if changed:
        runner('systemctl', 'daemon-reload')


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dash rescue</title><style>
:root{color-scheme:dark;--bg:#090f13;--surface:#111a20;--line:#2b3943;--text:#f1f5f4;--muted:#a6b6c0;--accent:#8befc4;--warn:#ffd080;--bad:#ff7979}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:18px "DejaVu Sans",Arial,sans-serif;padding:28px 36px;overflow:auto;height:100vh}
h1{margin:0 0 4px;font-size:34px}p{margin:4px 0;color:var(--muted)}.top{display:flex;gap:24px;align-items:flex-start}
.top>div:first-child{flex:1}.pill{display:inline-block;padding:6px 14px;border-radius:99px;font-weight:800;border:1px solid var(--line)}
.pill.bad{color:var(--bad);border-color:var(--bad)}.pill.good{color:var(--accent);border-color:var(--accent)}.pill.warn{color:var(--warn);border-color:var(--warn)}
main{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:22px;margin-top:18px}
.buttons{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-content:start}
button{min-height:86px;padding:12px 16px;border-radius:12px;border:1px solid var(--line);background:var(--surface);color:var(--text);font:inherit;font-weight:800;text-align:left;cursor:pointer}
button small{display:block;font-weight:400;color:var(--muted);font-size:14px;margin-top:4px}button[data-armed]{border-color:var(--warn);color:var(--warn)}
button:disabled{opacity:.45;cursor:default}pre{margin:0;background:#05090c;border:1px solid var(--line);border-radius:12px;padding:12px;font-size:13px;
white-space:pre-wrap;word-break:break-word;max-height:470px;overflow:auto;color:#cfd8dc}.facts{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:10px 0}
.facts b{color:var(--muted);font-weight:400}#said{min-height:26px;margin:10px 0;font-weight:800}@media(max-width:900px){main,.buttons{grid-template-columns:1fr}}
</style></head><body>
<div class="top"><div><h1>The dash is not running</h1><p id="why">Looking…</p></div><span class="pill" id="pill">…</span></div>
<div class="facts" id="facts"></div><div id="said"></div>
<main><section class="buttons" id="buttons"></section><section><p>The end of the dash's log (what it said before it stopped):</p><pre id="log">…</pre></section></main>
<script>
const $ = id => document.getElementById(id);
let armed = '', timer = 0, latest = null;
function fact(label, value) { const b = document.createElement('b'), s = document.createElement('span'); b.textContent = label; s.textContent = value || '—'; return [b, s]; }
function render(s) {
  latest = s;
  const pill = $('pill');
  if (s.answering) { pill.className = 'pill good'; pill.textContent = 'Dash running'; $('why').textContent = 'The dash is answering again: going back to it.'; }
  else if (s.busy) { pill.className = 'pill warn'; pill.textContent = 'Working…'; $('why').textContent = 'An update or a recovery is running. Leave the key on; this page follows it.'; }
  else { pill.className = 'pill bad'; pill.textContent = s.service === 'activating' ? 'Starting' : 'Not running';
    const said = {activating: 'starting again and again: it stops during start-up', failed: 'stopped with an error', inactive: 'stopped',
      active: 'running but not answering', unknown: 'in a state that could not be read'}[s.service] || s.service;
    $('why').textContent = 'The dash program is ' + said + '. Pick what to do below; the end of its log is on the right.'; }
  $('facts').replaceChildren(...fact('Running version', s.version), ...fact('Last version that ran', s.good), ...fact('Before the last update', s.previous),
    ...fact('Internet', s.internet === null ? 'checking' : s.internet ? 'yes' : 'no: updates need a saved Wi-Fi or your phone hotspot in range'),
    ...fact('Last update', s.update && s.update.message));
  $('said').textContent = s.action.message || '';
  $('said').style.color = s.action.state === 'failed' ? 'var(--bad)' : 'var(--accent)';
  $('log').textContent = s.journal || '(no log)';
  const list = $('buttons');
  if (!list.children.length) for (const [name, a] of Object.entries(s.actions)) {
    const b = document.createElement('button'); b.type = 'button'; b.dataset.action = name; b.onclick = () => press(name); list.append(b);
  }
  for (const b of list.children) {
    const a = s.actions[b.dataset.action], on = armed === b.dataset.action;
    b.disabled = !a.available || s.action.state === 'running' || s.busy;
    b.innerHTML = ''; b.append(on ? 'Press again to ' + a.title.toLowerCase() : a.title);
    const small = document.createElement('small'); small.textContent = a.available ? a.detail : 'No earlier version is saved'; b.append(small);
    if (on) b.dataset.armed = ''; else delete b.dataset.armed;
  }
}
async function press(name) {
  if (armed !== name) { armed = name; clearTimeout(timer); timer = setTimeout(() => { armed = ''; latest && render(latest); }, 6000); latest && render(latest); return; }
  armed = '';
  try {
    const r = await fetch('/act', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Frogdash-Rescue': '1'}, body: JSON.stringify({action: name})});
    const said = await r.json(); if (said.error) { $('said').textContent = said.error; $('said').style.color = 'var(--bad)'; }
  } catch { $('said').textContent = 'The rescue helper did not answer'; }
  poll();
}
async function poll() {
  try { render(await (await fetch('/state', {cache: 'no-store', headers: {'X-Frogdash-Rescue': '1'}})).json()); }
  catch { $('why').textContent = 'The rescue helper is not answering'; }
}
poll(); setInterval(poll, 2000);
</script></body></html>"""


def handler(rescue, port):
    class Handler(BaseHTTPRequestHandler):
        def allowed(self):
            host = (self.headers.get('Host') or '').split(':')[0]
            return host in ('127.0.0.1', 'localhost')

        def reply(self, status, body, kind='application/json'):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {'error': 'local only'})
            if self.path == '/':
                return self.reply(200, PAGE.encode(), 'text/html; charset=utf-8')
            if self.path == '/health':
                return self.reply(200, {'rescue': True})
            if self.path == '/state' and self.headers.get(HEADER) == '1':
                return self.reply(200, rescue.state())
            return self.reply(404, {'error': 'not found'})

        def do_POST(self):
            try:   # Read first: answering before the body is read resets the connection
                body = self.rfile.read(min(int(self.headers.get('Content-Length') or 0), 1000))
            except ValueError:
                return self.reply(400, {'error': 'bad request'})
            if not self.allowed() or self.headers.get(HEADER) != '1' or self.path != '/act':
                return self.reply(403, {'error': 'not allowed'})
            try:
                name = json.loads(body or b'{}').get('action')
            except (ValueError, AttributeError):
                return self.reply(400, {'error': 'bad request'})
            error = rescue.start(name)
            return self.reply(409 if error else 200, {'error': error} if error else {'started': name})

        def log_message(self, *args):
            pass
    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args(argv)
    rescue = Rescue()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(rescue, args.port))
    print(f'frogdash-rescue: listening on 127.0.0.1:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
