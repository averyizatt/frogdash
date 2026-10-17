"""Uploads after an update (tools/frogdash_upload.py and the phone page's Uploads section),
against a stand-in GitHub that records what it is sent."""
import gzip
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

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
        self.up.local = lambda path, method='GET', timeout=10: self.listing if path == '/logs' else None
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

    def test_reports_and_the_newest_drive_go_up_once(self):
        (self.state / 'log-upload.json').write_text(json.dumps({'repo': 'owner/frogdash', 'token': TOKEN}))
        (self.state / 'screen-status.json').write_text('{"state": "original"}')
        self.log('20261014T170000Z', 30, b'yesterday')
        first = self.log('20261015T120000Z', 30, b'drive part one' * 100)
        second = self.log('20261015T123200Z', 10, b'drive part two' * 100)
        hub = FakeGitHub()
        said = self.up.run(now=1792065600, github=hub, wait=lambda s: None)
        self.assertEqual(said, 'Uploaded the diagnostics and 2 recordings of the newest drive')
        self.assertEqual(sorted(p.rsplit('-', 1)[1] for p in hub.files), ['boot.txt', 'diagnostics.json', 'events.txt', 'journal.txt'])
        self.assertEqual(list(hub.files)[0].rsplit('-', 1)[1], 'events.txt')         # What went wrong, first
        diagnostics = json.loads(next(v for p, v in hub.files.items() if p.endswith('diagnostics.json')))
        self.assertEqual(diagnostics['helpers']['screen-status.json'], {'state': 'original'})
        self.assertEqual(diagnostics['gps']['gpspipe'], '(output of timeout)\n')   # What gpsd hears, raw
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
