"""The knock page: spectrum, frequency, amplifier and second resonance shown live, and every setting changeable."""
import argparse
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State
from hardware.frogdash.gps import GPS
ROOT = Path(__file__).resolve().parents[1]


async def text(page, selector):
    return (await page.locator(selector).inner_text()).strip()


async def wait_text(page, element, fragment, timeout=8000):
    await page.wait_for_function('([id, part]) => document.getElementById(id).textContent.includes(part)', arg=[element, fragment], timeout=timeout)


async def set_number(page, selector, value):
    field = page.locator(selector)
    await field.fill(str(value))
    await field.blur()


async def fits(page, body):
    """Nothing in the view is cut off or pushed outside the dialog."""
    return await page.evaluate("""body => {
      const view = document.querySelector(body), dialog = document.getElementById('knock-overlay').getBoundingClientRect();
      const outside = [...view.querySelectorAll('.kval, .knock-graph, .knock-card, input, select, button')].filter(node => {
        const r = node.getBoundingClientRect();
        return r.width && (r.left < dialog.left - 1 || r.right > dialog.right + 1);
      });
      return {scrolls: view.scrollHeight > view.clientHeight + 1, outside: outside.length, wide: view.scrollWidth > view.clientWidth + 1};
    }""", body)


async def page_at(browser, width, height):
    page = await browser.new_page(viewport={'width': width, 'height': height})
    errors, network = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: network.append(request.url) if request.url.startswith(('http:', 'https:')) else None)
    await page.add_init_script("window.states=0; addEventListener('frogdash-state',()=>states++)")
    await page.goto((ROOT / 'preview/index.html').as_uri())
    await page.wait_for_function('states > 3')
    return page, errors, network


async def live_view(page, wide):
    await page.locator('#knock-launch').click()
    await page.wait_for_function("document.getElementById('knock-spectrum-normal').getAttribute('d').startsWith('M')")
    assert await page.locator('#knock-view-live').is_visible() and await page.locator('#knock-view-settings').is_hidden()
    # The spectrum: both curves, the listening band, the second-resonance band and the marks.
    drawn = await page.evaluate("""() => ({
      normal: document.getElementById('knock-spectrum-normal').getAttribute('d').split('L').length,
      burst: document.getElementById('knock-spectrum-burst').getAttribute('d').split('L').length,
      band: +document.getElementById('knock-band').getAttribute('width'), bandAt: +document.getElementById('knock-band').getAttribute('x'),
      second: +document.getElementById('knock-band-second').getAttribute('width'),
      marks: [...document.querySelectorAll('#knock-marks text')].map(t => t.textContent),
      axis: [...document.querySelectorAll('#knock-spectrum-axis text')].map(t => t.textContent)})""")
    assert drawn['normal'] >= 36 and drawn['burst'] == 36, drawn
    assert drawn['band'] > 20 and drawn['second'] > 20, drawn
    # 6.25 kHz of a 2 to 12.5 kHz axis, 1500 Hz wide: the band starts at about 5.5 kHz.
    assert abs(drawn['bandAt'] - (48 + (5500 - 2000) / 10500 * 888)) < 3, drawn
    assert drawn['marks'] == ['BORE', 'ENGINE'], drawn
    assert 'dB' in drawn['axis'] and '6 kHz' in drawn['axis'] and '12 kHz' in drawn['axis'], drawn
    assert await page.locator('#knock-spectrum-missing').is_hidden()
    # The numbers.
    assert await text(page, '#knock-freq') == '6.25 kHz'
    assert await text(page, '#knock-freq-note') == 'LEARNED · BORE 5.97'
    assert (await text(page, '#knock-amp')).endswith('×')
    assert 'AUTOMATIC · POSITION' in await text(page, '#knock-amp-note') and 'OF 30' in await text(page, '#knock-amp-note')
    assert 'normal 9' in await text(page, '#knock-second')
    assert await text(page, '#knock-found') == '6.26 kHz · 84% of 120 agree'
    assert await text(page, '#knock-tone') == 'None'
    assert await text(page, '#knock-rest') == '0.82 V'
    assert 'mV' in await text(page, '#knock-swing') and '% of room' in await text(page, '#knock-swing')
    assert await text(page, '#knock-rate') == '38,460'
    assert 'ESP32 CONTROLLER' in await text(page, '#knock-source') and 'LISTENING AT 6.3 kHz' in await text(page, '#knock-source')
    assert await text(page, '#knock-status') == 'OK'
    layout = await fits(page, '#knock-view-live')
    assert not layout['outside'] and not layout['wide'], layout
    if wide:
        assert not layout['scrolls'], 'On the dash the whole live view fits without scrolling'
        # The two graphs sit side by side at the same height.
        boxes = [await page.locator(selector).bounding_box() for selector in ('#knock-graph', '#knock-spectrum')]
        assert abs(boxes[0]['y'] - boxes[1]['y']) < 2 and boxes[1]['x'] > boxes[0]['x'] + boxes[0]['width'] * .8, boxes
        assert boxes[1]['height'] > page.viewport_size['height'] * .28, boxes
    # A knock: the page says so in every place.
    await page.evaluate("frogdashDemo.scenario('warning')")
    await page.wait_for_function("document.getElementById('knock-status').textContent === 'WARNING'")
    await wait_text(page, 'knock-second', 'RINGING')
    await wait_text(page, 'knock-crest', 'NOTABLE')
    await page.evaluate("frogdashDemo.scenario('drive')")
    await page.wait_for_function("document.getElementById('knock-status').textContent === 'OK'")


