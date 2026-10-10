# Watchdogs and automatic recovery

What keeps the dash running without a keyboard, from the bottom up.

| Layer | Failure | Recovery |
| --- | --- | --- |
| Whole Pi | Kernel/SD hang, brownout lock-up | Hardware watchdog reboots the Pi after 15 s (`system.conf.d/frogdash-watchdog.conf`, install below) |
| Dash service | Python crash | `Restart=on-failure` after 2 s, never gives up (`StartLimitIntervalSec=0`) |
| Dash service | Event loop frozen | systemd watchdog (`WatchdogSec=20`); the loop pings every 2 s, systemd kills and restarts it |
| Screen | Browser crash | `frogdash-console@` restarts it after 1 s, unlimited |
| Screen | Browser frozen while the service is alive | Kiosk launcher restarts the browser when the page stops rendering for about 20-30 s |
| CAN interface | Not up at boot | `frogdash.service` pulls in `frogdash-can.service` |
| CAN interface | MCP2515 driver reset (can0 disappears/reappears) | `frogdash-can.service` restarts whenever can0 appears |
| CAN bus | Bus-off (wiring fault, no ACK) | Kernel restarts the controller after 100 ms (`restart-ms 100`) |
| CAN socket | Read error | Reopened after 1 s; send failures (full TX queue, nothing ACKing) never drop reception |
| Duplicate senders | Another node sends GPS 0x203 or engine RPM 0x309 | The dash stops its own copy for that run and shows BLOCKED |
| Stale data | A module goes quiet | Every value expires on its own timeout and shows stale/offline, never a frozen number |
| Controls | Command lost | Each command waits for an acknowledgement; 3 s without one shows "outcome unknown" |
| Pump test | Dash or link lost | The meth controller stops a remote test after 3 s without traffic |
| Interior lights | Dash stops | The gateway turns lights off 5 s after the last command; the dash restores them after a restart |
| Reverse camera / dash cam | Feed stalls or drops | Shown as CAMERA LOST / DASHCAM OFFLINE (never a frozen image) and reconnected automatically |
| Dash cam Wi-Fi | Camera off or out of range | NetworkManager reconnects (set unlimited retries below) |

Not automatic: a dash cam whose own web server has stopped answering needs a power
cycle (normally the ignition does this), and failed hardware (camera ribbon, CAN
wiring) shows up as a clear message rather than being retried forever.

## One-time setup on the Pi

```sh
cd /opt/frogdash && sudo git pull --ff-only
sudo cp hardware/systemd/frogdash.service hardware/systemd/frogdash-can.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system.conf.d
sudo cp hardware/systemd/system.conf.d/frogdash-watchdog.conf /etc/systemd/system.conf.d/
sudo systemctl daemon-reexec
sudo systemctl reenable frogdash-can.service
sudo nmcli con modify dashcam connection.autoconnect yes connection.autoconnect-retries 0
sudo systemctl restart frogdash.service
```

Check the hardware watchdog is armed: `systemctl show -p RuntimeWatchdogUSec`
should print `RuntimeWatchdogUSec=15s`, and `dmesg | grep -i watchdog` should show
the bcm2835 watchdog.

## Clock from GPS

The Pi has no battery-backed clock and the car has no internet, so set the time
from the USB GPS (gpsd feeds chrony). The Pi setup does the first three lines itself on
the next **Update now** with internet; only the time zone is yours to set:

```sh
sudo apt install -y chrony
sudo cp hardware/chrony/frogdash-gps.conf /etc/chrony/conf.d/
sudo systemctl restart chrony gpsd
sudo timedatectl set-timezone America/Denver
```

`chronyc sources` shows `#* GPS` once it has locked (needs a GPS fix). The dash
clock follows within a minute. Pick your own zone with `timedatectl list-timezones`.

## Updating in the car (no Ethernet)

**Dash management → Support & testing → Update now** pulls the latest version from
GitHub and restarts the dash. It only fast-forwards; a failed download or local
changes leave the running version untouched, and the result is shown next to the button.

