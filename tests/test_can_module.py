import tempfile
import unittest
from pathlib import Path

from hardware.frogdash.health import can_module


class CanModuleTest(unittest.TestCase):
    def test_reports_spi_handshake_without_bus_traffic(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            net, interrupts = root / 'net', root / 'interrupts'
            interrupts.write_text('           CPU0       CPU1\n 52:          7          5  pinctrl-bcm2835  25 Edge      mcp251x\n')
            self.assertFalse(can_module('can0', net, interrupts)['present'])
            device = net / 'can0'
            device.mkdir(parents=True)
            (device / 'operstate').write_text('unknown\n')
            (device / 'flags').write_text('0x1\n')
            result = can_module('can0', net, interrupts)
            self.assertTrue(result['present'])
            self.assertTrue(result['up'])
            self.assertEqual(result['interrupts'], 12)
            (device / 'flags').write_text('0x0\n')
            self.assertFalse(can_module('can0', net, interrupts)['up'])


if __name__ == '__main__':
    unittest.main()
