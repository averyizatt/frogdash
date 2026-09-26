# Vehicle controls

Open **CONTROLS** on the production dashboard, or tap the water/meth tile.
The original browser preview remains simulated. Replay never transmits commands.

## Water/meth

- **ARM / DISARM**: command the Nano's boost-only injection mode. The state pill
  and pump duty continue to show received telemetry, not an optimistic prediction.
- **CLEAR FAULTS**: ask the controller to clear its latches. Persistent underlying
  faults may remain or return; the dashboard does not erase them locally.
- **APPLY BOOST START**: set the start threshold in **gauge kPa**, 0–250, while
  disarmed. The Nano's `0x301/0x04` command uses gauge pressure even though its
  separate `0x304` configuration frame uses a pressure reference differently.
- **RUN 3-SECOND TEST**: run the selected 1–100% duty while disarmed, with fresh
  module telemetry, no meth faults, and tank above 10%. STOP TEST stays available
  even while another command is pending. There is a three-second cooldown.

Tests send stop on the service's three-second deadline, stale module telemetry,
reported fault, CCM configuration conflict, browser disconnect, panel close,
page hide, or service shutdown. A missing test acknowledgement also triggers a
stop attempt. If CAN itself has failed, the Pi cannot deliver STOP; the Nano's
existing five-second maximum/manual-test failsafe remains the hardware backstop.
Normal armed injection is **not** automatically disarmed when the browser closes.

Mixture ratio, IAT threshold, and maximum injection duty are not exposed by this
panel: they do not have matching implemented direct commands in the pinned Nano
firmware. The header declares an IAT command that the actual receiver does not
implement. This UI does not invent that functionality or broadcast guessed
configuration defaults. Settings here are runtime changes, not guaranteed EEPROM
persistence. The requested boost input is not a live settings readback.

## Transfer control from the CCM

The CCM currently sends `0x304` periodically, which can re-arm/disarm the Nano and
overwrite its boost trigger. Frogdash waits three seconds after CAN attachment
to inspect ownership. Recent `0x304` traffic blocks meth arm/test/tuning/clear
commands and explains the conflict in the panel. Explicit DISARM and STOP can
still be sent, but a continuing CCM broadcast can undo DISARM.

Apply the supplied compatibility patch in the **DIYComfortControlModule** repo:

```sh
git apply --check /path/to/frogdash/hardware/compat/comfort-disable-meth-control.patch
git apply /path/to/frogdash/hardware/compat/comfort-disable-meth-control.patch
```

Add `-DCCM_CAN_METH_CONTROL_ENABLED=0` to that firmware environment's PlatformIO
build flags, rebuild, and flash. This prevents the CCM's CAN send path from
transmitting engine commands (`0x301`, including knock) or meth config (`0x304`).
CCM heartbeat, engine runtime, and telemetry reception continue. The flag defaults
to 1 so merely applying the patch preserves the original CCM behavior. The GPS
ownership patch is separate and can be applied alongside this one.

Once those broadcasts stop, controls become available after the observation
window expires. Use Frogdash as the single engine-control UI; CAN schema 2 has
no sender identity or transaction ID for these commands. No remote repository
was changed or firmware flashed by this implementation.

## Knock and lighting

Knock controls support enable/disable, threshold offset (0–200), adaptive
multiplier (encoded as ×10, 12–38), clearing events, and requesting current
configuration pages. The panel displays actual readback separately from requested
input values. Enabling/disabling this setting changes the Nano's knock monitor.

Taillight controls support brightness 0–255 and STOCK/SEQUENTIAL modes through
`0x101`. Brake/turn/running/reverse inputs keep their firmware-defined behavior.
The taillight protocol provides **no command ACK or mode readback**: the UI says
SENT, never confirmed. Applied brightness can differ from requested brightness
because of module dimming/thermal behavior. Show/demo/override animations are
not exposed in this driving dashboard.

## Command results and limits

The local, same-origin WebSocket accepts named actions, not arbitrary CAN frames.
The service validates integer ranges, source freshness, ownership and pump-test
conditions; bounds concurrent requests; and serializes socket writes. Stop/disarm
preempts a pending control request. Commands are never replayed after reconnect
or automatically retried. Per-connection request IDs prevent duplicate submissions.

For `0x301` commands, `0x30A` schema-2 replies must match the command and, for
successful ACKs, the applied value. Results are ACKNOWLEDGED, REJECTED, ADJUSTED,
or UNKNOWN after timeout/disconnection. An ACK means the command was accepted;
only fresh telemetry describes the actual resulting module state. A command from
another CAN controller during the wait makes attribution UNKNOWN. The wire
protocol cannot perfectly distinguish delayed replies to identical commands;
the service serializes requests and applies a brief reply quiet period.

Only one control surface should write a given module. The 3-second ownership
observation is a duplicate-writer guard, not a bus ownership negotiation protocol.
Physical Pi/CAN/pump validation is still required; desktop tests use simulated
transport and controller replies.
