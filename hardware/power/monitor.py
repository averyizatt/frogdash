#!/usr/bin/env python3
"""PiSugar 3 input-loss monitor. Standard library only; dry-run unless --execute.

The vendor daemon owns I2C. This process requests normal Linux shutdown; the
system-shutdown hook cuts UPS output only after services/filesystems stop.
"""
import argparse
import json
import logging
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import threading


LOG = logging.getLogger('frogdash-power')
DEFAULT_SOCKET = '/tmp/pisugar-server.sock'


class ProtocolError(ValueError):
    pass


class PiSugar:
    def __init__(self, path=DEFAULT_SOCKET, timeout=1.0):
        self.path, self.timeout = path, timeout

    def request(self, command):
        """One bounded transaction; tolerate unsolicited vendor button events."""
        key = command.split()[1] if command.startswith('get ') else command.split()[0]
        prefix = key + ': '
        deadline = time.monotonic() + self.timeout
        pending = b''
        received = 0
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.path)
            connection.sendall((command + '\n').encode('ascii'))
            while received < 8192:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('PiSugar response timed out')
                connection.settimeout(remaining)
                chunk = connection.recv(min(1024, 8192 - received))
                if not chunk:
                    raise ProtocolError('PiSugar closed without a matching response')
                received += len(chunk)
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    decoded = line.decode('utf-8', errors='strict').rstrip('\r')
                    if decoded.startswith(prefix):
                        return decoded[len(prefix):].strip()
                    if decoded not in ('single', 'double', 'long'):
                        raise ProtocolError('Unexpected PiSugar response: ' + decoded[:160])
        raise ProtocolError('PiSugar response exceeded 8192 bytes')

    def boolean(self, field):
        value = self.request('get ' + field)
        if value not in ('true', 'false'):
            raise ProtocolError(f'Invalid {field}: {value[:160]}')
        return value == 'true'

    def verify_model(self):
        if self.request('get model') != 'PiSugar 3':
            raise ProtocolError('Requires PiSugar 3 / 3 Plus, selected as PiSugar 3')

    def input_present(self):
        self.verify_model()
        # Charging=false can mean a full battery; only this field detects input.
        return self.boolean('battery_power_plugged')

    def telemetry(self):
        result = {'errors': []}
        for field, command, limits in (
                ('battery_percent', 'battery', (0, 100)),
                ('battery_volts', 'battery_v', (0, 6)),
                ('charging', 'battery_charging', None),
                ('auto_power_on', 'auto_power_on', None)):
            try:
                value = self.boolean(command) if limits is None else float(self.request('get ' + command))
                if limits is not None and (not math.isfinite(value) or not limits[0] <= value <= limits[1]):
                    raise ProtocolError('Invalid ' + command)
                result[field] = value
            except (OSError, ValueError) as exc:
                result[field] = None
                result['errors'].append(str(exc))
        result['sampled_monotonic'] = time.monotonic()
        return result

    def check(self):
        self.verify_model()
        result = {'model': 'PiSugar 3', 'firmware': self.request('get firmware_version'),
                  'input_present': self.boolean('battery_power_plugged'),
                  'auto_power_on': self.boolean('auto_power_on'),
                  'soft_poweroff': self.boolean('soft_poweroff'),
                  'low_battery_percent': float(self.request('get safe_shutdown_level')),
                  'low_battery_delay_seconds': float(self.request('get safe_shutdown_delay'))}
        if not result['auto_power_on'] or not result['soft_poweroff']:
            raise ProtocolError('Enable auto_power_on and soft_poweroff before commissioning')
        if not (0 < result['low_battery_percent'] <= 30 and 0 <= result['low_battery_delay_seconds'] <= 30):
            raise ProtocolError('Configure low-battery protection before commissioning')
        return result

    def configure(self):
        self.verify_model()
        if not self.boolean('battery_power_plugged'):
            raise ProtocolError('Connect external power before configuring the UPS')
        commands = [('set_auto_power_on true',), ('set_soft_poweroff true',),
                    ('set_soft_poweroff_shell /usr/bin/systemctl poweroff',),
                    ('set_safe_shutdown_level 10', 'safe_shutdown_level 10'),
                    ('set_safe_shutdown_delay 5', 'safe_shutdown_delay 5')]
        for alternatives in commands:
            for index, command in enumerate(alternatives):
                try:
                    if self.request(command) != 'done':
                        raise ProtocolError('PiSugar rejected ' + command)
                    break
                except (ProtocolError, TimeoutError):
                    if index == len(alternatives) - 1:
                        raise
        result = self.check()
        if (result['low_battery_percent'] != 10 or result['low_battery_delay_seconds'] != 5
                or self.request('get soft_poweroff_shell') != '/usr/bin/systemctl poweroff'):
            raise ProtocolError('PiSugar configuration readback did not match requested settings')
        return result


