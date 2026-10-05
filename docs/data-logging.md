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

After installing this checkout at `/opt/frogdash`, update both the unit and your
environment file, preserving any GPS/ownership settings you already use:

```sh
sudo cp hardware/systemd/frogdash.service /etc/systemd/system/
sudo nano /etc/default/frogdash
sudo systemctl daemon-reload
sudo systemctl restart frogdash
curl http://127.0.0.1:8080/health
```

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
