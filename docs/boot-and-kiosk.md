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
The service uses `Type=simple` with a bounded post-start helper. The helper waits
for the main process's PAM-created session ID, verifies its user, leader PID,
TTY and PAM service with logind, then activates that exact session. It retries
registration every 100 ms for up to eight seconds; it adds no fixed startup delay.
`TimeoutStartSec=20` also bounds service activation. `Type=exec` was tested on the
bench but left this Pi stuck in `activating/start` despite successful rendering,
so it is not used with this PAM setup. Only one console instance should be enabled. Keep the ordinary tty1 login for
maintenance; Cage's `-s` option allows switching virtual terminals.

The readiness launcher polls local `/health` every 100 ms, with a 500 ms request
timeout. It launches Chromium on the first HTTP 200, even with no CAN/GPS data.
It bypasses HTTP proxies for loopback, uses no fixed startup sleep and keeps
Chromium's sandbox enabled. If HTTP is still unavailable after approximately
30 seconds, it exits and systemd retries after one second. It never changes
power controls. The backend is no longer ordered after `network.target`: its
HTTP and gpsd connections use loopback, and sensor/hotspot connections retry
independently. NetworkManager can start in parallel. Install the separate [PiSugar power setup](pisugar-power.md) for
ignition-loss shutdown; the previous GPIO23/24 relay design is retired.

After confirming a compatible Debian/Pi OS installation, typical dependencies
are installed with:

```sh
sudo apt install cage chromium dbus-user-session libpam-systemd kbd
command -v cage chromium dbus-run-session loginctl python3
ls -l /dev/dri
```

Keep the existing KMS display configuration; check display resolution and touch
input on the real panel. Do not add unrelated boot overlays or GPU flags. Cage
must have logind support. Test from a **local console**, as the intended normal
user, with the backend running and no desktop compositor owning the display:

```sh
sudo systemctl start frogdash
dbus-run-session -- cage -s -m last -- python3 /opt/frogdash/tools/launch_kiosk.py --wayland --dedicated-profile --allow-audio
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
profile. The dedicated profile uses Chromium `--password-store=basic` to avoid
unattended GNOME/KWallet prompts and D-Bus activation timeouts. This store does
not provide desktop-keyring encryption; keep it for the local dash and do not
save website passwords in it. Ordinary desktop profiles keep their normal
password-store selection. Reusing the same user, profile and `http://127.0.0.1:8080/` origin keeps
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

For monitor speakers, the supplied units enable startup audio in Chromium.
Select the HDMI output in Linux, enable warning chimes in Drive > Alerts and
verify audibility following [screen audio setup](screen-audio.md). No audio
readiness wait is added to the boot path.

## Measure and optimize

```sh
journalctl -b -u frogdash -u frogdash-console@YOUR_USER -o short-monotonic
systemd-analyze critical-chain frogdash-console@YOUR_USER.service
```

For a single read-only report, run:

```sh
python3 /opt/frogdash/tools/boot_report.py --user foxbody
```

Substitute the actual kiosk username. Use `sudo` if journal access is denied.
The report includes OS, kernel/userspace boot time, critical chains, startup
units, launch logs and DRM connector modes. It changes no settings. Missing
utilities and individual command timeouts are reported without aborting.

The launcher logs `boot+...s` at these stages:

- Waiting for local HTTP: the Cage session has started the launcher.
- HTTP ready; launching Chromium: the local service accepts requests.
- First render heartbeat observed: the browser has rendered the dashboard and
  its heartbeat has reached the backend. This is observed at the supervisor's
  next poll; heartbeat and polling intervals are each two seconds. It is an
  upper-bound observation with a few seconds of sampling/transport delay, **not
  the instant of first paint or proof the physical screen is showing gauges**.
  A configured splash can still cover the instruments.

These timestamps start at kernel uptime, not ignition key-on. A kiosk restart
later in the same boot reports its later uptime; use a cold start for comparisons.
Record several ordinary cold starts on video: key-on, visible instruments,
first live CAN readings, and first valid GPS speed. GPS acquisition is independent
and never gates UI startup. Systemd's reports help identify service delays but
do not capture the whole driver experience.

### Updating an existing console installation

With external power present, update the checkout and installed backend unit:

```sh
cd /opt/frogdash
sudo git pull --ff-only
sudo install -m 0644 hardware/systemd/frogdash.service /etc/systemd/system/frogdash.service
sudo install -m 0644 hardware/systemd/frogdash-console@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart frogdash.service
sudo systemctl restart frogdash-console@foxbody.service
```

The kiosk restart briefly blanks the display and loads the new timing logger.
No PiSugar services or user environment files are replaced. Existing systemd
drop-ins still apply; inspect `systemctl show frogdash -p After` if a network
ordering remains. For cold-start measurements, perform a normal safe shutdown,
let PiSugar switch its output off, restore input power and run the report.
Do not count the update/restart itself as a boot benchmark.

### Reading the bench measurement

