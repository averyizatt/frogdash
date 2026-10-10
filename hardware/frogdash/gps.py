"""USB GPS through the distribution's python3-gps/libgps bindings."""
import asyncio
import json
import math
import socket
import time

STALL_S = 10  # Reopen the gpsd connection after this long without any report.
QUIET_S = 15  # No report from any receiver for this long: the receiver is not being heard.


def ubx(message_class, message_id, payload=b''):
    """A u-blox binary command with its header and checksum."""
    body = bytes([message_class, message_id]) + len(payload).to_bytes(2, 'little') + payload
    a = b = 0
    for byte in body:
        a = (a + byte) & 0xFF
        b = (b + a) & 0xFF
    return b'\xb5\x62' + body + bytes([a, b])


# CFG-RST, GNSS-only controlled restart. Warm keeps what the receiver knows about the
# satellites; cold clears it and starts from nothing.
UBX_WARM_START = ubx(0x06, 0x04, bytes([0x01, 0x00, 0x02, 0x00]))
UBX_COLD_START = ubx(0x06, 0x04, bytes([0xFF, 0xFF, 0x02, 0x00]))


def send_to_receiver(path, frame, host='127.0.0.1', port=2947, timeout=2):
    """Pass raw bytes to the receiver through gpsd (gpsd 3.21 or newer; not in read-only mode)."""
    with socket.create_connection((host, port), timeout) as link:
        link.sendall(('?DEVICE=' + json.dumps({'path': path, 'hexdata': frame.hex()}, separators=(',', ':')) + '\n').encode())
        link.settimeout(.5)
        try:
            link.recv(4096)
        except OSError:
            pass


