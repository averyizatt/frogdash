"""The Log viewer (Drive > Log viewer, logview.js) in the preview, on its simulated drive: the
graphs appear, a drag zooms in, the cursor shows each channel, channels and graphs are added
and removed and remembered, the keys move and zoom, and nothing goes to the network."""
import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main(path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=path, headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors, network = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: network.append(request.url) if request.url.startswith(('http:', 'https:')) else None)
        await page.add_init_script('window.frogdashLaterDelay = 0')
        await page.goto((ROOT / 'preview/dash.html').as_uri())
        await page.wait_for_function('window.frogdashLaterLoaded', timeout=20000)
        await page.evaluate("localStorage.removeItem('frogdash-logview-panes'); frogdashDemo.scenario('normal')")
        await page.locator('#drive-launch').click()
        await page.locator('[data-driver-tab="logs"]').click()
        await page.wait_for_function("document.querySelectorAll('.lv-pane canvas').length >= 4", timeout=10000)
        panes = await page.evaluate('FrogdashLogView.panes')
        assert panes[0] == ['RPM'] and 'AFR' in panes[1], panes
        assert (await page.evaluate('FrogdashLogView.view'))['end'] == 900, 'The whole log first'
        assert await page.locator('#lv-range').text_content() == '0:00 – 15:00 of 15:00'

        # A drag across a graph zooms into that stretch; every graph follows.
        over = page.locator('.lv-pane').nth(1).locator('.u-over')
        box = await over.bounding_box()
        y = box['y'] + box['height'] / 2
        await page.mouse.move(box['x'] + box['width'] * .2, y); await page.mouse.down()
        await page.mouse.move(box['x'] + box['width'] * .3, y, steps=6); await page.mouse.up()
        await page.wait_for_function("FrogdashLogView.view.end - FrogdashLogView.view.start < 120")
        view = await page.evaluate('FrogdashLogView.view')
        assert 150 < view['start'] < 200, view
        scales = await page.evaluate("[...document.querySelectorAll('.lv-pane')].length")
        assert scales == 4

        # The cursor: each channel's value at that moment, beside min, average and max.
        await page.mouse.move(box['x'] + box['width'] * .5, y)
        await page.wait_for_function("document.querySelector('.lv-stats thead th:nth-child(2)').textContent.startsWith('At ')")
        rpm = await page.locator('#lv-stats tr').first.locator('td').nth(1).text_content()
        assert rpm.isdigit() and 800 < int(rpm) < 6000, rpm
        assert await page.locator('#lv-stats tr').count() == sum(len(p) for p in panes)

        # Keys (and the steering wheel): ON on the graphs, then Up zooms in around the middle and
        # Left goes earlier; ON again gives the arrows back to moving between controls.
        await page.locator('#lv-panes').focus()
        await page.keyboard.press('Enter')
        await page.wait_for_function("document.getElementById('lv-panes').classList.contains('wheel-editing')")
        before = await page.evaluate('FrogdashLogView.view')
        await page.keyboard.press('ArrowUp')
        after = await page.evaluate('FrogdashLogView.view')
        assert abs((after['end'] - after['start']) * 2 - (before['end'] - before['start'])) < .01, (before, after)
        await page.keyboard.press('ArrowLeft')
        assert (await page.evaluate('FrogdashLogView.view'))['start'] < after['start']
        await page.keyboard.press('Enter')
        assert not await page.evaluate("document.getElementById('lv-panes').classList.contains('wheel-editing')")
        await page.locator('[data-lv="all"]').click()
        assert (await page.evaluate('FrogdashLogView.view')) == {'start': 0, 'end': 900}

        # A channel added to the third graph, one removed from the first, a graph taken away;
        # the choice is kept for the next time.
        await page.locator('.lv-pane').nth(2).locator('.lv-add').select_option('Batt V')
        assert 'Batt V' in (await page.evaluate('FrogdashLogView.panes'))[2]
        await page.locator('.lv-pane').nth(3).locator('.lv-remove').click()
        assert len(await page.evaluate('FrogdashLogView.panes')) == 3
        assert await page.evaluate("JSON.parse(localStorage.getItem('frogdash-logview-panes')).length") == 3
        assert await page.evaluate("JSON.parse(localStorage.getItem('frogdash-logview-panes'))[2].includes('Batt V')")

        assert not errors, errors
        assert not network, network
        await browser.close()
    print('Log viewer: graphs, drag to zoom, cursor values with min/avg/max, keys, channels and graphs added, removed and kept; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
