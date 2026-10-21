"""Photo gauge faces (skins.js), in the preview: chosen from the Appearance gallery, the
needles point at the printed marks for the demo's readings, the lamps follow the dash's
indicators, CHECK opens the alerts, and other gauge styles come back cleanly."""
import argparse
import asyncio
from pathlib import Path
import sys

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

# The angle from a dial's pivot to a printed mark: where its needle must point.
NEEDLE = """dial => parseFloat(document.querySelector(`.skin-dial[data-dial="${dial}"] .skin-needle`).style.transform.match(/-?[\\d.]+/)[0])"""


async def main(path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=path, headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors, network = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: network.append(request.url) if request.url.startswith(('http:', 'https:')) else None)
        await page.add_init_script('window.frogdashLaterDelay = 0')
        await page.goto((ROOT / 'preview/index.html').as_uri())
        await page.wait_for_function('window.frogdashLaterLoaded', timeout=20000)
        await page.evaluate("frogdashDemo.scenario('normal')")
        await page.wait_for_function("document.getElementById('rpm-value').textContent === '3450'")
        assert await page.locator('.skin-cluster').count() == 0, 'Built only when chosen'

        await page.locator('#appearance-launch').click()
        await page.locator('[data-collection-filter="retro"]').click()
        await page.locator('button[data-look="ferrari"]').click()
        await page.locator('#appearance-close').click()
        await page.wait_for_function("document.documentElement.dataset.gauges === 'skin-ferrari'")
        await page.wait_for_function("document.querySelector('.skin-cluster')?.checkVisibility()")
        assert not await page.locator('.custom-cluster').is_visible()
        # 3450 rpm: between the 3 and 4 marks; 47 mph between 40 and 60; 62 psi = 4.3 bar, just short of 5.
        await page.wait_for_function("document.querySelector('.skin-dial[data-dial=\"speed\"]').dataset.quality === 'live'")
        await page.wait_for_timeout(300)
        rpm, speed, oil = [await page.evaluate(NEEDLE, d) for d in ('rpm', 'speed', 'oil')]
        assert -57 < rpm < -28, rpm
        assert -85 < speed < -56, speed
        assert -12 < oil < 0, oil
        # No oil temperature or fuel level sender: resting at their stops, dimmed.
        assert await page.locator('.skin-dial[data-dial="oiltemp"]').get_attribute('data-quality') != 'live'
        assert await page.evaluate(NEEDLE, 'fuel') < -30
        # The dash fits on the photo's black edges: top bar and buttons above it, all clickable.
        for selector in ('#drive-launch', '#alerts-launch', '#appearance-launch'):
            box = await page.locator(selector).bounding_box()
            hit = await page.evaluate('([x, y]) => document.elementFromPoint(x, y).closest("button")?.id', [box['x'] + box['width'] / 2, box['y'] + box['height'] / 2])
            assert hit == selector[1:], (selector, hit)
        await page.screenshot(path=str(ROOT / '.tmp/skin-ferrari.png'))

        # Lamps: the headlight lamp from the running lights; CHECK from alerts, and a tap opens them.
        await page.evaluate("frogdashDemo.scenario('night')")
        await page.wait_for_function("document.querySelector('[data-lamp=\"lights\"]').dataset.on === 'true'")
        assert await page.locator('[data-lamp="brake"]').get_attribute('data-on') == 'false'
        await page.evaluate("frogdashDemo.scenario('warning')")
        await page.wait_for_function("document.querySelector('[data-lamp=\"check\"]').dataset.on === 'true'")
        await page.wait_for_function("!document.querySelector('.skin-warning').hidden && document.querySelector('.skin-warning').textContent.includes('COOLANT HIGH')")
        await page.locator('[data-lamp="check"]').click()
        await page.wait_for_function("document.getElementById('drive-dialog').open")
        assert not await page.locator('[data-driver-panel="alerts"]').is_hidden()
        await page.screenshot(path=str(ROOT / '.tmp/skin-ferrari-warning.png'))
        await page.locator('#drive-close').click()

        # Back to another style: the photo goes, the vector dials come back; the choice is kept.
        await page.reload()
        await page.wait_for_function("document.documentElement.dataset.gauges === 'skin-ferrari'")
        await page.locator('#appearance-launch').click()
        await page.locator('[data-appearance-tab="instruments"]').click()
        await page.locator('#appearance-gauges').select_option('foxbody')
        await page.locator('#appearance-close').click()
        await page.wait_for_function("document.querySelector('.custom-cluster').checkVisibility()")
        assert not await page.locator('.skin-cluster').is_visible()
        assert not network, network
        assert not errors, errors
        await browser.close()
    print('Photo face: chosen from the gallery, needles on the printed marks, lamps, CHECK to the alerts, and back to vector dials passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
