# Five-button steering-wheel navigation

Frogdash accepts debounced Up, Down, Left, Right and OK inputs from the CCM.
The default layout is a four-way pad with OK in the middle. GPIO wiring,
pull-ups and the physical switch scan belong to the CCM; the Pi only reads CAN.

## Using the dash

- Arrow buttons move the highlighted focus. On vertical menu tabs, Up/Down
  switches category and Right enters that category's controls. Horizontal tabs
  use Left/Right and Down. All visible enabled controls can be reached.
- Tap OK to open/select the highlighted button. With no current focus on the
  main dash, OK opens Controls. Arrows also reach Drive, Race, Appearance,
  Knock and Sensors from the main navigation bar.
- For a number, slider or dropdown, OK enters edit mode (dashed highlight).
  Arrows change the value; OK finishes editing. Changes dispatch the same
  input/change events as touch; explicit Apply/Save buttons still need selection.
- Hold OK for 0.8 seconds to go back: leave edit mode first, then close the top
  menu on the next hold. A long hold never also sends a short OK on release.
- Directional holds repeat after 0.45 seconds, then every 0.15 seconds. OK never
  repeats. Touch remains available and clears the wheel highlight/edit mode.

Arrow keys and Enter provide the same controls in the live dash and
[web preview](https://averyizatt.github.io/frogdash/). Escape goes back immediately.
Every control works from the wheel alone:

- **Text boxes** (splash title, service names, sensor search): OK opens an
  on-screen keyboard. Arrows move in two dimensions across the keys, OK types,
  and Shift, Space, Delete, Clear and Done sit on the bottom row. Hold OK to
  cancel and keep the previous text. Length limits still apply.
- **Color squares** (Color studio slots, night accent): OK opens a color picker
  with the 24-color spectrum and Hue, Saturation and Lightness sliders.
- **Files** (background and splash images, backup restore): OK lists files in
  the Pi's import folder, `/var/lib/frogdash/import`, filtered to what the control
  accepts. Copy files there over SSH or from a USB stick
  (`sudo cp picture.jpg /var/lib/frogdash/import/`). Loading one uses the same
  checks as a normal upload. PNG, JPEG, WebP and JSON up to 10 MB, plain names only.
- **Gauges**: gauges and readings on the main dash can be reached with the arrows;
  OK opens the same reading picker as press-and-hold.
- **Long number ranges** speed up while an arrow is held (×10, ×100, ×1000,
  scaled to the field), so values such as service distances stay reachable.

With a USB keyboard attached, typing into text boxes works directly as usual.
Selecting a control uses its existing action and validation; vehicle
commands and parked-only settings retain all existing gates. The wheel does not
send an actuator command directly from the backend.

## New CCM CAN message

Use standard 11-bit ID **0x205**, **500 kbit/s**, **DLC 3**:

| Byte | Meaning |
| --- | --- |
| 0 | Pressed levels: bit 0 Up, bit 1 Down, bit 2 Left, bit 3 Right, bit 4 OK; bits 5-7 zero |
| 1 | Rolling report sequence, unsigned byte, wraps 255 to 0 |
| 2 | Wheel-message version, exactly 1 |

Transmit immediately on every debounced press/release and every **50 ms** while
idle or held. Increment the sequence on **every report**, including idle.
Use active-high logical pressed bits regardless of the physical GPIO polarity.
Debounce switches on the CCM (typically a stable 20 ms); send levels, not clicks,
hold events or pre-repeated key actions. Example: idle `00 10 01`, OK down
`10 11 01`, OK released `00 12 01`. Hex values shown.

This message is distinct from the old heartbeat 0x200 input flags, whose
Up/Down/Enter/Back/Touch mapping remains unchanged. Do not put the new five-way
mask in that heartbeat or bind both sources to the same navigation action.
Only one CCM should publish 0x205. No acknowledgement or Pi reply is required.
Verify the ID is unused by any additional nodes on the installed bus.

The shared [C++ header](../hardware/can_contract/README.md) adds:

```cpp
// Within your CCM button scan/transmit task, using debounced levels:
static uint8_t wheelSequence = 0;
uint8_t pressed = 0;
if (upPressed)    pressed |= can_protocol::steering_button::UP;
if (downPressed)  pressed |= can_protocol::steering_button::DOWN;
if (leftPressed)  pressed |= can_protocol::steering_button::LEFT;
if (rightPressed) pressed |= can_protocol::steering_button::RIGHT;
if (okPressed)    pressed |= can_protocol::steering_button::OK;
auto frame = can_protocol::packSteeringButtons(pressed, wheelSequence++);
// Enqueue frame through the existing CCM CAN transmit task.
// Call this on each change and every STEERING_BUTTONS_TX_MS (50 ms).
```

These button variables and the transmit call must be connected to your CCM's
new input task; this repository cannot assign pins that have not been chosen.
The source firmware and flashed CCM are not modified automatically.

To install definitions, copy the current shared header or apply the combined
`hardware/compat/comfort-fuel-contract.patch` to the pinned original CCM header.
If you already applied the previous fuel-only extension from Frogdash a8c777e,
apply `hardware/compat/comfort-steering-contract.patch` instead. Do not apply both.
The extension version becomes 2; existing schema-2 ACKs and fuel/GPS formats
remain unchanged. GPIO scan/transmit integration and flashing are still required.

## Freshness and recovery

The backend captures each edge before WebSocket sampling, so quick taps between
screen refreshes survive. It keeps at most 32 recent navigation events; UI clients
consume each event ID once. Events older than 750 ms are discarded, and initial
connection/reload/reconnect skips existing history. Replay CAN logs never drive
navigation. Hidden browser windows consume no actions.

Input becomes unavailable after **350 ms** without a new sequence. Duplicate
reports cannot sustain a held button. Malformed messages, sequence restart,
disconnection and simultaneous button chords cancel the gesture. Release all
buttons before continuing; a held OK at startup cannot select anything. Missing
CAN never invents an OK release. A stuck direction cannot generate actuator clicks.

`wheel.buttons_mask` and `wheel.sequence` appear in Sensors and schema-8 MLG
logs. The WebSocket `wheel` object reports readiness and recent navigation events;
those events are for the UI, not an actuator API. The Pi does not claim exclusive
browser ownership: keep one active kiosk window connected to the vehicle.

Automated checks cover the C++ frame builder, decoder, edge/hold timing, sequence
wrap, stale/duplicate/invalid frames, replay exclusion and live browser navigation.
Bench-test the real switches, bounce, quick taps, long holds, CAN loss and CCM
restart before using the wheel as the main input device.
