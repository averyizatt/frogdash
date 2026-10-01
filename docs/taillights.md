# Taillight studio

Open **Controls → Lighting → Open taillights**. Everything here is sent over CAN to
the [CustomTaillights](https://github.com/averyizatt/CustomTaillights/tree/dd4d971b47a7e4aee9d07c7801daaec4579f19e2)
controller on ID `0x101`; the controller sends no command acknowledgement, so the
live states come from its `0x100` telemetry.

| Section | What it does | When |
| --- | --- | --- |
| **Mode** | Stock or Sequential turn signals; brightness 0–255 | Anytime |
| **Shows** | 33 show animations (Rainbow … Glitch), or **Demo**, which cycles them every 5 s | Parked only |
| **Test & effects** | Force each side to Off/Running/Brake/Turn/Reverse/Brake + turn/Hazard; one-shot **Brake check** scroll, **Amber flash**, or scroll two characters | Parked only |
| **Normal lights** | Ends any show, demo, test or one-shot | Anytime |

The firmware has 36 shows; CAN can select the first 33 (0–32). Afterburner, Tunnel
and Apex Weave are only available from the taillight's own Wi-Fi page.

## Safety

The taillight firmware never lets a show, test or one-shot suppress a physical
**brake** or **reverse** signal. It does replace the **turn signals** while one is
running. So:

- Shows, demo, tests and one-shots are refused unless the car is parked (fresh GPS
  speed under 1 km/h, or engine-off RPM). The backend enforces this, not just the screen.
- If the car moves faster than 5 km/h for one second while any of them is active,
  the backend sends **Normal lights** automatically. This also covers a show that
  was started from the taillight's Wi-Fi page (reported as SHOW). Missing speed
  data counts as moving. Stock/Sequential and brightness are never blocked.

## Settings over CAN

Needs the CustomTaillights PCB firmware with the CAN settings extension
(`can_protocol.h` extension 3: subcommands 0x06-0x09 on 0x101, reports on 0x103).
Three tabs in the taillight studio:

- **Style:** brake, turn, reverse and running animations; taillight style (lens
  preset); simple or custom turn timing; startup animation; rest mode; and the
  scrolling text used by text shows.
- **Colors & timing:** brake, turn, reverse and running colors; saved brightness;
  running light level; blink, sweep, hold and off times; animation and show
  speeds; frame time.
- **Profiles:** save to the taillights, undo unsaved changes, factory defaults
  (press twice), and six profile slots to load, save or delete (delete needs a
  second press).

Every field shows the value the controller reports, refreshed whenever its
settings revision changes, so it always reflects what the lamps will do. Changes
apply immediately; **Save** writes them to the controller's flash, otherwise they are
lost at power off. Older firmware without the extension leaves these tabs disabled.

## Live mirror

The left of the screen draws both lamps LED by LED: the clear 21×5 top strip in
full color, and the red-lens 21×5 strip and 17×10 panel in red, which is all their
lenses pass. It follows each side's reported state (running, brake, turn, hazard,
reverse, show) and plays frames **recorded from the actual firmware animation code**:

- `tools/taillight_recorder/` compiles the unmodified CustomTaillights animation
  sources against FastLED 3.10.3 (the controller's version) on a normal computer
  with a simulated clock, records every show and state at 20 fps, and writes
  `hardware/ui/taillights/frames.bin` (about 410 KB compressed). Re-run it after
  changing the taillight firmware:
  `python tools/taillight_recorder/build.py`, then `python tools/update_preview.py`.
  It needs git and g++ (MSYS2 on Windows).
- Patterns and timing are the firmware's own. Limits: CAN does not report which
  show is running or its phase, so the mirror starts its copy when the state
  changes and can drift from the lamps over time; colors use the firmware
  defaults, not changes made on the Wi-Fi page; effects using the controller's
  hardware random source (sparkle, lightning timing) will not match flash for flash;
  a show started from the Wi-Fi page is drawn as Rainbow and labeled as such.
- The lamps are drawn with turn sweeps running outward from the car's centre, as
  recorded. If yours physically run the other way, flip the `col` line in
  `hardware/ui/taillights.js` (`paint()`).

An exact live mirror would need the controller to stream its LED buffer (for
example over Wi-Fi to the Pi); CAN cannot carry 760 LEDs at animation speed.