The September 29 bench report reached `multi-user.target` in **5.570 seconds of
userspace**. The backend was ordered after `network.target` at 3.513 seconds;
`gpsd.socket` was already ready at 2.314 seconds. Removing the network ordering
allows earlier startup (roughly 1.2 seconds of dependency spacing in this sample),
but CPU/I/O contention and other ordering can reduce any actual saving. The
backend's 2.033-second activation is not the Chromium startup time. Kernel,
firmware and monitor wake times were not included in the supplied output.
Measure again before changing other services or claiming a key-on startup time.

### Fix repeated kiosk restarts before timing

A later bench log showed seven kiosk restarts by kernel uptime 60 seconds,
including exit status 1. The user-session journal then revealed a Cage timeout
waiting for an active DRM session, a first browser-render watchdog restart,
and a GNOME Secret Service activation timeout. The post-start helper addresses activation before PAM registration, and the
dedicated profile's basic store removes the keyring dependency. A temporary
`Type=exec` change produced successful browser heartbeats in 4.03/4.04 seconds
after launch but left systemd waiting for process-start confirmation; the final
unit uses `Type=simple` plus explicit registered-session activation. The initial helper used comma-separated `loginctl` properties, which return
no fields on the Pi's version. It now requests each property separately.
The corrected helper subsequently activated session c16, but two earlier attempts
still timed out before a PAM session opened. `TTYVHangup=yes` is a likely startup
race: systemd v252 resets the terminal before each executed command, including
`ExecStartPost`, potentially hanging up the main process as it starts. Terminal
hangup/disallocation are now disabled; ordinary terminal reset is retained.
This correction and cold-boot timing still need confirmation on the Pi; the log alone
cannot establish that every missed render was caused by the keyring. The
EDID warning should be investigated if screen mode or HDMI initialization
remains incorrect after startup is stable.

That restart sequence is a startup failure, not a cold-boot benchmark.
`Type=simple` can report the kiosk as started before Cage/Chromium are ready.
The unit's short activation time therefore does not establish display readiness.
The console also waits for `systemd-user-sessions`; retain that login/session
ordering rather than weakening it to shorten the critical chain.

PAM/logind can place child processes in user session scopes. If the service
journal contains only systemd start/stop lines, also inspect the user's journal:

```sh
sudo journalctl -b -o short-monotonic --no-pager _UID=$(id -u foxbody) -n 120
systemctl show frogdash-console@foxbody -p NRestarts -p Result -p ExecMainStatus
```

The boot report includes these diagnostics. Investigate the actual Cage/seat,
Chromium or launcher error before changing GPU options, deleting the browser
profile or extending the render watchdog grace period. A surviving manual
Chromium instance can also prevent a supervised browser from owning its profile;
check running processes if the log reports a profile lock. Keep one kiosk owner
and preserve the profile's saved appearance settings.

For a clipped HDMI dashboard, capture the kiosk's actual browser layout after
it has rendered:

```sh
curl -s http://127.0.0.1:8080/ui/display
```

This local-only endpoint reports the latest kiosk heartbeat's screen and browser
viewport sizes, dashboard bounds, CSS positioning, browser version and responsive
stylesheet presence. `fresh` means sampled within ten seconds; `waiting` means no
layout report has arrived. Browser geometry does not prove the HDMI monitor is
showing every pixel: if the bounds fit, investigate the output mode and monitor
scaling next. Reports stay in memory and are not written to the SD card.

The console starts Cage with `-m last`, using one output instead of its default
extended layout. A 1920x1080 screen with a 3840x1080 browser viewport indicates
that the app is receiving a wider desktop than the visible monitor. Do not
compensate by hard-coding a CSS resolution; inspect the connectors and compositor
configuration. With multiple connected outputs, `last` selects the last one
Cage discovers, which may differ from the intended dash. Disconnect unused
outputs during bench testing and verify the viewport again after restarting.


On Raspberry Pi OS, check the network-at-boot setting in `raspi-config`; the
dashboard needs only loopback and does not require Wi-Fi to connect. Remove
unnecessary waits only after the critical chain identifies them. Leave optional
Wi-Fi management available for the log-transfer feature. Keep the application's
splash off during timing. A decorative boot image hides messages but does not
shorten startup. Measure the existing microSD before deciding to replace it.

Sources: [systemd terminal setup](https://github.com/systemd/systemd/blob/v252/src/core/execute.c),
[Chromium Linux password storage](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/password_storage.md),
[systemd network ordering](https://systemd.io/NETWORK_ONLINE/),
[Cage systemd sessions](https://github.com/cage-kiosk/cage/wiki/Starting-Cage-on-boot-with-systemd),
[Cage command-line options](https://github.com/cage-kiosk/cage/blob/master/cage.1.scd),
[Raspberry Pi configuration](https://www.raspberrypi.com/documentation/computers/configuration.html).
Launcher readiness, timeout, proxy handling and browser arguments have automated
tests. The actual PAM/logind/Cage/Chromium boot path still requires testing on
the Pi and its installed distribution.
