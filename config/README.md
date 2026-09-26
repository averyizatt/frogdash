# config/

`frogdash.env` configures the production systemd daemon. Copy it to
`/etc/default/frogdash`; see [setup](../docs/can-integration.md).

Future hardware-specific configuration may include:

- `display.yaml` — screen size, resolution, orientation, brightness curve
- `can.yaml` — CAN bus interface, bitrate, message IDs (e.g. OBD-II PIDs)
- `gpio.yaml` — pin assignments for buttons, indicators
- `gps.yaml` — serial port, baud rate, update rate
- `thresholds.yaml` — warning/critical thresholds for coolant, oil P, oil T, battery, AFR

CAN bitrate is currently configured through Linux (`ip link`); protocol IDs and
validated wire layouts live in `hardware/frogdash/protocol.py`.