async def settings_view(page):
    await page.locator('#knock-view-settings-tab').click()
    assert await page.locator('#knock-view-settings').is_visible() and await page.locator('#knock-view-live').is_hidden()
    await page.wait_for_function("document.getElementById('knock-set-multiplier').value === '2'")
    shown = {name: await page.locator(f'#knock-set-{name}').input_value() for name in
             ('multiplier', 'offset', 'hold', 'level-gain', 'min-rpm', 'min-map', 'center', 'bore', 'freq-mode', 'bandwidth', 'amp-mode')}
    assert shown == {'multiplier': '2', 'offset': '20', 'hold': '0.3', 'level-gain': '1', 'min-rpm': '0', 'min-map': '100', 'center': '6.25',
                     'bore': '96', 'freq-mode': 'auto', 'bandwidth': '15', 'amp-mode': 'auto'}, shown
    assert await page.locator('#knock-set-center').is_disabled()       # Found from the engine: nothing to type.
    assert await page.locator('#knock-set-amp-step').is_disabled()     # The controller is setting the gain.
    assert not (await fits(page, '#knock-view-settings'))['outside']

    # A setting goes to the controller, and the field then shows the controller's value.
    await set_number(page, '#knock-set-multiplier', 2.6)
    await page.wait_for_function("document.getElementById('knock-result').dataset.status === 'simulated'")
    await page.wait_for_function("document.getElementById('knock-set-multiplier').value === '2.6'")
    await set_number(page, '#knock-set-multiplier', 9)                 # Beyond what the controller takes: limited.
    await page.wait_for_function("document.getElementById('knock-set-multiplier').value === '3.8'")
    for field, value, shown_as in (('offset', 12, '12'), ('hold', 0.5, '0.5'), ('min-rpm', 2500, '2500'), ('min-map', 110, '110'), ('level-gain', 1.5, '1.5')):
        await page.wait_for_timeout(120)
        await set_number(page, f'#knock-set-{field}', value)
        await page.wait_for_function(f"document.getElementById('knock-set-{field}').value === '{shown_as}'")
    await page.locator('#knock-set-bandwidth').select_option('9')
    await page.wait_for_function("document.getElementById('knock-set-bandwidth').value === '9'")
    await page.locator('#knock-set-off').click()
    await page.wait_for_function("document.getElementById('knock-set-off').classList.contains('active')")
    await page.locator('#knock-set-on').click()
    await page.wait_for_function("document.getElementById('knock-set-on').classList.contains('active')")

    # The knock frequency: found from the engine, or set by hand.
    await wait_text(page, 'knock-set-freq-note', 'learned from the engine')
    assert 'The bore suggests 5.97 kHz' in await text(page, '#knock-set-freq-note')
    await page.locator('#knock-set-freq-mode').select_option('manual')
    await wait_text(page, 'knock-set-freq-note', 'set by hand')
    assert await page.locator('#knock-set-center').is_enabled() and await page.locator('#knock-set-relearn').is_disabled()
    await set_number(page, '#knock-set-center', 6.6)
    await wait_text(page, 'knock-source', 'LISTENING AT 6.6 kHz')
    await page.locator('#knock-set-freq-mode').select_option('auto')
    await wait_text(page, 'knock-set-freq-note', 'learned from the engine')
    assert await page.locator('#knock-set-center').is_disabled()
    await page.locator('#knock-set-relearn').click()
    await wait_text(page, 'knock-set-freq-note', "the bore's figure until the engine has been heard")
    await wait_text(page, 'knock-set-freq-note', 'learned from the engine')     # A few seconds of simulated running later.
    await set_number(page, '#knock-set-bore', 86)
    await wait_text(page, 'knock-set-freq-note', 'The bore suggests 6.66 kHz')

    # The amplifier: left to the controller, or held where the driver puts it.
    await wait_text(page, 'knock-set-amp-note', 'set by the controller')
    await page.locator('#knock-set-amp-mode').select_option('hold')
    await wait_text(page, 'knock-set-amp-note', 'held here')
    assert await page.locator('#knock-set-amp-step').is_enabled()
    await page.locator('#knock-set-amp-step').evaluate("slider => { slider.value = 5; slider.dispatchEvent(new Event('change', {bubbles: true})); }")
    await wait_text(page, 'knock-set-amp-note', 'position 5 of 30, held here')
    await page.locator('#knock-view-live-tab').click()
    await wait_text(page, 'knock-amp-note', 'HELD · POSITION 5 OF 30')
    assert await text(page, '#knock-amp') == '2.7×'
    await page.locator('#knock-view-settings-tab').click()
    await page.locator('#knock-set-amp-mode').select_option('auto')
    await wait_text(page, 'knock-set-amp-note', 'set by the controller')


