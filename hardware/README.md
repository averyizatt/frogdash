# hardware/

The Raspberry Pi implementation is now here. See the
[CAN and USB GPS setup guide](../docs/can-integration.md).

- `frogdash/`: Python state service, SocketCAN decoder, gpsd USB receiver,
  GPS CAN broadcast, local WebSocket API, health endpoint, replay adapter, and
  [rotating binary MLG recorder](../docs/data-logging.md).
- `ui/`: production dashboard, quality indicators, knock monitor, CAN inspector,
  and water/meth/knock/lighting controls.
- `systemd/`: daemon and graphical-session kiosk service templates.
- `compat/`: CCM patches to transfer GPS and engine-control ownership to the Pi.

Run `python -m hardware.frogdash.server --interface can0 --gpsd` from the repo
root after installation. GPIO, fuel-level sensing, power control, and physical
CAN adapter setup remain hardware-specific integration work.
