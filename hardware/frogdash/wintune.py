"""Windows tuning software on the dash (Tuning page). Experimental.

Two routes, chosen per USB device by what Linux makes of it (usb_devices):

- serial: the ECU or its tuning cable is a USB serial port (FTDI, Silicon Labs, CH340,
  Prolific, or USB ACM). The maker's Windows tuner runs on the dash in Wine through Box64
  (tools/frogdash_wine.py), with the port as COM1, COM2...
- driver: the device needs its maker's own Windows driver, which Wine cannot load. The dash
  shares it with a Windows PC on its network over USB/IP (tools/frogdash_tuning.py); the PC
  attaches it, loads the real driver and runs the tuner as if the cable were plugged in.

Like tune.py this is a mailbox: the kiosk launcher (tools/launch_kiosk.py), which runs in
the screen's session, reports what Wine has (programs, installers, COM ports) every 2 s and
collects the dash's request to install or open something. Root's jobs (the USB stick, USB
sharing) go to frogdash-tuning.path as a request file.
"""
from pathlib import Path
import os

KIOSK_TIMEOUT = 8.0
SYS_USB = Path(os.environ.get('FROGDASH_SYS_USB', '/sys/bus/usb/devices'))
SERIAL_DRIVERS = {'ftdi_sio', 'cp210x', 'ch341', 'ch341-uart', 'pl2303', 'cdc_acm', 'usbserial_generic', 'option', 'qcserial'}
# Interfaces that are plainly not an ECU or tuning cable: left out of the list.
NOT_TUNING = {'hub', 'usbhid', 'usb-storage', 'uas', 'uvcvideo', 'snd-usb-audio', 'btusb', 'cdc_ether', 'rndis_host',
              'r8152', 'ax88179_178a', 'rtl8xxxu', 'mt7601u', 'rt2800usb', '88XXau', 'rtw_8821cu', 'rtw88_8821cu', 'brcmfmac', 'gs_usb'}
NOT_TUNING_CLASSES = {'03', '08', '09', '0e', '01', 'e0'}   # HID, storage, hub, video, audio, wireless


def read(path, default=''):
    try:
        return path.read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        return default


def usb_devices(root=SYS_USB):
    """Plugged-in USB devices that could be an ECU or a tuning cable, each with its route."""
    out = []
    for device in sorted(root.glob('[0-9]*-[0-9]*')):
        if ':' in device.name or not (device / 'idVendor').exists():
            continue
        drivers, classes, ttys = set(), set(), []
        for interface in device.glob(f'{device.name}:*'):
            driver = interface / 'driver'
            if driver.exists():
                drivers.add(os.path.basename(os.path.realpath(driver)))
            classes.add(read(interface / 'bInterfaceClass').lower())
            ttys += [t.name for t in interface.glob('tty*') if t.name.startswith('tty')]
            ttys += [t.name for t in interface.glob('tty/tty*')]
        if read(device / 'bDeviceClass').lower() == '09':
            continue                                              # A hub
        name = ' '.join(filter(None, (read(device / 'manufacturer'), read(device / 'product')))) or 'USB device'
        entry = {'busid': device.name, 'name': name[:80], 'id': f"{read(device / 'idVendor')}:{read(device / 'idProduct')}",
                 'drivers': sorted(drivers), 'ttys': sorted(set(ttys))}
        if 'usbip-host' in drivers:
            entry['route'] = 'shared'
        elif drivers & SERIAL_DRIVERS or entry['ttys']:
            entry['route'] = 'serial'
        elif drivers & NOT_TUNING or (classes and classes <= NOT_TUNING_CLASSES):
            continue
        else:
            entry['route'] = 'driver'                             # Nothing in Linux claims it: the maker's own driver
        out.append(entry)
    return out


class WinTune:
    def __init__(self, state):
        self.state = state
        self.want = None
        self.kiosk = None
        self.seen = float('-inf')
        self.wheel_seen = 0

    def linked(self):
        return self.kiosk is not None and self.state.clock() - self.seen < KIOSK_TIMEOUT

    def snapshot(self):
        kiosk = self.kiosk if self.linked() else None
        out = {'available': bool(kiosk and kiosk.get('ready')), 'kiosk': kiosk is not None,
               'state': kiosk['state'] if kiosk else 'unavailable',
               'message': kiosk['message'] if kiosk else 'Only on the dash screen in the car: the kiosk runs Windows tuners',
               'programs': kiosk.get('programs', []) if kiosk else [], 'installers': kiosk.get('installers', []) if kiosk else [],
               'ports': kiosk.get('ports', []) if kiosk else []}
        if kiosk and not kiosk.get('ready'):
            out['message'] = kiosk.get('why') or out['message']
        return out

    def request(self, action, target=None):
        if action not in ('install', 'open', 'close'):
            raise ValueError('Unknown Windows tuning action')
        status = self.snapshot()
        if action != 'close' and not status['available']:
            raise ValueError(status['message'])
        if action == 'install' and target not in {i['path'] for i in status['installers']}:
            raise ValueError('That installer is not on the Pi')
        if action == 'open' and target not in {p['path'] for p in status['programs']}:
            raise ValueError('That program is not installed')
        self.want = {'action': action, 'target': target}
        return self.snapshot()

    def report(self, data):
        """The kiosk launcher's 2 s report. Returns what it should do now, or None."""
        if not isinstance(data, dict) or data.get('state') not in ('idle', 'running', 'failed') or not isinstance(data.get('message', ''), str):
            raise ValueError('Invalid kiosk report')
        keep = lambda items: [i for i in (items or [])[:50] if isinstance(i, dict)]
        self.kiosk = {'ready': bool(data.get('ready')), 'why': str(data.get('why', ''))[:300], 'state': data['state'],
                      'message': data.get('message', '')[:300], 'programs': keep(data.get('programs')),
                      'installers': keep(data.get('installers')), 'ports': keep(data.get('ports'))}
        self.seen = self.state.clock()
        action, self.want = self.want, None
        # Holding OFF (the wheel's "home") closes it, as for TunerStudio: a way back without a keyboard.
        events = list(self.state.wheel.events)
        home = any(e['action'] == 'home' and e['id'] > self.wheel_seen for e in events)
        if events:
            self.wheel_seen = max(self.wheel_seen, events[-1]['id'])
        if home and data['state'] == 'running' and action is None:
            action = {'action': 'close', 'target': None}
        return action