**A bad update undoes itself.** After the restart the new version has to prove itself:
the service must come up, answer on its health page and stay up for 15 s, and the
screen must reconnect if it was connected before. If it does not, the updater puts the
previous version back (code and unit files), restarts it, and reports "Update undone".
That commit is not installed again; **Update now** waits for a newer one. The failed
start is saved for the fix:

```sh
cat /var/lib/frogdash/update-failure.log
```

**Undo update** (press twice) returns to the version before the last update when a
version runs but misbehaves. **Update now** goes forward to the newest again. From a
terminal: `sudo sh /opt/frogdash/tools/frogdash_update.sh rollback`.

One-time setup:

```sh
cd /opt/frogdash && sudo git pull --ff-only
sudo cp hardware/systemd/frogdash-update.service hardware/systemd/frogdash-update.path /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now frogdash-update.path
```

That is the only thing that ever needs a keyboard or SSH. Everything else a version
needs on the Pi is done for it, as root, by the updater.

### Pi setup: nothing to type after an update

`tools/frogdash_setup.sh` holds every system-side requirement as a step. The updater
runs it after each update that passed its check, and again on **Update now** when
already up to date. Each step looks first and acts only when something is missing, so
running it again changes nothing. It is always the new version's script that runs, so a
new requirement arrives with the update that needs it.

| Step | What it does | Needs internet |
|---|---|---|
| Dash helpers | Installs and enables the Wi-Fi and GPS recovery helpers and the Wi-Fi keeper | No |
| GPS service | Points gpsd at the GPS receiver only (`USBAUTO="false"`, `-n`, starts with the Pi) | No |
| Clock from GPS | Installs chrony and its GPS setting | First time |
| TunerStudio: Java and display | Installs `xwayland` and `default-jre` | First time |
| TunerStudio: program | Downloads TunerStudio MS from tunerstudio.com (checked against a known SHA-256) into the screen user's home | First time |
| TunerStudio: serial port | Adds the screen user to `dialout`, then restarts the screen once | No |

A step that needs the internet waits and says so; **Update now** with Wi-Fi connected
runs it. The first run downloads Java and TunerStudio (about 300 MB) and can take
several minutes: the update status says it is finishing the Pi setup.

**System check → Updates** lists every step with its result. **Pi setup** there says
whether this version's setup has run.

The dash also checks by itself: about 10 s after it starts, if the setup script is not
the one that last ran, it asks the updater to run it (the request word `setup`: the
updater runs the script and does nothing else). That covers an update installed by an
older updater.

Still by hand, because they are choices or need a password, not requirements of an
update: the first install of the Pi, options in `/etc/default/frogdash` (`--terminal`,
`--camera`, `--dashcam`), the dash cam's Wi-Fi profile, the time zone, and flashing the
ESP32 and the Nano.

The Pi needs internet on its built-in Wi-Fi. Join a network from the dash:
**Controls → Wi-Fi → Internet (for updates)**: Scan, pick the network, type the
password with the on-screen keyboard and Connect. The network is remembered and
rejoined automatically. Its helper is installed by the Pi setup above; by hand it is:

```sh
sudo cp hardware/systemd/frogdash-wifi.service hardware/systemd/frogdash-wifi.path /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now frogdash-wifi.path
```

Passwords are never stored in this repository; NetworkManager keeps them on the Pi.
The same thing from a terminal:

```sh
sudo nmcli dev wifi connect "<network name>" password "<password>" ifname wlan0
```

The update also refreshes any installed systemd unit files that changed. From a
laptop on the same hotspot you can still use `ssh` and `sudo sh
/opt/frogdash/tools/frogdash_update.sh`. Firmware for the ESP32 modules and the
Nano is separate and still flashed over USB.

## One Wi-Fi adapter for the dash cam and internet

If the Pi's built-in Wi-Fi cannot reach your networks (for example it only receives
5 GHz, or your router rejects it), one USB adapter does both jobs:

- **Wi-Fi keeper** (`frogdash-netkeeper.service`) keeps the adapter on the dash cam. Every
  10 s, if the dash cam connection is down and nothing is borrowing the adapter, it
  rescans and reconnects. No commands needed after an update, a reboot or a dash cam restart.
  The Pi setup installs the service itself; the commands below are only for doing it by hand.
