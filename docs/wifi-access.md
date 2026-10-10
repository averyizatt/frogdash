# The dash on your phone: logs, faults and updates over Wi-Fi

The dash has its own Wi-Fi network. On the dash: **Controls → Wi-Fi → turn the hotspot
on**. It stays on for 20 minutes and is off after every boot. The tab shows the network
name, its password, the address to open and an eight-digit access code.

On your phone or laptop:

1. Join the Wi-Fi network shown (`Foxbody Dash` on a new install). The phone may say it
   has no internet; stay on it.
2. Open `http://10.42.0.1:8081` in the browser.
3. Enter the access code from the dash.

The page gives you:

| | |
|---|---|
| **Faults and system check** | Everything the dash's System check found, faults first, each with what to do about it |
| **Download diagnostics file** | One file with the system check, every current reading, helper results and the last failed start. Send it when something needs looking at |
| **Software** | The installed version, **Update now** and **Undo last update** (two presses each, as on the dash), and **Install gateway firmware** when a new build is ready ([firmware-updates.md](firmware-updates.md)) |
| **Drive review** | The recorded drives |
| **Saved logs** | Tap a file to save it. **Finish the current log** closes the file being recorded so it can be downloaded too; recording carries on in a new one |

**Updating from the phone.** The dash needs internet for an update, which the hotspot
does not provide: it joins a saved Wi-Fi network in range (your home network in the
driveway) with its other adapter, as **Update now** on the dash does. The dash restarts
during the update. The hotspot stays up and your login stays valid for 15 minutes, and
the page follows the update until it reports the result. Your phone cannot be the
internet source at the same time as it is joined to the dash's network.

The Pages preview only simulates this setting and creates no wireless network.

## Setup: nothing to type

The Pi setup (see [reliability.md](reliability.md), *Pi setup*) creates the hotspot the
next time the dash updates: **System check → Updates → Phone hotspot** shows the result.
It picks a Wi-Fi adapter that can be an access point, one the dash cam does not use if
there is one, generates a 20-character password on the Pi, installs the helper, and
restarts the dash once so it may use it.

**With one adapter, the hotspot has priority over the cameras.** If the only adapter
that can be an access point is the dash cam's, the hotspot is made on it. Switching the
hotspot on then drops the dash cam's Wi-Fi: the Dashcam view and the reverse view say
the cameras are off, and the dash stops trying to reach them. Switching it off (or its
20-minute limit) hands the adapter back and the cameras reconnect within about 10
seconds. The dash cam itself keeps recording to its own card the whole time. In this
arrangement an update started from the phone also needs that adapter for the internet,
so the hotspot drops while the update runs; switch it back on afterwards to see the
result. With two adapters none of this applies.

Use Raspberry Pi OS with NetworkManager and the WLAN country set. The hotspot uses
2.4 GHz WPA2/CCMP and shared IPv4 addressing/DHCP on `10.42.0.0/24`, which must not
overlap other networks. An existing hotspot profile is never overwritten.

By hand, the same steps are:

```sh
cd /opt/frogdash
sudo python3 tools/setup_hotspot.py --interface wlan0 --ssid "Foxbody Dash"
sudo cp hardware/systemd/frogdash-hotspot.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/frogdash.service.d
sudo cp config/hotspot-service.conf /etc/systemd/system/frogdash.service.d/hotspot.conf
sudo systemctl daemon-reload
sudo systemctl enable --now frogdash-hotspot.service
sudo systemctl restart frogdash
```

The dash finds the helper at `/run/frogdash-connect/control.sock` by itself; the
`--hotspot-socket` option is only needed for a different path. The password is stored in
root-readable files in `/etc/frogdash/` and NetworkManager's system connection directory,
and is shown only on the dash while the hotspot is on. The access code and browser
session change each time the hotspot is switched on; the network password persists.
Turning it off drops ongoing transfers.

## Service boundaries and recovery

The full dashboard stays unprivileged on `127.0.0.1:8080`. A root broker listens
only on `/run/frogdash-connect/control.sock`, restricted to `frogdash-connect`.
It can activate/deactivate one configured NetworkManager UUID and accepts no
arbitrary shell commands, profiles, SSIDs or file paths. Only the optional service
drop-in grants the dashboard this supplementary group.

The separate transfer server binds `10.42.0.1:8081`, requires a client address in
the hotspot subnet and the dash code, rate-limits login attempts, and uses an
HttpOnly SameSite cookie. It serves the page, status, the system check, the
diagnostics file and completed managed logs, and accepts four fixed actions: finish
the current log, update, undo the last update, and install the gateway firmware
already on the Pi (the same request the dash's own
buttons make; the update itself is done by the root update helper). There is no
vehicle-command websocket, CAN transmitter, raw-frame API, arbitrary-file access,
command line or any other system administration. Credentials are not
included in the vehicle state stream or logs. Do not port-forward this listener.

Normal dashboard shutdown asks the broker to disable the hotspot, except during the
15 minutes after an update was started from the phone. Its own timer
also expires sessions after a dashboard crash. Broker startup disables any leftover
active profile before serving requests. Failed timeout shutdown is retried.

```sh
nmcli device status
nmcli -g WIFI-PROPERTIES.AP device show wlan0
systemctl status frogdash-hotspot frogdash
journalctl -u frogdash-hotspot -u frogdash -n 50
```

If a phone reports no internet, stay on the hotspot and enter its numeric address
manually. If the dash says the hotspot is not set up, press **Update now** and look at
**System check → Updates → Phone hotspot**. Authentication, isolation, expiry and browser
transfers are tested; actual AP broadcasting/radio switching requires Pi testing.
