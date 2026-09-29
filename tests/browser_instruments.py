"""New clusters: actual pointer movement, data quality, units, saved choices and sizing."""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from browser_layout import inspect
ROOT = Path(__file__).resolve().parents[1]

async def main(executable):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=executable)
        page = await browser.new_page(viewport={'width':1920,'height':720})
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto((ROOT/'preview/index.html').as_uri())
        await page.wait_for_function('window.frogdashRendered > 2')
        await page.locator('#appearance-launch').click()
        await page.locator('[data-collection-filter="retro"]').click()
        for look, kind in [('foxbody','foxbody'),('foxnight','foxbody'),('svo','analog'),('outrun','digital'),('terminal','digital'),('vector','analog')]:
            await page.locator(f'[data-look="{look}"]').click()
            assert await page.locator('html').get_attribute('data-gauges') == kind
            assert await page.locator(f'[data-look="{look}"]').get_attribute('aria-pressed') == 'true'
        await page.locator('#appearance-tab-instruments').click()
        assert await page.locator('[data-accent]').count() == 16
        await page.locator('#appearance-gauges').select_option('foxbody')
        await page.locator('#appearance-needle').fill('#ffbc90')
        await page.get_by_role('button',name='Hot pink',exact=True).click()
        await page.locator('#appearance-close').click()
        needle=page.locator('.cluster-rpm .dial-needle')
        before=await needle.get_attribute('transform')
        await page.wait_for_function('(before)=>document.querySelector(".cluster-rpm .dial-needle").getAttribute("transform")!==before',arg=before)
        await page.reload()
        await page.wait_for_function('window.frogdashRendered > 2')
        assert await page.locator('html').get_attribute('data-gauges') == 'foxbody'
        assert await page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--needle").trim()') == '#ffbc90'
        await page.evaluate("frogdashDemo.scenario('normal')")
        await page.wait_for_function('document.querySelector(".cluster-speed .dial-value").textContent === "47"')
        await page.evaluate("FrogdashUnits.set('metric')")
        await page.wait_for_function('document.querySelector(".cluster-speed .dial-value").textContent === "76"')
        assert await page.locator('.cluster-speed .dial-unit').text_content() == 'km/h'
        assert '240' in await page.locator('.cluster-speed .dial-scale').text_content()
        # Missing/stale/fault data cannot be represented by a valid zero needle.
        for quality in ('unavailable','stale','fault'):
            result=await page.evaluate('''quality=>{
              const snapshot={values:{'engine.rpm':{quality,value:3500}}};
              FrogdashInstruments.render(snapshot,true);
              const gauge=document.querySelector('.cluster-rpm');
              return [gauge.querySelector('.dial-value').textContent,gauge.querySelector('.dial-needle').style.visibility,gauge.querySelector('.cluster-quality').textContent];
            }''',quality)
            assert result[0]=='\u2014' and result[1]=='hidden' and result[2], result
        await page.evaluate('''()=>{
          const shift=document.getElementById('shift-lights');shift.hidden=false;shift.dataset.shift='true';
          [...shift.children].forEach(n=>n.dataset.on='true');
          document.getElementById('warn-banner').hidden=false;document.getElementById('warn-banner').textContent='SENSOR FAULT';
          FrogdashInstruments.render({values:{}},false);
          if(document.querySelector('.cluster-track').hidden || document.querySelector('.cluster-warning').textContent!=='SENSOR FAULT') throw Error('Track or warning lost');
        }''')
        for width,height in ((1920,720),(1280,480),(1920,1080),(1366,768),(800,600),(390,844)):
            await page.set_viewport_size({'width':width,'height':height})
            for kind in ('foxbody','analog','digital'):
                await page.locator('#appearance-launch').click()
                await page.locator('#appearance-tab-instruments').click()
                await page.locator('#appearance-gauges').select_option(kind)
                await inspect(page,'#appearance-dialog')
                await page.locator('#appearance-close').click()
                await page.wait_for_timeout(100)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width,kind)
                for selector in ('.custom-cluster','.cluster-telemetry','.cluster-speed','.cluster-rpm'):
                    box=await page.locator(selector).bounding_box()
                    assert box['x']>=-1 and box['x']+box['width']<=width+1,(width,kind,selector,box)
                if width>=1280:
                    box=await page.locator('#display').bounding_box()
                    assert box['y']>=-1 and box['y']+box['height']<=height+1,(width,kind,box)
            print(f'Custom clusters fit {width} x {height}',flush=True)
        assert not errors,errors
        await browser.close()
    print('Retro and digital presets, live needles, missing signals, unit scales, persistence and menus passed.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
