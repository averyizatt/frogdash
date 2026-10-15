# Uploads after each update

After every **Update now** (on the dash or the phone page), while the Pi is online, it
uploads to the owner's **private** GitHub repository (`averyizatt/frogdash-logs`):

| What | Where in the repository |
|---|---|
| Diagnostics: self check, every helper's status (update, setup, GPS, Wi-Fi, screen), the last failed start, disk and power flags | `pi/<date>/<time>-diagnostics.json` |
| The boot report (`tools/boot_report.py`): boot timing, kiosk start, display modes | `pi/<date>/<time>-boot.txt` |
| The dash's own service logs since the Pi started | `pi/<date>/<time>-journal.txt` |
| The newest drive's recordings, gzip-compressed MLG | a release named `drive-<date>-<time>` |

The file being recorded is finished first, so a drive that has just ended goes up whole.
A drive is the recordings less than ten minutes apart. Each drive goes up once; the
reports go up every time. This happens on any connection, including a phone hotspot:
the reports are small, a drive is roughly ten to a few tens of MB per hour driven after
compression. Over 400 MB compressed in one drive, the rest waits.

If an update is undone because the new version did not start, the upload still runs
after going back, so the failed start's log goes up with the diagnostics.

The result is the last part of the update's status message ("Uploaded the diagnostics
and 2 recordings of the newest drive", or "Upload failed: ..." with the reason). The
update itself never fails because of an upload.

## Setting it up (once)

1. On GitHub: Settings > Developer settings > Personal access tokens > Fine-grained
   tokens > Generate new token. Repository access: **Only select repositories**,
   `frogdash-logs`. Permissions: **Contents: Read and write**. An expiry of a year is
   fine; make a new one when it runs out.
2. Turn on the dash's hotspot (Controls > Wi-Fi), open its page on the phone, enter the
   code, and under **Uploads** enter `averyizatt/frogdash-logs` and paste the token.
   **Save**.

The token is kept on the Pi only (`log-upload.json` in the dash's state folder, readable
by the dash and root), sent only to GitHub, and never shown again or included in the
diagnostics. **Stop uploading** deletes it.

The repository must stay private: recordings contain GPS positions.

Reading it: a recording is `gunzip`ped and opened in MegaLogViewer. The tools here can
read both: `python tools/inspect_mlg.py file.mlg`.
