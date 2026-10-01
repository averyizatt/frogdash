import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from hardware.frogdash.adapters import CAN_FRAME, socketcan
from hardware.frogdash.runtime import EngineRuntime
from hardware.frogdash.state import State


class Clock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now


class EngineRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.state = State(clock=self.clock)
        self.state.connected = True
        self.runtime = self.state.runtime

    def test_matches_ccm_payload_and_prefers_fresh_rpm(self):
        self.assertEqual(self.runtime.frame(), bytes([0, 0, 0, 0]))  # No RPM: zero, not valid.
        self.state.ingest(0x500, bytes([0, 0, 0x0B, 0xB8, 0, 0, 255, 2]))  # Gateway 3000 rpm.
        self.assertEqual(self.runtime.frame(), bytes([0xB8, 0x0B, 0, 1]))
        self.state.ingest(0x5F0, bytes([0, 1, 0, 0, 0, 0, 0x0F, 0xA0]))  # MicroSquirt group 0: 4000 rpm.
        self.assertEqual(self.runtime.frame(), bytes([0xA0, 0x0F, 0, 1]))
        self.clock.now += 1  # Both stale: report zero, not the last value.
        self.assertEqual(self.runtime.frame(), bytes([0, 0, 0, 0]))

    def test_listens_first_then_paces_and_latches_on_conflict(self):
        self.assertFalse(self.runtime.due(0.0))
        self.assertFalse(self.runtime.due(1.9))
        self.assertTrue(self.runtime.due(2.0))
        self.assertFalse(self.runtime.due(2.03))
        self.assertTrue(self.runtime.due(2.05))
        self.runtime.observe(0x309)
        self.assertTrue(self.runtime.conflict)
        self.assertFalse(self.runtime.due(10.0))
        self.assertIn('BLOCKED', self.runtime.snapshot()['status'])

    def test_disabled_never_sends_and_comfort_follows_gateway(self):
        self.assertFalse(EngineRuntime(self.state, enabled=False).due(5.0))
        self.state.ingest(0x501, bytes([0, 0, 0, 1]))
        self.assertEqual(self.state.snapshot()['modules']['comfort'], 'live')


class EngineRuntimeSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_published_on_the_bus_and_send_failure_is_harmless(self):
        state = State()
        bus = MagicMock()
        bus.__enter__.return_value = bus
        loop = MagicMock()
        ticks = iter([0, 0.5, 1.0])
        clock = [2.0]
        def time():
            value = next(ticks, None)
            if value is None:
                clock[0] += .06; value = clock[0]
            return value
        loop.time.side_effect = time
        loop.sock_sendall = AsyncMock(side_effect=[OSError(105, 'No buffer space available')] + [None] * 200)
        calls = []
        async def receive(*_):
            calls.append(1)
            if len(calls) > 80:
                raise asyncio.CancelledError()
            raise TimeoutError()
        loop.sock_recv = receive
        with patch('hardware.frogdash.adapters.socket.socket', return_value=bus), \
             patch.multiple('hardware.frogdash.adapters.socket', AF_CAN=29, CAN_RAW=1, SOL_CAN_RAW=101, create=True), \
             patch('hardware.frogdash.adapters.asyncio.get_running_loop', return_value=loop):
            with self.assertRaises(asyncio.CancelledError):
                await socketcan(state, 'can0')
        ids = [CAN_FRAME.unpack(call.args[1])[0] for call in loop.sock_sendall.call_args_list]
        self.assertGreaterEqual(len(ids), 2)
        self.assertEqual(set(ids), {0x309})
        self.assertEqual(state.runtime.tx_count, len(ids) - 1)  # First send failed without dropping the socket.
        self.assertEqual(bus.__enter__.call_count, 1)


if __name__ == '__main__':
    unittest.main()
