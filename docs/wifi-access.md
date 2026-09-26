# Wi-Fi hotspot and log transfer

**Controls → Wi-Fi** enables a discoverable, password-protected `Frogdash` hotspot
for 20 minutes. It starts off after boot. Join from your phone/laptop, open
`http://10.42.0.1:8081`, and enter the eight-digit access code displayed on the
dash. The mobile page downloads completed MLG files and shows CAN, module, GPS
and recording status. The current log becomes downloadable after rotation.
The Pages preview only simulates this setting and creates no wireless network.

## Requirements

Use Raspberry Pi OS with NetworkManager and an AP-capable Wi-Fi adapter. Pi models
without onboard Wi-Fi need a suitable USB adapter. Set the correct WLAN country
and enable the radio through `sudo raspi-config` before setup.

Activating the hotspot replaces the built-in radio's current Wi-Fi client
connection; perform initial installation from the Pi display or Ethernet. After
turning it off, NetworkManager may reconnect to saved networks according to its
existing autoconnect policy. The hotspot uses 2.4 GHz WPA2/CCMP and shared IPv4
addressing/DHCP. It needs no internet, although shared mode may forward an upstream
internet connection if one exists. `10.42.0.0/24` must not overlap other networks.
References: [Pi networking](https://www.raspberrypi.com/documentation/computers/configuration.html#connect-to-a-wireless-network),
[NetworkManager settings](https://networkmanager.dev/docs/api/latest/nm-settings-nmcli.html),
[nmcli](https://networkmanager.dev/docs/api/latest/nmcli.html).

## Install on the Pi

Install the checkout and virtual environment at `/opt/frogdash` first. The broker
runs as root, so the checkout, interpreter and dependencies must be root-owned
and not writable by unprivileged users.

```sh
sudo apt install network-manager
cd /opt/frogdash
sudo chown -R root:root /opt/frogdash
sudo python3 tools/setup_hotspot.py --interface wlan0 --ssid Frogdash
sudo cp hardware/systemd/frogdash-hotspot.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/frogdash.service.d
sudo cp config/hotspot-service.conf /etc/systemd/system/frogdash.service.d/hotspot.conf
```

The provisioner checks AP support and creates a non-autoconnecting profile. It
refuses to overwrite an existing configuration. It generates a 20-character Wi-Fi
password locally and stores it in root-readable files in `/etc/frogdash/` and
NetworkManager's system connection directory. It does not print the password.

Append the socket option to existing `/etc/default/frogdash` arguments, preserving
your GPS and logging choices:

```sh
FROGDASH_ARGS="--interface can0 --gpsd --log-dir /var/lib/frogdash/logs --hotspot-socket /run/frogdash-connect/control.sock"
sudo systemctl daemon-reload
sudo systemctl enable --now frogdash-hotspot.service
sudo systemctl restart frogdash
```

The `FROGDASH_ARGS` line above belongs **in the environment file**, not just in
an interactive shell. Controls → Wi-Fi then shows the network password, browser
address and separate dash access code while enabled. The code/browser session
change each time the transfer listener starts; the network password persists.
Turning it off drops ongoing transfers. Automatic timeout is 20 minutes.

## Service boundaries and recovery

The full dashboard stays unprivileged on `127.0.0.1:8080`. A root broker listens
only on `/run/frogdash-connect/control.sock`, restricted to `frogdash-connect`.
It can activate/deactivate one configured NetworkManager UUID and accepts no
arbitrary shell commands, profiles, SSIDs or file paths. Only the optional service
drop-in grants the dashboard this supplementary group.

The separate transfer server binds `10.42.0.1:8081`, requires a client address in
the hotspot subnet and the dash code, rate-limits login attempts, and uses an
HttpOnly SameSite cookie. It serves only transfer assets, status and completed
managed logs. There is no vehicle-command websocket, CAN transmitter, raw-frame
API, arbitrary-file access or remote system administration. Credentials are not
included in the vehicle state stream or logs. Do not port-forward this listener.

Normal dashboard shutdown asks the broker to disable the hotspot. Its own timer
also expires sessions after a dashboard crash. Broker startup disables any leftover
active profile before serving requests. Failed timeout shutdown is retried.

```sh
nmcli device status
nmcli -g WIFI-PROPERTIES.AP device show wlan0
systemctl status frogdash-hotspot frogdash
journalctl -u frogdash-hotspot -u frogdash -n 50
```

If a phone reports no internet, stay on the hotspot and enter its numeric address
manually. If the dash says the helper is unavailable, check profile provisioning,
the drop-in and socket argument. Authentication, isolation, expiry and browser
transfers are tested; actual AP broadcasting/radio switching requires Pi testing.
