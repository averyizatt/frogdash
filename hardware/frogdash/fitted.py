"""Which of the modules' analog inputs have a sensor on them.

The water/meth board reports a fault bit (0x303 bytes 6-7, protocol.ANALOG_BITS) for every
analog input that does not read in range, and an input with nothing wired to it never does:
the car's board reports fuel pressure, meth pressure, boost reference, intake air, engine bay,
ambient and cabin "faulted" at every start, because none of them is fitted. Shown as faults,
those lit SENSOR FAULT on every drive, with nothing to find in the fault lists.

So an input counts as fitted once it has read in range (its fault bit clear) for OK_S without a
break, and that is remembered on the Pi (/var/lib/frogdash/analog-sensors.json): a sensor
that has worked and then reads out of range (unplugged, shorted, failing) is a fault, as
before; an input that has never read in range is "not fitted" and stays off the banner. A
sensor taken out for good is forgotten from the Sensors > Signals page.
"""
import json
from pathlib import Path

from .driving import atomic_write
from .protocol import ANALOG_BITS

OK_S = 3.0


class FittedSensors:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.seen = set()       # Inputs that have read in range: fitted
        self.ok_since = {}      # Input -> when its fault bit was last seen clear without a break
        if self.path:
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                self.seen = {name for name in data.get('fitted', []) if name in ANALOG_BITS}
            except (OSError, ValueError, AttributeError):
                pass   # None yet, or unreadable: learnt again from the next drive

    def observe(self, flags, now):
        """The module's fault bits (sensors.fault_flags), each time they arrive."""
        added = False
        for name, bit in ANALOG_BITS.items():
            if flags >> bit & 1:
                self.ok_since.pop(name, None)
                continue
            since = self.ok_since.setdefault(name, now)
            if name not in self.seen and now - since >= OK_S:
                self.seen.add(name)
                added = True
        if added:
            self.save()

    def fitted(self, name):
        return name in self.seen

    def forget(self):
        """Every input back to not fitted, until it reads in range again."""
        self.seen.clear()
        self.ok_since.clear()
        self.save()

    def save(self):
        if not self.path:
            return
        try:
            atomic_write(self.path, {'version': 1, 'fitted': sorted(self.seen)})
        except OSError:
            pass   # A full or read-only card: still right for this drive
