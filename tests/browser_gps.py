"""No speed: the reason and what the dash is trying appear where the speed would be."""
import argparse
import asyncio
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.gps import GPS
from hardware.frogdash.gpswatch import GpsRecovery
from hardware.frogdash.state import State
from hardware.frogdash.server import create_app

ROOT = Path(__file__).resolve().parents[1]
PORT = '/dev/ttyACM0'


async def shown(page, scope='.speed'):
    return await page.locator(f'{scope} .speed-problem').evaluate("""box => {
      const inside = (a, b) => a.left >= b.left - 1 && a.right <= b.right + 1 && a.top >= b.top - 1 && a.bottom <= b.bottom + 1;
      const card = box.parentElement, r = box.getBoundingClientRect();
      const readout = card.querySelector('.speed-readout'), source = card.querySelector('.speed-source');
      return {hidden: box.hidden, text: [...box.children].map(e => e.textContent), inside: inside(r, card.getBoundingClientRect()),
              width: r.width, overflow: [...box.children].some(e => e.scrollWidth > box.clientWidth + 1),
              digits: readout ? getComputedStyle(readout).display !== 'none' : null,
              clear: source ? r.bottom <= source.getBoundingClientRect().top : true};
    }""")


async def title_is(page, title, scope='.speed'):
    await page.wait_for_function('([scope, title]) => document.querySelector(`${scope} .speed-problem strong`)?.textContent === title', arg=[scope, title])


async def main(browser_path):
    now = 0.0
    state = State(clock=lambda: now)
    state.connected = True
    gps = GPS(clock=lambda: now, wall=lambda: 0)
    gps.started, gps.connected, gps.gpsd_ok, gps.linked_at = 0.0, True, True, 0.0
    state.gps = gps
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path)
        with tempfile.TemporaryDirectory() as directory:
            watch = state.gps_recovery = GpsRecovery(gps, Path(directory), lambda: now)
            runner = web.AppRunner(create_app(state), access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            page = await browser.new_page(viewport={'width': 1920, 'height': 720})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}')
                # The first seconds are a start-up, not a fault.
                await title_is(page, 'GPS STARTING')
                assert not (await shown(page))['digits']

                # Receiver not found: named, with the port gpsd is watching, and the dash's first try announced.
                now = 20.0
                gps.update({'class': 'DEVICES', 'devices': [{'path': '/dev/ttyUSB0'}]})
                watch.step()
                await title_is(page, 'GPS RECEIVER NOT FOUND')
                box = await shown(page)
                assert '/dev/ttyUSB0' in box['text'][1], box
                assert box['text'][2].startswith('Next try in'), box
                now = 36.0
                watch.step()
                await page.wait_for_function("document.querySelector('.speed .speed-problem small').textContent.includes('Restarting the GPS service')")
                box = await shown(page)
                assert box['text'][2] == 'Trying: Restarting the GPS service (step 1 of 3)', box
                assert box['inside'] and box['clear'] and not box['overflow'] and not box['digits'], box
                assert await page.locator('#gps-sats').inner_text() == 'GPS · RECEIVER NOT FOUND'
                await page.screenshot(path=str(ROOT / '.tmp/gps-not-found.png'))
                # With no helper installed the request is never collected, and the driver is told where to look.
                now = 46.0
                watch.step()
                now = 60.0
                await page.wait_for_function("document.querySelector('.speed .speed-problem small').textContent.includes('System check')")

                # Receiver talking, signals too weak for a position.
                gps.update({'class': 'TPV', 'device': PORT, 'mode': 1})
                gps.update({'class': 'SKY', 'device': PORT, 'satellites': [{'ss': s, 'used': False} for s in (14, 19, 22, 17)]})
                watch.step()
                await title_is(page, 'GPS SIGNAL TOO WEAK')
                box = await shown(page)
                assert '22 dB' in box['text'][1] and box['inside'] and box['clear'] and not box['overflow'], box
                await page.screenshot(path=str(ROOT / '.tmp/gps-weak.png'))

                # The same message sits on the speed dial of every other gauge style.
                seen = set()
                for look in ('cyberdeck', 'toxic', 'hologram'):
                    await page.locator('#appearance-launch').click()
                    await page.locator('[data-collection-filter="cyber"]').click()
                    await page.locator(f'button[data-look="{look}"]').click()
                    await page.locator('#appearance-dialog').evaluate('d => d.close()')
                    gauges = await page.locator('html').get_attribute('data-gauges')
                    seen.add(gauges)
                    scope = '.speed' if gauges == 'standard' else '.cluster-speed'
                    await title_is(page, 'GPS SIGNAL TOO WEAK', scope)
                    box = await shown(page, scope)
                    assert not box['hidden'] and box['width'] > 150 and box['inside'] and not box['overflow'], (look, box)
                    assert await page.locator(f'{scope} .speed-problem').is_visible(), look
                    await page.screenshot(path=str(ROOT / f'.tmp/gps-weak-{gauges}.png'))
                assert len(seen) == 3, seen

                # A position: the message goes and the speed is back.
                gps.update({'class': 'SKY', 'device': PORT, 'satellites': [{'ss': 38, 'used': True}] * 6})
                gps.update({'class': 'TPV', 'device': PORT, 'mode': 3, 'speed': 10.0, 'time': '2026-10-09T12:00:00.000Z'})
                watch.step()
                await page.wait_for_function("document.querySelector('.speed .speed-problem').hidden")
                box = await shown(page)
                assert box['digits'] and box['text'] == ['', '', ''], box
                assert await page.locator('#speed-digits').inner_text() == '22'
                assert not await page.locator('.speed').evaluate("el => el.classList.contains('has-speed-problem')")
                assert watch.snapshot()['first_fix_s'] == 60.0

                # Lost while driving: back to the reason within the quiet time.
                now = 80.0
                await title_is(page, 'GPS RECEIVER NOT FOUND')
                assert not errors, errors
            finally:
                await page.close()
                await runner.cleanup()
                await browser.close()

        # The preview keeps its simulated speed and never shows the message.
        browser = await p.chromium.launch(executable_path=browser_path)
        try:
            page = await browser.new_page(viewport={'width': 1920, 'height': 720})
            await page.goto((ROOT / 'preview/index.html').as_uri())
            await page.wait_for_function("document.getElementById('speed-digits').textContent !== '—'")
            assert (await shown(page))['hidden']
            await page.evaluate("frogdashDemo.scenario('offline')")
            await page.wait_for_timeout(300)
            assert (await shown(page))['hidden']
        finally:
            await browser.close()
    print('No-speed reasons, recovery announcements, every gauge style, return of speed and preview isolation passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
