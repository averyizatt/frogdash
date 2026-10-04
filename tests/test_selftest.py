import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash import selftest
from hardware.frogdash.paint import Paint
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State


class Health:
    status = {'can_module': {'present': True, 'up': True, 'spi': 'spi0.0'},
              'can': {'state': 'ERROR-ACTIVE', 'bitrate': 500000, 'error_counters': {'tx': 0, 'rx': 0}},
              'power': {'undervoltage_now': False, 'undervoltage_since_boot': True}, 'cpu_c': 52.0,
              'disk': {'free_bytes': 10 * 2 ** 30, 'total_bytes': 32 * 2 ** 30}}


class SelfTestTests(unittest.TestCase):
    def find(self, report, name):
        return next(item for item in report['lines'] if item['name'] == name)

    def test_empty_bus_fails_with_fixes_and_healthy_parts_pass(self):
        state = State()
        state.connected = True
        state.health = Health()
        report = selftest.report(state, None, wall=lambda: 1790000000)
        self.assertEqual(self.find(report, 'CAN module (MCP2515)')['status'], 'ok')
        self.assertEqual(self.find(report, 'Bus health')['status'], 'ok')
        self.assertEqual(self.find(report, 'Water/meth')['status'], 'fail')
        self.assertTrue(self.find(report, 'Water/meth')['fix'])
        self.assertEqual(self.find(report, 'Power supply')['status'], 'warn')
        self.assertEqual(self.find(report, 'Reverse camera')['status'], 'skip')
        self.assertEqual(self.find(report, 'Clock')['status'], 'ok')
        self.assertEqual(sum(report['counts'].values()), len(report['lines']))

    def test_module_fault_and_ok_are_reported(self):
        state = State()
        state.connected = True
        state.ingest(0x300, bytes([0, 0, 0, 0, 0, 60, 60, 1]))
        state.ingest(0x501, bytes([0, 31, 0, 1]))
        state.ingest(0x500, bytes(6) + bytes([50, 4]))
        state.ingest(0x202, bytes.fromhex('0BB8000001010000'))
        state.ingest(0x503, bytes.fromhex('01000000000100'))
        report = selftest.report(state)
        meth = self.find(report, 'Water/meth')
        self.assertEqual(meth['status'], 'warn')
        self.assertIn('Tank low', meth['detail'])
        self.assertEqual(self.find(report, 'Comfort gateway')['status'], 'ok')
        self.assertEqual(self.find(report, 'Clock')['fix'] == '', self.find(report, 'Clock')['status'] == 'ok')


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_records_and_downloads_candump_format(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State()
            state.connected = True
            state.paint = Paint(Path(folder) / 'appearance-paint.json')
            async with TestClient(TestServer(create_app(state))) as client:
                self.assertFalse((await (await client.get('/can/capture')).json())['available'])
                self.assertEqual((await client.post('/can/capture', json={'seconds': 5})).status, 200)
                state.ingest(0x300, bytes([0, 0, 85, 1, 20, 60, 70, 0]))
                state.ingest(0x18FF0001, bytes([1, 2]), extended=True)
                status = await (await client.get('/can/capture')).json()
                self.assertEqual((status['frames'], status['recording']), (2, True))
                text = await (await client.get('/can/capture?download=1')).text()
                self.assertRegex(text, r'\(\d+\.\d{6}\) can0 300#0000550114 ?3C4600')
                self.assertIn('can0 18FF0001#0102', text)
                self.assertEqual((await client.get('/selftest')).status, 200)


if __name__ == '__main__':
    unittest.main()
