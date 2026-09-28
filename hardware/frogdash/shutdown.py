"""Durable evidence of application cleanup, not proof of physical power cutoff."""
from copy import deepcopy
import json
import logging
import math
from pathlib import Path
import time
from uuid import uuid4

from .driving import atomic_write

LOG = logging.getLogger(__name__)


def boot_id():
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip() or None
    except OSError:
        return None


def valid_record(record):
    if not isinstance(record, dict) or not isinstance(record.get('run_id'), str):
        return False
    if record.get('state') == 'running':
        return True
    if record.get('state') not in ('saved', 'save_failed'):
        return False
    ended = record.get('ended_ms')
    errors = record.get('errors')
    return (type(ended) in (int, float) and math.isfinite(ended) and ended > 0
            and type(record.get('recording_enabled')) is bool
            and isinstance(errors, list) and all(isinstance(error, str) for error in errors)
            and (not errors if record['state'] == 'saved' else bool(errors)))


class ShutdownHistory:
    def __init__(self, path, boot=None):
        self.path = Path(path)
        self.boot = boot if boot is not None else boot_id()
        self.document = None
        self.error = ''
        self.started = False

    def start(self):
        previous = None
        interruptions = 0
        try:
            if self.path.stat().st_size > 65536:
                raise ValueError('Oversized shutdown record')
            old = json.loads(self.path.read_text(encoding='utf-8'))
            current = old['current']
            if old.get('version') != 1 or not valid_record(current):
                raise ValueError('Invalid shutdown record')
            previous = old.get('previous')
            if previous is not None and not valid_record(previous):
                raise ValueError('Invalid previous shutdown record')
            if self.boot and current.get('boot_id') == self.boot:
                # Restarting the dashboard must not erase the previous boot's result.
                interruptions = int(current.get('interruptions', 0)) + (current['state'] != 'saved')
            else:
                previous = current
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            previous = None
            self.error = 'Previous shutdown record unreadable; completion cannot be confirmed'
        self.document = {'version': 1, 'previous': previous, 'current': {
            'boot_id': self.boot, 'scope': 'boot' if self.boot else 'service',
            'run_id': uuid4().hex, 'started_ms': int(time.time() * 1000),
            'ended_ms': None, 'state': 'running', 'interruptions': interruptions}}
        try:
            atomic_write(self.path, self.document)
            self.started = True
        except OSError as exc:
            self.error = 'Cannot persist shutdown tracking: ' + str(exc)
            LOG.error('%s', self.error)

    def finish(self, state):
        if not self.started:
            return
        errors = [message for message in (
            state.trip.error, state.driving.storage_error, state.driving.settings_error,
            state.race.storage_error, state.operations.error,
            state.recorder.status.get('error') if state.recorder else None) if message]
        self.document['current'].update(
            state='save_failed' if errors else 'saved', ended_ms=int(time.time() * 1000),
            errors=errors, recording_enabled=state.recorder is not None,
            log_rows=state.recorder.written if state.recorder else 0,
            dropped_samples=state.recorder.dropped if state.recorder else 0)
        try:
            # Written only AFTER all producers stop, accepted MLG rows drain,
            # files fsync/close, and trip/review/race saves complete.
            atomic_write(self.path, self.document)
        except OSError as exc:
            self.error = 'Shutdown completion could not be synced: ' + str(exc)
            LOG.error('%s', self.error)

    def snapshot(self):
        return {'previous': deepcopy(self.document.get('previous')) if self.document else None,
                'tracking': self.started, 'error': self.error,
                'scope': 'boot' if self.boot else 'service'}
