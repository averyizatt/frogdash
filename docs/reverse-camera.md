# Reverse camera

Frogdash can show a Raspberry Pi CSI camera (for example the Camera Module v2.1)
as a full-screen rear view. It opens automatically when the CAN reverse signal
(`lighting.reverse`, from the lighting module) turns on, and closes a few seconds
as soon as it turns off (or after an optional delay). It never sends vehicle commands.

**The camera is a driving aid, not a replacement for mirrors or looking.** The
Pi must have finished booting before a view can appear. Factory systems must show
the image within 2 seconds of selecting reverse; this build has not been measured
against that, so check the delay on your car before relying on it.

## Hardware

- **Camera:** Pi Camera Module v2.1 (Sony IMX219). Its lens covers about 62°
  horizontally, narrower than most dedicated backup cameras (120–170°), so the
  bumper corners may be out of view. A clip-on wide-angle lens or the Camera
  Module 3 Wide (120°) shows more.
- **Cable:** the CSI ribbon cannot reach the rear of a car. Use a CSI-to-HDMI
  extender pair: one board at the Pi, one at the camera, joined by an ordinary
  HDMI cable. This carries the CSI signal; it is not an HDMI video source.
  Keep the HDMI cable away from ignition leads and route it clear of the exhaust.
- **Mounting:** the bare board is not weatherproof. Use a sealed housing with a
  clear window. If the image is upside down, add `--camera-rotate 180`.

## Pi setup

On Raspberry Pi OS Bookworm (or newer):

```sh
sudo apt install -y python3-picamera2
rpicam-hello --list-cameras          # should list imx219
rpicam-still -o /tmp/test.jpg        # confirms the extender and ribbons work
```

Frogdash's service environment must be able to import the system camera package.
Managed releases are created with `--system-site-packages`. A checkout with its
own `.venv` created without that option will report
`ModuleNotFoundError: No module named 'libcamera'` in the camera view; recreate it:

```sh
cd /opt/frogdash
sudo python3 -m venv --system-site-packages --clear .venv
sudo .venv/bin/pip install -r requirements.lock
```

Add `--camera` to `FROGDASH_ARGS` in `/etc/default/frogdash`, then restart:

```sh
FROGDASH_ARGS="--interface can0 --gpsd --log-dir /var/lib/frogdash/logs --camera"
sudo systemctl restart frogdash.service
sudo systemctl restart --no-block frogdash-console@<user>.service
```

The supplied `frogdash.service` already runs with the `video` group, which
Raspberry Pi OS uses for camera devices; no user changes are needed. If you run
the server another way, that user must be in the `video` group.

### Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--camera` | off | Enable the reverse camera |
| `--camera-size WxH` | `640x480` | Capture size. Larger sizes add delay and CPU/heat |
| `--camera-fps N` | `30` | Frame rate, 5–60 |
| `--camera-rotate 180` | `0` | For an upside-down mount |
| `--camera-keep-warm` | off | Keep capturing between views so the picture appears faster, at the cost of power and heat |

Without `--camera-keep-warm` the camera starts when a view opens and stops 20
seconds after the last view closes. Starting the camera typically takes about a
second, so enable keep-warm if the first frame arrives too late for you.

## Using it

- **Automatic:** shifting into reverse opens the view; leaving reverse closes it
  immediately by default, or after an optional 3, 5 or 10 second delay.
- **Manual:** the **Camera** button in the top bar (shown only when `--camera`
  is enabled). A manually opened view closes itself above about 10 mph so it
  cannot keep covering the gauges while driving forward.
- **Test without reverse:** Drive → Dash management → Support & testing shows the
  camera's status (not enabled, ready, running with frame rate, or the error) and
  **Open camera test** for aiming the camera and setting guides while parked.
- **Guides / Mirror / Adjust:** toggle the red–yellow–green distance guides and
  the mirror image (on by default, like other backup cameras), and set guide
  width, far width, length and left/right shift. Guides are a visual reference,
  not calibrated distances. Line them up with a known object behind the car.
- Speed and active warnings stay visible beside the image.

Camera preferences save on the display and are included in display backups.

## Failure behavior

The view never presents an old image as live. It shows **CAMERA LOST** with the
reason when the service reports no frame for more than one second, the stream
drops, or the camera cannot start (for example "Camera not detected" or a missing
`picamera2`). It reconnects automatically every two seconds and clears the
warning when frames resume. Gauges, alerts, CAN and logging keep running.

The stream is served only to the dashboard on the Pi itself (`127.0.0.1`), as a
hardware-encoded MJPEG stream; phones on the Wi-Fi hotspot cannot open it. Expect
roughly 150–250 ms of delay.

## Validation

`tests/test_camera.py` covers on-demand start, MJPEG framing, shared viewers,
idle stop, missing cameras and local-only access. `tests/browser_camera.py` covers
auto-open and linger, manual close when moving, guides, persistence, layouts, and
live, frozen and missing feeds through the production endpoints with a simulated
sensor. The preview's **reverse** scenario uses a simulated camera image.

Physical validation on the Pi with the v2.1 camera and extender is still pending:
confirm the picture, the delay from shifting into reverse, heat after a long idle
in reverse, and the image with the engine running (ignition noise on the cable).
