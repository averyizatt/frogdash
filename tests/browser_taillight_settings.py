"""Taillight settings tabs: readback, live changes, colors, text, save/revert and profiles (simulated controller)."""
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
        await page.evaluate('window.FrogdashTaillights.open()')
        sync = '#tl-panel-style [data-tl-sync]'
        await page.locator('#tl-tab-style').click()
        await page.wait_for_function(f"document.querySelector('{sync}').textContent.includes('match')")
        assert await page.locator('#tl-set-lens_preset').input_value() == '1'  # Read back from the controller.
        assert await page.locator('#tl-show-text').input_value() == 'FOX BODY'
        assert not await page.locator('#tl-gate').is_visible()
        await page.select_option('#tl-set-brake_anim', '5')
        await page.wait_for_function(f"document.querySelector('{sync}').textContent.includes('Unsaved')")
        await page.locator('#tl-show-text').fill('fast')
        await page.locator('#tl-panel-style [data-compute="text"]').click()
        await page.locator('#tl-tab-colors').click()
        await page.locator('#tl-color-turn').evaluate("el => { el.value = '#00ff00'; el.dispatchEvent(new Event('change')); }")
        await page.locator('#tl-set-turn_blink_ms').fill('900')
        await page.locator('#tl-set-turn_blink_ms').dispatch_event('change')
        await page.locator('#tl-tab-profiles').click()
        await page.locator('#tl-panel-profiles [data-compute="revert"]').click()
        await page.wait_for_function("document.getElementById('tl-set-brake_anim').value === '0'")
        assert await page.locator('#tl-color-turn').input_value() == '#ff7a00'
        await page.locator('#tl-tab-style').click()
        await page.select_option('#tl-set-brake_anim', '5')
        await page.locator('#tl-tab-profiles').click()
        await page.locator('#tl-panel-profiles [data-compute="save"]').click()
        await page.wait_for_function(f"document.querySelector('#tl-panel-profiles [data-tl-sync]').textContent.includes('match')")
        slot3 = page.locator('#tl-profile-list [data-slot="2"]')
        await slot3.locator('[data-compute="store"]').click()
        await page.wait_for_function("document.querySelector('#tl-profile-list [data-slot=\"2\"] [data-profile-state]').textContent === 'Saved'")
        await page.locator('#tl-profile-list [data-slot="4"] [data-compute="load"]').click()
        await page.wait_for_function("document.getElementById('tl-ack').textContent.includes('empty')")
        delete = slot3.locator('[data-compute="remove"]')
        await delete.click()
        assert await delete.inner_text() == 'PRESS AGAIN'  # Deleting needs a second press.
        await delete.click()
        await page.wait_for_function("document.querySelector('#tl-profile-list [data-slot=\"2\"] [data-profile-state]').textContent === 'Empty'")
        assert not errors, errors
        await browser.close()
    print('Taillight settings: readback, live style/color/timing/text changes, revert, save, profiles and confirmations passed.')


if __name__ == '__main__':
    asyncio.run(main())
