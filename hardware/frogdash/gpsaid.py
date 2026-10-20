"""Satellite data kept across power-offs, for a receiver with no backup battery.

The VK-162 (u-blox 7) forgets everything when the key goes off, so every start is a cold
start: it has to download each satellite's orbit (its ephemeris) from the sky, which
takes 30 s under open sky and minutes through a car roof. This keeps a copy on the Pi:

- Save: while the receiver has a position (2 minutes after the first fix, then every 10
  minutes), ask it through gpsd for its ephemerides (UBX-AID-EPH), almanac (AID-ALM) and
  ionosphere/UTC data (AID-HUI), and write them to gps-aid.json in the data folder.
- Restore: when the receiver is first heard without a position, send them back, with the
  last known position (AID-INI). A stop of an hour or two then starts almost like a hot
  start; after longer, the almanac still tells it which satellites to look for. The
  receiver checks each ephemeris's age itself once it knows the time, and drops old ones.

u-blox receivers only: the commands go through gpsd's ?DEVICE (as the recovery steps do),
and the answers are read back in gpsd's raw mode, where each binary packet arrives as one
line of hex.
"""
import asyncio
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time

# pyubx2 reads the receiver's answers by field name when it is installed (the Pi setup
# installs it). The dash must start without it: everything here also works from the
# bytes, as it did before pyubx2.
try:
    from pyubx2 import GET, SET, UBXMessage, UBXReader, VALCKSUM
    from pyubx2.exceptions import UBXMessageError, UBXParseError, UBXTypeError
    UBX_ERRORS = (UBXParseError, UBXMessageError, UBXTypeError)
except ImportError:
    UBXMessage = UBXReader = None
    UBX_ERRORS = ()

from .gps import ANTENNA, JAMMING, UBX_HARDWARE_POLL, checksum, ubx

AID_INI, AID_HUI, AID_ALM, AID_EPH = (0x0B, 0x01), (0x0B, 0x02), (0x0B, 0x30), (0x0B, 0x31)
HARDWARE_EVERY_S = 60      # How often the receiver is asked about its radio (MON-HW)
FIRST_SAVE_S = 120         # After the first fix of a run
SAVE_EVERY_S = 600
MAX_AGE_S = 7 * 86400      # Older than this (by the Pi's clock) is not sent
EPH_BYTES, ALM_BYTES, HUI_BYTES = 104, 40, 72   # Payload length of a message that carries data


def packets_in(data):
    """The UBX packets in `data` whose checksum is right: [(raw, message)], the message as
    pyubx2 reads it, or None for one it has no layout for or without pyubx2 (kept either
    way: the satellite data is sent back byte for byte). A damaged packet is skipped and
    the search goes on from the next header, which pyubx2's own stream reader does not do."""
    found, i = [], 0
    while (i := data.find(b'\xb5\x62', i)) >= 0 and i + 8 <= len(data):
        end = i + 8 + int.from_bytes(data[i + 4:i + 6], 'little')
        if end <= len(data) and checksum(data[i + 2:end - 2]) == data[end - 2:end]:
            raw = data[i:end]
            message = None
            if UBXReader:
                try:
                    message = UBXReader.parse(raw, validate=VALCKSUM, msgmode=GET)
                except (*UBX_ERRORS, ValueError, KeyError, IndexError):
                    pass
            found.append((raw, message))
            i = end
            continue
        i += 2
    return found


def frames_in(data):
    """The UBX packets in `data` whose checksum is right: [(class, id, payload)]."""
    return [(raw[2], raw[3], raw[6:-2]) for raw, _ in packets_in(data)]


def exchange(path, frames, seconds=4.0, host='127.0.0.1', port=2947, pace=0.02):
    """Send UBX `frames` to the receiver through gpsd and return the UBX packets it sends
    back within `seconds` (gpsd's raw mode: one line of hex per binary packet)."""
    collected = []
    with socket.create_connection((host, port), 3) as link:
        link.sendall(('?WATCH=' + json.dumps({'enable': True, 'raw': 1, 'device': path}) + '\n').encode())
        time.sleep(.2)
        for frame in frames:
            link.sendall(('?DEVICE=' + json.dumps({'path': path, 'hexdata': frame.hex()}, separators=(',', ':')) + '\n').encode())
            time.sleep(pace)
        link.settimeout(.25)
        buffer, deadline = b'', time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                chunk = link.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            buffer += chunk
            *lines, buffer = buffer.split(b'\n')
            for line in lines:
                text = line.strip().decode('ascii', 'replace')
                if text and not text.startswith('{') and all(c in '0123456789abcdefABCDEF' for c in text) and len(text) % 2 == 0:
                    collected.extend(frames_in(bytes.fromhex(text)))
    return collected


