"""The on-screen keyboard (keyboard.js): a text field clicked with the mouse brings it up,
inside the open dialog; its keys type, shift, switch to symbols, delete, move the caret
and send Enter; Done and a click elsewhere put it away; Tab on a real keyboard does not
bring it up."""
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
        await page.goto((ROOT / 'preview/dash.html').as_uri())
        await page.wait_for_timeout(1200)
        await page.locator('#controls-launch').click()
        await page.locator('#tab-wifi').click()
        field = page.locator('#net-password')
        await field.click()
        pad = page.locator('#osk')
        await pad.wait_for(state='visible')
        assert await pad.evaluate("el => !!el.closest('dialog')"), 'inside the dialog, so its keys are not inert'
        box = await pad.bounding_box()
        assert box['y'] + box['height'] <= 720.5 and box['width'] >= 1900, box

        async def tap(key):
            await pad.locator(f'button[data-key="{key}"]').first.click()
        for key in ('shift', 'H', 'u', 'n', 't', 'e', 'r', '2'):
            await tap(key)
        assert await field.input_value() == 'Hunter2'
        assert await page.evaluate("document.activeElement.id") == 'net-password'      # The keys never take the focus
        await tap('symbols')
        await tap('!')
        await tap('letters')
        await tap('backspace')
        await tap('left')
        await tap('x')
        assert await field.input_value() == 'Hunterx2', await field.input_value()
        await page.screenshot(path=str(ROOT / '.tmp/keyboard.png'))
        await tap('done')
        await pad.wait_for(state='hidden')

        # Tab from a real keyboard into the field: no on-screen keyboard.
        await page.locator('#net-connect').focus()
        await page.keyboard.press('Shift+Tab')
        await page.keyboard.press('Shift+Tab')
        await page.wait_for_timeout(200)
        assert await pad.is_hidden()

        # Enter reaches the field (the Terminal sends a command on Enter).
        await field.click()
        await pad.wait_for(state='visible')
        await field.evaluate("el => el.addEventListener('keydown', e => { if (e.key === 'Enter') el.dataset.entered = '1'; })")
        await tap('enter')
        assert await field.get_attribute('data-entered') == '1'
        # A click elsewhere puts it away.
        await page.locator('#wifi-summary').click()
        await pad.wait_for(state='hidden')
        assert not errors, errors
        await browser.close()
    print('On-screen keyboard: opens on a mouse click inside the dialog, types, shift, symbols, delete, caret, Enter, Done, click away; not on Tab; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
