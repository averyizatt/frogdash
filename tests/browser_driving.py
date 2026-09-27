"""Exercise day/night, profiles, alerts, bookmarks and authenticated phone review."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.driving import Driving
from hardware.frogdash.recorder import Recorder, Config
from hardware.frogdash.connectivity import TransferPortal

ROOT = Path(__file__).resolve().parents[1]


async def preview(browser):
    page = await browser.new_page(viewport={'width': 1980, 'height': 720})
    errors, network = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda req: network.append(req.url) if req.url.startswith(('http:', 'https:')) else None)
    await page.goto((ROOT / 'preview/index.html').as_uri())
    await page.wait_for_function('document.getElementById("rpm-value").textContent === "3450"')
    await page.wait_for_function('document.documentElement.dataset.lighting === "day"')
    await page.evaluate("frogdashDemo.scenario('night')")
    await page.wait_for_function('document.documentElement.dataset.lighting === "night"')
    await page.locator('#drive-launch').click()
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.wait_for_timeout(150)
    await page.locator('#lighting-mode').select_option('day')
    assert await page.locator('html').get_attribute('data-lighting') == 'day'
    await page.locator('#lighting-mode').select_option('auto')
    await page.evaluate("frogdashDemo.scenario('offline')")
    await page.wait_for_function('document.documentElement.dataset.lighting === "day"')
    await page.evaluate("frogdashDemo.scenario('parked')")
    for layout in ('street', 'tuning', 'track'):
        await page.locator(f'button[data-layout="{layout}"]').click()
        await page.locator('#drive-close').click()
        await page.wait_for_function('document.getElementById("display").dataset.layout === ' + json.dumps(layout))
        await page.screenshot(path=str(ROOT / '.tmp' / f'layout-{layout}.png'))
        assert await page.evaluate('''() => {
          const frame = document.getElementById('display').getBoundingClientRect();
          return [...document.querySelectorAll('#display button')].every(el => {
            if (!el.checkVisibility()) return true;
            const r = el.getBoundingClientRect();
            return r.left >= frame.left && r.right <= frame.right && r.top >= frame.top && r.bottom <= frame.bottom;
          });
        }''')
        await page.locator('#drive-launch').click()
    await page.locator('#layout-slot-0').select_option('batt')
    await page.reload()
    await page.wait_for_function('document.getElementById("display").dataset.layout === "track"')
    assert await page.locator('#profile-sensors h2').first.inner_text() == 'Battery'
    await page.locator('#bookmark-launch').click()
    await page.wait_for_function('document.getElementById("bookmark-launch").textContent.startsWith("Marked #")')
    await page.evaluate("frogdashDemo.scenario('parked')")
    await page.wait_for_timeout(150)
    await page.locator('#alerts-launch').click()
    await page.locator('#setting-oil_psi').fill('90')
    await page.locator('#alert-settings button[type=submit]').click()
    await page.wait_for_function('document.getElementById("driver-alerts").textContent.includes("LOW OIL PRESSURE")')
    await page.locator('#driver-alerts button').first.click()
    assert 'engine.oil_pressure_psi: 62' in await page.locator('#alert-capture').inner_text()
    await page.locator('#ack-all').click()
    await page.wait_for_function('document.getElementById("alert-count").textContent === "0"')
    assert 'ACTIVE' in await page.locator('#driver-alerts').inner_text()
    await page.locator('#setting-oil_psi').fill('15')
    await page.locator('#alert-settings button[type=submit]').click()
    await page.wait_for_function('document.getElementById("driver-alerts").textContent.includes("No active")')
    await page.locator('[data-driver-tab="review"]').click()
    await page.locator('#drive-review .review-events button').last.click()
    assert 'Marker #' in await page.locator('#drive-review .review-event-detail').inner_text()
    assert await page.locator('#drive-review .review-options select').last.input_value() == 'event'
    await page.locator('#drive-review .review-options select').first.select_option('engine.fuel_pressure_psi')
    assert 'Fuel pressure' in await page.locator('#drive-review .review-readout').inner_text()
    async with page.expect_download() as info:
        await page.get_by_role('button', name='Export review', exact=True).click()
    assert (await info.value).suggested_filename == 'drive-demo.json'
    await page.locator('[data-driver-tab="health"]').click()
    await page.wait_for_function('document.getElementById("health-cards").textContent.includes("ERROR-ACTIVE")')
    assert 'SIMULATED' in await page.locator('#health-detail').inner_text()
    assert not network, network
    assert not errors, errors
    await page.close()


async def live(browser):
    with tempfile.TemporaryDirectory() as directory:
        state = State()
        state.connected = True
        state.driving = Driving(state, Path(directory))
        state.recorder = Recorder(state, Config(Path(directory) / 'logs', seconds=1, free_bytes=0))
        signals = {'vehicle.speed_kph': 0, 'tach.rpm': 2500, 'engine.oil_pressure_psi': 50, 'sensors.fault_flags': 0,
                   'engine.fuel_pressure_psi': 39, 'engine.boost_kpa': 50, 'ecu.afr': 12.5,
                   'ecu.afr_target': 12.5, 'ecu.coolant_c': 90, 'meth.state': 'OFF',
                   'meth.flow': 'OK', 'meth.fault_flags': 0, 'meth.duty_pct': 0,
                   'knock.warning': False, 'knock.critical': False, 'lighting.running': False}
        async def feed():
            while True:
                for key, value in signals.items():
                    state.samples[key, 0x202] = {'value': value, 'quality': 'live', 'source_id': 0x202,
                                                 'timestamp_ms': int(state.wall() * 1000), 'seen': state.clock()}
                await asyncio.sleep(.05)
        runner = web.AppRunner(create_app(state, feed), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
        port = site._server.sockets[0].getsockname()[1]
        page = await browser.new_page(viewport={'width': 1980, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        phone = phone_runner = None
        try:
            await page.goto(f'http://127.0.0.1:{port}')
            await page.wait_for_function('document.getElementById("rpm-value").textContent === "2500"')
            await page.locator('#bookmark-launch').click()
            await page.wait_for_function('document.getElementById("bookmark-launch").textContent.startsWith("Marked #")')
            await page.locator('#alerts-launch').click()
            await page.locator('#setting-oil_psi').fill('60')
            await page.locator('#alert-settings button[type=submit]').click()
            await page.wait_for_function('document.getElementById("driver-alerts").textContent.includes("LOW OIL PRESSURE")')
            await page.locator('#ack-all').click()
            await page.wait_for_function('document.getElementById("alert-count").textContent === "0"')
            signals['engine.oil_pressure_psi'] = 70
            await page.wait_for_function('document.getElementById("driver-alerts").textContent.includes("No active")')
            await page.locator('[data-driver-tab="review"]').click()
            await page.locator('#drive-review .review-events button').last.click()
            assert 'MLG Time' in await page.locator('#drive-review .review-event-detail').inner_text()
            assert len(state.driving.current['events']) >= 2
            await page.screenshot(path=str(ROOT / '.tmp/drive-live-review.png'))
            # Same review component, read-only and authenticated on the phone listener.
            portal = TransferPortal(state)
            phone_runner = web.AppRunner(portal.app('127.0.0.0/8'), access_log=None)
            await phone_runner.setup()
            phone_site = web.TCPSite(phone_runner, '127.0.0.1', 0); await phone_site.start()
            phone_port = phone_site._server.sockets[0].getsockname()[1]
            phone = await browser.new_page(viewport={'width': 390, 'height': 844})
            phone.on('pageerror', lambda error: errors.append(str(error)))
            await phone.goto(f'http://127.0.0.1:{phone_port}')
            await phone.locator('#code').fill(portal.code)
            await phone.locator('#login-form button').click()
            await phone.locator('#phone-review .review-events button').last.click()
            assert 'Marker #' in await phone.locator('.review-event-detail').inner_text()
            assert await phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await phone.screenshot(path=str(ROOT / '.tmp/phone-drive-review.png'), full_page=True)
            await portal.close()
            await phone.get_by_role('button', name='Refresh drives', exact=True).click()
            await phone.locator('#login').wait_for(state='visible')
            assert not errors, errors
        finally:
            if phone: await phone.close()
            if phone_runner: await phone_runner.cleanup()
            await page.close(); await runner.cleanup()
        stored = Driving(state, Path(directory))
        sessions = await stored.get_reviews()
        assert sessions[0]['status'] == 'complete'
        assert stored.settings['oil_psi'] == 60
        assert len((await stored.get_review(sessions[0]['name']))['events']) >= 2


async def main(path):
    (ROOT / '.tmp').mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=path, headless=True)
        try:
            await preview(browser)
            await live(browser)
        finally:
            await browser.close()
    print('Day/night fallback, saved profiles, alert configuration/acknowledgement, bookmarks, MLG references, graphs, persisted reviews, and authenticated phone review passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
