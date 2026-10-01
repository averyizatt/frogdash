"""Pi import folder: only plain, listed image/backup files can be read."""
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.imports import MAX_BYTES, Imports, safe
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State


class ImportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / 'import'
        self.folder.mkdir()
        (self.folder / 'art.png').write_bytes(b'\x89PNG')
        (self.folder / 'Backup 2026.json').write_text('{}', encoding='utf-8')
        (self.folder / 'notes.txt').write_text('x', encoding='utf-8')
        (self.folder / 'huge.jpg').write_bytes(b'\0' * (MAX_BYTES + 1))
        (self.folder / 'sub').mkdir()
        (Path(self.tmp.name) / 'secret.png').write_bytes(b'outside')
        state = State()
        state.imports = Imports(self.folder)
        self.client = TestClient(TestServer(create_app(state), host='127.0.0.1'))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_listing_shows_only_supported_small_files(self):
        listing = await (await self.client.get('/ui/import')).json()
        self.assertEqual([f['name'] for f in listing['files']], ['art.png', 'Backup 2026.json'])
        self.assertEqual(listing['files'][0]['type'], 'image/png')

    async def test_files_are_served_and_escapes_refused(self):
        response = await self.client.get('/ui/import/art.png')
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), b'\x89PNG')
        for name in ('..%2Fsecret.png', '%2E%2E%2Fsecret.png', 'notes.txt', 'huge.jpg', 'missing.png', '.hidden.png'):
            self.assertEqual((await self.client.get(f'/ui/import/{name}')).status, 404, name)

    async def test_remote_pages_cannot_read_files(self):
        response = await self.client.get('/ui/import/art.png', headers={'Origin': 'http://evil.example'})
        self.assertEqual(response.status, 403)

    async def test_bundled_art_is_listed_and_your_file_wins(self):
        art = Path(self.tmp.name) / 'art'
        art.mkdir()
        (art / 'logo.jpg').write_bytes(b'bundled')
        (art / 'art.png').write_bytes(b'bundled art')
        (art / 'unlisted.jpg').write_bytes(b'not in catalogue')
        (art / 'index.json').write_text('[{"name": "logo.jpg", "kind": "splash", "title": "Logo"}, {"name": "art.png", "kind": "background", "title": "Art"}, {"name": "../x.jpg"}]', encoding='utf-8')
        imports = Imports(self.folder, art)
        files = imports.listing()['files']
        self.assertEqual([(f['name'], f['source']) for f in files], [('art.png', 'Your imports'), ('Backup 2026.json', 'Your imports'), ('logo.jpg', 'Bundled art')])
        self.assertEqual(files[2]['title'], 'Logo')
        self.assertEqual(imports.path('art.png').read_bytes(), (self.folder / 'art.png').read_bytes())  # Your file shadows the bundled one.
        self.assertEqual(imports.path('logo.jpg').read_bytes(), b'bundled')
        self.assertIsNone(imports.path('unlisted.jpg'))

    def test_repository_art_catalogue_is_valid(self):
        root = Path(__file__).resolve().parents[1] / 'hardware' / 'art'
        imports = Imports(Path(self.tmp.name) / 'empty', root)
        files = imports.listing()['files']
        self.assertGreaterEqual(len(files), 8)
        self.assertTrue(all(f['kind'] in ('background', 'splash') and f['type'] == 'image/jpeg' for f in files))

    def test_name_rules(self):
        self.assertTrue(safe('My Car (2).webp'))
        for name in ('../x.png', 'a/b.png', 'x.exe', '.png', 'x..png', ''):
            self.assertFalse(safe(name), name)


if __name__ == '__main__':
    unittest.main()
