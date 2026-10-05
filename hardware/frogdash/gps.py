"""USB GPS through the distribution's python3-gps/libgps bindings."""
import asyncio
import math
import time

STALL_S = 10  # Reopen the gpsd connection after this long without any report.


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

    def update(self, report):
        kind = report.get("class")
        if kind not in ("TPV", "SKY"):
            return
        device = report.get("device")
        self.report_seen = self.clock()
        if self.device and device != self.device:
            # A receiver that re-plugs can come back under another name (ttyACM0 -> ttyACM1).
            # Follow it once the old name has been silent for 10 s, unless the user named one.
            if self.device_fixed or not device or self.clock() - self.device_seen <= 10:
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
    while True:
        session = None
        try:
            session = await asyncio.to_thread(libgps.gps, host="127.0.0.1", port="2947",
                                              mode=libgps.WATCH_ENABLE | libgps.WATCH_NEWSTYLE)
            session.sock.settimeout(1)
            gps_state.fields.clear()
            gps_state.mode = 0
            gps_state.fix_seen = float("-inf")
            gps_state.connected, gps_state.status = True, "gpsd connected; waiting for fix"
            gps_state.report_seen = gps_state.clock()
            while True:
                if await asyncio.to_thread(session.waiting, .2):
                    report = await asyncio.to_thread(next_report, session)
                    if report is not None:
                        gps_state.update(report)
                else:
                    await asyncio.sleep(.05)
                if gps_state.clock() - gps_state.report_seen > STALL_S:
                    # A connection that delivers nothing is treated as dead and reopened.
                    raise ConnectionError(f"no GPS reports for {STALL_S} s")
        except (OSError, ValueError, KeyError, libgps.json_error) as exc:
            gps_state.status = f"gpsd disconnected: {exc}"
        finally:
            gps_state.connected = False
            if session is not None:
                session.close()
        await asyncio.sleep(1)
