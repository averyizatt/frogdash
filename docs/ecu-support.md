# ECU support: profiles, tuning software and what has been checked

Frogdash reads an engine computer by **listening** to the data it broadcasts on CAN. It
never writes to an ECU. How each ECU's broadcast is laid out is described in an **ECU
profile**. Tuning the ECU is a separate job, done with the manufacturer's own software
over its own connection.

## 1. How the dash is built (assessment, November 2026)

| Part | Where | What it does |
|---|---|---|
| Pi and OS | Raspberry Pi 4, aarch64, Raspberry Pi OS (Trixie in the car) | `tools/frogdash_install.sh`; setup steps in `tools/frogdash_setup.sh` |
| Screen | Chromium in kiosk mode under Cage, started by `frogdash-console@<user>.service` and watched by `tools/launch_kiosk.py` | Draws `hardware/ui/`; reconnects by itself |
| CAN receiver | `hardware/frogdash/adapters.py` `socketcan()` | A raw SocketCAN socket on `can0` (MCP2515 HAT, 500 kbit/s by `frogdash-can.service`), passive |
| Decoding | `hardware/frogdash/protocol.py` `decode()` | Frogdash's own modules by their contract; **the ECU through its profile** (`hardware/frogdash/ecu/`) |
| Normalised values | `hardware/frogdash/state.py` | Each reading kept with its source, time and quality (`live`, `stale`, `fault`, `unavailable`); stale after the profile's timeout; `ALIASES` choose between sources (`engine.rpm` from the ECU, else the tach, else the gateway) |
| Backend to screen | `hardware/frogdash/server.py` | aiohttp; one snapshot over a WebSocket many times a second; commands back as HTTP |
| Logging | `hardware/frogdash/recorder.py`, `log_channels.py`, `mlg.py` | MegaLogViewer `.mlg` at 20 Hz of every decoded channel with its quality; raw CAN capture (Sensors → Raw CAN → Record) |
| Settings | `/etc/frogdash/system.json` (the [system profile](presets.md)) and JSON files in `/var/lib/frogdash` | The ECU profile is the system profile's `ecu.profile` |
| TunerStudio | `hardware/frogdash/tune.py` asks `tools/launch_kiosk.py`, which starts `TunerStudio.sh` over the dash (Xwayland, Java); installed by setup when asked | Talks to the MicroSquirt over its USB serial cable, independently of CAN |

The cleanest place for other ECUs was the ECU branch of `decode()`, which was hand-written
for MegaSquirt. It is now a table read by one generic decoder. Everything after it (alerts,
logs, gauges, modules) only knows the normalised `ecu.*` names, so it works unchanged with
any profile. Readings a profile does not have are shown as unavailable.

## 2. ECU profiles

Built-in profiles are JSON files in `hardware/frogdash/ecu/profiles/`. The format is
described at the top of `hardware/frogdash/ecu/__init__.py`. In short:

```json
{
  "id": "example", "label": "Example ECU", "bitrate": 500000, "extended": false,
  "timeout_s": 1.0, "status": "documented",
  "source": {"title": "Example CAN broadcast", "url": "https://…", "version": "1.2"},
  "setup": ["Steps in the ECU's software to switch the broadcast on"],
  "tuner": {"name": "…", "runs_on_dash": false, "connection": "USB", "url": "https://…"},
  "frames": [
    {"name": "ENGINE_1", "ids": ["0x360"], "length": 8, "signals": [
      {"key": "ecu.rpm", "layout": "u16@0"},
      {"key": "ecu.map_kpa", "layout": "u16@2", "scale": 0.1, "unit": "kPa"}
    ]}
  ]
}
```

- **Layouts:** `u8 s8`; `u16 s16 u32 s32` big-endian; `u16le s16le u32le s32le`
  little-endian; `bit@B.b`; `nib@B.b`. Each is checked against the frame's length.
