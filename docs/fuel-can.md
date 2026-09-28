# Fuel level from the external microcontroller

The microcontroller measures the sender, applies its tank calibration and
slosh filtering, and sends the resulting percentage. Frogdash only receives
CAN fuel telemetry: there is no Pi ADC driver, resistance calculation, I2C
polling task, sender calibration page or sender configuration API.

## Default message contract

This is a **new Frogdash contract for the planned fuel controller**, not an
existing message imported from the taillight/comfort/water-meth firmware. The
controller firmware has not been changed here. If that controller already has a
different format, match the decoder to it before deployment. Verify this ID is
unused by any other transmitter on your actual bus.

Use the existing **500 kbit/s** bus, a standard **11-bit ID `0x204`**, **DLC 3**,
and transmit **twice per second**, including when the measurement is invalid.

| Byte | Meaning |
| --- | --- |
| 0 | High byte of unsigned fuel percentage times 10 |
| 1 | Low byte; valid combined values are 0 through 1000 |
| 2 | Status: 0 = unavailable/not ready, 1 = valid, 2 = sensor fault |

These status values are an enum, not bit flags. Unknown status values or an
out-of-range percentage with status 1 are faults. With status 0 or 2, percentage
bytes are ignored. A measured empty tank is **0 with status 1**; an open/short
sender or failed measurement must never be sent as a valid empty reading.

| Condition | Three payload bytes (hex) |
| --- | --- |
| Empty, valid | `00 00 01` |
| 50.0%, valid | `01 F4 01` |
| Full, valid | `03 E8 01` |
| Not ready | `00 00 00` |
| Sender fault | `00 00 02` |

For a valid value already scaled to tenths of a percent (`uint16_t level10`),
the payload is `{uint8_t(level10 >> 8), uint8_t(level10), 1}`. Check the range
before sending. The transmitter owns calibration, fault detection and filtering.
The Pi sends no commands to this module and has no fuel-level transmitter.

Use the [shared C++ builder](../hardware/can_contract/README.md) to generate this
payload from firmware without duplicating its byte layout.

## Gauge, range and recordings

The decoder produces `vehicle.fuel_pct` for the main gauge, custom instruments
and fuel inventory. A fresh percentage multiplied by the configured tank capacity
(15.4 US gal by default) supplies remaining fuel. Range still needs learned,
calibrated fuel consumption; injector estimates and trip counters remain intact.
A fresh CAN level takes priority over manually entered inventory.

Fuel data expires after **two seconds** without its own update. Unrelated CAN
messages cannot refresh it. Disconnects, unavailable status and faults stop the
gauge from showing a live percentage. If manual inventory remains valid, the
trip computer may use it as the explicitly labelled estimated fallback.

MLG schema 8 records fuel percentage, controller status and their quality fields.
Non-live measurements are NaN, preserving the distinction between missing fuel
and an empty tank. `fuel.level_status` records the received status code; consult
`vehicle.fuel_pct` quality for the measurement's validity. The removed local
`fuel.sender_ohms` channel is not written in new files. Existing MLG files retain
their own embedded schema and remain readable.

## Upgrading from the Pi sender implementation

New configuration backups use version 2 and contain no Pi sender settings.
Version-1 backups (and interrupted version-1 restore journals) still restore
all supported settings; their `sender` section is discarded. An old
`/var/lib/frogdash/sender.json` is ignored and cannot enable hardware access.
No old user files are automatically deleted. Microcontroller calibration lives
on that controller and is not included in Frogdash backups.

If you previously installed an I2C-specific systemd drop-in solely for the old
sender, remove only that obsolete setting on the Pi and reload systemd. No I2C
permissions are needed by the Frogdash application. Keep unrelated overrides;
the separate [PiSugar power manager](pisugar-power.md) now owns I2C power control
and replaces the earlier ACC/relay shutdown service.

Bench-test empty/full/intermediate percentages, fault/unavailable status, malformed
frames, and stopped transmission before vehicle use. Automated tests cover CAN
decoding, freshness, trip inventory, browser display, logging and backup migration;
actual controller firmware and the physical sender still need commissioning.
