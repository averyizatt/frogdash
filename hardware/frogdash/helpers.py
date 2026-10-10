"""Pi setup without SSH: the dash notices when its version's setup has not run, and asks for it.

Everything a version needs on the Pi beyond its own files (root helpers, system packages,
service settings) is a step in tools/frogdash_setup.sh. The updater runs that script as
root after every update. The dash cannot run it, so when the script on disk is not the one
that last ran (its stamp differs from setup-status.json), the dash leaves the request word
'setup' for the updater, which runs the script and nothing else.

That needs the update helper itself, the one thing that is installed by hand.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import time

SCRIPT = Path(__file__).resolve().parents[2] / 'tools/frogdash_setup.sh'
UPDATER = Path('/etc/systemd/system/frogdash-update.path')
START_S = 10      # After the dash starts, so a boot is not slowed by it.
RETRY_S = 30
TRIES = 3
RUNNING_S = 3600  # A run that claims to be going for longer than this has died.


def stamp(script=SCRIPT):
    """The same value the script works out for itself: the start of its SHA-256."""
    try:
        return hashlib.sha256(script.read_bytes()).hexdigest()[:12]
    except OSError:
        return None


class Helpers:
    def __init__(self, folder, script=SCRIPT, updater=UPDATER, wall=time.time):
        self.folder, self.script, self.updater, self.wall = folder, script, updater, wall
        self.state = 'unknown'   # 'ok', 'installing', 'failed', 'no-updater' or 'unknown'
        self.steps = []
        self.asked = 0

    def read(self):
        try:
            status = json.loads((self.folder / 'setup-status.json').read_text(encoding='utf-8'))
            return status if isinstance(status, dict) else None
        except (OSError, ValueError):
            return None

    def step(self):
        """Ask the updater to run setup when it is due. True while it is worth looking again."""
        request = self.folder / 'update-request'
        wanted, status = stamp(self.script), self.read() or {}
        self.steps = [s for s in status.get('steps', []) if isinstance(s, dict)]
        if wanted is None:
            self.state = 'unknown'
            return False
        if status.get('stamp') == wanted:
            if not status.get('running'):
                self.state = 'ok'
                return False
            if abs(self.wall() - status.get('time', 0)) < RUNNING_S:
                self.state = 'installing'   # Packages can take minutes: wait without asking again.
                return True
        if not self.updater.exists():
            self.state = 'no-updater'
            return False
        try:
            if self.asked >= TRIES:
                # Nobody collected it: do not leave a request lying there for later.
                if request.exists() and request.read_text(encoding='utf-8').strip() == 'setup':
                    request.unlink()
                self.state = 'failed'
                return False
            if not request.exists():   # Never replace an update the driver has just asked for.
                request.write_text('setup', encoding='utf-8')
        except OSError:
            self.state = 'failed'
            return False
        self.asked += 1
        self.state = 'installing'
        return True

    def snapshot(self):
        return {'state': self.state, 'steps': self.steps}

    async def run(self):
        await asyncio.sleep(START_S)
        while await asyncio.to_thread(self.step):
            await asyncio.sleep(RETRY_S)
