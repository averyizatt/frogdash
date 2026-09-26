# Frogdash

A Raspberry Pi instrument cluster for a Foxbody Mustang, designed for a 1920 × 720, 12.3-inch display. Runs on Linux with SocketCAN, USB GPS through gpsd, and local vehicle controls.

**Start here:** [CAN + USB GPS installation](docs/can-integration.md) and [water/meth, knock, and lighting controls](docs/controls.md). Desktop tests cover the integration; Raspberry Pi and vehicle validation are still pending.

## Driver display

- Large, bold GPS speed and arc tachometer, with a quiet dark background and mint accents.
- Zero-centered vacuum/boost gauge and AFR gauge with the ECU's actual target.
- Matched coolant, oil pressure, fuel pressure, intake air, battery, and fuel cards.
- Taillight turn, brake, running, and reverse inputs; module connection health.
- Water/meth summary opens its controls directly. Separate tabs for injection, knock settings, and lighting.
- Knock history graph, searchable sensor readings, connection details, and raw CAN traffic.
- Explicit stale, fault, and unavailable states. Fuel remains unavailable until its CAN source is defined.

See [UI design and gauge behavior](docs/ui-design.md) for display scales and review details.

The Pi service also records [rotating MLG data logs](docs/data-logging.md) for
MegaLogViewer: 20 Hz, 30-minute/32 MiB files, and a 2 GiB retention budget by
default. Recording continues with the browser closed. Completed logs are available
under **Sensors → Saved data logs** or in `/var/lib/frogdash/logs`.

[MCP2515 setup](docs/mcp2515.md) supplies the SPI wiring plan and persistent
500 kbit/s CAN service. Optional [Wi-Fi access](docs/wifi-access.md) adds a
20-minute hotspot toggle under **Controls → Wi-Fi** and a phone-friendly page for
downloading logs and checking system status.

[Race mode and appearance](docs/race-and-appearance.md) add GPS acceleration
splits, eighth/quarter-mile timing, automatic or manual laps, saved session
exports, custom accents/backgrounds, and configurable startup splash screens.
Race timing continues on the Pi with the menu closed and is included in MLG logs.
Appearance preferences and uploaded artwork save on the current display.
The appearance gallery includes six coordinated looks and eight mixable preset
backgrounds, alongside custom colors, image uploads and splash screens.

[Driving tools](docs/driving-tools.md) add automatic day/night software dimming,
saved Street/Tuning/Track layouts, conditional latched alerts, optional chimes,
one-touch log bookmarks, synchronized drive-review graphs on the dash and Wi-Fi
page, and read-only Pi/CAN health diagnostics. The existing power/shutdown service
and its GPIO assignments stay separate.

## Browser preview

Open [preview/index.html](preview/index.html) in your browser, or use the GitHub Pages preview. It works directly from disk without dependencies or network access.

The persistent **DEMO · SIMULATED** badge identifies generated readings. Controls only change the simulated state. `M` opens controls, `K` opens the knock monitor, and `Esc` closes a dialog. Use the arrow keys to change control tabs. The production UI receives its readings exclusively from the local CAN/GPS service.

The preview uses copies of the production design with a separate demo transport. After editing `hardware/ui/`, regenerate it:

```bash
python tools/update_preview.py
python tools/update_preview.py --check
```

## Repository

| Path | Contents |
| --- | --- |
| `hardware/frogdash/` | Linux CAN/GPS service, protocol decoding, control commands |
| `hardware/ui/` | Authoritative production dashboard |
| `preview/` | Standalone simulated design preview; published by GitHub Pages |
| `hardware/systemd/` | Raspberry Pi service templates |
| `hardware/compat/` | Comfort controller patches for GPS/control ownership |
| `config/` | Production service environment |
| `tests/` | Protocol, GPS, control, service, replay, and browser checks |
| `docs/` | Installation, protocol provenance, controls, and design |

## Validation

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tools/update_preview.py --check

# Optional real browser integration and visual review
python -m pip install playwright
python -m playwright install chromium
python tests/browser_smoke.py
python tests/browser_personalize.py
python tests/browser_driving.py
python tests/browser_layout.py
# Or pass --browser /path/to/chromium
```

The browser check saves screenshots in `.tmp/` and exercises live telemetry, command acknowledgements, stopping pump tests, reconnects, dialog navigation, warnings, offline states, and the isolated design preview.

Vehicle commissioning still requires confirming controller firmware ownership, the fuel sender protocol, and the display on the actual Pi. The [original phase plan](docs/phase-2-plan.md) is retained for reference.
