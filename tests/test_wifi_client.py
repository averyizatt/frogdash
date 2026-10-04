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
            ('dev', 'wifi'): '*:thefrogpit:82:WPA2\n:thefrogpit:40:WPA2\n:My\:Net:55:--\n:DC-37BB0BD3:90:WPA2\n::30:WPA2\n',
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
        self.assertEqual([n['ssid'] for n in result['networks']], ['thefrogpit', 'My:Net'])
        self.assertEqual(result['networks'][0], {'ssid': 'thefrogpit', 'signal': 82, 'secure': True, 'saved': True, 'connected': True})
        self.assertFalse(result['networks'][1]['secure'])


class WifiInterfaceTests(unittest.TestCase):
    def test_internet_uses_the_adapter_the_dash_cam_does_not(self):
        class Fake:
            def __init__(self, name): self.name = name
        for dashcam, expected in (('wlan0', 'wlan1'), ('wlan1', 'wlan0')):
            with patch.object(helper, 'nmcli', lambda *a, **k: (0, dashcam + '
', '')),                  patch.object(helper.Path, 'glob', lambda self, pattern: [Fake('wlan0'), Fake('wlan1')]):
                self.assertEqual(helper.interface(), expected)


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
                self.assertEqual((await client.post('/wifi-client', json={'action': 'connect', 'ssid': 'home', 'password': 'longenough'})).status, 200)
                request = json.loads((Path(folder) / 'wifi-request.json').read_text())
                self.assertEqual(request, {'action': 'connect', 'ssid': 'home', 'password': 'longenough'})
                self.assertTrue((await (await client.get('/wifi-client')).json())['pending'])


if __name__ == '__main__':
    unittest.main()
