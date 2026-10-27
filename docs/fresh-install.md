# Fresh install on a new SD card

From a blank card to the dash on the screen: flash, one command, restart. About 20 minutes,
most of it downloads.

## 0. If the Pi showed nothing at all: check the Pi first

A bad SD card stops Linux, but a Raspberry Pi 4 still shows its own **bootloader screen**
without one. Before flashing, take the SD card out, connect the screen to the **HDMI 0**
port (the micro-HDMI next to the USB-C power) and power on:

| You see | Means |
|---|---|
| A grey/white screen with the Raspberry Pi logo and boot text, green LED flashing | The Pi and the screen are fine; the old card was the problem. Carry on. |
| Nothing on the screen, red LED on, green LED flashing a pattern | The Pi is running; count the green flashes against Raspberry Pi's LED codes. Try the other cable/port. |
| Nothing, red LED off or flickering | No proper power: try another 5 V 3 A USB-C supply and cable, and power the Pi directly, without the PiSugar. |
| Nothing at all, both LEDs off, very low current | The Pi is not starting: a new card will not fix it (bootloader EEPROM recovery or a replacement Pi). |

## 1. Flash the card

In **Raspberry Pi Imager**:

1. **Device:** Raspberry Pi 4.
2. **OS:** Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**. Choose the **Bookworm**
   edition if it is offered (it may be listed as Legacy): the car has run on Bookworm. The
   newer release should also work.
3. **Storage:** the new card.
4. **Edit settings** before writing:
   - Hostname `frogdash`.
   - Username **`foxbody`** and a password (the same user as before).
   - Your home Wi-Fi network and country.
   - Services: **enable SSH** with password authentication, for this one install.

## 2. Install

Put the card in, connect the screen to HDMI 0, power on and wait about two minutes. From a
computer on the same Wi-Fi:

```sh
ssh foxbody@frogdash.local
curl -fsSL https://raw.githubusercontent.com/averyizatt/frogdash/main/tools/frogdash_install.sh | sudo sh
```

(No computer: plug a keyboard into the Pi, log in on the screen and type the `curl` line.)

It shows each step as it goes, `OK` or `FAIL` with what to do:

1. Internet and system
2. System packages: git, Python, gpsd, can-utils, Cage and Chromium
3. SPI, I2C and the CAN board: the MCP2515 overlay for the car's board (8 MHz crystal,
   interrupt GPIO 25) in `/boot/firmware/config.txt`
4. The dash's code in `/opt/frogdash`
5. Its Python environment
6. Services: the dash, CAN, the updater and the screen for `foxbody`
7. The dash started and answering
8. The Pi setup: helpers, GPS, the clock from GPS, the phone hotspot, the exact 1920 × 720
   screen mode, the recovery guard and rescue screen, module firmware
9. PiSugar power: the vendor software and the clean shutdown

Everything is logged in `/var/log/frogdash-install.log`. Running it again is safe.

## 3. Restart and check

```sh
sudo reboot
```

The dash appears about 10 seconds after power. Then:

```sh
sudo sh /opt/frogdash/tools/frogdash_install.sh --check
```

It checks each service, the dash answering, `can0`, gpsd, the screen connection, the power
flags (under-voltage) and the Pi setup's steps.

## 4. PiSugar

Step 9 installs the PiSugar Power Manager (unattended, model PiSugar 3) and the dash's
clean shutdown on ignition loss; nothing to do separately. Add `--no-pisugar` to the
install command to leave it out on a Pi without one. Details: [PiSugar power](pisugar-power.md).

## 5. What a new card starts without

Settings lived on the old card, so set these again from the dash:

- **Reports to GitHub:** Dash management → Software & power → Connect GitHub.
- **Dash cam and Wi-Fi networks:** Controls → Wi-Fi.
- **Look, alerts, fuel setup, trips:** Appearance and Drive. The odometer can be set under
  Drive → Trips & economy.
- **TunerStudio:** Tune → Install TunerStudio, when you want it.

After that, **Update now** keeps everything current; nothing else needs SSH.
