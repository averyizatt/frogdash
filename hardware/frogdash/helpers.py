"""The dash's root helpers (update, Wi-Fi, GPS): which are installed, and getting the rest added.

Each helper is a pair of systemd units in hardware/systemd: a .path unit that watches for
a request file, and the .service it starts. The dash has no rights to install them. The
updater runs as root, so the dash asks it: a request holding the word 'helpers' makes
tools/frogdash_update.sh copy and enable whichever pairs are missing, and nothing else.
That needs the update helper itself, which is the one that has to be installed by hand.
"""
import asyncio
import os
from pathlib import Path

SHIPPED = Path(__file__).resolve().parents[1] / 'systemd'
INSTALLED = Path('/etc/systemd/system')
UPDATER = 'frogdash-update'
START_S = 10   # After the dash starts, so a boot is not slowed by it.
RETRY_S = 30
TRIES = 3


def shipped(folder=SHIPPED):
    return sorted(p.stem for p in folder.glob('frogdash-*.path') if (folder / f'{p.stem}.service').is_file())


def missing(shipped_in=SHIPPED, installed_in=INSTALLED):
    """Helpers in this version that are not installed and enabled on the Pi."""
    def installed(name):
        return ((installed_in / f'{name}.path').is_file() and (installed_in / f'{name}.service').is_file()
                and os.path.lexists(installed_in / 'multi-user.target.wants' / f'{name}.path'))
    return [name for name in shipped(shipped_in) if not installed(name)]


class Helpers:
    def __init__(self, folder, shipped_in=SHIPPED, installed_in=INSTALLED):
        self.folder, self.shipped_in, self.installed_in = folder, shipped_in, installed_in
        self.state = 'unknown'   # 'ok', 'installing', 'failed', 'no-updater' or 'unknown'
        self.missing = []
        self.asked = 0

    def step(self):
        """Ask the updater for what is missing. True while it is worth looking again."""
        request = self.folder / 'update-request'
        try:
            self.missing = missing(self.shipped_in, self.installed_in)
        except OSError:
            self.state = 'unknown'
            return False
        if not self.missing:
            self.state = 'ok'
            return False
        if UPDATER in self.missing:
            self.state = 'no-updater'
            return False
        try:
            if self.asked >= TRIES:
                # Nobody collected it: do not leave a request lying there for later.
                if request.exists() and request.read_text(encoding='utf-8').strip() == 'helpers':
                    request.unlink()
                self.state = 'failed'
                return False
            if not request.exists():   # Never replace an update the driver has just asked for.
                request.write_text('helpers', encoding='utf-8')
        except OSError:
            self.state = 'failed'
            return False
        self.asked += 1
        self.state = 'installing'
        return True

    def snapshot(self):
        return {'state': self.state, 'missing': [name.replace('frogdash-', '') for name in self.missing]}

    async def run(self):
        await asyncio.sleep(START_S)
        while await asyncio.to_thread(self.step):
            await asyncio.sleep(RETRY_S)
