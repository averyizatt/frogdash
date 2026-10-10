# CAN compatibility and commissioning

Audited on 2026-09-27 against the current project revisions listed in
[CAN integration](can-integration.md#imported-wire-definitions) and pinned in
[`sources.json`](../hardware/can_contract/sources.json). The shared CCM and
taillight schema-2 headers are identical. Water/meth includes that same shared
contract; its actual Nano command handlers were checked as well.

## Bus and message ownership

All modules use classical CAN, standard 11-bit IDs, at 500 kbit/s. Linux SocketCAN
and the [MCP2515 setup](mcp2515.md) provide the Pi transport. IDs below are hex.

| Publisher | IDs | Purpose |
| --- | --- | --- |
| Taillights | 100, 102 | Left/right state and inputs, brightness, thermal status, fault events |
| CCM dashboard firmware | 200, 202, 309 | Heartbeat, tach status, RPM runtime for the Nano |
| CCM sensor-gateway firmware | 202, 500, 501, 503 | Tach status, speed/RPM/fuel, cruise buttons, interior light state |
| Dash (Pi), when no other sender | 309 | RPM runtime for the Nano, from MicroSquirt, tach or gateway RPM |
| Dash (Pi) | 502 | Interior light commands to the sensor gateway |
| Dash (Pi) | 680 | Firmware update commands and image data for a named module ([firmware-updates.md](firmware-updates.md), additive) |
| Sensor gateway, taillight controller | 681 | Firmware build and update acknowledgements, each naming itself (additive) |
| CCM or Pi, one owner | 203 | GPS speed, altitude, satellites and validity |
| External fuel controller | 204 | Fuel percentage and validity, new additive contract |
| CCM wheel input task | 205 | Five debounced button levels and report sequence, new additive contract |
| Water/meth Nano | 300, 302, 303, 306, 307, 308, 30A-30D | Meth, sensors, knock, configuration replies and acknowledgements |
| Water/meth Nano | 30F | Pulse tuning status, settings and intake air temperatures (extension 4, additive) |
| Configuration requester | 305 | Meth configuration request |
| Control owner | 101, 301 | Lighting and meth/knock commands |
| CCM unless control ownership transferred | 304 | Meth configuration broadcast with XOR checksum |
| MicroSquirt | 5E8-5EB | Simplified dash data supported on MS2 |
| MicroSquirt | 5F0 + group, or 700 + group | Supported realtime data groups |

The actual CCM sends heartbeat every 250 ms, tach/runtime every 50 ms and GPS
every 500 ms. Only one node should publish each state or own actuator control.
When moving GPS to the Pi, apply `comfort-disable-gps-tx.patch` and set
`CCM_CAN_GPS_TX_ENABLED=0`. When moving meth/knock control to the Pi, apply
`comfort-disable-meth-control.patch` and set `CCM_CAN_METH_CONTROL_ENABLED=0`.
Both patches are in `hardware/compat/`; rebuild and flash the CCM afterward.
The Nano consumes 309 to arm knock detection above its minimum RPM. With the CCM
dashboard firmware, keep its runtime transmission enabled and start the dash with
`--no-engine-runtime`. With the sensor-gateway firmware (which sends no 309), the
dash publishes it every 50 ms after listening 2 s for another sender; if one
appears it stops for that run and Sensors → Connection details shows BLOCKED. The GPS patch
only disables CCM transmission; it does not add an external-GPS display to CCM.
Frogdash's duplicate-GPS-owner detection blocks its GPS TX until the conflict
is resolved and the service restarted. See [controls](controls.md) for command
gates, confirmations, acknowledgements and pump-test timeout behavior.

## MicroSquirt with both broadcasts enabled

The target is MS2/Extra 3.4.x, including the current official
[3.4.4 release](https://www.msextra.com/downloads/ms2-extra-3-4-4-release/).
Your exact installed version has not been read from the ECU. In TunerStudio,
check CAN-Bus/Testmodes settings against the official
[broadcast specification](https://www.msextra.com/doc/pdf/Megasquirt_CAN_Broadcast.pdf):

- Enable CAN and Dash Broadcasting. Automatic dash mode uses decimal 1512
  (0x5E8) at 20 Hz on MS2.
- Keep Realtime Broadcasting enabled. Frogdash accepts the default decimal
  1520 (0x5F0) and CCM's alternate decimal 1792 (0x700) base. Match the base
  already selected for CCM; the ECU transmits one configured realtime base.
- Enable desired groups at 10-20 Hz for live display/logging. Groups 0-11
  cover the main engine channels, pulse widths, corrections and status.
  Additional decoded MS2 fields are in groups 12-15, 17-18, 26-29 and 43.
  Only enable groups that your firmware exposes and your setup needs.
- A CAN node number is not the broadcast arbitration ID. Do not change it to
  1512, 1520 or 1792. These are message base identifiers.

Both broadcast streams feed the same normalized engine channels. The newest
live source wins, with per-frame expiry; unrelated traffic cannot keep old
engine readings live. Unsupported fields/groups remain raw or unavailable.
MS3-only VSS/EGT fields are not interpreted as MicroSquirt measurements.
TunerStudio serial packets and 29-bit tuning/passthrough requests are different
protocols; Frogdash does not write ECU tuning parameters.

The audit corrected status5 to a signed 16-bit word at bytes 4-5, preserving
status6/7 at bytes 6/7, and corrected dwell to unsigned 16-bit. These fix errors
also present in the pinned CCM decoder; that upstream decoder is not modified
here. Added channels include injection-event flags, correction factors, rate
of change, wall fuel, sequential pulse widths and sync-loss diagnostics.
They appear in CAN/SENSORS and schema-7 MLG logs with their quality fields.
Batch-fire fuel estimates continue using main bank pulse widths and the saved
injector calibration; adding sequential channels does not change that model.

Generic sensors use the 2016 specification's divide-by-10 scaling (also used
by CCM); an older official DBC lists a conflicting factor. Their physical
meaning still depends on ECU configuration. Idle output is deliberately raw
because its units depend on PWM versus stepper configuration. MAF uses the
specification's 650 g/s range scaling; verify ECU MAF range before interpreting
that optional channel. Sync-loss count is the transmitted byte, not a lifetime
counter. None of these optional fields creates a new safety warning by itself.

## New features in the shared contract

The [exportable firmware header](../hardware/can_contract/README.md) includes
fuel ID 204, DLC 3, every 500 ms: big-endian percentage times ten and a validity
enum. It also includes a builder for the existing GPS payload. The old schema-2
ACK version remains 2, so existing modules remain compatible. Apply
`comfort-fuel-contract.patch` to add these definitions to CCM's shared header,
or copy the exported header into the external controller project. Definitions
alone do not implement measurement or transmission on that controller.

Fuel feeds the gauge, trip inventory/range and recordings; GPS feeds speed,
trips and race timing; taillight inputs feed brake/turn/running/reverse indicators
and night dimming. Alerts and speaker chimes consume normalized readings.
Themes, splash screens, Wi-Fi transfer and service reminders stay local to the
Pi and need no new CAN frames. Fuel pressure and meth tank state are separate
from fuel level. No Pi sender ADC or GPIO measurement is used.

## What has been verified

Automated tests compile the pinned shared C++ builders and compare their bytes
to the Python telemetry decoder, GPS transmitter and every supported dashboard
command. Regression tests cover MS2 word offsets, signedness, scaling, both
realtime bases, simultaneous dash/realtime reception and independent expiry.
The original header checksum is checked to prevent accidental contract drift.

Before driving, commission the installed firmware: check bitrate/termination,
compare RPM, temperatures, AFR, MAP and pulse widths to TunerStudio, verify
module inputs, exercise parked commands and ACKs, and test stale/fault recovery.
Check fuel empty/full/fault frames and GPS ownership after flashing the CCM.
These tests verify software layouts; physical bus/device operation remains to
be checked on the Pi. Ignition power now uses the separate
[PiSugar 3 Plus setup](pisugar-power.md), replacing the previous ACC/relay design.

[Steering-wheel navigation](steering-wheel.md) adds 0x205 in shared extension 2.
It requires integrating the new CCM button scan/transmit task; the old heartbeat
input flags are unchanged. New MLG recordings use schema 8 with wheel diagnostics.
