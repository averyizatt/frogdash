"""The Log viewer's reader (hardware/frogdash/logview.py) and its routes, against MLG logs
written by the dash's own encoder."""
import asyncio
import math
from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.logview import Log, LogCache
from hardware.frogdash.mlg import Encoder, Field
from hardware.frogdash.recorder import Config, Recorder
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

FIELDS = [Field('Time', 's', 'Time', digits=3), Field('RPM', 'RPM', 'engine', digits=0),
          Field('Q RPM', category='Quality', kind=0, digits=0),
          Field('TPS', '%', 'engine', kind=0, digits=1, scale=0.5)]


def write_log(path, rows, marker_at=None, partial=False):
    """`rows` of (time, rpm, quality, raw tps); a marker block before row `marker_at`."""
    encoder = Encoder(FIELDS, 1793900000)
    blob = bytearray(encoder.header)
    for index, (t, rpm, quality, tps) in enumerate(rows):
        if index == marker_at:
            blob += bytes([1, 0, 0, 0]) + b'Bookmark'.ljust(50, b'\0')
        blob += encoder.row(t, (t, rpm, quality, tps))
    if partial:
        blob += encoder.row(99, (99, 1, 1, 1))[:7]          # A block still being written
    Path(path).write_bytes(blob)


class LogReaderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)          # After each log is closed (cleanups run last first)
        self.path = Path(self.folder.name) / 'frogdash-live-20261105T221000Z-a1b2c3d4e5f6.mlg'

    def test_channels_markers_values_and_gaps(self):
        rows = [(i * .05, 800 + i * 10, 1, i % 200) for i in range(400)]
        rows[100] = (rows[100][0], math.nan, 0, 4)                # No live RPM: a gap, not a zero
        write_log(self.path, rows, marker_at=200, partial=True)
        log = Log(self.path)
        self.addCleanup(log.close)
        info = log.describe()
        self.assertEqual([c['name'] for c in info['channels']], ['RPM', 'TPS'])   # Not Time or the quality flags
        self.assertEqual((info['rows'], info['duration_s']), (400, 19.95))
        self.assertEqual(info['markers'], [{'t': 10.0, 'text': 'Bookmark'}])
        data = log.series(['RPM', 'TPS'], 5, 5.2)
        self.assertFalse(data['thinned'])
        self.assertEqual(data['t'][0], 4.95)                         # One beyond each edge
        self.assertIn(None, data['series']['RPM'])                  # Row 100, at 5.0 s
        self.assertEqual(data['series']['TPS'][:3], [49.5, 2.0, 50.5])   # Scaled: raw 99, 4, 101 at 0.5
        self.assertEqual(log.stats(['RPM'], 0, 1)['RPM'], {'min': 800.0, 'avg': 900.0, 'max': 1000.0, 'min_t': 0.0, 'max_t': 1.0})   # Both ends included

    def test_whole_rows_every_nth_for_a_scatter_plot(self):
        rows = [(i * .05, 1000 + i, 1, i % 200) for i in range(1000)]
        write_log(self.path, rows)
        log = Log(self.path)
        self.addCleanup(log.close)
        data = log.samples(['RPM', 'TPS'], points=100)
        self.assertEqual((data['step'], len(data['t'])), (10, 100))
        # The same rows for each channel: RPM and TPS at row 30 are 1030 and 30 * 0.5.
        self.assertEqual((data['t'][3], data['series']['RPM'][3], data['series']['TPS'][3]), (1.5, 1030.0, 15.0))
        self.assertEqual(len(log.samples(['RPM'], 10, 12)['t']), 41)           # Short: every row
        self.assertEqual(log.stats(['TPS'])['TPS']['max_t'], 9.95)             # Raw 199 first at row 199

    def test_a_long_log_is_thinned_and_keeps_its_spike(self):
        rows = [(i * .05, 3000.0, 1, 0) for i in range(20000)]
        rows[12345] = (rows[12345][0], 7400.0, 1, 0)             # One sample at the limiter
        write_log(self.path, rows)
        log = Log(self.path)
        self.addCleanup(log.close)
        data = log.series(['RPM'], points=500)
        self.assertTrue(data['thinned'])
        self.assertLessEqual(len(data['t']), 500)
        self.assertEqual(max(data['series']['RPM']), 7400.0)

    def test_a_log_still_being_written_is_read_again_when_it_grows(self):
        cache = LogCache()
        self.addCleanup(cache.close)
        write_log(self.path, [(i * .05, 900, 1, 0) for i in range(10)])
        self.assertEqual(cache.open(self.path).rows, 10)
        encoder = Encoder(FIELDS, 1793900000)
        with self.path.open('ab') as stream:                     # The recorder appends
            for i in range(10, 30):
                stream.write(encoder.row(i * .05, (i * .05, 900, 1, 0)))
        self.assertEqual(cache.open(self.path).rows, 30)

    def test_each_b_press_is_a_mark_from_the_bookmark_id_channel(self):
        fields = [Field('Time', 's', 'Time', digits=3), Field('Bookmark ID', '', 'dash', kind=4, digits=0)]
        encoder = Encoder(fields, 1793900000)
        ids = [2] * 50 + [3] * 50 + [3] * 50 + [4] * 50          # 2 was pressed before this log began
        self.path.write_bytes(encoder.header + b''.join(encoder.row(i * .1, (i * .1, n)) for i, n in enumerate(ids)))
        log = Log(self.path)
        self.addCleanup(log.close)
        self.assertEqual(log.describe()['markers'], [{'t': 5.0, 'text': 'Bookmark 3'}, {'t': 15.0, 'text': 'Bookmark 4'}])

    def test_not_a_log(self):
        self.path.write_bytes(b'hello')
        with self.assertRaises(ValueError):
            Log(self.path)


class LogViewRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_screen_reads_a_log_and_its_bookmarks(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State()
            state.recorder = Recorder(state, Config(Path(directory), free_bytes=0))
            name = 'frogdash-live-20261105T221000Z-a1b2c3d4e5f6.mlg'
            write_log(Path(directory) / name, [(i * .05, 900 + i, 1, 0) for i in range(100)])
            state.driving.finished.append({'name': 'drive', 'events': [{'id': 3, 'label': 'Bookmark', 'kind': 'bookmark',
                                                                        'log': {'name': name, 'time_s': 2.5}}]})
            async with TestClient(TestServer(create_app(state))) as client:
                info = await (await client.get(f'/logs/{name}/view')).json()
                self.assertEqual(info['events'], [{'t': 2.5, 'label': 'Bookmark', 'kind': 'bookmark'}])
                data = await (await client.get(f'/logs/{name}/series?channels=RPM&start=1&end=2')).json()
                self.assertEqual(data['stats']['RPM']['max'], 940.0)
                rows = await (await client.get(f'/logs/{name}/series?channels=RPM&mode=sample&points=10')).json()
                self.assertEqual((rows['step'], rows['series']['RPM'][1]), (10, 910.0))
                self.assertEqual((await client.get('/logs/other.mlg/view')).status, 404)
                self.assertEqual((await client.get(f'/logs/{name}/series?start=x')).status, 400)
                self.assertEqual((await client.get(f'/logs/{name}/series?channels=Nope')).status, 422)
            await asyncio.sleep(0)


if __name__ == '__main__':
    unittest.main()
