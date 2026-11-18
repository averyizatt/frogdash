# Changelog

Frogdash has one version number for the whole system: the dash on the Pi and the firmware
of the three modules on the CAN bus. A release has the same `VERSION` in all four
repositories and a `vX.Y` tag on each:

- [frogdash](https://github.com/averyizatt/frogdash): the dash
- [DIYComfortControlModule](https://github.com/averyizatt/DIYComfortControlModule): the sensor gateway and the shared CAN contract
- [CustomTaillights](https://github.com/averyizatt/CustomTaillights): the taillights
- [DIYWaterMethInjection](https://github.com/averyizatt/DIYWaterMethInjection): the ESP32 water/meth board

The dash's Software card and Support tab show the version the Pi runs. Each module's row
on the Firmware page shows the version it runs and the version available.

## Unreleased

- **Car signals for any car:** turn signals, brake, lights, reverse and fuel level can come
  from a Pi pin (through an optocoupler; turn signals stay on between flashes), an ADS1115
  (the fuel sender, averaged), any CAN frame's bit or byte, or the ECU's own reading, chosen
  per signal in the wizard ([docs/car-signals.md](docs/car-signals.md)). Setup installs
  python3-libgpiod or switches I2C on only when used.
- **Wizard, after the owner's review:** the screen page forces whichever size is picked (the
  screen helper now makes the EDID for any size; 1920 x 720 is byte for byte as before); the
  ECU page is a card per ECU with its logo (hardware/ui/ecu-logos) and a custom one
  (/etc/frogdash/ecu/custom.json), without test status; the CAN board is the Waveshare HAT or
  "Other"; GPS from USB, the CAN bus or none; the Frogdash modules page is gone; the tuning
  software offered follows the ECU (a Windows tuner on the dash can be chosen; installing it
  is not built yet and setup says so).
- **Setup wizard** on the dash's screen: nine pages from the preset to a review of the
  changes; Apply saves the system profile (the old one kept as a backup) and runs the Pi
  setup through the new root-owned `frogdash-config.path`. It opens by itself on a new
  install, from Dash management → Setup checklist at any time, and in the live preview
  with `?wizard` (the real presets and ECU profiles; nothing saved). The ECU page shows,
  for each profile, how many of its frames are on the bus now. Eleven pages: preset, screen
  (common sizes drawn with the dash fitted in), ECU, CAN board, GPS, cameras, modules, what the
  dash shows, power, place/units/network, review.
- **The dash shows what the car has:** the map and race timer can be switched off, and the
  knock monitor, water/meth panel and taillight controls are hidden in a car without that
  module. New profile fields `features`, `locale.units` and `screen.size`; the reference car
  keeps everything.
- **Gauges with any ECU:** an ECU that sends lambda shows on the AFR gauge as AFR (lambda ×
  14.7); oil and fuel pressure in kPa show in psi; oil temperature, fuel level and speed come
  from the ECU when no module gives them. Only where nothing else gives the reading live, so the
  reference car is unchanged.

## 1.2.1 (2026-11-17)

- **Fix:** the System check's bus-speed warning had a quote mark that stopped
  `selftest.py` from loading in 1.2. Install 1.2.1, not 1.2.

## 1.2 (2026-11-17)

Toward Frogdash in other cars: what a car has now lives in one file on the Pi.

### Project
- **MIT licence.** Frogdash is open source: anyone may use, change and build on it.
- **The README describes Frogdash as a dash for any car with an aftermarket ECU.** It
  covers what it works with today and what is coming, how body signals (turn, brake,
  fuel level) reach the dash, the Foxbody as the reference build with its parts list, and a
  step-by-step install guide for people new to Linux.

### ECU profiles
- **The engine computer is read through an ECU profile** (`hardware/frogdash/ecu/`): a JSON
  table of its frames and signals, read by one decoder. The rest of the dash only knows the
  normalised `ecu.*` values, so another ECU needs a profile, not code. The profile in use is
  the system profile's `ecu.profile`.
- **MegaSquirt / MicroSquirt is the first profile.** It is generated from the tables the DBC
  was built from, and a test proves it decodes every ID (dash broadcast and both realtime
  bases) exactly as the hand-written decoder did, to the last bit of every value.
- A profile is checked when loaded: layouts within the frame, CAN bit rates, 11 or 29-bit
  IDs, and no ID of the Frogdash modules. A bad one is not used. **System check** names the
  profile in use and any problem, and `/ecu/profiles` lists them all with their source
  document, how far each is checked, and its tuning software.
- **rusEFI** (verbose CAN broadcast): 70 signals from rusEFI's own DBC and firmware source
  (rusefi/rusefi bfde8f4), little-endian, at its movable base (0x200 by default; the system
  profile's `ecu.base_id`). Tested with frames packed as the firmware packs them; not yet in
  a car.
- **MaxxECU** (default CAN output protocol v1.3, 98 signals, checked against MaxxECU's own DBC),
  **ECUMaster EMU Black / PRO** (EMU CAN stream, 62 signals, from the EMU Black manual v1.4) and
  **Speeduino** (its Haltech-format broadcast, 24 signals, from its source). Each is tested with
  frames built from its document; none yet in a car. Pressures are given in kPa in every profile.
- **Haltech** Elite / Nexus (ECU Broadcast CAN Protocol v2.0, 113 signals) and **Holley** Terminator X /
  HP / Dominator and Sniper (Holley's CAN protocol rev 1 and its DBCs; 29-bit IDs carrying the ECU's
  serial, a float per channel, °F/psi/mph converted). Tested with frames built from the documents.
- **AEM Infinity** (AEMnet data stream from AEM's own document, 31 signals) and **FuelTech** FT500 /
  FT600 / FT550 / FT450 (FTCAN 2.0 simplified broadcast, 21 signals).
- **29-bit IDs and 1 Mbit/s buses:** profiles may use 29-bit IDs (only the ECU's 29-bit frames are
  read), floats, and an ID mask. The CAN bus runs at the system profile's `ecu.bitrate`
  (500 kbit/s unless set), and System check warns when it is not the ECU profile's.
- A profile only has to keep clear of the modules **this car has**: an ECU may use the IDs
  of modules that are not there, and its frames there never reach the modules' code.
- [docs/ecu-support.md](docs/ecu-support.md): how the dash is built, the profile format,
  adding an ECU, and the state of each ECU and its tuning software.

### Setup and install
- **The system profile.** `/etc/frogdash/system.json` says what this car has: the ECU, the
  CAN board, GPS, cameras, modules, power board, time zone, hotspot name and where reports
  go. It starts from a preset in `presets/`: `generic` for a new car, `foxbody` for this
  project's own car. The dash's options are made from it. It replaces the tracked
  `config/frogdash-options`, so a choice made on the Pi never blocks an update. See
  [docs/presets.md](docs/presets.md).
- **The car does not change.** At its first update a Pi installed before profiles gets one
  from the `foxbody` preset, with exactly the options it ran
  (`--interface can0 --gpsd --log-dir /var/lib/frogdash/logs --terminal`).
- **The Pi setup installs what the profile names and leaves out the rest:** the CAN
  board's line in `config.txt`, gpsd and the clock from GPS, TunerStudio, the forced
  1920 × 720 screen mode, each module's firmware file, the time zone, the Wi-Fi country
  and the hotspot's name. A car without the water/meth module gets no 0x309 frames, and
  one without GPS on the bus gets no 0x203.
- **The installer installs only the core** (Python, can-utils, the screen) and writes the
  profile: `--preset`, `--repo`, and `--oscillator`, `--interrupt` and `--no-pisugar`
  filling it in. Its `--check` does not count a part the profile does not have as a
  failure.
- **Reports go to the profile's repository** (`uploads.repo`). On the generic preset that
  is empty until chosen, and Connect GitHub says so.

### Dash
- **Water/meth black box: the supply voltage.** Each sample of a black box record now
  carries the MicroSquirt's battery voltage at that moment (column `ecu_battery_v`). The
  words end with the voltage at the end and the lowest, for example *MicroSquirt battery
  10.9 V at the end, lowest 10.9 V at the end*. The dash keeps the last minute of the
  ECU's reading and lines it up with the board's last heartbeat before it went quiet. This
  is the car's voltage at the ECU: it shows a dip the whole car saw (the pump starting on
  a weak battery), not a bad connection on the board's own feed. If the dash did not see
  the board go quiet, it adds no voltage rather than guessing one.

## 1.1 (2026-11-13)

Faster module updates over CAN, a check after each, and one version number.

**The first install of 1.1 on each module goes the old, slow way.** Only the board's new
firmware speaks the faster protocol, so the updates after that one are the fast ones.

### Firmware updates over CAN (all three modules and the dash)
- **Update protocol version 2.** The image goes in 8 KB blocks, each compressed on its
  own (images shrink to about 60–65%). The module answers once per block, not every few
  frames. A block with frames missing is answered with the first and last missing frame,
  and only those are sent again. Modules on version 1 still update the old way.
- **The modules read SPI faster.** The sensor gateway and the water/meth board now clock
  their MCP2515 at 8 MHz (it was 1 MHz). During an update the water/meth board polls its
  CAN module every 0.2 ms. The taillights were already at 10 MHz.
- **A check after each update.** Before the dash confirms a new build, it waits for the
  module's own messages to come back after its restart and stay fresh for 3 s (within
  20 s). The gateway's are 0x500; the taillights' are 0x100; the water/meth board's are
  0x300, 0x307 and 0x30F. A module that fails the check is not confirmed, so it rolls back
  to the build it had by itself.
- Expected update times after 1.1 is on a board: water/meth about 20–30 s (it was 2 min
  23 s), gateway about 15–25 s (56 s), taillights about 40–70 s (2 min 30 s).

### Versions
- **One version for the system**: a `VERSION` file and a `vX.Y` tag in all four
  repositories. The firmware builds write the version into their manifest. The dash shows
  "Version 1.1 (abc1234)" on the Software card, "Dash 1.1" on the Support tab, and each
  module as "1.1 (build …)". The event log's start message names the version. The
  updater's status and the uploaded reports carry the release.
- `tools/install_release.py` accepts a two-part version (1.1) as well as three (1.1.0).

## 1.0 (2026-11-13)

The system as it was in the car and checked on 2026-11-13. Earlier work had no release
numbers: the dash's `VERSION` said 0.4.0 and the modules went by build hash.

### Dash (Raspberry Pi, 1920 × 720 screen)
- Gauges and photo cluster skins (old-school Ferrari, Fox LCD, Saleen) with day and night
  pictures, live needles and lamps.
- The MicroSquirt over CAN (500 kbit/s, Waveshare RS485 CAN HAT, MCP2515 at 12 MHz).
- Alerts with codes and their own limits, including "not charging" and "charging voltage
  high" from the MicroSquirt's battery voltage. Warnings and the keyboard are kept out of
  the strip the steering column hides.
- Drive recordings named by their real start once the clock is set, uploaded with the
  diagnostics report. A log viewer in the style of MegaLogViewer: Graph, Scatter, Table,
  Data, Track and Summary.
- Updates from git with Update now. Pi setup steps run by the updater (no SSH). Dash
  options are kept in the repository. Wi-Fi on either adapter (wlan0 or wlan1).
- GitHub reports after each update, PiSugar 3 shutdown on power loss, GPS clock and
  speed, and a dash cam.
- Firmware updates for the modules over CAN, restarts of the modules from the dash, and
  the water/meth tuning page.

### Sensor gateway (DIYComfortControlModule)
- The shared CAN contract (`can_protocol.h`, `firmware_update.h`, `frogdash.dbc`) for the
  dash and every module, up to extension 9.
- Firmware updates over CAN, built and published by CI. Restart from the dash; its CAN
  recovers by itself; lost arbitration no longer pauses sending.

### Taillights (CustomTaillights)
- One headless PCB build with lighting settings over CAN (extension 3), Wi-Fi off.
- Firmware updates over CAN, restart from the dash, a start once more on settled power,
  an RTC watchdog, and running lights that ride through dropouts.

### Water/meth (DIYWaterMethInjection)
- **ESP32-S3 only.** The Nano build and the GPIO17 master relay are gone. The pump runs
  from a MOSFET on GPIO15.
- **Pulse drive.** The pump is fully on or fully off, in runs of at least 500 ms (or
  continuous), with a 0.4 s soft start from 5% on each run.
- **The nozzle's measured flow, about 160 ml/min, is the built-in figure** (its label says
  60). It came from the owner's 3 s test, about 8 g of water. The dose limit is the share
  of time on × that flow, capped by tank mix: water 10%, 18% meth 12%, 36% meth 15%,
  53% meth 18% of fuel.
- **Either intake air sensor input.** The board reads both and uses the one that is
  connected.
- **A status light** on the onboard LED: green armed and ready, blue spraying (brighter
  with duty), yellow when it cannot spray just now, flashing red when something needs
  fixing.
- **Hardened against freezes and crashes.** It recovers by itself and keeps a black box of
  the last 10 s, which it sends to the dash after a reset nobody asked for (extension 9).
- Knock detection is off for now.
