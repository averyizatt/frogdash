"""Browser checks for saved appearance, splash uploads and live/preview GPS timing."""
import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.gps import GPS
from hardware.frogdash.race import Race

ROOT = Path(__file__).resolve().parents[1]


async def preview(browser):
    page = await browser.new_page(viewport={'width': 1980, 'height': 720})
    errors, network = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: network.append(request.url) if request.url.startswith(('http:', 'https:')) else None)
    await page.goto((ROOT / 'preview/index.html').as_uri())
    await page.evaluate("frogdashDemo.scenario('normal')")
    await page.wait_for_function("document.getElementById('rpm-value').textContent === '3450'")
    await page.screenshot(path=str(ROOT / '.tmp/appearance-test-upload.png'))
    # Footer buttons must remain inside the panel even with the extra destinations.
    assert await page.locator('.dashboard-nav').evaluate('(el) => el.getBoundingClientRect().right <= document.getElementById("display").getBoundingClientRect().right')
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.wait_for_timeout(150)
    await page.locator('#appearance-launch').click()
    # Catalogue choices affect the actual dash, survive reload, and compose
    # with independent backgrounds without touching splash or driving layout.
    warning_color = await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--warn")')
    for look, finish in [('original', 'midnight'), ('glacier', 'horizon'), ('heritage', 'graphite'), ('afterhours', 'dusk'), ('apex', 'carbon'), ('expedition', 'contour')]:
        await page.locator(f'button[data-look="{look}"]').click()
        assert await page.locator('html').get_attribute('data-finish') == finish
        assert await page.locator('button[data-look][aria-pressed="true"]').count() == 1
        assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--warn")') == warning_color
    await page.locator('[data-collection-filter="performance"]').click()
    for look, finish, style in [('sprint', 'pitlane', 'race'), ('endurance', 'apexline', 'race'), ('rally', 'technical', 'race'), ('clubsport', 'carbon', 'race'), ('obsidian', 'satin', 'touring'), ('executive', 'horizon', 'touring')]:
        await page.locator(f'button[data-look="{look}"]').click()
        assert await page.locator('html').get_attribute('data-finish') == finish
        assert await page.locator('html').get_attribute('data-instrument-style') == style
        assert await page.locator('button[data-look][aria-pressed="true"]').count() == 1
        assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--warn")') == warning_color
    assert await page.locator('.look-card:visible').count() == 6
    # Cyber looks differ in structure, not only color: layout, type, shape and edges all change.
    await page.locator('[data-collection-filter="cyber"]').click()
    assert await page.locator('.look-card:visible').count() == 6
    for look, finish, gauges, font, shape, edge in [('cyberdeck', 'neoncity', 'cyber', 'mono', 'chamfer', 'glow'), ('netrunner', 'circuit', 'cyber', 'mono', 'sharp', 'accent'), ('ronin', 'void', 'cyber', 'racing', 'chamfer', 'rail'), ('hologram', 'aurora', 'standard', 'sans', 'round', 'glow'), ('toxic', 'hazard', 'digital', 'mono', 'sharp', 'accent'), ('blackout', 'void', 'cyber', 'sans', 'sharp', 'none')]:
        await page.locator(f'button[data-look="{look}"]').click()
        html = page.locator('html')
        assert [await html.get_attribute(f'data-{name}') for name in ('finish', 'gauges', 'font', 'shape', 'edge')] == [finish, gauges, font, shape, edge], look
        assert await page.locator('button[data-look][aria-pressed="true"]').count() == 1
        assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--warn")') == warning_color
    await page.locator('[data-collection-filter="signature"]').click()
    await page.locator('[data-look="expedition"]').click()
    for finish in ['midnight', 'graphite', 'carbon', 'glow', 'horizon', 'grid', 'contour', 'dusk', 'pitlane', 'apexline', 'technical', 'satin', 'void', 'duotone', 'neoncity', 'circuit', 'hazard', 'aurora']:
        await page.locator(f'button[data-background="{finish}"]').click()
        assert await page.locator('html').get_attribute('data-scene') == finish
    await page.locator('button[data-background="dusk"]').click()
    assert 'customized' in await page.locator('#appearance-current').inner_text()
    assert await page.locator('button[data-look][aria-pressed="true"]').count() == 0
    await page.reload()
    assert await page.evaluate('JSON.parse(localStorage.getItem("frogdash.appearance.v1")).look') == 'expedition'
    assert await page.locator('html').get_attribute('data-finish') == 'dusk'
    assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--surface").trim()') == '#192018'
    await page.evaluate("frogdashDemo.scenario('night')")
    await page.wait_for_function('document.documentElement.dataset.lighting === "night"')
    assert await page.locator('#display').evaluate('(el) => getComputedStyle(el).getPropertyValue("--accent").trim()') == '#ffc77d'
    await page.evaluate("frogdashDemo.scenario('normal')")
    await page.wait_for_function('document.documentElement.dataset.lighting === "day"')
    assert await page.locator('#display').evaluate('(el) => getComputedStyle(el).getPropertyValue("--accent").trim()') == '#7ed321'
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.wait_for_timeout(150)
    await page.locator('#appearance-launch').click()
    await page.locator('#appearance-tab-gallery').focus()
    await page.keyboard.press('ArrowRight')
    assert await page.locator('#appearance-custom').is_visible()
    await page.locator('#appearance-tab-custom').click()
    for transparency, alpha in [(0, 255), (50, 128), (100, 0)]:
        await page.locator('#appearance-transparency').fill(str(transparency))
        assert await page.locator('#appearance-transparency-value').inner_text() == f'{transparency}%'
        actual = await page.locator('.primary-instruments').evaluate("""el => {
          const c = document.createElement('canvas'); c.width = c.height = 1;
          const ctx = c.getContext('2d'); ctx.fillStyle = getComputedStyle(el).backgroundColor;
          ctx.fillRect(0,0,1,1); return ctx.getImageData(0,0,1,1).data[3];
        }""")
        assert abs(actual - alpha) <= 1, (transparency, actual)
        assert await page.locator('#speed-digits').evaluate('(el) => getComputedStyle(el).opacity') == '1'
        assert await page.locator('.primary-instruments').evaluate('(el) => getComputedStyle(el).opacity') == '1'
    await page.locator('#appearance-transparency').fill('50')
    await page.locator('#appearance-tab-instruments').click()
    await page.get_by_role('button', name='Violet', exact=True).click()
    await page.locator('#appearance-tab-custom').click()
    await page.locator('#appearance-finish').select_option('carbon')
    await page.reload()
    assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()') == '#9d00ff'
    assert await page.locator('html').get_attribute('data-finish') == 'carbon'
    assert await page.locator('#appearance-transparency').input_value() == '50'
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.wait_for_timeout(150)
    await page.locator('#appearance-launch').click()
    await page.locator('#appearance-tab-custom').click()
    await page.locator('#appearance-background').set_input_files(str(ROOT / '.tmp/appearance-test-upload.png'))
    await page.wait_for_function('document.documentElement.dataset.finish === "image"')
    await page.locator('#appearance-splash-image').set_input_files(str(ROOT / '.tmp/appearance-test-upload.png'))
    await page.wait_for_function('document.getElementById("appearance-splash").value === "image"')
    await page.locator('#appearance-tab-gallery').click()
    await page.locator('button[data-look="glacier"]').click()
    await page.locator('#appearance-tab-custom').click()
    await page.locator('#appearance-finish').select_option('image')
    assert await page.evaluate('JSON.parse(localStorage.getItem("frogdash.appearance.v1")).background.startsWith("data:image/")')
    assert await page.locator('#appearance-splash').input_value() == 'image'
    await page.locator('#appearance-duration').select_option('5')
    await page.locator('#appearance-preview').click()
    assert await page.locator('#splash-image').is_visible()
    await page.locator('#splash-skip').click()
    assert await page.locator('#appearance-dialog').is_visible()
    await page.locator('#appearance-splash').select_option('wordmark')
    await page.locator('#appearance-title-input').fill('FOXBODY / 5.0')
    await page.locator('#appearance-title-input').press('Tab')
    await page.locator('#appearance-preview').click()
    assert await page.locator('#splash-title').inner_text() == 'FOXBODY / 5.0'
    await page.screenshot(path=str(ROOT / '.tmp/splash-custom-title.png'))
    await page.locator('#splash-skip').click()
    await page.reload()
    # Moving telemetry dismisses the configured startup splash automatically.
    await page.wait_for_function('!document.getElementById("splash-dialog").open')
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.wait_for_timeout(150)
    await page.locator('#appearance-launch').click()
    await page.locator('#appearance-tab-custom').click()
    assert await page.locator('#appearance-title-input').input_value() == 'FOXBODY / 5.0'
    await page.locator('#appearance-reset').click()
    assert await page.evaluate('JSON.parse(localStorage.getItem("frogdash.appearance.v1")).look') == 'original'
    assert await page.locator('#appearance-transparency').input_value() == '0'
    await page.locator('#appearance-close').click()
    await page.locator('#race-launch').click()
    await page.locator('[data-race="accel"]').click()
    await page.wait_for_function('document.getElementById("race-phase").textContent === "DEMO · COMPLETE"')
    assert await page.locator('#race-0_60').inner_text() == '5.82 s'
    async with page.expect_download() as info:
        await page.locator('#race-export').click()
    assert (await info.value).suggested_filename == 'frogdash-demo-race-results.json'
    await page.screenshot(path=str(ROOT / '.tmp/race-preview-complete.png'))
    await page.locator('[data-race="laps"]').click()
    await asyncio.sleep(.4)
    await page.locator('[data-race="lap"]').click()
    assert await page.locator('#race-lap-count').inner_text() == '1'
    await page.locator('[data-race="stop"]').click()
    assert not errors, errors
    assert not network, network
    await page.close()


