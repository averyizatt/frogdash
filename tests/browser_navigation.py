"""Real CAN edges -> WebSocket -> wheel focus; keyboard preview and edit controls."""
import argparse
import asyncio
from contextlib import suppress
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

ROOT = Path(__file__).resolve().parents[1]


async def check(browser, url, state):
    page = await browser.new_page(viewport={'width': 1920, 'height': 720})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    await page.add_init_script("window.testSockets=[]; window.WebSocket=class extends WebSocket {constructor(...a){super(...a);testSockets.push(this)}}")
    mask = 0
    async def publisher():
        seq = 0
        while True:
            state.ingest(0x205, bytes([mask, seq, 1]))
            seq = (seq + 1) & 255
            await asyncio.sleep(.025)
    task = asyncio.create_task(publisher())
    async def press(value, duration=.09):
        nonlocal mask
        mask = value
        await asyncio.sleep(duration)
        mask = 0
        await asyncio.sleep(.2)
    async def focused(identifier):
        await page.wait_for_function('(id) => document.activeElement.id === id', arg=identifier)
    try:
        await page.goto(url)
        await page.wait_for_timeout(300)
        # Any button on the plain dashboard opens the quick menu; entries deep-link into a section.
        await press(16)
        await page.wait_for_function('document.getElementById("wheel-menu").open')
        for _ in range(3):
            await press(2)                 # Map -> Interior lights -> Taillights -> Water / meth
        await press(16)
        await page.wait_for_function('document.getElementById("controls-dialog").open && !document.getElementById("wheel-menu").open')
        await focused('meth-test-duty')  # Landed inside the section.
        await press(16, .9)                # Back steps out to the section list first.
        await focused('tab-meth')
        await press(2)
        await focused('tab-tune')
        assert await page.locator('#panel-tune').is_visible()
        await press(1); await press(1)     # Up wraps within the section list, never into the panel.
        assert await page.evaluate('document.activeElement.getAttribute("role")') == 'tab'
        await press(16, .9)                # Back at the section list closes the menu.
        await page.wait_for_function('!document.getElementById("controls-dialog").open')
        # Old event history is never replayed after a reload.
        await page.reload()
        await page.wait_for_timeout(300)
        assert not await page.locator('#controls-dialog').evaluate('(el) => el.open')
        # Edit mode prevents arrows on an unfocused input from changing values.
        await page.locator('#controls-launch').click()
        await page.keyboard.press('Enter')   # First press after touch only shows the highlight.
        await focused('tab-meth')
        await page.locator('#meth-test-duty').focus()
        await page.keyboard.press('Enter')
        assert await page.locator('#meth-test-duty').evaluate('(el) => el.classList.contains("wheel-editing")')
        before = int(await page.locator('#meth-test-duty').input_value())
        await page.keyboard.press('ArrowRight')
        assert int(await page.locator('#meth-test-duty').input_value()) == before + 1
        await page.keyboard.press('Enter')
        await page.keyboard.press('Escape')  # Section -> section list.
        await focused('tab-meth')
        await page.keyboard.press('Escape')  # Section list -> closed.
        assert not await page.locator('#controls-dialog').evaluate('(el) => el.open')
        # Unavailable controller commands remain disabled and cannot be selected.
        await page.locator('#controls-launch').click()
        await press(16)
        await press(8)  # Into meth panel: first enabled input, skipping commands.
        await focused('meth-test-duty')
        assert await page.locator('[data-action="meth.test"]').is_disabled()
        # Lost CAN stops repeats; button state must return to neutral before resuming.
        mask = 2
        await asyncio.sleep(.12)
        task.cancel()
        with suppress(asyncio.CancelledError): await task
        await page.wait_for_timeout(500)
        current = await page.evaluate('document.activeElement.id')
        await page.wait_for_timeout(350)
        assert current == await page.evaluate('document.activeElement.id')
        assert not errors, errors
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError): await task
        await page.evaluate('''async () => { await Promise.all(testSockets.map(ws => new Promise(resolve => {
          if (ws.readyState === WebSocket.CLOSED) return resolve();
          ws.addEventListener('close', resolve, {once:true}); ws.close();
        }))); }''')
        await page.close()


async def preview(browser):
    page = await browser.new_page(viewport={'width': 1280, 'height': 480})
    try:
        await page.goto((ROOT / 'preview/index.html').as_uri())
        await page.keyboard.press('Enter')
        assert await page.locator('#wheel-menu').evaluate('(el) => el.open')
        await page.keyboard.press('Escape')
        assert not await page.locator('#wheel-menu').evaluate('(el) => el.open')
        await page.locator('#controls-launch').click()
        await page.keyboard.press('Enter')
        await page.keyboard.press('ArrowDown')
        assert await page.locator('#panel-tune').is_visible()
        await page.keyboard.down('Enter')
        await page.wait_for_timeout(900)
        await page.keyboard.up('Enter')
        assert not await page.locator('#controls-dialog').evaluate('(el) => el.open')
        # Gallery tabs and selects work through the same navigation layer.
        await page.locator('#appearance-launch').click()
        await page.locator('#appearance-tab-gallery').focus()
        await page.keyboard.press('ArrowDown')   # Sections are chosen with up/down in every menu.
        assert await page.locator('#appearance-custom').is_visible()
        await page.keyboard.press('ArrowRight')  # Right opens the section.
        assert await page.evaluate('document.getElementById("appearance-custom").contains(document.activeElement)')
        await page.keyboard.press('Escape'); await page.keyboard.press('Escape')
        assert not await page.locator('#appearance-dialog').evaluate('(el) => el.open')
    finally:
        await page.close()


async def main(path):
    state = State()
    state.connected = True
    app = create_app(state)
    app.cleanup_ctx.clear()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=path)
            try:
                await check(browser, f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}', state)
                await preview(browser)
            finally:
                await browser.close()
    finally:
        await runner.cleanup()
    print('CAN wheel navigation: quick menu, two-level sections, long-back, reconnect, stale input, edit mode, disabled controls and preview keyboard passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
