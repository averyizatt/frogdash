"""Recorded CustomTaillights frames: complete, consistent with their index, and served locally."""
import json
import unittest
import zlib
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

FOLDER = Path(__file__).resolve().parents[1] / 'hardware' / 'ui' / 'taillights'


class TaillightFrameTests(unittest.IsolatedAsyncioTestCase):
    def test_recordings_match_their_index(self):
        meta = json.loads((FOLDER / 'frames.json').read_text(encoding='utf-8'))
        data = zlib.decompress((FOLDER / 'frames.bin').read_bytes())
        clips = {clip['name']: clip for clip in meta['clips']}
        self.assertEqual(meta['lamp_bytes'], 590)  # 105 RGB top-strip LEDs + 275 red-lens LEDs.
        self.assertEqual([clips[f'show-{i}']['title'] for i in (0, 5, 30, 32)], ['Rainbow', 'Police', 'Radar', 'Glitch'])
        self.assertEqual(sum(1 for c in meta['clips'] if c['group'] == 'show'), 33)
        for name in ('running', 'brake', 'reverse', 'off', 'turn-left-seq', 'turn-right-stock', 'hazard-seq', 'brake-turn-left-seq'):
            self.assertIn(name, clips)
        end = max(c['offset'] + c['frames'] * 2 * 590 for c in meta['clips'])
        self.assertEqual(end, len(data))
        brake = data[clips['brake']['offset']:][:590]
        self.assertEqual(brake[315:], bytes([255]) * 275)  # Brake fills every red-lens LED.
        self.assertEqual(meta['source']['repository'], 'averyizatt/CustomTaillights')

    async def test_frames_are_served_and_other_names_refused(self):
        client = TestClient(TestServer(create_app(State()), host='127.0.0.1'))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        for name in ('frames.json', 'frames.bin'):
            response = await client.get(f'/taillights/{name}')
            self.assertEqual(response.status, 200, name)
            self.assertEqual(await response.read(), (FOLDER / name).read_bytes())
        for name in ('../server.py', 'other.bin', '%2E%2E%2Findex.html'):
            self.assertEqual((await client.get(f'/taillights/{name}')).status, 404, name)


if __name__ == '__main__':
    unittest.main()
