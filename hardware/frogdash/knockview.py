"""The knock spectrum sent by the ESP32 water/meth controller (0x30E, can_protocol.h extension 6).

The controller sends two spectra once a second, six values to a frame: what each frequency
normally carries, and the loudest block of the last second. They are put back together
here for the knock page. The single values in the same message (amplifier gain, knock
frequency, second resonance) are ordinary signals, decoded in protocol.py.

The Nano controller never sends 0x30E: `supported` is then false and the page shows what
the Nano does report.
"""
POINTS, PER_FRAME = 36, 6
START_HZ, STEP_HZ = 2000, 300
NORMAL, BURST = 5, 6
TIMEOUT = 3.0


def level_db(byte):
    """A spectrum byte as sent: (dB + 10) * 3."""
    return round(byte / 3 - 10, 1)


class KnockDetail:
    def __init__(self, clock):
        self.clock = clock
        self.reset()

    def reset(self):
        self.seen = None
        self.spectra = {NORMAL: [None] * POINTS, BURST: [None] * POINTS}
        self.stamp = {NORMAL: None, BURST: None}

    @property
    def supported(self):
        return self.seen is not None and self.clock() - self.seen <= TIMEOUT

    def observe(self, data):
        if len(data) != 8:
            return
        self.seen = self.clock()
        kind, first = data[0], data[1]
        if kind in self.spectra and first % PER_FRAME == 0 and first + PER_FRAME <= POINTS:
            self.spectra[kind][first:first + PER_FRAME] = [level_db(value) for value in data[2:8]]
            self.stamp[kind] = self.seen

    def spectrum(self, kind):
        """The whole spectrum, or None until every part of it has arrived recently."""
        stamp, values = self.stamp[kind], self.spectra[kind]
        if stamp is None or self.clock() - stamp > TIMEOUT or any(value is None for value in values):
            return None
        return list(values)

    def snapshot(self):
        return {'supported': self.supported, 'start_hz': START_HZ, 'step_hz': STEP_HZ,
                'normal': self.spectrum(NORMAL), 'burst': self.spectrum(BURST)}