async def live(browser):
    now = 0
    with tempfile.TemporaryDirectory() as directory:
        state = State(clock=lambda: now)
        state.gps = GPS(clock=lambda: now, transmit=False)
        state.race = Race(Path(directory) / 'race.json', clock=lambda: now)
        async def hold_gps(_):
            await asyncio.Event().wait()
        with patch('hardware.frogdash.server.gpsd', hold_gps):
            runner = web.AppRunner(create_app(state), access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            page = await browser.new_page(viewport={'width': 1980, 'height': 720})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def feed(t, speed):
                nonlocal now
                now = t
                state.gps.update({'class': 'TPV', 'mode': 3, 'speed': speed, 'lat': 40, 'lon': -105,
                    'time': datetime.fromtimestamp(1700000000 + t, timezone.utc).isoformat()})
            try:
                feed(0, 0)
                await page.goto(f'http://127.0.0.1:{port}')
                await page.locator('#race-launch').click()
                await page.locator('[data-race="accel"]').click()
                await page.wait_for_function('document.getElementById("race-phase").textContent === "ARMED"')
                await page.locator('#race-close').click()
                for i in range(1, 181):
                    feed(i / 10, max(0, (i / 10 - 2) * 4))
                    await asyncio.sleep(.002)
                await page.locator('#race-launch').click()
                await page.wait_for_function('document.getElementById("race-phase").textContent === "COMPLETE"')
                assert await page.locator('#race-0_60').inner_text() == '6.71 s'
                async with page.expect_download() as info:
                    await page.locator('#race-export').click()
                download = await info.value
                await download.save_as(str(ROOT / '.tmp/race-live-results.json'))
                assert download.suggested_filename == 'frogdash-race-results.json'
                await page.reload()
                await page.locator('#race-launch').click()
                await page.wait_for_function('document.getElementById("race-0_60").textContent === "6.71 s"')
                assert not errors, errors
            finally:
                await page.close()
                await runner.cleanup()
        assert len(Race(Path(directory) / 'race.json').history) == 1


async def main(browser_path):
    (ROOT / '.tmp').mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path, headless=True)
        try:
            await preview(browser)
            await live(browser)
        finally:
            await browser.close()
    print('Appearance persistence, image uploads, splash, simulated sessions, live GPS timing, closed-menu recording, exports and reload passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    args = parser.parse_args()
    asyncio.run(main(args.browser))
