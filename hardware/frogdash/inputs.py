"""Car signals from somewhere other than the reference car's own boards.

In the reference car the turn signals, brake, lights and reverse come from the taillight
board (0x100) and the fuel level from the sensor gateway (0x500). High beam and parking
brake come from no board: any car, the reference one included, can wire them here. Each
car chooses, per signal, in the setup wizard (the system profile's `signals`,
sysconfig.SIGNALS):

  ecu    the ECU profile's own reading (ECU_KEYS), when its broadcast has one
  gpio   a Pi pin, through an optocoupler (never 12 V on a pin), active low or high
  adc    the fuel sender's voltage on an ADS1115 (I2C), empty and full in millivolts
  can    a bit of any CAN frame (for fuel: a byte, and the value that means full)
  module the reference car's boards: nothing to do here
  none   not shown

Whatever the source, the dash value is the same one the boards give (TARGETS), so the
indicators, the reverse camera, alerts, logs and the fuel gauge work unchanged. Turn
signals flash: they count as on while a pulse came within FLASH_HOLD_S.

Analog sensors (the system profile's `sensors`, a0-a3: the ADS1115's inputs not used for the
fuel level): a sender with a straight-line output (0.5-4.5 V pressure senders and the like),
calibrated by two points, or a thermistor temperature sender with a pull-up resistor,
calibrated by three (Steinhart-Hart). Volts are the sender's own: the input's reading
divided by the divider in front of it (a 5 V sender needs one: the ADS1115 reads at most
4.096 V). Each feeds a dash reading (SENSOR_READINGS) or one of its own (sensor.a0...).

The Pi-pin reader needs python3-libgpiod (setup installs it when a pin is used) and is
imported only then; without it the signals say why they are unavailable.
"""
import math
import os
import threading
import time

TARGETS = {'turn_left': 'lighting.turn_left', 'turn_right': 'lighting.turn_right', 'brake': 'lighting.brake',
           'lights': 'lighting.running', 'reverse': 'lighting.reverse', 'highbeam': 'lighting.highbeam',
           'parking_brake': 'lighting.parking_brake', 'fuel': 'vehicle.fuel_pct'}
ECU_KEYS = {'turn_left': 'ecu.turn_left', 'turn_right': 'ecu.turn_right', 'brake': 'ecu.brake_pedal',
            'lights': 'ecu.headlights', 'reverse': 'ecu.reverse', 'highbeam': 'ecu.high_beam',
            'parking_brake': 'ecu.parking_brake', 'fuel': 'ecu.fuel_level_pct'}
LABELS = {'turn_left': 'Left turn signal', 'turn_right': 'Right turn signal', 'brake': 'Brake', 'lights': 'Lights',
          'reverse': 'Reverse', 'highbeam': 'High beam', 'parking_brake': 'Parking brake', 'fuel': 'Fuel level'}
SENSOR_CHANNELS = ('a0', 'a1', 'a2', 'a3')
# The dash reading an analog sensor can feed, and the unit its calibration values are in.
SENSOR_READINGS = {'oil_pressure': 'engine.oil_pressure_psi', 'fuel_pressure': 'engine.fuel_pressure_psi',
                   'oil_temp': 'engine.oil_temp_c', 'coolant': 'engine.coolant_c', 'iat': 'engine.iat_c',
                   'trans_temp': 'sensor.trans_temp_c'}
TEMPERATURE_READINGS = ('oil_temp', 'coolant', 'iat', 'trans_temp')
SENSOR_UNITS = {'none': '', 'psi': '_psi', 'kpa': '_kpa', 'c': '_c', 'v': '_v', 'pct': '_pct'}
SENSOR_AVERAGE = 3
FLASH_HOLD_S = 0.8      # A flasher is off for about a third of a second between pulses
CAN_TIMEOUT_S = 1.5
ADC_TIMEOUT_S = 3.0
FUEL_AVERAGE = 20       # ADS1115 samples (5 a second) averaged: the fuel moves in the tank


def sensor_key(channel, spec):
    """The dash reading an analog sensor gives: one the dash has, or sensor.a0 (with its unit)."""
    if spec['reading'] != 'custom':
        return SENSOR_READINGS[spec['reading']]
    return f"sensor.{channel}{'_c' if spec['type'] == 'thermistor' else SENSOR_UNITS[spec['unit']]}"


def sensor_keys(sensors):
    return [sensor_key(ch, spec) for ch, spec in (sensors or {}).items() if spec.get('type', 'none') != 'none']


def steinhart(points):
    """Steinhart-Hart A, B, C from three (ohms, degC) points."""
    (r1, t1), (r2, t2), (r3, t3) = points
    l1, l2, l3 = math.log(r1), math.log(r2), math.log(r3)
    y1, y2, y3 = 1 / (t1 + 273.15), 1 / (t2 + 273.15), 1 / (t3 + 273.15)
    g2, g3 = (y2 - y1) / (l2 - l1), (y3 - y1) / (l3 - l1)
    c = (g3 - g2) / (l3 - l2) / (l1 + l2 + l3)
    b = g2 - c * (l1 * l1 + l1 * l2 + l2 * l2)
    return y1 - (b + l1 * l1 * c) * l1, b, c


