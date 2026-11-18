"""The setup wizard (wizard.js), in the preview: ?wizard opens it on the first page; every
built-in ECU profile is offered; choosing one sets the CAN bus to its speed and keeps
water/meth (which needs a MegaSquirt) off; the review lists the changes first; Apply in the
preview saves nothing and says so; ?wizard=4 opens the fourth page; Dash management opens
it too; no errors."""
import argparse
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
PROFILES = sorted(p.stem for p in (ROOT / 'hardware/frogdash/ecu/profiles').glob('*.json'))


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        url = (ROOT / 'preview/dash.html').as_uri()
        await page.goto(url + '?wizard')
        await page.wait_for_selector('#setup-wizard[open]', timeout=20000)
        assert await page.text_content('#wizard-title') == 'Start from'
        assert await page.get_attribute('[data-wizard-preset="foxbody"]', 'aria-pressed') == 'true'   # The car as it is
        await page.click('#wizard-next')
        assert await page.text_content('#wizard-title') == 'Screen'
        assert await page.get_attribute('[data-wizard-screen="1920x720"]', 'aria-pressed') == 'true'
        assert await page.is_checked('input[data-wizard-path="screen.mode"]')                     # The car's panel is forced
        await page.click('[data-wizard-screen="800x480"]')
        assert not await page.is_checked('input[data-wizard-path="screen.mode"]')
        assert await page.is_disabled('input[data-wizard-path="screen.mode"]')                    # Only the bar panel is forced
        await page.click('#wizard-next')
        offered = await page.evaluate("[...document.querySelectorAll('[data-wizard-ecu]')].map(b => b.dataset.wizardEcu).sort()")
        assert offered == PROFILES, offered
        await page.click('[data-wizard-ecu="haltech"]')
        assert await page.get_attribute('[data-wizard-ecu="haltech"]', 'aria-pressed') == 'true'
        assert await page.input_value('select[data-wizard-path="ecu.bitrate"]') == '1000000'          # Haltech's 1 Mbit/s
        for _ in range(4):
            await page.click('#wizard-next')
        assert await page.text_content('#wizard-title') == 'Frogdash modules'
        assert await page.is_disabled('input[data-wizard-path="modules.watermeth"]')
        assert not await page.is_checked('input[data-wizard-path="modules.watermeth"]')
        await page.click('#wizard-next')
        assert await page.text_content('#wizard-title') == 'On the dash'
        await page.click('input[data-wizard-path="features.race"]')
        await page.click('[data-wizard-page="10"]')                                                  # Straight to the review
        assert await page.text_content('#wizard-title') == 'Review and apply'
        rows = await page.evaluate("[...document.querySelectorAll('.wizard-review tr')].map(r => [r.className, r.cells[0].textContent, r.cells[1].textContent])")
        changed = [r[1:] for r in rows if r[0] == 'changed']
        assert changed == [['ECU', 'Haltech'], ['CAN bus speed', '1000 kbit/s'], ['Water/meth', 'Off'], ['Screen', '800 × 480'],
                           ['Force 1920 × 720', 'Off'], ['Race timer', 'Off']], changed
        assert all(r[0] == 'changed' for r in rows[:len(changed)])                                   # Changes first
        await page.click('#wizard-next')
        await page.wait_for_function("document.getElementById('wizard-progress').textContent.includes('Nothing was saved')", timeout=8000)
        await page.click('#wizard-close')
        assert not await page.evaluate("document.getElementById('setup-wizard').open")

        await page.goto(url + '?wizard=4')
        await page.wait_for_selector('#setup-wizard[open]', timeout=20000)
        assert await page.text_content('#wizard-title') == 'CAN board'
        await page.click('#wizard-close')
        await page.evaluate("window.frogdashLater")
        await page.evaluate("document.getElementById('operations-dialog').showModal()")             # Dash management
        await page.click('#operations-dialog .ops-wizard-open')                                      # Setup checklist's box
        await page.wait_for_selector('#setup-wizard[open]', timeout=8000)
        assert await page.text_content('#wizard-title') == 'Start from'
        await page.click('#wizard-close')
        await page.click('#operations-dialog [data-ops-tab="terminal"]')
        await page.click('#operations-dialog .ops-wizard-tab')                                       # The sidebar entry, from any tab
        await page.wait_for_selector('#setup-wizard[open]', timeout=8000)
        assert not errors, errors
        await browser.close()
    print(f'Setup wizard: {len(PROFILES)} ECU profiles offered, Haltech sets 1 Mbit/s, review lists {json.dumps(changed)}; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
