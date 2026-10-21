"""Gauges first (later.js), in the preview: the gauges draw before any of the other screens'
files load; those load about four seconds later without moving anything on the main
screen; a press on one of their buttons before then still opens it; no errors."""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
# The main screen's structure: its panels and cards and the top bar's buttons (not the
# live numbers inside them, which move with the readings).
LAYOUT = """() => [...document.querySelectorAll('#display > *, #display > * > *, .topbar > *, .topbar button')]
  .filter(n => n.offsetParent).map(n => { const r = n.getBoundingClientRect();
    return [n.id || n.className, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })"""


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto((ROOT / 'preview/dash.html').as_uri())
        await page.wait_for_function('window.frogdashRendered >= 1')
        first = await page.evaluate('performance.now()')
        loaded = await page.evaluate("""() => ({knock: !!window.FrogdashKnock, graphs: !!window.FrogdashGraphs,
            scripts: [...document.scripts].map(s => s.src.split('/').pop().split('?')[0]).filter(n => ['knock.js', 'graphs.js', 'operations.js', 'navigation.js'].includes(n))})""")
        assert loaded == {'knock': False, 'graphs': False, 'scripts': []}, loaded       # The gauges came first
        assert await page.evaluate('!!window.FrogdashInstruments && !!window.FrogdashCamera && !!window.FrogdashDashcam')
        await page.wait_for_timeout(3000)                     # The first readings settle; the others are still to come
        assert not await page.evaluate('window.frogdashLaterLoaded')
        before = await page.evaluate(LAYOUT)
        await page.wait_for_function('window.frogdashLaterLoaded', timeout=20000)
        after_ms = await page.evaluate('performance.now()') - first
        assert after_ms >= 3500, after_ms                                                # Not straight away
        for name in ('FrogdashKnock', 'FrogdashGraphs', 'FrogdashTaillights', 'FrogdashSummary', 'FrogdashKeyboard', 'FrogdashMap'):
            assert await page.evaluate(f'!!window.{name}'), name
        await page.wait_for_timeout(500)
        after = await page.evaluate(LAYOUT)
        moved = [(a, b) for a, b in zip(before, after) if a != b]
        assert not moved and len(before) == len(after), moved[:5]                      # Nothing on the main screen moved
        assert not errors, errors
        # A press on a later screen's button before it has loaded: it opens once loaded.
        page2 = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors2 = []
        page2.on('pageerror', lambda error: errors2.append(str(error)))
        await page2.goto((ROOT / 'preview/dash.html').as_uri())
        await page2.wait_for_function('window.frogdashRendered >= 1')
        assert not await page2.evaluate('window.frogdashLaterLoaded')
        await page2.locator('#knock-launch').click()
        await page2.wait_for_selector('#knock-overlay[open]', timeout=8000)
        assert await page2.evaluate('window.frogdashLaterLoaded')
        assert not errors2, errors2
        await browser.close()
    print(f'Gauges first: other screens loaded {after_ms / 1000:.1f} s after the first frame, main screen unchanged, early press opens; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
