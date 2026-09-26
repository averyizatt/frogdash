"""Independent MLG v1/v2 validator; streams records without loading the log into RAM.

python tools/inspect_mlg.py path/to/log.mlg [--fields] [--allow-truncated]
"""
import argparse
import json
import math
from pathlib import Path
import struct

FORMATS = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'q', 7: 'f', 10: 'B', 11: 'H', 12: 'I'}


class Reader:
    def __init__(self, stream, allow_truncated=False):
        self.stream, self.allow_truncated = stream, allow_truncated
        self.truncated = False
        prefix = self.take(8)
        if prefix[:6] != b'MLVLG\0':
            raise ValueError('Not an MLVLG binary log')
        self.version = int.from_bytes(prefix[6:8], 'big')
        if self.version == 2:
            self.timestamp, info_start, data_start, self.size, count = struct.unpack('>IIIHH', self.take(16))
            field_size = 89
        elif self.version == 1:
            self.timestamp, info_start, data_start, self.size, count = struct.unpack('>IHIHH', self.take(14))
            field_size = 55
        else:
            raise ValueError(f'Unsupported MLG version {self.version}')
        if not count or data_start > 16 * 1024 * 1024:
            raise ValueError('Invalid MLG header dimensions')
        self.fields, offset = [], 0
        for _ in range(count):
            raw = self.take(field_size)
            kind = raw[0]
            if kind not in FORMATS:
                raise ValueError(f'Unsupported field type {kind}')
            scalar = struct.Struct('>' + FORMATS[kind])
            scale, transform = struct.unpack('>ff', raw[46:54]) if kind < 10 else (1, 0)
            self.fields.append({'name': self.string(raw[1:35]), 'units': self.string(raw[35:45]),
                                'type': kind, 'offset': offset, 'scale': scale, 'transform': transform,
                                'category': self.string(raw[55:89]) if self.version == 2 else '',
                                'struct': scalar})
            offset += scalar.size
        if offset != self.size or data_start < stream.tell() or (info_start and not stream.tell() <= info_start < data_start):
            raise ValueError('MLG header offsets or record size are inconsistent')
        self.info = ''
        if info_start:
            self.take(info_start - stream.tell())
            self.info = self.string(self.take(data_start - info_start))
        else:
            self.take(data_start - stream.tell())

    @staticmethod
    def string(raw):
        return raw.split(b'\0')[0].decode('utf-8', errors='replace')

    def take(self, size):
        data = self.stream.read(size)
        if len(data) != size:
            raise ValueError('Truncated MLG header')
        return data

    def records(self):
        while True:
            at = self.stream.tell()
            kind = self.stream.read(1)
            if not kind:
                return
            if kind[0] not in (0, 1):
                raise ValueError(f'Unknown block type {kind[0]} at byte {at}')
            length = self.size + 4 if kind[0] == 0 else 53
            raw = self.stream.read(length)
            if len(raw) != length:
                self.truncated = True
                if self.allow_truncated:
                    return
                raise ValueError(f'Truncated record at byte {at}')
            counter, timestamp = raw[0], int.from_bytes(raw[1:3], 'big')
            if kind[0] == 1:
                yield {'type': 'marker', 'counter': counter, 'timestamp': timestamp, 'message': self.string(raw[3:])}
                continue
            data = raw[3:-1]
            if sum(data) % 256 != raw[-1]:
                raise ValueError(f'Checksum mismatch at byte {at}')
            values = {}
            for f in self.fields:
                value = f['struct'].unpack_from(data, f['offset'])[0]
                values[f['name']] = (value + f['transform']) * f['scale']
            yield {'type': 'data', 'counter': counter, 'timestamp': timestamp, 'values': values}


def inspect(path, fields=False, allow_truncated=False):
    with Path(path).open('rb') as stream:
        reader = Reader(stream, allow_truncated)
        rows = markers = 0
        ranges = {}
        for record in reader.records():
            if record['type'] == 'marker':
                markers += 1
                continue
            rows += 1
            for name in ('Time', 'RPM', 'MAP', 'AFR'):
                value = record['values'].get(name)
                if value is not None and math.isfinite(value):
                    lo, hi = ranges.get(name, (value, value))
                    ranges[name] = [min(lo, value), max(hi, value)]
        result = {'version': reader.version, 'fields': len(reader.fields), 'record_bytes': reader.size,
                  'data_records': rows, 'markers': markers, 'checksums': 'all complete records valid',
                  'truncated_tail': reader.truncated, 'ranges': ranges}
        if fields:
            result['definitions'] = [{k: v for k, v in f.items() if k != 'struct'} for f in reader.fields]
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--fields', action='store_true')
    parser.add_argument('--allow-truncated', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.path, args.fields, args.allow_truncated), indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')