def sensor_value(spec, mv):
    """The reading for the sender's own voltage, or None (open or shorted: a fault)."""
    if spec['type'] == 'linear':
        return spec['v1_value'] + (mv - spec['v1_mv']) * (spec['v2_value'] - spec['v1_value']) / (spec['v2_mv'] - spec['v1_mv'])
    if spec['type'] == 'thermistor':
        if not 0 < mv < spec['supply_mv'] * 0.995:
            return None
        ohms = spec['pullup_ohm'] * mv / (spec['supply_mv'] - mv)
        a, b, c = steinhart([(spec['r1_ohm'], spec['t1_c']), (spec['r2_ohm'], spec['t2_c']), (spec['r3_ohm'], spec['t3_c'])])
        ln = math.log(ohms)
        inverse = a + b * ln + c * ln ** 3
        return None if inverse <= 0 else 1 / inverse - 273.15
    return None


class Inputs:
    def __init__(self, signals, sensors=None, clock=time.monotonic):
        self.clock = clock
        self.sensors = {ch: spec for ch, spec in (sensors or {}).items() if ch in SENSOR_CHANNELS and spec.get('type', 'none') != 'none'}
        self.sensor_mv = {}       # channel -> the sender's volts, the last few
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

    def analog(self, channel, input_mv):
        """One reading of an ADS1115 input used by an analog sensor (a0-a3)."""
        spec = self.sensors.get(channel)
        if not spec:
            return
        with self.lock:
            recent = self.sensor_mv[channel] = (self.sensor_mv.get(channel, []) + [input_mv * 100 / spec['divider_pct']])[-SENSOR_AVERAGE:]
            mv = sum(recent) / len(recent)
        value = sensor_value(spec, mv)
        self.seen(f'sensor.{channel}', None if value is None or not math.isfinite(value) else round(value, 3))

    def adc_inputs(self):
        """The ADS1115 inputs to read: the fuel sender's and the analog sensors'."""
        wanted = [int(ch[1]) for ch in self.sensors]
        fuel = self.signals.get('fuel')
        if fuel and fuel['source'] == 'adc':
            wanted.append(fuel['adc_channel'])
        return sorted(set(wanted))

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
        for channel, spec in self.sensors.items():
            sample = {'value': None, 'quality': 'unavailable', 'source_id': None, 'source': f'sensor {channel.upper()}', 'timestamp_ms': now_ms}
            with self.lock:
                found = self.latest.get(f'sensor.{channel}')
            if found:
                fresh = now - found[1] <= ADC_TIMEOUT_S
                sample.update(value=found[0], quality='fault' if found[0] is None and fresh else 'live' if fresh else 'stale')
            out[sensor_key(channel, spec)] = sample
        return out

    def view(self):
        """For the setup wizard: each signal's source, last value and any problem, and each
        analog sensor's volts and reading."""
        now = self.clock()
        with self.lock:
            out = {name: {'source': spec['source'], 'value': self.latest.get(name, (None, 0))[0],
                          'age_s': round(now - self.latest[name][1], 1) if name in self.latest else None,
                          'problem': self.problem.get(name)}
                   for name, spec in self.signals.items()}
            out['sensors'] = {}
            for channel, spec in self.sensors.items():
                name, recent = f'sensor.{channel}', self.sensor_mv.get(channel)
                out['sensors'][channel] = {'key': sensor_key(channel, spec), 'value': self.latest.get(name, (None, 0))[0],
                                           'volts': round(sum(recent) / len(recent) / 1000, 3) if recent else None,
                                           'age_s': round(now - self.latest[name][1], 1) if name in self.latest else None,
                                           'problem': self.problem.get(name)}
            return out


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
    fuel_input = fuel['adc_channel'] if fuel and fuel['source'] == 'adc' else None
    wanted = inputs.adc_inputs()
    if wanted:
        users = (['fuel'] if fuel_input is not None else []) + [f'sensor.{ch}' for ch in inputs.sensors]
        def read_adc():
            try:
                adc = ADS1115()
            except Exception as exc:
                return inputs.failed(users, f'No ADS1115 found on I2C (address 0x48): {exc}')
            while not stop.wait(0.2):
                try:
                    for index in wanted:
                        mv = adc.millivolts(index)
                        if index == fuel_input:
                            inputs.adc(mv)
                        inputs.analog(f'a{index}', mv)
                except Exception as exc:
                    inputs.failed(users, f'The ADS1115 did not answer: {exc}')
                    stop.wait(2)
        threading.Thread(target=read_adc, name='car signals: ADS1115', daemon=True).start()
    return stop
