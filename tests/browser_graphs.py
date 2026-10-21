"""Live graphs (graphs.js, uPlot), in the preview: recorded from page load, six charts drawn
with values in their legends, the time window and Hold work, nothing spills off the screen,
on the dash's screen and at phone width."""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        for width, height in ((1920, 720), (390, 844)):
            page = await browser.new_page(viewport={'width': width, 'height': height})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.add_init_script('window.frogdashLaterDelay = 0')   # The other screens straight after the gauges
            await page.goto((ROOT / 'preview/index.html').as_uri())
            await page.wait_for_function('window.frogdashLaterLoaded', timeout=20000)   # Everything after the gauges (later.js)
            await page.wait_for_function('window.frogdashRendered > 2')
            await page.wait_for_function('window.FrogdashGraphs.points >= 8', timeout=8000)   # Recording before it is opened
            await page.evaluate('window.FrogdashGraphs.open()')
            await page.wait_for_selector('#graphs-dialog[open]')
            assert await page.locator('#graphs-grid .graphs-card').count() == 6
            assert await page.locator('#graphs-grid canvas').count() == 6
            assert await page.locator('[data-window="300"]').get_attribute('aria-pressed') == 'true'
            # The demo's RPM has values: without a pointer over the chart, its legend shows the newest.
            await page.locator('[data-window="60"]').click()
            await page.mouse.move(5, 5)
            await page.wait_for_function("""() => /[0-9]/.test(document.querySelector('#graphs-grid .graphs-card:nth-child(2) .u-legend .u-series:nth-child(2) .u-value')?.textContent || '')""", timeout=4000)
            legend = await page.locator('#graphs-grid .graphs-card:nth-child(2) .u-legend').inner_text()
            assert 'RPM' in legend, legend
            # Nothing wider than the dialog.
            overflow = await page.evaluate("""() => {
                const box = document.getElementById('graphs-dialog').getBoundingClientRect();
                return [...document.querySelectorAll('#graphs-dialog *')].filter(n => {
                    const r = n.getBoundingClientRect();
                    return r.width && (r.right > box.right + 1 || r.left < box.left - 1);
                }).map(n => n.className || n.tagName).slice(0, 5);
            }""")
            assert not overflow, overflow
            assert await page.locator('[data-window="60"]').get_attribute('aria-pressed') == 'true'
            await page.locator('[data-window="900"]').click()
            assert await page.locator('[data-window="60"]').get_attribute('aria-pressed') == 'false'
            await page.locator('#graphs-hold').click()
            assert await page.locator('#graphs-hold').inner_text() == 'Follow'
            assert (await page.locator('#graphs-note').inner_text()).startswith('Held at')
            await page.locator('#graphs-hold').click()
            if width > 600:
                await page.screenshot(path=str(ROOT / '.tmp/graphs.png'))
            await page.locator('#graphs-close').click()
            assert not await page.locator('#graphs-dialog').evaluate('d => d.open')
            assert not errors, errors
            await page.close()
        await browser.close()
    print('Live graphs: recorded from load, six charts with live legends, window and Hold, no overflow; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
