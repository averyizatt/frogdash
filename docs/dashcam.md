# Wi-Fi dash cam view

Shows the live picture from a Viidure-app dash cam (tested with a Wanlipo front/rear
5 GHz camera: eeasytech SoC, HUAXIN firmware `DVR-A13-20250707`) on the dash, with a
front/rear switch. The camera keeps recording to its own card.

## How it works

Captured from the Viidure phone app:

1. `GET /app/setsystime?date=YYYYMMDDhhmmss` and `GET /app/enterrecorder` on
   `http://192.168.169.1` (the camera's web API).
2. A TCP connection to port 5000 stays open: the camera's notification channel
   (`{"msgid":"rec",...}`).
3. Live video is standard RTSP at `rtsp://192.168.169.1:554/` over TCP. The camera
   also advertises an AAC audio track with an invalid configuration; it is ignored.
4. While watching, the app polls `/app/getparamvalue?param=rec` every few seconds.
5. Front/rear: `/app/setparamvalue?param=switchcam&value=0` (front) or `1` (rear).

The dash does the same. ffmpeg converts the video to JPEG frames that use the
reverse camera's stream and lost-feed handling. The camera's web server is fragile,
so only the app's own requests are sent; if it stops answering, power-cycle the camera.

### The picture is kept ready

Starting live view takes several seconds: the camera's web server, the video
connection, then ffmpeg's first picture. That is far too slow for a reverse view, so
the dash keeps the stream running in the background from the moment it starts, on the
**rear** camera. Selecting reverse, or opening the Dashcam view, shows the picture that
is already arriving.

- After a look at the front camera, the dash returns to the rear one three seconds
  after the view closes, ready for the next reverse.
- A stream that ends or freezes (camera off, Wi-Fi dropped) is reconnected by itself:
  at once, then every 4, 8, 16 and 30 seconds while the camera stays away.
- A picture more than a second old is never shown as live. The view waits for a new one.
- The camera keeps recording to its own card throughout.

The cost is the Pi decoding video all the time: more processor load and heat (**System
check → Pi → Temperature** shows it). **Keep the picture ready (instant reverse)** in the
Dashcam view switches it off; live view then starts when a view opens and stops 10
seconds after it closes, as before. The choice is remembered.

The camera has no live GPS: its settings list has no GPS or speed entry, and the
route shown by the app and DC Player is stored in the recordings. The dash keeps
using its USB GPS for speed.

## Setup on the Pi

Use a second Wi-Fi adapter (USB) for the dash cam so the built-in Wi-Fi stays free
for the hotspot. Check which interface is USB:

```sh
readlink -f /sys/class/net/wlan1/device | grep -q usb && echo "wlan1 is USB"
```

Join the camera's Wi-Fi (name and password from the camera's Wi-Fi menu):

```sh
sudo nmcli dev wifi connect "DC-37BB0BD3" password "12345678" ifname wlan1 name dashcam
sudo nmcli con modify dashcam ipv4.never-default yes ipv6.method ignore ipv4.dhcp-timeout 60 connection.autoconnect yes
sudo apt install -y ffmpeg
```

Add `--dashcam` to `FROGDASH_ARGS` in `/etc/default/frogdash` and restart
`frogdash.service`. A **Dashcam** button appears next to Mark log. Options:
`--dashcam-host` (default `192.168.169.1`) and `--dashcam-width` (default 1280; the
stream is scaled down to this). Close the phone app while using the dash view: the
camera serves one viewer at a time.

## Tools

- `python3 tools/dashcam_probe.py` reads the camera's identity and media info;
  `--live` copies the app's live-view sequence and tests the RTSP stream.
- `sudo sh tools/dashcam_sniff.sh` records the phone app's traffic with a
  monitor-mode USB adapter and decrypts it with the camera's Wi-Fi password, for
  cameras whose live-view sequence differs.
