"""Exercise default animated preview, synchronized signals and playback controls."""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
ROOT = Path(__file__).resolve().parents[1]

async def main(path):
    (ROOT / '.tmp').mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=path)
        page = await browser.new_page(viewport={'width':1920, 'height':720})
        errors, requests = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: requests.append(r.url) if r.url.startswith(('http:', 'https:')) else None)
        await page.goto((ROOT / 'preview/index.html').as_uri())
        await page.evaluate("""window.demoSamples=[]; addEventListener('frogdash-state', e => {
          const v=e.detail.snapshot.values;
          demoSamples.push({rpm:v['engine.rpm'].value,speed:v['vehicle.speed_kph'].value,
            boost:v['engine.boost_kpa'].value,brake:v['lighting.brake'].value,fuel:v['vehicle.fuel_pct'].value});
        });""")
        await page.wait_for_timeout(4200)
        assert await page.evaluate('new Set(demoSamples.map(s=>s.rpm)).size > 20')
        assert await page.evaluate('demoSamples.at(-1).speed > demoSamples[0].speed')
        assert await page.locator('#rpm-bar-fill').get_attribute('stroke-dasharray') != '0 100'
        await page.locator('#demo-motion').click()
        await page.wait_for_timeout(150)
        frozen = await page.evaluate('demoSamples.at(-1)')
        await page.wait_for_timeout(500)
        assert frozen == await page.evaluate('demoSamples.at(-1)'), 'Pause must freeze every generated gauge'
        await page.locator('#demo-driving').click()
        await page.wait_for_function('demoSamples.at(-1).speed === 0')
        await page.locator('#appearance-launch').click()
        await page.locator('#appearance-tab-custom').click()
        await page.wait_for_function('!document.getElementById("appearance-custom").inert')
        await page.locator('#appearance-transparency').fill('35')
        await page.locator('#appearance-close').click()
        await page.locator('#demo-driving').click()
        await page.wait_for_function('demoSamples.at(-1).speed > 0')
        # Complete the braking segment with real elapsed time, exercising the full cycle.
        await page.wait_for_function('demoSamples.some(s=>s.brake && s.boost < -40)', timeout=30000)
        assert await page.evaluate('demoSamples.some(s=>s.rpm>5500) && demoSamples.some(s=>s.boost>70)')
        assert await page.evaluate('demoSamples.every(s=>Number.isFinite(s.fuel) && s.fuel >= 0 && s.fuel <= 100)')
        assert await page.locator('#connection-summary').inner_text() == 'DEMO \u00b7 SIMULATED'
        await page.locator('#demo-motion').click()
        for width,height in [(1920,720),(1280,480),(960,360)]:
            await page.set_viewport_size({'width':width,'height':height})
            await page.wait_for_timeout(80)
            assert await page.locator('.topbar').evaluate("""bar => {
              const children=[...bar.children].filter(x=>x.checkVisibility()).map(x=>x.getBoundingClientRect());
              return children.every((r,i)=>!i || r.left >= children[i-1].right - 1);
            }"""), 'Preview controls overlap the header'
        await page.screenshot(path=str(ROOT / '.tmp/demo-dynamic.png'))
        assert not errors, errors
        assert not requests, requests
        await browser.close()
    print('Animated driving cycle, shifting, boost/vacuum, braking, pause/resume, parked editing and preview layout passed.')

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
