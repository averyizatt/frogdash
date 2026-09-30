"""Exercise real Web Audio scheduling; physical HDMI audibility is a Pi acceptance check."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]
TRACE = """(() => {
  window.testSockets = [];
  window.WebSocket = class extends WebSocket {
    constructor(...args) { super(...args); testSockets.push(this); }
  };
  window.tones = [];
  const start = OscillatorNode.prototype.start;
  OscillatorNode.prototype.start = function(when) {
    // A beep may layer several oscillators starting together; count beeps, not oscillators.
    if (!tones.some(t => t.when === when)) tones.push({when, at: performance.now(), activated: navigator.userActivation.hasBeenActive});
    return start.call(this, when);
  };
  window.peaks = [];
  const ramp = AudioParam.prototype.exponentialRampToValueAtTime;
  AudioParam.prototype.exponentialRampToValueAtTime = function(value, when) {
    if (value > .0001) peaks.push(value); return ramp.call(this, value, when);
  };
})();"""


async def count(page, n):
    await page.wait_for_function('(n) => tones.length === n', arg=n)


async def close_context(context, page):
    # Close the streaming connection cleanly before terminating Chromium's pipes.
    await page.evaluate("""async () => {
      await Promise.all((window.testSockets || []).map(ws => new Promise(resolve => {
        if (ws.readyState === WebSocket.CLOSED) return resolve();
        ws.addEventListener('close', resolve, {once: true}); ws.close();
      })));
    }""")
    await context.close()


async def volume(page, n):
    await page.locator('#alert-volume').fill(str(n))
    assert await page.locator('#alert-volume-value').inner_text() == f'{n}%'


async def check(browser, url, state):
    context = await browser.new_context(viewport={'width': 1920, 'height': 720})
    await context.add_init_script(TRACE)
    page = await context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    oil = state.driving.alerts['oil']
    def incident():
        oil.update(active=True, latched=True, acknowledged=False, condition='active')
        state.driving.alert_seq += 1
    try:
        # Saved chimes plus a current incident must work before any touch/click.
        state.driving.settings['chime'] = True
        incident()
        await page.goto(url)
        # Playwright evaluate can itself grant activation; poll via CDP without it.
        cdp = await context.new_cdp_session(page)
        for _ in range(50):
            result = await cdp.send('Runtime.evaluate', {'expression': 'window.tones?.length === 2', 'userGesture': False})
            if result['result'].get('value') is True:
                break
            await page.wait_for_timeout(100)
        else:
            raise AssertionError('No startup chime without user activation')
        await cdp.detach()
        assert await page.evaluate('tones.every(t => !t.activated)')
        await page.wait_for_timeout(3300)
        assert await page.evaluate('tones.length') == 2, 'Repeated snapshots must not repeat a chime'
        await page.locator('#alerts-launch').click()
        await volume(page, 25)
        await page.locator('#test-chime').click()
        await count(page, 4)
        assert abs(await page.evaluate('peaks.at(-1)') - .9 * .25) < .00001  # 100% = 0.9 of full scale
        # A second incident inside the throttle window is queued, then cancelled on recovery.
        incident()
        await page.wait_for_timeout(200)
        oil.update(active=False, condition='normal')
        await page.wait_for_timeout(3100)
        assert await page.evaluate('tones.length') == 4
        # Historical latched incidents do not sound on reload; volume survives.
        await page.reload()
        await page.wait_for_function('document.getElementById("audio-status").textContent.includes("Browser audio ready")')
        await page.wait_for_timeout(300)
        assert await page.evaluate('tones.length') == 0
        await page.locator('#alerts-launch').click()
        assert await page.locator('#alert-volume').input_value() == '25'
        await volume(page, 0)
        incident()
        await page.locator('#test-chime').click()
        await page.wait_for_timeout(350)
        assert await page.evaluate('tones.length') == 0
        assert 'muted' in await page.locator('#audio-status').inner_text()
        await volume(page, 50)
        await page.wait_for_timeout(200)
        assert await page.evaluate('tones.length') == 0, 'Unmuting must not replay a muted incident'
        incident()
        await count(page, 2)
        incident()
        await page.wait_for_timeout(200)
        assert await page.evaluate('tones.length') == 2
        await count(page, 4)
        times = await page.evaluate('tones.map(t => t.at)')
        assert times[2] - times[0] >= 2990
        # Turning off chimes leaves the warning visible.
        await page.locator('#alert-chime').uncheck()
        await page.locator('#alert-settings button[type=submit]').click()
        await page.wait_for_function('document.getElementById("alert-settings-status").textContent.includes("saved")')
        incident()
        await page.wait_for_timeout(350)
        assert await page.evaluate('tones.length') == 4
        assert 'LOW OIL PRESSURE' in await page.locator('#driver-alerts').inner_text()
        await page.screenshot(path=str(ROOT / '.tmp/audio-alerts-1920x720.png'))
        assert not errors, errors
    finally:
        await close_context(context, page)

    # Simulate an audio device/API failure while keeping normal service/UI behavior.
    state.driving.settings['chime'] = True
    context = await browser.new_context()
    await context.add_init_script(TRACE + 'window.AudioContext = window.webkitAudioContext = undefined;')
    page = await context.new_page()
    try:
        await page.goto(url)
        await page.locator('#alerts-launch').click()
        assert 'Audio unavailable' in await page.locator('#audio-status').inner_text()
        assert 'LOW OIL PRESSURE' in await page.locator('#driver-alerts').inner_text()
        await page.locator('#alert-settings button[type=submit]').click()
        await page.wait_for_function('document.getElementById("alert-settings-status").textContent.includes("saved")')
        assert await page.locator('#alert-settings button[type=submit]').is_enabled()
    finally:
        await close_context(context, page)

    # A browser policy can leave resume() pending forever; settings must still save.
    context = await browser.new_context()
    await context.add_init_script(TRACE + """
      window.blockAudio = true;
      window.AudioContext = class extends AudioContext {
        get state() { return blockAudio ? 'suspended' : super.state; }
        resume() { return blockAudio ? new Promise(() => {}) : super.resume(); }
      };
    """)
    page = await context.new_page()
    try:
        await page.goto(url)
        await page.locator('#alerts-launch').click()
        assert 'needs activation' in await page.locator('#audio-status').inner_text()
        await page.locator('#alert-settings button[type=submit]').click()
        await page.wait_for_function('document.getElementById("alert-settings-status").textContent.includes("saved")')
        assert await page.locator('#alert-settings button[type=submit]').is_enabled()
        assert await page.evaluate('tones.length') == 0
        oil.update(active=False, condition='normal')
        await page.wait_for_timeout(200)
        await page.evaluate('window.blockAudio = false')
        await page.locator('#test-chime').click()
        await count(page, 2)
        assert 'Browser audio ready' in await page.locator('#audio-status').inner_text()
    finally:
        await close_context(context, page)


async def main(path):
    (ROOT / '.tmp').mkdir(exist_ok=True)
    state = State(clock=lambda: 0)
    state.connected = True
    state.samples['ecu.rpm', 1520] = dict(value=0, quality='live', source_id=1520, timestamp_ms=0, seen=0)
    app = create_app(state)
    # Control incident timing deterministically; this test covers browser delivery,
    # with debounce/telemetry freshness separately exercised in test_driving.py.
    app.cleanup_ctx.clear()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=path, headless=True,
                args=['--autoplay-policy=no-user-gesture-required'])
            try:
                await check(browser, f'http://127.0.0.1:{port}', state)
            finally:
                await browser.close()
    finally:
        await runner.cleanup()
    print('Audio startup without touch, incident throttling/recovery, saved volume, mute, test tone, disabled alerts and unavailable/blocked audio passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
