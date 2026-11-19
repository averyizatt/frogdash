"""Analog sensors in the setup wizard (wizard.js, Car signals page), in the preview: a pressure
sender from the list of common ones, a thermistor with its temperatures typed in °F, the fuel
sender's input taken; the review lists them, and the profile the wizard would apply is one
the Pi accepts (sysconfig.validate) with the values in psi and °C."""
import argparse
import asyncio
from pathlib import Path
import sys
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hardware.frogdash import sysconfig  # noqa: E402


async def change(page, selector, value):
    await page.fill(selector, value)
    await page.locator(selector).evaluate('n => n.dispatchEvent(new Event("change", {bubbles: true}))')


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto((ROOT / 'preview/dash.html').as_uri() + '?wizard=0')
        await page.wait_for_selector('#setup-wizard[open]', timeout=20000)
        await page.click('[data-wizard-preset="generic"]')
        await page.click('[data-wizard-page="6"]')                                   # Car signals
        # The fuel sender on A0: that input is taken.
        await page.click('[data-wizard-pick="signals.fuel.source"][data-value="adc"]')
        assert 'The fuel sender' in await page.locator('.sensor-row-wizard >> nth=0').text_content()
        # A1: a 0-150 psi sender for oil pressure, through a divider.
        await page.click('[data-wizard-pick="sensors.a1.type"][data-value="linear"]')
        await page.select_option('select[data-wizard-sender="a1"]', 'p150')
        assert await page.input_value('input[data-wizard-path="sensors.a1.v2_value"]') == '150'
        await change(page, 'input[data-wizard-path="sensors.a1.divider_pct"]', '66')
        # A2: a thermistor for the transmission, its points typed in °F.
        await page.click('[data-wizard-pick="sensors.a2.type"][data-value="thermistor"]')
        await page.select_option('select[data-wizard-path="sensors.a2.reading"]', 'trans_temp')
        await page.select_option('select[data-wizard-sender="a2"]', 'gm')
        assert await page.input_value('input[data-wizard-path="sensors.a2.t3_c"]') == '212'         # 100 °C shown in °F
        await change(page, 'input[data-wizard-path="sensors.a2.t1_c"]', '-40')
        await change(page, 'input[data-wizard-path="sensors.a2.r1_ohm"]', '100700')
        # A3: a reading of its own, in volts.
        await page.click('[data-wizard-pick="sensors.a3.type"][data-value="linear"]')
        await page.select_option('select[data-wizard-path="sensors.a3.reading"]', 'custom')
        await change(page, 'input[data-wizard-path="sensors.a3.name"]', 'Rail volts')
        await page.select_option('select[data-wizard-path="sensors.a3.unit"]', 'v')
        draft = await page.evaluate('window.frogdashWizard.draft')
        profile = sysconfig.validate(draft)
        a1, a2 = profile['sensors']['a1'], profile['sensors']['a2']
        assert (a1['reading'], a1['v2_value'], a1['divider_pct']) == ('oil_pressure', 150, 66), a1
        assert (a2['reading'], a2['t1_c'], a2['r1_ohm'], a2['t3_c']) == ('trans_temp', -40, 100700, 100), a2
        assert profile['sensors']['a3']['name'] == 'Rail volts'
        assert "FD_ADC_INPUTS='1'" in sysconfig.shell(profile)
        await page.click('[data-wizard-page="10"]')                                  # Review
        rows = await page.evaluate("[...document.querySelectorAll('.wizard-review tr.changed')].map(r => r.cells[0].textContent + ': ' + r.cells[1].textContent)")
        assert any(r.startswith('Sensor on A1: Oil pressure') for r in rows), rows
        assert any(r.startswith('Sensor on A2: Transmission temperature: thermistor') for r in rows), rows
        assert not errors, errors
        await browser.close()
    print('Wizard sensors: a pressure sender from the list through a divider, a thermistor in °F, a reading of its own; the Pi accepts the profile; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
