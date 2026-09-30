"""Taillight studio: modes, shows, tests, parked gating, auto-clear and the recorded LED mirror.

python tests/browser_taillights.py [--browser /path/to/chromium]
"""
import argparse
import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright
from browser_layout import inspect

ROOT = Path(__file__).resolve().parents[1]
# Samples the top row of LEDs on each lamp from the canvas: '#' lit, '.' dark.
SAMPLE = '''async count => {
  const c = document.getElementById('tl-canvas'), ctx = c.getContext('2d'), out = [];
  const s = Math.min(c.width / 49, c.height / 24), oy = (c.height - 24 * s) / 2, ox = (c.width - 49 * s) / 2, y = oy + 2.5 * s;
  for (let i = 0; i < count; i++) {
    await new Promise(r => setTimeout(r, 50));
    let left = '', right = '';
    for (let x = 0; x < 21; x++) {
      const a = ctx.getImageData(ox + (x + .5) * s, y, 1, 1).data, b = ctx.getImageData(ox + (26 + x + .5) * s, y, 1, 1).data;
      left += a[0] > 90 ? '#' : '.'; right += b[0] > 90 ? '#' : '.';
    }
    out.push([left, right]);
  }
  return out;
}'''


async def main(executable):
    with socket.socket() as probe:  # The recordings need HTTP; file:// cannot fetch them.
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1', '--directory', str(ROOT / 'preview')],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=executable)
            page = await browser.new_page(viewport={'width': 1920, 'height': 720})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            await page.goto(f'http://127.0.0.1:{port}/index.html')
            await page.wait_for_function('window.frogdashRendered > 2')
            await page.evaluate("frogdashDemo.scenario('parked')")
            await page.locator('#controls-launch').click()
            await page.locator('#tab-lighting').click()
            await page.locator('#tl-launch').click()
            await page.wait_for_function("document.querySelector('#tl-shows [data-value=\"30\"]').textContent.includes('Radar')")
            await inspect(page, '#taillight-dialog')
            # Shows: all 33 selectable while parked; the mirror plays the recording.
            await page.locator('#tl-tab-shows').click()
            assert await page.locator('#tl-shows button').count() == 33
            await inspect(page, '#taillight-dialog')
            await page.locator('#tl-shows [data-value="5"]').click()
            await page.wait_for_function("document.getElementById('tl-left-state').textContent === 'SHOW'")
            assert 'Police' in await page.locator('#tl-mirror-note').text_content()
            await page.locator('[data-action="lighting.demo"]').click()
            await page.wait_for_function("document.getElementById('tl-mirror-note').textContent.startsWith('Demo')")
            await page.locator('.tl-normal').click()
            await page.wait_for_function("document.getElementById('tl-left-state').textContent === 'OFF'")
            # Per-side tests: the recorded sequential turn sweeps outward on each lamp.
            await page.locator('#tl-tab-tests').click()
            await inspect(page, '#taillight-dialog')
            for left, right, lamp in (('3', '1', 0), ('1', '3', 1)):
                await page.locator('#tl-left').select_option(left)
                await page.locator('#tl-right').select_option(right)
                await page.locator('[data-compute="override"]').click()
                await page.wait_for_function("document.getElementById('tl-left-state').textContent !== 'OFF'")
                await page.wait_for_timeout(300)
                rows = [row[lamp] for row in await page.evaluate(SAMPLE, 24)]
                lit = [r.count('#') for r in rows]
                assert max(lit) >= 12 and min(lit) == 0, rows  # Sweeps across the strip, then blanks.
                growing = [r for r in rows if 0 < r.count('#') < 21]
                inner = (lambda r: r[-1] == '#') if lamp == 0 else (lambda r: r[0] == '#')
                assert growing and all(inner(r) for r in growing), rows  # Starts at the car's centre.
            # One-shot text uses a computed value.
            await page.locator('#tl-text').fill('hi')
            await page.locator('[data-compute="text"]').click()
            await page.wait_for_function("document.getElementById('tl-left-state').textContent === 'CUSTOM'")
            # Driving: shows are refused and an active one is cleared automatically.
            await page.locator('#tl-tab-shows').click()
            await page.locator('#tl-shows [data-value="0"]').click()
            await page.wait_for_function("document.getElementById('tl-left-state').textContent === 'SHOW'")
            await page.evaluate("frogdashDemo.scenario('normal')")
            await page.wait_for_function("document.getElementById('tl-left-state').textContent !== 'SHOW'")
            await page.wait_for_function("document.querySelector('#tl-shows [data-value=\"3\"]').disabled")
            assert 'Park first' in await page.locator('#tl-gate').text_content()
            assert not await page.locator('.tl-normal').is_disabled()
            assert not await page.locator('#taillight-dialog [data-action="lighting.mode"]').first.is_disabled()
            for width, height in ((1280, 480), (1024, 768), (390, 844)):
                await page.set_viewport_size({'width': width, 'height': height})
                await inspect(page, '#taillight-dialog')
            assert not errors, errors
            await browser.close()
    finally:
        server.terminate()
    print('Taillight studio: 33 shows, demo, per-side tests, one-shots, parked gating, auto-clear and outward recorded sweeps passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
