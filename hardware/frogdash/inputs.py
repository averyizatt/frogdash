"""Car signals from somewhere other than the reference car's own boards.

In the reference car the turn signals, brake, lights and reverse come from the taillight
board (0x100) and the fuel level from the sensor gateway (0x500). Another car chooses, per
signal, in the setup wizard (the system profile's `signals`, sysconfig.SIGNALS):

  ecu    the ECU profile's own reading (ECU_KEYS), when its broadcast has one
  gpio   a Pi pin, through an optocoupler (never 12 V on a pin), active low or high
  adc    the fuel sender's voltage on an ADS1115 (I2C), empty and full in millivolts
  can    a bit of any CAN frame (for fuel: a byte, and the value that means full)
  module the reference car's boards: nothing to do here
  none   not shown

Whatever the source, the dash value is the same one the boards give (TARGETS), so the
indicators, the reverse camera, alerts, logs and the fuel gauge work unchanged. Turn
signals flash: they count as on while a pulse came within FLASH_HOLD_S.

The Pi-pin reader needs python3-libgpiod (setup installs it when a pin is used) and is
imported only then; without it the signals say why they are unavailable.
"""
import os
import threading
import time

TARGETS = {'turn_left': 'lighting.turn_left', 'turn_right': 'lighting.turn_right', 'brake': 'lighting.brake',
           'lights': 'lighting.running', 'reverse': 'lighting.reverse', 'fuel': 'vehicle.fuel_pct'}
ECU_KEYS = {'turn_left': 'ecu.turn_left', 'turn_right': 'ecu.turn_right', 'brake': 'ecu.brake_pedal',
            'lights': 'ecu.headlights', 'reverse': 'ecu.reverse', 'fuel': 'ecu.fuel_level_pct'}
LABELS = {'turn_left': 'Left turn signal', 'turn_right': 'Right turn signal', 'brake': 'Brake', 'lights': 'Lights',
          'reverse': 'Reverse', 'fuel': 'Fuel level'}
FLASH_HOLD_S = 0.8      # A flasher is off for about a third of a second between pulses
CAN_TIMEOUT_S = 1.5
ADC_TIMEOUT_S = 3.0
FUEL_AVERAGE = 20       # ADS1115 samples (5 a second) averaged: the fuel moves in the tank


class Inputs:
    def __init__(self, signals, clock=time.monotonic):
        self.clock = clock
        self.signals = {name: spec for name, spec in (signals or {}).items()
                        if name in TARGETS and spec.get('source') in ('ecu', 'gpio', 'adc', 'can')}
        self.latest = {}          # name -> (value, when)
        self.last_on = {}         # turn signal -> when it was last seen on
        self.fuel_mv = []
        self.problem = {}         # name -> why it is unavailable
        self.by_id = {}
        for name, spec in self.signals.items():
            if spec['source'] == 'can':
                self.by_id.setdefault(spec['can_id'], []).append(name)
        self.lock = threading.Lock()

    def pins(self):
        """{pin: active_low} for the signals on Pi pins."""
        return {spec['pin']: spec['active_low'] for spec in self.signals.values() if spec['source'] == 'gpio'}

    # --- Sources ---
    def ingest(self, can_id, data):
        """A received frame: the bits and bytes chosen in the wizard."""
        for name in self.by_id.get(can_id, ()):
            spec = self.signals[name]
            if name == 'fuel':
                if spec['byte'] >= len(data):
                    continue
                value = min(100.0, data[spec['byte']] * 100 / spec['full_raw'])
            else:
                byte, bit = divmod(spec['bit'], 8)
                if byte >= len(data):
                    continue
                value = bool(data[byte] >> bit & 1)
            self.seen(name, value)

    def gpio(self, levels):
        """Pin levels read now ({pin: True for high})."""
        for name, spec in self.signals.items():
            if spec['source'] == 'gpio' and spec['pin'] in levels:
                self.seen(name, levels[spec['pin']] != spec['active_low'])

    def adc(self, millivolts):
        """The fuel sender's voltage (ADS1115), averaged and turned into percent."""
        spec = self.signals.get('fuel')
        if not spec or spec['source'] != 'adc':
            return
        with self.lock:
            self.fuel_mv = (self.fuel_mv + [millivolts])[-FUEL_AVERAGE:]
            average = sum(self.fuel_mv) / len(self.fuel_mv)
        share = (average - spec['empty_mv']) / (spec['full_mv'] - spec['empty_mv'])
        self.seen('fuel', round(max(0.0, min(1.0, share)) * 100, 1))

    def seen(self, name, value):
        now = self.clock()
        with self.lock:
            self.latest[name] = (value, now)
            if value is True:
                self.last_on[name] = now
            self.problem.pop(name, None)

    def failed(self, names, why):
        with self.lock:
            for name in names:
                self.problem[name] = why

    # --- What the dash shows ---
    def values(self, values, now_ms):
        """Samples for the dash values these signals stand for (TARGETS)."""
        out = {}
        now = self.clock()
        for name, spec in self.signals.items():
            target, source = TARGETS[name], spec['source']
            sample = {'value': None, 'quality': 'unavailable', 'source_id': spec.get('can_id') if source == 'can' else None,
                      'source': f'{source} input', 'timestamp_ms': now_ms}
            if source == 'ecu':
                ecu = values.get(ECU_KEYS[name])
                if ecu:
                    value = ecu['value']
                    if name != 'fuel' and value is not None:
                        value = bool(value)
                        if value:
                            self.last_on[name] = now
                    sample.update(value=value, quality=ecu['quality'], source_id=ecu.get('source_id'), source='ECU')
            else:
                with self.lock:
                    found = self.latest.get(name)
                timeout = CAN_TIMEOUT_S if source == 'can' else ADC_TIMEOUT_S if source == 'adc' else 1.0
                if found and now - found[1] <= timeout:
                    sample.update(value=found[0], quality='live')
                elif found:
                    sample.update(value=found[0], quality='stale')
            if name.startswith('turn_') and sample['quality'] == 'live' and sample['value'] is False:
                sample['value'] = now - self.last_on.get(name, -1e9) <= FLASH_HOLD_S   # Between flashes
            out[target] = sample
        return out

    def view(self):
        """For the setup wizard: each signal's source, last value and any problem."""
        now = self.clock()
        with self.lock:
            return {name: {'source': spec['source'], 'value': self.latest.get(name, (None, 0))[0],
                           'age_s': round(now - self.latest[name][1], 1) if name in self.latest else None,
                           'problem': self.problem.get(name)}
                    for name, spec in self.signals.items()}


