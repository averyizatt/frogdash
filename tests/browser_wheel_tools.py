"""Everything is usable with only the five steering-wheel buttons, sent as real CAN 0x205 frames.

Covers the on-screen keyboard, color picker, Pi file picker, gauge reassignment and
accelerating number steps.  python tests/browser_wheel_tools.py [--browser PATH]
"""
import argparse
import asyncio
import base64
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from browser_layout import inspect
from hardware.frogdash.imports import Imports
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]
UP, DOWN, LEFT, RIGHT, OK = 1, 2, 4, 8, 16


async def wheel_session(browser, url, state, imports):
    page = await browser.new_page(viewport={'width': 1920, 'height': 720})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    mask = 0

    async def publisher():
        seq = 0
        while True:
            state.ingest(0x205, bytes([mask, seq, 1]))
            seq = (seq + 1) & 255
            await asyncio.sleep(.025)

    async def press(value, duration=.09):
        nonlocal mask
        mask = value
        await asyncio.sleep(duration)
        mask = 0
        await asyncio.sleep(.2)

    async def ok(selector=None):
        if selector:
            await page.locator(selector).focus()
        await press(OK)

    active = lambda: page.evaluate('document.activeElement.textContent || document.activeElement.id')
    task = asyncio.create_task(publisher())
    try:
        await page.goto(url)
        await page.wait_for_function('document.querySelectorAll(".look-card").length > 20')
        await page.wait_for_timeout(300)

        # Keyboard: OK on a text box opens it; arrows move in 2D across the key grid.
        await ok('#appearance-launch')
        await ok('#appearance-tab-custom')
        await ok('#appearance-title-input')
        await page.wait_for_selector('#wheel-keyboard[open]')
        await inspect(page, '#wheel-keyboard')
        assert await active() == 'A'
        await press(UP); assert await active() == 'Q'
        await press(RIGHT); assert await active() == 'W'
        await press(DOWN); assert await active() == 'S'
        await ok('#wheel-keyboard [data-key="clear"]')
        for key in ('V', '8'):
            await ok(f'#wheel-keyboard .wheel-key:text-is("{key}")')
        await ok('#wheel-keyboard [data-key="done"]')
        await page.wait_for_selector('#wheel-keyboard', state='hidden')
        assert await page.locator('#appearance-title-input').input_value() == 'V8'
        assert await page.evaluate('JSON.parse(localStorage.getItem("frogdash.appearance.v1")).title') == 'V8'
        assert await page.evaluate('document.activeElement.id') == 'appearance-title-input'
        # Holding OK cancels and keeps the previous text.
        await ok('#appearance-title-input')
        await ok('#wheel-keyboard [data-key="clear"]')
        await press(OK, .95)
        await page.wait_for_selector('#wheel-keyboard', state='hidden')
        assert await page.locator('#appearance-title-input').input_value() == 'V8'

        # Pi file picker lists the import folder, filtered by what the control accepts.
        await ok('#appearance-background')
        await page.wait_for_selector('#wheel-files .wheel-file')
        names = await page.locator('#wheel-files .wheel-file strong').all_text_contents()
        assert names == ['dash-art.png'], names  # backup.json is not an image.
        await inspect(page, '#wheel-files')
        await press(OK)
        await page.wait_for_function('document.documentElement.dataset.finish === "image"')

        # Color picker: swatch then Done sets the numeral color like the native picker.
        await ok('#appearance-tab-instruments')
        await ok('#appearance-numeral')
        await page.wait_for_selector('#wheel-color[open]')
        await inspect(page, '#wheel-color')
        await ok('#wheel-color .wheel-swatch[aria-label="Red"]')
        await ok('#wheel-color .wheel-done')
        assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--numeral").trim()') == '#ff1a1a'
        # Sliders: OK enters edit mode, arrows change the value, OK finishes.
        await ok('#appearance-numeral')
        await ok('#wheel-color-h')
        for _ in range(3):
            await press(RIGHT)
        await press(OK)
        await ok('#wheel-color .wheel-done')
        assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--numeral").trim()') != '#ff1a1a'
        await press(OK, .95)   # Hold OK: back out of the section...
        await press(OK, .95)   # ...and again to close (the wheel skips Close buttons).
        await page.wait_for_function('!document.getElementById("appearance-dialog").open')

        # Gauges: reachable by the wheel; OK opens the reading picker.
        await ok('.sensor-row:not(.profile-sensors) [data-gauge-slot="sensor-0"]')
        await page.wait_for_selector('#gauge-picker[open]')
        await ok('#gauge-picker [data-metric="afr"]')
        assert await page.locator('#profile-sensors .sensor-card h2').first.text_content() == 'Air / fuel'

        # Backups: the restore control lists only JSON files.
        await ok('#drive-launch')
        await ok('#operations-launch')
        await ok('[data-ops-tab="backup"]')
        await ok('#backup-file')
        await page.wait_for_selector('#wheel-files .wheel-file')
        assert await page.locator('#wheel-files .wheel-file strong').all_text_contents() == ['backup.json']
        await press(OK, .95)

        # Long number ranges accelerate while an arrow is held.
        await ok('[data-ops-tab="service"]')
        await ok('#maintenance-distance')
        await press(UP, 5)
        value = int(await page.locator('#maintenance-distance').input_value())
        assert value >= 500, value
        await press(OK)
        assert not errors, errors
    finally:
        task.cancel()
        await page.close()


async def main(executable):
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / 'import'
        folder.mkdir()
        (folder / 'dash-art.png').write_bytes(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='))
        (folder / 'backup.json').write_text('{"format": "frogdash-backup", "version": 2}', encoding='utf-8')
        (folder / 'notes.txt').write_text('ignored', encoding='utf-8')
        state = State()
        state.connected = True
        state.imports = Imports(folder)
        app = create_app(state)
        app.cleanup_ctx.clear()
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(executable_path=executable)
                try:
                    await wheel_session(browser, f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/', state, state.imports)
                finally:
                    await browser.close()
        finally:
            await runner.cleanup()
    print('Wheel tools over CAN: keyboard, color picker, Pi file picker, backups, gauge picker and accelerating numbers passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
