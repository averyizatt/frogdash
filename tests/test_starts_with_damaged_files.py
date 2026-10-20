"""The dash starts whatever state its saved files are in.

A power cut while a file is written, or a full SD card, can leave a file empty, cut
short or holding something else. A file the dash cannot read must never stop it from
starting: on the Pi that is a black screen on every boot, which no going back to an
earlier version would cure. Here the real start-up (python -m hardware.frogdash.server,
as the Pi runs it) is given every file it keeps, damaged several ways, and must answer
on /health and serve the screen.
"""
import json
import os
import shutil
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FILES = ['alerts.json', 'appearance-paint.json', 'can-status.json', 'dashcam.json', 'gps-aid.json', 'gps-status.json',
         'hotspot-resume.json', 'interior.json', 'last-drive.json', 'log-upload.json', 'meth-arm.json', 'meth-presets.json',
         'nav.json', 'operations.json', 'restore-pending.json', 'screen-status.json', 'setup-status.json', 'shutdown.json',
         'trip.json', 'update-status.json', 'upload-status.json', 'wifi-request.json', 'wifi-status.json', 'race.json',
         'frogdash-race-results.json', 'events/2026-10-20.jsonl', 'firmware/gateway.json', 'firmware/taillights.json',
         'firmware/watermeth.json', 'firmware/gateway.bin']
DAMAGE = {
    'garbage': b'\x00\xff{"cut short',
    'empty': b'',
    'a list': b'[1, 2, 3]',
    'null': b'null',
    'a string': b'"hello"',
    'wrong fields': json.dumps({'version': 'x', 'state': 5, 'value': [None], 'frames': 'nope', 'saved': 'yesterday',
                                'repo': 7, 'token': None, 'files': 3}).encode(),
}


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class DamagedFilesTests(unittest.TestCase):
    def start(self, folder):
        """(health status, page status), or the end of the dash's output when it did not start."""
        port = free_port()
        output = Path(tempfile.mkdtemp()) / 'dash.log'   # Outside the data folder: it may be read-only
        self.addCleanup(shutil.rmtree, output.parent, True)
        with open(output, 'wb') as log:
            process = subprocess.Popen([sys.executable, '-m', 'hardware.frogdash.server', '--interface', 'can0', '--gpsd',
                                        '--log-dir', str(folder / 'logs'), '--data-dir', str(folder),
                                        '--race-file', str(folder / 'race.json'), '--port', str(port)],
                                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, 'PYTHONUNBUFFERED': '1'})
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as answer:
                            health = answer.status
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=5) as answer:
                            return health, answer.status
                    except OSError:
                        time.sleep(.5)
            finally:
                if os.name == 'nt':   # A Windows venv's python.exe starts the real one as a child
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True)
                process.kill()
                process.wait(10)
        return output.read_text(errors='replace')[-3000:]

    def test_it_starts_with_every_file_damaged_in_every_way(self):
        for kind, body in DAMAGE.items():
            with self.subTest(kind), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
                folder = Path(directory)
                for name in FILES:
                    (folder / name).parent.mkdir(parents=True, exist_ok=True)
                    (folder / name).write_bytes(body)
                self.assertEqual(self.start(folder), (200, 200), kind)

    @unittest.skipIf(os.name == 'nt' or hasattr(os, 'geteuid') and os.geteuid() == 0, 'needs Linux permissions, not root')
    def test_it_starts_when_nothing_can_be_written(self):
        # A full SD card, or a folder left read-only: the screen still comes up.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            folder = Path(directory) / 'data'
            (folder / 'logs').mkdir(parents=True)
            (folder / 'trip.json').write_text('{"odometer_km": 5}')
            for path in (folder / 'logs', folder):
                path.chmod(0o555)
            try:
                result = self.start(folder)
            finally:
                for path in (folder, folder / 'logs'):
                    path.chmod(0o755)
            self.assertEqual(result, (200, 200))


if __name__ == '__main__':
    unittest.main()
