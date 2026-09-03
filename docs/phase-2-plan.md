# Phase 2 implementation plan

Phase 2 turns the approved 1920×720 browser design into a reliable Raspberry Pi
dashboard. It is a bench implementation phase; connecting it permanently to the
vehicle remains Phase 3.

## Recommended architecture

- **Computer:** Raspberry Pi 5 (4 GB is sufficient), Raspberry Pi OS Lite 64-bit.
- **Display:** native 1920×720 HDMI panel. Confirm the exact controller board and
  brightness input before buying the remaining hardware.
- **UI:** production web UI in Chromium kiosk mode. Rebuild the preview as
  production components; do not run the simulator as the vehicle dashboard.
- **Runtime:** Python service using SocketCAN, `gpsd`, and `libgpiod`. It owns the
  vehicle state model and publishes normalized updates to the UI over a local
  WebSocket.
- **CAN:** Linux SocketCAN at 500 kbit/s. Prefer an isolated CAN interface. The
  existing shared CAN contract is the source of truth for custom frames.
- **Power:** automotive-rated, fused 12 V to regulated 5 V supply with ignition
  sensing, load-dump/reverse-polarity protection, and controlled shutdown. Do not
  power the Pi directly from an accessory wire or a generic buck converter.
- **GPS:** USB or UART GNSS receiver exposed through `gpsd`.
- **Inputs:** protected momentary switches through GPIO. Vehicle 12 V signals must
  never connect directly to Pi GPIO.

## Data path

```text
CAN interface ── SocketCAN ──┐
GPS receiver ───── gpsd ─────┼─> state service ─> local WebSocket ─> kiosk UI
GPIO buttons ─── libgpiod ───┘         │
                                       └─> health/fault log
```

The UI is display-only by default. Commands that can change vehicle behavior need
an explicit allowlist, validation, rate limiting, and a separate confirmation path.

## Existing CAN contract

The current custom network uses standard 11-bit identifiers at 500 kbit/s. The
production runtime should vendor a pinned copy of the shared contract and test its
decoders against recorded frames. Frames already relevant to the dashboard include:

- `0x100` taillight state
- `0x200` master heartbeat
- `0x202` tach/RPM state
- `0x203` GPS state
- `0x300` water/meth state
- `0x302` water/meth fault
- `0x303` extended engine sensors
- `0x307` knock state
- `0x308` knock fault

OBD-II polling should be added only for values not available on the custom CAN
network. Its bus load and supported PIDs must be measured on the actual ECU before
it becomes a primary data source.

## Repository layout for Phase 2

```text
hardware/
  service/          Python state service and source adapters
  ui/               Production dashboard UI
  systemd/          Service and kiosk units
  tests/            Decoder, replay, stale-data, and UI tests
config/
  display.yaml
  can.yaml
  gpio.yaml
  gps.yaml
  thresholds.yaml
docs/
  phase-2-plan.md
  wiring/           Added after exact hardware is selected
```

## Work packages

### 2A — Contracts and desktop runtime

1. Define the normalized vehicle-state schema, units, timestamps, quality, and
   stale-data rules.
2. Add configuration schemas and validation.
3. Implement SocketCAN readers against `vcan0` and recorded CAN logs.
4. Implement the WebSocket state API and a deterministic simulator/replay source.
5. Add decoder tests for every supported frame and failure tests for malformed or
   stale data.

**Exit criterion:** the production UI runs on a development machine from replayed
CAN data with no simulator code in the UI.

### 2B — Production UI and kiosk

1. Rebuild the approved v0.2.10 layout as production components.
2. Bind every display value to the normalized state API.
3. Add source-loss states; never leave a stale value looking live.
4. Add day/night brightness control, startup splash, and clean reconnect behavior.
5. Package Chromium kiosk and the state service as systemd units with automatic
   restart and bounded logs.

**Exit criterion:** cold boot reaches the dashboard automatically, the UI recovers
from a service restart, and loss of CAN/GPS is visible within the configured timeout.

### 2C — Pi bench integration

1. Build the Pi OS image and pin package versions.
2. Validate the display's exact timing, rotation, touch behavior, and brightness.
3. Bring up isolated SocketCAN, then replay frames before attaching a live bench bus.
4. Integrate GPS and protected GPIO buttons.
5. Measure boot time, CPU/GPU temperature, memory, frame rate, and 12-hour stability.

**Exit criterion:** 12-hour bench run without UI lockups, uncontrolled restarts, or
unbounded logs; CAN and GPS disconnect/reconnect tests pass.

### 2D — Vehicle-ready package

1. Finalize the fused power/shutdown circuit and wiring diagram.
2. Make the root filesystem resilient to abrupt power loss where practical.
3. Add a read-only vehicle test mode and CAN logging procedure.
4. Document rollback, recovery, and safe-disable procedures.

**Exit criterion:** the bench package is ready for a separately approved Phase 3
vehicle installation. No permanent vehicle wiring is part of Phase 2.

## Decisions required before hardware purchase

- Exact display/controller board and its brightness-control interface
- Pi 5 versus an already-owned suitable Pi
- Isolated USB-CAN adapter versus an isolated Pi HAT
- Automotive power/shutdown controller
- GPS receiver and antenna placement
- Physical button count and functions
- Which ECU values require OBD-II versus the custom CAN network

## First implementation task

Start with **2A: normalized state schema plus a `vcan0` replay service**. It does not
require hardware, proves the production architecture, and prevents UI code from
becoming coupled to individual CAN frames.
