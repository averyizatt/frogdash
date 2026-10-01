"""Interior lights tab: zones, presets, brightness and off through the preview's simulated gateway."""
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
        zones = page.locator('#interior-zones')
        await page.locator('[data-interior-zone="1"]').click()
        await page.locator('[data-interior-color="#a020ff"]').click()
        await page.wait_for_function("document.getElementById('interior-zones').textContent.includes('Upper: on')")
        assert 'Lower: off' in await zones.inner_text()
        await page.locator('#interior-brightness').fill('100')
        await page.locator('[data-interior-zone="0"]').click()
        await page.locator('[data-interior-apply]').click()
        await page.wait_for_function("document.getElementById('interior-zones').textContent.includes('Lower: on · 100%')")
        await page.locator('[data-interior-off]').click()
        await page.wait_for_function("!document.getElementById('interior-zones').textContent.includes(': on')")
        assert not errors, errors
        await browser.close()
    print('Interior lights: zone selection, presets, brightness, apply and off through the simulated gateway passed.')


if __name__ == '__main__':
    asyncio.run(main())