async def nano_controller(page):
    """The controller in the car today reports no spectrum, frequency or gain: the page says so and keeps working."""
    await page.evaluate("frogdashDemo.knockController('nano')")
    await wait_text(page, 'knock-set-amp-note', 'needs the ESP32 controller')
    for control in ('amp-mode', 'amp-step', 'bore', 'relearn'):
        assert await page.locator(f'#knock-set-{control}').is_disabled(), control
    assert await page.locator('#knock-set-multiplier').is_enabled() and await page.locator('#knock-set-freq-mode').is_enabled()
    assert await page.locator('#knock-set-freq-mode option').first.inner_text() == 'From the bore'
    await page.locator('#knock-view-live-tab').click()
    await page.wait_for_function("!document.getElementById('knock-spectrum-missing').hidden")
    assert 'ESP32' in await text(page, '#knock-spectrum-missing')
    assert await text(page, '#knock-amp') == '—' and await text(page, '#knock-amp-note') == 'FIXED BY THE CIRCUIT'
    assert await text(page, '#knock-second') == '—' and await text(page, '#knock-found') == '—'
    assert await text(page, '#knock-freq-note') == 'FROM THE BORE'
    assert '% of range' in await text(page, '#knock-swing') and await text(page, '#knock-rest') == '2.5 V'
    assert await text(page, '#knock-energy-num') != '—' and await text(page, '#knock-status') == 'OK'   # The level graph is the Nano's too.
    assert await page.locator('#knock-spectrum-normal').get_attribute('d') == ''
    await page.evaluate("frogdashDemo.knockController('esp32')")
    await page.wait_for_function("document.getElementById('knock-spectrum-normal').getAttribute('d').startsWith('M')")


