"""First paint uses the saved look even when Chromium's storage was lost (for example, key-off).

python tests/browser_first_paint.py [--browser /path/to/chromium]
"""
import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.backlight import Backlight
from hardware.frogdash.driving import Driving
from hardware.frogdash.operations import Operations
from hardware.frogdash.paint import Paint
from hardware.frogdash.race import Race
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.trip import Trip

ROOT = Path(__file__).resolve().parents[1]


async def main(executable):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        state = State('replay')
        state.race, state.driving, state.trip = Race(None), Driving(state, data), Trip(state, data / 'trip.json')
        state.operations, state.backlight, state.health, state.shutdown_history = Operations(state, data), Backlight(None), None, None
        state.paint = Paint(data / 'appearance-paint.json')
        runner = web.AppRunner(create_app(state))
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        url = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/'
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(executable_path=executable)
                first = await browser.new_page(viewport={'width': 1920, 'height': 720})
                errors = []
                first.on('pageerror', lambda e: errors.append(str(e)))
                await first.goto(url)
                await first.wait_for_function('document.querySelectorAll(".look-card").length > 20')
                await first.evaluate("document.querySelector('[data-look=\"cyberdeck\"]').click()")
                await first.locator('#appearance-launch').click()
                await first.locator('#appearance-tab-custom').click()
                await first.locator('#appearance-splash').select_option('wordmark')
                # An uploaded background contains ';' in its data URL and must not break the snapshot.
                await first.set_input_files('#appearance-background', files=[{'name': 'bg.png', 'mimeType': 'image/png',
                    'buffer': bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                                            '1f15c4890000000d49444154789c6360f80f000001010005180d0a0000000049454e44ae426082')}])
                await first.wait_for_function('document.documentElement.dataset.finish === "image"')
                for _ in range(50):
                    if state.paint.value and state.paint.value['data'].get('finish') == 'image':
                        break
                    await asyncio.sleep(.1)
                assert state.paint.value, 'Snapshot never reached the service'
                assert state.paint.value['data']['preset'] == 'cyberdeck' and state.paint.value['splash'] is True
                assert 'custom-background' not in state.paint.value['style']
                assert not errors, errors
                # Fresh profile = everything in Chromium's storage lost. Block the appearance
                # script so this shows exactly what the served page paints on its own.
                context = await browser.new_context(viewport={'width': 1920, 'height': 720})
                page = await context.new_page()
                await page.route('**/personalize.js*', lambda route: route.abort())
                await page.goto(url, wait_until='domcontentloaded')
                result = await page.evaluate("""() => ({gauges: document.documentElement.dataset.gauges, preset: document.documentElement.dataset.preset,
                  accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
                  display: getComputedStyle(document.getElementById('display')).visibility})""")
                assert result == {'gauges': 'cyber', 'preset': 'cyberdeck', 'accent': '#ff2bd6', 'display': 'hidden'}, result
                # Failsafe: gauges are revealed even if the splash never opens.
                await page.wait_for_function("getComputedStyle(document.getElementById('display')).visibility === 'visible'", timeout=4000)
                await browser.close()
        finally:
            await runner.cleanup()
    print('First paint: saved look served by the Pi with lost browser storage, background upload, splash hold and failsafe passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
