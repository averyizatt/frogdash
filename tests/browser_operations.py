"""Management UI, parked gates, real backup/restore, units and wide-screen bounds."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.state import State
from hardware.frogdash.server import create_app
from hardware.frogdash.operations import Operations
from hardware.frogdash.trip import Trip
from hardware.frogdash.driving import Driving
from hardware.frogdash.race import Race
from browser_layout import inspect

ROOT = Path(__file__).resolve().parents[1]


async def preview(browser):
    page = await browser.new_page(viewport={'width': 1980, 'height': 720})
    errors, requests = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: requests.append(r.url) if r.url.startswith(('http:', 'https:')) else None)
    await page.goto((ROOT / 'preview/index.html').as_uri())
    await page.evaluate("frogdashDemo.scenario('normal')")
    await page.wait_for_function("document.getElementById('speed-digits').textContent === '47'")
    await page.locator('#drive-launch').click()
    await page.locator('#operations-launch').click()
    assert await page.locator('[data-ops-tab="sender"], #sender-form').count() == 0
    await page.locator('[data-ops-tab="service"]').click()
    assert await page.locator('#maintenance-form').evaluate('(n) => n.inert')
    await page.locator('#demo-park').click()
    await page.wait_for_function("!document.getElementById('maintenance-form').inert")
    await page.locator('[data-ops-tab="display"]').click()
    await page.locator('#units-system').select_option('metric')
    await page.locator('#operations-close').click()
    await page.locator('#drive-close').click()
    await page.evaluate("frogdashDemo.scenario('normal')")
    await page.wait_for_function("document.getElementById('speed-digits').textContent === '76'")
    assert await page.locator('#coolant-val').inner_text() == '96'
    assert await page.locator('#boost-val').inner_text() == '85.0'
    assert await page.locator('.speed-readout .unit').inner_text() == 'km/h'
    await page.reload()
    await page.evaluate("frogdashDemo.scenario('normal')")
    await page.wait_for_function("document.getElementById('speed-digits').textContent === '76'")
    assert not errors, errors
    assert not requests, requests
    await page.close()


async def live(browser):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        state = State(clock=lambda: 0)
        state.connected = True
        state.samples['ecu.rpm', 1520] = dict(value=0, quality='live', seen=0, source_id=1520, timestamp_ms=0)
        state.ingest(0x204, bytes.fromhex('01F401'))
        state.operations = Operations(state, path)
        state.trip = Trip(state, path / 'trip.json')
        state.driving = Driving(state, path)
        state.race = Race(path / 'race.json')
        runner = web.AppRunner(create_app(state), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
        page = await browser.new_page(viewport={'width': 1980, 'height': 720})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        try:
            await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/?kiosk=' + 'f' * 32)
            await page.wait_for_function("document.getElementById('fuel-val').textContent === '50'")
            state.ingest(0x204, bytes.fromhex('000002'))
            await page.wait_for_function("document.querySelector('[data-signal=\"vehicle.fuel_pct\"]').dataset.quality === 'fault'")
            assert await page.locator('#fuel-val').inner_text() != '0'
            state.ingest(0x204, bytes.fromhex('01F401'))
            await page.locator('#drive-launch').click()
            await page.locator('#operations-launch').click()
            await page.locator('[data-ops-tab="service"]').click()
            await page.locator('#maintenance-name').fill('Oil & filter')
            await page.locator('#maintenance-distance').fill('3000')
            await page.locator('#maintenance-days').fill('180')
            await page.locator('#maintenance-form button').click()
            await page.wait_for_function("document.getElementById('maintenance-list').textContent.includes('Oil & filter')")
            await page.get_by_role('button', name='Record service', exact=True).click()
            await page.wait_for_function("document.getElementById('maintenance-list').textContent.includes('Last service')")
            assert len(state.operations.data['maintenance'][0]['history']) == 1
            await page.locator('[data-ops-tab="support"]').click()
            await page.locator('#acceptance-list button').first.click()
            await page.wait_for_function("document.getElementById('acceptance-list').textContent.includes('✓')")
            async with page.expect_download() as event:
                await page.locator('#diagnostic-download').click()
            await (await event.value).save_as(path / 'diagnostic.json')
            assert json.loads((path / 'diagnostic.json').read_text())['format'] == 'frogdash-diagnostics'
            await page.locator('[data-ops-tab="backup"]').click()
            async with page.expect_download() as event:
                await page.locator('#backup-download').click()
            await (await event.value).save_as(path / 'backup.json')
            backup = json.loads((path / 'backup.json').read_text())
            assert 'sender' not in backup
            assert backup['version'] == 2
            assert backup['trip']['settings']['capacity_l'] == 15.4 * 3.785411784
            state.operations.data['maintenance'].clear()
            await page.locator('#backup-file').set_input_files(path / 'backup.json')
            await page.wait_for_function("!document.getElementById('backup-restore').disabled")
            await inspect(page, '#operations-dialog')
            await page.locator('#backup-restore').click()
            await page.wait_for_function("document.getElementById('operations-dialog') && !document.getElementById('operations-dialog').open")
            assert len(state.operations.data['maintenance']) == 1
            assert not state.operations.restoring
            await page.wait_for_timeout(2300)
            assert 'f' * 32 in state.operations.heartbeats
            assert not errors, errors
        finally:
            await page.close(); await runner.cleanup()


async def main(path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=path)
        try:
            await preview(browser)
            await live(browser)
        finally:
            await browser.close()
    print('Management: parked locks, CAN fuel display, metric conversion, maintenance/history, diagnostics, backup/restore and render heartbeat passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
