"""Optional real Chromium test: pip install playwright; playwright install chromium.

Run from repo root: python tests/browser_smoke.py [--browser /path/to/chromium]
"""
import argparse
import asyncio
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.gps import GPS
from hardware.frogdash.recorder import Recorder, Config
from tools.inspect_mlg import inspect as inspect_mlg
from hardware.frogdash.connectivity import TransferPortal


async def check_transfer(browser, state, errors):
    portal = TransferPortal(state)
    runner = web.AppRunner(portal.app('127.0.0.0/8'), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    page = await browser.new_page(viewport={'width': 390, 'height': 844})
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        await page.goto(f'http://127.0.0.1:{port}')
        await page.locator('#code').fill(portal.code)
        await page.locator('#login-form button').click()
        await page.locator('#content').wait_for(state='visible')
        await page.locator('#files a').first.wait_for()
        async with page.expect_download() as download_info:
            await page.locator('#files a').first.click()
        await (await download_info.value).save_as('.tmp/phone-download.mlg')
        assert inspect_mlg('.tmp/phone-download.mlg')['data_records'] > 0
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await page.screenshot(path='.tmp/phone-log-transfer.png', full_page=True)
        await portal.close()
        await page.locator('#refresh').click()
        await page.locator('#login').wait_for(state='visible')
    finally:
        await page.close()
        await runner.cleanup()


async def check_preview(browser, errors):
    """Exercise the same visual design without permitting a network connection."""
    page = await browser.new_page(viewport={'width': 1920, 'height': 720})
    page.on('pageerror', lambda error: errors.append(str(error)))
    network = []
    page.on('websocket', lambda ws: network.append(ws.url))
    page.on('request', lambda request: network.append(request.url) if request.url.startswith(('http:', 'https:')) else None)
    await page.goto((Path(__file__).resolve().parents[1] / 'preview' / 'index.html').as_uri())
    await page.wait_for_function("document.getElementById('connection-summary').textContent === 'DEMO · SIMULATED'")
    assert await page.locator('#afr-target').inner_text() == '12.5'
    assert (await page.locator('#afr-state').inner_text()).lower() == 'at target'
    await page.screenshot(path='.tmp/dashboard-preview.png')
    await page.evaluate("frogdashDemo.scenario('vacuum')")
    await page.wait_for_function("document.getElementById('boost-state').textContent === 'VACUUM'")
    assert await page.locator('#boost-val').inner_text() == '-8.0'
    # Negative pressure extends left from zero; it must never look like positive boost.
    position = await page.locator('#boost-fill').evaluate('(el) => [parseFloat(el.style.left), parseFloat(el.style.width)]')
    assert position[0] < 33.333 and abs(sum(position) - 100 / 3) < .01
    await page.evaluate("frogdashDemo.scenario('warning')")
    await page.wait_for_function("document.getElementById('warn-banner').textContent.includes('COOLANT HIGH')")
    assert await page.locator('[data-signal="engine.coolant_c"]').get_attribute('data-tone') == 'danger'
    await page.screenshot(path='.tmp/dashboard-warning.png')
    await page.locator('#knock-launch').click()
    assert await page.locator('#knock-status').inner_text() == 'WARNING'
    await page.screenshot(path='.tmp/dashboard-knock.png')
    await page.keyboard.press('Escape')
    assert await page.locator('#knock-launch').evaluate('(el) => document.activeElement === el')
    await page.evaluate("frogdashDemo.scenario('offline')")
    await page.wait_for_function("document.getElementById('rpm-value').textContent === '—'")
    assert await page.locator('#connection-summary').inner_text() == 'DEMO · OFFLINE'
    assert await page.locator('[data-signal="engine.rpm"] .quality-label').inner_text() == 'STALE'
    await page.screenshot(path='.tmp/dashboard-offline.png')
    await page.evaluate("frogdashDemo.scenario('normal')")
    await page.wait_for_function("document.getElementById('rpm-value').textContent === '3450'")
    await page.set_viewport_size({'width': 1280, 'height': 720})
    await page.locator('#controls-launch').click()
    await page.locator('#tab-meth').focus()
    await page.keyboard.press('ArrowDown')
    assert await page.locator('#panel-knock').is_visible()
    await page.screenshot(path='.tmp/dashboard-knock-settings.png')
    await page.keyboard.press('ArrowDown')
    assert await page.locator('#panel-lighting').is_visible()
    await page.locator('#lighting-brightness-input').fill('128')
    await page.locator('[data-action="lighting.brightness"]').click()
    await page.wait_for_function("document.getElementById('lighting-live-summary').textContent.includes('128 / 255')")
    await page.screenshot(path='.tmp/dashboard-lighting.png')
    await page.keyboard.press('Escape')
    await page.locator('#controls-launch').click()
    await page.locator('#tab-wifi').click()
    await page.locator('#wifi-on').click()
    assert await page.locator('#wifi-summary').inner_text() == 'DEMO · Hotspot on'
    assert await page.locator('#wifi-code').inner_text() == '12345678'
    await page.locator('#wifi-off').click()
    await page.keyboard.press('Escape')
    await page.locator('#diagnostics-launch').click()
    await page.locator('#signal-filter').fill('oil')
    assert await page.locator('#signals tr').count() == 1
    await page.wait_for_timeout(1100)
    assert not network, network
    await page.close()


async def main(browser_path=None):
    Path('.tmp').mkdir(exist_ok=True)
    state = State()
    state.connected, state.status = True, 'test CAN'
    state.gps = GPS(transmit=False)
    log_directory = tempfile.TemporaryDirectory()
    state.recorder = Recorder(state, Config(Path(log_directory.name), seconds=.5, free_bytes=0))
    # Test the browser with injected data; do not launch the Linux GPS adapter.
    app = create_app(state)
    app.cleanup_ctx.clear()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    state.recorder.start()
    frames = [(0x100, '05010502804600'), (0x202, '0D7A000001011400'),
              (0x300, '0000640155505000'), (0x303, '7C4E00003C410000'),
              (0x307, '13140FB403225500'), (0x5E8, '07080D7A080201F4'),
              (0x5EA, '937C03E800000000'), (0x5EB, '008E000000000000')]
    sent = []

    async def sender(identifier, data):
        sent.append((identifier, data))
        if identifier == 0x301:
            if data[0] in (1, 2, 3):
                mode = (1 if data[1] else 0) if data[0] == 1 else 4 if data[0] == 2 else 0
                duty = data[1] if data[0] == 2 else 0
                frames[2] = (0x300, bytes([mode, duty, 100, 1, 85, 80, 80, 0]).hex())
            state.ingest(0x30A, bytes([data[0], 0, data[1] if len(data) > 1 else 0, 2]))
    state.controls.attach(sender)
    state.controls.ready_at = 0

    async def feed():
        while True:
            for identifier, data in frames:
                state.ingest(identifier, bytes.fromhex(data))
            state.gps.connected = True
            state.gps.update({'class': 'TPV', 'mode': 3, 'speed': 21})
            await asyncio.sleep(.05)

    task = asyncio.create_task(feed())
    errors = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=browser_path, headless=True)
            page = await browser.new_page(viewport={'width': 1920, 'height': 720})
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(f'http://127.0.0.1:{port}')
            await page.wait_for_function("document.getElementById('rpm-value').textContent === '3450'")
            assert await page.locator('#speed-digits').inner_text() == '47'
            assert await page.locator('#fuel-val').inner_text() == '—'
            assert await page.locator('#turn-left').get_attribute('data-on') == 'true'
            assert 'on' in (await page.locator('#icon-brake').get_attribute('class')).split()
            assert await page.locator('#afr-val').inner_text() == '12.4'
            assert await page.locator('#afr-target').inner_text() == '14.7'
            assert (await page.locator('#afr-state').inner_text()).lower() == 'below target'
            assert await page.locator('[id^="sim-"]').count() == 0
            await page.locator('#knock-launch').click()
            await page.wait_for_function("document.getElementById('knock-energy-num').textContent === '20'")
            assert await page.locator('#knock-status').inner_text() == 'OK'
            await page.locator('#knock-close').click()
            await page.locator('#diagnostics-launch').click()
            assert await page.locator('#signals tr').count() > 30
            await page.locator('#log-details summary').click()
            await page.wait_for_function("document.getElementById('recording-badge').textContent === 'REC 20 Hz'")
            await page.wait_for_timeout(600)
            await page.locator('#refresh-logs').click()
            await page.locator('#log-files a').first.wait_for()
            async with page.expect_download() as download_info:
                await page.locator('#log-files a').first.click()
            download = await download_info.value
            await download.save_as('.tmp/browser-download.mlg')
            assert inspect_mlg('.tmp/browser-download.mlg')['data_records'] > 0
            await page.locator('#log-details summary').click()
            await page.locator('#diagnostics-close').click()
            await page.locator('#controls-launch').click()
            await page.locator('[data-action="meth.arm"][data-value="1"]').click()
            await page.wait_for_function("document.getElementById('command-result').textContent.startsWith('ACKNOWLEDGED')")
            await page.wait_for_function("document.getElementById('meth-live-summary').textContent.startsWith('ARMED')")
            assert sent[-1] == (0x301, b'\x01\x01')
            await page.locator('[data-action="meth.arm"][data-value="0"]').click()
            await page.wait_for_function("document.getElementById('meth-live-summary').textContent.startsWith('OFF')")
            await page.wait_for_function("!document.querySelector('[data-action=\"meth.test\"]').disabled")
            await page.locator('#meth-test-duty').fill('10')
            await page.locator('[data-action="meth.test"]').click()
            await page.wait_for_function("document.getElementById('meth-live-summary').textContent.startsWith('TEST')")
            await page.screenshot(path='.tmp/dashboard-controls.png')
            close_bounds = await page.locator('#controls-close').bounding_box()
            assert close_bounds['y'] >= 0 and close_bounds['y'] + close_bounds['height'] <= 720
            await page.locator('#controls-close').click()
            await page.wait_for_function("document.getElementById('meth-state-pill').textContent === 'OFF'")
            assert (0x301, b'\x02\x0a') in sent and sent[-1] == (0x301, b'\x03')
            # Navigating away from water/meth must also stop an active pump test.
            await page.locator('#meth-cell').click()
            await page.wait_for_function("!document.querySelector('[data-action=\"meth.test\"]').disabled")
            await page.locator('[data-action="meth.test"]').click()
            await page.wait_for_function("document.getElementById('meth-live-summary').textContent.startsWith('TEST')")
            await page.locator('#tab-knock').click()
            await page.wait_for_function("document.getElementById('meth-state-pill').textContent === 'OFF'")
            assert sent[-1] == (0x301, b'\x03')
            await page.keyboard.press('Escape')
            Path('.tmp').mkdir(exist_ok=True)
            await page.screenshot(path='.tmp/dashboard-live.png')
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            state.gps.connected = False
            state.connected = False
            await page.wait_for_function("document.getElementById('rpm-value').textContent === '—'")
            assert await page.locator('#speed-digits').inner_text() == '—'
            assert await page.locator('#turn-left').get_attribute('data-on') == 'false'
            await page.context.set_offline(True)
            await page.wait_for_function("document.getElementById('connection').textContent.includes('DISCONNECTED')")
            await page.context.set_offline(False)
            state.connected = True
            task = asyncio.create_task(feed())
            await page.wait_for_function("document.getElementById('rpm-value').textContent === '3450'")
            await page.set_viewport_size({'width': 1280, 'height': 720})
            bounds = await page.locator('#display').bounding_box()
            assert bounds['width'] <= 1281 and bounds['height'] <= 721
            await page.screenshot(path='.tmp/dashboard-1280.png')
            await check_preview(browser, errors)
            await check_transfer(browser, state, errors)
            assert not errors, errors
            await browser.close()
    finally:
        await state.controls.close()
        await state.recorder.close()
        log_directory.cleanup()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runner.cleanup()
    print('Browser integration passed: telemetry, controls, recording, Wi-Fi preview, phone portal login and MLG downloads, session expiry; no JS errors or preview network access.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
