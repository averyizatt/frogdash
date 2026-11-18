"""The setup wizard (wizard.js), in the preview: ?wizard opens it on the first page; the
screen page forces whichever size is picked; every built-in ECU profile is offered, plus a
custom one; the CAN board is the Waveshare HAT or "Other" with its own crystal and pin; GPS
from USB, the CAN bus or none; each car signal picks a source and its settings; the tuning
software follows the ECU; the reference car's own boards are not offered; the review lists
the changes first; Apply in the preview saves nothing and says so; ?wizard=4 opens page 4;
Dash management opens it too; no errors."""
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
        title = lambda: page.text_content('#wizard-title')
        go = lambda n: page.click(f'[data-wizard-page="{n}"]')
        await page.goto(url + '?wizard')
        await page.wait_for_selector('#setup-wizard[open]', timeout=20000)
        assert await title() == 'Start from'
        assert await page.get_attribute('[data-wizard-preset="foxbody"]', 'aria-pressed') == 'true'   # The car as it is
        await page.click('[data-wizard-preset="generic"]')                                           # A new build

        await page.click('#wizard-next')
        assert await title() == 'Screen'
        assert await page.is_disabled('input[data-wizard-path="screen.mode"]')                       # auto: nothing to force
        await page.click('[data-wizard-screen="1024x600"]')
        await page.click('input[data-wizard-path="screen.mode"]')
        assert 'Force 1024 × 600 at boot' in await page.text_content('.wizard-toggle')

        await page.click('#wizard-next')
        assert await title() == 'Engine computer'
        offered = await page.evaluate("[...document.querySelectorAll('[data-wizard-ecu]')].map(b => b.dataset.wizardEcu)")
        assert sorted(offered) == sorted(PROFILES + ['custom']), offered
        body = await page.text_content('#wizard-body')
        assert 'simulated' not in body.lower() and 'heard now' not in body and 'Running in a car' not in body, body
        await page.wait_for_selector('#wizard-check[data-state="ok"]', timeout=5000)                 # The recording's MicroSquirt talks
        assert 'MicroSquirt is talking' in await page.text_content('#wizard-check')
        await page.click('[data-wizard-ecu="aem"]')
        await page.wait_for_selector('#wizard-check[data-state="other_ecu"]', timeout=5000)
        await page.click('#wizard-check .wizard-check-use')                                          # "Use MicroSquirt"
        assert await page.get_attribute('[data-wizard-ecu="megasquirt"]', 'aria-pressed') == 'true'
        await page.click('[data-wizard-ecu="haltech"]')
        await page.wait_for_selector('#wizard-check[data-state="wrong_speed"]', timeout=5000)        # 1 Mbit/s, the bus 500k

        await page.click('#wizard-next')
        assert await title() == 'CAN board'
        assert not await page.locator('select[data-wizard-path="can_hat.oscillator"]').count()       # Waveshare: nothing to set
        await page.click('[data-wizard-pick="can_hat.board"][data-value="other"]')
        await page.select_option('select[data-wizard-path="can_hat.oscillator"]', '8000000')
        await page.click('[data-wizard-pick="can_hat.present"][data-value="false"]')                 # A USB adapter
        assert not await page.locator('select[data-wizard-path="can_hat.oscillator"]').count()

        await page.click('#wizard-next')
        assert await title() == 'GPS'
        await page.click('[data-wizard-pick="gps.source"][data-value="usb"]')

        await page.click('#wizard-next')
        assert await title() == 'Cameras'
        await page.click('#wizard-next')
        assert await title() == 'Car signals'
        assert not await page.locator('[data-value="module"]').count()                               # No Frogdash boards in a new build
        assert await page.locator('[data-wizard-pick="signals.brake.source"][data-value="ecu"]').count()   # Haltech sends the brake switch
        await page.click('[data-wizard-pick="signals.turn_left.source"][data-value="gpio"]')
        await page.select_option('select[data-wizard-path="signals.turn_left.pin"]', '17')
        await page.click('[data-wizard-pick="signals.fuel.source"][data-value="adc"]')
        await page.fill('input[data-wizard-path="signals.fuel.full_mv"]', '0.45')
        await page.locator('input[data-wizard-path="signals.fuel.full_mv"]').evaluate('n => n.dispatchEvent(new Event("change", {bubbles: true}))')

        await page.click('#wizard-next')
        assert await title() == 'On the dash'
        body = await page.text_content('#wizard-body')
        assert 'water/meth' not in body.lower() and 'taillight' not in body.lower(), body
        assert 'Windows tuning for NSP (experimental)' in body, body                                 # Haltech's own tuner
        assert not await page.locator('input[data-wizard-path="tunerstudio"]').count()

        await go(10)
        assert await title() == 'Review and apply'
        rows = await page.evaluate("[...document.querySelectorAll('.wizard-review tr.changed')].map(r => [r.cells[0].textContent, r.cells[1].textContent])")
        found = dict(rows)
        assert found['Screen'] == '1024 × 600' and found['Forced at boot'] == 'Yes, 1024 × 600', found
        assert found['ECU'] == 'Haltech' and found['CAN bus speed'] == '1000 kbit/s', found
        assert found['CAN board'] == 'Other' and found['CAN board type'] == 'USB adapter', found
        assert found['Left turn signal'] == 'Pi pin GPIO 17, low when on', found
        assert found['Fuel level'] == 'ADS1115 A0, 0.50 V empty, 0.45 V full', found
        all_rows = await page.evaluate("[...document.querySelectorAll('.wizard-review tr')].map(r => r.className)")
        assert all_rows[:len(rows)] == ['changed'] * len(rows)                                       # Changes first
        await page.click('#wizard-next')
        await page.wait_for_function("document.getElementById('wizard-progress').textContent.includes('Nothing was saved')", timeout=8000)
        await page.click('#wizard-close')

        await page.goto(url + '?wizard=4')
        await page.wait_for_selector('#setup-wizard[open]', timeout=20000)
        assert await title() == 'CAN board'
        await page.click('#wizard-close')
        await page.evaluate("window.frogdashLater")
        await page.evaluate("document.getElementById('operations-dialog').showModal()")             # Dash management
        await page.click('#operations-dialog .ops-wizard-open')                                      # Setup checklist's box
        await page.wait_for_selector('#setup-wizard[open]', timeout=8000)
        assert not errors, errors
        await browser.close()
    print(f'Setup wizard: {len(PROFILES)} ECU profiles and a custom one, car signals, review {json.dumps(found)}; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
