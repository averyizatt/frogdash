"""The dash starts on a Pi that does not have a newly added Python package yet.

The updater moves the code on with git and restarts the dash; a package added to
requirements.lock is installed by the Pi setup only after the new version has started
(tools/frogdash_setup.sh, "Python packages"). In October 2026 the dash imported pyubx2
at start, could not start on the Pi, and the screen stayed black. So every package added
since the Pi was first set up must be optional at import, and this test starts the dash
with them blocked. A package added later goes in NEW_PACKAGES too.
"""
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
NEW_PACKAGES = ('pyubx2', 'pynmeagps', 'pyrtcm')   # Not on a Pi set up before October 2026

CHILD = textwrap.dedent('''
    import asyncio, json, sys
    BLOCKED = set(sys.argv[1].split(','))
    class Block:
        def find_spec(self, name, path=None, target=None):
            if name.split('.')[0] in BLOCKED:
                raise ModuleNotFoundError(f"No module named '{name}'")
    sys.meta_path.insert(0, Block())
    from aiohttp.test_utils import TestClient, TestServer
    from hardware.frogdash import gpsaid
    from hardware.frogdash.server import create_app
    from hardware.frogdash.state import State

    async def main():
        async with TestClient(TestServer(create_app(State()))) as client:
            health = (await client.get('/health')).status
            page = (await client.get('/')).status
        payload = bytes.fromhex(sys.argv[2])
        report = gpsaid.hardware_report(payload, 0.0)
        print(json.dumps({'health': health, 'page': page, 'pyubx2': gpsaid.UBXMessage is not None,
                          'initial': gpsaid.initial(39.0639, -108.5506, None, wall=1792065600).hex(),
                          'radio': report,
                          'frames': [list(f[:2]) for f in gpsaid.frames_in(bytes.fromhex(sys.argv[3]))]}))
    asyncio.run(main())
''')


class StartsWithoutNewPackagesTests(unittest.TestCase):
    def test_the_dash_starts_and_the_gps_code_works_without_them(self):
        from pyubx2 import GET, UBXMessage
        from hardware.frogdash import gpsaid
        radio = UBXMessage('MON', 'MON-HW', GET, jammingState=2, jamInd=150, aStatus=4, noisePerMS=91, agcCnt=5000).serialize()
        mixed = b'noise' + radio + gpsaid.initial(39.0, -108.5)
        done = subprocess.run([sys.executable, '-c', CHILD, ','.join(NEW_PACKAGES), radio[6:-2].hex(), mixed.hex()],
                              cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        child = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertFalse(child['pyubx2'])                          # Really without it
        self.assertEqual((child['health'], child['page']), (200, 200))
        # Without pyubx2 the same bytes and the same readings as with it.
        self.assertEqual(child['initial'], gpsaid.initial(39.0639, -108.5506, None, wall=1792065600).hex())
        self.assertEqual(child['radio'], gpsaid.hardware_report(radio[6:-2], 0.0))
        self.assertEqual(child['radio']['jamming'], 'warning')
        self.assertEqual(child['frames'], [[0x0A, 0x09], [0x0B, 0x01]])


if __name__ == '__main__':
    unittest.main()
