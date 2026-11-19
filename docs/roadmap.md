# Roadmap: setting Frogdash up without writing code

Frogdash should be set up for any car from its own screen, the way the setup wizard and the
custom ECU editor already are, with no code and no files edited by hand. This list is what
is planned for that, roughly in the order it helps the most people. Done items move to the
[changelog](../CHANGELOG.md).

## Done (unreleased)

1. **Screen editor.** Any reading on any gauge or tile, including a custom ECU profile's own
   readings and the analog sensors below, with its own name, range, decimals and warning
   zones (low and high), set by pressing and holding the gauge.
2. **Alert builder.** An alert on any reading: above or below a limit, for how long,
   only with the engine running, warning or critical. Shown and acknowledged like the
   built-in ones (Alerts tab), and logged.
3. **Analog sensors.** The ADS1115's four inputs for more than the fuel level: 0.5–4.5 V
   pressure senders, thermistor temperature senders (coolant, oil, transmission) and any
   sensor with a straight-line output, calibrated with two measured points or chosen from
   a list of common senders. Each feeds a dash reading (oil pressure, oil temperature…) or
   a reading of its own name.

## Next

4. **Factory CAN for modern cars.** Pick the make and model and get speed, wheel buttons,
   doors and lights from the car's own CAN bus, without Frogdash's boards (from opendbc,
   MIT licensed, where it has the car).
5. **Calculated readings.** Gear from speed and RPM, boost from MAP and barometric
   pressure, fuel economy, a difference or ratio of two readings: built from menus.
6. **Buttons and outputs.** Any CAN bit or Pi pin runs a dash action (next screen, mark the
   log, mute alerts); the dash drives a shift light or a pin from an RPM, a temperature or
   an alert.
7. **One-file sharing.** The whole setup (wizard choices, ECU profile, screens, alerts,
   sensors) saved as one file, to keep, restore or share for the same car or ECU.
8. **More from the custom ECU editor.**
   - Multiplexed frames: one ID carrying several pages, picked by a byte.
   - Value names: 0–3 shown as P/R/N/D, status codes as words.
   - ECUs that must be asked: periodic request frames, beyond OBD-II.

## Also planned

- Water/meth with ECUs other than MegaSquirt: the dash forwards MAP to the board (0x309),
  with a small change to the board's firmware.
- More ECU profiles: Link (with its CAN document), Emtron, Syvecs, and the rest of Haltech's,
  AEM's and FuelTech's data streams.
- Each built-in ECU profile proven on a real car (a CAN recording from one).
