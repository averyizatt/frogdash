"""UPS/shutdown diagnostics in live UI and the matching 1920x720 preview."""
import argparse
import asyncio
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.state import State
from hardware.frogdash.server import create_app

ROOT = Path(__file__).resolve().parents[1]


class FixtureHealth:
    def __init__(self):
        self.stopping = False
        self.status = {'ups': {'available': True, 'battery_percent': 78, 'battery_volts': 3.95,
                              'charging': False, 'input_present': False, 'auto_power_on': True},
                       'shutdown': {'tracking': True, 'scope': 'boot', 'previous': {
                           'state': 'saved', 'ended_ms': time.time() * 1000 - 60000,
                           'recording_enabled': True, 'dropped_samples': 2}}}

    async def run(self):
        while not self.stopping:
            await asyncio.sleep(.05)


async def open_health(page):
    await page.locator('#drive-launch').click()
    await page.locator('[data-driver-tab="health"]').click()


async def main(browser_path):
    (ROOT / '.tmp').mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path, headless=True)
        errors = []
        try:
            page = await browser.new_page(viewport={'width': 1920, 'height': 720})
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto((ROOT / 'preview/index.html').as_uri())
            await open_health(page)
            await page.wait_for_function('document.getElementById("health-cards").textContent.includes("86.0%")')
            assert 'SIMULATED' in await page.locator('#health-shutdown-note').inner_text()
            for width, height in ((1920, 720), (1980, 720), (1280, 480)):
                await page.set_viewport_size({'width': width, 'height': height})
                await page.wait_for_timeout(120)
                assert await page.locator('#drive-dialog').evaluate("""dialog => {
                    const frame = document.getElementById('display').getBoundingClientRect();
                    const box = dialog.getBoundingClientRect();
                    return box.left >= frame.left - 1 && box.right <= frame.right + 1
                        && box.top >= frame.top - 1 && box.bottom <= frame.bottom + 1
                        && dialog.scrollWidth <= dialog.clientWidth + 1
                        && dialog.scrollHeight <= dialog.clientHeight + 1;
                }""")
                assert await page.locator('#health-cards').evaluate('e => e.scrollWidth <= e.clientWidth + 1')
                assert await page.locator('[data-driver-panel=health]').evaluate('e => e.scrollHeight <= e.clientHeight + 1')
                if width == 1920:
                    await page.screenshot(path=str(ROOT / '.tmp/ups-health-preview.png'))
            await page.close()
            state = State()
            state.connected = True
            state.health = FixtureHealth()
            runner = web.AppRunner(create_app(state), access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            try:
                page = await browser.new_page(viewport={'width': 1920, 'height': 720})
                page.on('pageerror', lambda error: errors.append(str(error)))
                await page.goto('http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1]))
                await open_health(page)
                await page.wait_for_function('document.getElementById("health-cards").textContent.includes("78.0%")')
                assert 'On battery' in await page.locator('#health-cards').inner_text()
                assert 'Data synced' in await page.locator('#health-cards').inner_text()
                assert '2 recording samples' in await page.locator('#health-shutdown-note').inner_text()
                state.health.status['shutdown']['previous'] = {'state': 'running'}
                await page.wait_for_function('document.getElementById("health-cards").textContent.includes("Unconfirmed")')
                assert 'Data synced' not in await page.locator('#health-cards').inner_text()
                state.health.status['shutdown']['previous'] = {'state': 'save_failed', 'errors': ['Disk full']}
                await page.wait_for_function('document.getElementById("health-shutdown-note").textContent.includes("Disk full")')
                state.health.status['ups'] = {'available': False, 'battery_percent': 78}
                await page.wait_for_function('!document.getElementById("health-cards").textContent.includes("78.0%")')
                state.health.status['shutdown']['previous'] = None
                await page.wait_for_function('document.getElementById("health-cards").textContent.includes("No record")')
                await page.close()
            finally:
                await runner.cleanup()
            assert not errors, errors
        finally:
            await browser.close()
    print('UPS quality, shutdown evidence, storage failure, stale readings and panel-size layouts passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
