# Rotating MLG recording

Frogdash records genuine binary `.mlg` files using EFI Analytics' published
[MLG version 2 specification](https://www.efianalytics.com/TunerStudio/docs/MLG_Binary_LogFormat_2.0.pdf).
The implementation was checked against the supplied TunerStudio log: version 2,
113 fields, 278 payload bytes per record, 25,913 data records and 17 markers.
The independent reader consumed that entire file with no checksum errors.
The original log and its embedded tuning information are not copied into the project.

## Enable on the Pi

The supplied systemd service and `config/frogdash.env` enable recording at startup:

```sh
FROGDASH_ARGS="--interface can0 --gpsd --log-dir /var/lib/frogdash/logs"
```

The options the dash runs with are the list in `config/frogdash-options`: every
**Update now** writes them into `FROGDASH_ARGS` in `/etc/default/frogdash` and restarts
the dash if they changed, after checking that the dash takes them (step *Dash options*
in System check). Change recording there, for example a `--log-hz 50` line; nothing is
typed on the Pi.

`StateDirectory=frogdash` gives the service a writable persistent directory under
its existing sandbox. Recording runs inside the Frogdash daemon, independently
of Chromium. No separate cron task or `logrotate` rule is needed: rotating a live
binary file externally would break its header/record structure.

For a manual run, add `--log-dir ./logs`. Omitting `--log-dir` disables recording.
Replay can be recorded explicitly, with `replay` in both filename and metadata.

## Defaults and retention

| Option | Default |
| --- | --- |
| `--log-hz` | 20 samples/second |
| `--log-minutes` | New file after 30 minutes |
| `--log-file-mib` | New file before exceeding 32 MiB |
| `--log-total-mib` | 2,048 MiB total managed logs |
| `--log-min-free-mib` | Keep 256 MiB free on the filesystem |

Time and size limits apply together; whichever is reached first rotates the log.
The oldest completed Frogdash files are deleted when the storage budget or free
space reserve requires it. **Copy logs you want to keep out of this directory.**
Only regular files matching the recorder's exact generated filename pattern are
eligible for retention. Unrelated files, symlinks and the active log are excluded.
A directory lock prevents two recorder processes from using the same directory.

Every startup and rotation creates a new independent file, including its channel
definitions. UTC filenames include a random suffix to avoid overwriting logs
after clock adjustments or rapid restarts. Each file's `Time` starts at zero and
uses the monotonic capture clock. The date in its header depends on the Pi's clock.

Filesystem work uses a worker thread and a bounded two-second queue. A slow or
full disk does not block CAN processing. Dropped samples are counted; storage
errors pause recording, appear in the dash/health response and journal, and retry
after 30 seconds. The writer flushes and syncs at least every five seconds and on
rotation/shutdown. Abrupt power loss can lose the latest unsynced records and leave
a partial final record; it is not equivalent to a clean service shutdown.

## Read or copy logs

The header shows `REC 20 Hz`, `LOG OFF`, or `LOG ERROR`. Open **Sensors → Saved
data logs** and refresh the list to download completed files. The current file
is identified as recording; it becomes downloadable after rotation. A stopped
service's final file can be copied directly from `/var/lib/frogdash/logs`.
The driver web service remains bound to localhost; use the Pi browser, an SSH
tunnel, or install the separate [Wi-Fi transfer page](wifi-access.md).

- `GET /logs`: recorder status and file inventory.
- `GET /logs/<filename>`: download a completed managed log; active files return 409.
- `GET /health`: includes recording status, active filename, error and drop count.

Open the `.mlg` in MegaLogViewer using **File → Open**. A synthetic test file can
be made without hardware:

```sh
python tools/make_demo_log.py .tmp/frogdash-demo.mlg
python tools/inspect_mlg.py .tmp/frogdash-demo.mlg
```

The generator refuses to overwrite an existing file. `inspect_mlg.py` independently
validates v1/v2 headers, records and checksums. `--fields` lists channel definitions;
`--allow-truncated` examines intact records before an incomplete tail without
modifying the file. Actual MegaLogViewer GUI loading and Pi power-loss behavior
still need to be checked on the target installations.

## Log viewer on the dash

**Drive workspace → Log viewer** shows any of these logs MegaLogViewer style, without copying
them anywhere. First the logs: one row each, newest first, with its day, start time, length and
size (the one being recorded says so). Tap one to open it; **‹ Logs** goes back. An open log has
six views, chosen at the top right:

**Graph**
- The channels chosen, each on its own scale: on **one graph**, or **Stacked**, a strip each on
  one time line. Scales fit the time on screen, or **the whole log** (they then stay put while
  zooming).
- **The channels beside it**: every channel in the log, the ones on the graph first, then the
  rest by group. Tap one to put it on the graph or take it off (up to eight); the search box
  finds one by name. The choice is kept for the next log.
- **Layouts…**: ready-made sets (Fueling, Boost, Ignition, Temperatures and pressures,
  Water/meth, Driving), and **Save** keeps the channels on the graph as one of your own.
  **Clear** takes them all off.
- **The cursor**: each channel on the graph shows its value at that moment, beside its lowest,
  average and highest over the time on screen. Off the graph the cursor stays where it was.
- **Mark A**: tap the graph (without dragging) to put A there. Each channel then shows its
  change from A, and the bar says how long from A the cursor is. **Clear A** takes it away.
- **Zoom**: drag across the graph, or Zoom in / Zoom out, ◀ ▶ to go earlier or later, Whole log.
  With the steering wheel or the arrow keys: highlight the graph, press ON, then left/right move
  in time and up/down zoom; ON again to leave.
- **Play** runs the cursor through the drive at 1× to 32×, with the graph following it.
- **Find**: type a condition, e.g. `RPM > 6000 and AFR > 13`, and **Find ▶ / ◀ Find** jump to
  each time it comes true ("3 of 12").
- **Marks**: each bookmark (B, from the log's Bookmark ID channel) and the drive's alerts and
  bookmarks are dashed lines across the graph; **Marks…** jumps to one.
- **+ Calculated field**: a channel worked out from others, e.g. `[AFR] - [AFR Target 1]`, with
  a name and units. One tap fills in an example: AFR error, Lambda, Boost from baro, Injector
  duty. Calculated fields can be graphed and used in every view, and are kept for every log
  that has the channels they use.

**Scatter**: one channel across, one up, coloured by a third (RPM, MAP and AFR to start with).
Point at a dot to read it; tap it to see that moment on the graph.

**Table**: a third channel in cells of two others, like a VE table. A cell shows the average,
lowest or highest value, the number of samples, or the time spent there. Columns and rows are 12
round values across what the log reached; type another number, or the values themselves
(`500, 1000, 1500, …`) to match your own table. The graph cursor's cell is outlined. Tap a cell
for its samples, time, lowest and highest, and to see the first time on the graph.

**Data**: the rows themselves for the time on the graph, of the channels on it (every row once
zoomed in far enough). Tap a row to choose it; **Show the chosen row on the graph**.

**Track**: the GPS position (the dead-reckoned position if the GPS had none), coloured by a
channel, with a scale bar. Green is the start, red the end, white the graph cursor, yellow A.
Tap the line to see that moment on the graph.

**Summary**: the drive's peaks, each with **Show** to open the graph there:
- the drive's length and distance, top speed, highest RPM, peak boost (and its RPM);
- time at wide open throttle and in boost;
- lean moments under boost, hottest coolant and intake air;
- lowest oil pressure above 2500 RPM, lowest battery while running;
- water/meth spraying, bookmarks and alerts.

Below the peaks, every main channel's lowest, average and highest for the whole log, with when
the lowest and highest were.

**Only when**: Scatter and Table can take only the rows where a condition holds: a warm engine,
under boost, wide open, cruising, or your own (`[CLT] > 160 and [TPS] > 50`). Scatter, Table and
Track can show the whole log or only the time on the graph.

**Formulas** (calculated fields, Find, Only when): channels go in `[brackets]`, or bare if the
name has no spaces (`RPM`). They can use numbers, `+ - * / % ^` and `> < >= <= == !=`, `and or
not`, and `abs min max sqrt round floor ceil log exp if(test, then, else)`. A formula is read,
never run as code.

Readings that were not live (a sensor with no signal) are gaps, not zeros.

The Pi reads only the channels and the time asked for. For the graph, a long stretch is thinned
to each part's lowest and highest value, so a spike is never lost when the whole drive is shown;
zooming in reads every sample again. Where one channel is paired with another (Scatter, Table,
Track, calculated fields, Find), whole rows are read: every row, or every nth of a long log, up
to 20,000. The Summary's lowest and highest come from every row. (`hardware/frogdash/logview.py`,
`hardware/ui/mlgplot.js`.) The live preview has four simulated drives to try it on.

## Channels and compatibility

The fixed schema currently contains 168 decoded channels, a quality field for each,
and Time/CAN connection/drop counters (339 fields). Common measurements use the
same names as the sample: RPM, MAP, TPS, AFR, AFR Target 1, MAT, CLT, PW, Batt V,
OilPressure, FuelPressure, Vehicle Speed and GPS fields. MAT/CLT use Fahrenheit;
other `*_c` channels retain Celsius. The log includes water/meth, knock, lighting,
comfort, configuration and event diagnostics. String states are numeric enums
whose mappings are embedded in the file metadata.

`Q <channel>` is 0 unavailable, 1 live, 2 stale, or 3 fault. Non-live readings are
IEEE NaN, never a made-up zero or a silently held stale reading. Filter to quality
1 when analyzing a measurement. For example, require `Q AFR = 1`, `Q RPM = 1`
and `Q MAP = 1` for engine analysis. Event/config fields retain their historical
protocol meaning; they are not evidence that a fault is currently active.

This is a sampled log of what reaches Frogdash, not a complete serial ECU capture
or raw CAN dump. A 20 Hz recorder does not create 20 Hz sensor updates. Fields
available only over TunerStudio's serial protocol are not fabricated, and this file
does not embed your MSQ/tune. Fuel level remains unavailable until the external controller sends a valid
[CAN fuel percentage](fuel-can.md). F32 measurements have normal float precision; GPS coordinates
are approximately meter-resolution. Raw CAN diagnostics remain available through
the existing inspector, but raw frame traffic is not stored in this MLG file.

The writer uses the documented big-endian header, 89-byte field definitions,
10-microsecond rolling timestamps and payload byte-sum checksum. The sample
confirms an 8-bit counter wrapping through 255 to 0. An explicit Time channel
preserves long gaps and elapsed time beyond the short timestamp wrap.

[Race mode](race-and-appearance.md) adds GPS timing channels to new MLG files:
race phase, elapsed time, distance, acceleration splits, eighth/quarter-mile
times and crossing speeds, lap count and best lap. Invalid race measurements
carry fault quality and NaN. Completed session history and detailed lap results
are also available as a separate JSON export in the Race screen.

[Drive review](driving-tools.md) adds a Bookmark ID counter to new logs and
stores manual/fault captures with approximate MLG time references in separate
bounded review JSON files. Its lower-rate graphs and retention are independent
of MLG recording. The same read-only review is available over the Wi-Fi portal.

[Trip and fuel](trip-and-fuel.md) adds schema-4 trip distance counters, estimated
fuel flow/inventory/range, and instant/average US MPG to new files. Fuel values
require calibration and remain explicitly estimates; unavailable values use
NaN and their quality flag. Older files retain their own embedded field schema.

[CAN fuel level](fuel-can.md) is included in schema 8: percentage, controller status and
quality fields. The local resistance channel from schema 5 is removed from new
files; older recordings retain their embedded schema. Faults and stale readings
retain NaN/quality semantics. Display unit selection does not change recorded units.

Schema 7 also expands the MS2/Extra CAN channels and corrects status-word and
dwell decoding. See [CAN compatibility](can-compatibility.md). Older files keep
their embedded channel definitions and remain readable.

Schema 8 includes the CCM steering button mask and report sequence. Replaying
a CAN capture never executes wheel navigation actions. See [steering-wheel input](steering-wheel.md).

Schema 10 adds the fused navigation channels (`nav.*`): position and heading that
continue through GPS dropouts, their source (GPS, estimated, last known), the speed
source, an accuracy figure, time since the last fix and the learned wheel-speed scale.
