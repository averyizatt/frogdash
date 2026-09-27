"""Optional ADS1115 resistance sender input. Disabled until wiring is verified."""
import asyncio
import math
import os
import time

DEFAULTS = dict(enabled=False, bus=1, address=0x48, pullup_ohms=100.,
                points=[[16., 0.], [158., 100.]], smoothing_s=8.)


def validate(settings):
    if not isinstance(settings, dict) or set(settings) != set(DEFAULTS) or type(settings['enabled']) is not bool:
        raise ValueError('Expected all sender settings')
    for key, lo, hi in [('bus', 0, 20), ('address', 0x48, 0x4b)]:
        if type(settings[key]) is not int or not lo <= settings[key] <= hi:
            raise ValueError(f'Invalid sender {key}')
    for key, lo, hi in [('pullup_ohms', 100, 10000), ('smoothing_s', 0, 60)]:
        if type(settings[key]) not in (int, float) or not math.isfinite(settings[key]) or not lo <= settings[key] <= hi:
            raise ValueError(f'Invalid {key}')
    points = settings['points']
    if not isinstance(points, list) or not 2 <= len(points) <= 12:
        raise ValueError('Provide 2–12 resistance/percentage calibration points')
    for point in points:
        if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
            raise ValueError('Invalid calibration point')
        if not 1 <= point[0] <= 10000 or not 0 <= point[1] <= 100:
            raise ValueError('Calibration points out of range')
    if points[0][1] != 0 or points[-1][1] != 100 or any(a[0] >= b[0] or a[1] >= b[1] for a, b in zip(points, points[1:])):
        raise ValueError('Calibration must increase from empty (0%) to full (100%)')
    return {**settings, 'points': [list(p) for p in points]}


def resistance(voltage, supply, pullup):
    if not all(math.isfinite(v) for v in (voltage, supply)) or not 2.8 <= supply <= 3.5:
        raise ValueError('Sender excitation voltage is invalid')
    if voltage <= supply * .001:
        raise ValueError('Sender short circuit or ground fault')
    if voltage >= supply * .98:
        raise ValueError('Sender open circuit or supply short')
    return pullup * voltage / (supply - voltage)


def percentage(ohms, points):
    if not points[0][0] * .5 <= ohms <= points[-1][0] * 1.5:
        raise ValueError('Sender resistance outside plausible range')
    if ohms <= points[0][0]:
        return 0.
    for (r0, p0), (r1, p1) in zip(points, points[1:]):
        if ohms <= r1:
            return p0 + (ohms - r0) * (p1 - p0) / (r1 - r0)
    return 100.


def read_ads1115(bus, address):
    """AIN0=sender divider, AIN1=3.3 V excitation; +/-4.096 V, 128 SPS."""
    import fcntl  # Linux only; no dependency on GPIO libraries.
    fd = os.open(f'/dev/i2c-{bus}', os.O_RDWR)
    try:
        fcntl.ioctl(fd, 0x0703, address)  # I2C_SLAVE
        def reg(index):
            os.write(fd, bytes([index]))
            data = os.read(fd, 2)
            if len(data) != 2:
                raise OSError('Short ADC response')
            return int.from_bytes(data, 'big')
        def channel(index):
            config = 0x8000 | ((4 + index) << 12) | (1 << 9) | 0x100 | 0x80 | 3
            os.write(fd, bytes([1]) + config.to_bytes(2, 'big'))
            deadline = time.monotonic() + .2
            while not reg(1) & 0x8000:
                if time.monotonic() > deadline:
                    raise TimeoutError('ADC conversion timed out')
                time.sleep(.002)
            raw = reg(0)
            if raw & 0x8000:
                raw -= 65536
            return raw * 4.096 / 32768
        return channel(0), channel(1)
    finally:
        os.close(fd)


class FuelSender:
    def __init__(self, state, reader=read_ads1115):
        self.state, self.reader = state, reader
        self.settings = validate(DEFAULTS)
        self.seen = float('-inf')
        self.ohms = self.level = None
        self.quality, self.message = 'unavailable', 'Sender input disabled'
        self.stopping = False
        self.generation = 0

    def configure(self, settings):
        self.settings = validate(settings)
        self.generation += 1
        self.ohms = self.level = None
        self.seen = float('-inf')
        self.quality = 'unavailable'
        self.message = 'Waiting for ADC' if self.settings['enabled'] else 'Sender input disabled'

    def feed(self, voltage, supply):
        now = self.state.clock()
        try:
            ohms = resistance(voltage, supply, self.settings['pullup_ohms'])
            level = percentage(ohms, self.settings['points'])
            tau = self.settings['smoothing_s']
            dt = now - self.seen
            if self.level is not None and self.quality == 'live' and 0 < dt <= 2 and tau:
                level = self.level + (level - self.level) * (1 - math.exp(-dt / tau))
            self.ohms, self.level = ohms, level
            self.quality, self.message = 'live', 'ADS1115 sender · calibrated level estimate'
        except ValueError as exc:
            self.ohms = self.level = None
            self.quality, self.message = 'fault', str(exc)
        self.seen = now

    def snapshot(self):
        quality = self.quality
        if self.settings['enabled'] and self.state.clock() - self.seen > 2:
            quality = 'stale' if self.seen != float('-inf') else 'unavailable'
        return dict(settings=self.settings, quality=quality, message=self.message,
                    ohms=self.ohms, percent=self.level)

    def values(self):
        if not self.settings['enabled']:
            return {}
        status = self.snapshot()
        return {key: dict(value=value, quality=status['quality'], source_id=None, source='ADS1115 fuel sender',
                          timestamp_ms=int(self.state.wall() * 1000)) for key, value in
                [('vehicle.fuel_pct', self.level), ('fuel.sender_ohms', self.ohms)]}

    async def run(self):
        while not self.stopping:
            if self.settings['enabled'] and self.state.mode != 'replay':
                generation = self.generation
                try:
                    values = await asyncio.to_thread(self.reader, self.settings['bus'], self.settings['address'])
                    if generation == self.generation:
                        self.feed(*values)
                except (OSError, ValueError, ImportError) as exc:
                    if generation == self.generation:
                        self.quality, self.message = 'fault', f'ADC unavailable: {type(exc).__name__}'
                        self.ohms = self.level = None
                        self.seen = self.state.clock()
            await asyncio.sleep(.5)
