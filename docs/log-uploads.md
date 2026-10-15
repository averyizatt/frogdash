# Uploads after each update

After every **Update now** (on the dash or the phone page), while the Pi is online, it
uploads to this repository, on its own branch **`pi-logs`** (data only: nothing lands on
`main`, and the tests do not run for it):

| What | Where |
|---|---|
| Diagnostics: self check, every helper's status (update, setup, GPS, Wi-Fi, screen), the last failed start, disk and power flags | `pi/<date>/<time>-diagnostics.json` on `pi-logs` |
| The boot report (`tools/boot_report.py`): boot timing, kiosk start, display modes | `pi/<date>/<time>-boot.txt` |
| The dash's own service logs since the Pi started | `pi/<date>/<time>-journal.txt` |
| The newest drive's recordings, gzip-compressed MLG | a pre-release named `drive-<date>-<time>` |

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
access code and session, and the upload token. Recordings (MLG) carry no Wi-Fi details.

The token can write to this repository, which is also where the Pi installs its software
from. It is kept on the Pi only (`log-upload.json` in the dash's state folder, readable by
the dash and root), sent only to GitHub, never shown again or included in an upload. If
the Pi is lost or stolen, delete the token on GitHub.

## Setting it up (once)

1. On GitHub: Settings > Developer settings > Personal access tokens > Fine-grained
   tokens > Generate new token. Repository access: **Only select repositories**,
   `frogdash`. Permissions: **Contents: Read and write**. An expiry of a year is fine;
   make a new one when it runs out.
2. Turn on the dash's hotspot (Controls > Wi-Fi), open its page on the phone, enter the
   code, and under **Uploads** check the repository (`averyizatt/frogdash`) and paste
   the token. **Save**. **Stop uploading** deletes it.

Reading it: a recording is `gunzip`ped and opened in MegaLogViewer, or read with
`python tools/inspect_mlg.py file.mlg`.
