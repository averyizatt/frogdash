# Console boot and startup measurement

Target hardware: Raspberry Pi 4, 4 GB RAM, microSD. The installed distribution
is not yet identified. **No physical cold-boot benchmark has been measured.**
Under 15 seconds from key-on to visible instruments is an optimization target,
not a measured result or a guarantee. Firmware, card, display initialization,
Linux services and Chromium startup all contribute. First boot after installing
packages or creating a browser profile is not representative of routine starts.

## Identify the current installation first

On the Pi, collect these read-only details before installing the console option:

```sh
cat /etc/os-release
uname -m
systemctl get-default
systemctl status display-manager --no-pager
systemd-analyze time
systemd-analyze critical-chain
systemd-analyze blame
```

An absent display-manager service is normal on a console-only installation.
The setup below targets a Debian/Raspberry Pi OS installation with systemd,
logind, PAM, KMS graphics and a native Chromium package. Other distributions,
including Chromium supplied through Snap, need their own package/session checks.
Do not replace the existing TunerStudio boot setup until this path has been
tested manually on the intended OS.

## Optional console kiosk

`hardware/systemd/frogdash-console@.service` starts Cage and Chromium as an
existing normal user on **tty7**, directly from `multi-user.target`. It needs
no desktop autologin or full desktop environment. It starts the Frogdash backend
in parallel and uses a small PAM session to give Cage access through logind.
Only one console instance should be enabled. Keep the ordinary tty1 login for
maintenance; Cage's `-s` option allows switching virtual terminals.

The readiness launcher polls local `/health` every 100 ms, with a 500 ms request
timeout. It launches Chromium on the first HTTP 200, even with no CAN/GPS data.
It bypasses HTTP proxies for loopback, uses no fixed startup sleep and keeps
Chromium's sandbox enabled. If HTTP is still unavailable after approximately
30 seconds, it exits and systemd retries after one second. It never changes
power controls, shutdown services, GPIO23 or GPIO24.

After confirming a compatible Debian/Pi OS installation, typical dependencies
are installed with:

```sh
sudo apt install cage chromium dbus-user-session libpam-systemd kbd
command -v cage chromium dbus-run-session chvt python3
ls -l /dev/dri
```

Keep the existing KMS display configuration; check display resolution and touch
input on the real panel. Do not add unrelated boot overlays or GPU flags. Cage
must have logind support. Test from a **local console**, as the intended normal
user, with the backend running and no desktop compositor owning the display:

```sh
sudo systemctl start frogdash
dbus-run-session -- cage -s -- python3 /opt/frogdash/tools/launch_kiosk.py --wayland --dedicated-profile
```

For automatic startup, copy the session files and enable **your actual username**
in place of `YOUR_USER` (do not use root):

```sh
sudo install -m 0644 /opt/frogdash/hardware/pam/frogdash-kiosk /etc/pam.d/frogdash-kiosk
sudo install -m 0644 /opt/frogdash/hardware/systemd/frogdash-console@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/frogdash-console@.service
sudo systemctl enable --now frogdash-console@YOUR_USER.service
```

This assumes `/opt/frogdash` already contains the repository, virtual environment
and installed `frogdash.service`. Do not run the old desktop kiosk, TunerStudio
autostart, or a display manager alongside Cage on the same seat. On an existing
desktop system, arrange the console target and stop its graphical session only
after confirming the distribution and retaining a working console/SSH login.
This template does not automatically disable another service or change the
default boot target.

The console uses `~/.config/frogdash-chromium` in that user's home. It persists
themes, uploads and display settings; it is separate from the ordinary Chromium
profile. Reusing the same user, profile and `http://127.0.0.1:8080/` origin keeps
those settings. The original desktop user-service template now uses the same
readiness launcher but retains the ordinary Chromium profile.

For another executable path or port, override the console's `ExecStart` with
`systemctl edit frogdash-console@YOUR_USER`, retaining Cage/session arguments
and adding launcher `--browser /path/to/chromium` or `--port NUMBER`. The backend
port must match. The launcher uses only Python's standard library.

To stop automatic console launch:

```sh
sudo systemctl disable --now frogdash-console@YOUR_USER.service
```

## Measure and optimize

```sh
journalctl -b -u frogdash -u frogdash-console@YOUR_USER -o short-monotonic
systemd-analyze critical-chain frogdash-console@YOUR_USER.service
```

The launcher logs `boot+...s` when it begins waiting and when it launches
Chromium. These timestamps start at kernel uptime, not relay key-on, and are
**not first-paint measurements**. Record several ordinary cold starts on video:
key-on, visible instruments, first live CAN readings, and first valid GPS speed.
GPS acquisition is independent and never gates UI startup. Systemd's reports
help identify service delays but do not capture the whole driver experience.

On Raspberry Pi OS, check the network-at-boot setting in `raspi-config`; the
dashboard needs only loopback and does not require Wi-Fi to connect. Remove
unnecessary waits only after the critical chain identifies them. Leave optional
Wi-Fi management available for the log-transfer feature. Keep the application's
splash off during timing. A decorative boot image hides messages but does not
shorten startup. Measure the existing microSD before deciding to replace it.

Sources: [Cage systemd sessions](https://github.com/cage-kiosk/cage/wiki/Starting-Cage-on-boot-with-systemd),
[Cage command-line options](https://github.com/cage-kiosk/cage/blob/master/cage.1.scd),
[Raspberry Pi configuration](https://www.raspberrypi.com/documentation/computers/configuration.html).
Launcher readiness, timeout, proxy handling and browser arguments have automated
tests. The actual PAM/logind/Cage/Chromium boot path still requires testing on
the Pi and its installed distribution.
