"""Monotonic freshness, bounded diagnostics, and source arbitration."""
from collections import OrderedDict, deque
import time

from .protocol import ANALOG_BITS, EVENT_IDS, TIMEOUTS, decode
from .controls import Controls

ALIASES = {
    "engine.rpm": ("ecu.rpm", "tach.rpm"),
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
        self.events = deque(maxlen=100)
        self.received = self.malformed = self.ignored = self.seq = 0
        self.gps = None
        self.recorder = None
        self.controls = Controls(self)

    def ingest(self, can_id, data, extended=False, remote=False, error=False):
        now, stamp = self.clock(), int(self.wall() * 1000)
        self.received += 1
        raw_key = f"{'err' if error else 'ext' if extended else 'std'}:{can_id:X}"
        self.raw[raw_key] = {"id": can_id, "data": data.hex().upper(), "dlc": len(data),
                             "extended": extended, "remote": remote, "error": error,
                             "timestamp_ms": stamp}
        self.raw.move_to_end(raw_key)
        while len(self.raw) > 256:
            self.raw.popitem(last=False)
        if extended or remote or error:
            self.ignored += 1
            return
        try:
            signals = decode(can_id, data)
        except ValueError as exc:
            self.malformed += 1
            self.status = str(exc)
            for (name, source), sample in self.samples.items():
                if source == can_id:
                    sample["quality"] = "fault"
            return
        for name, signal in signals.items():
            self.samples[name, can_id] = {"value": signal.value, "quality": signal.quality,
                                         "source_id": can_id, "timestamp_ms": stamp,
                                         "seen": now}
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
            if source not in EVENT_IDS and (not self.connected or age > TIMEOUTS.get(source, .5)):
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
            values[name] = dict(missing)
        boost = values.get("engine.boost_kpa")
        map_value, baro = values.get("ecu.map_kpa", missing), values.get("ecu.baro_kpa", missing)
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
        modules = {}
        for name, source in (("taillights", 0x100), ("comfort", 0x200), ("watermeth", 0x300), ("knock", 0x307)):
            matching = [v for v in values.values() if v["source_id"] == source]
            modules[name] = "live" if any(v["quality"] == "live" for v in matching) else "stale" if matching else "unavailable"
        return {"type": "state", "seq": self.seq, "timestamp_ms": int(self.wall() * 1000),
                "mode": self.mode, "values": values, "modules": modules,
                "transport": {"connected": self.connected, "status": self.status,
                              "received": self.received, "malformed": self.malformed, "ignored": self.ignored},
                "gps": {"status": self.gps.status, "tx_status": self.gps.tx_status,
                        "tx_count": self.gps.tx_count, "conflict": self.gps.conflict} if self.gps else None,
                "controls": self.controls.status(), "events": list(self.events),
                "recording": dict(self.recorder.status) if self.recorder else {"enabled": False, "state": "disabled"}}
