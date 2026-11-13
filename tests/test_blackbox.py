"""The ESP32 water/meth board's black box (can_protocol.h extension 9): put back together,
written to the event log once in words with every sample, shown, and answered."""
import tempfile
import unittest
from pathlib import Path

from hardware.frogdash.blackbox import COLUMNS, RECEIVED, rows_of, summary
from hardware.frogdash.eventlog import EventLog, read
from hardware.frogdash.state import State

try:
    from tests.test_can_contract import COMPILER, vectors
except ImportError:   # pragma: no cover
    COMPILER = None


def sample(duty=0.0, duty_max=None, map_kpa=132, rpm=3400, hold=0, state=0x10, events=0x03, rx_ms=10, gap_ms=21, pre_c=35, heap_kb=248):
    return bytes([round(duty * 2), round((duty if duty_max is None else duty_max) * 2), map_kpa, round(rpm / 32), hold | state,
                  events, rx_ms // 10, gap_ms, pre_c + 40 if pre_c is not None else 0, heap_kb // 2])


def frames(payload, reason=9, window_ms=100, version=1):
    """What the board sends: a header, then the bytes seven to a frame (the last padded)."""
    count = -(-len(payload) // 7)
    total = sum(payload) & 0xFFFF
    out = [bytes([0xFF, version, len(payload) // 10, window_ms // 10, reason, count, total >> 8, total & 0xFF])]
    for index in range(count):
        out.append(bytes([index]) + payload[index * 7:index * 7 + 7].ljust(7, b'\x00'))
    return out


class BlackBoxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.0
        self.state = State('socketcan', clock=lambda: self.now, wall=lambda: 1794000000.0)
        self.state.connected = True
        self.state.eventlog = EventLog(self.state, Path(self.temp.name), wall=lambda: 1794000000.0, clock=lambda: self.now)
        self.sent = []

        async def sender(identifier, data):
            self.sent.append((identifier, bytes(data)))
        self.state.controls.attach(sender)

    def feed(self, frame_list):
        for frame in frame_list:
            self.state.ingest(0x310, frame)

    def entries(self):
        return [e for e in read(self.state.eventlog.folder) if e['text'].startswith('water/meth black box')]

    def brownout_with_the_pump_starting(self):
        """Ten seconds: 9.5 s armed and waiting for boost, then the pump starting in its soft start."""
        quiet = [sample(hold=2) for _ in range(95)]
        starting = [sample(duty=10 + 5 * i, hold=0, state=0x30, events=0x03 | (0x04 if i == 0 else 0)) for i in range(5)]
        return b''.join(quiet + starting)

    async def test_a_record_is_written_once_in_words_and_answered(self):
        payload = self.brownout_with_the_pump_starting()
        self.feed(frames(payload))
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['level'], 'warn')
        self.assertEqual(entries[0]['text'],
                         'water/meth black box (brownout (supply dip)), the 10.0 s before it: pump on at 30%, started 0.4 s before the end '
                         '(still in its soft start); 132 kPa, 3392 rpm; CAN heard to the end; longest control gap 21 ms; least free memory 248 KB')
        detail = entries[0]['detail']
        self.assertEqual((detail['columns'], len(detail['rows']), detail['window_ms']), (COLUMNS, 100, 100))
        self.assertEqual(detail['rows'][0][:2], [-9.9, 0.0])
        self.assertEqual(detail['rows'][-1][:6], [0.0, 30.0, 30.0, 132, 3392, 'NONE'])
        # Shown on the Water / meth tab.
        shown = self.state.snapshot()['meth_black_box']
        self.assertEqual((shown['reason'], shown['at']), (9, 1794000000.0))
        self.assertIn('pump on at 30%', shown['text'])
        # Answered once, so the board stops sending it.
        await self.state.controls.answer_black_box()
        await self.state.controls.answer_black_box()
        self.assertEqual(self.sent, [(0x301, RECEIVED)])
        # Sent again because the answer was lost: answered again, written once.
        self.feed(frames(payload))
        await self.state.controls.answer_black_box()
        self.assertEqual((len(self.entries()), self.sent[-1], len(self.sent)), (1, (0x301, RECEIVED), 2))

    async def test_a_record_that_does_not_arrive_whole_is_neither_written_nor_answered(self):
        payload = self.brownout_with_the_pump_starting()
        whole = frames(payload)
        self.feed(whole[1:])                          # A record whose header was missed (the dash started late)
        self.feed(whole[:40] + whole[41:])            # One frame lost on the way
        damaged = list(whole)
        damaged[5] = damaged[5][:3] + bytes([damaged[5][3] ^ 1]) + damaged[5][4:]
        self.feed(damaged)                            # A byte changed on the way: the sum does not match
        self.feed(frames(payload, version=2))         # A record from a newer layout: not guessed at
        await self.state.controls.answer_black_box()
        self.assertEqual((self.entries(), self.sent), ([], []))
        # The board's next try arrives whole, frames in any order.
        self.feed(whole[:1] + list(reversed(whole[1:])))
        await self.state.controls.answer_black_box()
        self.assertEqual((len(self.entries()), self.sent), (1, [(0x301, RECEIVED)]))

    def test_the_summary_says_what_went_wrong(self):
        # CAN went silent for the last 2 s and the controller was set up again; the pump had stopped.
        rows = [sample(duty=40, hold=0, state=0x10) for _ in range(70)]
        rows.append(sample(duty=0, duty_max=40, hold=2, events=0x03 | 0x08))
        rows += [sample(hold=2, events=0x02, rx_ms=300) for _ in range(9)]
        rows += [sample(hold=2, map_kpa=0, rpm=0, events=0x00 | (0x10 if i % 5 == 0 else 0) | 0x20, rx_ms=2550, gap_ms=180, heap_kb=120)
                 for i in range(20)]
        text = summary(rows_of(b''.join(rows), 100), 3, 100)
        self.assertEqual(text, '(software restart), the 10.0 s before it: pump off, stopped 2.9 s before the end (up to 40%); '
                               'no fresh MicroSquirt data at the end; nothing heard on CAN for the last 2.5 s or more; '
                               'CAN set up again in 4 of the windows; frames not getting out in 20 of the windows; '
                               'longest control gap 180 ms; least free memory 120 KB')

    @unittest.skipUnless(COMPILER, 'C++ compiler required for the firmware builders')
    async def test_the_firmware_builders_frames_put_together(self):
        built = vectors()
        self.feed([built[name][1] for name in ('meth_box_header', 'meth_box_data0', 'meth_box_data1', 'meth_box_data2')])
        self.assertEqual({built[name][0] for name in built if name.startswith('meth_box')}, {0x310})
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        rows = entries[0]['detail']['rows']
        self.assertEqual(rows, [[-0.1, 32.0, 32.0, 132, 3392, 'NONE', 0x30, 0x07, 10, 21, 35, 248],
                                [0.0, 35.0, 35.0, 132, 3392, 'NONE', 0x10, 0x03, 10, 22, 35, 248]])
        self.assertIn('(brownout (supply dip)), the 0.2 s before it: pump on at 35%, started 0.1 s before the end', entries[0]['text'])


if __name__ == '__main__':
    unittest.main()
