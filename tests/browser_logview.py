"""The Log viewer (Drive > Log viewer, mlgplot.js) in the preview, on its simulated drives: the
list of logs first, a log opened from it as one graph, a drag zooms in, the cursor shows each
channel on the graph, channels are put on and taken off from the list (and remembered), the
search finds one, the keys move and zoom, ‹ Logs goes back, and nothing goes to the network."""
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
        await page.evaluate("localStorage.removeItem('frogdash-logview-channels'); frogdashDemo.scenario('normal')")
        await page.locator('#drive-launch').click()
        await page.locator('[data-driver-tab="logs"]').click()

        # First the list: every log, newest first, with its day, start, length and size.
        await page.wait_for_selector('.lv-file[data-log]')
        rows = page.locator('.lv-file[data-log]')
        assert await rows.count() == 4
        first = await rows.first.locator('span').all_text_contents()
        assert first[2] == '15 min' and first[3] == '1.8 MB', first
        assert await page.locator('#lv-viewer').is_hidden()

        # A log opened: one graph of the starting channels, the whole log on screen.
        await rows.nth(1).click()
        await page.wait_for_selector('#lv-plot canvas')
        assert await page.locator('#lv-browser').is_hidden()
        assert await page.evaluate('FrogdashLogView.channels') == ['RPM', 'AFR', 'AFR Target 1', 'Boost psi']
        assert (await page.evaluate('FrogdashLogView.view'))['end'] == 1680
        assert await page.locator('#lv-plot canvas').count() == 1, 'One graph'
        assert '28 min' in await page.locator('#lv-title').text_content()

        # A drag across the graph zooms into that stretch.
        box = await page.locator('#lv-plot .u-over').bounding_box()
        y = box['y'] + box['height'] / 2
        await page.mouse.move(box['x'] + box['width'] * .2, y); await page.mouse.down()
        await page.mouse.move(box['x'] + box['width'] * .3, y, steps=6); await page.mouse.up()
        await page.wait_for_function("FrogdashLogView.view.end - FrogdashLogView.view.start < 250")
        view = await page.evaluate('FrogdashLogView.view')
        assert 250 < view['start'] < 400 and view['end'] - view['start'] < 250, view   # Around 20-30 % of 28 min

        # The cursor: each channel on the graph shows its value then, beside min, average and max.
        await page.mouse.move(box['x'] + box['width'] * .5, y)
        await page.wait_for_function("document.getElementById('lv-at').textContent.startsWith('At ')")
        rpm = page.locator('.lv-channel[data-channel="RPM"]')
        assert await rpm.get_attribute('aria-pressed') == 'true'
        value = await rpm.locator('b').text_content()
        assert value.isdigit() and 800 < int(value) < 6000, value
        assert len(await rpm.locator('span').all_text_contents()) >= 4

        # Channels on and off from the list; the choice is kept for the next log.
        await page.locator('.lv-channel[data-channel="MAP"]').click()
        assert 'MAP' in await page.evaluate('FrogdashLogView.channels')
        await page.locator('.lv-channel[data-channel="AFR Target 1"]').click()
        assert 'AFR Target 1' not in await page.evaluate('FrogdashLogView.channels')
        assert await page.evaluate("JSON.parse(localStorage.getItem('frogdash-logview-channels')).includes('MAP')")
        # The search finds one by its name.
        await page.locator('#lv-find').fill('oil')
        names = await page.locator('.lv-channel[data-channel]').evaluate_all('rows => rows.map(r => r.dataset.channel)')
        assert names == ['OilPressure'], names
        await page.locator('#lv-find').fill('')

        # Keys (and the steering wheel): ON on the graph, then Up zooms in and Left goes earlier;
        # ON again gives the arrows back to moving between controls.
        await page.locator('#lv-plot').focus()
        await page.keyboard.press('Enter')
        await page.wait_for_function("document.getElementById('lv-plot').classList.contains('wheel-editing')")
        before = await page.evaluate('FrogdashLogView.view')
        await page.keyboard.press('ArrowUp')
        after = await page.evaluate('FrogdashLogView.view')
        assert abs((after['end'] - after['start']) * 2 - (before['end'] - before['start'])) < .01, (before, after)
        await page.keyboard.press('ArrowLeft')
        assert (await page.evaluate('FrogdashLogView.view'))['start'] < after['start']
        await page.keyboard.press('Enter')
        await page.locator('[data-lv="all"]').click()
        assert (await page.evaluate('FrogdashLogView.view')) == {'start': 0, 'end': 1680}

        # ‹ Logs: back to the list; another log opens with the same channels.
        await page.locator('#lv-back').click()
        await page.wait_for_selector('#lv-browser:not([hidden]) .lv-file[data-log]')
        await page.locator('.lv-file[data-log]').first.click()
        await page.wait_for_selector('#lv-plot canvas')
        assert 'MAP' in await page.evaluate('FrogdashLogView.channels')

        # Opened at once, before the menus' files have loaded (the normal delay, not 0): it comes up
        # by itself when they arrive, on the preview's simulated drives, not asking for the Pi's logs.
        early = await browser.new_page(viewport={'width': 1920, 'height': 720})
        early.on('pageerror', lambda error: errors.append(str(error)))
        await early.goto((ROOT / 'preview/dash.html').as_uri())
        await early.wait_for_function("document.getElementById('drive-launch')")
        await early.locator('#drive-launch').click()
        await early.locator('[data-driver-tab="logs"]').click()
        await early.wait_for_selector('.lv-file[data-log]', timeout=20000)
        assert 'could not' not in await early.locator('#lv-browser-note').text_content()

        assert not errors, errors
        assert not network, network
        await browser.close()
    print('Log viewer: list of logs, one graph, drag to zoom, cursor values with min/avg/max, channels on and off and kept, search, keys, back to the list; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