class GPS:
    def __init__(self, clock=time.monotonic, wall=time.time, device=None, transmit=True):
        self.clock, self.wall = clock, wall
        self.device, self.transmit = device, transmit
        self.device_fixed = device is not None  # Named by the user: never switch.
        self.device_seen = float('-inf')
        self.report_seen = float('-inf')
        self.connected = False
        self.status = "waiting for gpsd"
        self.mode = 0
        self.fix_seen = float("-inf")
        self.fields = {}
        self.conflict = False
        self.tx_count = 0
        self.tx_status = "waiting for CAN" if transmit else "disabled"
        self.on_report = None
        self.sky = None  # Latest satellite report: seen, used, strongest signal.
        self.sky_seen = float('-inf')
        self.other_device = None  # A receiver gpsd hears that this dash is not using.
        self.other_seen = float('-inf')
        self.gpsd_ok = None        # Whether the last connection attempt reached gpsd.
        self.gpsd_error = None
        self.started = None        # When the dash first tried to reach gpsd.
        self.linked_at = float('-inf')
        self.first_fix_s = None    # Seconds from start to the first position.
        self.devices = {}          # What gpsd is watching: path -> driver name.

    def update(self, report):
        kind = report.get("class")
        if kind == "DEVICES":
            self.devices = {d.get("path"): d.get("driver") for d in report.get("devices", []) if d.get("path")}
            return
        if kind == "DEVICE" and report.get("path"):
            if report.get("activated") or report.get("driver"):
                self.devices[report["path"]] = report.get("driver") or self.devices.get(report["path"])
            return
        if kind not in ("TPV", "SKY"):
            return
        device = report.get("device")
        self.report_seen = self.clock()
        if self.device and device != self.device:
            # A receiver that re-plugs can come back under another name (ttyACM0 -> ttyACM1).
            # Follow it once the old name has been silent for 10 s, unless the user named one.
            if self.device_fixed or not device or self.clock() - self.device_seen <= 10:
                if device:
                    self.other_device, self.other_seen = device, self.clock()
                return
            self.device = device
            self.fields.clear()
            self.mode = 0
        if device and not self.device:
            self.device = device
        self.device_seen = self.clock()
        if self.on_report:
            self.on_report(report)
        now, stamp = self.clock(), int(self.wall() * 1000)

        def put(name, value):
            if isinstance(value, (int, float)) and math.isfinite(value):
                self.fields[name] = (value, now, stamp)

        if kind == "TPV":
            self.mode = report.get("mode", 0)
            self.fix_seen = now
            self.status = "GPS fix" if self.mode in (2, 3) else "GPS searching"
            if self.mode in (2, 3) and self.first_fix_s is None and self.started is not None:
                self.first_fix_s = round(now - self.started, 1)
            if self.mode not in (2, 3) or report.get("status") in (5, 6, 8):
                self.mode = 0
                self.fields.clear()
                return
            speed = report.get("speed")
            if isinstance(speed, (float, int)) and 0 <= speed <= 6553.5 / 3.6:
                put("vehicle.speed_kph", speed * 3.6)
            elif speed is not None:
                self.fields.pop("vehicle.speed_kph", None)
            for source, target in (("lat", "gps.latitude"), ("lon", "gps.longitude"), ("track", "gps.track_deg")):
                put(target, report.get(source))
            if self.mode == 3:
                put("gps.altitude_m", report.get("altMSL"))
            else:
                self.fields.pop("gps.altitude_m", None)
        else:
            satellites = report.get("satellites", [])
            put("gps.satellites", sum(bool(s.get("used")) for s in satellites))
            put("gps.satellites_in_view", len(satellites))
            strengths = [s.get("ss") for s in satellites if isinstance(s.get("ss"), (int, float)) and s.get("ss") > 0]
            self.sky = {'in_view': len(satellites), 'used': sum(bool(s.get("used")) for s in satellites),
                        'heard': len(strengths), 'best_db': round(max(strengths)) if strengths else None}
            self.sky_seen = now

    def diagnosis(self):
        """Why there is or is not a position, in words, with what to do about it."""
        now = self.clock()
        device = self.device or 'no receiver'
        if self.gpsd_ok is None:
            return {'state': 'starting', 'text': self.status, 'fix': ''}
        if not self.gpsd_ok:
            return {'state': 'no-gpsd', 'text': f'GPS service not reachable: {self.gpsd_error or self.status}',
                    'fix': 'sudo systemctl status gpsd; check python3-gps is installed'}
        if self.device_fixed and now - self.other_seen <= QUIET_S and now - self.device_seen > QUIET_S:
            return {'state': 'silent', 'text': f'gpsd hears a receiver at {self.other_device}, but the dash is set to use only {self.device}',
                    'fix': 'Remove --gps-device from FROGDASH_ARGS in /etc/default/frogdash (the dash then follows the receiver), and restart frogdash'}
        if now - self.report_seen > QUIET_S:
            if self.started is not None and now - self.started <= QUIET_S:
                return {'state': 'starting', 'text': 'Waiting for the receiver to report', 'fix': ''}
            watching = ', '.join(sorted(self.devices)) or 'no port at all'
            return {'state': 'silent', 'text': f'No receiver is reporting (the GPS service is watching {watching})',
                    'fix': 'Receiver unplugged, or gpsd is watching the wrong port: ls -l /dev/serial/by-id/ and set DEVICES in /etc/default/gpsd to the GPS'}
        sky = self.sky if now - self.sky_seen <= QUIET_S else None
        if self.mode in (2, 3):
            return {'state': 'fix', 'text': f"Fix with {sky['used'] if sky else '?'} satellites ({device})", 'fix': ''}
        if not sky or not sky['heard']:
            return {'state': 'deaf', 'text': f'Receiver is talking but hears no satellites ({device})',
                    'fix': 'Antenna has no sky view, or radio noise is drowning it: move it away from the Pi blue USB 3 ports, the dash cam and the Wi-Fi adapter with a USB extension cable'}
        strength = f"strongest signal {sky['best_db']} dB" if sky['best_db'] is not None else 'signal strength unknown'
        if sky['best_db'] is not None and sky['best_db'] < 25:
            return {'state': 'weak', 'text': f"Hears {sky['heard']} satellites but all weak ({strength}; a fix needs about 30)",
                    'fix': 'Weak signals with a clear sky mean radio noise: move the receiver away from the Pi blue USB 3 ports, the dash cam and the Wi-Fi adapter with a USB extension cable'}
        return {'state': 'searching', 'text': f"Hears {sky['heard']} satellites, {strength}; working out a position",
                'fix': 'A first fix after a long break can take a few minutes with a clear view of the sky'}

    def driver(self):
        """gpsd's name for the receiver in use, such as 'u-blox'; None until it is identified."""
        return self.devices.get(self.device) or next((name for name in self.devices.values() if name), None)

    def restart_receiver(self, cold=False, send=send_to_receiver):
        """Ask a u-blox receiver to restart its satellite search. Returns False for other makes."""
        path = self.device or next(iter(self.devices), None)
        if not path or 'u-blox' not in (self.driver() or '').lower():
            return False
        send(path, UBX_COLD_START if cold else UBX_WARM_START)
        return True

    def values(self):
        now = self.clock()
        result = {}
        for name in ("vehicle.speed_kph", "gps.altitude_m", "gps.latitude", "gps.longitude", "gps.track_deg", "gps.satellites", "gps.satellites_in_view"):
            value, seen, stamp = self.fields.get(name, (None, float("-inf"), None))
            sky = name in ("gps.satellites", "gps.satellites_in_view")
            quality = "unavailable" if value is None else "live"
            if value is not None and (not self.connected or now - seen > (5 if sky else 2)):
                quality = "stale"
            elif not sky and (self.mode not in (2, 3) or now - self.fix_seen > 2):
                quality = "unavailable"
            result[name] = {"value": value, "quality": quality, "source": "gpsd", "source_id": None, "timestamp_ms": stamp}
        return result

    def frame(self):
        """Existing 0x203: km/h x10 BE, signed MSL meters BE."""
        values = self.values()
        def valid(name): return values[name]["quality"] == "live"
        speed_ok = valid("vehicle.speed_kph")
        speed = round(values["vehicle.speed_kph"]["value"] * 10) if speed_ok else 0
        alt = round(values["gps.altitude_m"]["value"]) if valid("gps.altitude_m") else 0
        alt = max(-32768, min(32767, alt))
        used = min(255, values["gps.satellites"]["value"]) if valid("gps.satellites") else 0
        visible = min(255, values["gps.satellites_in_view"]["value"]) if valid("gps.satellites_in_view") else 0
        flags = (0x13 if speed_ok else 0) | (0x08 if visible else 0)
        return speed.to_bytes(2, "big") + alt.to_bytes(2, "big", signed=True) + bytes([used, self.mode if speed_ok else 0, flags, visible])


