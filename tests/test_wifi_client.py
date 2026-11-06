import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from hardware.frogdash.paint import Paint
from hardware.frogdash.server import create_app
from hardware.frogdash.state import State

spec = importlib.util.spec_from_file_location('frogdash_wifi', Path(__file__).resolve().parents[1] / 'tools' / 'frogdash_wifi.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class WifiHelperTests(unittest.TestCase):
    def test_survey_parses_escapes_and_hides_the_dash_cam(self):
        replies = {
            ('con',): 'frogdash-thefrogpit:802-11-wireless\nWired connection 1:802-3-ethernet\n',
            ('dev', 'wifi'): '*:thefrogpit:82:WPA2\n:thefrogpit:40:WPA2\n:My\:Net:55:--\n:DC-37BB0BD3:90:WPA2\n::30:WPA2\n'
                             ':Avery’s iPhone:48:WPA2\n:bad\x07name:20:WPA2\n',
            ('dev', 'show'): '192.168.1.44/24\n',
            ('networking',): 'full\n',
        }
        def nmcli(*args, timeout=45):
            words = [a for a in args if not a.startswith('-') and a not in ('NAME,TYPE', 'IN-USE,SSID,SIGNAL,SECURITY', 'IP4.ADDRESS')]
            for key, reply in replies.items():
                if tuple(words[:len(key)]) == key:
                    return 0, reply, ''
            return 0, '', ''
        with patch.object(helper, 'nmcli', nmcli):
            result = helper.survey('wlan0')
        self.assertEqual((result['connected'], result['address'], result['internet']), ('thefrogpit', '192.168.1.44', True))
        # An iPhone's hotspot (curly apostrophe) is listed; a name with a control character is not.
        self.assertEqual([n['ssid'] for n in result['networks']], ['thefrogpit', 'My:Net', 'Avery’s iPhone'])
        self.assertEqual(result['networks'][0], {'ssid': 'thefrogpit', 'signal': 82, 'secure': True, 'saved': True, 'connected': True})
        self.assertFalse(result['networks'][1]['secure'])


class WifiInterfaceTests(unittest.TestCase):
    def test_internet_uses_the_adapter_the_dash_cam_does_not(self):
        class Fake:
            def __init__(self, name): self.name = name
        for dashcam, expected in (('wlan0', 'wlan1'), ('wlan1', 'wlan0')):
            reply = (0, dashcam, '')
            with patch.object(helper, 'nmcli', lambda *a, **k: reply), \
                 patch.object(helper.Path, 'glob', lambda self, pattern: [Fake('wlan0'), Fake('wlan1')]):
                self.assertEqual(helper.interface(), expected)


class WifiFallbackTests(unittest.TestCase):
    """The car: the built-in wlan0 could not join the phone hotspot, wlan1 could (November 2026)."""
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        state = Path(self.folder.name)
        self.calls = []
        self.status = state / 'wifi-status.json'
        self.patches = [patch.object(helper, 'STATUS', self.status), patch.object(helper, 'REQUEST', state / 'wifi-request.json'),
                        patch.object(helper, 'LAST', state / 'wifi-adapter'), patch.object(helper, 'CHOICE', state / 'wifi-internet'),
                        patch.object(helper, 'LOCK', state / 'lock'), patch.object(helper.time, 'sleep', lambda s: None),
                        patch.object(helper, 'radio_on', lambda: self.calls.append(('radio on',))),
                        patch.object(helper, 'adapters', lambda: helper.__dict__['_order'])]
        helper._order = ['wlan0', 'wlan1']
        for p in self.patches:
            p.start()
        self.state = state

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.folder.cleanup()

    def run_helper(self, request, works_on=('wlan1',), wrong=False, sees=('wlan0', 'wlan1'), on=None):
        (self.state / 'wifi-request.json').write_text(json.dumps(request))
        def nmcli(*args, timeout=45):
            self.calls.append(args)
            if args[:4] == ('-t', '-f', 'SSID', 'dev'):          # What an adapter's scan lists
                return 0, 'Phone\n' if args[args.index('ifname') + 1] in sees else 'Other\n', ''
            if args[:4] == ('-t', '-f', 'ACTIVE,SSID', 'dev'):   # What it is on now
                return 0, 'yes:Phone\n' if args[args.index('ifname') + 1] == on else 'no:Phone\n', ''
            if args[:1] == ('--wait',) and 'ifname' in args:
                device = args[args.index('ifname') + 1]
                if wrong:
                    return 4, '', 'Secrets were required, but not provided'
                return (0, '', '') if device in works_on else (10, '', 'No network with SSID found')
            if 'show' in args and 'dashcam' in args:
                return 10, '', 'no such connection'
            return 0, '', ''
        with patch.object(helper, 'nmcli', nmcli):
            helper.main()
        return json.loads(self.status.read_text())

    def test_join_falls_back_to_the_other_adapter_and_remembers_it(self):
        status = self.run_helper({'action': 'connect', 'ssid': 'Phone', 'password': 'p' * 8})
        self.assertEqual(status['state'], 'connected')
        self.assertIn('with wlan1: wlan0 could not', status['message'])
        self.assertEqual((self.state / 'wifi-adapter').read_text(), 'wlan1')
        # Saved for any adapter, so the next start joins it on whichever one sees it.
        self.assertIn(('con', 'modify', 'frogdash-Phone', 'connection.interface-name', ''), self.calls)
        self.assertEqual(self.calls[0], ('radio on',))

    def test_neither_adapter_says_so_and_a_wrong_password_stops_at_once(self):
        status = self.run_helper({'action': 'connect', 'ssid': 'Phone', 'password': 'p' * 8}, works_on=())
        self.assertEqual(status['state'], 'failed')
        self.assertIn('with wlan0 or wlan1', status['message'])
        self.calls.clear()
        status = self.run_helper({'action': 'connect', 'ssid': 'Phone', 'password': 'p' * 8}, wrong=True)
        self.assertEqual(status['message'], 'Wrong password')
        self.assertFalse(any(call[:1] == ('--wait',) and 'wlan1' in call for call in self.calls))   # No join tried on wlan1

    def test_an_adapter_that_cannot_see_the_network_is_skipped_at_once(self):
        status = self.run_helper({'action': 'connect', 'ssid': 'Phone', 'password': 'p' * 8}, sees=('wlan1',))
        self.assertEqual(status['state'], 'connected')
        self.assertFalse(any(call[:1] == ('--wait',) and 'wlan0' in call for call in self.calls))   # No 30 s wait on wlan0
        self.assertIn('wlan0 (does not see it) could not', status['message'])
        self.calls.clear()
        status = self.run_helper({'action': 'connect', 'ssid': 'Phone', 'password': 'p' * 8}, sees=())
        self.assertIn('not in range of wlan0 or wlan1', status['message'])

    def test_a_network_already_joined_is_left_alone(self):
        # Typing the password again must not drop the connection that works.
        status = self.run_helper({'action': 'connect', 'ssid': 'Phone', 'password': 'p' * 8}, on='wlan1')
        self.assertEqual((status['state'], status['message']), ('connected', 'Joined Phone'))
        self.assertFalse(any('delete' in call or call[:1] == ('--wait',) for call in self.calls))

    def test_scan_uses_both_adapters(self):
        self.run_helper({'action': 'scan'})
        rescans = [c[-1] for c in self.calls if c[:3] == ('dev', 'wifi', 'rescan')]
        self.assertEqual(rescans, ['wlan0', 'wlan1'])

    def test_order_the_owner_choice_then_the_last_that_worked_then_built_in(self):
        class Fake:
            def __init__(self, name): self.name = name
        self.patches[-1].stop()
        try:
            with patch.object(helper, 'nmcli', lambda *a, **k: (0, '', '')), \
                 patch.object(helper.Path, 'glob', lambda self, pattern: [Fake('wlan0'), Fake('wlan1')]):
                self.assertEqual(helper.adapters(), ['wlan0', 'wlan1'])
                (self.state / 'wifi-adapter').write_text('wlan1')
                self.assertEqual(helper.adapters(), ['wlan1', 'wlan0'])
                (self.state / 'wifi-internet').write_text('wlan0')
                self.assertEqual(helper.adapters(), ['wlan0', 'wlan1'])
        finally:
            self.patches[-1].start()


class WifiRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_requests_are_validated_and_written(self):
        with tempfile.TemporaryDirectory() as folder:
            state = State()
            state.paint = Paint(Path(folder) / 'appearance-paint.json')
            async with TestClient(TestServer(create_app(state))) as client:
                self.assertEqual((await (await client.get('/wifi-client')).json())['networks'], [])
                for bad in ({'action': 'run'}, {'action': 'connect', 'ssid': '', 'password': 'longenough'},
                            {'action': 'connect', 'ssid': 'home', 'password': 'short'}):
                    self.assertEqual((await client.post('/wifi-client', json=bad)).status, 400)
                self.assertEqual((await client.post('/wifi-client', json={'action': 'connect', 'ssid': 'x' * 30 + '’', 'password': 'longenough'})).status, 400)   # 33 bytes
                self.assertEqual((await client.post('/wifi-client', json={'action': 'connect', 'ssid': 'Avery’s iPhone', 'password': 'longenough'})).status, 200)
                self.assertEqual(json.loads((Path(folder) / 'wifi-request.json').read_text())['ssid'], 'Avery’s iPhone')
                self.assertEqual((await client.post('/wifi-client', json={'action': 'connect', 'ssid': 'home', 'password': 'longenough'})).status, 200)
                request = json.loads((Path(folder) / 'wifi-request.json').read_text())
                self.assertEqual(request, {'action': 'connect', 'ssid': 'home', 'password': 'longenough'})
                self.assertTrue((await (await client.get('/wifi-client')).json())['pending'])


if __name__ == '__main__':
    unittest.main()
