"""Bounded background MLG recorder; all filesystem work runs off the CAN loop."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import logging
import math
import os
from pathlib import Path
import re
import shutil
import time
from uuid import uuid4

from .log_channels import FIELDS, info, row_values
from .mlg import Encoder

LOG = logging.getLogger(__name__)
NAME = re.compile(r'^frogdash-(live|replay)-\d{8}T\d{6}Z-[0-9a-f]{12}\.mlg$')
MIB = 1024 * 1024


@dataclass(frozen=True)
class Config:
    directory: Path
    hz: float = 20
    seconds: float = 1800
    file_bytes: int = 32 * MIB
    total_bytes: int = 2048 * MIB
    free_bytes: int = 256 * MIB

    def __post_init__(self):
        if not math.isfinite(self.hz) or not 1 <= self.hz <= 100:
            raise ValueError('Log sample rate must be between 1 and 100 Hz')
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError('Log rotation duration must be positive')
        if self.file_bytes < 65536 or self.total_bytes < self.file_bytes * 2 or self.free_bytes < 0:
            raise ValueError('Log size must be >=64 KiB, budget >=2 files, and free-space reserve >=0')


def inventory(directory):
    """Only files owned by this recorder. No symlinks, directories or arbitrary MLGs."""
    files = []
    if not directory.exists():
        return files
    for path in directory.iterdir():
        if NAME.fullmatch(path.name) and not path.is_symlink() and path.is_file():
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            files.append((path, stat.st_size, stat.st_mtime))
    return sorted(files, key=lambda item: (item[2], item[0].name))


class RotatingWriter:
    """Single-thread-owned disk writer; active files are never retention victims."""
    def __init__(self, config, mode='socketcan', disk_usage=shutil.disk_usage):
        self.config, self.mode, self.disk_usage = config, mode, disk_usage
        self.file = self.path = self.lock = None
        self.encoder = None
        self.bytes = self.rows = self.retained_bytes = 0
        self.started = self.last_sync = self.last_prune = 0
        self.closed = False

    def acquire(self):
        if self.lock:
            return
        directory = self.config.directory
        directory.mkdir(parents=True, exist_ok=True)
        lock = (directory / '.frogdash-recorder.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if lock.seek(0, 2) == 0:
                    lock.write(b'0')
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            raise OSError('Another recorder owns this log directory') from None
        self.lock = lock

    def prune(self, required):
        files = inventory(self.config.directory)
        self.retained_bytes = sum(max(size, self.bytes) if path == self.path else size for path, size, _ in files)
        free = self.disk_usage(self.config.directory).free
        for path, size, _ in files:
            if self.retained_bytes + required <= self.config.total_bytes and free >= self.config.free_bytes + required:
                break
            if path == self.path:
                continue
            path.unlink()
            self.retained_bytes -= size
            free = self.disk_usage(self.config.directory).free
        if self.retained_bytes + required > self.config.total_bytes or free < self.config.free_bytes + required:
            raise OSError(errno.ENOSPC, 'Log storage budget or free-space reserve reached')

    def finish_file(self):
        if self.file:
            stream, self.file = self.file, None
            try:
                stream.flush()
                os.fsync(stream.fileno())
                if os.name == 'posix':
                    directory_fd = os.open(self.config.directory, os.O_DIRECTORY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            finally:
                try:
                    stream.close()
                finally:
                    self.path = None

    def write(self, snapshot, now, dropped=0):
        if self.closed:
            raise RuntimeError('Recorder is closed')
        self.acquire()
        record_size = 5 + sum(1 if f.kind == 0 else 4 for f in FIELDS)
        if self.file and (now - self.started >= self.config.seconds or self.bytes + record_size > self.config.file_bytes):
            self.finish_file()
        if not self.file:
            stamp = snapshot['timestamp_ms'] / 1000
            self.encoder = Encoder(FIELDS, stamp, info(self.mode, self.config.hz))
            self.prune(len(self.encoder.header) + record_size)
            date = datetime.fromtimestamp(stamp, timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            source = 'replay' if self.mode == 'replay' else 'live'
            self.path = self.config.directory / f'frogdash-{source}-{date}-{uuid4().hex[:12]}.mlg'
            self.file = self.path.open('xb')
            self.file.write(self.encoder.header)
            self.bytes = len(self.encoder.header)
            self.retained_bytes += self.bytes
            self.rows = 0
            self.started = self.last_sync = self.last_prune = now
        elapsed = max(0, now - self.started)
        packet = self.encoder.row(elapsed, row_values(snapshot, elapsed, dropped))
        if now - self.last_prune >= 1 or self.retained_bytes + len(packet) > self.config.total_bytes:
            # Reserve room for the next second between free-space checks.
            self.prune(math.ceil(len(packet) * (self.config.hz + 1)))
            self.last_prune = now
        self.file.write(packet)
        self.bytes += len(packet)
        self.retained_bytes += len(packet)
        self.rows += 1
        if self.rows == 1 or now - self.last_sync >= 5:
            self.file.flush()
            os.fsync(self.file.fileno())
            self.last_sync = now

    def close(self):
        try:
            self.finish_file()
        finally:
            if self.lock:
                self.lock.close()
                self.lock = None
            self.closed = True


class Recorder:
    def __init__(self, state, config):
        self.state, self.config = state, config
        self.writer = RotatingWriter(config, state.mode)
        self.queue = asyncio.Queue(maxsize=max(20, math.ceil(config.hz * 2)))
        self.tasks = []
        self.dropped = 0
        self.written = 0
        self.status = {'enabled': True, 'state': 'starting', 'file': None, 'rows': 0,
                       'dropped': 0, 'error': None, 'hz': config.hz}

    def start(self):
        self.tasks = [asyncio.create_task(self.produce()), asyncio.create_task(self.consume())]

    async def produce(self):
        interval = 1 / self.config.hz
        deadline = time.monotonic()
        while True:
            now = time.monotonic()
            snapshot = self.state.snapshot()
            try:
                self.queue.put_nowait((snapshot, now))
            except asyncio.QueueFull:
                self.dropped += 1
            deadline += interval
            if deadline < now:
                missed = int((now - deadline) / interval) + 1
                self.dropped += missed
                deadline += missed * interval
            await asyncio.sleep(max(0, deadline - time.monotonic()))

    async def consume(self):
        retry_at = 0
        while True:
            item = await self.queue.get()
            try:
                if item is None:
                    return
                snapshot, stamp = item
                if time.monotonic() < retry_at:
                    self.dropped += 1
                    self.status = {**self.status, 'dropped': self.dropped}
                    continue
                try:
                    await asyncio.to_thread(self.writer.write, snapshot, stamp, self.dropped)
                    self.written += 1
                    self.status = {'enabled': True, 'state': 'recording', 'file': self.writer.path.name,
                                   'rows': self.written, 'dropped': self.dropped, 'error': None, 'hz': self.config.hz}
                except OSError as exc:
                    self.dropped += 1
                    try:
                        await asyncio.to_thread(self.writer.finish_file)
                    except OSError:
                        pass
                    self.status = {'enabled': True, 'state': 'error', 'file': None, 'rows': self.written,
                                   'dropped': self.dropped, 'error': str(exc), 'hz': self.config.hz}
                    LOG.error('MLG recorder paused; retrying in 30 seconds: %s', exc)
                    retry_at = time.monotonic() + 30
            finally:
                self.queue.task_done()

    async def close(self):
        if self.tasks:
            self.tasks[0].cancel()
            await asyncio.gather(self.tasks[0], return_exceptions=True)
            await self.queue.put(None)
            # Drain accepted samples and finish the file; never cancel an in-flight
            # to_thread write and race it with close/rotation on another thread.
            await self.tasks[1]
        await asyncio.to_thread(self.writer.close)
        self.status = {**self.status, 'state': 'stopped', 'file': None}

    def files(self):
        active = self.writer.path
        return [{'name': path.name, 'bytes': size, 'modified_ms': int(stamp * 1000), 'active': path == active}
                for path, size, stamp in reversed(inventory(self.config.directory))]
