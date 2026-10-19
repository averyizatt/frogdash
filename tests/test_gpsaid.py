"""Satellite data kept across power-offs for a receiver with no backup battery (gpsaid.py),
against a stand-in gpsd and a stand-in receiver."""
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest

from hardware.frogdash.gps import GPS, ubx
from hardware.frogdash.gpsaid import (AID_ALM, AID_EPH, AID_HUI, AID_INI, FIRST_SAVE_S, HARDWARE_EVERY_S, GpsAid, exchange,
                                      frames_in, initial, packets_in)
from pyubx2 import GET, UBXMessage


def radio(jamming=1, level=20, antenna=2):
    """The receiver's MON-HW answer."""
    return UBXMessage('MON', 'MON-HW', GET, jammingState=jamming, jamInd=level, aStatus=antenna,
                      noisePerMS=87, agcCnt=4096).serialize()


def eph(sv, data=True):
    return ubx(*AID_EPH, struct.pack('<II', sv, 0x1234) + (bytes(range(96)) if data else b''))


def alm(sv):
    return ubx(*AID_ALM, struct.pack('<II', sv, 2440) + bytes(32))


HUI = ubx(*AID_HUI, bytes(72))


class PacketTests(unittest.TestCase):
    def test_packets_are_found_and_a_damaged_one_is_skipped(self):
        bad = bytearray(eph(5))
        bad[20] ^= 0xFF
        self.assertEqual(packets_in(radio())[0][1].identity, 'MON-HW')     # Read by pyubx2
        found = frames_in(b'noise' + eph(3) + bytes(bad) + alm(7) + eph(9)[:30])
        self.assertEqual([(c, i, len(p)) for c, i, p in found], [(0x0B, 0x31, 104), (0x0B, 0x30, 40)])

    def test_the_last_position_and_the_time_for_the_receiver(self):
        frame = initial(39.0639, -108.5506, 1400.0)
        (c, i, payload), = frames_in(frame)
        self.assertEqual(((c, i), len(payload)), (AID_INI, 48))
        lat, lon, alt, acc, _, week, tow, _, t_acc, _, _, _, flags = struct.unpack('<iiiIHHIiIIiII', payload)
        self.assertEqual((lat, lon, alt, acc, week, flags), (390639000, -1085506000, 140000, 5000000, 0, 0x21))   # No time: clock not trusted
        payload = frames_in(initial(39.0639, -108.5506, None, wall=1792065600))[0][2]
        _, _, _, _, _, week, tow, _, t_acc, _, _, _, flags = struct.unpack('<iiiIHHIiIIiII', payload)
        self.assertEqual((week, tow, t_acc, flags), (2440, 388818000, 2000, 0x63))     # 2026-10-15 12:00 UTC, altitude unknown


class GpsdTests(unittest.TestCase):
    def test_commands_go_through_gpsd_and_the_answers_come_back_from_its_raw_mode(self):
        server = socket.create_server(('127.0.0.1', 0))
        got = []

        def serve():
            link, _ = server.accept()
            with link:
                link.settimeout(2)
                data = b''
                while data.count(b'\n') < 3:
                    data += link.recv(4096)
                got.extend(data.decode().splitlines())
                link.sendall(b'{"class":"WATCH","enable":true,"raw":1}\n' + eph(3).hex().encode() + b'\n'
                             + b'$GPGGA,ignored\n' + (alm(3) + HUI).hex().encode() + b'\n')
        thread = threading.Thread(target=serve)
        thread.start()
        try:
            answers = exchange('/dev/ttyACM0', [ubx(*AID_EPH), ubx(*AID_ALM)], seconds=1, port=server.getsockname()[1], pace=0)
        finally:
            thread.join(5)
            server.close()
        self.assertEqual(json.loads(got[0].split('=', 1)[1]), {'enable': True, 'raw': 1, 'device': '/dev/ttyACM0'})
        self.assertEqual(got[1], '?DEVICE={"path":"/dev/ttyACM0","hexdata":"b5620b3100003cbf"}')
        self.assertEqual([(c, i) for c, i, _ in answers], [AID_EPH, AID_ALM, AID_HUI])


class KeeperTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.now, self.wall = 0.0, 1792065600.0
        self.gps = GPS(clock=lambda: self.now, wall=lambda: self.wall)
        self.sent = []
        self.radio_polls, self.radio = 0, radio()
        self.receiver = [eph(sv) for sv in (3, 7, 12)] + [eph(sv, data=False) for sv in (1, 2)] + [alm(3), HUI]
        self.aid = GpsAid(self.gps, self.folder.name, clock=lambda: self.now, wall=lambda: self.wall,
                          talk=self.talk, synchronized=lambda: False)

    def tearDown(self):
        self.folder.cleanup()

    def talk(self, path, frames, seconds=4.0):
        if [(f[2], f[3]) for f in frames] == [(0x0A, 0x09)]:     # The radio check, once a minute
            self.radio_polls += 1
            return frames_in(self.radio)
        self.sent.append((path, [(f[2], f[3]) for f in frames]))
        return [frames_in(f)[0] for f in self.receiver] if any((f[2], f[3]) == AID_EPH and f[4] == 0 for f in frames) else []

    def heard(self, mode, **fix):
        self.gps.update({'class': 'DEVICE', 'path': '/dev/ttyACM0', 'driver': 'u-blox', 'activated': 'x'})
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyACM0', 'mode': mode, **fix})

    def test_saved_while_it_has_a_position_and_sent_back_after_a_power_off(self):
        self.heard(3, lat=39.06, lon=-108.55, altMSL=1400, speed=0)
        self.aid.step()
        self.assertEqual(self.sent, [])                                     # A position at once: nothing to send
        self.now = FIRST_SAVE_S + 1
        self.heard(3, lat=39.06, lon=-108.55, altMSL=1400, speed=0)
        self.aid.step()
        self.assertEqual(self.sent[-1][1], [AID_HUI, AID_ALM, AID_EPH])     # The three polls
        saved = json.loads(Path(self.folder.name, 'gps-aid.json').read_text())
        self.assertEqual((len(saved['frames']), saved['position']), (5, [39.06, -108.55, 1400]))   # Empty orbits left out
        self.assertEqual(self.aid.note, 'Satellite data saved: 3 satellite orbits, 1 almanac entries')

        # Key off, key on 40 minutes later: a new dash run, the receiver cold.
        self.now, self.wall = 0.0, self.wall + 2400
        self.gps = GPS(clock=lambda: self.now, wall=lambda: self.wall)
        self.aid = GpsAid(self.gps, self.folder.name, clock=lambda: self.now, wall=lambda: self.wall,
                          talk=self.talk, synchronized=lambda: False)
        self.sent.clear()
        self.heard(1)
        self.aid.step()
        self.aid.step()                                                      # Once per connection
        self.assertEqual(self.sent, [('/dev/ttyACM0', [AID_INI, AID_HUI, AID_ALM, AID_EPH, AID_EPH, AID_EPH])])
        self.assertEqual(self.aid.note, 'Satellite data restored: 3 satellite orbits from 40 min ago')

    def test_the_receiver_is_asked_about_its_radio_once_a_minute(self):
        self.gps.gpsd_ok = True
        self.heard(1)
        self.aid.step()
        self.assertEqual(self.radio_polls, 1)
        self.assertEqual(self.gps.hardware, {'antenna': 'ok', 'jamming': 'ok', 'jam_ind': 20, 'noise': 87, 'agc_pct': 50, 'seen': 0.0})
        self.assertEqual(self.gps.diagnosis()['state'], 'deaf')
        self.now = HARDWARE_EVERY_S - 1
        self.heard(1)
        self.aid.step()
        self.assertEqual(self.radio_polls, 1)
        # Something in the car starts drowning the satellites: said so, with what to do.
        self.radio, self.now = radio(jamming=3, level=190), HARDWARE_EVERY_S
        self.heard(1)
        self.aid.step()
        found = self.gps.diagnosis()
        self.assertEqual(found['state'], 'jammed')
        self.assertIn('radio interference (critical, level 190 of 255)', found['text'])
        self.assertIn('dash cam', found['fix'])
        # With a fix it stays a fix, with the interference noted.
        self.heard(3, lat=39.06, lon=-108.55, speed=0)
        self.assertEqual(self.gps.diagnosis()['state'], 'fix')
        self.assertIn('reports radio interference (critical)', self.gps.diagnosis()['text'])
        # An antenna fault reported by the receiver comes first.
        self.radio, self.now = radio(antenna=4), 2 * HARDWARE_EVERY_S
        self.heard(1)
        self.aid.step()
        self.assertEqual(self.gps.diagnosis()['state'], 'antenna')

    def test_not_a_u_blox_or_nothing_saved_or_too_old_sends_nothing(self):
        self.gps.update({'class': 'TPV', 'device': '/dev/ttyUSB0', 'mode': 1})
        self.aid.step()
        self.heard(1)
        self.aid.step()                                                      # Nothing saved yet
        self.assertEqual(self.sent, [])
        Path(self.folder.name, 'gps-aid.json').write_text(json.dumps({'saved': self.wall - 9 * 86400, 'frames': [eph(3).hex()]}))
        self.aid.restored_for = None
        self.aid.step()
        self.assertEqual((self.sent, self.aid.note), ([], 'Saved satellite data too old to use'))


if __name__ == '__main__':
    unittest.main()