def controller_frames(fixed_step=None):
    """What the ESP32 controller sends: knock status and settings, and the six kinds of 0x30E."""
    step = 12 if fixed_step is None else fixed_step
    gain = round((1 + 10 * step / 30) * 10)
    spectrum = [round((24 - point * .3 + (9 if point in (14, 15) else 0) + 10) * 3) for point in range(36)]
    burst = [value + (36 if point in (14, 15) else 6) for point, value in enumerate(spectrum)]
    frames = [(0x5E8, bytes.fromhex('07080D7A080201F4')),
              (0x307, bytes.fromhex('13140FB403225500')),
              (0x30C, bytes([3, 20, 20, 0, 120, 30, 10, 63])),             # Listening on, frequency found from the engine
              (0x30D, bytes([15, 192, 64, 2, 5, 20, 96, 0])),
              (0x30E, bytes([1, 16 if fixed_step is not None else 1, gain, step, 30, 51, 20, 50])),
              (0x30E, bytes([2, 7]) + (6300).to_bytes(2, 'big') + (6320).to_bytes(2, 'big') + bytes([78, 64])),
              (0x30E, bytes([3]) + (5968).to_bytes(2, 'big') + (0).to_bytes(2, 'big') + (38460).to_bytes(2, 'big') + b'\x00'),
              (0x30E, bytes([4, 0, 11, 9, 14, 13, 0, 0]))]
    for kind, points in ((5, spectrum), (6, burst)):
        frames += [(0x30E, bytes([kind, first] + points[first:first + 6])) for first in range(0, 36, 6)]
    return frames


async def went_out(sent, data):
    for _ in range(60):
        if sent and sent[-1] == (0x301, data):
            return
        await asyncio.sleep(.1)
    raise AssertionError(f'{data.hex()} was not sent: {sent[-3:]}')


async def real_backend(browser):
    """The same page fed by CAN frames through the dash's own server, and its commands going out on the bus."""
    state = State()
    state.connected, state.status = True, 'test CAN'
    app = create_app(state)
    app.cleanup_ctx.clear()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    sent, held = [], {'step': None, 'esp32': True, 'moving': False}
    state.gps = GPS(transmit=False)

    async def sender(identifier, data):
        sent.append((identifier, bytes(data)))
        if identifier == 0x301:
            if data[0] == 0x4B:
                held['step'] = data[1] - 1 if data[1] else None
            state.ingest(0x30A, bytes([data[0], 0, data[1] if len(data) > 1 else 0, 2]))
    state.controls.attach(sender)
    state.controls.ready_at = 0

    async def feed():
        while True:
            for identifier, data in controller_frames(held['step']):
                if identifier != 0x30E or held['esp32']:
                    state.ingest(identifier, data)
            state.gps.connected = True
            state.gps.update({'class': 'TPV', 'mode': 3, 'speed': 14 if held['moving'] else 0})
            await asyncio.sleep(.05)

    task = asyncio.create_task(feed())
    try:
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(f'http://127.0.0.1:{port}')
        await page.wait_for_function("document.getElementById('rpm-value').textContent === '3450'")
        await page.locator('#knock-launch').click()
        await page.wait_for_function("document.getElementById('knock-spectrum-burst').getAttribute('d').startsWith('M')")
        assert await text(page, '#knock-freq') == '6.30 kHz' and await text(page, '#knock-freq-note') == 'LEARNED · BORE 5.97'
        assert await text(page, '#knock-amp') == '5.0×' and await text(page, '#knock-amp-note') == 'AUTOMATIC · POSITION 12 OF 30'
        assert await text(page, '#knock-found') == '6.32 kHz · 78% of 64 agree'
        assert await text(page, '#knock-second') == '11 · normal 9' and await text(page, '#knock-crest') == '1.3×'
        assert await text(page, '#knock-swing') == '160 mV · 20% of room' and await text(page, '#knock-rest') == '0.82 V'
        assert await text(page, '#knock-tone') == 'None' and await text(page, '#knock-rate') == '38,460'
        assert 'KNOCK SENSOR · LIVE · LISTENING AT 6.3 kHz · ESP32 CONTROLLER' == await text(page, '#knock-source')
        # The spectrum arrives in six frames of six points: the hump at 6.2 to 6.5 kHz is in both curves.
        peak = await page.evaluate("""() => ['knock-spectrum-normal', 'knock-spectrum-burst'].map(id => {
          const points = document.getElementById(id).getAttribute('d').split(' ').slice(0, 36).map(p => p.slice(1).split(',').map(Number));
          return points.reduce((best, p, i) => p[1] < points[best][1] ? i : best, 0);
        })""")
        assert peak == [14, 14], peak
        assert await page.locator('#knock-marks text').all_text_contents() == ['BORE', 'ENGINE']

        # Settings go out as water/meth commands, and the page follows the controller.
        await page.locator('#knock-view-settings-tab').click()
        await page.wait_for_function("document.getElementById('knock-set-bore').value === '96'")
        await page.locator('#knock-set-amp-mode').select_option('hold')
        await wait_text(page, 'knock-set-amp-note', 'position 12 of 30, held here')
        assert sent[-1] == (0x301, bytes([0x4B, 13])), sent[-1]            # Position 12, sent as 13: 0 means automatic.
        # Straight back again: the dash refuses the same command twice in a row this fast, so
        # the page holds the change until it can go, and the choice stays as the driver left it.
        await page.locator('#knock-set-amp-mode').select_option('auto')
        await page.wait_for_timeout(500)
        assert await page.locator('#knock-set-amp-mode').input_value() == 'auto' and sent[-1] == (0x301, bytes([0x4B, 13]))
        await wait_text(page, 'knock-set-amp-note', 'set by the controller')
        assert sent[-1] == (0x301, bytes([0x4B, 0])), sent[-1]
        assert 'REJECTED' not in await text(page, '#knock-result')
        await set_number(page, '#knock-set-bore', 92)
        await went_out(sent, bytes([0x4C, 92]))
        await page.locator('#knock-set-relearn').click()
        await went_out(sent, bytes([0x4D]))
        assert [data for _, data in sent] == [bytes([0x4B, 13]), bytes([0x4B, 0]), bytes([0x4C, 92]), bytes([0x4D])], sent

        # The ESP32 reports stop (the Nano board is fitted): within a few seconds the page says so.
        held['esp32'] = False
        await wait_text(page, 'knock-set-amp-note', 'needs the ESP32 controller', timeout=12000)
        assert await page.locator('#knock-set-relearn').is_disabled() and await page.locator('#knock-set-multiplier').is_enabled()
        assert await page.locator('#knock-set-blocked').is_hidden()

        # Moving: the dash refuses calibration changes, and the page says why instead of only greying out.
        held['moving'] = True
        await wait_text(page, 'knock-set-blocked', 'Stop the car first')
        assert await page.locator('#knock-set-blocked').is_visible()
        for control in ('multiplier', 'offset', 'min-map', 'freq-mode', 'bandwidth'):
            assert await page.locator(f'#knock-set-{control}').is_disabled(), control
        assert await page.locator('#knock-set-off').is_enabled()           # Switching it off is always possible.
        await page.locator('#knock-view-live-tab').click()
        assert await text(page, '#knock-status') == 'OK'                   # And the live view carries on.
        held['moving'] = False
        await page.locator('#knock-view-settings-tab').click()
        await page.wait_for_function("document.getElementById('knock-set-blocked').hidden")
        assert await page.locator('#knock-set-multiplier').is_enabled()
        assert not errors, errors
        await page.close()
    finally:
        await state.controls.close()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runner.cleanup()


