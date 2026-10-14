"""Screen mode on the dash: the Support row, the two-press trial, and the KEEP question after a
trial restart, through the dash's own server. The preview has no Pi behind it: no row there."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.paint import Paint
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
ROOT = Path(__file__).resolve().parents[1]
SURVEY = {'connectors': [{'name': 'HDMI-A-1', 'status': 'connected', 'edid_bytes': 256, 'edid_ok': True, 'panel_1920x720': False,
                          'modes': ['1920x1080', '1680x1050'], 'mode_count': 26},
                         {'name': 'HDMI-A-2', 'status': 'disconnected', 'edid_bytes': 0, 'edid_ok': False, 'panel_1920x720': False, 'modes': [], 'mode_count': 0}],
          'boot_time': ['Startup finished in 1.889s (kernel) + 5.583s (userspace) = 7.472s'],
          'first_render': ['[   32.235810] pi dbus-run-session[1085]: Frogdash kiosk: first render heartbeat observed (boot+32.23s; 10.06s after browser launch)']}


async def text(page, selector):
    return (await page.locator(selector).inner_text()).strip()


async def main(browser_path):
    folder = Path(tempfile.mkdtemp())
    state = State()
    state.connected, state.status = True, 'test CAN'
    state.paint = Paint(folder / 'appearance-paint.json')
    status = folder / 'screen-status.json'
    status.write_text(json.dumps({'state': 'original', 'message': 'The screen uses its own modes', 'applied': False, **SURVEY}))
    app = create_app(state)
    app.cleanup_ctx.clear()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
            page = await browser.new_page(viewport={'width': 1920, 'height': 720})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(f'http://127.0.0.1:{port}')
            await page.locator('#drive-launch').click()
            await page.locator('#operations-launch').click()
            await page.locator('[data-ops-tab="support"]').click()
            await page.wait_for_function("!document.getElementById('screen-row').hidden")
            line = await text(page, '#screen-status')
            assert 'The screen uses its own modes' in line, line
            assert 'HDMI-A-1: 26 modes, none of them 1920 × 720' in line, line
            assert 'HDMI-A-2' not in line and 'Dash: first render heartbeat observed (boot+32.23s' in line, line
            assert await page.locator('#screen-back').is_hidden()
            # Two presses, because it restarts the dash.
            await page.locator('#screen-try').click()
            assert await text(page, '#screen-try') == 'Press again'
            assert 'goes back by itself' in await text(page, '#screen-status')
            assert not (folder / 'screen-request').exists()
            await page.locator('#screen-try').click()
            await page.wait_for_function("document.getElementById('screen-try').disabled")
            assert (folder / 'screen-request').read_text() == 'trial'
            await page.screenshot(path=str(ROOT / '.tmp/screen-support.png'))
            # The helper restarts the Pi into the trial; the dash comes back and asks.
            (folder / 'screen-request').unlink()
            status.write_text(json.dumps({'state': 'trial', 'message': 'Trying exact 1920 x 720', 'started': int(time.time()), 'deadline_s': 90,
                                          'applied': False, **SURVEY}))
            await page.reload()
            await page.wait_for_function("document.getElementById('screen-trial').open", timeout=8000)
            count = await text(page, '#screen-trial-count')
            assert 'goes back by itself in 8' in count or 'goes back by itself in 9' in count, count
            assert await page.evaluate("document.activeElement.id") == 'screen-keep'
            await page.keyboard.press('Escape')                   # Escape is not an answer
            assert await page.locator('#screen-trial').evaluate('d => d.open')
            await page.screenshot(path=str(ROOT / '.tmp/screen-trial.png'))
            await page.locator('#screen-keep').click()
            await page.wait_for_function("document.getElementById('screen-trial-count').textContent === 'Answer sent…'")
            assert (folder / 'screen-request').read_text() == 'keep'
            (folder / 'screen-request').unlink()
            status.write_text(json.dumps({'state': 'kept', 'message': 'The screen now gets exactly 1920 x 720 at every start', 'applied': True, **SURVEY}))
            await page.wait_for_function("!document.getElementById('screen-trial').open", timeout=5000)
            await page.locator('#drive-launch').click()
            await page.locator('#operations-launch').click()
            await page.locator('[data-ops-tab="support"]').click()
            await page.wait_for_function("!document.getElementById('screen-back').hidden", timeout=25000)
            assert await page.locator('#screen-try').is_hidden()
            assert not errors, errors
            # The preview: no Pi, so no row and no question.
            preview = await browser.new_page(viewport={'width': 1920, 'height': 720})
            preview.on('pageerror', lambda error: errors.append(str(error)))
            await preview.goto((ROOT / 'preview/index.html').as_uri())
            await preview.wait_for_timeout(1500)
            assert await preview.locator('#screen-row').is_hidden()
            assert not await preview.locator('#screen-trial').evaluate('d => d.open')
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
    print('Screen mode: Support row with what the Pi sees, two-press trial, KEEP question after the restart, kept state; preview untouched; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
