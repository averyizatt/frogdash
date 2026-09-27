# Setup, ownership and service (0.4)

Open **Drive → Dash management** on the Pi or the matching preview. The six panels stay within the scaled 1920×720 frame, including on a 1980×720 display.

## Commissioning

The setup checklist reports platform, CAN connection, GPS speed freshness, module presence, display dimensions, sender configuration and injector-estimate readiness. It links to calibration and vehicle acceptance checks. Live data does not establish wiring correctness or sensor accuracy; the final physical checks remain manual.

The current vehicle defaults are a **15.4 US gallon** tank and **four 440 cc/min injectors**, two alternating squirts per four-stroke cycle (**0.5 pulses per injector per crank revolution**). Injector fuel-use estimation stays disabled until effective dead time and PW1/PW2 bank assignment are verified. A valid fuel sender supplies remaining fuel independently; range still requires learned, calibrated consumption data.

Configuration forms, sender calibration, alert/fuel calibration, profile restore and pump tests require fresh stationary telemetry. Stationary means valid speed below 1 km/h, or fresh zero RPM when speed is unavailable. A live moving speed overrides zero RPM. Missing data never grants permission. Viewing remains available. Pump tests stop when stationary confirmation is lost. Controller protection remains in the module firmware; stop/disarm stays available when CAN is connected.

## Fuel sender input: hardware confirmation pending

Configured endpoints: **16 Ω empty; 158 Ω full**. Raspberry Pi GPIO has no general-purpose analog resistance input. Do not connect a tank sender directly to GPIO, and do not parallel an existing gauge circuit with a new pull-up.

The optional implementation supports an **ADS1115** over Linux `/dev/i2c-*`, without a GPIO library. It is disabled by default. Confirm the ADC board and whether the sender is dedicated or shared before selecting a vehicle interface circuit. Automotive supply/transient protection, ground offsets and wire-fault behavior need an appropriate conditioned interface and bench validation.

The selected divider uses a **100 Ω reference resistor** from the regulated 3.3 V supply to a resistance-to-ground sender. For a dedicated sender, the measurement topology is:

```text
3.3 V supply ── 100 Ω ──┬── sender (16–158 Ω) ── GND
                       └── ADC AIN0
3.3 V supply ────────────── ADC AIN1
```

The ADC shares that reference ground. Use the regulated supply rail, not a GPIO output, to excite the divider. AIN0 measures the divider and AIN1 measures the nominal 3.3 V excitation, compensating for supply variation. The resistance calculation is `100 × Vsender / (Vexcitation − Vsender)` ohms. With exactly 3.3 V excitation this becomes `100 × Vsender / (3.3 − Vsender)`. The ADC is still required; a divider alone does not give the Pi an analog input. Confirm whether the sender is shared with another gauge before connecting this topology to the vehicle.

Defaults are bus 1, address `0x48` (decimal 72), 100 Ω pull-up, 8-second smoothing. Existing saved calibrations are preserved: set **Pull-up · Ω** to **100** on an already-configured installation when fitting this resistor. ADS1115 conversions use single-ended AIN0/AIN1 at 128 SPS, ±4.096 V range, sampled twice per second. The configured input range does **not** permit applying more than the ADC's supply voltage to an analog input. See the [TI ADS1115 datasheet](https://www.ti.com/lit/ds/symlink/ads1115.pdf), especially input limits and register configuration.

At 3.3 V with a 100 Ω pull-up, isolated 16 Ω and 158 Ω resistors produce approximately **0.455 V empty** and **2.021 V full**. Divider current is about 28.4 mA at empty and 12.8 mA at full. The reference resistor dissipates at most 0.109 W with a shorted sender; use at least a 0.25 W resistor, with suitable temperature derating. Verify those endpoints, intermediate loads, an open wire and a short on a bench before commissioning. Software computes resistance before converting to percentage; divider voltage itself is not linear with resistance. It optionally interpolates up to 12 measured resistance/percentage points for tank shape, smooths slosh, and marks missing/out-of-range readings stale or faulted. Faults never become a valid empty reading. Long vehicle wiring and the real tank require testing; software plausibility limits are not electrical protection.

If the chosen board is compatible, enable I²C using the instructions for the Pi's actual distro. On Pi 4 the normal I²C1 pins are BCM2/3 (physical pins 3/5). Keep bus pull-ups at 3.3 V. This leaves MCP2515 SPI/IRQ wiring and the existing **BCM23/24 power monitor** alone. After confirming that the distro's `i2c` group owns the selected `/dev/i2c-1` device, add a service drop-in with `sudo systemctl edit frogdash`:

```ini
[Service]
SupplementaryGroups=i2c
```

Restart `frogdash.service`, then enter the actual interface values in Fuel sender and enable only after wiring verification. No I²C scan or GPIO reconfiguration is performed automatically. Replay mode never opens the ADC. The new resistance channel and quality flags are recorded in **MLG schema 5**; no new CAN frame was invented for fuel transmission.

## Backup, restore and support

**Download backup** combines current browser preferences with Pi configuration: appearance/background/splash, layouts, units, alerts, sender calibration, fuel calibration, trip counters, learned economy, race gate/history, maintenance and acceptance records. Browser preferences are explicitly collected from the display making the backup. **Save display profile to Pi / Use saved Pi display profile** transfers preferences between display profiles.

Restoring first validates the whole file. It writes a durable `restore-pending.json` before replacing configuration. An interrupted restore blocks further changes and is replayed at the next service start; do not delete that file to clear a failed restore. Correct storage/permission failures and restart. Manual fuel inventory requires reconfirmation. Restoration reloads the browser. A preview backup is labelled simulated and is rejected by production restore.

