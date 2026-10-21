"""Camera views, in the preview: the picture in the middle filling its space at its true shape
(cropped, never stretched), speed on the left, controls on the right; the preview draws its
stock photos; the dash cam shows the speed too."""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def layout(page, dialog):
    return await page.evaluate("""dialog => {
      const box = s => document.querySelector(`${dialog} ${s}`).getBoundingClientRect();
      const stage = box('.camera-stage'), info = box('.camera-info'), side = box('.camera-side:not(.camera-info)');
      const shown = [...document.querySelectorAll(`${dialog} .camera-stage :is(img, canvas)`)].find(n => !n.hidden && n.id !== 'camera-guides');
      return {stage: [stage.left, stage.right, stage.width, stage.height], info: [info.left, info.right], side: [side.left, side.right],
              fit: getComputedStyle(shown).objectFit, position: getComputedStyle(shown).objectPosition};
    }""", dialog)


async def lit(page, canvas):
    # Opened as a file, a canvas with the photo drawn on it cannot be read back (the photo
    # 'taints' it): that refusal itself says the photo is there.
    return await page.evaluate("""id => { const c = document.getElementById(id), g = c.getContext('2d');
      let d; try { d = g.getImageData(c.width / 2, c.height / 2, 40, 40).data; } catch (e) { return e.name === 'SecurityError' ? 999 : 0; }
      let s = 0, n = 0; for (let i = 0; i < d.length; i += 4) { s += d[i] + d[i + 1] + d[i + 2]; n++; } return s / n; }""", canvas)


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto((ROOT / 'preview/dash.html').as_uri())
        await page.wait_for_function('window.frogdashRendered > 2')
        await page.evaluate("frogdashDemo.scenario('reverse')")
        await page.wait_for_selector('#camera-dialog[open]')
        await page.wait_for_function("(() => { const s = document.querySelector('#camera-dialog .camera-stage').getBoundingClientRect(); return s.width > 1000; })()")
        await page.wait_for_timeout(800)
        found = await layout(page, '#camera-dialog')
        left, right, width, height = found['stage']
        assert found['info'][1] <= left + 1 and found['side'][0] >= right - 1, found      # Speed | picture | controls
        assert width > 1100 and abs((left + right) / 2 - 960) < 60, found                  # In the middle of the screen
        assert (found['fit'], found['position']) == ('cover', '50% 70%'), found            # Filled, true shape, ground kept
        assert await page.locator('#camera-dialog .camera-info #camera-speed').count() == 1
        assert await lit(page, 'camera-demo') > 30, 'the stock photo is drawn'
        await page.screenshot(path=str(ROOT / '.tmp/camera-fill.png'))
        await page.evaluate("frogdashDemo.scenario('drive')")
        await page.wait_for_function("!document.getElementById('camera-dialog').open", timeout=8000)

        await page.locator('#dashcam-launch').click()
        await page.wait_for_selector('#dashcam-dialog[open]')
        await page.locator('#dashcam-rear').click()
        await page.wait_for_timeout(900)
        found = await layout(page, '#dashcam-dialog')
        assert found['info'][1] <= found['stage'][0] + 1 and found['side'][0] >= found['stage'][1] - 1, found
        assert found['fit'] == 'cover', found
        assert await page.locator('#dashcam-speed').inner_text() not in ('', '—')            # Speed beside the picture
        assert await lit(page, 'dashcam-demo') > 30
        await page.screenshot(path=str(ROOT / '.tmp/dashcam-fill.png'))
        assert not errors, errors
        await browser.close()
    print('Camera views: speed | filled picture | controls, centred, true shape, ground kept; stock photos; dash cam speed; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
