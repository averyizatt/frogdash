"""Interior lights page: power, which lights, brightness and colour through the preview's simulated gateway."""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto((ROOT / 'preview' / 'index.html').as_uri())
        await page.locator('#controls-launch').click()
        await page.locator('#tab-interior').click()
        status = "document.getElementById('interior-zones').textContent"
        await page.locator('[data-interior-zone="1"]').click()
        await page.locator('[data-interior-color="#a020ff"]').click()      # A colour applies at once.
        await page.wait_for_function(f"{status}.includes('Upper: on · 50%') && {status}.includes('Lower: off')")
        assert await page.locator('#interior-strip-upper').get_attribute('data-state') == 'on'
        await page.locator('[data-interior-zone="0"]').click()
        await page.locator('[data-interior-level="100"]').click()          # So does a brightness.
        await page.wait_for_function(f"{status}.includes('Lower: on · 100%')")
        assert await page.locator('[data-interior-level="100"]').get_attribute('aria-pressed') == 'true'
        await page.locator('[data-interior-off]').click()
        await page.wait_for_function(f"!{status}.includes(': on')")
        await page.locator('[data-interior-on]').click()                   # ON restores the chosen colour and level.
        await page.wait_for_function(f"{status}.includes('Upper: on · 100%')")
        # Odometer: set from the Trips page, shown under the speed.
        await page.locator('#controls-close').click()
        await page.locator('#drive-launch').click()
        await page.locator('[data-driver-tab="trip"]').click()
        await page.locator('#odometer-input').fill('67456')
        await page.locator('#odometer-apply').click()
        await page.wait_for_function("document.getElementById('odometer-reading').textContent.includes('67,456')")
        assert '67,45' in await page.locator('#odometer').text_content()
        assert not errors, errors
        await browser.close()
    print('Interior lights: power, lights, brightness and colour apply at once; odometer set and shown; passed.')


if __name__ == '__main__':
    asyncio.run(main())
