"""Mirror of the CustomTaillights settings, kept in sync from its 0x103 reports.

The controller reports a revision counter every 500 ms. When it changes (a setting,
profile or defaults changed from any source), the dashboard asks for a full report.
"""
# can_protocol.h taillight_setting keys 1..21 with their ranges.
SETTINGS = {
    1: ('brightness', 10, 255), 2: ('brightness_dim', 5, 35), 3: ('turn_blink_ms', 200, 1500),
    4: ('turn_custom', 0, 1), 5: ('turn_sweep_ms', 50, 1500), 6: ('turn_hold_ms', 0, 1500),
    7: ('turn_off_ms', 50, 1500), 8: ('brake_speed', 50, 200), 9: ('reverse_speed', 50, 200),
    10: ('run_speed', 50, 200), 11: ('frame_ms', 10, 100), 12: ('brake_anim', 0, 6),
    13: ('turn_anim', 0, 7), 14: ('reverse_anim', 0, 3), 15: ('run_anim', 0, 5),
    16: ('lens_preset', 0, 3), 17: ('startup_anim', 0, 1), 18: ('rest_mode', 0, 1),
    19: ('show_speed', 50, 200), 20: ('show_anim', 0, 35), 21: ('show_mode', 0, 1)}
KEYS = {name: key for key, (name, _, _) in SETTINGS.items()}
COLORS = ('brake', 'turn', 'reverse', 'running')
FLAGS = {'unsaved': 1, 'show': 2, 'demo': 4, 'custom': 8, 'override': 16}
PROFILE_COUNT = 6
STATUS_TIMEOUT = 1.5
REPORT_RETRY = 2.0


class TaillightSettings:
    def __init__(self, clock):
        self.clock = clock
        self.reset()

    def reset(self):
        self.values, self.colors = {}, {}
        self.text = bytearray(64)
        self.text_length = None
        self.revision = self.flags = self.show_anim = self.profiles = self.phase_ms = None
        self.status_seen = None
        self.reported_revision = None  # Revision the current values belong to.
        self.requested_at = None
        self.requested_revision = None
        self.last_ack = None

    @property
    def supported(self):
        """Firmware with the settings extension reports status every 500 ms."""
        return self.status_seen is not None and self.clock() - self.status_seen <= STATUS_TIMEOUT

    def observe(self, data):
        kind = data[0]
        if kind == 1:
            self.last_ack = {'command': data[1], 'status': data[2], 'subject': data[3],
                             'value': int.from_bytes(data[4:6], 'big'), 'revision': data[6]}
        elif kind == 2 and data[1] in SETTINGS:
            self.values[SETTINGS[data[1]][0]] = int.from_bytes(data[2:4], 'big')
            self.reported_revision = data[4]
        elif kind == 3 and data[1] < len(COLORS):
            self.colors[COLORS[data[1]]] = '#' + data[2:5].hex()
            self.reported_revision = data[5]
        elif kind == 4 and data[1] <= 63:
            chunk = bytes(data[2:8])
            end = chunk.find(0)
            usable = chunk if end < 0 else chunk[:end]
            self.text[data[1]:data[1] + len(usable)] = usable[:64 - data[1]]
            if end >= 0 or data[1] + 6 >= 64:
                self.text_length = data[1] + len(usable)
        elif kind == 5:
            self.revision, self.flags, self.show_anim, self.profiles = data[1], data[2], data[3], data[4]
            self.phase_ms = int.from_bytes(data[5:7], 'big') * 16
            self.status_seen = self.clock()

    def complete(self):
        return (len(self.values) == len(SETTINGS) and len(self.colors) == len(COLORS)
                and self.text_length is not None and self.reported_revision == self.revision)

    def needs_report(self):
        """True when the mirror is out of date and no report request is in flight."""
        if not self.supported or self.complete():
            return False
        if self.requested_revision != self.revision:
            return True  # Changed since the last request: ask again right away.
        return self.clock() - self.requested_at >= REPORT_RETRY

    def requested(self):
        self.requested_at = self.clock()
        self.requested_revision = self.revision
        self.text_length = None

    def snapshot(self):
        flags = self.flags or 0
        return {'supported': self.supported, 'complete': self.complete(), 'revision': self.revision,
                **{name: bool(flags & bit) for name, bit in FLAGS.items()},
                'show_anim': self.show_anim, 'phase_ms': self.phase_ms,
                'profiles': [bool((self.profiles or 0) & (1 << slot)) for slot in range(PROFILE_COUNT)],
                'settings': dict(self.values), 'colors': dict(self.colors),
                'text': self.text[:self.text_length or 0].decode('ascii', 'replace') if self.text_length is not None else None,
                'last_ack': self.last_ack}
