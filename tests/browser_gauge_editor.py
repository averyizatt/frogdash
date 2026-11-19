"""The screen editor (driving.js), in the preview: press and hold a lower tile, New gauge,
pick any reading the dash has, name it and set its range; it goes in that tile and survives
a reload. Warning zones on a built-in gauge turn the tile red outside them and show on its
track; a custom gauge can be deleted, and its tile goes back to the default."""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def hold(page, selector):
    box = await page.locator(selector).bounding_box()
    await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    await page.mouse.down()
    await page.wait_for_timeout(800)
    await page.mouse.up()


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto((ROOT / 'preview/dash.html').as_uri())
        await page.wait_for_function('window.frogdashRendered > 2')
        await page.evaluate("FrogdashUnits.set('us'); frogdashDemo.scenario('normal')")

        # A new gauge on any reading: the ECU's RPM, as "Revs", 0-8000.
        await hold(page, '.sensor-row:not(.profile-sensors) .sensor-card >> nth=2')
        await page.wait_for_selector('#gauge-picker[open]')
        await page.click('#gauge-picker-new')
        await page.wait_for_selector('#gauge-editor[open]')
        assert await page.is_disabled('#gauge-editor-save')                       # No reading yet
        await page.fill('#gauge-editor-filter', 'rpm')
        await page.click('#gauge-editor-readings [data-reading="engine.rpm"]')
        await page.fill('#gauge-editor-name', 'Revs')
        await page.fill('#gauge-editor-min', '0')
        await page.fill('#gauge-editor-max', '8000')
        await page.fill('#gauge-editor-low', '9000')
        await page.fill('#gauge-editor-high', '100')
        assert 'lower than' in await page.text_content('#gauge-editor-problem')       # Limits the wrong way round
        assert await page.is_disabled('#gauge-editor-save')
        await page.fill('#gauge-editor-low', '')
        await page.fill('#gauge-editor-high', '')
        await page.click('#gauge-editor-save')
        tile = '#profile-sensors .sensor-card >> nth=2'
        await page.wait_for_function("!document.getElementById('profile-sensors').hidden")
        assert await page.locator(tile).locator('h2').text_content() == 'Revs'
        await page.wait_for_function("document.querySelectorAll('#profile-sensors .sensor-card')[2].querySelector('.sensor-reading span').textContent !== '—'")
        assert await page.locator(tile).locator('.scale-labels span').all_text_contents() == ['0', '8000']
        # In the picker's list from now on, and kept over a reload.
        await page.reload()
        await page.wait_for_function('window.frogdashRendered > 2')
        await page.evaluate("frogdashDemo.scenario('normal')")
        assert await page.locator(tile).locator('h2').text_content() == 'Revs'

        # Warning zones on a built-in gauge (coolant, in °F as the display shows it).
        await hold(page, '#profile-sensors .sensor-card >> nth=0')
        await page.click('#gauge-picker-edit')
        await page.wait_for_selector('#gauge-editor[open][data-kind="zones"]')
        assert await page.locator('#gauge-editor-readings-box').is_hidden()
        await page.fill('#gauge-editor-high', '150')                              # The demo's coolant is above it
        await page.click('#gauge-editor-save')
        await page.wait_for_function("document.querySelectorAll('#profile-sensors .sensor-card')[0].dataset.tone === 'danger'")
        left = await page.locator('#profile-sensors .sensor-card >> nth=0').locator('.zone-high').evaluate('n => parseFloat(n.style.left)')
        assert abs(left - (150 - 100) / 150 * 100) < 0.5, left                       # 150 °F on a 100-250 °F track
        stored = await page.evaluate("JSON.parse(localStorage.getItem('frogdash.driving.v1')).zones.coolant.high")
        assert abs(stored - (150 - 32) / 1.8) < 1e-9, stored                          # Kept in °C, the reading's own unit
        # Metric: the same limit, shown as °C.
        await page.evaluate("FrogdashUnits.set('metric')")
        await hold(page, '#profile-sensors .sensor-card >> nth=0')
        await page.click('#gauge-picker-edit')
        assert await page.input_value('#gauge-editor-high') == '65.56'
        await page.click('#gauge-editor-close')

        # Deleting the custom gauge puts the tile's default back.
        await hold(page, tile)
        await page.click('#gauge-picker-edit')
        await page.click('#gauge-editor-delete')
        assert await page.locator('#gauge-picker [data-metric="my1"]').count() == 0
        assert await page.locator(tile).locator('h2').text_content() == 'Fuel pressure'
        assert not errors, errors
        await browser.close()
    print('Screen editor: a gauge for any reading, named and ranged, kept over a reload; warning zones in the display units; delete puts the default back; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
