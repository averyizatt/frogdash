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
    for width, height in ((1920, 720), (1280, 480), (960, 360), (1366, 768), (390, 844)):
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
        await slider.scroll_into_view_if_needed()
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
        # Pulse tuning in the preview: a setting, a limit the stand-in controller enforces, a preset.
        await page.locator('#tab-tune').click()
        await page.wait_for_function('document.getElementById("mt-sync").textContent.includes("Matches preset: Conservative")')
        assert await page.locator('#mt-period_ms').input_value() == '4'
        assert await page.locator('#mt-fluid').input_value() == 'Water'
        await page.locator('#mt-start_psi_x10').fill('6.5')
        await page.locator('#mt-start_psi_x10').blur()
        await page.wait_for_function('document.getElementById("mt-summary").textContent.startsWith("At 6.5 psi the pump runs 1 s in every 4 s (15 ml/min), rising to 2 s in every 4 s (30 ml/min) at 10 psi.")')
        assert "Never more than 10% of the engine's fuel flow" in await page.locator('#mt-summary').inner_text()
        await page.wait_for_function('document.getElementById("mt-sync").textContent.includes("Unsaved changes")')
        await page.locator('#mt-min_on_ms').fill('3.5')   # Above the maximum: limited, never raising it.
        await page.locator('#mt-min_on_ms').blur()
        await page.wait_for_function('document.getElementById("mt-min_on_ms").value === "2"')
        assert await page.locator('#mt-max_on_ms').input_value() == '2'
        await page.locator('#mt-min_on_ms').fill('0.1')   # Shorter than the relay allows.
        await page.locator('#mt-min_on_ms').blur()
        await page.wait_for_function('document.getElementById("mt-min_on_ms").value === "0.5"')
        await page.locator('#mt-preset').select_option('Mild')
        await page.locator('#mt-apply').click()
        await page.wait_for_function('document.getElementById("mt-sync").textContent.includes("Matches preset: Mild")')
        assert await page.locator('#mt-max_on_ms').input_value() == '3'
        # Tank mix: the blend and its dose limit change, the flow preset stays.
        await page.locator('#mt-fluid').select_option('53% meth')
        await page.wait_for_function('document.getElementById("mt-max_dose_pct").value === "18"')
        assert 'Matches preset: Mild' in await page.locator('#mt-sync').inner_text()
        await page.locator('#mt-preset').select_option('Standard')
        await page.locator('#mt-apply').click()
        await page.wait_for_function('document.getElementById("mt-summary").textContent.includes("rising to on continuously (60 ml/min) at 8 psi")')
        assert await page.locator('#mt-fluid').input_value() == '53% meth'
        await page.locator('#mt-preset').select_option('Mild')
        await page.locator('#mt-apply').click()
        await page.wait_for_function('document.getElementById("mt-sync").textContent.includes("Matches preset: Mild")')
        await page.locator('#mt-preset').select_option('Custom 1')
        assert await page.locator('#mt-apply').is_disabled()   # Empty slot.
        await page.locator('#mt-store').click()
        await page.wait_for_function('document.getElementById("mt-sync").textContent.includes("Matches preset: Mild")')
        await page.locator('#mt-save').click()
        await page.wait_for_function('document.getElementById("mt-sync").textContent.startsWith("Saved on the controller")')
        await page.locator('#mt-defaults').click()
        await page.wait_for_function('document.getElementById("mt-sync").textContent.includes("Matches preset: Conservative")')
        assert await page.locator('#mt-fluid').input_value() == 'Water'   # Defaults are water only.
        await page.locator('#mt-revert').click()
        await page.wait_for_function('document.getElementById("mt-max_on_ms").value === "3"')
        assert await page.locator('#mt-fluid').input_value() == '53% meth'
        await page.locator('#tab-meth').click()
        assert await page.locator('#meth-live-hold').inner_text() in ('Disarmed', 'Armed: waiting for boost', 'Injecting', 'Held: engine RPM is below the minimum')
        assert await page.locator('#meth-live-flow').inner_text() != '—'
        assert '°C' in await page.locator('#meth-live-pre').inner_text()   # Metric was chosen above.
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
    page = await browser.new_page(viewport={'width': 1366, 'height': 768})
    try:
        await page.goto('http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1]))
        await page.locator('#appearance-launch').click()
        await page.locator('#appearance-tab-custom').click()
        await page.wait_for_function('!document.getElementById("appearance-custom").inert')
        assert 'Settings locked' not in await page.locator('#appearance-access').inner_text()
        assert not await page.locator('#appearance-looks').evaluate('e=>e.inert')
        for connected, value in ((True, 30), (True, 0), (False, 0)):
            state.connected = connected
            speed['value'] = value
            await page.wait_for_timeout(300)
            slider = page.locator('#appearance-transparency')
            await slider.scroll_into_view_if_needed()
            box = await slider.bounding_box()
            await page.mouse.click(box['x'] + box['width'] * .5, box['y'] + box['height'] / 2)
            before = int(await slider.input_value())
            assert before >= 45
            await page.keyboard.press('ArrowRight')
            assert int(await slider.input_value()) == before + 5
            assert not await page.locator('#appearance-custom').evaluate('e=>e.inert')
        await page.reload()
        await page.locator('#appearance-launch').click()
        await page.locator('#appearance-tab-custom').click()
        assert int(await page.locator('#appearance-transparency').input_value()) > 0
        assert not await page.locator('#appearance-custom').evaluate('e=>e.inert')
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
    print('Fresh moving preview: mouse/touch/keyboard transparency, menus, toggles, commands and production editing with moving/missing CAN passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
