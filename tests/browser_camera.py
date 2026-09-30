"""Reverse camera: auto-open on reverse, linger/close, guides, persistence, and honest lost-feed states.

python tests/browser_camera.py [--browser /path/to/chromium]
"""
import argparse
import asyncio
import base64
import tempfile
import threading
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web
from playwright.async_api import async_playwright
from browser_layout import inspect
from hardware.frogdash.backlight import Backlight
from hardware.frogdash.camera import Camera
from hardware.frogdash.driving import Driving
from hardware.frogdash.operations import Operations
from hardware.frogdash.race import Race
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.trip import Trip

ROOT = Path(__file__).resolve().parents[1]


async def preview(browser):
    page = await browser.new_page(viewport={'width': 1920, 'height': 720})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    await page.goto((ROOT / 'preview/index.html').as_uri())
    await page.wait_for_function('window.frogdashRendered > 2')
    await page.evaluate("frogdashDemo.scenario('normal')")
    assert await page.locator('#camera-launch').is_visible()
    await page.evaluate("frogdashDemo.scenario('reverse')")
    await page.wait_for_selector('#camera-dialog[open]', timeout=3000)
    assert await page.locator('#camera-guides line').count() == 12
    assert await page.locator('#camera-dialog').get_attribute('data-mirror') == 'true'
    await inspect(page, '#camera-dialog')
    await page.locator('#camera-settings-toggle').click()
    await inspect(page, '#camera-dialog')
    await page.locator('#camera-width').fill('85')
    await page.locator('#camera-mirror-toggle').click()
    assert await page.locator('#camera-dialog').get_attribute('data-mirror') == 'false'
    # By default the view closes as soon as reverse turns off.
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.wait_for_function("!document.getElementById('camera-dialog').open", timeout=1500)
    # An optional delay keeps it open briefly after leaving reverse.
    await page.evaluate("frogdashDemo.scenario('reverse')")
    await page.wait_for_selector('#camera-dialog[open]', timeout=3000)
    await page.locator('#camera-settings-toggle').click()
    await page.locator('#camera-linger').select_option('3')
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.wait_for_timeout(1500)
    assert await page.locator('#camera-dialog').is_visible()
    await page.wait_for_function("!document.getElementById('camera-dialog').open", timeout=5000)
    # A manual view closes once the car drives forward so gauges are never covered.
    await page.locator('#camera-launch').click()
    assert await page.locator('#camera-dialog').is_visible()
    await page.evaluate("frogdashDemo.scenario('normal')")
    await page.wait_for_function("!document.getElementById('camera-dialog').open", timeout=3000)
    # Auto-open can be turned off.
    await page.reload()
    await page.wait_for_function('window.frogdashRendered > 2')
    prefs = await page.evaluate('FrogdashCamera.prefs')
    assert prefs['width'] == 85 and prefs['mirror'] is False, prefs
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.wait_for_timeout(300)
    await page.locator('#camera-launch').click()
    await page.locator('#camera-settings-toggle').click()
    await page.locator('#camera-auto').uncheck()
    await page.locator('#camera-close').click()
    await page.evaluate("frogdashDemo.scenario('reverse')")
    await page.wait_for_timeout(800)
    assert not await page.evaluate("document.getElementById('camera-dialog').open")
    # Dash health opens a test view without reverse.
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.locator('#drive-launch').click()
    await page.locator('#operations-launch').click()
    await page.locator('[data-ops-tab="support"]').click()
    await page.wait_for_function("document.getElementById('camera-test-status').textContent === 'Simulated'")
    await page.locator('#camera-test').click()
    assert await page.locator('#camera-dialog').is_visible()
    await page.locator('#camera-close').click()
    # Speaker test sits beside the camera test and reports what it is playing.
    for kind, text in (('left', 'LEFT'), ('right', 'RIGHT'), ('sweep', '80 Hz'), ('chime', 'chime')):
        await page.locator(f'[data-speaker-test="{kind}"]').click()
        await page.wait_for_function("t => document.getElementById('speaker-test-status').textContent.includes(t)", arg=text, timeout=3000)
    await inspect(page, '#operations-dialog')
    await page.locator('#operations-close').click()
    await page.locator('#drive-close').click()
    for width, height in ((1280, 480), (1024, 768), (390, 844)):
        await page.set_viewport_size({'width': width, 'height': height})
        await page.locator('#camera-launch').click()
        await inspect(page, '#camera-dialog')
        await page.locator('#camera-close').click()
    assert not errors, errors
    await page.close()


async def production(browser):
    """Real endpoints with a fake sensor: live frames, a frozen sensor, recovery and a missing camera."""
    page = await browser.new_page()
    await page.set_content('<canvas id=c width=640 height=480></canvas>')
    jpeg = base64.b64decode((await page.evaluate("document.getElementById('c').toDataURL('image/jpeg', .8)")).split(',')[1])
    await page.close()
    stall = threading.Event()

    def sensor(camera):
        running = threading.Event(); running.set()

        def run():
            while running.is_set():
                if not stall.is_set():
                    camera.publish_threadsafe(jpeg)
                time.sleep(1 / 30)
        threading.Thread(target=run, daemon=True).start()
        return running.clear

    def missing(camera):
        raise RuntimeError('Camera not detected')

    for opener in (sensor, missing):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            state = State('replay')
            state.connected = True
            state.race, state.driving, state.trip = Race(None), Driving(state, data), Trip(state, data / 'trip.json')
            state.operations, state.backlight, state.health, state.shutdown_history = Operations(state, data), Backlight(None), None, None
            state.camera = Camera(opener=opener, idle_s=.5)
            runner = web.AppRunner(create_app(state))
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                page = await browser.new_page(viewport={'width': 1920, 'height': 720})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                await page.goto(f'http://127.0.0.1:{port}/')
                await page.wait_for_selector('#camera-launch:not([hidden])', timeout=5000)
                await page.locator('#drive-launch').click()
                await page.locator('#operations-launch').click()
                await page.locator('[data-ops-tab="support"]').click()
                await page.wait_for_function("document.getElementById('camera-test-status').textContent === 'Ready'", timeout=5000)
                await page.locator('#camera-test').click()
                if opener is missing:
                    await page.wait_for_function("document.getElementById('camera-lost-detail').textContent.includes('Camera not detected')", timeout=5000)
                    assert await page.locator('#camera-feed').is_hidden()
                else:
                    await page.wait_for_function("document.getElementById('camera-state').textContent.includes('FPS')", timeout=5000)
                    assert await page.locator('#camera-lost').is_hidden()
                    stall.set()
                    await page.wait_for_selector('#camera-lost:not([hidden])', timeout=4000)
                    assert 'No new frame' in await page.locator('#camera-lost-detail').text_content()
                    stall.clear()
                    await page.wait_for_selector('#camera-lost', state='hidden', timeout=6000)
                    await page.locator('#camera-close').click()
                    for _ in range(50):
                        if not state.camera.running:
                            break
                        await asyncio.sleep(.05)
                    assert not state.camera.running and state.camera.viewers == 0
                assert not errors, errors
                await page.close()
            finally:
                await runner.cleanup()


async def main(executable):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=executable)
        await preview(browser)
        await production(browser)
        await browser.close()
    print('Reverse camera and speaker test: auto-open, linger, manual close when moving, guides, persistence, layouts, live/frozen/missing feeds passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
