import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.adapters import read_replay, replay
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.gps import GPS
from hardware.frogdash.adapters import CAN_FRAME, socketcan


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_gps_transmit_payload_and_duplicate_sender_latch(self):
        state = State()
        state.gps = GPS()
        state.gps.connected = True
        state.gps.update({'class': 'TPV', 'mode': 3, 'speed': 21, 'altMSL': -10})
        bus = MagicMock()
        bus.__enter__.return_value = bus
        loop = MagicMock()
        loop.time.side_effect = [0, 2.1, 2.1]
        loop.sock_sendall = AsyncMock()
        loop.sock_recv = AsyncMock(side_effect=[CAN_FRAME.pack(0x203, 8, bytes(8)), asyncio.CancelledError()])
        with patch('hardware.frogdash.adapters.socket.socket', return_value=bus), \
             patch.multiple('hardware.frogdash.adapters.socket', AF_CAN=29, CAN_RAW=1, SOL_CAN_RAW=101, create=True), \
             patch('hardware.frogdash.adapters.asyncio.get_running_loop', return_value=loop):
            with self.assertRaises(asyncio.CancelledError):
                await socketcan(state, 'can0')
        packet = loop.sock_sendall.call_args.args[1]
        self.assertEqual(CAN_FRAME.unpack(packet), (0x203, 8, bytes.fromhex('02F4FFF600031300')))
        self.assertEqual(loop.sock_sendall.await_count, 1)
        self.assertTrue(state.gps.conflict)
        self.assertIn('BLOCKED', state.gps.tx_status)

    async def test_gps_transmit_failure_keeps_reception_online(self):
        # Alone on the bus nothing ACKs, the TX queue fills and send fails; CAN must stay live.
        state = State()
        state.gps = GPS()
        state.gps.connected = True
        state.gps.update({'class': 'TPV', 'mode': 3, 'speed': 21, 'altMSL': -10})
        bus = MagicMock()
        bus.__enter__.return_value = bus
        loop = MagicMock()
        loop.time.side_effect = [0, 2.1, 2.1, 2.2]
        loop.sock_sendall = AsyncMock(side_effect=OSError(105, 'No buffer space available'))
        states = []
        async def receive(*_):
            states.append(state.connected)
            if len(states) == 2:
                raise asyncio.CancelledError()
            return CAN_FRAME.pack(0x202, 8, bytes.fromhex('0D7A000001010000'))
        loop.sock_recv = receive
        with patch('hardware.frogdash.adapters.socket.socket', return_value=bus),              patch.multiple('hardware.frogdash.adapters.socket', AF_CAN=29, CAN_RAW=1, SOL_CAN_RAW=101, create=True),              patch('hardware.frogdash.adapters.asyncio.get_running_loop', return_value=loop):
            with self.assertRaises(asyncio.CancelledError):
                await socketcan(state, 'can0')
        self.assertEqual(states, [True, True])
        self.assertEqual(bus.__enter__.call_count, 1)
        self.assertEqual((loop.sock_sendall.await_count, state.gps.tx_count), (1, 0))

    async def test_snapshot_staleness_reconnect_and_assets(self):
        state = State()
        state.connected = True
        state.ingest(0x202, bytes.fromhex('0D7A000001010000'))
        async with TestClient(TestServer(create_app(state))) as client:
            response = await client.get('/')
            html = await response.text()
            self.assertIn('Sensors &amp; connections', html)
            self.assertNotIn('sim-controls', html)
            ws = await client.ws_connect('/state')
            snapshot = await ws.receive_json()
            self.assertEqual(snapshot['values']['engine.rpm']['value'], 3450)
            await asyncio.sleep(.6)
            for _ in range(10):
                update = await ws.receive_json()
                if update['values']['engine.rpm']['quality'] == 'stale': break
            self.assertEqual(update['values']['engine.rpm']['quality'], 'stale')
            await ws.close()
            ws = await client.ws_connect('/state')
            self.assertIn('engine.rpm', (await ws.receive_json())['values'])
            await ws.close()
            self.assertEqual((await client.get('/health')).status, 200)
            self.assertEqual((await client.get('/raw')).status, 200)
            self.assertEqual((await client.get('/state', headers={'Origin': 'http://elsewhere.invalid'})).status, 403)
            self.assertEqual((await client.get('/secrets.env')).status, 404)

    async def test_replay_preserves_timing_and_stales_at_end(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.log'
            path.write_text('(1.0) can0 100#01010502804610\n(1.05) can0 100#01010000804610\n')
            frames = read_replay(path)
            state = State('replay')
            await replay(state, frames)
            self.assertEqual(state.received, 2)
            self.assertFalse(state.connected)
            self.assertEqual(state.snapshot()['values']['lighting.brake']['quality'], 'stale')
            path.write_text('(1.0) can0 100#0\n')
            with self.assertRaises(ValueError): read_replay(path)


if __name__ == '__main__':
    unittest.main()
