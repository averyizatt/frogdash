# Module firmware from the dash, over the CAN bus

The firmware of the car's ESP32 modules can be replaced from the dash through the CAN
wire that already connects them. No USB cable, and no Wi-Fi in the modules.

| Module | From the dash | Time | While it runs |
|---|---|---|---|
| Sensor gateway | Yes | About a minute | Speed, fuel level, wheel buttons and interior lights pause |
| Taillight controller | Yes | A few minutes (its firmware is three times the size) | Lamps dark. Lights off and foot off the brake: any light input stops the update at once |
| Water/meth controller, ESP32 board | Yes | About a minute | Injection off. Engine off: it will not start, and stops, if the pump is on or boost comes up |

## Using it

1. **Update now** (with Wi-Fi connected) downloads the newest firmware of each module
   onto the Pi along with the dash's own update. **System check → Updates** shows which
   build of each is on the Pi and which each module is running.
2. With the car stopped: **Dash management → Software & power → Install** (a row per module), and press
   again to confirm. The same buttons are on the phone page under *Software*.
3. The status line shows progress. The module then restarts. The dash waits until it
   answers as the new build **and its own regular messages are back on the bus and stay
   fresh for 3 seconds** (the gateway's speed and RPM, the taillights' light state, the
   water/meth controller's state, knock state and tuning status), and only then confirms
   the build. If they do not come back within 20 seconds, the dash does not confirm it and
   the module goes back to the firmware it had, by itself. The event log and the status
   line say which messages came back, or which did not.

A button only appears when the build on the Pi differs from the one the module reports.
One module is updated at a time.

**The first time, each module needs flashing once by USB** from VS Code, because the
firmware it has now cannot receive an update. Until then the dash says that module is
not answering.

## Where the firmware comes from

Each module's repository builds its firmware on GitHub on every change and publishes it
as a release (`gateway-latest`, `taillights-latest`, `watermeth-latest`) with a manifest
holding the build number, size, SHA-256 and the system version (`VERSION`: "1.1" for a
build on the release tag `v1.1`, "1.1+" for one after it), which the dash shows beside the
build. The Pi setup (`tools/frogdash_setup.sh`,
steps *Gateway firmware file*, *Taillight firmware file* and *Water/meth firmware
file*) downloads them and only keeps a file that matches its SHA-256. The build number is the first eight hex digits of the commit; a
build flashed from the editor reports `00000000`, so the published build is offered
over it.

## What keeps it safe

| | |
|---|---|
| Moving | The dash refuses to start while a speed reading says the car is moving, and stops the transfer if it starts moving. The module then simply carries on |
| The module's real work | The taillight controller will not start while any light input is on, and drops the transfer the instant one comes on. The lights always win. The ESP32 water/meth controller does the same for the pump running or boost within 1 psi of its start, and holds the pump off during a transfer |
| A bad frame | The module writes a block only when every frame arrived and its CRC-16 matches. With protocol version 2 it keeps the frames that arrived and names the range it missed, and the dash sends only that range again; a damaged block is sent again whole. Version 1 sends a block again whole either way. Each miss slows the dash's pace a step |
| A block that will not unpack | Version 2 compresses each block on its own: a block whose bytes arrived as sent but do not unpack to exactly its 8 KB of image calls the transfer off, and the old firmware keeps running |
| A bad image | Before restarting, the module checks the CRC-32 of everything received and the image's own checksum. A wrong or incomplete image is discarded and the old firmware keeps running |
| A firmware that does not work | The new firmware starts on trial. If the dash has not confirmed it within 90 seconds, or it hangs or crashes, the module restarts into the firmware it had before. The dash only confirms once the module's own messages are back and steady, so a build that starts but does not do its job is not kept either. The dash reports that it went back |
| An interrupted transfer | The running firmware is never overwritten: the image goes into a spare slot. A transfer the dash abandons is dropped after 5 seconds |

## How fast, and protocol version 2

From November 2026 the update protocol has a version 2 (`firmware_update.h`), which every
module's firmware reports in its answer to the dash's query:

- **Blocks of 8 KB of image**, so the dash waits for an answer about 50 times for the
  water/meth controller's image instead of about 900. It still pauses every few frames,
  at the pace the module keeps up with.
- **Compression:** each block is sent as its own zlib stream and the module unpacks it with
  the decompressor in the ESP32's ROM. The published images shrink to 59-65%.
- **Only the missing frames again**, not the block.
- **Faster reading on the boards:** the gateway and the water/meth controller talk to their
  CAN controller at 8 MHz instead of 1 MHz (the wiring is soldered), and the water/meth
  controller reads it every 0.2 ms during a transfer instead of every millisecond. Before,
  it lost frames and the dash slowed to one frame per 2 ms: 2.8 KB/s.

The dash uses version 2 only with a module that reports it, and version 1 otherwise, so
**the first update to firmware with version 2 goes the old, slower way**; the status line
then says its next updates take the faster protocol. A dash from before version 2 sends a
module version 1, which the module still takes.

## Messages

Two additive messages (`hardware/can_contract/include/can_contract/firmware_update.h`,
the same file the modules are built with). They sit in the block reserved for future
use, clear of the MicroSquirt's broadcast range (0x5F0–0x62F). Modules without this
simply ignore them.

| ID | Direction | DLC | Content |
|---|---|---:|---|
| 0x680 | dash → module | 8 | Commands (query, begin, block end, end, abort, confirm, restart) naming a target module, and the image data: seven bytes a frame in version 1, six (and two naming the frame) in version 2 |
| 0x681 | module → dash | 8 | Build and state, and an acknowledgement of every command |

Target 1 is the sensor gateway, target 2 the taillight controller, target 3 the ESP32
water/meth controller.

The ESP32 board is the water/meth controller in the car since November 2026. It refuses
an update, and drops one that is running, when the pump is on or boost is near: install
with the engine off.

The water/meth row distinguishes telemetry from firmware-update replies:

| The water/meth controller | The line reads |
|---|---|
| Not heard at all | *Not answering*: check the ESP32 board's power and CAN wiring |
| State reports arrive, but no firmware reply | *Not answering*: flash `esp32s3_water_meth` once by USB if its firmware lacks the updater |
| Firmware replies arrive | The installed build and any available update |

Both current pulse firmware and earlier ESP32 PWM firmware use the same updater.

The first flash of the ESP32 board is by USB from VS Code. It then reports build
`00000000`, and the published build is offered over it on this line.

## Adding another module

Any ESP32 module with two application slots (the default 4 MB and 8 MB layouts have
them) can join without a new message:

1. **Module firmware:** take the next target number in `firmware_update.h`, create a
   `can_protocol::firmware::Receiver` with a small flash adapter (five calls into
   `esp_ota_ops.h`; the gateway's `OtaFlash` is the pattern), let its CAN filter accept
   0x680, hand those frames to the receiver, and return `true` from
   `verifyRollbackLater()`. If the module has work that must not wait, refuse or cancel
   with the *busy* status as the taillight controller does.
2. **Its repository:** copy the gateway's GitHub workflow so every push publishes the
   image and its manifest.
3. **The dash:** one row in `MODULES` in `hardware/frogdash/fwupdate.py` and one
   `firmware_file` line in `tools/frogdash_setup.sh`. The Support tab, the phone page
   and System check follow the table.

## Tests

`tests/test_fwupdate.py` runs the dash's sender against the modules' real receiver code,
compiled for the computer from the shared header: complete transfers to all three
targets, lost frames and lost answers, a module that goes back to its old firmware, one
that never comes back, one that refuses or stops because it is needed, a controller
that does not answer firmware commands despite sending state reports, and the car moving off mid-transfer;
and for version 2: compressed and plain transfers, only the missing frames sent again, the
first update going the old way and the next the new, and a new build whose own messages
do not come back (not confirmed) or come back late (waited for). The modules' own tests
(`test/test_firmware_update` in DIYComfortControlModule) cover the receiver's version 2
on its own.
`tests/test_can_contract.py` checks every frame the dash builds against the modules'
own builders. All three firmwares are compiled by their GitHub workflows. None of this has run on the car: the first real transfer is the test of
the wiring and timing.
