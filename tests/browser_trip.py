"""Trip UI on demo and real HTTP service, including saved calibration/counters."""
import argparse
import asyncio
from pathlib import Path
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.state import State
from hardware.frogdash.server import create_app
from hardware.frogdash.trip import Trip

ROOT = Path(__file__).resolve().parents[1]


async def preview(browser):
    page = await browser.new_page(viewport={'width': 1980, 'height': 720})
    errors, requests = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda req: requests.append(req.url) if req.url.startswith(('http:', 'https:')) else None)
    await page.goto((ROOT / 'preview/index.html').as_uri())
    await page.locator('#drive-launch').click()
    await page.locator('[data-driver-tab="trip"]').click()
    await page.wait_for_function('document.getElementById("trip-range").textContent.includes("211")')
    before = await page.locator('#trip-b-distance').inner_text()
    await page.locator('[data-trip-reset="a"]').click()
    assert '52.3' in await page.locator('#trip-a-distance').inner_text()
    await page.locator('[data-trip-reset="a"]').click()
    await page.wait_for_function('document.getElementById("trip-a-distance").textContent.startsWith("0.0")')
    assert before == await page.locator('#trip-b-distance').inner_text()
    await page.locator('[data-driver-tab="fuel"]').click()
    assert await page.locator('#fuel-capacity_l').input_value() == '15.4'
    assert await page.locator('#fuel-pulses_per_rev').input_value() == '0.5'
    await page.locator('#fuel-pulses_per_rev').fill('0')
    await page.locator('#fuel-settings button').click()
    await page.wait_for_function('document.getElementById("fuel-settings-status").textContent.includes("pulse rate")')
    await page.locator('#fuel-pulses_per_rev').fill('1')
    await page.locator('#fuel-settings button').click()
    await page.locator('#fuel-amount').fill('10')
    await page.locator('#fuel-amount-form button[type=submit]').click()
    await page.locator('[data-driver-tab="trip"]').click()
    await page.wait_for_function('document.getElementById("trip-fuel-source").textContent.includes("10.00")')
    await page.locator('[data-driver-tab="display"]').click()
    await page.locator('#layout-slot-0').select_option('range')
    await page.locator('#drive-close').click()
    assert await page.locator('#profile-sensors h2').first.inner_text() == 'Est. range'
    await page.evaluate("frogdashDemo.scenario('offline')")
    await page.locator('#drive-launch').click()
    await page.locator('[data-driver-tab="trip"]').click()
    await page.wait_for_function('document.getElementById("trip-quality").textContent.includes("GPS unavailable")')
    assert '—' in await page.locator('#trip-range').inner_text()
    # CAN/GPS loss does not disconnect the local service or prevent a reset.
    assert not await page.locator('[data-trip-reset="a"]').is_disabled()
    assert not errors, errors
    assert not requests, requests
    await page.close()


async def live(browser):
    now = 0
    state = State(clock=lambda: now)
    state.connected = True
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'trip.json'
        state.trip = Trip(state, path)
        runner = web.AppRunner(create_app(state), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        page = await browser.new_page(viewport={'width': 1980, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}')
            await page.locator('#drive-launch').click()
            await page.locator('[data-driver-tab="fuel"]').click()
            await page.wait_for_function('document.getElementById("fuel-injector_cc_min").value === "440"')
            assert not await page.locator('#fuel-enabled').is_checked()
            assert await page.locator('#fuel-pulses_per_rev').input_value() == '0.5'
            await page.locator('#fuel-pulses_per_rev').fill('1')
            await page.locator('#fuel-pw2_injectors').fill('2')
            await page.locator('#fuel-dead_ms').fill('1')
            await page.locator('#fuel-enabled').check()
            await page.locator('#fuel-settings button').click()
            await page.wait_for_function('document.getElementById("fuel-settings-status").textContent === "Saved on the Pi."')
            assert state.trip.settings['enabled']
            await page.locator('#fuel-amount').fill('10')
            await page.locator('#fuel-amount-form button[type=submit]').click()
            await page.wait_for_function('document.getElementById("fuel-inventory-status").textContent.includes("10.00")')
            await page.locator('#drive-close').click()
            for t in range(61):
                now = t
                state.ingest(0x5F0, struct.pack('>HHHH', t, 6000, 8000, 3000))
                state.ingest(0x203, struct.pack('>HhBBBB', 1000, 0, 8, 3, 0x13, 10))
                state.trip.sample(state.snapshot())
            await page.locator('#drive-launch').click()
            await page.locator('[data-driver-tab="trip"]').click()
            await page.wait_for_function('document.getElementById("trip-a-distance").textContent.startsWith("1.0")')
            assert state.trip.snapshot()['range_km'] > 0
            await page.locator('[data-trip-reset="a"]').click()
            await page.locator('[data-trip-reset="a"]').click()
            await page.wait_for_function('document.getElementById("trip-a-distance").textContent.startsWith("0.0")')
            await page.reload()
            await page.locator('#drive-launch').click()
            await page.locator('[data-driver-tab="trip"]').click()
            await page.wait_for_function('document.getElementById("trip-b-distance").textContent.startsWith("1.0")')
            assert not errors, errors
        finally:
            await page.close()
            await runner.cleanup()
        restored = Trip(state, path)
        assert restored.counters['a']['km'] == 0
        assert restored.counters['b']['km'] > 1
        assert restored.settings['pw2_injectors'] == 2


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path)
        try:
            await preview(browser)
            await live(browser)
        finally:
            await browser.close()
    print('Trip reset confirmation, demo isolation, calibration, inventory, live closed-menu counting, reload, persistent counters and offline states passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