- **A broadcast that can be moved** (rusEFI's starts wherever its base address is set):
  frames are given as `offsets` from a `base` with its default, and the system profile's
  `ecu.base_id` says where it is in this car (0: the default).
- **Values:** the raw number × `scale` + `offset`, or a named conversion. Keys are always
  `ecu.<name>` in fixed units (°C, kPa, V, %): the profile converts.
- **Checks when loaded:**
  - the bit rate is one CAN uses;
  - IDs fit 11-bit (or 29-bit with `extended`);
  - no ID is listed twice;
  - IEEE floats (`f32@B`, big-endian, or `f32le@B`), and an `id_mask` for an ECU that puts
    its serial number in the low bits of every ID (Holley);
  - **no ID of a Frogdash module this car has** (taillights 0x100–0x10F; gateway
    0x200–0x20F and 0x500–0x50F; water/meth 0x300–0x31F), nor one the dash sends (0x680/0x681,
    and 0x203 when it sends its GPS). The IDs of modules the car does not have are free, and
    a frame the ECU sends there never reaches that module's code.

  A profile that fails is not used. The dash reads MegaSquirt instead and says why under
  **Sensors → System check → ECU profile**.
- **`status`:** `car` means running in a car; `simulated` means frames built from the
  document decode correctly in tests; `documented` means written from the document only.
  A profile is never shown as more checked than it is.
- **29-bit and 1 Mbit/s ECUs:** a profile with `extended` is read from 29-bit frames (and
  only those: a 29-bit frame is never a module's). The CAN bus runs at the system profile's
  `ecu.bitrate` (500 kbit/s unless set): `frogdash-can.service` reads it from
  `/etc/frogdash/system.env`, and setup restarts can0 when it changes. System check warns
  when the ECU profile's bit rate is not the bus's.
- `GET /ecu/profiles` lists the built-in profiles with their source, status, setup steps and
  tuning software. The setup wizard will use it to offer the choice.

### Adding an ECU

1. Find the manufacturer's **published** CAN broadcast document or DBC. Never guess IDs or
   scaling. Note its URL and version.
2. Write `profiles/<id>.json` from it: each frame and signal, in the dash's units. Use the
   existing `ecu.*` names where the reading is the same (`ecu.rpm`, `ecu.map_kpa`,
   `ecu.coolant_c`, `ecu.iat_c`, `ecu.throttle_pct`, `ecu.afr`, `ecu.battery_v`…), so
   gauges and alerts pick it up.
3. Add tests to `tests/test_ecu_profiles.py` that build frames from the document's own
   examples and check the values. That makes it `simulated`.
4. With a CAN capture from a real car (Sensors → Raw CAN → Record), it becomes `car`.

## 3. Profiles and their state

| ECU | CAN decoding | Source | CAN setup | Tuning software | Tuning connection | Runs on the Pi | Checked |
|---|---|---|---|---|---|---|---|
| MegaSquirt / MicroSquirt (MS2/Extra) | Supported: dash broadcast (1512) and realtime groups (1520 or 1792), 102 signals | [Megasquirt CAN Broadcast](https://www.msextra.com/doc/pdf/Megasquirt_CAN_Broadcast.pdf) | 500 kbit/s, 11-bit; switched on in TunerStudio | TunerStudio MS | RS232 serial through a USB adapter, 115200 | Yes: TunerStudio runs on the dash | **In a car** (the Foxbody) |

| rusEFI (verbose CAN broadcast) | Supported: 12 frames, 70 signals: RPM, timing, MAP, throttle and pedal, coolant, intake air, oil and fuel pressure and temperature, battery, lambda 1 and 2, fuel level, vehicle speed, gear, fuel trims and flow, cams, 8 EGTs, knock per cylinder, status bits | [rusEFI_CAN_verbose.dbc](https://github.com/rusefi/rusefi/blob/bfde8f4945ecd33a9d3090b20aefba1521675801/firmware/controllers/can/rusEFI_CAN_verbose.dbc) and [can_verbose.cpp](https://github.com/rusefi/rusefi/blob/bfde8f4945ecd33a9d3090b20aefba1521675801/firmware/controllers/can/can_verbose.cpp), rusefi/rusefi bfde8f4 (2025-11-20) | 500 kbit/s, 11-bit, little-endian, base 0x200 (512) by default and movable; switched on with *CAN broadcast using custom rusEFI protocol*; every 50 ms | TunerStudio with the rusEFI project, or rusEFI's console | The board's USB serial; or over CAN through rusEFI's CAN-to-TCP proxy | TunerStudio runs on the dash; a rusEFI connection from the Pi is **not tested** | **Simulated**: frames packed as the firmware packs them decode to the right values; not yet in a car |

| MaxxECU (default CAN output protocol) | Supported: 22 frames, 98 signals: RPM, throttle, MAP, lambda (average, A, B, target), ignition, pulse width, duty, vehicle and wheel speeds, battery, baro, intake air, coolant, oil pressure and temperature, fuel pressure, boost target and duty, gear, 8 EGTs, knock, cams, accelerations, status bits, user channels | [MaxxECU default CAN protocol](https://www.maxxecu.com/webhelp/can-default_maxxecu_protocol.html) v1.3 (2020-09-29), checked signal by signal against MaxxECU's own `MaxxECU_Default_CAN_protocol_v1.3.dbc` | 500 kbit/s, 11-bit, little-endian, fixed IDs 0x520-0x542; switched on in MTune (v1.2 with a VAG DSG) | MTune | USB to a Windows computer | No: MaxxECU's driver is Windows-only | **Simulated** |
| ECUMaster EMU Black / EMU PRO (EMU CAN stream) | Supported: 8 frames, 62 signals: RPM, throttle, MAP, intake air, coolant, oil temperature and pressure, fuel pressure, baro, vehicle speed, ignition, dwell, lambda, EGT 1-2, gear, battery, ethanol, error and status flags, drive-by-wire, traction, boost target, fuel used, analog inputs | [EMU Black manual](https://www.ecumaster.com/files/EMU_BLACK/EMU_BLACK_manual.pdf) v1.4 (firmware 2.169+, 9 July 2026), section 6; [EMU PRO manual](https://www.ecumaster.com/files/EMU_PRO/EMU_PRO_Manual.pdf) v1.1 (the same structure) | 500 kbit/s set in the EMU client (Black's default is 1 Mbps; PRO: CAN 2), 11-bit, little-endian, base 0x600 by default and movable; "Send EMU stream over CAN-Bus" | EMU Black Client; EMU PRO client | Black: USB-C. PRO: a USB-to-CAN interface (ECUMaster USBtoCAN, Peak, Kvaser) | No: Windows programs | **Simulated** |
| Speeduino (Haltech-format broadcast) | Supported: 8 frames, 24 signals: RPM, MAP, throttle, fuel and oil pressure, load, duty, advance, pulse widths 1-4, lambda 1-2, vehicle speed, gear, cams, battery, boost target, baro, coolant, intake air, fuel temperature | Speeduino's own source, [comms_CAN.cpp](https://github.com/noisymime/speeduino/blob/97ef8e8d48b03de3acbdcefe352a6c912d539ca9/speeduino/comms_CAN.cpp), noisymime/speeduino 97ef8e8 (2026-10-03) | 500 kbit/s, 11-bit, big-endian, fixed IDs 0x360-0x3E0; only boards with built-in CAN (Teensy 3.5/3.6/4.1, STM32); broadcast protocol "Haltech" in TunerStudio | TunerStudio with the Speeduino project | The board's USB serial | TunerStudio runs on the dash; Speeduino from the Pi **not tested** | **Simulated** |

| Haltech Elite / Nexus (ECU Broadcast CAN Protocol) | Supported: 27 frames, 113 signals from 0x360 to 0x3E5: RPM, MAP, throttle, coolant/fuel/oil/wastegate pressure, injector duty and times, ignition, lambda 1-4, knock, wheel speeds, cams, vehicle speed, gear, fuel flow, battery, boost target, baro, 12 EGTs, ambient, temperatures, ethanol, fuel level and trims, status lights and switches | Haltech ECU Broadcast CAN Protocol, document version 2.0 (Nexus firmware 1.25+, Elite 3.11+), from [its knowledge-base article](https://support.haltech.com/portal/en/kb/articles/haltech-can-ecu-broadcast-protocol) | **1 Mbit/s**, 11-bit, big-endian, fixed IDs; pressures sent absolute, temperatures in 0.1 K | NSP (ESP for older Elite firmware) | USB to a Windows computer | No | **Simulated** (the document's own example included) |
| Holley Terminator X / X Max / HP / Dominator | Supported: 29 channels: RPM, pulse width, duty, AFR and target, lambda and target, closed-loop and learn, VE, timing, knock retard, idle, MAP, TPS, intake air, coolant, baro, battery, oil and fuel pressure, boost, pedal, speed, gear, fans | Holley EFI 1st Party CAN Communications Protocol, revision 1 (8 November 2024), and Holley's `Terminator X V3.dbc` (the same IDs as `HP & Dominator V6.dbc`) | **1 Mbit/s, 29-bit**; the ECU's serial in the low 11 bits (any Holley ECU is read); a float per channel; °F, psi and mph converted | Holley EFI software | Holley 558-443 CAN-to-USB interface; Holley says its driver does not work on ARM | No: a Windows computer is needed to tune | **Simulated** |
| Holley Sniper (V2 and later) | Supported: 21 channels (as above where Sniper has them) | The same document and Holley's `Sniper V2.dbc`: Sniper uses its own channel numbers | As Holley above | Sniper software | As Holley above | No | **Simulated** |

| AEM Infinity (AEMnet data stream) | Supported: 3 frames, 31 signals: RPM, throttle, intake air, coolant, lambda 1-2 and target, vehicle speed, gear, timing, battery, MAP, VE, fuel and oil pressure, status flags | AEM's [TA2 AEMNet Configuration](https://documents.aemelectronics.com/techlibrary_ta2_infinity_aemnet_configuration.pdf) (Rev. A, 2016; AEMnet v150609) | 500 kbit/s, **29-bit**, big-endian, fixed IDs 0x01F0A000-0x01F0A004; on by default | AEM Infinity Tuner | USB to a Windows computer | No | **Simulated** |
| FuelTech FT500 / FT600 / FT550 / FT450 (FTCAN 2.0 simplified broadcast) | Supported: 6 packets, 21 signals: TPS, MAP, air and engine temperature, oil/fuel/water pressure, gear, lambda, RPM, oil temperature, wheel speeds, lambda correction, fuel flow, injection times, transmission temperature, brake pressure | [FTCAN 2.0 protocol](https://files.fueltech.net/manual/Ingles/Protocol_FTCAN20.pdf), revision 044 (17/09/2026) | **1 Mbit/s, 29-bit**, signed 16-bit big-endian, 100 Hz; FT500 0x14000600-608, others 0x14080600-608 | FTManager | USB to a Windows computer (or the ECU's screen) | No | **Simulated**; whether MAP is absolute is not stated in the protocol |

rusEFI notes: its default base 0x200 shares IDs with the Frogdash comfort module and
gateway. In a car without them it is used as it is; with them, move rusEFI's base (for
example to 0x400) and set `ecu.base_id` to match, or the dash refuses the profile and says
so. Lambda is given as lambda and pressures in kPa: the dash's AFR and oil pressure gauges
do not show these yet (next step). rusEFI's Haltech-format dash broadcast is a separate
option, not read by this profile.

Not read: MegaSquirt's separate **29-bit** CAN protocol (TunerStudio passthrough and module
requests), and MS3-only broadcast fields.

Still to do, each only from its manufacturer's own published document:

| ECU | Where it stands |
|---|---|
| Haltech, the rest of the protocol | Frames 0x3E6-0x3F3, 0x469-0x477 and 0x6F0-0x701 of document version 2.0 are not read yet. |
| Link G4X / G5 (Generic Dash) | The CAN Gauge manual URL is gone (HTTP 404) and the forum's DBC post refuses automated fetches (403). Link's knowledge base (support.linkecu.com) is still to be searched. |
| AEM Infinity, the rest of the stream | Messages past 0x01F0A004 (more sensors, analog inputs) are not read yet. |
| FuelTech, the full FTCAN 2.0 stream | Only the simplified packets are read; the MeasureID stream and segmented packets are not. |
| Emtron, Syvecs | Not yet looked up. |

## 4. Tuning software

The dashboard's CAN reception and the ECU's tuning connection are separate: the dash keeps
reading the broadcast while a tuning program is connected. A public broadcast document
says nothing about an ECU's tuning protocol, and Frogdash will never send calibration
writes of its own.

The ways a tuning program can be reached from the dash, in order of preference:

1. **Native on the Pi:** TunerStudio (MegaSquirt today; Speeduino and rusEFI use it too).
   Already built in.
2. **The manufacturer's network connection** (Ethernet or Wi-Fi), where one is
   officially supported: no driver needed.
3. **Wine with Box64 or FEX on the Pi:** worth trying only for a program with no special
   USB driver. A program that starts is not proof that it can reach the ECU: each would be
   tested for install, start, display, USB device, connection and live data separately.
4. **A Windows computer in the car or the garage**, its screen shown on the dash (RDP
   through FreeRDP, or Apache Guacamole in the dash's browser). The Pi keeps the dash; the
   Windows computer runs the program and its drivers.

Each profile's `tuner` block says which applies and how far it has been checked. An ECU is
only called tunable from the dash once the connection itself has worked.
