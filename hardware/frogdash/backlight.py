"""Optional, explicitly selected Linux backlight device; no GPIO/PWM guessing."""
import os
from pathlib import Path
import re


class Backlight:
    def __init__(self, name=None, root='/sys/class/backlight'):
        if name is not None and not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', name):
            raise ValueError('Invalid backlight device name')
        self.root, self.name = Path(root), name
        self.error = ''

    def status(self):
        devices = sorted(p.name for p in self.root.iterdir() if p.is_dir()) if self.root.is_dir() else []
        available = self.name in devices if self.name else False
        writable = available and os.access(self.root / self.name / 'brightness', os.W_OK)
        return dict(devices=devices, selected=self.name, writable=bool(writable), error=self.error)

    def set(self, percent):
        if type(percent) not in (int, float) or not 10 <= percent <= 100:
            raise ValueError('Backlight brightness must be 10–100%')
        if not self.name or not self.status()['writable']:
            raise ValueError('Backlight control not configured or permitted on this display')
        path = self.root / self.name
        maximum = int((path / 'max_brightness').read_text())
        if maximum < 1:
            raise ValueError('Invalid backlight maximum')
        (path / 'brightness').write_text(str(max(1, round(maximum * percent / 100))))
        return percent
