# Display modes, alerts, bookmarks, review and health

Open **Drive** in the footer for Display modes, Alerts, Drive review and Dash
health. **Mark log** and **Alerts** also stay on the main instrument screen.
These tools do not command the engine or change the existing shutdown service.
No GPIO is accessed. BCM 23/24 remain reserved for the owner's ACC/relay service.

## Day/night and saved layouts

Automatic lighting follows the taillight module's fresh `lighting.running`
signal. Lights on selects night; lights off selects day. Missing/stale data
returns automatic mode to day brightness. Manual Always day / Always night
overrides are available. Each mode has its own brightness slider; night also
has an accent color. Day styling comes from Appearance. Transitions are smooth
unless the browser requests reduced motion.

Brightness is software dimming of the dashboard and dialogs, not a change to
the physical LCD backlight. No unsupported monitor brightness protocol is
assumed. Preferences persist in this display's browser profile, separately
from the service's shared alert settings.

Street, Tuning and Track each remember six configurable lower instruments.
Street starts with the familiar temperature/pressure/fuel cards; Tuning favors
AFR, target, boost, pressure and injection; Track adds last/best lap readings.
The primary instrument proportions change too. Track includes shift lights
with a saved 2000–9000 RPM threshold. This is a visual shift cue, not an ECU
rev limiter, and it does not change the tachometer's existing red-zone scale.
Reset this layout restores only the selected layout's instrument choices.

## Advisory alerts

Defaults are starting values to configure for the engine, not a validated tune.
All rules require fresh inputs. The Pi evaluates them every 100 ms, independently
of the browser or menu state:

| Rule | Default condition | Required duration |
| --- | --- | --- |
| Oil | Below 15 psi at/above 1500 RPM | 1 s |
| Lean | AFR > ECU target + 1.0, boost ≥20 kPa, RPM ≥1500 | 0.8 s |
| Coolant | At/above 112 °C | 2 s |
| Water/meth | Fault bits, FAULT state, or LOW_FLOW/NO_FLOW while SPRAYING | 1 s |
| Knock | Controller warning or critical indication | 0.2 s |

Oil, lean, coolant and water/meth rules can be enabled/disabled and their numeric
thresholds adjusted where applicable. Knock uses the controller's own warning
decision. Unknown flow is not treated as confirmed no-flow; pump-test mode does
not trigger the delivery rule. Missing AFR target prevents the lean comparison.

An incident latches the warning and captures the readings once. It requires one
second of fresh normal data to recover, and acknowledgement to dismiss the latch.
Acknowledge does not hide a condition that is still active. Losing telemetry
does not clear an incident: its status becomes SIGNAL LOST. A fresh recurrence
creates a new capture. Selecting an alert shows its captured values/qualities.

Optional chimes sound on this browser for new incidents, at most once per three
seconds. Enable chime and tap Test chime to confirm the Pi's audio output and
unlock browser audio. A closed browser cannot produce a chime, but service-side
alerts/captures continue. These are advisory; ECU/module protection remains in
those controllers.

Settings persist as `<data-dir>/alerts.json`. The default data directory is
`/var/lib/frogdash`; override with `--data-dir`. Disk errors are shown, and
in-memory evaluation continues. Replay uses a separate `<data-dir>/replay`
directory so it does not mix recorded drives with live drives.

## Bookmarks and drive review

Press **Mark log** or **B** from the main dashboard. Manual markers are limited
to one per second. Every alert incident also creates a marker automatically.
Each event stores its time, label, sensor values/qualities and, when available,
the active MLG filename and approximate MLG Time position.

New MLG files include a **Bookmark ID** counter, resetting at service startup.
It increments for both manual and alert events; closely spaced events can occur
between two MLG samples, so not every intermediate counter value is guaranteed
to appear as a row. Use the review's event time and captured readings as well.
Markers still work when MLG recording is disabled, with a clear “no active MLG”
message. No MLG binary format changes are required beyond the additional channel.

