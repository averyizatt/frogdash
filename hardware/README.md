# hardware/

This folder will hold the Raspberry Pi implementation described in
[`docs/phase-2-plan.md`](../docs/phase-2-plan.md):

- Production web UI in Chromium kiosk mode
- Python state service and local WebSocket API
- SocketCAN readers and frame decoders
- `libgpiod` input handler for protected physical buttons
- `gpsd` receiver
- systemd services, health reporting, replay tools, and tests

Implementation starts with a desktop `vcan0` replay service; hardware selection and
vehicle wiring are deliberately deferred until the interfaces are confirmed.
