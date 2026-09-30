"""Files the dashboard can load without a touchscreen: images and backups copied to the Pi.

Copy files into the import folder (default /var/lib/frogdash/import) over SSH or from
a USB stick. The steering-wheel file picker lists them; loading one goes through the
same validation as a normal browser upload. Plain file names only, no subfolders.
"""
import re

TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.json': 'application/json'}
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._()-]{0,119}')
MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 100


def mime(name):
    dot = name.rfind('.')
    return TYPES.get(name[dot:].lower()) if dot > 0 else None


def safe(name):
    return bool(NAME.fullmatch(name)) and '..' not in name and mime(name) is not None


class Imports:
    def __init__(self, directory):
        self.directory = directory

    def listing(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            entries = sorted(self.directory.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            return {'directory': str(self.directory), 'files': [], 'error': f'{type(exc).__name__}: {exc}'[:200]}
        files = []
        for path in entries:
            try:
                if not safe(path.name) or not path.is_file() or path.is_symlink():
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            if size <= MAX_BYTES:
                files.append({'name': path.name, 'type': mime(path.name), 'size': size})
            if len(files) >= MAX_FILES:
                break
        return {'directory': str(self.directory), 'files': files, 'error': None}

    def path(self, name):
        """Resolve a listed file, or None. Never follows names outside the folder."""
        if not safe(name):
            return None
        path = self.directory / name
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
                return None
        except OSError:
            return None
        return path
