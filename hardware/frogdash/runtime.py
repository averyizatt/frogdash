"""Engine runtime (0x309) for the water/meth controller, sent by the dash.

The comfort module's dashboard firmware used to publish 0x309 (RPM) every 50 ms;
its sensor-gateway build does not. The water/meth Nano needs it to arm knock
detection above its minimum RPM. The dash takes over with the same payload the
CCM sent: RPM little-endian, MAP 0 and valid bit 0 only while RPM is fresh and
above zero. Only one node may publish 0x309, so the dash listens first and
latches off for this run if any other sender appears (RAW_RECV_OWN_MSGS is off,
so every received 0x309 came from another node).
"""
from .protocol import TIMEOUTS

ID = 0x309
INTERVAL = .05
LISTEN = 2.0
RPM_SOURCES = ('ecu.rpm', 'tach.rpm', 'gateway.rpm')


class EngineRuntime:
    def __init__(self, state, enabled=True):
        self.state, self.enabled = state, enabled
        self.conflict = False
        self.started = None
        self.next_tx = 0.0
        self.tx_count = 0
        self.status = 'disabled' if not enabled else 'listening for another 0x309 sender'

    def observe(self, can_id):
        if can_id == ID and self.enabled and not self.conflict:
            self.conflict = True
            self.status = 'BLOCKED: another node publishes 0x309 (CCM dashboard firmware?); dash runtime TX off until restart'

    def rpm(self):
        """Freshest live RPM from the ECU, tach frame or sensor gateway, else None."""
        best = None
        for name in RPM_SOURCES:
            for (signal, _source), sample in self.state.samples.items():
                if signal != name or sample['quality'] != 'live':
                    continue
                if self.state.clock() - sample['seen'] > TIMEOUTS.get(sample['source_id'], .5):
                    continue
                if best is None or sample['seen'] > best['seen']:
                    best = sample
        return None if best is None else max(0, min(0xFFFF, int(round(best['value']))))

    def frame(self):
        rpm = self.rpm()
        valid = 1 if rpm else 0
        rpm = rpm or 0
        return bytes([rpm & 0xFF, rpm >> 8, 0, valid])

    def due(self, now):
        """True when a frame should be sent now; handles the initial listening window."""
        if not self.enabled or self.conflict:
            return False
        if self.started is None:
            self.started = now
        if now - self.started < LISTEN or now < self.next_tx:
            return False
        self.next_tx = now + INTERVAL
        return True

    def sent(self, ok, error=None):
        if ok:
            self.tx_count += 1
            self.status = 'publishing 0x309 engine RPM every 50 ms'
        else:
            self.status = f'0x309 not sent: {error or "TX timeout"} (no other node ACKing?)'

    def reset(self):
        self.started = None
        if not self.conflict and self.enabled:
            self.status = 'listening for another 0x309 sender'

    def snapshot(self):
        return {'enabled': self.enabled, 'conflict': self.conflict, 'tx_count': self.tx_count, 'status': self.status}
