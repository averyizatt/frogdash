"""The custom ECU editor (ecu-editor.js), in the preview: Custom ECU opens it from the
wizard's ECU page; the reference car's frames are on its bus; tapping an ID adds the frame;
a reading set to two bytes at byte 0 shows the MicroSquirt's RPM live; Done hands the
profile back to the wizard, whose review lists it. And the editor's decoder gives what the
dash's own (hardware/frogdash/ecu) gives for every kind of layout, bit for bit."""
import argparse
import asyncio
import math
import random
import sys
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hardware.frogdash import ecu  # noqa: E402

LAYOUTS = ['u8@3', 's8@7', 'u16@0', 's16@6', 'u16le@1', 's16le@5', 'u32@2', 's32le@4', 'f32@0', 'f32le@4',
           'bit@2.5', 'nib@6.4', 'ule@3:11', 'sle@20:13', 'ube@7:16', 'sbe@19:12', 'ube@44:9', 'ule@0:32']


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto((ROOT / 'preview/dash.html').as_uri() + '?wizard=3')
        await page.wait_for_selector('#setup-wizard[open]', timeout=20000)
        await page.click('[data-wizard-ecu="custom"]')
        await page.click('[data-wizard-custom-edit]')
        await page.wait_for_selector('#ecu-editor[open]')
        assert await page.locator('[data-ee-bus="1512"]').count() == 1                      # 0x5E8 from the recording
        await page.click('[data-ee-bus="1512"]')
        await page.click('[data-ee-add="signal"]')
        assert await page.input_value('#ee-signal select') == 'ecu.rpm'                     # The first reading not yet used
        await page.click('[data-ee-pick="kind"][data-value="u16"]')
        await page.wait_for_function("document.querySelector('[data-ee-value=\"0\"]').textContent !== '—'")
        rpm = float(await page.text_content('[data-ee-value="0"]'))
        assert 500 < rpm < 8000, rpm
        await page.click('#ee-done')
        assert await page.locator('#ecu-editor[open]').count() == 0
        assert '1 frame, 1 reading' in await page.text_content('.wizard-custom')
        await page.click('[data-wizard-page="10"]')                                          # Review
        assert 'Custom ECU profile' in await page.text_content('.wizard-review')

        # The same decoder as the dash's, for random frames and every kind of layout.
        rng, cases = random.Random(7), []
        for _ in range(60):
            data = bytes(rng.randrange(256) for _ in range(8))
            for layout in LAYOUTS:
                spec = {'layout': layout, 'scale': rng.choice([1, 0.1, 0.01, 2.5]), 'offset': rng.choice([0, -40, 100])}
                if rng.random() < .3:
                    spec['from'] = rng.choice(['degF', 'psi', 'mph', 'K', 'bar'])
                want = ecu.converter(spec)(ecu.reader(layout, 8)(data))
                want = want if math.isfinite(want) else None             # A float that is not a number: shown as —
                cases.append({'spec': spec, 'data': list(data), 'want': want})
        got = await page.evaluate("cases => cases.map(c => window.frogdashEcuEditor.value(c.spec, 8, c.data))", cases)
        bad = [(c['spec'], bytes(c['data']).hex(), c['want'], g) for c, g in zip(cases, got)
               if not (g == c['want'] or (None not in (g, c['want']) and abs(g - c['want']) <= 1e-9 * max(1, abs(c['want']))))]
        assert not bad, bad[:5]
        assert not errors, errors
        await browser.close()
    print(f'Custom ECU editor: frame from the bus, live RPM {rpm:.0f}, back to the wizard; {len(cases)} decodes match the dash; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