def next_report(session):
    # libgps may return a partial read without replacing cached .data. Clear
    # that cache so fragments never refresh a previous fix's freshness timer.
    session.data = None
    if session.read() < 0:
        raise ConnectionError("gpsd stream closed")
    return session.data


async def gpsd(gps_state):
    try:
        import gps as libgps
    except ImportError:
        gps_state.status = "Install python3-gps; create venv with --system-site-packages"
        return
    failures = 0
    while True:
        session = None
        if gps_state.started is None:
            gps_state.started = gps_state.clock()
        try:
            session = await asyncio.to_thread(libgps.gps, host="127.0.0.1", port="2947",
                                              mode=libgps.WATCH_ENABLE | libgps.WATCH_NEWSTYLE)
            session.sock.settimeout(1)
            gps_state.fields.clear()
            gps_state.mode = 0
            gps_state.fix_seen = float("-inf")
            gps_state.connected, gps_state.status = True, "gpsd connected; waiting for fix"
            gps_state.gpsd_ok, gps_state.gpsd_error = True, None
            # Stall detection counts from this connection; report_seen is only ever a real report,
            # so a receiver that says nothing is recognised as silent across reconnects.
            gps_state.linked_at = gps_state.clock()
            failures = 0
            while True:
                if await asyncio.to_thread(session.waiting, .2):
                    report = await asyncio.to_thread(next_report, session)
                    if report is not None:
                        gps_state.update(report)
                else:
                    await asyncio.sleep(.05)
                if gps_state.clock() - max(gps_state.report_seen, gps_state.linked_at) > STALL_S:
                    # A connection that delivers nothing is treated as dead and reopened.
                    raise ConnectionError(f"no GPS reports for {STALL_S} s")
        except (OSError, ValueError, KeyError, libgps.json_error) as exc:
            gps_state.status = f"gpsd disconnected: {exc}"
            if session is None:
                gps_state.gpsd_ok, gps_state.gpsd_error = False, str(exc)
        finally:
            gps_state.connected = False
            if session is not None:
                session.close()
        # At start-up gpsd may come up a moment after the dash: retry quickly, then ease off.
        failures += 1
        await asyncio.sleep(.25 if failures <= 20 else 1)
