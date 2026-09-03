# Phase 2 — UI and connection layer

Phase 2 turns the approved browser design into the production dashboard for Avery's
Raspberry Pi 4. This phase is deliberately limited to the UI and the local data
connection that feeds it.

Power control, automotive shutdown, wiring, GPS hardware, GPIO hardware, and CAN
interface selection are outside this plan. The existing auto-shutdown script will
be integrated later through a documented service boundary; it will not be replaced.

## Target architecture

- **Computer:** existing Raspberry Pi 4 running Raspberry Pi OS 64-bit.
- **UI:** lightweight HTML, CSS, and JavaScript in Chromium kiosk mode at 1920×720.
- **State service:** a small Python process owns current vehicle state, timestamps,
  source health, and stale-data detection.
- **UI connection:** one local WebSocket endpoint sends a complete snapshot on
  connect, then small state updates as values change.
- **Input adapters:** simulator/replay first, SocketCAN next. Both produce the same
  normalized state so the UI never parses raw CAN frames.

```text
simulator / CAN replay / SocketCAN
                 │
                 v
       Python state service
       - decode and normalize
       - timestamps and quality
       - stale-data detection
                 │
       ws://127.0.0.1:<port>/state
                 │
                 v
        Chromium dashboard UI
```

Keeping CAN decoding outside the browser means the same UI works with simulated,
recorded, and live data. It also keeps the Pi 4 workload predictable and lets the
dashboard reconnect without reloading Chromium.

## UI connection contract

Every update carries a monotonic sequence number and source timestamp. Values use
display-independent units; formatting and unit labels remain UI concerns.

```json
{
  "type": "state",
  "seq": 1842,
  "timestamp_ms": 1788472800123,
  "values": {
    "engine.rpm": { "value": 3450, "quality": "live" },
    "vehicle.speed_mph": { "value": 47, "quality": "live" },
    "knock.energy": { "value": 20, "quality": "live" },
    "knock.baseline": { "value": 15, "quality": "live" },
    "knock.threshold": { "value": 180, "quality": "live" }
  }
}
```

Quality is one of `live`, `stale`, `unavailable`, or `fault`. The UI must never
leave an old number looking live. On disconnect it keeps the last snapshot only
long enough to show the transition, marks affected values stale, and retries with
bounded backoff. Reconnection always starts with a fresh full snapshot.

The UI is read-only in this phase. Simulator controls stay confined to the preview
and are not shipped in kiosk mode.

## Work packages

### 2A — Finish and freeze the UI

1. Complete the remaining visual review, including the knock monitor.
2. Define responsive behavior for the 1920×720 target and smaller development
   viewports.
3. Add explicit loading, disconnected, stale, and fault states.
4. Measure animation smoothness and CPU usage with Chromium on a Pi 4.

**Exit criterion:** the approved dashboard is visually stable, touch controls work,
and no simulated value can be mistaken for a live source.

### 2B — Normalized state and WebSocket service

1. Define the state field names, units, types, timestamps, quality, and stale limits.
2. Implement the local WebSocket snapshot/update protocol.
3. Move simulation into a service adapter instead of generating it in the UI.
4. Add deterministic replay fixtures for UI development and regression tests.
5. Add SocketCAN decoding behind the same adapter interface.

**Exit criterion:** switching between simulator, replay, and live SocketCAN requires
no UI code changes.

### 2C — Bind and package the production UI

1. Bind every dashboard component to the normalized state client.
2. Add reconnect handling, stale transitions, and visible source health.
3. Package the state service and Chromium kiosk launcher as supervised services.
4. Keep logs bounded and expose a simple local health endpoint.
5. Provide a hook for the existing auto-shutdown script to stop the services cleanly.

**Exit criterion:** service restarts and data-source loss recover without manual UI
reload, and the existing shutdown workflow can stop Frogdash cleanly.

### 2D — Pi 4 validation

1. Verify the exact display timing, scaling, touch input, and kiosk startup.
2. Measure boot-to-dashboard time, frame rate, CPU temperature, memory, and Chromium
   stability on the Pi 4.
3. Run a 12-hour simulator/replay soak test.
4. Test state-service restart, WebSocket disconnect, stale data, and clean shutdown.

**Exit criterion:** the Pi 4 holds the target frame rate without UI lockups or
unbounded memory/log growth and recovers from every tested connection failure.

## Immediate sequence

1. Approve the revised knock monitor and freeze the remaining visual design.
2. Define the normalized state schema.
3. Build the WebSocket service with simulator and replay adapters.
4. Replace browser-owned simulation with the WebSocket client.
5. Validate and tune the result on the Pi 4.
