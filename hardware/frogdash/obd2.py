"""Generic OBD-II over CAN (SAE J1979 mode 01 on ISO 15765-4): any car whose OBD port has CAN.

An OBD-II ECU broadcasts nothing; it answers requests. With the "obd2" (or "obd2_29bit")
ECU profile chosen, the dash asks for each reading in turn on the functional request ID
(0x7DF, or 0x18DB33F1 for 29-bit) and reads the answers (0x7E8-0x7EF, or 0x18DAF1xx).
Only mode 01 "show current data" requests are sent: read-only, the same as any scan tool.

First it asks which readings the car supports (PIDs 0x00, 0x20, 0x40: bitmaps), again every
few seconds until the car answers (key off: nothing answers). Then it cycles through the
supported readings it knows (PIDS), the fast ones (RPM, speed, throttle, MAP) between each
of the others, at REQUEST_HZ in all. Formulas from SAE J1979 / ISO 15031-5.
"""
REQUEST_HZ = 20
DISCOVERY_RETRY_S = 3.0
SUPPORT_PIDS = (0x00, 0x20, 0x40)

# PID -> (dash value, bytes used, formula on the data bytes A, B)
PIDS = {
    0x04: ('ecu.engine_load_pct', 1, lambda a, b: a * 100 / 255),
    0x05: ('ecu.coolant_c', 1, lambda a, b: a - 40),
    0x06: ('ecu.stft1_pct', 1, lambda a, b: (a - 128) * 100 / 128),
    0x07: ('ecu.ltft1_pct', 1, lambda a, b: (a - 128) * 100 / 128),
    0x0A: ('ecu.fuel_pressure_kpa', 1, lambda a, b: a * 3),
    0x0B: ('ecu.map_kpa', 1, lambda a, b: a),
    0x0C: ('ecu.rpm', 2, lambda a, b: (a * 256 + b) / 4),
    0x0D: ('ecu.vehicle_speed_kph', 1, lambda a, b: a),
    0x0E: ('ecu.spark_deg', 1, lambda a, b: a / 2 - 64),
    0x0F: ('ecu.iat_c', 1, lambda a, b: a - 40),
    0x10: ('ecu.maf_g_s', 2, lambda a, b: (a * 256 + b) / 100),
    0x11: ('ecu.throttle_pct', 1, lambda a, b: a * 100 / 255),
    0x1F: ('ecu.seconds', 2, lambda a, b: a * 256 + b),
    0x24: ('ecu.lambda1', 2, lambda a, b: (a * 256 + b) * 2 / 65536),
    0x2F: ('ecu.fuel_level_pct', 1, lambda a, b: a * 100 / 255),
    0x33: ('ecu.baro_kpa', 1, lambda a, b: a),
    0x42: ('ecu.battery_v', 2, lambda a, b: (a * 256 + b) / 1000),
    0x44: ('ecu.lambda_target', 2, lambda a, b: (a * 256 + b) * 2 / 65536),
    0x46: ('ecu.ambient_c', 1, lambda a, b: a - 40),
    0x5C: ('ecu.oil_temp_c', 1, lambda a, b: a - 40),
    0x5E: ('ecu.fuel_rate_l_h', 2, lambda a, b: (a * 256 + b) / 20),
}
FAST = (0x0C, 0x0D, 0x11, 0x0B)


def decode(data):
    """{dash value: value} from one mode 01 answer (single frame), or {} for anything else."""
    data = bytes(data)
    if len(data) < 4 or data[1] != 0x41 or data[0] < 2:
        return {}
    pid = data[2]
    if pid not in PIDS:
        return {}
    key, size, formula = PIDS[pid]
    if data[0] < 2 + size or len(data) < 3 + size:
        return {}
    a, b = data[3], data[4] if size == 2 else 0
    return {key: formula(a, b)}


def keys():
    return sorted({key for key, _, _ in PIDS.values()})


def request(pid):
    """The 8 bytes of a mode 01 request for one PID (ISO 15765-4 single frame, padded)."""
    return bytes([0x02, 0x01, pid, 0x55, 0x55, 0x55, 0x55, 0x55])


class Poller:
    """What to ask next, and what the car said it supports."""
    def __init__(self, extended=False, clock=None):
        self.request_id = 0x18DB33F1 if extended else 0x7DF
        self.extended = extended
        self.supported = set()     # PIDs the car answered as supported
        self.answered = set()      # Support bitmaps (0x00, 0x20, 0x40) that came back
        self.next_at = 0.0
        self.discovery_at = 0.0
        self.cycle, self.fast, self.slow_index, self.fast_index = [], [], 0, 0
        self.sent_count = self.answers = 0
        self.last_error = None

    def due(self, now):
        return now >= self.next_at

    def seen(self, data):
        """An answer from the car (state.ingest): support bitmaps update what is asked."""
        data = bytes(data)
        if len(data) >= 7 and data[1] == 0x41 and data[2] in SUPPORT_PIDS:
            base = data[2]
            bits = int.from_bytes(data[3:7], 'big')
            self.supported |= {base + n + 1 for n in range(32) if bits >> (31 - n) & 1}
            self.answered.add(base)
            self.cycle, self.fast = [], []
        elif len(data) >= 3 and data[1] == 0x41:
            self.answers += 1

    def wanted(self):
        """The support bitmaps still to ask for: 0x00 first, then each the car said it has."""
        out = [] if 0x00 in self.answered else [0x00]
        for base in (0x20, 0x40):
            if base not in self.answered and (base in self.supported):
                out.append(base)
        return out

    def next_pid(self, now):
        missing = self.wanted()
        if missing and now >= self.discovery_at:
            self.discovery_at = now + DISCOVERY_RETRY_S
            return missing[0]
        if not self.supported:
            return None
        if not self.cycle and not self.fast:
            self.cycle = [p for p in sorted(PIDS) if p in self.supported and p not in FAST]
            self.fast = [p for p in FAST if p in self.supported]
        # Fast readings between each slow one.
        turn = self.sent_count % 2
        if turn == 0 and self.fast:
            pid = self.fast[self.fast_index % len(self.fast)]
            self.fast_index += 1
            return pid
        if self.cycle:
            pid = self.cycle[self.slow_index % len(self.cycle)]
            self.slow_index += 1
            return pid
        return self.fast[self.fast_index % len(self.fast)] if self.fast else None

    def frame(self, now):
        """(CAN ID, data) to send now, or None. The ID carries the 29-bit flag when extended."""
        self.next_at = now + 1 / REQUEST_HZ
        pid = self.next_pid(now)
        if pid is None:
            return None
        self.sent_count += 1
        return (self.request_id | (0x80000000 if self.extended else 0)), request(pid)

    def sent(self, ok, error=None):
        self.last_error = None if ok else str(error or 'not sent')

    def snapshot(self):
        return {'supported': sorted(p for p in self.supported if p in PIDS), 'answers': self.answers,
                'requests': self.sent_count, 'error': self.last_error}