class LossTimer:
    """Require consecutive fresh absent samples, never sum separate crank dips."""
    def __init__(self, delay=8.0, max_gap=2.0):
        if not math.isfinite(delay) or not 5 <= delay <= 10:
            raise ValueError('Input-loss delay must be between 5 and 10 seconds')
        self.delay, self.max_gap = delay, max_gap
        self.since = self.last_sample = None
        self.committed = False

    def update(self, present, now):
        if self.last_sample is not None and (now < self.last_sample or now - self.last_sample > self.max_gap):
            self.since = None
        self.last_sample = now
        if self.committed:
            return {'state': 'shutdown_requested', 'remaining_seconds': 0}
        if present is not False:
            self.since = None
            return {'state': 'external_power' if present is True else 'unavailable', 'remaining_seconds': None}
        if self.since is None:
            self.since = now
        remaining = max(0.0, self.delay - (now - self.since))
        return {'state': 'shutdown_due' if remaining == 0 else 'on_battery',
                'remaining_seconds': round(remaining, 2)}


def request_poweroff():
    # Never call the UPS cutoff binary here. systemd stops the logger first.
    subprocess.run(['/usr/bin/systemctl', '--no-block', 'poweroff'], check=True, timeout=5)


class Monitor:
    def __init__(self, client, delay=8, execute=False, shutdown=request_poweroff):
        self.client, self.execute, self.shutdown = client, execute, shutdown
        self.timer = LossTimer(delay)
        self.next_attempt = 0.0

    def tick(self):
        error = None
        try:
            present = self.client.input_present()
        except (OSError, ValueError) as exc:
            present, error = None, str(exc)
        now = time.monotonic()
        status = self.timer.update(present, now)
        status.update(input_present=present, timestamp=time.time(), monotonic=now, dry_run=not self.execute, error=error)
        if status['state'] == 'shutdown_due':
            if not self.execute:
                status['state'] = 'would_shutdown'
            elif now >= self.next_attempt:
                try:
                    self.shutdown()
                    self.timer.committed = True
                    status['state'] = 'shutdown_requested'
                except (OSError, subprocess.SubprocessError) as exc:
                    status['state'], status['error'] = 'shutdown_failed', str(exc)
                    self.next_attempt = now + 2.0
        return status


def write_status(path, status):
    """Use the root-owned /run directory created by systemd; no SD-card writes."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(status, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', default=DEFAULT_SOCKET)
    parser.add_argument('--loss-delay', type=float, default=8)
    parser.add_argument('--status-file', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true', help='Allow normal systemctl poweroff')
    mode.add_argument('--dry-run', action='store_true', help='Observe only (default)')
    mode.add_argument('--check', action='store_true', help='Read vendor settings and exit')
    mode.add_argument('--configure-vendor', action='store_true', help='Enable restore, soft off and low-battery shutdown')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        monitor = Monitor(PiSugar(args.socket), args.loss_delay, args.execute)
        if args.check or args.configure_vendor:
            result = monitor.client.configure() if args.configure_vendor else monitor.client.check()
            print(json.dumps(result, indent=2))
            return 0
    except (OSError, ValueError) as exc:
        LOG.error('%s', exc)
        return 1
    stopping = False
    telemetry = {}
    telemetry_stop = threading.Event()

    def sample_telemetry():
        nonlocal telemetry
        # Separate, bounded I/O: battery diagnostics must not block the loss timer.
        client = PiSugar(args.socket, timeout=.4)
        while not telemetry_stop.is_set():
            telemetry = client.telemetry()
            telemetry_stop.wait(5)

    worker = threading.Thread(target=sample_telemetry, name='ups-telemetry', daemon=True)
    worker.start()

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        telemetry_stop.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    previous = None
    LOG.info('Monitoring PiSugar input; loss delay %.1fs; %s', args.loss_delay,
             'shutdown enabled' if args.execute else 'DRY RUN')
    while not stopping:
        status = monitor.tick()
        status['ups'] = telemetry
        summary = (status['state'], status['error'])
        if summary != previous:
            LOG.info('%s', json.dumps(status))
            previous = summary
        if args.status_file:
            try:
                write_status(args.status_file, status)
            except OSError as exc:
                LOG.error('Cannot write power status: %s', exc)
        time.sleep(.5)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
