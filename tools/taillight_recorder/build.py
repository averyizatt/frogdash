"""Record CustomTaillights animations into hardware/ui/taillights/ for the dashboard mirror.

Runs the unmodified firmware animation code on this computer (g++ and git required),
compiled against the same FastLED version the taillight controller uses:

    python tools/taillight_recorder/build.py [--taillights PATH] [--compiler g++]

Without --taillights, the pinned CustomTaillights revision from
hardware/can_contract/sources.json is fetched into .cache/. Re-run after updating the
taillight firmware, then run tools/update_preview.py.
"""
import argparse
import json
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CACHE = ROOT / '.cache'
OUT = ROOT / 'hardware' / 'ui' / 'taillights'
FASTLED_TAG = '3.10.3'  # platformio.ini lib_deps in CustomTaillights
REPO = 'https://github.com/averyizatt/CustomTaillights.git'


def checkout(url, ref, folder):
    if not (folder / '.git').exists():
        subprocess.run(['git', 'clone', '--quiet', url, str(folder)], check=True)
    subprocess.run(['git', '-C', str(folder), 'fetch', '--quiet', '--tags', 'origin'], check=True)
    subprocess.run(['git', '-C', str(folder), 'checkout', '--quiet', ref], check=True)
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--taillights', type=Path, help='Existing CustomTaillights checkout')
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    CACHE.mkdir(exist_ok=True)
    pinned = json.loads((ROOT / 'hardware' / 'can_contract' / 'sources.json').read_text())['repositories']['CustomTaillights']
    taillights = args.taillights or checkout(REPO, pinned, CACHE / 'CustomTaillights')
    revision = subprocess.run(['git', '-C', str(taillights), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    fastled = checkout('https://github.com/FastLED/FastLED.git', FASTLED_TAG, CACHE / 'FastLED') / 'src'
    src = taillights / 'src'
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / 'recorder.exe'
        subprocess.run([args.compiler, '-std=c++17', '-O2', '-w', '-DFASTLED_STUB_IMPL', '-DFASTLED_FORCE_SOFTWARE_SPI',
                        f'-I{HERE / "stubs"}', f'-I{src}', f'-I{taillights / "include"}', f'-I{fastled}',
                        str(HERE / 'recorder.cpp'),
                        *(str(src / name) for name in ('animations.cpp', 'matrix_animations.cpp', 'taillight.cpp', 'font5x.cpp', 'settings.cpp')),
                        *(str(fastled / name) for name in ('hsv2rgb.cpp', 'lib8tion.cpp', 'fl/fill.cpp')),
                        '-o', str(exe)], check=True)
        raw, index = Path(tmp) / 'frames.raw', Path(tmp) / 'frames.json'
        subprocess.run([str(exe), str(raw), str(index)], check=True)
        catalogue = json.loads(index.read_text())
        catalogue['source'] = {'repository': 'averyizatt/CustomTaillights', 'revision': revision, 'fastled': FASTLED_TAG}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / 'frames.bin').write_bytes(zlib.compress(raw.read_bytes(), 9))
        (OUT / 'frames.json').write_text(json.dumps(catalogue, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'Wrote {OUT / "frames.bin"} ({(OUT / "frames.bin").stat().st_size // 1024} KB) from CustomTaillights {revision[:7]}')


if __name__ == '__main__':
    if not shutil.which('git'):
        raise SystemExit('git is required')
    main()
