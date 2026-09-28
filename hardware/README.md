# hardware/

The Raspberry Pi implementation is now here. See the
[CAN and USB GPS setup guide](../docs/can-integration.md).

- `frogdash/`: Python state service, SocketCAN decoder, gpsd USB receiver,
  GPS CAN broadcast, local WebSocket API, health endpoint, replay adapter, and
  [rotating binary MLG recorder](../docs/data-logging.md).
- `ui/`: production dashboard, quality indicators, knock monitor, CAN inspector,
  and water/meth/knock/lighting controls.
- `systemd/`: daemon, kiosk and PiSugar power service templates.
- `power/`: independent input-loss monitor and final UPS cutoff hook; follow
  the [PiSugar 3 Plus setup](../docs/pisugar-power.md) to replace the old ACC/relay.
- `compat/`: CCM patches to transfer GPS and engine-control ownership to the Pi.

Run `python -m hardware.frogdash.server --interface can0 --gpsd` from the repo
root after installation. Fuel sensing belongs to the external CAN controller.
Physical CAN, UPS wiring, shutdown cutoff and automatic restart need bench
commissioning with the actual hardware.
