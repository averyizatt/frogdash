# Presets and the system profile

Frogdash was built in one car, a Fox body Mustang. Since version 1.2 everything that is
particular to a car is kept in one file on the Pi, the **system profile**. The rest of
Frogdash reads it, so another car can use the same code.

## The system profile

`/etc/frogdash/system.json` says what this car has:

| Field | What it means |
|---|---|
| `preset` | The preset the profile starts from (below) |
| `configured` | The car's choices have been made (the setup wizard, from 1.3, sets it) |
| `interface` | The Linux CAN interface (`can0`) |
| `ecu.profile`, `ecu.bitrate` | The engine computer on the bus (`megasquirt` until 1.4 adds others) and the bus speed |
| `can_hat.present`, `.oscillator`, `.interrupt`, `.spi_hz` | The MCP2515 CAN board: there or not, its crystal (12000000 for the Waveshare RS485 CAN HAT, 8000000 for the common blue boards), its interrupt pin, its SPI clock |
| `gps.enabled`, `.transmit_on_can` | A USB GPS receiver (gpsd), and whether its position is also sent on the bus as 0x203 (for the comfort module) |
| `recording` | Drive recordings (MLG logs) |
| `camera.enabled`, `.rotate` | Reverse camera on the Pi's camera connector |
| `dashcam.enabled` | Wi-Fi dash cam view |
| `power` | `pisugar3` or `none` |
| `modules.gateway`, `.taillights`, `.watermeth` | The Frogdash modules on the bus |
| `tunerstudio` | TunerStudio on the dash screen |
| `terminal` | The Terminal tab, with sudo |
| `locale.timezone`, `.wifi_country` | Empty: the Pi keeps its own |
| `hotspot_name` | The dash's own Wi-Fi network for the phone page |
| `uploads.repo` | The GitHub repository reports and drives go to (`owner/name`); empty, none |
| `screen.mode` | `auto` (the screen's own) or `1920x720` (forced, for the foxbody car's panel) |
| `extra_args` | Further dash options, one word each (for example `--log-hz`, `50`) |

The file keeps only the preset's name and what differs from the preset. A change to the
preset in the repository therefore reaches every car on it at its next update, while a
choice made on the Pi stays as it was made.

`tools/frogdash_setup.sh` (run after every update) reads the profile:

- the dash's options (`FROGDASH_ARGS`) are made from it (step *Dash options*);
- each part is installed or left out to match: the CAN board's line in `config.txt`,
  gpsd and the clock from GPS, TunerStudio, the 1920 × 720 screen mode, each module's
  firmware file, the time zone, the Wi-Fi country and the hotspot's name;
- nothing it does not have is sent onto the bus: no 0x203 GPS without `gps.transmit_on_can`,
  no 0x309 engine RPM without the water/meth module.

Parts are not uninstalled when switched off; they are left unused.

`hardware/frogdash/sysconfig.py` holds the checks: a profile with a field that is wrong
is not used (System check names the field), and the last good values stay in force.
Next to it, `system.env` holds the same values for the setup script.

## Presets

In `presets/`:

- **`generic`**: a new car. A CAN board (12 MHz, interrupt 25) and drive recordings; no
  GPS, modules, PiSugar, Terminal or uploads; the screen's own mode; the Pi's own time
  zone. The dash's Setup (1.3) fills in the rest.
- **`foxbody`**: the car Frogdash was built in, exactly as it ran before profiles: the
  Waveshare RS485 CAN HAT, a USB GPS also sent on the bus, the gateway, taillights and
  water/meth modules, a PiSugar 3, the Terminal, America/Denver, the "Foxbody Dash"
  hotspot, reports to averyizatt/frogdash and the 1920 × 720 panel.

The installer writes the profile (`--preset`, `--oscillator`, `--interrupt`,
`--no-pisugar`; see [fresh-install.md](fresh-install.md)). A Pi installed before profiles
gets one from the `foxbody` preset at its first update to 1.2, with the options it ran.

From the command line on the Pi:

```sh
cd /opt/frogdash
.venv/bin/python -m hardware.frogdash.sysconfig get gps.enabled
.venv/bin/python -m hardware.frogdash.sysconfig args        # The dash's options from it
```
