"""Files the dashboard can load without a touchscreen: images and backups copied to the Pi.

Copy files into the import folder (default /var/lib/frogdash/import) over SSH or from
a USB stick. The steering-wheel file picker lists them; loading one goes through the
same validation as a normal browser upload. Plain file names only, no subfolders.
"""
import json
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
    def __init__(self, directory, bundled=None):
        self.directory = directory
        # Read-only artwork shipped in the repository (hardware/art), updated by git pull.
        self.bundled = bundled
        self.catalogue = {}
        try:
            for item in json.loads((bundled / 'index.json').read_text(encoding='utf-8')):
                if safe(item['name']):
                    self.catalogue[item['name']] = {'kind': str(item.get('kind', '')), 'title': str(item.get('title', ''))[:60]}
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def _bundled_files(self, taken):
        files = []
        for name, info in self.catalogue.items():
            path = self.bundled / name
            try:
                if name in taken or not path.is_file() or path.stat().st_size > MAX_BYTES:
                    continue
                files.append({'name': name, 'type': mime(name), 'size': path.stat().st_size, 'source': 'Frogdash art', **info})
            except OSError:
                continue
        return files

    def listing(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            entries = sorted(self.directory.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            return {'directory': str(self.directory), 'files': self._bundled_files(set()), 'error': f'{type(exc).__name__}: {exc}'[:200]}
        files = []
        for path in entries:
            try:
                if not safe(path.name) or not path.is_file() or path.is_symlink():
                    continue
                size = path.stat().st_size
            except OSError:
                continue
            if size <= MAX_BYTES:
                files.append({'name': path.name, 'type': mime(path.name), 'size': size, 'source': 'Your imports'})
            if len(files) >= MAX_FILES:
                break
        return {'directory': str(self.directory), 'files': files + self._bundled_files({f['name'] for f in files}), 'error': None}

    def path(self, name):
        """Resolve a listed file, or None. Never follows names outside the folder."""
        if not safe(name):
            return None
        for folder in (self.directory, self.bundled if name in self.catalogue else None):
            if folder is None:
                continue
            path = folder / name
            try:
                if not path.is_symlink() and path.is_file() and path.stat().st_size <= MAX_BYTES:
                    return path
            except OSError:
                continue
        return None
