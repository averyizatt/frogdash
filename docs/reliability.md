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
from the USB GPS (gpsd feeds chrony):

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

The Pi needs internet on its built-in Wi-Fi. Join a network from the dash:
**Controls → Wi-Fi → Internet (for updates)**: Scan, pick the network, type the
password with the on-screen keyboard and Connect. The network is remembered and
rejoined automatically. One-time setup for that menu:

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

The line under the speed and **Sensors → System check → USB GPS** name the reason:

| Message | Meaning | What to do |
|---|---|---|
| Service not running | gpsd is not reachable | `sudo systemctl status gpsd` |
| Receiver not found | gpsd runs but nothing reports | Unplugged, or gpsd is watching the wrong port: check `DEVICES` above |
| No satellites heard | The receiver talks but hears nothing | No sky view, or strong radio noise |
| Signal too weak | Satellites heard, none strong enough | Radio noise: see below |
| Finding position | Good signals, no position yet | Wait; a first fix after a long break can take minutes |

**Radio noise is the usual cause in a car.** A Pi 4's blue USB 3 ports, the dash cam and
a Wi-Fi adapter all radiate right at GPS frequencies. A receiver plugged straight into
the Pi can hear nothing even under an open sky. Put it on a USB extension cable of a
metre or two, in a black USB 2 port, away from the Pi, the dash cam and the Wi-Fi
adapter. System check shows the strongest signal; a fix needs about 30 dB.

To look at it directly (the Terminal tab in Dash management works for this):

```sh
gpspipe -w -n 12 | grep -E '"class":"(TPV|SKY)"' | cut -c1-300
```
