import subprocess
import unittest
from unittest.mock import patch

from hardware.frogdash import netstate


class NetStateTests(unittest.TestCase):
    def test_wifi_names_from_network_manager(self):
        out = 'ethernet:unavailable:\nwifi:connected:dashcam\nwifi:connected:Home\\: 5G\nwifi:disconnected:\nloopback:connected (externally):lo\n'
        with patch.object(netstate.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, out, '')):
            self.assertEqual(netstate.wifi_networks(), ['dashcam', 'Home: 5G'])

    def test_checked_at_most_every_ten_seconds(self):
        netstate._last.update(at=float('-inf'), value=None)
        now = [100.0]
        with patch.object(netstate, 'wifi_networks', return_value=['Home']) as wifi, patch.object(netstate, 'internet', return_value=True):
            self.assertEqual(netstate.check(lambda: now[0]), {'wifi': ['Home'], 'internet': True})
            now[0] += 5
            netstate.check(lambda: now[0])
            self.assertEqual(wifi.call_count, 1)
            now[0] += 6
            netstate.check(lambda: now[0])
            self.assertEqual(wifi.call_count, 2)


if __name__ == '__main__':
    unittest.main()