async def main(browser_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=browser_path) if browser_path else await p.chromium.launch()
        try:
            await real_backend(browser)
            (ROOT / '.tmp').mkdir(exist_ok=True)
            for width, height in ((1920, 720), (1280, 480), (390, 844)):
                page, errors, network = await page_at(browser, width, height)
                await live_view(page, wide=width >= 1280)
                if width == 1920:
                    await page.screenshot(path=str(ROOT / '.tmp/knock-live.png'))
                await settings_view(page)
                if width == 1920:
                    await page.screenshot(path=str(ROOT / '.tmp/knock-settings.png'))
                await nano_controller(page)
                await page.keyboard.press('Escape')
                assert not await page.locator('#knock-overlay').evaluate('dialog => dialog.open')
                # From the controls page, straight to the settings.
                await page.locator('#controls-launch').click()
                await page.locator('#tab-knock').click()
                await page.locator('#knock-open-settings').click()
                assert await page.locator('#knock-view-settings').is_visible()
                assert not await page.locator('#controls-dialog').evaluate('dialog => dialog.open')
                assert not errors, errors
                assert not network, network
                await page.close()
        finally:
            await browser.close()
    print('Knock page: spectrum, frequency, amplifier and second resonance live from CAN frames and in the preview; every setting changes; the Nano controller falls back cleanly; passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
