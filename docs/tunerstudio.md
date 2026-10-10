# TunerStudio on the dash screen

With a keyboard and mouse plugged into the Pi, TunerStudio can run on the dash's own
screen: **menu → TunerStudio**, or **Dash management → TunerStudio → Open TunerStudio**.
It opens over the dash; exit it and the gauges come back.

TunerStudio is a separate desktop program, not a page of the dash. It talks to the
MicroSquirt over the **USB serial cable**, exactly as it does from a laptop. The dash
keeps reading the engine over CAN at the same time, so the two do not share a connection.

## Setup on the Pi: press Update now

Nothing is typed on the Pi. With Wi-Fi connected, press **Dash management → Support →
Update now**. The update's Pi setup (`tools/frogdash_setup.sh`) does all of this the
first time, which takes several minutes:

- installs `xwayland`, which lets the kiosk show an older-style desktop program;
- installs `default-jre` (Java, the full package, not the headless one);
- downloads TunerStudio MS for Linux from <https://www.tunerstudio.com> into the screen
  user's home (`~/TunerStudioMS`) after checking it against a known SHA-256;
- adds the screen user to the `dialout` group for the serial port;
- points the Pi's GPS service at the GPS receiver only (`USBAUTO="false"`), so it never
  opens the MicroSquirt cable as if it were a GPS;
- restarts the screen once, after which **TunerStudio** appears in the dash menu.

**Sensors → System check → Updates** shows each of these with its result. One that says
it needs the internet is done by the next **Update now** with Wi-Fi connected.

The dash looks for TunerStudio in `~/TunerStudioMS`, `/opt/TunerStudioMS` and
`/usr/local/TunerStudioMS`. A copy you put there yourself is used as it is and nothing
is downloaded. For any other folder, set `FROGDASH_TUNERSTUDIO` for the screen service
(`sudo systemctl edit "frogdash-console@$USER"`, `Environment=FROGDASH_TUNERSTUDIO=/path`).

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
- **No speed lockout:** it opens whether the car is stopped or moving, for road tuning.
  It covers the gauges while it is open, so that is for a passenger to use.
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
| TunerStudio is not on the Pi yet | **Update now** with Wi-Fi connected; System check → Updates → TunerStudio: program |
| The screen has no X display | **Update now** with Wi-Fi connected; System check → Updates → TunerStudio: Java and display |
| Closed right after starting | The same line in System check; then the log below |
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
