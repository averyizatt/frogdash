"""Gateway firmware from the dash: the Support tab's line and button, through a whole install."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from playwright.async_api import async_playwright
from hardware.frogdash import fwupdate as fw
from hardware.frogdash.state import State
from hardware.frogdash.server import create_app

ROOT = Path(__file__).resolve().parents[1]
OLD, NEW = '0a0b0c0d', '1a2b3c4d'


class Gateway:
    """A well-behaved module, in Python: accepts every block, restarts into the new build on trial."""
    def __init__(self, firmware):
        self.firmware, self.build, self.trial, self.blocks, self.commands = firmware, OLD, False, 0, []

    def reply(self, payload):
        self.firmware.observe(bytes(payload))

    async def sender(self, identifier, data):
        assert identifier == fw.ID_COMMAND and len(data) == 8
        op = data[0]
        if not op & 0x80:
            return
        self.commands.append(op)
        if op == fw.QUERY:
            self.reply(bytes([fw.INFO, 1]) + bytes.fromhex(self.build) + bytes([fw.ON_TRIAL if self.trial else 0, 1]))
        elif op == fw.BLOCK_END:
            self.blocks += 1
            await asyncio.sleep(.1)    # Slow enough for the screen to show progress, however busy the computer.
            self.reply(bytes([fw.ACK, 1, op, fw.OK]) + data[2:4] + b'\x00\x00')
        elif op == fw.END:
            self.reply(bytes([fw.ACK, 1, op, fw.OK, 0, 0, 0, 0]))
            self.build, self.trial = NEW, True
        elif op == fw.CONFIRM:
            self.trial = False
            self.reply(bytes([fw.ACK, 1, op, fw.OK, 0, 0, 0, 0]))
        else:
            self.reply(bytes([fw.ACK, 1, op, fw.OK, 0, 0, 0, 0]))


async def main(browser_path):
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        image = bytes(range(256)) * 80
        (folder / 'gateway.bin').write_bytes(image)
        (folder / 'gateway.json').write_text(json.dumps({'build': NEW, 'size': len(image), 'sha256': hashlib.sha256(image).hexdigest()}))
        state = State('socketcan')
        state.connected = True
        async def quick(seconds):
            await asyncio.sleep(min(seconds, .01))
        state.firmware = fw.ModuleFirmware(state, folder, sleep=quick)
        state.firmware.run = lambda: asyncio.sleep(3600)   # No background asking: the test decides when the gateway is heard.
        gateway = Gateway(state.firmware)
        state.controls.attach(gateway.sender)
        runner = web.AppRunner(create_app(state), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=browser_path)
            page = await browser.new_page(viewport={'width': 1920, 'height': 720})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                await page.goto(f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}')
                await page.locator('#drive-launch').click()
                await page.locator('#operations-launch').click()
                await page.locator('[data-ops-tab="support"]').click()
                # Before the gateway has answered: said plainly, and nothing to press.
                await page.wait_for_function("document.getElementById('firmware-status').textContent.includes('not answering')")
                assert await page.locator('#firmware-install').is_hidden()
                await state.firmware.query()
                await page.wait_for_function(f"document.getElementById('firmware-status').textContent.includes('build {OLD}. Build {NEW} is ready to install')")
                button = page.locator('#firmware-install')
                assert await button.is_visible() and await button.inner_text() == 'Install gateway firmware'
                box = await page.locator('#firmware-status').bounding_box()
                dialog = await page.locator('#operations-dialog').bounding_box()
                assert box['x'] >= dialog['x'] and box['x'] + box['width'] <= dialog['x'] + dialog['width'], (box, dialog)
                await page.screenshot(path=str(ROOT / '.tmp/firmware-ready.png'))
                # One press only arms it and says what will pause.
                await button.click()
                assert await button.inner_text() == 'Press again'
                assert 'Stop the car first' in await page.locator('#firmware-status').inner_text()
                assert fw.BEGIN not in gateway.commands
                # Moving: refused with the reason, nothing sent.
                state.samples['vehicle.speed_kph', 0x203] = dict(value=40, quality='live', seen=state.clock(), source_id=0x203, timestamp_ms=0)
                await button.click()
                await page.wait_for_function("document.getElementById('firmware-status').textContent.includes('Stop the car first: the module does nothing else')")
                assert fw.BEGIN not in gateway.commands
                del state.samples['vehicle.speed_kph', 0x203]
                # Stopped: two presses install it, with progress, to the confirmed result.
                await page.wait_for_timeout(1500)
                assert 'Stop the car first: the module does nothing else' in await page.locator('#firmware-status').inner_text()   # Still readable.
                await page.wait_for_function("document.getElementById('firmware-install').textContent === 'Install gateway firmware'", timeout=10000)
                await button.click()
                await button.click()
                await page.wait_for_function("/Sending: \\d+ of \\d+ KB \\(\\d+%\\)/.test(document.getElementById('firmware-status').textContent)")
                assert await button.is_disabled()
                await page.wait_for_function(f"document.getElementById('firmware-status').textContent === 'Gateway updated to build {NEW}'", timeout=30000)
                await page.wait_for_function("document.getElementById('firmware-install').hidden")
                assert gateway.blocks == -(-len(image) // fw.BLOCK_BYTES) and gateway.commands[-1] == fw.CONFIRM and not gateway.trial
                assert not errors, errors
            finally:
                await page.close()
                await browser.close()
                await runner.cleanup()
    print('Gateway firmware: status line, two-press install, refusal while moving, progress and confirmed result passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser')
    asyncio.run(main(parser.parse_args().browser))