def clock_synchronized():
    """Whether the Pi's clock is known to be right (chrony or NTP has set it). The Pi has
    no clock battery: at key-on it may be hours out, and a wrong time sent to the
    receiver would slow it down, so the time is only sent when it is right."""
    try:
        out = subprocess.run(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'], capture_output=True,
                             text=True, timeout=3, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        return out.strip() == 'yes'
    except (OSError, subprocess.SubprocessError):
        return False


def initial(lat, lon, alt_m=0.0, accuracy_m=50000, wall=None):
    """UBX-AID-INI: the last known position (and the time, when the Pi's clock is right)."""
    flags = 0x01 | 0x20                       # Position valid, given as latitude/longitude/altitude
    if alt_m is None:
        alt_m, flags = 0.0, flags | 0x40      # Altitude not known
    week = tow_ms = 0
    t_acc_ms = 0
    if wall is not None:
        gps_s = wall - 315964800 + 18         # Unix time to GPS time (18 leap seconds)
        week, tow_ms = int(gps_s // 604800), int((gps_s % 604800) * 1000)
        t_acc_ms, flags = 2000, flags | 0x02  # Time valid, to about 2 s
    if UBXMessage:
        return UBXMessage('AID', 'AID-INI', SET, ecefXOrLat=round(lat * 1e7), ecefYOrLon=round(lon * 1e7),
                          ecefZOrAlt=round(alt_m * 100), posAcc=round(accuracy_m * 100), wn=week, tow=tow_ms,
                          tAccMs=t_acc_ms, flags=flags.to_bytes(4, 'little')).serialize()
    payload = struct.pack('<iiiIHHIiIIiII', round(lat * 1e7), round(lon * 1e7), round(alt_m * 100),
                          round(accuracy_m * 100), 0, week, tow_ms, 0, t_acc_ms, 0, 0, 0, flags)
    return ubx(*AID_INI, payload)


def hardware_report(payload, seen):
    """What MON-HW says about the receiver's radio, in words the dash shows: read by
    pyubx2 when installed, else from its fixed layout (u-blox 7 and later)."""
    if UBXMessage:
        m = UBXMessage(b'\x0a', b'\x09', GET, payload=payload)
        noise, agc, antenna, jamming, level = m.noisePerMS, m.agcCnt, m.aStatus, m.jammingState, m.jamInd
    else:
        noise, agc = struct.unpack_from('<HH', payload, 16)
        antenna, jamming, level = payload[20], payload[22] >> 2 & 3, payload[45]
    return {'antenna': ANTENNA.get(antenna, 'unknown'), 'jamming': JAMMING.get(jamming, 'unknown'),
            'jam_ind': level, 'noise': noise, 'agc_pct': round(agc * 100 / 8191), 'seen': seen}


class GpsAid:
    def __init__(self, gps, folder, nav=None, clock=time.monotonic, wall=time.time,
                 talk=exchange, synchronized=clock_synchronized):
        self.gps, self.path, self.nav = gps, Path(folder) / 'gps-aid.json', nav
        self.clock, self.wall, self.talk, self.synchronized = clock, wall, talk, synchronized
        self.restored_for = None     # Device the saved data was sent to (once per connection)
        self.first_fix_at = None
        self.saved_at = None
        self.note = None             # Last thing done, for the event log and System check
        self.stopping = False
        self.hardware_at = None      # When the receiver was last asked about its radio

    def usable(self):
        driver = (self.gps.driver() or '').lower()
        return bool(self.gps.device) and 'u-blox' in driver and self.clock() - self.gps.device_seen <= 15

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) and isinstance(data.get('frames'), list) else None
        except (OSError, ValueError):
            return None

    def save(self):
        polls = [ubx(*AID_HUI), ubx(*AID_ALM), ubx(*AID_EPH)]
        packets = self.talk(self.gps.device, polls)
        keep = [(c, i, p) for c, i, p in packets
                if (c, i) == AID_EPH and len(p) == EPH_BYTES or (c, i) == AID_ALM and len(p) == ALM_BYTES
                or (c, i) == AID_HUI and len(p) == HUI_BYTES]
        eph = sum((c, i) == AID_EPH for c, i, _ in keep)
        if not eph:
            self.note = 'Satellite data not saved: the receiver sent none back'
            return False
        values = self.gps.values()
        position = [values[name]['value'] for name in ('gps.latitude', 'gps.longitude', 'gps.altitude_m')]
        body = {'saved': self.wall(), 'device': self.gps.device, 'position': position,
                'frames': [ubx(c, i, p).hex() for c, i, p in keep]}
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(body), encoding='utf-8')
        os.replace(tmp, self.path)
        alm = sum((c, i) == AID_ALM for c, i, _ in keep)
        self.note = f'Satellite data saved: {eph} satellite orbits, {alm} almanac entries'
        return True

    def restore(self, data):
        age = self.wall() - float(data.get('saved') or 0)
        if not 0 <= age <= MAX_AGE_S:
            self.note = 'Saved satellite data too old to use'
            return False
        frames, with_time = [], False
        lat, lon, alt = (list(data.get('position') or []) + [None] * 3)[:3]
        if self.nav is not None and getattr(self.nav, 'position', None):
            lat, lon = self.nav.position             # The last known position, if it moved since
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            with_time = self.synchronized()
            frames.append(initial(lat, lon, alt if isinstance(alt, (int, float)) else None,
                                  wall=self.wall() if with_time else None))
        saved = [bytes.fromhex(h) for h in data['frames'] if isinstance(h, str)]
        # Ionosphere/UTC first, then the almanac, then the orbits.
        order = {AID_HUI: 0, AID_ALM: 1, AID_EPH: 2}
        frames += sorted((f for f in saved if (f[2], f[3]) in order), key=lambda f: order[(f[2], f[3])])
        self.talk(self.gps.device, frames, seconds=.5)
        eph = sum((f[2], f[3]) == AID_EPH for f in saved)
        self.note = f'Satellite data restored: {eph} satellite orbits from {round(age / 60)} min ago' + (', with the time' if with_time else '')
        return True

    def check_hardware(self):
        """Ask the receiver about its radio (MON-HW): antenna, noise and jamming. Interference
        from USB 3, a dash cam or LED drivers is a usual cause of a GPS that loses its fix
        in a car, and the receiver can tell."""
        now = self.clock()
        if self.hardware_at is not None and now - self.hardware_at < HARDWARE_EVERY_S:
            return
        self.hardware_at = now
        for c, i, payload in self.talk(self.gps.device, [UBX_HARDWARE_POLL], seconds=1.5):
            if (c, i) == (0x0A, 0x09) and len(payload) >= 60:
                self.gps.hardware = hardware_report(payload, now)
                return

    def step(self):
        """One look; blocking (talks to gpsd), so it runs in a thread."""
        if not self.usable():
            return
        self.keep_data()
        try:
            self.check_hardware()    # After the satellite data: that is what a cold start waits for
        except (OSError, struct.error, *UBX_ERRORS) as error:
            self.note = f'Could not ask the receiver about its radio: {error}'

    def keep_data(self):
        fixed = self.gps.mode in (2, 3)
        if self.restored_for != self.gps.device and not fixed:
            self.restored_for = self.gps.device
            data = self.load()
            if data:
                try:
                    self.restore(data)
                except OSError as error:
                    self.note = f'Could not restore the satellite data: {error}'
        if not fixed:
            return
        now = self.clock()
        if self.first_fix_at is None:
            self.first_fix_at = now
            self.restored_for = self.gps.device   # Already has a position: nothing to send
        due = self.saved_at is None and now - self.first_fix_at >= FIRST_SAVE_S or \
            self.saved_at is not None and now - self.saved_at >= SAVE_EVERY_S
        if due:
            self.saved_at = now
            try:
                self.save()
            except OSError as error:
                self.note = f'Could not save the satellite data: {error}'

    async def run(self):
        while not self.stopping:
            await asyncio.to_thread(self.step)
            await asyncio.sleep(5)
