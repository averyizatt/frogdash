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
