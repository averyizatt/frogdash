# Uploads after each update

After every **Update now** (on the dash or the phone page), while the Pi is online, it
uploads to this repository, on its own branch **`pi-logs`** (data only: nothing lands on
`main`, and the tests do not run for it):

| What | Where |
|---|---|
| What went wrong, and when, since the last report: the GPS losing its fix or receiver, a position with no speed, the CAN bus and each module going quiet, ignition, under-voltage, heat, recording errors, engine start and stop (`hardware/frogdash/eventlog.py`) | `pi/<date>/<time>-events.txt` on `pi-logs` |
| Diagnostics: self check, the dash's live state, every helper's status (update, setup, GPS, Wi-Fi, screen), module firmware, the last failed start, disk and power flags; raw GPS evidence (25 lines of `gpspipe`, gpsd's ports, USB devices) and CAN evidence (link counters, two seconds of traffic) | `pi/<date>/<time>-diagnostics.json` |
| The boot report (`tools/boot_report.py`): boot timing, kiosk start, display modes | `pi/<date>/<time>-boot.txt` |
| The system log: the dash, GPS, Wi-Fi and power services since the Pi started, warnings from everything, and the end of the start before (how it shut down) | `pi/<date>/<time>-journal.txt` |
| The newest drive's recordings, gzip-compressed MLG | a pre-release named `drive-<date>-<time>` |

The dash writes its record of what went wrong all the time, a file a day in `events/` in
its data folder (kept 30 days, at most 20 MB), so a problem on a drive is there at the
next update. The setup keeps the system log across restarts (at most 150 MB).

The reports are made after every update even when uploads are not connected, and kept on
the Pi (the newest 10) until they can go up; the first upload sends them too.

The file being recorded is finished first, so a drive that has just ended goes up whole.
A drive is the recordings less than ten minutes apart. Each drive goes up once; the
reports go up every time. This happens on any connection, including a phone hotspot:
the reports are small, a drive roughly ten to a few tens of MB per hour driven after
compression. Over 400 MB compressed in one drive, the rest waits.

If an update is undone because the new version did not start, the upload still runs
after going back, so the failed start's log goes up with the diagnostics.

The result is the last part of the update's status message ("Uploaded the diagnostics
and 2 recordings of the newest drive", or "Upload failed: ..." with the reason). The
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
**Authorize**. The card turns to **Connected**; from then on every update sends the
reports with nothing to do. **Disconnect** (two presses) stops it.

This uses GitHub's device flow through the owner's own OAuth app, made once on GitHub
(Settings > Developer settings > OAuth Apps > New OAuth App, any homepage and callback
address, **Enable Device Flow** ticked). Its Client ID is public, not a secret: it is
`CLIENT_ID` in `hardware/frogdash/github_link.py`.

A token pasted on the phone page (Uploads) still works the same way.

Reading it: a recording is `gunzip`ped and opened in MegaLogViewer, or read with
`python tools/inspect_mlg.py file.mlg`.