# --- Readers (threads), started by the server when a signal needs one ---

def gpio_lines(pins):
    """A function returning {pin: level}, from python3-libgpiod (v2). Raises ImportError or
    OSError when it cannot: the caller reports it."""
    import gpiod                                   # Optional: python3-libgpiod, installed by setup when used
    from gpiod.line import Bias, Direction, Value
    chip_path = None
    for path in sorted(p for p in os.listdir('/dev') if p.startswith('gpiochip')):
        with gpiod.Chip('/dev/' + path) as chip:
            if chip.get_info().label in ('pinctrl-bcm2711', 'pinctrl-bcm2835', 'pinctrl-rp1', 'pinctrl-bcm2712'):
                chip_path = '/dev/' + path
                break
    if not chip_path:
        raise OSError('No Raspberry Pi GPIO chip found')
    config = {pin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP if low else Bias.PULL_DOWN,
                                      debounce_period=None) for pin, low in pins.items()}
    request = gpiod.request_lines(chip_path, consumer='frogdash car signals', config=config)
    order = list(pins)
    return lambda: dict(zip(order, (v == Value.ACTIVE for v in request.get_values(order))))


class ADS1115:
    """An ADS1115 on /dev/i2c-1 at 0x48: one single-ended channel, ±4.096 V, 128 samples/s."""
    I2C_SLAVE = 0x0703

    def __init__(self, bus=1, address=0x48):
        import fcntl                                # Linux only
        self.fd = os.open(f'/dev/i2c-{bus}', os.O_RDWR)
        fcntl.ioctl(self.fd, self.I2C_SLAVE, address)

    def millivolts(self, channel):
        config = 0x8000 | (4 + channel) << 12 | 1 << 9 | 1 << 8 | 4 << 5 | 3
        os.write(self.fd, bytes([1, config >> 8, config & 0xFF]))
        time.sleep(0.012)
        os.write(self.fd, bytes([0]))
        raw = int.from_bytes(os.read(self.fd, 2), 'big', signed=True)
        return raw * 4096 / 32768


def start(inputs, stop=None):
    """Threads for the Pi pins (50 a second) and the ADS1115 (5 a second), if used."""
    stop = stop or threading.Event()
    pins = inputs.pins()
    pin_names = [n for n, s in inputs.signals.items() if s['source'] == 'gpio']
    if pins:
        def read_pins():
            try:
                read = gpio_lines(pins)
            except ImportError:
                return inputs.failed(pin_names, 'python3-libgpiod is not installed yet: run Update (setup installs it)')
            except Exception as exc:
                return inputs.failed(pin_names, f'The Pi pins could not be read: {exc}')
            while not stop.wait(0.02):
                try:
                    inputs.gpio(read())
                except Exception as exc:
                    inputs.failed(pin_names, f'The Pi pins could not be read: {exc}')
                    stop.wait(2)
        threading.Thread(target=read_pins, name='car signals: pins', daemon=True).start()
    fuel = inputs.signals.get('fuel')
    if fuel and fuel['source'] == 'adc':
        def read_adc():
            try:
                adc = ADS1115()
            except Exception as exc:
                return inputs.failed(['fuel'], f'No ADS1115 found on I2C (address 0x48): {exc}')
            while not stop.wait(0.2):
                try:
                    inputs.adc(adc.millivolts(fuel['adc_channel']))
                except Exception as exc:
                    inputs.failed(['fuel'], f'The ADS1115 did not answer: {exc}')
                    stop.wait(2)
        threading.Thread(target=read_adc, name='car signals: fuel sender', daemon=True).start()
    return stop
