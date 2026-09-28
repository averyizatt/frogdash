# Raspberry Pi CAN + USB GPS integration

The production app lives in `hardware/`: Python owns CAN/GPS data and serves a
self-contained dashboard to Chromium at `http://127.0.0.1:8080`. The original
`preview/` stays a separate simulation. The production browser never generates
sensor readings. Named, validated vehicle commands are available through the
[controls panel](controls.md); arbitrary CAN frame injection is not exposed.

For the verified module contract, both MicroSquirt broadcast modes, and firmware
ownership steps, see [CAN compatibility](can-compatibility.md). The reusable
[C++ contract package](../hardware/can_contract/README.md) includes fuel and GPS.

## Run on Raspberry Pi OS

For the planned MCP2515, use the [wiring and persistent CAN setup guide](mcp2515.md).
The app uses Linux SocketCAN; the driver needs the board's actual oscillator and
GPIO assignment. All three project modules use **500000 bit/s, standard 11-bit
classical CAN**.

```sh
sudo apt update
sudo apt install python3-venv python3-gps gpsd gpsd-clients can-utils chromium
# Run from the frogdash checkout:
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
sudo ip link set can0 up type can bitrate 500000 restart-ms 100
ip -details -statistics link show can0
.venv/bin/python -m hardware.frogdash.server --interface can0 --gpsd
chromium --kiosk http://127.0.0.1:8080/
```

The bitrate is configured by Linux, not by the app. Persist that configuration
using the network manager already installed on the Pi. CAN reception reconnects
after interface errors; absent modules become stale independently. The app binds
the full dashboard only to localhost. Optional [Wi-Fi log access](wifi-access.md)
uses a separate transfer site. `/health` reports transport/module/GPS health, `/state`
is a WebSocket, and `/raw` lists the most recent frame per identifier (max 256).
Raw extended, remote, and error frames are diagnostic-only; they cannot overwrite
the standard-frame decoder. Raw traffic is not a persistent trip recorder.

## USB GPS via gpsd

Use the OS `gpsd` daemon and its **distribution `python3-gps` client library**,
not a similarly named pip package. `--system-site-packages` makes those bindings
visible in the virtual environment. gpsd handles USB/serial device protocols.

1. Plug in the receiver and find its stable path with `ls -l /dev/serial/by-id/`.
2. If gpsd does not auto-detect it, set `DEVICES="/dev/serial/by-id/YOUR_RECEIVER"`
   and `GPSD_OPTIONS="-n"` in `/etc/default/gpsd`, then restart `gpsd`.
3. Verify a real fix with `cgps -s` or `gpspipe -w` before starting Frogdash.
4. Start with `--gpsd`. Optionally pass `--gps-device /dev/ttyACM0` using the
   exact device name reported by gpsd; otherwise the first receiver is selected
   and locked for the process lifetime. The client connects to localhost:2947.

USB GPS is authoritative while `--gpsd` is enabled. Speed in m/s is converted
to km/h internally and MPH in the UI. No silent fallback to a different GPS
receiver occurs. A speed field older than two seconds, a lost fix, a simulated
fix, or a gpsd disconnection stops live speed display. Partial TPV reports do
not refresh the age of missing speed. Satellite counts expire after five
seconds. Local GPS continues working if CAN fails.

### GPS back onto CAN

`--gpsd` broadcasts the existing **0x203, DLC 8** at **2 Hz**:

| Bytes | Encoding |
|---|---|
| 0–1 | speed km/h × 10, unsigned big-endian |
| 2–3 | MSL altitude meters, signed big-endian; 0 when unavailable |
| 4 | satellites used, capped at 255 |
| 5 | GPS fix mode 2 or 3; 0 without fresh speed/fix |
| 6 | existing CCM flags: bit 0 RX live, bit 1 parsed data, bit 3 satellites visible, bit 4 valid fix |
| 7 | satellites visible, capped at 255 |

Speed/fix validity flags clear and speed becomes zero on loss of valid speed.
Consumers must inspect validity; zero alone does not mean the car is stopped.
The existing frame has no separate altitude-valid bit and no latitude/longitude
fields. Full position, track, and altitude quality remain in the local state API.
No new CAN IDs were invented. `--gps-no-transmit` keeps USB GPS local only.

