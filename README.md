# Uploads from the dash Pi

This branch holds data, not code. After every update the Pi uploads here
(`tools/frogdash_upload.py` on `main`):

- `pi/<date>/<time>-diagnostics.json`: self check, every helper's status, the last failed start
- `pi/<date>/<time>-boot.txt`: boot timing, kiosk start, display modes
- `pi/<date>/<time>-journal.txt`: the dash's own service logs since the Pi started

and each drive's recordings, gzip-compressed MLG, as files of a release named
`drive-<date>-<time>` (gunzip, then open in MegaLogViewer).

Recordings include GPS positions; that is intended. Wi-Fi passwords and network names,
the hotspot password and the phone page's code are blanked out before upload.
