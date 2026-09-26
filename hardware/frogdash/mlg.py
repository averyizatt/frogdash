"""MLVLG v2 writer. Wire layout: EFI Analytics MLG_Binary_LogFormat_2.0.pdf.

Independent reader/validator: tools/inspect_mlg.py. No external dependency.
"""
from dataclasses import dataclass
import math
import struct

HEADER = struct.Struct('>6sHIIIHH')
FIELD = struct.Struct('>B34s10sBffb34s')
TYPES = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'q', 7: 'f'}


def text(value, length):
    encoded = value.encode('ascii')
    if len(encoded) >= length or b'\0' in encoded:
        raise ValueError(f'MLG text does not fit {length - 1} characters: {value!r}')
    return encoded.ljust(length, b'\0')


@dataclass(frozen=True)
class Field:
    name: str
    units: str = ''
    category: str = ''
    kind: int = 7
    digits: int = 2
    scale: float = 1.0
    transform: float = 0.0

    def definition(self):
        if self.kind not in TYPES or not math.isfinite(self.scale) or self.scale == 0:
            raise ValueError('Invalid MLG field type or scale')
        return FIELD.pack(self.kind, text(self.name, 34), text(self.units, 10), 0,
                          self.scale, self.transform, self.digits, text(self.category, 34))


class Encoder:
    def __init__(self, fields, timestamp, info='Frogdash'):
        self.fields = tuple(fields)
        if len({f.name for f in fields}) != len(fields):
            raise ValueError('Duplicate MLG field names')
        definitions = b''.join(f.definition() for f in fields)
        self.record = struct.Struct('>' + ''.join(TYPES[f.kind] for f in fields))
        info = info.encode('ascii') + b'\0'
        info_start = HEADER.size + len(definitions)
        self.header = HEADER.pack(b'MLVLG\0', 2, int(timestamp), info_start,
                                  info_start + len(info), self.record.size, len(fields)) + definitions + info
        self.counter = 0

    def row(self, elapsed, values):
        # Explicit Time channel carries long gaps and multiple timestamp wraps.
        # Timestamp is 10 microseconds/tick, NOT milliseconds (655.36 ms wrap).
        payload = self.record.pack(*values)
        prefix = struct.pack('>BBH', 0, self.counter, round(elapsed * 100_000) & 0xFFFF)
        self.counter = (self.counter + 1) & 0xFF
        return prefix + payload + bytes([sum(payload) & 0xFF])
