"""The drive summary at key-off (summary.js), in the preview: Key off brings the summary up
over everything with the shutdown countdown; Key on puts the gauges back; the app menu's Last drive
shows it again."""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto((ROOT / 'preview/index.html').as_uri())
        await page.wait_for_function('window.frogdashRendered > 2')
        assert not await page.locator('#summary-dialog').evaluate('d => d.open')
        await page.locator('#demo-key').click()
        await page.wait_for_selector('#summary-dialog[open]', timeout=4000)
        grid = await page.locator('#summary-grid').inner_text()
        for figure in ('Distance', '13.3', 'mi', 'Peak boost', '8.2', 'psi', '5240', 'Water / meth sprayed', '48'):
            assert figure in grid, (figure, grid)
        await page.wait_for_function("/^[0-9]+ s$/.test(document.getElementById('summary-seconds').textContent)")
        assert await page.locator('#summary-grid li[data-tone="warn"]').count() == 2      # Knock and problems
        await page.screenshot(path=str(ROOT / '.tmp/summary.png'))
        await page.locator('#demo-key').evaluate('b => b.click()')                       # Key on again
        await page.wait_for_function("!document.getElementById('summary-dialog').open", timeout=4000)
        await page.evaluate("window.FrogdashSummary.open()")      # The app menu's Last drive
        await page.wait_for_selector('#summary-dialog[open]')
        assert await page.locator('#summary-title').inner_text() == 'This drive so far'
        assert await page.locator('#summary-countdown').is_hidden()
        await page.locator('#summary-close').click()
        assert not errors, errors
        await browser.close()
    print('Drive summary: key off shows it with the countdown, key on closes it, Last drive opens it; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
