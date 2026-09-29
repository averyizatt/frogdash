# Setup, ownership and service (0.4)

Open **Drive → Dash management** on the Pi or the matching preview. The five panels stay within the scaled 1920×720 frame, including on a 1980×720 display.

## Commissioning

The setup checklist reports platform, CAN connection, GPS speed freshness, module presence, display dimensions, CAN fuel quality and injector-estimate readiness. It links to vehicle acceptance checks. Live data does not establish wiring correctness or sensor accuracy; the final physical checks remain manual.

The current vehicle defaults are a **15.4 US gallon** tank and **four 440 cc/min injectors**, two alternating squirts per four-stroke cycle (**0.5 pulses per injector per crank revolution**). Injector fuel-use estimation stays disabled until effective dead time and PW1/PW2 bank assignment are verified. A valid CAN fuel percentage supplies remaining fuel independently; range still requires learned, calibrated consumption data.

Dash configuration, alert/fuel estimate calibration and profile restore do not require stationary telemetry. Appearance and local display preferences also work without a backend connection; saving Pi settings requires the dash service. Restore remains blocked during race timing or pump tests and retains validation and recovery checks. Physical controller commands keep their existing module/telemetry requirements: pump tests stop when stationary confirmation is lost, and stop/disarm stays available when CAN is connected.

## External fuel controller

Fuel sender measurement, resistance conversion, tank calibration and smoothing
run on the separate microcontroller. Frogdash receives the resulting percentage
through CAN; see the [fuel CAN contract](fuel-can.md). The Pi sender driver,
calibration UI, polling task and configuration API have been removed. There is
no direct fuel-sender wiring or I2C setup required on the Pi.

## Backup, restore and support

**Download backup** combines current browser preferences with Pi configuration: appearance/background/splash, layouts, units, alerts, injector fuel calibration, trip counters, learned economy, race gate/history, maintenance and acceptance records. Browser preferences are explicitly collected from the display making the backup. **Save display profile to Pi / Use saved Pi display profile** transfers preferences between display profiles.

New backups use version 2. Version-1 backups still restore supported settings, while ignoring the removed Pi sender section; old `sender.json` files are no longer read. Restoring first validates the whole file. It writes a durable `restore-pending.json` before replacing configuration. An interrupted restore blocks further changes and is replayed at the next service start; do not delete that file to clear a failed restore. Correct storage/permission failures and restart. Manual fuel inventory requires reconfirmation. Restoration reloads the browser. A preview backup is labelled simulated and is rejected by production restore.

Backups exclude MLG recordings, drive-review files, Linux configuration, Wi-Fi credentials, service units and software binaries. Download recordings separately and preserve `/etc/default/frogdash` plus intentional systemd drop-ins before changing an installation. A software rollback does not rewind recorded data or configuration.

**Download diagnostics** exports software/platform, CAN/GPS/recorder state, source quality, CAN fuel status, Pi health, calibration settings and recent in-memory management/controller results. It excludes raw CAN, GPS positions, credentials and artwork. It is not a system journal export. For startup failures, also collect `journalctl -u frogdash -b` and the kiosk service journal locally.

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
2. Cranking / key cycling: commission the [PiSugar 3 Plus setup](pisugar-power.md), retire the old BCM23/24 relay service, and verify ride-through, orderly log closure, output cutoff and automatic restart. Test input returning during shutdown too.
3. GPS unplug/replug and lost fix: stale/unavailable speed, reconnect, no fabricated race result.
4. CAN/module loss and recovery: correct stale flags, bus errors, command availability and controller ownership. Confirm no duplicate GPS transmitter.
5. Storage pressure: bounded MLG rotation, visible failures and recovery; retain unrelated files.
6. Long recording: independently open generated `.mlg` files in MegaLogViewer; verify timestamps, channel units, schema and gaps.
7. Actual 12.3-inch screen: every menu, touch target, daylight/night contrast and any hardware brightness control.
8. Controllers and sender: requested value → ACK if defined → live readback, then controller power-cycle retention; external fuel-controller percentage/validity checks and transmission-loss handling.

Browser/automated tests cannot establish these physical outcomes. Controller protocol support is unchanged: water/meth and knock have command acknowledgements, taillights have send-only commands plus telemetry, and persistence is not guaranteed by the current firmware. Adding EEPROM persistence or additional readback needs an agreed firmware change in the module repositories.
