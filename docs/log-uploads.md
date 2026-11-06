# Reports and drive uploads

**Send now**, **Update now**, and automatic uploads send reports and all unsent drive
recordings together. The automatic helper checks about every five minutes for internet
and waits while an update or recovery is running or requested. It also checks between
files, so a newly requested update takes priority after the current transfer finishes.
Home Wi-Fi and a phone hotspot both work; the dash cam's Wi-Fi has no internet.

Reports upload to this repository on their own branch **`pi-logs`** (data only: nothing lands on
`main`, and the tests do not run for it):

| What | Where |
|---|---|
| What went wrong, and when, since the last report: the GPS losing its fix or receiver, a position with no speed, the CAN bus and each module going quiet, ignition, under-voltage, heat, recording errors, engine start and stop (`hardware/frogdash/eventlog.py`) | `pi/<date>/<time>-events.txt` on `pi-logs` |
| Diagnostics: self check, the dash's live state, every helper's status (update, setup, GPS, Wi-Fi, screen), module firmware, the last failed start, disk and power flags; raw GPS evidence (25 lines of `gpspipe`, gpsd's ports, USB devices) and CAN evidence (link counters, two seconds of traffic) | `pi/<date>/<time>-diagnostics.json` |
| The boot report (`tools/boot_report.py`): boot timing, kiosk start, display modes | `pi/<date>/<time>-boot.txt` |
| The system log: the dash, GPS, Wi-Fi and power services since the Pi started, warnings from everything, and the end of the start before (how it shut down) | `pi/<date>/<time>-journal.txt` |
| CAN recordings made on the dash since the last report (Sensors > Raw CAN > Record), in candump log format, for SavvyCAN or cantools with `hardware/can_contract/frogdash.dbc` ([savvycan.md](savvycan.md)) | `pi/<date>/<time>-can-<when>.log` |
| All unsent drive recordings, gzip-compressed MLG | a pre-release per drive named `drive-<date>-<time>` |

The dash writes its record of what went wrong all the time, a file a day in `events/` in
its data folder (kept 30 days, at most 20 MB), so a problem on a drive is there at the
next upload. The setup keeps the system log across restarts (at most 150 MB).

The reports are made after every update even when uploads are not connected, and kept on
the Pi (the newest 10) until they can go up; the first upload sends them too.

Interrupted uploads resume on the next attempt. Files already on the reports branch
are checked against the saved report: identical files are skipped, and changed files
are updated using GitHub's current file SHA. This also handles a connection dropping
after GitHub saved a file but before the Pi received its reply. A report leaves the
queue only after all its files have uploaded successfully.

The file being recorded is closed first, and recording continues in a new file. Files
still being written are excluded. A drive is the recordings less than ten minutes apart.
All retained, unsent recordings go up, including older drives. Each successful file is
saved in the upload history immediately, so an interrupted upload resumes the remaining
files in the same release. Each recording goes up once; the
reports go up every time. This happens on any connection, including a phone hotspot:
the reports are small, a drive roughly ten to a few tens of MB per hour driven after
compression. Each upload pass sends up to 400 MB compressed; the rest waits for the next
automatic pass or **Send now**. Unsent recordings and queued reports trigger an automatic
upload without needing new faults, a reboot, or a software update. Events alone send at
most every 30 minutes; a new boot also sends a report.

If an update is undone because the new version did not start, the upload still runs
after going back, so the failed start's log goes up with the diagnostics.

The result is the last part of the update's status message ("Uploaded the diagnostics
and 2 drive recordings", or "Upload failed: ..." with the reason). The
update itself never fails because of an upload.

## Public, on purpose

The repository is public, and so are the uploads, **GPS positions included**: the owner
chose this. What is blanked out of every text before it goes up: saved Wi-Fi passwords
and network names (from NetworkManager), the dash's hotspot password, the phone page's
access code and session, and the upload access itself. Recordings (MLG) carry no Wi-Fi
details.

The access can write to the owner's public repositories, including this one, where the
Pi installs its software from. It is kept on the Pi only (`log-upload.json` in the dash's
state folder, readable by the dash and root), sent only to GitHub, never shown or
included in an upload. If the Pi is lost or stolen, revoke it on GitHub (Settings >
Applications > Authorized OAuth Apps).

## Connecting it (once)

On the dash, with internet (home Wi-Fi or the phone hotspot): **Dash management >
Software & power > Reports to GitHub > Connect GitHub**. The dash shows a code such as
`WDJB-MJHT`. On the phone open **github.com/login/device**, type the code and press
**Authorize**. The card turns to **Connected** and sends reports and drives. They then
upload automatically when online and no update is running. **Send now** sends them
on demand. **Disconnect** (two presses) stops uploads.

This uses GitHub's device flow through the owner's own OAuth app, made once on GitHub
(Settings > Developer settings > OAuth Apps > New OAuth App, any homepage and callback
address, **Enable Device Flow** ticked). Its Client ID is public, not a secret: it is
`CLIENT_ID` in `hardware/frogdash/github_link.py`.

A token pasted on the phone page (Uploads) still works the same way.

GitHub may issue an eight-hour access token when connecting with the on-screen code.
The Pi keeps the accompanying refresh token privately and renews the access token
before it expires when uploading. After upgrading from a version that discarded the
refresh token, disconnect and connect once more to enable renewal. The card says
whether renewal is automatic; dates include the month name, time and time zone.
Pasted personal access tokens retain the expiration chosen on GitHub.

Reading it: a recording is `gunzip`ped and opened in MegaLogViewer, or read with
`python tools/inspect_mlg.py file.mlg`.
