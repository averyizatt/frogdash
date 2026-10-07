# TunerStudio on the dash screen

With a keyboard and mouse plugged into the Pi, TunerStudio can run on the dash's own
screen: **menu → TunerStudio**, or **Dash management → TunerStudio → Open TunerStudio**.
It opens over the dash; exit it and the gauges come back.

TunerStudio is a separate desktop program, not a page of the dash. It talks to the
MicroSquirt over the **USB serial cable**, exactly as it does from a laptop. The dash
keeps reading the engine over CAN at the same time, so the two do not share a connection.

## One-time setup on the Pi

Run these as the user the dash screen runs as (the name after `frogdash-console@`).

```sh
sudo apt install -y xwayland default-jre
sudo usermod -aG dialout "$USER"
```

- `xwayland` lets the kiosk show an older-style desktop program such as TunerStudio.
- `default-jre` is Java. It must be the full package, not `default-jre-headless`.
- `dialout` gives your user the serial port.

Download the **Linux** version of TunerStudio MS from
<https://www.tunerstudio.com/index.php/downloads> and unpack it into your home folder,
so the start script is `~/TunerStudioMS/TunerStudio.sh`:

```sh
tar -xzf TunerStudioMS_*.tar.gz -C ~
ls ~/TunerStudioMS/TunerStudio.sh
sudo reboot
```

After the reboot the **TunerStudio** icon appears in the dash menu. The dash looks in
`~/TunerStudioMS`, `/opt/TunerStudioMS` and `/usr/local/TunerStudioMS`. For any other
folder, set it for the screen service:

```sh
sudo systemctl edit "frogdash-console@$USER"
# add:
# [Service]
# Environment=FROGDASH_TUNERSTUDIO=/path/to/TunerStudioMS
```

## First run

1. Plug in the keyboard, the mouse and the USB serial cable to the MicroSquirt.
2. Open TunerStudio from the dash. Java takes several seconds to show its window.
3. Enter your registration, then create or open your project. To reuse the laptop's
   project, copy its folder into `~/TunerStudioProjects/` on the Pi.
4. In **Communications → Settings** choose the serial port (usually `/dev/ttyUSB0`)
   and the MicroSquirt's baud rate (115200), then **Test Port**.

## Using it

- **Exit:** File → Exit returns to the dash. Without a keyboard, hold **OFF** on the
  steering wheel for about two seconds: the dash closes TunerStudio.
- **Stopped only:** it will not open while the dash sees the car moving (speed above
  5 km/h). With no speed reading at all, such as in a garage without a GPS fix, it opens.
- **The dash underneath keeps running:** logging, alerts, CAN and the dash cam carry on.
  Only the picture is covered.
- **Burn your changes** in TunerStudio before exiting, as on a laptop. Closing it from
  the steering wheel does not ask first.

## Limits

- The screen is 1920 × 720 and the dash hump covers the bottom centre. Tall
  TunerStudio dialogs may be cramped; move them with the mouse.
- A Pi 4 runs TunerStudio more slowly than a laptop.
- TunerStudio cannot tune through the Pi's CAN module; the serial cable is required.

## If it does not open

The status line under the button says why. The usual causes:

| Message | Fix |
|---|---|
| TunerStudio is not installed | Unpack it into `~/TunerStudioMS` (above) |
| The screen has no X display | `sudo apt install xwayland`, then reboot |
| Closed right after starting | `sudo apt install default-jre`; see the log below |
| Only on the dash screen in the car | The dash is not running in its kiosk (for example a browser on a laptop) |

```sh
journalctl -u "frogdash-console@*" -n 40
```

## How it works

The dash service is sandboxed and cannot start programs on the screen. The kiosk
launcher (`tools/launch_kiosk.py`) already runs in the screen session as your normal
user and supervises Chromium. Every two seconds it reports to the dash
(`POST /tune/kiosk`) and collects any open or close request (`hardware/frogdash/tune.py`).
It starts `TunerStudio.sh` as your user, with no extra privileges, and pauses the
frozen-screen watchdog while TunerStudio covers the dash.
