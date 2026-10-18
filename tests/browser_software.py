"""Support > Software: the dash's update shown step by step in colour, and the power and
shutdown rows, through the dash's own server with the updater's status file and the
PiSugar watcher's readings standing in."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.github_link import GitHubLink
from hardware.frogdash.paint import Paint
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
ROOT = Path(__file__).resolve().parents[1]


async def steps(page):
    return await page.evaluate("[...document.querySelectorAll('#update-steps li')].map(li => li.dataset.step + ':' + li.dataset.state).join(' ')")


async def main(browser_path):
    folder = Path(tempfile.mkdtemp())
    state = State()
    state.connected, state.status = True, 'test CAN'
    state.paint = Paint(folder / 'appearance-paint.json')
    status = folder / 'update-status.json'
    status.write_text(json.dumps({'state': 'current', 'message': 'Already up to date', 'version': 'abc1234', 'previous': 'def5678'}))
    ups = {'available': True, 'state': 'external_power', 'input_present': True, 'remaining_seconds': None, 'battery_percent': 82.0,
           'battery_volts': 4.05, 'charging': True, 'auto_power_on': True, 'error': None, 'dry_run': False}
    # GitHub stands in: a code, then 'pending' until the phone authorizes.
    github = {'authorized': False}

    def post(url, fields):
        if url.endswith('/device/code'):
            return {'device_code': 'dev123', 'user_code': 'WDJB-MJHT', 'verification_uri': 'https://github.com/login/device', 'expires_in': 900, 'interval': 1}
        return {'access_token': 'gho_test'} if github['authorized'] else {'error': 'authorization_pending'}
    state.github = GitHubLink(folder, client_id='Iv1.test', post=post, user=lambda token: {'login': 'averyizatt'}, sleep=lambda s: asyncio.sleep(.2))
    # The uploader counts the reports kept on the Pi (their folder is root's alone, as on the car).
    (folder / 'upload-status.json').write_text(json.dumps({'time': 1792065600, 'state': 'held', 'held': 1, 'message': 'Report kept on the Pi: uploads not set up'}))
    (folder / 'reports').mkdir(mode=0o700)
    state.health = SimpleNamespace(status={'status': 'sampled', 'ups': ups, 'shutdown': {'previous': {'state': 'saved', 'ended_ms': 1792000000000}, 'tracking': True}})
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
            await page.locator('[data-ops-tab="software"]').click()
            await page.wait_for_function("document.getElementById('update-pill').textContent === 'Up to date'")
            assert await page.locator('#update-pill').get_attribute('data-tone') == 'good'
            assert await page.locator('#update-version').inner_text() == 'Version abc1234 · before it def5678'
            assert await steps(page) == 'internet:done download:skipped restart:done setup:done upload:done'
            # Power and shutdown: on ignition, battery, last shutdown clean.
            power = await page.locator('#power-rows').inner_text()
            assert 'Ignition power' in power and 'On' in power and '82%' in power and 'Clean' in power, power
            # An update running: the steps follow the updater's messages.
            status.write_text(json.dumps({'state': 'running', 'message': 'Updated (3 changes). Restarting the dash and checking it', 'version': 'abc1234'}))
            await page.locator('#update-check').click()
            await page.wait_for_function("document.getElementById('update-pill').textContent === 'Updating…'")
            assert await steps(page) == 'internet:done download:done restart:current setup:todo upload:todo'
            assert await page.locator('#update-run').is_disabled()
            # The key goes off: the countdown is shown.
            ups.update(input_present=False, remaining_seconds=4.2)
            await page.wait_for_function("document.getElementById('power-rows').textContent.includes('Shutting down in 5 s')", timeout=8000)
            assert await page.locator('#power-rows li').first.get_attribute('data-tone') == 'warn'
            # Reports to GitHub: not connected, one report waiting; Connect shows a code to type on the phone.
            await page.wait_for_function("document.getElementById('uploads-pill').textContent === 'Not connected'")
            assert '1 report waiting on the Pi' in await page.locator('#uploads-status').inner_text()
            await page.locator('#uploads-connect').click()
            await page.wait_for_function("document.querySelector('#uploads-code strong').textContent === 'WDJB-MJHT'")
            assert await page.locator('#uploads-code').is_visible() and await page.locator('#uploads-connect').is_hidden()
            await page.locator('#software-card').scroll_into_view_if_needed()
            await page.screenshot(path=str(ROOT / '.tmp/software-updating.png'))
            github['authorized'] = True
            await page.wait_for_function("document.getElementById('uploads-pill').textContent === 'Connected'", timeout=10000)
            assert await page.locator('#uploads-where').inner_text() == 'To averyizatt/frogdash (branch pi-logs) · as averyizatt'
            saved = json.loads((folder / 'log-upload.json').read_text())
            assert (saved['repo'], saved['token']) == ('averyizatt/frogdash', 'gho_test'), saved
            assert 'gho_test' not in await page.content()                            # Never shown
            await page.locator('#uploads-disconnect').click()
            assert await page.locator('#uploads-disconnect').inner_text() == 'Press again'
            await page.locator('#uploads-disconnect').click()
            await page.wait_for_function("document.getElementById('uploads-pill').textContent === 'Not connected'")
            assert not (folder / 'log-upload.json').exists()
            # The new version did not start: it went back, and the step that failed says so.
            status.write_text(json.dumps({'state': 'rolledback', 'message': 'Update undone: version 9999999 did not start properly (the dash service did not stay up), so the dash went back to the version that worked', 'version': 'abc1234'}))
            await page.wait_for_function("document.getElementById('update-pill').textContent === 'Went back'", timeout=8000)
            assert await steps(page) == 'internet:done download:done restart:warn setup:todo upload:todo'
            status.write_text(json.dumps({'state': 'failed', 'message': 'No internet: no saved Wi-Fi network in range. Join one in Controls > Wi-Fi, or turn on your phone hotspot', 'version': 'abc1234'}))
            await page.locator('#update-check').click()
            await page.wait_for_function("document.getElementById('update-pill').textContent === 'Failed'")
            assert await steps(page) == 'internet:bad download:todo restart:todo setup:todo upload:todo'
            assert await page.locator('#update-pill').get_attribute('data-tone') == 'bad'
            # A shutdown that did not finish saving.
            ups.update(input_present=True, remaining_seconds=None)
            state.health.status['shutdown'] = {'previous': {'state': 'running'}, 'tracking': True}
            await page.wait_for_function("document.getElementById('power-rows').textContent.includes('Not confirmed')", timeout=8000)
            # Wi-Fi… goes to Controls > Wi-Fi.
            await page.locator('#update-wifi').click()
            await page.wait_for_function("document.getElementById('controls-dialog').open && !document.getElementById('panel-wifi').hidden")
            assert not await page.locator('#operations-dialog').evaluate('el => el.open')
            assert not errors, errors
            # The preview: no Pi to update, said plainly.
            preview = await browser.new_page(viewport={'width': 1920, 'height': 720})
            preview.on('pageerror', lambda error: errors.append(str(error)))
            await preview.goto((ROOT / 'preview/index.html').as_uri())
            await preview.wait_for_timeout(1200)
            await preview.locator('#drive-launch').click()
            await preview.locator('#operations-launch').click()
            await preview.locator('[data-ops-tab="software"]').click()
            await preview.wait_for_function("document.getElementById('update-status').textContent.includes('preview has no Pi')")
            assert 'none in the preview' in await preview.locator('#firmware-modules').inner_text()
            assert not errors, errors
            await browser.close()
    finally:
        await runner.cleanup()
    print('Software card: update steps and colours for current, running, went back and failed; modules; power, countdown and last shutdown; GitHub link by code; Wi-Fi button; preview; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