- **Update now** borrows the adapter: joins a saved network in range, updates, hands it back.
- **Controls > Wi-Fi > Internet** borrows it too when `/etc/frogdash/wifi-internet` names
  that adapter: Scan and Connect save a network for updates, then return to the dash cam.

```sh
sudo cp hardware/systemd/frogdash-netkeeper.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now frogdash-netkeeper.service
sudo mkdir -p /etc/frogdash && echo wlan1 | sudo tee /etc/frogdash/wifi-internet
```

Give the dash cam connection a fixed address (its DHCP is slow) and keep saved
internet networks from grabbing the adapter on their own:

```sh
sudo nmcli con modify dashcam ipv4.method manual ipv4.addresses 192.168.169.88/24 ipv4.never-default yes
sudo nmcli con modify home connection.autoconnect no connection.interface-name ""
```

To use the adapter by hand for a while (the keeper would otherwise take it back),
hold the lock: `sudo touch /run/frogdash-wifi.lock`; it expires after 5 minutes, or
`sudo rm /run/frogdash-wifi.lock` to release it.

## GPS dropouts: wheel-speed fallback and dead reckoning

`hardware/frogdash/nav.py` fuses the USB GPS with the sensor gateway's wheel speed so
speed and position do not blank when the fix drops (tunnels, garages, canyon walls,
the first seconds after start-up).

| Situation | Speed shown | Position on the map |
| --- | --- | --- |
| GPS has a fix | GPS speed | GPS (green arrow) |
| Fix lost, wheel sensor working | Calibrated wheel speed, labelled **WHEEL SPEED · GPS LOST** | Estimated (amber arrow, dashed accuracy circle) |
| Fix lost, no wheel speed, first 4 s | Last GPS speed, labelled **GPS SPEED · HOLDING** | Carried along the road at that speed (amber arrow) |
| Fix lost, no wheel speed, after 4 s | Unavailable | Last position (grey arrow) |
| Just started, no fix yet | Wheel speed if moving | Last saved position until the fix arrives |

- **Calibration.** While both are live above 30 km/h (19 mph), the wheel-speed scale is
  learned from GPS and saved, so tyre size and sensor differences cancel out. System
  check shows whether it is calibrated yet.
- **Dead reckoning.** Distance comes from wheel speed. Direction comes from following
  the road in the bundled street map: the estimate snaps to the road being driven and
  follows its bends, continuing onto the road that needs the least turn at each end.
  Off the map, or off a mapped road, it carries straight on along the last heading.
- **Limits.** There is no gyro or compass, so a turn at a junction during a dropout
  cannot be seen; the estimate takes the straightest continuation. The accuracy figure
  grows with distance (about 3% on a mapped road, 25% off-road) and the GPS position
  replaces the estimate the moment a fix returns. Raw `gps.*` signals stay unavailable
  during a dropout; the fused values are `nav.*`.
- **Trips and odometer** keep counting on wheel speed during a dropout.

GPS input hardening: a gpsd connection that delivers nothing for 10 s is reopened; a
receiver that re-plugs under another device name is followed after 10 s of silence
(unless one was named with `--gps-device`); the last position and calibration are saved
every 20 s in `nav.json`.

For the receiver itself, start gpsd without waiting for a client and give it a stable
device path in `/etc/default/gpsd`:

```sh
ls -l /dev/serial/by-id/        # copy the name of your GPS
sudo nano /etc/default/gpsd     # DEVICES="/dev/serial/by-id/<that name>"  GPSD_OPTIONS="-n"  USBAUTO="false"
sudo systemctl restart gpsd.socket gpsd
```

`USBAUTO="false"` matters once any other USB serial device is plugged into the Pi, such
as the MicroSquirt cable for TunerStudio: with it on, gpsd opens every USB serial
adapter and probes it as a GPS, which can leave it watching the wrong port and sends
stray bytes to the ECU.

### No speed: what the dash tells you

When there is no speed, the reason takes the place of the speed digits, in every gauge
style, with what the dash is trying under it. **Sensors → System check → USB GPS** shows
the same reason with the fix.

