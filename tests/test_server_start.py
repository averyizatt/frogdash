"""The dash service's own start-up (server.main), as systemd runs it, up to the point where
it would start serving: argument handling, every component it builds, the helper socket.
Nothing else in the tests runs this path, and a mistake in it stops the whole dash."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hardware.frogdash import server


class StartTests(unittest.TestCase):
    def start(self, *args):
        started = {}

        def run_app(app, **kwargs):
            started.update(kwargs, app=app)
        with mock.patch.object(server.web, 'run_app', run_app), mock.patch.object(sys, 'argv', ['server', *args]):
            server.main()
        return started

    def test_a_replay_starts_and_serves_on_the_port(self):
        with tempfile.TemporaryDirectory() as folder:
            replay = Path(folder) / 'drive.log'
            replay.write_text('(0.000) can0 5E8#07080D7A080201F4\n')
            started = self.start('--replay', str(replay), '--port', '8099', '--data-dir', folder, '--race-file', str(Path(folder) / 'race.json'))
            self.assertEqual((started['host'], started['port']), ('127.0.0.1', 8099))
            self.assertIsNotNone(started['app'])

    def test_the_car_configuration_starts(self):
        # As the Pi runs it (FROGDASH_ARGS), with the folders in a temporary place.
        with tempfile.TemporaryDirectory() as folder:
            started = self.start('--interface', 'can0', '--log-dir', str(Path(folder) / 'logs'), '--data-dir', folder,
                                 '--race-file', str(Path(folder) / 'race.json'))
            self.assertEqual(started['port'], 8080)


if __name__ == '__main__':
    unittest.main()
