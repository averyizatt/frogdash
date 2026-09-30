# Screen speakers and warning chimes

Frogdash sends a short double chime through Chromium's normal Linux audio output.
It needs no extra buzzer or GPIO wiring when the monitor accepts HDMI audio.
The proposed Amazon 12.3-inch, 1920 x 720 touchscreen has not been identified by
model, so HDMI audio support still needs confirmation from its listing/manual.
On the Pi 4, use a micro-HDMI cable appropriate for the monitor's HDMI input.
Connect touchscreen USB and display power as required by that monitor's manual.

## Dashboard controls

While parked, open **Drive > Alerts** (or **Alerts** in the footer):

1. Enable **Warning chimes** and press **Save alert settings**. They default off.
2. Adjust **Volume**, then press **Test chime** to check audibility. Volume saves
   immediately on this display; zero mutes both warnings and the test tone.
3. Also set the monitor's own volume. HDMI audio on the Pi has no Linux volume
   control, so the dashboard slider sets the digital level: 100% plays at 0.9 of
   full scale. The chime is a bell-like 1 kHz tone with a softer octave, which
   small built-in display speakers reproduce far louder than a low pure tone.

For HDMI speakers (for example the Prechen 12.3-inch bar display), unplug any cable
from the display's 3.5 mm jack: it is a headphone output and mutes the speakers.
Point ALSA at the HDMI port the display uses (card 1 is `vc4hdmi0` / HDMI-A-1):

```sh
printf 'defaults.pcm.card 1
defaults.ctl.card 1
' | sudo tee /etc/asound.conf
speaker-test -c 2 -t wav -l 1
```

Use the card number from `aplay -l`; `plughw:` devices fail on Pi HDMI because
it needs IEC958 samples, while `default:` and `hdmi:` convert automatically.

Low oil pressure, lean-under-boost, high coolant, water/meth faults and knock
use the existing alert rules. Chimes announce new current, unacknowledged
incidents, with at least three seconds between automatic sounds. They do not
repeat continuously for an ongoing fault. Closely spaced incidents combine into
one pending sound; pending sounds expire after five seconds or when the current
condition is no longer confirmed, acknowledged, disconnected or muted.
Recovered historical latches do not chime when opening the dashboard. An active
confirmed incident may chime once when the browser first connects.

The enable setting persists on the Pi. Volume persists in the browser profile
and is included in the existing display-preference backup. **Test chime** works
even with automatic warning chimes off. On a fresh browser/profile, volume is 50%.
The same controls appear in the standalone web preview; preview alert settings
are simulated and reset when reloading, while its display volume stays saved.

## Speaker test

**Drive > Dash management > Support & testing > Speaker test** plays a low tone on
the left speaker only, a higher tone on the right only, an 80 Hz to 8 kHz sweep
on both (listen for rattles or dropouts), or the warning chime. It uses the chime
volume from **Drive > Alerts**; at 0% it reports that audio is muted. If the Linux
output is mono, it says so, and both speakers play every test.

## Startup and Linux audio output

Both supplied kiosk units pass `--allow-audio` to `tools/launch_kiosk.py`, which
adds Chromium's `--autoplay-policy=no-user-gesture-required` for that process.
Saved, enabled chimes can then initialize without a touchscreen tap after key-on.
The default launcher invocation without that flag keeps normal browser policy.
A normal browser/web preview may require **Test chime** to unlock playback.
See [Chrome's documented autoplay behavior](https://developer.chrome.com/blog/autoplay).
Audio initialization never delays dashboard startup or saving alert settings.

Select the HDMI monitor as the normal Linux output for the **same normal user
that runs the kiosk**. Raspberry Pi OS supports HDMI, USB and supported analog
outputs; see [Raspberry Pi audio configuration](https://www.raspberrypi.com/documentation/computers/configuration.html#change-audio-output).

First identify the installed distribution and audio stack:

```sh
cat /etc/os-release
command -v wpctl pactl aplay
```

If PipeWire/WirePlumber is installed and running for the kiosk user, use
`wpctl status` to find the HDMI sink, then `wpctl set-default ID` with its actual
numeric ID. Confirm that the default marker moved to that sink. Do not assume
an ID from another Pi is correct. Check its mute/volume in the OS audio controls.

An ALSA-only installation needs its ALSA default output set instead. Raspberry
Pi OS Lite may lack a desktop audio server; do not assume `wpctl` is present.
With ALSA utilities installed, `aplay -l` and `aplay -L` list playback hardware
and named outputs. Use that distribution's audio configuration (including the
Audio option in `raspi-config` when provided), then restart the kiosk and test.
See Raspberry Pi's [audio options guide](https://pip-assets.raspberrypi.com/categories/1259-audio-camera-and-display/documents/RP-008124-WP-1-Choosing%20an%20Audio%20option.pdf).
No global ALSA files, audio devices, boot overlays or package installations are
automatically changed by Frogdash. The exact distro and panel are needed to
finish device selection on the real Pi.

For an existing installation, reinstall **the kiosk unit you actually use**
from `hardware/systemd/` and reload its systemd manager, then restart that kiosk
when parked. The console template is a system unit; the desktop template is a
user unit. See [console setup](boot-and-kiosk.md). Deploying UI assets alone does
not change an already installed systemd unit or running Chromium command line.

## Acceptance check on the car

- With the monitor connected and powered, select HDMI audio and verify **Test
  chime** at a sensible monitor/master volume.
- Enable chimes, save, and cold-boot into the kiosk. Confirm a controlled test
  alert produces sound without first tapping the screen. Use simulated/replayed
  telemetry for testing rather than provoking an actual engine fault.
- Confirm the sound is audible with the engine running and ordinary cabin noise.
- Check muted volume and disabled chimes, and verify visual warnings still work.
- If the display is disconnected/reconnected, retest its output; Linux or the
  monitor may change routing. The application cannot prove physical audibility.

"Browser audio ready" only confirms a running Web Audio context. It does not
prove that HDMI is selected, speakers are connected, or either mixer is unmuted.
If audio is unavailable/blocked the UI reports it, and visual alerts continue.
Chimes require an open, working dashboard browser; backend monitoring and
recording continue independently. Automated browser tests validate scheduling,
startup, volume, mute, throttling and failure behavior, not physical sound.
