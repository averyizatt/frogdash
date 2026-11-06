"""The Log viewer (Drive > Log viewer): the dash's MLG logs read back for graphs on the screen.

A log is read one channel at a time and only as far as it is asked for: the file is mapped,
its data blocks found once, and each channel unpacked in C (struct.iter_unpack over the
blocks, the other bytes skipped). A drive of an hour at 20 Hz with two hundred fields is
never held whole in Python objects. Wire layout: EFI Analytics MLG_Binary_LogFormat_2.0.pdf,
the same as hardware/frogdash/mlg.py writes and tools/inspect_mlg.py checks.

A long range is thinned for the screen: each stretch of samples becomes its lowest and its
highest value, so a spike is never lost when the whole drive is shown (MegaLogViewer does
the same). Non-live readings are NaN in the log and come back as gaps (None).
"""
from array import array
from bisect import bisect_left, bisect_right
from collections import OrderedDict
import math
import mmap
from pathlib import Path
import struct

FORMATS = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'q', 7: 'f', 10: 'B', 11: 'H', 12: 'I'}
MARKER_BYTES = 53          # A marker block after its type byte: counter, timestamp, 50 bytes of text
MAX_POINTS = 4000
# Recorder bookkeeping and each channel's quality flag: in the file, not worth a graph.
HIDDEN_CATEGORIES = {'Quality', 'Recorder'}


class LogError(ValueError):
    pass


def text(raw):
    return raw.split(b'\0')[0].decode('utf-8', errors='replace')


