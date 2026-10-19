"""hardware/can_contract/frogdash.dbc (for SavvyCAN and cantools) says what the dash's own
decoder says: random frames of every message are decoded both ways and compared, signal
by signal. And the file is what tools/make_dbc.py writes now."""
from functools import reduce
from operator import xor
import random
import unittest

try:
    import cantools
except ImportError:          # Only on the computers that check the code: not on the Pi.
    cantools = None

from hardware.frogdash.protocol import decode

if cantools:
    from tools import make_dbc


def fix(frame_id, d, rng):
    """Make a random frame one the dash accepts: version bytes, checksums, report kinds."""
    if frame_id == 0x205:
        d[0] &= 0x1F; d[2] = 1
    elif frame_id == 0x204:
        d[0:2] = rng.randrange(1001).to_bytes(2, 'big'); d[2] = 1
    elif frame_id == 0x500:
        d[6] %= 101; d[7] &= 7
    elif frame_id == 0x501:
        d[0] &= 31; d[1] = d[1] & 31 | d[0]; d[3] = 1
    elif frame_id == 0x503:
        d[0] = rng.choice((1, 2)); d[5] = 1
    elif frame_id == 0x304:
        d[7] = reduce(xor, d[:7], 0)
    elif frame_id == 0x30A:
        d[3] = 2
    elif frame_id == 0x103:
        d[0] = rng.randrange(1, 6)
    elif frame_id == 0x30E:
        d[0] = rng.randrange(1, 7)
        if d[0] >= 5:
            d[1] = rng.randrange(6) * 6
    elif frame_id == 0x30F:
        d[0] = rng.randrange(1, 5)
    return bytes(d)


@unittest.skipUnless(cantools, 'cantools is only installed where the code is checked (requirements-tools.lock)')
class DbcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = cantools.database.load_file(str(make_dbc.OUT))

    def test_the_file_is_up_to_date_with_the_script(self):
        self.assertEqual(make_dbc.OUT.read_text(encoding='utf-8').replace('\r\n', '\n'), make_dbc.text(),
                         'Run python tools/make_dbc.py after changing a message')

    def test_every_signal_decodes_as_the_dash_decodes_it(self):
        rng = random.Random(4)
        compared = 0
        for frame_id, signals in make_dbc.keys().items():
            message = self.db.get_message_by_frame_id(frame_id)
            for _ in range(40):
                data = fix(frame_id, bytearray(rng.randbytes(message.length)), rng)
                dash = decode(frame_id, data)
                tool = message.decode(data, decode_choices=True, scaling=True)
                for name, key, mux in signals:
                    if name not in tool:
                        continue          # Another report kind
                    self.assertIn(key, dash, f'0x{frame_id:03X} {name}: the dash has no {key}')
                    want, got = dash[key].value, tool[name]
                    where = f'0x{frame_id:03X} {message.name}.{name} for {data.hex()}'
                    if want is None or isinstance(want, str) and want.startswith('UNKNOWN('):
                        continue          # Not available, or a value with no name: nothing to compare
                    if isinstance(want, str):
                        self.assertEqual(str(got), want, where)
                        compared += 1
                        continue
                    got = getattr(got, 'value', got)   # A named value where the dash keeps the number
                    if isinstance(want, bool):
                        self.assertEqual(int(got), int(want), where)
                    else:
                        self.assertAlmostEqual(float(got), float(want), delta=1e-3 + abs(want) * 1e-9, msg=where)
                    compared += 1
        self.assertGreater(compared, 5000)

    def test_the_dashes_commands_and_the_firmware_channel_are_described(self):
        command = self.db.get_message_by_name('METH_COMMAND')
        self.assertEqual(command.decode(bytes([7, 0, 0, 0, 0, 0, 0, 0]))['command'], 'RESTART')
        reply = self.db.get_message_by_name('FIRMWARE_COMMAND').decode(bytes([0x86, 2, 0, 0, 0, 0, 0, 0]))
        self.assertEqual((reply['op'], reply['target']), ('RESTART', 'TAILLIGHTS'))


if __name__ == '__main__':
    unittest.main()
