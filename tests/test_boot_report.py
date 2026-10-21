import tempfile
import unittest
from pathlib import Path

from tools.boot_report import early_kiosk_lines, usb_topology


class BootReportTests(unittest.TestCase):
    def test_early_timeline_survives_later_restarts_and_out_of_order_journal(self):
        output = ('[ 155.1] pi: Frogdash kiosk: restarted\n'
                  '[ 24.95] pi: Frogdash kiosk: first render\n'
                  '-- No entries --\n'
                  '[ 7.1] pi: Frogdash kiosk: starting Cage\n')
        lines = early_kiosk_lines(output).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn('starting Cage', lines[0])
        self.assertIn('first render', lines[1])
        self.assertIn('No kiosk milestones', early_kiosk_lines('permission denied'))

    def test_usb_report_maps_kernel_paths_without_device_serials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            device = root / '1-1.2.4'
            (device / 'power').mkdir(parents=True)
            for name, value in {'idVendor': '0bda', 'idProduct': 'c820',
                                'product': '802.11ac NIC', 'serial': 'private-serial',
                                'power/control': 'auto'}.items():
                (device / name).write_text(value)
            (root / 'unrelated-entry').mkdir()
            result = usb_topology(root)
            self.assertIn('1-1.2.4:', result)
            self.assertIn('idVendor=0bda', result)
            self.assertIn('power/control=auto', result)
            self.assertNotIn('private-serial', result)
            self.assertEqual(len(result.splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