class Log:
    """One MLG file, mapped. Channels are read when first asked for and kept (see LogCache)."""

    def __init__(self, path):
        self.path = Path(path)
        stat = self.path.stat()
        self.key = (stat.st_size, stat.st_mtime_ns)
        with self.path.open('rb') as stream:
            self.data = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) if stat.st_size else b''
        self.columns = {}
        self.header()
        self.blocks()

    def close(self):
        if isinstance(self.data, mmap.mmap):
            self.data.close()

    def header(self):
        d = self.data
        if len(d) < 8 or d[:6] != b'MLVLG\0':
            raise LogError('Not an MLG log')
        self.version = int.from_bytes(d[6:8], 'big')
        if self.version == 2:
            self.timestamp, info_start, data_start, size, count = struct.unpack_from('>IIIHH', d, 8)
            field_size, at = 89, 24
        elif self.version == 1:
            self.timestamp, info_start, data_start, size, count = struct.unpack_from('>IHIHH', d, 8)
            field_size, at = 55, 22
        else:
            raise LogError(f'MLG version {self.version} is not supported')
        if not count or data_start > len(d) or at + count * field_size > len(d):
            raise LogError('The log header is damaged')
        self.fields, offset = [], 0
        for index in range(count):
            raw = d[at + index * field_size:at + (index + 1) * field_size]
            kind = raw[0]
            if kind not in FORMATS:
                raise LogError(f'Field type {kind} is not supported')
            scale, transform = struct.unpack('>ff', raw[46:54]) if kind < 10 else (1.0, 0.0)
            self.fields.append({'name': text(raw[1:35]), 'units': text(raw[35:45]), 'kind': kind, 'offset': offset,
                                'scale': scale if math.isfinite(scale) and scale else 1.0,
                                'transform': transform if math.isfinite(transform) else 0.0,
                                'digits': raw[54] if self.version == 2 and raw[54] < 10 else 2,
                                'category': text(raw[55:89]) if self.version == 2 else ''})
            offset += struct.calcsize('>' + FORMATS[kind])
        if offset != size:
            raise LogError('The log header does not match its records')
        self.size, self.data_start = size, data_start
        self.info = text(d[info_start:data_start]) if info_start and info_start < data_start else ''
        self.by_name = {f['name']: f for f in self.fields}

    def blocks(self):
        """The runs of data blocks between markers, as (first byte, rows), and the markers."""
        d, at, stride = self.data, self.data_start, self.size + 5   # type, counter, 2-byte timestamp, record, checksum
        self.runs, self.markers, rows, start = [], [], 0, None
        while at < len(d):
            kind = d[at]
            if kind == 0:
                if at + stride > len(d):
                    break                        # The block being written: left for the next read
                if start is None:
                    start = at
                rows += 1
                at += stride
                continue
            if start is not None:
                self.runs.append((start, rows)); start, rows = None, 0
            if kind == 1 and at + 1 + MARKER_BYTES <= len(d):
                self.markers.append((sum(r for _, r in self.runs), text(d[at + 4:at + 1 + MARKER_BYTES])))
                at += 1 + MARKER_BYTES
                continue
            break                                # Anything else: the rest is not a log
        if start is not None:
            self.runs.append((start, rows))
        self.rows = sum(r for _, r in self.runs)

    def column(self, name):
        """Every value of one field, scaled, as an array of floats (NaN for no reading)."""
        if name in self.columns:
            return self.columns[name]
        field = self.by_name.get(name)
        if field is None:
            raise LogError(f'No channel {name} in this log')
        size = struct.calcsize('>' + FORMATS[field['kind']])
        before = 4 + field['offset']                         # type, counter, timestamp
        after = self.size + 5 - before - size
        row = struct.Struct(f'>{before}x{FORMATS[field["kind"]]}{after}x')
        out = array('d')
        scale, transform, integer = field['scale'], field['transform'], field['kind'] != 7
        for start, rows in self.runs:
            for (value,) in row.iter_unpack(self.data[start:start + rows * row.size]):
                out.append((value + transform) * scale if integer or math.isfinite(value) else math.nan)
        self.columns[name] = out
        return out

    def times(self):
        """Seconds since the log started: its Time channel (the dash writes one), else the
        blocks' own 10 microsecond counter, which wraps every 655 ms."""
        if 'Time' in self.by_name:
            return self.column('Time')
        if '__ticks' not in self.columns:
            out, total, last = array('d'), 0, None
            for start, rows in self.runs:
                for (tick,) in struct.Struct(f'>2xH{self.size + 1}x').iter_unpack(self.data[start:start + rows * (self.size + 5)]):
                    total += 0 if last is None else (tick - last) & 0xFFFF
                    last = tick
                    out.append(total / 100_000)
            self.columns['__ticks'] = out
        return self.columns['__ticks']

    def bookmarks(self):
        """Each B press, from the log itself: the dash writes the bookmark's number in its
        Bookmark ID channel, so the moment it changes is the moment it was pressed."""
        if 'Bookmark ID' not in self.by_name or not self.rows:
            return []
        times, ids, found, last = self.times(), self.column('Bookmark ID'), [], None
        for index, value in enumerate(ids):
            if math.isnan(value) or value == last:
                continue
            if last is not None and value > 0:
                found.append({'t': round(times[index] - times[0], 3), 'text': f'Bookmark {int(value)}'})
            last = value
        return found

    def describe(self):
        times = self.times()
        shown = [f for f in self.fields if f['category'] not in HIDDEN_CATEGORIES and f['name'] != 'Time']
        return {'name': self.path.name, 'version': self.version, 'rows': self.rows,
                'started_s': self.timestamp, 'duration_s': round(times[-1] - times[0], 3) if self.rows else 0,
                'channels': [{k: f[k] for k in ('name', 'units', 'category', 'digits')} for f in shown],
                'markers': [{'t': round(times[min(row, self.rows - 1)] - times[0], 3), 'text': message}
                            for row, message in self.markers if self.rows] + self.bookmarks()}

    def series(self, names, start=None, end=None, points=2000):
        """Time (seconds from the start) and each channel between start and end, at most about
        `points` samples: thinned to each stretch's lowest and highest value."""
        times = self.times()
        if not self.rows:
            return {'t': [], 'series': {name: [] for name in names}, 'thinned': False}
        origin = times[0]
        lo = bisect_left(times, origin + start) if start is not None else 0
        hi = bisect_right(times, origin + end) if end is not None else self.rows
        lo, hi = max(0, lo - 1), min(self.rows, hi + 1)          # One beyond each edge: lines reach the sides
        columns = [self.column(name) for name in names]
        points = max(10, min(int(points), MAX_POINTS))
        count = hi - lo
        clean = lambda v: None if math.isnan(v) or math.isinf(v) else round(v, 4)
        if count <= points:
            return {'t': [round(times[i] - origin, 3) for i in range(lo, hi)],
                    'series': {name: [clean(c[i]) for i in range(lo, hi)] for name, c in zip(names, columns)}, 'thinned': False}
        buckets = points // 2
        t, series = [], {name: [] for name in names}
        for b in range(buckets):
            a, z = lo + count * b // buckets, lo + count * (b + 1) // buckets
            if a >= z:
                continue
            t += [round(times[a] - origin, 3), round(times[z - 1] - origin, 3)]
            for name, c in zip(names, columns):
                values = [v for v in c[a:z] if not math.isnan(v) and not math.isinf(v)]
                series[name] += [round(min(values), 4), round(max(values), 4)] if values else [None, None]
        return {'t': t, 'series': series, 'thinned': True}

    def stats(self, names, start=None, end=None):
        """Lowest, average and highest of each channel in a range, from every sample."""
        times = self.times()
        if not self.rows:
            return {}
        origin = times[0]
        lo = bisect_left(times, origin + start) if start is not None else 0
        hi = bisect_right(times, origin + end) if end is not None else self.rows
        result = {}
        for name in names:
            values = [v for v in self.column(name)[lo:hi] if not math.isnan(v) and not math.isinf(v)]
            result[name] = {'min': round(min(values), 4), 'avg': round(sum(values) / len(values), 4), 'max': round(max(values), 4)} if values else None
        return result


class LogCache:
    """The last few logs opened, so zooming and panning read nothing again. A log still being
    written (or rotated) is opened again when its size or time changes."""

    def __init__(self, keep=2):
        self.keep, self.logs = keep, OrderedDict()

    def open(self, path):
        path = Path(path)
        stat = path.stat()
        log = self.logs.get(path)
        if log is None or log.key != (stat.st_size, stat.st_mtime_ns):
            if log:
                log.close()
            log = Log(path)
            self.logs[path] = log
        self.logs.move_to_end(path)
        while len(self.logs) > self.keep:
            self.logs.popitem(last=False)[1].close()
        return log

    def close(self):
        for log in self.logs.values():
            log.close()
        self.logs.clear()