| Message | Meaning | What to do |
|---|---|---|
| GPS starting | The first 15 s after the dash starts | Nothing: not a fault yet |
| Service not running | gpsd is not reachable | `sudo systemctl status gpsd` |
| Receiver not found | gpsd runs but nothing reports | Unplugged, or gpsd is watching the wrong port: check `DEVICES` above |
| No satellites heard | The receiver talks but hears nothing | No sky view, or strong radio noise |
| Signal too weak | Satellites heard, none strong enough | Radio noise: see below |
| Finding position | Good signals, no position yet | Wait; a first fix after a long break can take minutes |

### GPS recovery: what the dash tries by itself

A watchdog (`hardware/frogdash/gpswatch.py`) works through these steps and announces
each one where the speed would be. A position at any point stops it.

| Problem | Step | When |
|---|---|---|
| Service not running | Restart the GPS service | After 5 s |
| Receiver not found | Restart the GPS service | After 15 s |
| | Look for the receiver on the USB ports and point gpsd at it | 25 s later |
| | Reset the receiver's USB connection (as if unplugged and replugged) | 25 s later |
| | Start again from the top | Every 5 minutes |
| Receiver reports, no position | Restart its satellite search (u-blox command) | After 2 minutes |
| | Clear its memory and search from nothing, once | 3 minutes later |
| | Restart the search again | Every 15 minutes |

The first three steps need root, which the dash does not have. A small helper does
them. The Pi setup installs it with the update that brings it (see **Pi setup** above);
nothing needs typing. By hand it would be:

```sh
cd /opt/frogdash
sudo cp hardware/systemd/frogdash-gps.service hardware/systemd/frogdash-gps.path /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now frogdash-gps.path
```

The helper (`tools/frogdash_gps.sh`) does only those three things. The dash asks by
leaving one word (`restart`, `repin` or `usb`) in its data folder; anything else is
refused. Until it is installed, the dash says so under the reason and in System check
(**GPS recovery helper**), and the satellite-search restarts still work.

"Look for the receiver" sets `DEVICES`, `GPSD_OPTIONS="-n"` and `USBAUTO="false"` in
`/etc/default/gpsd` (the original is kept as `/etc/default/gpsd.frogdash-bak`), and
only when exactly one device in `/dev/serial/by-id/` names itself as a GPS (u-blox,
GPS, GNSS, GlobalSat). A receiver that appears as a plain serial adapter, such as a
Prolific-based BU-353, is never guessed at, because the MicroSquirt tuning cable looks
the same: the dash lists what is plugged in and `DEVICES` is set by hand, as above.

Run a step by hand: `sudo sh /opt/frogdash/tools/frogdash_gps.sh repin`.

### Getting a position sooner

**System check → Time to first position** shows how long it took after the dash started.

- gpsd starts with the Pi and reads the receiver from the first second (`-n`, and
  `gpsd.service` enabled), instead of starting when the dash first asks. The helper's
  restart and "look for the receiver" steps set both.
- The dash retries the GPS service four times a second while it comes up.
- A 2D position is enough for speed; it does not wait for altitude.
- What software cannot change: the receiver loses power with the ignition. One with a
  backup battery or capacitor keeps its satellite data and has a position in a few
  seconds if the car was off for under about four hours; one without starts from
  nothing every time, about 30 s under a clear sky and much longer with a weak
  signal. If the time shown is always over a minute, it is the receiver or the noise
  around it, not the Pi.

**Radio noise is the usual cause in a car.** A Pi 4's blue USB 3 ports, the dash cam and
a Wi-Fi adapter all radiate right at GPS frequencies. A receiver plugged straight into
the Pi can hear nothing even under an open sky. Put it on a USB extension cable of a
metre or two, in a black USB 2 port, away from the Pi, the dash cam and the Wi-Fi
adapter. System check shows the strongest signal; a fix needs about 30 dB.

To look at it directly (the Terminal tab in Dash management works for this):

```sh
gpspipe -w -n 12 | grep -E '"class":"(TPV|SKY)"' | cut -c1-300
```