Drive review starts when fresh RPM reaches 300, GPS speed exceeds 2 km/h, or
someone records a bookmark. It ends after two minutes of fresh RPM below 300
with no measured movement, or on orderly dashboard-service exit. Missing RPM
does not falsely signal engine shutdown. None of these actions shut down the Pi.

Reviews include peak boost, maximum coolant/intake temperature, maximum speed,
minimum oil pressure while at/above 1500 RPM, faults, bookmarks and race results.
The synchronized graphs show RPM, boost, AFR versus target, plus a selectable
fourth channel. Selecting a bookmark focuses on ±15 seconds around its time;
the shared slider moves the cursor across all traces. Unavailable values create
gaps rather than fabricated readings. Export review downloads the JSON data.

Charts initially sample at 2 Hz. After 10,800 points, the stored trace is reduced
to every second point and its interval doubles; longer drives repeat this process
to bound memory. The displayed chart interval documents this reduction. Peak
statistics still inspect every service evaluation. For full-rate analysis use
the MLG file, which retains its configured recorder rate.

The service checkpoints reviews about every 15 seconds and promptly after an
event, using atomic replacement and file sync in a worker thread. An unclosed
checkpoint recovered after restart is labeled **interrupted**, never complete.
Data after the last successful checkpoint may be missing after abrupt power loss.
The existing shutdown script remains responsible for power sequencing.

Reviews live in `<data-dir>/drives/`. Retention keeps up to 20 recorder-owned
drive JSON files within a 64 MiB budget, protecting the active drive and ignoring
unrelated files and symlinks. Each drive retains the latest 250 detailed events
and a total event count. These limits are separate from MLG retention, so an old
review can refer to an MLG that has already rotated out of storage.

The authenticated Wi-Fi page uses the same review/graph component. It provides
read-only review, JSON exports, MLG downloads and status. Alert configuration,
acknowledgement, bookmarking, CAN controls and power operations are not exposed
on that listener. An expired hotspot session hides the review and requests login.

## Dash health

Diagnostics refresh about every five seconds, outside the CAN receive loop:

- Free storage on the recording/data filesystem and recorder drop count.
- Linux thermal-zone temperature when exposed by the hardware.
- Pi undervoltage and throttling, both current and latched since boot, through
  the official [`vcgencmd get_throttled` interface](https://www.raspberrypi.com/documentation/computers/os.html).
- CAN controller state, bitrate and RX/TX errors from read-only `ip -j -details
  -statistics link show`; received error frames, bus-off and restart events from
  the existing [SocketCAN error-frame subscription](https://cdn.kernel.org/doc/html/latest/networking/can.html).
- Observed distinct USB GPS measurement rate and fix freshness.

Unavailable or unauthorized diagnostics are labeled unavailable. Zero errors
or “Clear” is never substituted for a failed read. Since-boot power flags refer
to the Pi firmware history, not just the current drive. CAN event counters on
the dash count frames seen since Frogdash started; interface counters may have
a different lifetime. This is not a CAN bus-utilization measurement.

Install `iproute2` and the Raspberry Pi package providing `vcgencmd` on the Pi.
The updated Frogdash service adds the `video` supplementary group for Pi firmware
diagnostics and `AF_NETLINK` for interface queries. It adds no administrative CAN
capability. Reinstall this unit template and reload/restart **frogdash.service**
when deploying the update; leave the separate shutdown service as it is.

## Validation

`tests/test_driving.py` covers debounce/latching/acknowledgement, stale data,
conditional rules, captures, MLG marker values, checkpoint recovery, retention,
API restrictions and health flag decoding. `tests/browser_driving.py` exercises
saved layouts, automatic lighting fallback, real service settings and markers,
review graphs/exports, and phone authentication/expiry. The layout check covers
all twelve submenu views at seven screen sizes. Pi display brightness, physical
audio output and actual hardware diagnostics still require commissioning.
