"""Monotonic freshness, bounded diagnostics, and source arbitration."""
from collections import OrderedDict, deque
import time

from .protocol import ANALOG_BITS, ECU_TIMEOUT, EVENT_IDS, TIMEOUTS, decode
from .controls import Controls
from .taillight import TaillightSettings
from .race import Race
from .driving import Driving
from .trip import Trip
from .operations import Operations
from .backlight import Backlight
from .wheel import SteeringWheel
from .runtime import EngineRuntime
from .nav import Navigator

ALIASES = {
    "engine.rpm": ("ecu.rpm", "tach.rpm", "gateway.rpm"),
    "engine.coolant_c": ("ecu.coolant_c",),
    "engine.afr": ("ecu.afr",),
    "engine.ego_correction_pct": ("ecu.ego_correction_pct",),
    "vehicle.battery_v": ("ecu.battery_v",),
}
UNAVAILABLE = ("vehicle.fuel_pct", "lighting.highbeam", "engine.oil_temp_c")


class State:
    def __init__(self, mode="socketcan", clock=time.monotonic, wall=time.time):
        self.clock, self.wall = clock, wall
        self.mode = mode
        self.connected = False
        self.status = "starting"
        self.samples = {}
        self.raw = OrderedDict()
        self.capture, self.capture_until = None, 0.0  # Timed raw capture for the CAN recorder tool.
        self.frames = {}  # Per standard ID: count, first/last time, last payload and decode error.
        self.events = deque(maxlen=100)
        self.received = self.malformed = self.ignored = self.seq = 0
        self.gps = None
        self.recorder = None
        self.camera = None
        self.dashcam = None
        self.terminal_enabled = False
        self.paint = None
        self.imports = None
        self.race = Race(clock=clock, wall=wall)
        self.driving = Driving(self)
        self.trip = Trip(self)
        self.operations = Operations(self)
        self.backlight = Backlight()
        self.wheel = SteeringWheel(clock)
        self.health = None
        self.shutdown_history = None
        self.can_errors = {'frames': 0, 'bus_off': 0, 'restarts': 0}
        self.taillight = TaillightSettings(clock)
        self.runtime = EngineRuntime(self, enabled=mode == 'socketcan')
        self.nav = Navigator(clock, wall)
        self.controls = Controls(self)

    def ingest(self, can_id, data, extended=False, remote=False, error=False):
        now, stamp = self.clock(), int(self.wall() * 1000)
        self.received += 1
        if error:
            self.can_errors['frames'] += 1
            self.can_errors['bus_off'] += bool(can_id & 0x40)
            self.can_errors['restarts'] += bool(can_id & 0x100)
        raw_key = f"{'err' if error else 'ext' if extended else 'std'}:{can_id:X}"
        self.raw[raw_key] = {"id": can_id, "data": data.hex().upper(), "dlc": len(data),
                             "extended": extended, "remote": remote, "error": error,
                             "timestamp_ms": stamp}
        self.raw.move_to_end(raw_key)
        while len(self.raw) > 256:
            self.raw.popitem(last=False)
        if self.capture is not None and now <= self.capture_until and len(self.capture) < 200000:
            self.capture.append(f"({stamp / 1000:.6f}) can0 {can_id:0{8 if extended else 3}X}#{'R' if remote else data.hex().upper()}")
        if extended or remote or error:
            self.ignored += 1
            return
        if can_id in self.frames or len(self.frames) < 512:
            entry = self.frames.setdefault(can_id, {'count': 0, 'first': now, 'error': None, 'error_at': None})
            entry.update(count=entry['count'] + 1, seen=now, data=data.hex().upper())
        try:
            signals = decode(can_id, data)
        except ValueError as exc:
            self.malformed += 1
            if can_id in self.frames:
                self.frames[can_id].update(error=str(exc), error_at=now)
            if can_id in (0x205, 0x501):
                self.wheel.reset()
            self.status = str(exc)
            for (name, source), sample in self.samples.items():
                if source == can_id:
                    sample["quality"] = "fault"
            return
        for name, signal in signals.items():
            self.samples[name, can_id] = {"value": signal.value, "quality": signal.quality,
                                         "source_id": can_id, "timestamp_ms": stamp,
                                         "seen": now}
        if can_id == 0x205 and self.mode == "socketcan" and self.connected:
            self.wheel.observe(data)
        elif can_id == 0x501 and self.mode == "socketcan" and self.connected:
            self.wheel.observe_gateway(data)
        if can_id == 0x103:
            self.taillight.observe(data)
        self.controls.observe(can_id, data)
        if can_id in EVENT_IDS:
            self.events.append({"id": can_id, "timestamp_ms": stamp, "data": data.hex().upper(),
                                "values": {k: v.value for k, v in signals.items()}})

    def snapshot(self):
        now = self.clock()
        values = {}
        for (name, source), sample in self.samples.items():
            value = {k: v for k, v in sample.items() if k != "seen"}
            age = now - sample["seen"]
            # Event/config replies describe history, not current fault state.
            limit = ECU_TIMEOUT if 0x5E8 <= source <= 0x73F else TIMEOUTS.get(source, .5)
            if source not in EVENT_IDS and (not self.connected or age > limit):
                value["quality"] = "stale"
            previous = values.get(name)
            if previous is None or (value["quality"] == "live", value["timestamp_ms"]) > (previous["quality"] == "live", previous["timestamp_ms"]):
                values[name] = value
        missing = {"value": None, "quality": "unavailable", "source_id": None, "timestamp_ms": None}
        faults = values.get("sensors.fault_flags", missing)
        for name, bit in ANALOG_BITS.items():
            if name not in values or values[name]["quality"] != "live":
                continue
            if faults["quality"] != "live":
                values[name] = {**values[name], "quality": "unavailable" if faults["quality"] == "unavailable" else "stale"}
            elif faults["value"] & (1 << bit):
                values[name] = {**values[name], "quality": "fault"}
        # Prefer ECU IAT only while its own frame is fresh.
        ecu_iat = values.get("ecu.iat_c")
        if ecu_iat and ecu_iat["quality"] == "live":
            values["engine.iat_c"] = dict(ecu_iat)
        for target, sources in ALIASES.items():
            candidates = [values[s] for s in sources if s in values]
            chosen = next((v for v in candidates if v["quality"] == "live"), candidates[0] if candidates else missing)
            values[target] = dict(chosen)
        # The comfort heartbeat carries defaults and no battery validity bit;
        # keep that value diagnostic-only rather than treating it as measured.
        for name in UNAVAILABLE:
            if name != 'vehicle.fuel_pct' or name not in values:
                values[name] = dict(missing)
        boost = values.get("engine.boost_kpa")
        map_value, baro = values.get("ecu.map_kpa", missing), values.get("ecu.baro_kpa", missing)
        # Barometric pressure barely changes: keep the last reading so boost follows MAP alone.
        if baro["quality"] == "live":
            self.last_baro = baro
        elif map_value["quality"] == "live" and getattr(self, "last_baro", None):
            baro = {**self.last_baro, "quality": "live", "timestamp_ms": map_value["timestamp_ms"]}
        if map_value["quality"] == baro["quality"] == "live":
            values["engine.boost_kpa"] = {**map_value, "value": map_value["value"] - baro["value"],
                                          "timestamp_ms": min(map_value["timestamp_ms"], baro["timestamp_ms"])}
        elif boost and values.get("meth.fault_flags", missing)["quality"] == "live" and values["meth.fault_flags"]["value"] & 2:
            values["engine.boost_kpa"] = {**boost, "quality": "fault"}
        self.seq += 1
        if self.gps:
            # USB GPS is authoritative when configured; do not silently switch
            # to a different receiver on CAN when the USB receiver loses fix.
            values.update(self.gps.values())
        # GPS when it has a fix; otherwise wheel speed and dead reckoning (nav.py).
        values.update(self.nav.step(self, values))
        race = self.race.snapshot()
        values.update(self.trip.values())
        values['dash.bookmark_id'] = {'value': self.driving.marker_seq, 'quality': 'live', 'source_id': None,
                                       'source': 'Drive review', 'timestamp_ms': int(self.wall() * 1000)}
        race_quality = 'fault' if race['phase'] == 'invalid' else 'unavailable' if race['phase'] == 'idle' else 'live'
        race_values = {'phase': race['phase'], 'elapsed_s': race['elapsed'], 'distance_m': race['distance_m'],
                       'lap_count': race['lap_count'], 'best_lap_s': race['best_lap'], **race['splits']}
        for key, value in race_values.items():
            values['race.' + key] = {'value': value, 'quality': 'live' if key == 'phase' else race_quality if value is not None else 'unavailable',
                                    'source_id': None, 'source': 'GPS timer', 'timestamp_ms': int(self.wall() * 1000)}
        modules = {}
        # The comfort module is live from its dashboard heartbeat or its sensor-gateway frames.
        for name, sources in (("taillights", (0x100,)), ("comfort", (0x200, 0x500, 0x501, 0x503)),
                              ("watermeth", (0x300,)), ("knock", (0x307,))):
            matching = [v for v in values.values() if v["source_id"] in sources]
            modules[name] = "live" if any(v["quality"] == "live" for v in matching) else "stale" if matching else "unavailable"
        return {"type": "state", "seq": self.seq, "timestamp_ms": int(self.wall() * 1000),
                "mode": self.mode, "values": values, "modules": modules,
                "transport": {"connected": self.connected, "status": self.status,
                              "received": self.received, "malformed": self.malformed, "ignored": self.ignored},
                "runtime": self.runtime.snapshot(), "nav": self.nav.snapshot(),
                "gps": {"status": self.gps.status, "tx_status": self.gps.tx_status,
                        "tx_count": self.gps.tx_count, "conflict": self.gps.conflict} if self.gps else None,
                "controls": self.controls.status(), "taillight": self.taillight.snapshot(), "events": list(self.events), "race": race,
                "drive": self.driving.snapshot(), "trip": self.trip.snapshot(),
                "operations": self.operations.status(), "system": dict(self.health.status) if self.health else None,
                "can_errors": dict(self.can_errors),
                "wheel": self.wheel.snapshot(self.connected and self.mode == "socketcan"),
                "recording": dict(self.recorder.status) if self.recorder else {"enabled": False, "state": "disabled"}}
