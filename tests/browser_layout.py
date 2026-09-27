"""Check dashboard submenus at native panel sizes and scaled browser previews.

python tests/browser_layout.py [--browser /path/to/chromium] [--url https://.../]
"""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
SIZES = [(1920, 720), (1980, 720), (1280, 480), (960, 360),
         (1920, 600), (1280, 720), (2560, 1440)]


async def inspect(page, selector, scroll_selector=None):
    problems = await page.locator(selector).evaluate('''(dialog, scrollSelector) => {
      const errors = [];
      const frame = document.getElementById('display').getBoundingClientRect();
      const box = dialog.getBoundingClientRect();
      if (box.left < frame.left - 1 || box.right > frame.right + 1 ||
          box.top < frame.top - 1 || box.bottom > frame.bottom + 1) {
        errors.push('Submenu extends outside the scaled dashboard');
      }
      if (dialog.scrollHeight > dialog.clientHeight + 1 || dialog.scrollWidth > dialog.clientWidth + 1)
        errors.push('Dialog shell overflows');
      const scroller = scrollSelector && dialog.querySelector(scrollSelector);
      if (scroller && (scroller.scrollHeight > scroller.clientHeight + 1 || scroller.scrollWidth > scroller.clientWidth + 1))
        errors.push('Controls or graph require scrolling');
      for (const el of dialog.querySelectorAll('button, input')) {
        if (!el.checkVisibility()) continue;
        const r = el.getBoundingClientRect();
        if (r.left < box.left || r.right > box.right || r.top < box.top || r.bottom > box.bottom)
          errors.push('Control clipped: ' + (el.id || el.textContent));
        const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        if (!el.contains(hit)) errors.push('Control obscured: ' + (el.id || el.textContent));
      }
      return errors;
    }''', scroll_selector)
    assert not problems, (page.viewport_size, selector, problems)


async def main(browser_path=None, url=None):
    (ROOT / '.tmp').mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path, headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(url or (ROOT / 'preview' / 'index.html').as_uri())
        await page.wait_for_function("document.getElementById('rpm-value').textContent === '3450'")
        await page.evaluate("frogdashDemo.scenario('parked')")
        await page.wait_for_timeout(150)
        for width, height in SIZES:
            await page.set_viewport_size({'width': width, 'height': height})
            await page.locator('#meth-cell').click()
            for tab in ('meth', 'knock', 'lighting', 'wifi'):
                await page.locator(f'#tab-{tab}').click()
                await inspect(page, '#controls-dialog', '.control-panels')
                if (width, height) in ((1980, 720), (1280, 480)):
                    await page.screenshot(path=str(ROOT / '.tmp' / f'menu-{tab}-{width}x{height}.png'))
            # Resize an already open submenu; do not rely on reopening to fix its bounds.
            await page.set_viewport_size({'width': 960, 'height': 360})
            await inspect(page, '#controls-dialog', '.control-panels')
            await page.set_viewport_size({'width': width, 'height': height})
            await page.keyboard.press('Escape')
            await page.locator('#drive-launch').click()
            for tab in ('display', 'trip', 'fuel', 'alerts', 'review', 'health'):
                await page.locator(f'[data-driver-tab="{tab}"]').click()
                if tab == 'review':
                    await page.locator('#drive-review .review-toolbar select option').first.wait_for(state='attached')
                await inspect(page, '#drive-dialog', f'[data-driver-panel="{tab}"]')
                if (width, height) in ((1980, 720), (1280, 480)):
                    await page.screenshot(path=str(ROOT / '.tmp' / f'menu-drive-{tab}-{width}x{height}.png'))
            await page.locator('#operations-launch').click()
            for tab in ('setup', 'sender', 'service', 'backup', 'display', 'support'):
                await page.locator(f'[data-ops-tab="{tab}"]').click()
                await inspect(page, '#operations-dialog')
                if (width, height) == (1980, 720):
                    await page.screenshot(path=str(ROOT / '.tmp' / f'management-{tab}.png'))
            await page.locator('#operations-close').click()
            await page.locator('#drive-close').click()
            for launch, dialog, scroll in [('knock-launch', 'knock-overlay', '.knock-body'),
                                           ('race-launch', 'race-dialog', '.race-body'),
                                           ('appearance-launch', 'appearance-dialog', '.appearance-body'),
                                           ('diagnostics-launch', 'diagnostics', None)]:
                await page.locator(f'#{launch}').click()
                await inspect(page, f'#{dialog}', scroll)
                if (width, height) in ((1980, 720), (1280, 480)):
                    await page.screenshot(path=str(ROOT / '.tmp' / f'menu-{dialog}-{width}x{height}.png'))
                if dialog == 'appearance-dialog':
                    await page.locator('#appearance-tab-custom').click()
                    await inspect(page, '#appearance-dialog', '.appearance-body')
                    await page.locator('#appearance-tab-gallery').click()
                if dialog == 'diagnostics':
                    await page.locator('.diagnostics-body').evaluate('(el) => { el.scrollTop = el.scrollHeight; }')
                    await inspect(page, '#diagnostics')
                await page.keyboard.press('Escape')
                assert await page.locator(f'#{launch}').evaluate('(el) => document.activeElement === el')
        assert not errors, errors
        await browser.close()
    print('All 21 submenu views fit the dashboard at all 7 sizes; controls remain visible and clickable, resize and keyboard close work.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    parser.add_argument('--url')
    args = parser.parse_args()
    asyncio.run(main(args.browser, args.url))
