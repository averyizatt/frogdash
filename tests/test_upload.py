"""Uploads after an update (tools/frogdash_upload.py and the phone page's Uploads section),
against a stand-in GitHub that records what it is sent."""
import gzip
import base64
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest.mock import Mock

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.connectivity import TransferPortal
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
TOKEN = 'github_pat_' + 'A1b2' * 20


class FakeGitHub:
    def __init__(self):
        self.files, self.releases, self.assets = {}, {}, []

    def put_file(self, path, content, message):
        self.files[path] = content

    def release(self, tag, title, notes):
        return self.releases.setdefault(tag, {'id': len(self.releases) + 1, 'tag': tag})

    def upload_asset(self, release, name, path):
        self.assets.append((release['tag'], name, gzip.decompress(Path(path).read_bytes())))


class ContentsAPI:
    """GitHub's create/update distinction, including a reply lost after committing."""
    def __init__(self):
        self.files, self.writes = {}, []
        self.fail_path = None
        self.lose_reply = False

    @staticmethod
    def sha(content):
        return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()

    def open(self, request, timeout):
        url = urllib.parse.urlsplit(request.full_url)
        path = urllib.parse.unquote(url.path.split('/contents/', 1)[1])
        payload = json.loads(request.data) if request.data else {}
        branch = payload.get('branch') or urllib.parse.parse_qs(url.query)['ref'][0]
        key = (branch, path)
        if path == self.fail_path:
            status, body = 503, {'message': 'Unavailable'}
        elif request.method == 'GET':
            status, body = (200, {'sha': self.sha(self.files[key])}) if key in self.files else (404, {})
        elif key in self.files and payload.get('sha') != self.sha(self.files[key]):
            status, body = 422, {'message': 'Invalid request. "sha" wasn\'t supplied.'}
        else:
            status, body = (200 if key in self.files else 201), {}
            self.files[key] = base64.b64decode(payload['content'])
            self.writes.append(key)
            if self.lose_reply:
                self.lose_reply = False
                raise urllib.error.URLError('Connection lost after commit')
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, 'Failed', {}, io.BytesIO(json.dumps(body).encode()))
        response = io.BytesIO(json.dumps(body).encode())
        response.status, response.headers = status, {}
        return response


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saved = dict(os.environ)
        self.state = Path(self.folder.name)
        os.environ['FROGDASH_STATE'] = str(self.state)
        import frogdash_upload
        self.up = importlib.reload(frogdash_upload)
        self.logs = self.state / 'logs'
        self.logs.mkdir()
        self.listing = {'files': []}
        self.snapshot = {'modules': {'taillights': 'live'}, 'updating': []}
        self.up.local = lambda path, method='GET', timeout=10: (self.listing if path == '/logs' else
                                                                 self.snapshot if path == '/snapshot' else None)
        self.up.text_of = lambda *args, timeout=30: f'(output of {args[0]})\n'

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        self.folder.cleanup()

    def log(self, stamp, minutes, body):
        """A recording that started at `stamp` (UTC) and was last written `minutes` later."""
        name = f'frogdash-live-{stamp}-{os.urandom(6).hex()}.mlg'
        path = self.logs / name
        path.write_bytes(body)
        end = self.up.started(name) + minutes * 60
        os.utime(path, (end, end))
        return name

    def test_existing_report_file_is_skipped_or_updated_on_its_branch(self):
        api = ContentsAPI()
        github = self.up.GitHub('owner/frogdash', TOKEN, opener=api, branch='reports/pi')
        path = 'pi/2026-11-06/120000-events.txt'
        github.put_file(path, b'GPS lost\n', 'report')
        github.put_file(path, b'GPS lost\n', 'report')
        self.assertEqual(len(api.writes), 1)  # A repeat creates no duplicate commit.
        github.put_file(path, b'GPS recovered\n', 'report')
        self.assertEqual(api.files, {('reports/pi', path): b'GPS recovered\n'})
        self.assertEqual(len(api.writes), 2)

    def test_success_reply_lost_after_commit_does_not_block_the_report(self):
        api, waits = ContentsAPI(), []
        api.lose_reply = True
        github = self.up.GitHub('owner/frogdash', TOKEN, opener=api, wait=waits.append)
        github.put_file('pi/events.txt', b'GPS lost\n', 'report')
        self.assertEqual(waits, [5])
        self.assertEqual(len(api.writes), 1)

    def test_partly_uploaded_report_and_the_rest_of_the_queue_resume(self):
        (self.state / 'log-upload.json').write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))
        api = ContentsAPI()
        github = self.up.GitHub('owner/frogdash', TOKEN, opener=api)
        api.fail_path = 'pi/2026-10-15/120000-diagnostics.json'
        with self.assertRaisesRegex(RuntimeError, '503'):
            self.up.run(now=1792065600, github=github, drives=False)
        self.assertEqual(len(self.up.held()), 1)
        self.assertEqual(api.writes, [('pi-logs', 'pi/2026-10-15/120000-events.txt')])
        for offset in range(1, 5):
            self.up.keep(1792065600 + offset * 60, {'events.txt': b'queued report\n'})
        api.fail_path = None
        said = self.up.run(now=1792069200, github=github, drives=False)
        self.assertIn('5 kept on the Pi', said)
        self.assertEqual(self.up.held(), [])
        self.assertEqual(len(api.writes), 12)  # Four original, four queued, four fresh files.
        status = json.loads((self.state / 'upload-status.json').read_text())
        self.assertEqual((status['state'], status['held']), ('done', 0))

    def test_validation_or_permission_error_does_not_count_as_uploaded(self):
        for status, lookup in ((422, (404, {})), (422, (403, {})), (422, (200, {})), (403, None)):
            with self.subTest(status=status, lookup=lookup):
                github = self.up.GitHub('owner/frogdash', TOKEN)
                answers = [(status, {'message': 'Refused'})] + ([lookup] if lookup else [])
                github.call = Mock(side_effect=answers)
                with self.assertRaisesRegex(RuntimeError, f'GitHub refused pi/events.txt \\({status}'):
                    github.put_file('pi/events.txt', b'events', 'report')
                self.assertEqual(github.call.call_count, len(answers))

    def test_conflicts_refresh_the_sha_and_stop_after_three_attempts(self):
        github = self.up.GitHub('owner/frogdash', TOKEN)
        github.call = Mock(side_effect=[(409, {'message': 'Conflict'}), (200, {'sha': 'changed'})] * 3)
        with self.assertRaisesRegex(RuntimeError, '409: Conflict'):
            github.put_file('pi/events.txt', b'events', 'report')
        self.assertEqual(github.call.call_count, 6)

    def test_the_newest_drive_is_the_files_close_together_at_the_end(self):
        up = self.up
        files = [('frogdash-live-20261014T170000Z-aaaaaaaaaaaa.mlg', up.started('frogdash-live-20261014T170000Z-aaaaaaaaaaaa.mlg') + 1800, 5),
                 ('frogdash-live-20261015T120000Z-bbbbbbbbbbbb.mlg', up.started('frogdash-live-20261015T120000Z-bbbbbbbbbbbb.mlg') + 1800, 6),
                 ('frogdash-live-20261015T123200Z-cccccccccccc.mlg', up.started('frogdash-live-20261015T123200Z-cccccccccccc.mlg') + 600, 7),
                 ('frogdash-live-20261015T125000Z-dddddddddddd.mlg', up.started('frogdash-live-20261015T125000Z-dddddddddddd.mlg') + 30, 8),
                 ('notes.txt', 0, 1)]
        drive = up.newest_drive(files, active={'frogdash-live-20261015T125000Z-dddddddddddd.mlg'})
        self.assertEqual([f[0][14:29] for f in drive], ['20261015T120000', '20261015T123200'])   # Not yesterday's, not the open file
        self.assertEqual(up.newest_drive([]), [])

    def test_not_set_up_keeps_the_report_on_the_pi_and_sends_it_later(self):
        events = self.state / 'events'
        events.mkdir()
        (events / '2026-10-15.jsonl').write_text(
            json.dumps({'t': 1792060000, 'level': 'warn', 'area': 'gps', 'text': 'GPS has a position but no speed', 'detail': {'status': 'GPS fix'}}) + '\n' +
            'not json\n' + json.dumps({'t': 1792060100, 'level': 'info', 'area': 'engine', 'text': 'Engine stopped'}) + '\n')
        said = self.up.run(now=1792065600, github=FakeGitHub(), wait=lambda s: None)
        self.assertEqual(said, 'Uploads not set up; report kept on the Pi (1 waiting)')
        self.assertEqual(json.loads((self.state / 'upload-status.json').read_text())['held'], 1)   # For the dash: it cannot read reports/
        kept = next((self.state / 'reports').iterdir())
        self.assertEqual(sorted(p.name for p in kept.iterdir()), ['boot.txt', 'diagnostics.json', 'events.txt', 'journal.txt'])
        self.assertEqual((kept / 'events.txt').read_text(),
                         '2026-10-15 10:26:40 UTC  WARN   gps      GPS has a position but no speed  {"status":"GPS fix"}\n'
                         '2026-10-15 10:28:20 UTC  INFO   engine   Engine stopped\n')
        # Set up later: the kept report goes up first, and the new one does not repeat its events.
        (self.state / 'log-upload.json').write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))
        hub = FakeGitHub()
        said = self.up.run(now=1792069200, github=hub, wait=lambda s: None)
        self.assertEqual(said, 'Uploaded the diagnostics (no new drive to send), and 1 earlier report kept on the Pi')
        self.assertIn(b'Engine stopped', hub.files['pi/2026-10-15/120000-events.txt'])
        self.assertEqual(hub.files['pi/2026-10-15/130000-events.txt'], b'(no events since the last report)\n')
        self.assertEqual(list((self.state / 'reports').iterdir()), [])
        self.assertEqual(json.loads((self.state / 'upload-status.json').read_text())['held'], 0)

    def test_reports_and_the_newest_drive_go_up_once(self):
        (self.state / 'log-upload.json').write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))
        (self.state / 'screen-status.json').write_text('{"state": "original"}')
        self.log('20261014T170000Z', 30, b'yesterday')
        first = self.log('20261015T120000Z', 30, b'drive part one' * 100)
        second = self.log('20261015T123200Z', 10, b'drive part two' * 100)
        # A CAN recording made on the dash: goes up with this report, once.
        (self.state / 'can-recordings').mkdir()
        recording = self.state / 'can-recordings/20261015-120500.log'
        recording.write_text('(1792065000.000000) can0 300#0000550114 3C4600\n')
        os.utime(recording, (1792065300, 1792065300))
        hub = FakeGitHub()
        said = self.up.run(now=1792065600, github=hub, wait=lambda s: None)
        self.assertEqual(said, 'Uploaded the diagnostics and 2 recordings of the newest drive')
        self.assertIn(b'can0 300#', next(v for p, v in hub.files.items() if p.endswith('can-20261015-120500.log')))
        hub.files = {p: v for p, v in hub.files.items() if not p.endswith('.log')}
        self.assertEqual(sorted(p.rsplit('-', 1)[1] for p in hub.files), ['boot.txt', 'diagnostics.json', 'events.txt', 'journal.txt'])
        self.assertEqual(list(hub.files)[0].rsplit('-', 1)[1], 'events.txt')         # What went wrong, first
        diagnostics = json.loads(next(v for p, v in hub.files.items() if p.endswith('diagnostics.json')))
        self.assertEqual(diagnostics['helpers']['screen-status.json'], {'state': 'original'})
        self.assertEqual(diagnostics['gps']['gpspipe'], '(output of timeout)\n')   # What gpsd hears, raw
        self.assertEqual(diagnostics['state'], self.snapshot)                        # The dash's live picture
        self.assertIn('The start before this one', next(v for p, v in hub.files.items() if p.endswith('journal.txt')).decode())
        self.assertEqual(list(hub.releases), ['drive-20261015-1200'])
        self.assertEqual([(name, body[:14]) for _, name, body in hub.assets],
                         [(first + '.gz', b'drive part one'), (second + '.gz', b'drive part two')])
        status = (self.state / 'upload-status.json').read_text()
        self.assertNotIn(TOKEN, status)
        # The next update: the reports again, the same drive not again.
        hub2 = FakeGitHub()
        self.assertEqual(self.up.run(now=1792069200, github=hub2, wait=lambda s: None), 'Uploaded the diagnostics (no new drive to send)')
        self.assertEqual((len(hub2.files), hub2.assets), (4, []))

    def test_reports_go_by_themselves_when_github_can_be_reached(self):
        boot, online, hub = ['boot-1'], [False], FakeGitHub()
        go = lambda now: self.up.auto(now=now, github=hub, reach=lambda: online[0], boot=lambda: boot[0])
        self.assertEqual(go(1792065600), 'Uploads not set up')
        (self.state / 'log-upload.json').write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))
        self.log('20261015T120000Z', 30, b'a drive')
        self.assertEqual(go(1792065600), 'No internet')                   # The dash cam's Wi-Fi: nothing goes
        self.assertEqual(hub.files, {})
        online[0] = True                                                 # Home Wi-Fi or the phone hotspot
        self.assertEqual(go(1792065660), 'Sent a report by itself')
        self.assertTrue(any(p.endswith('events.txt') for p in hub.files))
        self.assertEqual((hub.releases, hub.assets), ({}, []))            # Drives go with Update now / Send now
        count = len(hub.files)
        self.assertEqual(go(1792065960), 'Nothing new to send')           # Same start, nothing new
        events = self.state / 'events'
        events.mkdir(exist_ok=True)
        (events / '2026-10-15.jsonl').write_text(json.dumps({'t': 1792065900, 'level': 'warn', 'area': 'gps', 'text': 'GPS lost'}) + '\n')
        self.assertEqual(go(1792066200), 'Nothing new to send')           # New events, but not 30 minutes yet
        self.assertIn('Sent a report', go(1792065660 + self.up.AUTO_EVERY_S + 1))
        self.assertGreater(len(hub.files), count)
        boot[0] = 'boot-2'                                               # The next start goes up at once
        self.assertIn('Sent a report', go(1792065660 + self.up.AUTO_EVERY_S + 60))
        # While an update or recovery runs, it waits.
        boot[0] = 'boot-3'
        busy = self.state / 'busy'
        busy.write_text('')
        self.up.BUSY = busy
        self.assertEqual(go(1792065660 + self.up.AUTO_EVERY_S + 120), 'An update or recovery is running')

    def test_wifi_passwords_and_names_are_blanked_before_anything_goes_up(self):
        (self.state / 'log-upload.json').write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))
        (self.state / 'wifi-status.json').write_text(json.dumps({'state': 'joined', 'ssid': 'HomeNet42', 'message': 'Joined HomeNet42'}))
        (self.state / 'hotspot-resume.json').write_text(json.dumps({'until': 1, 'code': '48151623', 'session': 'sessiontoken-abc'}))
        answers = {
            ('nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show'): 'HomeNet42:802-11-wireless\nPhone Hot\\:spot:802-11-wireless\ndashcam:802-11-wireless\nWired:802-3-ethernet\n',
            ('nmcli', '-s', '-g', '802-11-wireless-security.psk', 'connection', 'show', 'HomeNet42'): 'correct-horse-77\n',
            ('nmcli', '-g', '802-11-wireless.ssid', 'connection', 'show', 'HomeNet42'): 'HomeNet42\n',
            ('nmcli', '-s', '-g', '802-11-wireless-security.psk', 'connection', 'show', 'Phone Hot:spot'): 'battery-staple-9\n',
            ('nmcli', '-g', '802-11-wireless.ssid', 'connection', 'show', 'Phone Hot:spot'): 'Phone Hot:spot\n',
        }
        story = 'Joined HomeNet42 (psk correct-horse-77), then Phone Hot:spot with battery-staple-9; portal code 48151623; dashcam up\n'
        self.up.text_of = lambda *args, timeout=30: answers.get(args, '') if args[0] == 'nmcli' else story
        hub = FakeGitHub()
        self.up.run(now=1792065600, github=hub, wait=lambda s: None)
        sent = b''.join(hub.files.values()).decode()
        for secret in ('HomeNet42', 'correct-horse-77', 'Phone Hot:spot', 'battery-staple-9', '48151623', 'sessiontoken-abc', TOKEN):
            self.assertNotIn(secret, sent, secret)
        self.assertIn('(Wi-Fi network)', sent)
        self.assertIn('(password hidden)', sent)
        self.assertIn('dashcam up', sent)              # The dash cam's own connection name stays readable

    def test_a_failure_is_one_line_and_never_shows_the_token(self):
        (self.state / 'log-upload.json').write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))

        class Refusing(FakeGitHub):
            def put_file(self, path, content, message):
                raise RuntimeError('GitHub refused it (401: Bad credentials)')
        self.up.GitHub = lambda repo, token, **kw: Refusing()
        printed = []
        self.up.print = printed.append
        self.up.main()
        self.assertEqual(printed, ['Upload failed: GitHub refused it (401: Bad credentials)'])
        self.assertNotIn(TOKEN, (self.state / 'upload-status.json').read_text())

    def test_a_login_github_no_longer_accepts_is_forgotten_and_the_report_kept(self):
        # The car, November 2026: "Bad credentials" on every try while the dash said Connected.
        config = self.state / 'log-upload.json'
        config.write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))
        up = self.up

        class Refused(FakeGitHub):
            def put_file(self, path, content, message):
                raise up.LoginRefused('Bad credentials')
        self.up.GitHub = lambda repo, token, **kw: Refused()
        printed = []
        self.up.print = printed.append
        self.up.main()
        self.assertEqual(printed, [self.up.REFUSED])
        self.assertFalse(config.exists())                        # The dash offers Connect GitHub again
        status = json.loads((self.state / 'upload-status.json').read_text())
        self.assertEqual((status['state'], status['held']), ('failed', 1))   # The report waits on the Pi
        # Connected again: the kept report goes up.
        config.write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))
        github = FakeGitHub()
        self.up.GitHub = lambda repo, token, **kw: github
        self.up.main()
        self.assertTrue(any(name.endswith('-diagnostics.json') for name in github.files))

    def test_when_a_pasted_token_stops_working_is_kept_and_shown(self):
        (self.state / 'log-upload.json').write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))
        github = FakeGitHub()
        github.expires = '2026-11-12 18:00:00 UTC'        # GitHub's github-authentication-token-expiration
        self.up.GitHub = lambda repo, token, **kw: github
        self.up.print = lambda *a: None
        self.up.main()
        status = json.loads((self.state / 'upload-status.json').read_text())
        self.assertEqual(status['login'], {'via': 'token pasted on the phone page', 'account': None, 'expires': '2026-11-12 18:00:00 UTC'})
        from hardware.frogdash.github_link import GitHubLink
        shown = GitHubLink(self.state, client_id='x').status()
        self.assertEqual((shown['via'], shown['expires']), ('token', '2026-11-12 18:00:00 UTC'))
        # The next report says how uploads are connected, never the token.
        report = json.dumps(self.up.diagnostics(0))
        self.assertIn('"expires": "2026-11-12 18:00:00 UTC"', report)
        self.assertNotIn(TOKEN, report)

    def test_expiring_device_login_renews_during_a_real_report_upload(self):
        from hardware.frogdash.github_link import refresh_login, write_login
        config = {'repo': 'owner/frogdash', 'token': TOKEN, 'refresh_token': 'private-renewal-token',
                  'via': 'device code', 'client_id': 'test-app', 'expires_at': 1, 'login_id': 'same-login'}
        write_login(self.up.CONFIG, config)
        self.up.text_of = lambda *a, **kw: TOKEN + ' private-renewal-token'
        answer = {'access_token': 'renewed-access-token', 'refresh_token': 'renewed-refresh-token', 'expires_in': 28800}
        post = Mock(return_value=answer)
        self.up.refresh_login = lambda path, current, force=False: refresh_login(path, current, force, post=post, wall=lambda: 1000)
        api, original = ContentsAPI(), self.up.GitHub
        self.up.GitHub = lambda repo, token, **kw: original(repo, token, opener=api, **kw)
        self.up.run(now=1792065600, drives=False)
        post.assert_called_once()
        self.assertEqual(json.loads(self.up.CONFIG.read_text())['refresh_token'], 'renewed-refresh-token')
        self.assertEqual(json.loads(self.up.STATUS.read_text())['login']['login_id'], 'same-login')
        sent = b''.join(api.files.values()).decode()
        for secret in (TOKEN, 'private-renewal-token', 'renewed-access-token', 'renewed-refresh-token'):
            self.assertNotIn(secret, sent)

    def test_refused_renewal_keeps_the_report_and_requests_reconnection(self):
        (self.state / 'log-upload.json').write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN,
                                                              'refresh_token': 'expired-refresh-token'}))
        self.up.refresh_login = Mock(side_effect=self.up.RefreshRefused('expired'))
        self.up.print = Mock()
        self.up.main()
        self.assertFalse(self.up.CONFIG.exists())
        self.assertEqual(len(self.up.held()), 1)
        self.up.print.assert_called_once_with(self.up.REFUSED)

    def test_a_moment_without_internet_is_waited_out(self):
        # The car: "Temporary failure in name resolution" while the Wi-Fi came back.
        import io
        import urllib.error

        class Response(io.BytesIO):
            status, headers = 200, {}
            def __enter__(self): return self
            def __exit__(self, *a): return False

        class Opener:
            tries = 0
            def open(self, request, timeout):
                Opener.tries += 1
                if Opener.tries <= 2:
                    raise urllib.error.URLError(OSError(-3, 'Temporary failure in name resolution'))
                return Response(b'{"ok": true}')
        waits = []
        github = self.up.GitHub('owner/frogdash', TOKEN, opener=Opener(), wait=waits.append)
        self.assertEqual(github.call('GET', 'https://api.github.com/user'), (200, {'ok': True}))
        self.assertEqual(waits, [5, 15])
        # Gone for good: the error after the last wait, and the report stays on the Pi.
        Opener.tries = -10
        with self.assertRaises(urllib.error.URLError):
            self.up.GitHub('owner/frogdash', TOKEN, opener=Opener(), wait=waits.append).call('GET', 'https://api.github.com/user')

    def test_github_answering_401_is_a_refused_login(self):
        import io
        import urllib.error

        class Opener:
            def open(self, request, timeout):
                raise urllib.error.HTTPError(request.full_url, 401, 'Unauthorized', {}, io.BytesIO(b'{"message": "Bad credentials"}'))
        with self.assertRaises(self.up.LoginRefused):
            self.up.GitHub('owner/frogdash', TOKEN, opener=Opener()).call('GET', 'https://api.github.com/user')


class PhonePageTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_token_is_saved_and_never_sent_back(self):
        with tempfile.TemporaryDirectory() as folder:
            portal = TransferPortal(State(), Path(folder))
            app = portal.app('127.0.0.0/8')
            async with TestClient(TestServer(app)) as client:
                origin = str(client.make_url('/')).rstrip('/')
                await client.post('/session', json={'code': portal.code}, headers={'Origin': origin})
                self.assertEqual(await (await client.get('/api/upload')).json(), {'configured': False, 'repo': None, 'last': None})
                bad = await client.post('/api/upload', json={'repo': 'owner/frogdash-logs', 'token': 'hunter2'}, headers={'Origin': origin})
                self.assertEqual(bad.status, 400)
                good = await client.post('/api/upload', json={'repo': 'owner/frogdash-logs', 'token': TOKEN}, headers={'Origin': origin})
                self.assertEqual(await good.json(), {'configured': True, 'repo': 'owner/frogdash-logs', 'last': None})
                self.assertEqual(json.loads((Path(folder) / 'log-upload.json').read_text())['token'], TOKEN)
                (Path(folder) / 'upload-status.json').write_text(json.dumps({'time': 5, 'state': 'done', 'message': 'Uploaded', 'sent': ['a']}))
                body = await (await client.get('/api/upload')).json()
                self.assertEqual(body['last'], {'time': 5, 'state': 'done', 'message': 'Uploaded'})
                self.assertNotIn(TOKEN, json.dumps(body))
                off = await client.post('/api/upload', json={'repo': 'owner/frogdash-logs', 'token': ''}, headers={'Origin': origin})
                self.assertFalse((await off.json())['configured'])
                self.assertFalse((Path(folder) / 'log-upload.json').exists())


if __name__ == '__main__':
    unittest.main()
