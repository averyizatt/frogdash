"""The dash's record of what went wrong (eventlog.py) and its GitHub link by code (github_link.py)."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from hardware.frogdash.eventlog import EventLog, HOLD_S, as_text, read
from hardware.frogdash.github_link import GitHubLink


class Clock:
    def __init__(self):
        self.now = 1792060000.0

    def __call__(self):
        return self.now


def snapshot(gps='fix', speed='live', connected=True, modules=None, rpm=None, ups=None):
    values = {'vehicle.speed_kph': {'value': 50 if speed == 'live' else None, 'quality': speed}}
    if rpm is not None:
        values['engine.rpm'] = {'value': rpm, 'quality': 'live'}
    return {'mode': 'socketcan', 'values': values, 'transport': {'connected': connected, 'status': 'can0 down' if not connected else 'ok'},
            'modules': modules or {'watermeth': 'live'}, 'recording': {'state': 'recording', 'error': None},
            'gps': {'status': 'GPS fix', 'diagnosis': {'state': gps, 'text': {'fix': 'Fix with 9 satellites', 'silent': 'No receiver is reporting'}.get(gps, gps)}},
            'system': {'ups': ups or {}}}


class EventLogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.log = EventLog(None, Path(self.folder.name) / 'events', wall=self.clock, clock=self.clock)

    def tearDown(self):
        self.folder.cleanup()

    def watch(self, seconds, **kwargs):
        for _ in range(int(seconds / 2)):
            self.log.watch(snapshot(**kwargs))
            self.clock.now += 2

    def texts(self):
        return [e['text'] for e in read(self.log.folder)]

    def test_how_things_stand_at_start_is_quiet_and_changes_are_written(self):
        self.watch(10, rpm=0)
        self.assertEqual(self.texts(), ['Engine stopped'])                 # Context, not a problem
        self.watch(10, rpm=900)
        self.watch(10, rpm=900, speed='unavailable')                         # The 0-speed signature
        self.watch(10, rpm=900, gps='silent', speed='unavailable')
        self.watch(10, rpm=900, connected=False, modules={'watermeth': 'stale'})
        self.assertEqual(self.texts(), ['Engine stopped', 'Engine started', 'GPS has a position but no speed',
                                        'No receiver is reporting', 'CAN bus lost: can0 down', 'Fix with 9 satellites'])
        levels = [e['level'] for e in read(self.log.folder)]
        self.assertEqual(levels[2:4], ['warn', 'error'])

    def test_a_blip_shorter_than_the_hold_is_not_written(self):
        self.watch(10)
        self.log.watch(snapshot(gps='silent'))
        self.clock.now += HOLD_S - 1
        self.watch(10)
        self.assertEqual(self.texts(), [])

    def test_a_module_going_quiet_is_written_but_not_when_the_whole_bus_is_down(self):
        self.watch(10)
        self.watch(10, modules={'watermeth': 'stale'})
        self.assertEqual(self.texts(), ['watermeth module not heard (stale)'])

    def test_restarts_fault_blips_module_faults_and_alerts_are_all_written(self):
        base = snapshot()
        self.log.watch(base)
        restart = {**base, 'gaps': [{'id': 0x300, 'module': 'water/meth', 'seconds': 2.4, 't': self.clock.now}],
                   'values': {**base['values'], 'meth.fault_flags': {'value': 0, 'raw': 3, 'quality': 'live'}},
                   'events': [{'id': 0x102, 'timestamp_ms': 5, 'data': '04020100', 'values': {'lighting.last_fault.code': 4}}],
                   'drive': {'alerts': [{'key': 'meth', 'title': 'WATER/METH FAULT', 'active': True,
                                         'context': {'meth.fault_flags': {'value': 3}, 'engine.rpm': {'value': 0}}}]}}
        self.log.watch(restart)
        self.log.watch(restart)                                               # Once each, not every look
        self.assertEqual(self.texts(), ['water/meth silent for 2.4 s (0x300), then back: a restart of the module, or a dropout',
                                        'meth faults reported: tank level low, no manifold pressure',
                                        'taillights: a light input was on at start-up', 'Alert shown: WATER/METH FAULT'])
        self.assertEqual(read(self.log.folder)[-1]['detail'], {'meth.fault_flags': 3})

    def test_each_taillight_start_is_written_once_in_words(self):
        base = snapshot()
        self.log.watch(base)
        start = {'id': 0x102, 'timestamp_ms': 1000, 'data': '08000101',
                 'values': {'lighting.last_fault.code': 8, 'lighting.last_fault.severity': 0,
                            'lighting.last_fault.data0': 1, 'lighting.last_fault.data1': 1}}
        again = {**start, 'timestamp_ms': 4000}                               # Sent again once the dash is heard
        dip = {'id': 0x102, 'timestamp_ms': 90000, 'data': '07010300',
               'values': {'lighting.last_fault.code': 7, 'lighting.last_fault.data0': 3}}
        self.log.watch({**base, 'events': [start]})
        self.log.watch({**base, 'events': [start, again]})
        self.log.watch({**base, 'events': [start, again, dip]})
        self.assertEqual(self.texts(), ['taillights started (power-on or reset button): after its restart on settled power',
                                        'taillights: restarted after a supply dip (brownout)'])

    def test_readable_text_and_reading_since(self):
        self.log.write('warn', 'gps', 'GPS has a position but no speed', {'status': 'GPS fix'})
        self.clock.now += 60
        self.log.write('info', 'engine', 'Engine stopped')
        entries = read(self.log.folder)
        self.assertEqual(as_text(entries).splitlines()[0],
                         '2026-10-15 10:26:40 UTC  WARN   gps      GPS has a position but no speed  {"status":"GPS fix"}')
        self.assertEqual([e['text'] for e in read(self.log.folder, since=entries[0]['t'])], ['Engine stopped'])


class GitHubLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_code_then_authorize_saves_the_access_for_the_uploader(self):
        with tempfile.TemporaryDirectory() as folder:
            answers = [{'error': 'authorization_pending'}, {'error': 'slow_down', 'interval': 0}, {'access_token': 'gho_abc'}]
            asked = []

            def post(url, fields):
                asked.append((url.rsplit('/', 1)[1], fields.get('client_id')))
                if url.endswith('/device/code'):
                    return {'device_code': 'd', 'user_code': 'ABCD-1234', 'verification_uri': 'https://github.com/login/device', 'expires_in': 900, 'interval': 0}
                return answers.pop(0)
            link = GitHubLink(folder, client_id='Ov23test', post=post, user=lambda token: {'login': 'averyizatt'}, sleep=lambda s: asyncio.sleep(0))
            self.assertEqual((await link.connect())['code'], 'ABCD-1234')
            await link.task
            status = link.status()
            self.assertEqual((status['configured'], status['repo'], status['account'], status['link']['state']),
                             (True, 'averyizatt/frogdash', 'averyizatt', 'connected'))
            self.assertEqual(json.loads((Path(folder) / 'log-upload.json').read_text())['token'], 'gho_abc')
            self.assertEqual({c for _, c in asked}, {'Ov23test'})
            # The reports waiting on the Pi go at once, not at the next update.
            self.assertEqual((Path(folder) / 'update-request').read_text(), 'upload')
            self.assertIn('sending the reports now', status['link']['message'])
            self.assertTrue(status['sending'])
            link.disconnect()
            self.assertFalse(link.status()['configured'])

    def test_send_now_asks_the_updater_and_never_replaces_an_update_request(self):
        with tempfile.TemporaryDirectory() as folder:
            link = GitHubLink(folder, client_id='Ov23test')
            self.assertEqual(link.send_now(), 'Connect GitHub first')
            (Path(folder) / 'log-upload.json').write_text(json.dumps({'repo': 'averyizatt/frogdash', 'token': 'gho_abc'}))
            (Path(folder) / 'update-request').write_text('requested')
            self.assertEqual(link.send_now(), 'An update is about to run: it sends the reports too')
            self.assertEqual((Path(folder) / 'update-request').read_text(), 'requested')
            (Path(folder) / 'update-request').unlink()
            self.assertIsNone(link.send_now())
            self.assertEqual((Path(folder) / 'update-request').read_text(), 'upload')
            self.assertTrue(link.status()['sending'])

    def test_the_reports_waiting_come_from_the_uploaders_count_not_its_root_only_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'upload-status.json').write_text(json.dumps({'state': 'held', 'held': 3, 'message': 'kept', 'sent': ['x']}))
            link = GitHubLink(folder, client_id='Ov23test')
            original = Path.iterdir
            def refuse(path):
                if path.name == 'reports':
                    raise PermissionError(13, 'Permission denied')
                return original(path)
            Path.iterdir = refuse
            try:
                (Path(folder) / 'reports').mkdir()
                status = link.status()
            finally:
                Path.iterdir = original
            self.assertEqual((status['held'], status['last']), (3, {'state': 'held', 'message': 'kept'}))

    async def test_declined_or_no_app_id_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            link = GitHubLink(folder, client_id='')
            self.assertFalse(link.status()['ready'])
            with self.assertRaises(ValueError):
                await link.connect()

            def post(url, fields):
                return {'device_code': 'd', 'user_code': 'X', 'interval': 0} if url.endswith('/device/code') else {'error': 'access_denied'}
            link = GitHubLink(folder, client_id='Ov23test', post=post, sleep=lambda s: asyncio.sleep(0))
            await link.connect()
            await link.task
            self.assertEqual(link.status()['link'], {'state': 'failed', 'message': 'Authorize was declined on GitHub'})
            self.assertFalse(link.status()['configured'])


if __name__ == '__main__':
    unittest.main()
