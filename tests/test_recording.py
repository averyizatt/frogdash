import asyncio
import io
import math
from pathlib import Path
import struct
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.log_channels import CHANNELS, FIELDS, row_values
from hardware.frogdash.mlg import Encoder, Field
from hardware.frogdash.recorder import Config, Recorder, RotatingWriter, inventory
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from tools.inspect_mlg import Reader


def snapshot():
    state = State()
    state.connected = True
    for can_id, data in [(0x5E8, '07080D7A080201F4'), (0x5EA, '937C03E800000000'),
                         (0x300, '0100640155505000'), (0x303, '7C4E00003C410000')]:
        state.ingest(can_id, bytes.fromhex(data))
    return state.snapshot()


def read(path):
    with path.open('rb') as stream:
        return list(Reader(stream).records())


class MLGTests(unittest.TestCase):
    def test_documented_wire_vector_and_256_counter_wrap(self):
        encoder = Encoder([Field('Time', 's')], 0)
        self.assertEqual(encoder.header[:24], struct.pack('>6sHIIIHH', b'MLVLG\0', 2, 0, 113, 122, 4, 1))
        self.assertEqual(encoder.row(1, [1]), bytes.fromhex('000086a03f800000bf'))
        encoder.counter = 255
        self.assertEqual(encoder.row(2, [2])[1], 255)
        self.assertEqual(encoder.row(3, [3])[1], 0)

    def test_independent_reader_time_wraps_units_and_quality(self):
        snap = snapshot()
        snap['values']['engine.coolant_c'] = {'quality': 'live', 'value': 100}
        snap['values']['gps.latitude'] = {'quality': 'stale', 'value': 40.123456}
        snap['values']['engine.oil_pressure_psi'] = {'quality': 'fault', 'value': 62}
        encoder = Encoder(FIELDS, 1234567890)
        data = encoder.header + b''.join(encoder.row(t, row_values(snap, t, 7)) for t in (0, .65, .7, 7200.25))
        reader = Reader(io.BytesIO(data))
        rows = list(reader.records())
        values = rows[-1]['values']
        self.assertEqual(values['Time'], 7200.25)
        self.assertEqual(values['RPM'], 3450)
        self.assertEqual(values['CLT'], 212)
        self.assertAlmostEqual(values['AFR'], 12.4, places=4)
        self.assertEqual(values['meth.state'], 1)
        self.assertEqual(values['Q meth.state'], 1)
        self.assertTrue(math.isnan(values['Latitude']))
        self.assertEqual(values['Q Latitude'], 2)
        self.assertTrue(math.isnan(values['OilPressure']))
        self.assertEqual(values['Q OilPressure'], 3)
        self.assertTrue(math.isnan(values['vehicle.fuel_pct']))
        self.assertEqual(values['Q vehicle.fuel_pct'], 0)
        self.assertEqual(values['Dropped samples'], 7)
        self.assertEqual(rows[2]['timestamp'], 70000 % 65536)
        self.assertEqual(reader.version, 2)
        self.assertEqual(len(reader.fields), len(CHANNELS) * 2 + 3)

    def test_reader_rejects_corruption_and_recovers_only_incomplete_tail(self):
        encoder = Encoder([Field('Time')], 1)
        good = encoder.header + encoder.row(0, [0])
        bad = good[:-1] + b'\xff'
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            list(Reader(io.BytesIO(bad)).records())
        with self.assertRaisesRegex(ValueError, 'Truncated record'):
            list(Reader(io.BytesIO(good[:-1])).records())
        recover = Reader(io.BytesIO(good + encoder.row(1, [1])[:-1]), allow_truncated=True)
        self.assertEqual(len(list(recover.records())), 1)
        self.assertTrue(recover.truncated)

    def test_validates_names_types_and_schema(self):
        with self.assertRaises(ValueError): Encoder([Field('x' * 34)], 0)
        with self.assertRaises(ValueError): Encoder([Field('x'), Field('x')], 0)
        with self.assertRaises(ValueError): Encoder([Field('x', kind=99)], 0)
        self.assertEqual(len({f.name for f in FIELDS}), len(FIELDS))
        sample = snapshot()
        self.assertFalse(set(sample['values']) - {c.key for c in CHANNELS})


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def config(self, **kwargs):
        return Config(self.path, free_bytes=0, **kwargs)

    def test_rotates_duration_and_restart_never_overwrites(self):
        config = self.config(seconds=1)
        writer = RotatingWriter(config)
        self.addCleanup(writer.close)
        snap = snapshot()
        for stamp in (0, .5, 1, 1.5): writer.write(snap, stamp)
        writer.close()
        files = inventory(self.path)
        self.assertEqual(len(files), 2)
        for path, _, _ in files:
            self.assertEqual([r['values']['Time'] for r in read(path)], [0, .5])
        again = RotatingWriter(config)
        self.addCleanup(again.close)
        again.write(snap, 0)
        again.close()
        self.assertEqual(len(inventory(self.path)), 3)

    def test_size_rotation_retention_and_foreign_files(self):
        config = self.config(file_bytes=65536, total_bytes=131072)
        unrelated = self.path / 'tunerstudio-original.mlg'
        unrelated.write_bytes(b'preserve this')
        writer = RotatingWriter(config)
        self.addCleanup(writer.close)
        snap = snapshot()
        for i in range(180): writer.write(snap, i / 20)
        active = writer.path
        writer.close()
        files = inventory(self.path)
        self.assertLessEqual(sum(size for _, size, _ in files), config.total_bytes)
        self.assertTrue(active.exists())
        self.assertGreater(len(files), 1)
        self.assertEqual(unrelated.read_bytes(), b'preserve this')
        for path, size, _ in files:
            self.assertLessEqual(size, config.file_bytes)
            self.assertTrue(read(path))

    def test_free_space_reserve_and_exclusive_directory_lock(self):
        writer = RotatingWriter(self.config(), disk_usage=lambda _: SimpleNamespace(free=1))
        self.addCleanup(writer.close)
        with self.assertRaises(OSError): writer.write(snapshot(), 0)
        self.assertFalse(inventory(self.path))
        second = RotatingWriter(self.config())
        self.addCleanup(second.close)
        with self.assertRaisesRegex(OSError, 'Another recorder'):
            second.write(snapshot(), 0)
        writer.close()
        second.write(snapshot(), 0)
        self.assertTrue(second.path.exists())

    def test_invalid_storage_and_rate_config(self):
        for options in ({'hz': 0}, {'hz': math.nan}, {'seconds': math.inf}, {'file_bytes': 1}, {'total_bytes': 1}):
            with self.assertRaises(ValueError): self.config(**options)


class RecorderServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_without_browser_and_download_only_closed_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State()
            state.connected = True
            state.recorder = Recorder(state, Config(Path(directory), seconds=.15, free_bytes=0))
            async with TestClient(TestServer(create_app(state))) as client:
                await asyncio.sleep(.4)
                listing = await (await client.get('/logs')).json()
                self.assertGreater(listing['recording']['rows'], 2)
                files = listing['files']
                completed = next(f for f in files if not f['active'])
                response = await client.get('/logs/' + completed['name'])
                self.assertEqual(response.status, 200)
                self.assertTrue(list(Reader(io.BytesIO(await response.read())).records()))
                # Stop rotation briefly so the currently active-file check is deterministic.
                object.__setattr__(state.recorder.config, 'seconds', 100)
                active = state.recorder.writer.path.name
                self.assertEqual((await client.get('/logs/' + active)).status, 409)
                self.assertEqual((await client.get('/logs/unrelated.mlg')).status, 404)
                self.assertEqual((await (await client.get('/health')).json())['recording']['state'], 'recording')
            self.assertEqual(state.recorder.status['state'], 'stopped')
            self.assertTrue(all(read(path) for path, _, _ in inventory(Path(directory))))

    async def test_storage_failure_does_not_stop_telemetry(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State()
            rec = Recorder(state, Config(Path(directory), free_bytes=0))
            state.recorder = rec
            with patch.object(rec.writer, 'write', side_effect=OSError('disk full')), self.assertLogs('hardware.frogdash.recorder', level='ERROR'):
                rec.start()
                await asyncio.sleep(.12)
                state.connected = True
                state.ingest(0x202, bytes.fromhex('0D7A000001010000'))
                self.assertEqual(state.snapshot()['values']['engine.rpm']['value'], 3450)
                self.assertEqual(rec.status['state'], 'error')
                self.assertIn('disk full', rec.status['error'])
                self.assertGreater(rec.dropped, 0)
                await rec.close()

    async def test_slow_disk_is_bounded_and_does_not_block_event_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            state = State()
            rec = Recorder(state, Config(Path(directory), hz=100, free_bytes=0))
            rec.queue = asyncio.Queue(maxsize=1)
            original = rec.writer.write
            def slow_write(*args):
                time.sleep(.06)
                original(*args)
            with patch.object(rec.writer, 'write', side_effect=slow_write):
                rec.start()
                beats = 0
                until = time.monotonic() + .25
                while time.monotonic() < until:
                    beats += 1
                    await asyncio.sleep(.005)
                await rec.close()
            # Windows timer resolution can be ~16 ms; synchronous disk writes
            # would permit at most four beats in this interval.
            self.assertGreater(beats, 6)
            self.assertGreater(rec.dropped, 0)
            self.assertGreater(rec.written, 0)
            rows = read(inventory(Path(directory))[0][0])
            self.assertGreater(rows[-1]['values']['Dropped samples'], 0)


if __name__ == '__main__':
    unittest.main()