**Only one node may own 0x203.** The pinned CCM currently sends it every 500 ms.
Frogdash listens for two seconds before first transmission and latches GPS TX
off if any other standard data frame with ID 0x203 is received, even later in
the session. The warning appears in the UI and `/health`; restarting is required
after resolving the conflict. SocketCAN's own-message reception stays disabled.
This detects duplicate publishers but is not a bus ownership negotiation scheme.

To transfer ownership, apply `hardware/compat/comfort-disable-gps-tx.patch` in
the **DIYComfortControlModule** checkout and add
`-DCCM_CAN_GPS_TX_ENABLED=0` to its PlatformIO build flags, rebuild, and flash
the CCM. The patch preserves the current behavior unless that flag is set.
It only disables that transmitter; it does not make the CCM consume external GPS
or replace its local GPS logic. No remote repository has been modified here.

```sh
# From the CCM checkout, using the actual path to this frogdash checkout:
git apply --check /path/to/frogdash/hardware/compat/comfort-disable-gps-tx.patch
git apply /path/to/frogdash/hardware/compat/comfort-disable-gps-tx.patch
```

## Imported wire definitions

The decoder was checked against these exact source revisions:

| Repository | Revision | Sources |
|---|---|---|
| [DIYComfortControlModule](https://github.com/averyizatt/DIYComfortControlModule/tree/69c73f86a61e9892836a1006f8a676e7e1e750a3) | `69c73f86a61e9892836a1006f8a676e7e1e750a3` | shared schema-2 `can_protocol.h`, `CanFrameBuilders.hpp`, `MicroSquirtProtocol.hpp`, `src/main.cpp` |
| [CustomTaillights](https://github.com/averyizatt/CustomTaillights/tree/dd4d971b47a7e4aee9d07c7801daaec4579f19e2) | `dd4d971b47a7e4aee9d07c7801daaec4579f19e2` | `src/canbus.cpp`, `src/can_protocol.h`, `src/inputs.cpp` |
| [DIYWaterMethInjection](https://github.com/averyizatt/DIYWaterMethInjection/tree/ae1e6ae1c98babd860ba3d328207434e4dd78cef) | `ae1e6ae1c98babd860ba3d328207434e4dd78cef` | `src/main_nano.cpp`, schema-2 contract via CCM |

| IDs | Decoded content |
|---|---|
| 100 / 102 | left/right light state, side-specific brake/running/turn/reverse inputs, brightness, raw die °C, thermal derate, fault events |
| 200 / 202 / 203 | comfort state/page/inputs/temperatures/heartbeat, tach RPM/status/frequency, GPS |
| 300 / 302 / 303 | meth state/duty/tank/flow/boost/temperatures, fault events, pressure and temperature sensor validity |
| 304 / 305 / 306 | meth configuration (XOR checked), requests, acknowledgements |
| 307 / 308 / 309 | knock energy/baseline/threshold/status/events, knock faults, engine runtime |
| 30A / 30B / 30C / 30D | schema-checked command ACK, knock live diagnostics, configuration pages |
| 5E8–5EC | MicroSquirt simplified dash broadcast |
| 5F0–62F and 700–73F | Supported MS2/Extra realtime fields; other groups remain raw |

The new external [fuel-controller contract](fuel-can.md) adds standard ID
**0x204, DLC 3** for percentage and validity. It must be implemented by that
controller; it is not part of the imported firmware revisions above.

IDs above are hexadecimal. Known frames require their documented DLC.
Every decoded field is available in **CAN / SENSORS**, even when it has no
dedicated main gauge. Fault events are a bounded history (100), not assumed
to be active forever. Current meth/knock/analog flags drive current warnings.
Received command payloads (101/201/301) remain raw. The control panel can transmit
the explicitly supported 101/301 commands; see [controls and ownership](controls.md).

Key compatibility details:

- Tach/GPS words are big-endian, while 309 RPM is little-endian.
- 303 pressure values are psi × 2; temperatures use Celsius + 40. Its fault
  bitfield is little-endian. IAT/bay values in 300 depend on validity in 303.
- 300 boost is nonnegative gauge kPa; ECU MAP minus baro supplies vacuum and
  boost when both values are fresh. Nano 300 fault bit 1 invalidates its MAP.
- Nano tank telemetry is currently **0 or 100 from a low-level switch**, not
  a continuous fluid-level measurement. Flow can legitimately be UNKNOWN.
- GPS `fix_type=1` is ambiguous in CCM; its validity flags are required.
- The CCM heartbeat battery field has no validity bit and can contain a default;
  it stays diagnostic-only. Main battery uses measured MicroSquirt telemetry.
- RPM prefers fresh ECU data, then a valid physical/CAN tach source. TEST/DEMO
  tach sources are unavailable. Each field expires from its own source frame.
- EGO displays ECU correction minus 100%; 100% correction displays as 0%.
- **High beam and oil temperature remain unavailable** because no confirmed CAN
  signal is defined. Fuel pressure is not fuel level. Fuel level uses the new
  [external-controller contract](fuel-can.md) and stays unavailable until received.

No CAN IDs for the car's unrelated OEM traffic are guessed. The receiver can show
that traffic raw; additional gauges require a documented matching decoder.

## Services and shutdown

Install this checkout at `/opt/frogdash` (readable by a service user), create its
venv there, then:

```sh
sudo cp config/frogdash.env /etc/default/frogdash
sudo cp hardware/systemd/frogdash.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now frogdash
curl http://127.0.0.1:8080/health
journalctl -u frogdash -n 30
```

The supplied environment enables USB GPS broadcasting; use the local-only
option while the CCM still owns 203. The daemon retries absent CAN/gpsd; it does
not configure network interfaces or serial drivers. The supplied service also
records rotating MLG files in `/var/lib/frogdash/logs`; see [data logging](data-logging.md)
for retention settings, downloads and MegaLogViewer compatibility.

For console-only Linux, use the separate [Cage console kiosk](boot-and-kiosk.md)
after checking the installed distribution. The original kiosk template below is
a **user service**, run in the Pi's existing graphical login session:

```sh
mkdir -p ~/.config/systemd/user
cp hardware/systemd/frogdash-kiosk.service ~/.config/systemd/user/
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY
systemctl --user daemon-reload
systemctl --user enable --now frogdash-kiosk
```

The readiness launcher discovers `chromium` or `chromium-browser` and waits for
local HTTP before opening it. Use a service override with launcher `--browser`
for a different executable. Configure graphical autologin/session startup
separately for this desktop option. The [PiSugar power monitor](pisugar-power.md)
requests normal Linux poweroff after sustained input loss. Systemd stops the
kiosk/backend and flushes storage before the final UPS cutoff hook runs. Install
that power setup separately when retiring the old ACC/relay hardware.

## Replay and validation

```sh
# Desktop, no CAN/GPS required. Fixtures are synthetic, clearly labeled REPLAY.
.venv/bin/python -m hardware.frogdash.server --replay tests/fixtures/demo.candump --loop
.venv/bin/python -m unittest discover -s tests -v
# Optional browser check:
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
.venv/bin/python tests/browser_smoke.py
```

Replay reads timestamped `candump -L` classical data frames, validates lengths
and timestamps, and preserves relative timing. It never opens CAN or transmits.
One-shot replay marks readings stale at EOF. Large log files are loaded into
memory; use short captures for this development adapter.

Linux virtual bus test:

```sh
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set vcan0 up
.venv/bin/python -m hardware.frogdash.server --interface vcan0 --gpsd
# In another terminal:
cansend vcan0 100#05010502804600
cansend vcan0 202#0D7A000001011400
candump vcan0,203:7FF
```

Before vehicle use, verify actual Pi CAN reception, USB fix/unplug recovery,
GPS ownership transfer and transmission, sensor validity, display scaling,
and boot/shutdown on hardware. Desktop tests do not establish hardware readiness.

API implementation references: [GPSD client HOWTO](https://gpsd.gitlab.io/gpsd/client-howto.html),
[GPSD reports and units](https://gpsd.gitlab.io/gpsd/gpsd_json.html),
[Python SocketCAN sockets](https://docs.python.org/3/library/socket.html),
[aiohttp server API](https://docs.aiohttp.org/en/stable/web_quickstart.html).
