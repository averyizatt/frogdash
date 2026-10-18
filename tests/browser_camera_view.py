"""Camera picture modes (camera-view.js) on the preview's rear camera: Wide by default and
filling the space beside the controls with a drawn picture; Fill; Whole back to the
original 4:3 box; the choice remembered; the stretch curve's figures."""
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
        await page.goto((ROOT / 'preview/index.html').as_uri())
        await page.wait_for_function('window.frogdashRendered > 2')
        # The stretch: a 4:3 picture into a 2.1:1 stage keeps 82% of the height, cut mostly at
        # the top, and the curve's centre slope is what is left to widen (1.29, under 1.45).
        plan = await page.evaluate("FrogdashCameraView.plan('wide', 2.1, 4 / 3)")
        assert abs(plan['a'] - 1.2915) < .01 and abs(plan['w'][0] - .117) < .001 and abs(plan['w'][1] - .82) < 1e-6, plan
        assert await page.evaluate("FrogdashCameraView.plan('fill', 2.1, 4 / 3).a") == 1
        await page.evaluate("frogdashDemo.scenario('reverse')")   # The preview's rear camera, in reverse
        dialog = page.locator('#camera-dialog')
        await dialog.wait_for(state='visible')
        stage = page.locator('#camera-dialog .camera-stage')
        assert await stage.get_attribute('data-view') == 'wide'
        await page.wait_for_function("!document.querySelector('#camera-dialog canvas.camera-view').hidden")
        await page.wait_for_timeout(400)
        wide = await stage.bounding_box()
        assert wide['width'] > 1300, wide                      # Beside the controls, not a 960-wide 4:3 box
        lit = await page.evaluate("""(() => { const c = document.querySelector('#camera-dialog canvas.camera-view');
            const g = c.getContext('webgl'); const px = new Uint8Array(4);
            g.readPixels(c.width >> 1, c.height >> 1, 1, 1, g.RGBA, g.UNSIGNED_BYTE, px); return px[0] + px[1] + px[2]; })()""")
        assert lit > 0, 'the picture is drawn'
        await page.screenshot(path=str(ROOT / '.tmp/camera-wide.png'))
        await page.locator('#camera-dialog .camera-view-modes button[data-view="whole"]').click()
        await page.wait_for_timeout(200)
        whole = await stage.bounding_box()
        assert abs(whole['width'] / whole['height'] - 4 / 3) < .02, whole
        assert await page.locator('#camera-dialog canvas.camera-view').is_hidden()
        await page.locator('#camera-dialog .camera-view-modes button[data-view="fill"]').click()
        assert await page.evaluate("JSON.parse(localStorage.getItem('frogdash.cameraview.v1')).camera") == 'fill'
        assert not errors, errors
        await browser.close()
    print('Camera picture: Wide by default filling the space, drawn; Fill; Whole back to 4:3; remembered; stretch figures; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