Backups exclude MLG recordings, drive-review files, Linux configuration, Wi-Fi credentials, service units and software binaries. Download recordings separately and preserve `/etc/default/frogdash` plus intentional systemd drop-ins before changing an installation. A software rollback does not rewind recorded data or configuration.

**Download diagnostics** exports software/platform, CAN/GPS/recorder state, source quality, sender calibration/faults, Pi health, calibration settings and recent in-memory management/controller results. It excludes raw CAN, GPS positions, credentials and artwork. It is not a system journal export. For startup failures, also collect `journalctl -u frogdash -b` and the kiosk service journal locally.

## Units, backlight and maintenance

US/metric selection changes road gauges and their scales, custom instrument tiles, trips, range, fuel volume/flow and economy. Logs, diagnostics, calibration fields and specifically named timing tests retain their explicit engineering units. This avoids changing protocol values when the display unit changes.

Physical brightness is optional: specify an actual device with `--backlight-name NAME` in `FROGDASH_ARGS`. The service lists `/sys/class/backlight`; unsupported HDMI displays show unavailable. The selected `brightness` file needs write permission for the service and a systemd `ReadWritePaths=` exception to its resolved sysfs path under `ProtectSystem=strict`. These permissions must be tailored to the actual driver/device; no blanket writable `/sys`, GPIO PWM, or guessed device is configured. Without that setup, Drive's day/night brightness remains a software effect.

Maintenance reminders use tracked distance, engine hours, calendar days, or a combination. Zero disables an interval; the first enabled interval to expire makes it due. Add the interval **remaining** until the next service. Recording service starts all enabled intervals again and saves history (last 50 records per reminder; up to 30 reminders). Missing telemetry means distance/engine time may undercount. Calendar reminders depend on correct Pi time. Frogdash distance is not a replacement for the vehicle's legal odometer.

## Versioned installation, update and rollback

The installer targets **Linux / systemd / Python 3.11+**. Confirm the distro and install its Python venv, gpsd and kiosk dependencies using [boot-and-kiosk.md](boot-and-kiosk.md) first. Runtime and browser test dependencies are pinned in separate lock files. Pi installation has not been performed from this Windows development environment.

From a reviewed release checkout:

```sh
python3 tools/install_release.py install
sudo python3 tools/install_release.py install --apply
```

The first command shows a plan. Apply stages `/opt/frogdash-releases/VERSION-CHECKSUM`, builds its venv and verifies source checksums before changing active paths. It stops only `frogdash.service`, atomically switches `/opt/frogdash`, installs the corresponding backend unit, and requires a healthy local service within 35 seconds. Failed activation restores the prior managed link and unit. Successful activation retains `/opt/frogdash-previous`; reload/restart the normal-user kiosk to load the matching UI. It never configures the vehicle shutdown service, Wi-Fi, boot overlays or login policy.

```sh
python3 /opt/frogdash/tools/install_release.py rollback
sudo python3 /opt/frogdash/tools/install_release.py rollback --apply
```

Updates require stationary confirmation from a running current service. If updating from an older service without that API, park and explicitly stop it first. Rollback is between managed releases with intact manifests; dependencies are not re-downloaded. `/var/lib/frogdash` remains in place. Back up first and review schema compatibility before downgrading. Incomplete staged releases are left inactive for inspection, never activated or silently deleted.

For a **legacy regular directory** at `/opt/frogdash`, the installer refuses to overwrite it. While parked, download a backup, stop the kiosk and backend, preserve the old service unit and `/etc/default/frogdash`, and move the inspected legacy directory to a named recovery location such as `/opt/frogdash-legacy`. Run the installer from a separate reviewed checkout. If initial migration fails, stop the backend and restore that directory and its saved service unit; automatic rollback begins after the first managed release. Do not remove the legacy copy until vehicle acceptance passes.

## Recovery and vehicle acceptance

The backend sends systemd readiness/watchdog notifications; a stalled event loop causes `WatchdogSec=20` to restart the service. The kiosk launcher supervises a dedicated Chromium process group and watches a per-launch render heartbeat. After startup grace, a responsive backend with no rendered frames triggers a browser restart. Backend outages allow reconnection time. Neither mechanism reboots the Pi or changes power control. Existing automatic crash restarts remain active.

Before road use, record real results under Support & testing:

1. Repeated cold starts: measure key-on to first UI and **live** readings separately; compare microSD performance and journal uptime stamps.
2. Cranking / key cycling: no undervoltage corruption or conflicting relay control; verify the existing external shutdown service still owns BCM23/24.
3. GPS unplug/replug and lost fix: stale/unavailable speed, reconnect, no fabricated race result.
4. CAN/module loss and recovery: correct stale flags, bus errors, command availability and controller ownership. Confirm no duplicate GPS transmitter.
5. Storage pressure: bounded MLG rotation, visible failures and recovery; retain unrelated files.
6. Long recording: independently open generated `.mlg` files in MegaLogViewer; verify timestamps, channel units, schema and gaps.
7. Actual 12.3-inch screen: every menu, touch target, daylight/night contrast and any hardware brightness control.
8. Controllers and sender: requested value → ACK if defined → live readback, then controller power-cycle retention; sender resistor tests and tank calibration.

Browser/automated tests cannot establish these physical outcomes. Controller protocol support is unchanged: water/meth and knock have command acknowledgements, taillights have send-only commands plus telemetry, and persistence is not guaranteed by the current firmware. Adding EEPROM persistence or additional readback needs an agreed firmware change in the module repositories.
