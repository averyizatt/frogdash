"""Fresh animated preview menus must respond to actual pointer/touch input."""
import argparse
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.state import State
from hardware.frogdash.server import create_app
ROOT = Path(__file__).resolve().parents[1]


async def preview(browser):
    for width, height in ((1920, 720), (1280, 480), (960, 360)):
        page = await browser.new_page(viewport={'width': width, 'height': height}, has_touch=True)
        errors, network = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: network.append(request.url) if request.url.startswith(('http:', 'https:')) else None)
        await page.add_init_script("window.speeds=[]; addEventListener('frogdash-state',e=>{const value=e.detail.snapshot.values?.['vehicle.speed_kph']?.value;if(Number.isFinite(value))speeds.push(value)})")
        await page.goto((ROOT / 'preview/index.html').as_uri())
        await page.wait_for_function('speeds.length > 2 && speeds.at(-1) > 1')
        await page.locator('#appearance-launch').click()
        await page.locator('#appearance-tab-custom').click()
        slider = page.locator('#appearance-transparency')
        box = await slider.bounding_box()
        await page.mouse.click(box['x'] + box['width'] * .7, box['y'] + box['height'] / 2)
        assert 65 <= int(await slider.input_value()) <= 75
        before = int(await slider.input_value())
        await page.keyboard.press('ArrowRight')
        assert int(await slider.input_value()) == before + 5, 'Native clicked slider keyboard input was intercepted'
        await page.touchscreen.tap(box['x'] + box['width'] * .3, box['y'] + box['height'] / 2)
        assert 25 <= int(await slider.input_value()) <= 35
        await page.mouse.move(box['x'] + box['width'] * .3, box['y'] + box['height'] / 2)
        await page.mouse.down()
        await page.mouse.move(box['x'] + box['width'] * .8, box['y'] + box['height'] / 2, steps=12)
        await page.mouse.up()
        expected = await slider.input_value()
        assert int(expected) >= 75
        await page.locator('#appearance-close').click()
        await page.reload()
        await page.wait_for_function('speeds.length > 2')
        assert await slider.input_value() == expected
        await page.locator('#drive-launch').click()
        await page.locator('#lighting-mode').select_option('night')
        await page.locator('[data-driver-tab="fuel"]').click()
        await page.locator('#fuel-enabled').uncheck()
        await page.locator('#fuel-settings button[type=submit]').click()
        await page.wait_for_function('document.getElementById("fuel-settings-status").textContent.includes("Simulated change")')
        await page.locator('[data-driver-tab="alerts"]').click()
        await page.locator('#alert-chime').check()
        await page.locator('#alert-settings button[type=submit]').click()
        await page.wait_for_function('document.getElementById("alert-settings-status").textContent.includes("Simulated alert")')
        await page.locator('#operations-launch').click()
        await page.locator('[data-ops-tab="service"]').click()
        await page.locator('#maintenance-name').fill('Preview oil service')
        await page.locator('#maintenance-days').fill('90')
        await page.locator('#maintenance-form button').click()
        await page.wait_for_function('document.getElementById("maintenance-list").textContent.includes("Preview oil service")')
        await page.locator('[data-ops-tab="display"]').click()
        await page.locator('#units-system').select_option('metric')
        assert await page.locator('#backlight-apply').is_disabled()
        assert 'Hardware only' in await page.locator('#backlight-status').inner_text()
        await page.locator('#operations-close').click()
        await page.locator('#drive-close').click()
        await page.locator('#controls-launch').click()
        await page.locator('#meth-boost-input').fill('45')
        await page.locator('[data-action="meth.boost"]').click()
        await page.wait_for_function('document.getElementById("command-result").textContent.includes("45 kPa")')
        await page.locator('[data-action="meth.test"]').click()
        await page.wait_for_function('document.getElementById("meth-live-summary").textContent.startsWith("TEST")')
        await page.locator('[data-action="meth.stop"]').click()
        await page.wait_for_function('document.getElementById("meth-live-summary").textContent.startsWith("OFF")')
        await page.locator('#tab-knock').click()
        await page.locator('#knock-offset-input').fill('28')
        await page.locator('[data-action="knock.threshold"]').click()
        await page.wait_for_function('document.getElementById("knock-live-summary").textContent.includes("Offset 28")')
        assert await page.evaluate('Math.max(...speeds) > Math.min(...speeds) + 1')
        assert not errors, errors
        assert not network, network
        await page.close()


async def production(browser):
    state = State(clock=lambda: 0)
    state.connected = True
    speed = {'value': 30, 'quality': 'live', 'seen': 0, 'source_id': 0x202, 'timestamp_ms': 0}
    state.samples['vehicle.speed_kph', 0x202] = speed
    runner = web.AppRunner(create_app(state), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    page = await browser.new_page(viewport={'width': 1920, 'height': 720})
    try:
        await page.goto('http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1]))
        await page.locator('#appearance-launch').click()
        await page.locator('#appearance-tab-custom').click()
        await page.wait_for_function('document.getElementById("appearance-custom").inert')
        assert 'Settings locked' in await page.locator('#appearance-access').inner_text()
        assert await page.locator('#appearance-looks').evaluate('e=>e.inert')
        speed['value'] = 0
        await page.wait_for_function('!document.getElementById("appearance-custom").inert')
        box = await page.locator('#appearance-transparency').bounding_box()
        await page.mouse.click(box['x'] + box['width'] * .5, box['y'] + box['height'] / 2)
        assert int(await page.locator('#appearance-transparency').input_value()) >= 45
        state.connected = False
        await page.wait_for_function('document.getElementById("appearance-custom").inert')
    finally:
        await page.close()
        await runner.cleanup()


async def main(path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=path)
        try:
            await preview(browser)
            await production(browser)
        finally:
            await browser.close()
    print('Fresh moving preview: mouse/touch/keyboard transparency, menus, toggles, commands and real parked locks passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
