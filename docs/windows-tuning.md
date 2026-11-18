# Tuning with Windows software (experimental)

MegaSquirt, Speeduino and rusEFI tune with TunerStudio, which runs on the dash (Tuning >
TunerStudio). Most other ECUs tune with their maker's Windows program: Holley EFI, AEM
Infinity Tuner, Haltech NSP, FuelTech FTManager, ECUMaster EMU Client, MaxxECU MTune, Link
PCLink. Choose **Windows tuning** on the setup wizard's "On the dash" page; setup then adds:

- **Wine 11.0 (x86-64) and Box64**, so the Windows program can run on the Pi. On a Pi 5,
  setup also switches to the 4 KB-page kernel Box64 needs (one restart).
- **USB sharing (USB/IP)**, for an ECU or cable that needs its maker's Windows driver.

## Which route: decided by the cable

Wine runs Windows programs, but it cannot load a Windows **driver** (`.sys`). So it depends
on what the ECU's USB is. Plug the tuning cable into the Pi and open **Dash management >
Tuning**: under "USB: the ECU or its tuning cable" each device says which route it takes.

| What Linux sees | Route |
|---|---|
| A USB serial port (FTDI, Silicon Labs CP210x, CH340, Prolific, or a USB ACM device) | The tuner runs **on the dash** in Wine; the port is COM1 (COM2... for more), set up each time the tuner opens |
| Nothing claims it (the maker's own driver) | **Share it with a Windows PC.** The PC attaches it over the dash's Wi-Fi, loads the real driver and runs the tuner as if the cable were plugged into it |

## On the dash (serial cables)

1. Put the maker's installer (`.exe` or `.msi`) on a USB stick and plug it into the Pi.
2. Tuning > **Look on the USB stick**, then **Copy to the Pi**, then **Eject**.
3. **Install**: the installer opens over the dash. Go through it with a mouse.
4. The tuner appears in the list: **Open**. Close it, or hold OFF on the steering wheel, to
   come back to the gauges. In the tuner, pick the COM port the Tuning page shows.

The first start takes a while (Wine sets itself up). Many tuners are 32-bit Windows
programs; how well those run under Box64 depends on the program. If one closes right after
starting, the Tuning page says so: use the Windows PC route instead.

## With a Windows PC (any cable)

1. On the PC, install **usbip-win2** (github.com/vadimgrn/usbip-win2, a signed USB/IP
   client) and the maker's tuner and driver as usual.
2. Join the PC to the dash's Wi-Fi (its hotspot).
3. On the dash: Tuning > **Share with a Windows PC** on the ECU's cable.
4. On the PC, as the Tuning page shows: `usbip attach -r <dash address> -b <port>`. Windows
   now sees the cable; open the tuner.
5. **Stop sharing** when done: the cable is the Pi's again.

The device is shared only while asked, only the one chosen, and only on the dash's own
network (TCP port 3240). The dash keeps reading the ECU's CAN broadcast throughout, so the
gauges and the drive log carry on while you tune.

## What is installed where

| | |
|---|---|
| Wine | `/opt/frogdash-wine/wine` (Kron4ek's build of Wine 11.0, SHA-256 checked) |
| Installers copied from the stick | `/opt/frogdash-wine/installers` |
| The tuners themselves | the screen user's `~/.frogdash-wine` (a Wine prefix) |
| Helpers | `tools/frogdash_wine.py` (screen side), `tools/frogdash_tuning.py` (root: USB stick, USB sharing), `hardware/frogdash/wintune.py` (dash) |
