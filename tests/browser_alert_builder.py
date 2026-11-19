"""The alert builder (alerts.js), in the preview: + New alert, pick any reading, above a limit
typed in the display's units, save; it is a card under "Your own", goes off on the simulated
car like the built-in alerts, can be changed and deleted. And the JS rule is the Pi's
(alerts.py custom_rule) field for field."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hardware.frogdash import alerts  # noqa: E402


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto((ROOT / 'preview/dash.html').as_uri())
        await page.wait_for_function('window.frogdashRendered > 2')
        await page.evaluate("FrogdashUnits.set('us'); frogdashDemo.scenario('normal')")
        await page.click('#drive-launch')
        await page.click('[data-driver-tab="alerts"]')
        await page.wait_for_function("window.FrogdashAlerts?.ready", timeout=15000)
        await page.click('#alert-new')
        await page.wait_for_selector('#alert-builder[open]')
        assert await page.is_disabled('#alert-builder-save')
        await page.fill('#alert-builder-filter', 'coolant')
        await page.click('#alert-builder-list [data-reading="engine.coolant_c"]')
        assert await page.input_value('#alert-builder-name') == 'Coolant high'          # Named from the reading
        assert await page.text_content('#alert-builder-unit') == '°F'
        await page.fill('#alert-builder-limit', '150')                                    # The demo's coolant is above it
        await page.fill('#alert-builder-delay', '0')
        await page.click('[data-ab-severity="critical"]')
        await page.click('#alert-builder-save')
        card = '.alert-widget[data-key="u1"]'
        await page.wait_for_selector(card)
        assert 'USR-01 · Your own' in await page.text_content(f'{card} .alert-code')
        await page.wait_for_function(f"document.querySelector('{card}').dataset.state === 'active'")
        assert await page.get_attribute(card, 'data-severity') == 'critical'
        settings = await page.evaluate("window.FrogdashDrive.current().settings")
        definition = settings['custom'][0]
        assert abs(definition['limit'] - (150 - 32) / 1.8) < 1e-3, definition               # Kept in °C
        assert settings['rules']['u1'] == {'enabled': True, 'delay': 0, 'limit': definition['limit']}
        # The Pi takes the same settings and makes the same rule.
        checked = alerts.validate_settings(settings)
        js_rule = await page.evaluate("key => window.FrogdashDrive.current().settings.custom.find(c => c.key === key)", 'u1')
        assert checked['custom'][0] == js_rule
        # Changed: below 300 °F now, so it stops.
        await page.click(f'{card} .alert-widget-main')
        await page.click('#alert-detail button:has-text("Change")')
        await page.wait_for_selector('#alert-builder[open]')
        assert await page.input_value('#alert-builder-limit') == '150'
        await page.click('[data-ab-op="<"]')
        assert await page.input_value('#alert-builder-name') == 'Coolant high'          # Named by hand: kept
        await page.fill('#alert-builder-limit', '100')
        await page.click('#alert-builder-save')
        await page.wait_for_function(f"document.querySelector('{card}').dataset.state !== 'active'")
        # Deleted.
        await page.click(f'{card} .alert-widget-main')
        await page.click('#alert-detail button:has-text("Change")')
        await page.click('#alert-builder-delete')
        await page.wait_for_function(f"!document.querySelector('{card}')")
        assert '0 going off' not in await page.text_content('#alerts-summary')
        # The JS rule and the Pi's, for the same definition, field for field.
        for definition in ({'key': 'u7', 'name': 'Trans hot', 'signal': 'ecu.transmission_temp_c', 'op': '>', 'limit': 110, 'severity': 'warning', 'running': True},
                           {'key': 'u12', 'name': 'Low', 'signal': 'ecu.my_reading', 'op': '<', 'limit': -3.5, 'severity': 'critical', 'running': False}):
            settings = {'version': 2, 'rules': {}, 'custom': [definition]}
            js = await page.evaluate("s => { window.FrogdashDrive.demo.settings = s; return null; }", settings)
            await page.wait_for_function(f"document.querySelector('.alert-widget[data-key=\"{definition['key']}\"]')")
            py = alerts.all_rules(alerts.validate_settings(settings))[definition['key']]
            got = await page.evaluate(f"key => window.frogdashAlertRuleOf(key)", definition['key'])
            assert json.loads(json.dumps(py)) == got, (py, got)
        assert not errors, errors
        await browser.close()
    print('Alert builder: any reading, limit in the display units, goes off on the simulated car, changed and deleted; the same rule as the Pi; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
