# Module firmware from the dash, over the CAN bus

The firmware of the car's ESP32 modules can be replaced from the dash through the CAN
wire that already connects them. No USB cable, and no Wi-Fi in the modules.

| Module | From the dash | Time | While it runs |
|---|---|---|---|
| Sensor gateway | Yes | About a minute | Speed, fuel level, wheel buttons and interior lights pause |
| Taillight controller | Yes | A few minutes (its firmware is three times the size) | Lamps dark. Lights off and foot off the brake: any light input stops the update at once |
| Water/meth Nano | No: see below | | |

## Using it

1. **Update now** (with Wi-Fi connected) downloads the newest firmware of each module
   onto the Pi along with the dash's own update. **System check → Updates** shows which
   build of each is on the Pi and which each module is running.
2. With the car stopped: **Dash management → Support → Install … firmware**, and press
   again to confirm. The same buttons are on the phone page under *Software*.
3. The status line shows progress. The module then restarts, and the dash confirms it
   is talking to the new build.

A button only appears when the build on the Pi differs from the one the module reports.
One module is updated at a time.

**The first time, each module needs flashing once by USB** from VS Code, because the
firmware it has now cannot receive an update. Until then the dash says that module is
not answering.

## Where the firmware comes from

Each module's repository builds its firmware on GitHub on every change and publishes it
as a release (`gateway-latest`, `taillights-latest`) with a manifest holding the build
number, size and SHA-256. The Pi setup (`tools/frogdash_setup.sh`, steps *Gateway
firmware file* and *Taillight firmware file*) downloads them and only keeps a file that
matches its SHA-256. The build number is the first eight hex digits of the commit; a
build flashed from the editor reports `00000000`, so the published build is offered
over it.

## What keeps it safe

| | |
|---|---|
| Moving | The dash refuses to start while a speed reading says the car is moving, and stops the transfer if it starts moving. The module then simply carries on |
| The module's real work | The taillight controller will not start while any light input is on, and drops the transfer the instant one comes on. The lights always win |
| A bad frame | The image goes in blocks of 448 bytes. The module writes a block only when every frame arrived and its CRC-16 matches; otherwise the dash sends that block again, more slowly |
| A bad image | Before restarting, the module checks the CRC-32 of everything received and the image's own checksum. A wrong or incomplete image is discarded and the old firmware keeps running |
| A firmware that does not work | The new firmware starts on trial. If the dash has not confirmed it within 90 seconds, or it hangs or crashes, the module restarts into the firmware it had before. The dash reports that it went back |
| An interrupted transfer | The running firmware is never overwritten: the image goes into a spare slot. A transfer the dash abandons is dropped after 5 seconds |

## Messages

Two additive messages (`hardware/can_contract/include/can_contract/firmware_update.h`,
the same file the modules are built with). They sit in the block reserved for future
use, clear of the MicroSquirt's broadcast range (0x5F0–0x62F). Modules without this
simply ignore them.

| ID | Direction | DLC | Content |
|---|---|---:|---|
| 0x680 | dash → module | 8 | Commands (query, begin, block end, end, abort, confirm) naming a target module, and the image data, seven bytes a frame |
| 0x681 | module → dash | 8 | Build and state, and an acknowledgement of every command |

Target 1 is the sensor gateway, target 2 the taillight controller.

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

## The water/meth Nano

The Nano cannot be updated this way as it is. Its ATmega328P can only rewrite its own
program from a bootloader, the one it has listens on USB serial, and there is no spare
slot to keep the old firmware in. Doing it over CAN means replacing that bootloader
with a CAN one, which needs a hardware programmer once and leaves no automatic
way back if a transfer goes wrong (the bootloader survives, so it can be tried again,
but the pump controller is out of action until one succeeds). Replacing the Nano with
an ESP32 board would put it on the same footing as the other modules.

## Tests

`tests/test_fwupdate.py` runs the dash's sender against the modules' real receiver code,
compiled for the computer from the shared header: complete transfers to both targets,
lost frames and lost answers, a module that goes back to its old firmware, one that
never comes back, one that refuses or stops because it is needed, and the car moving
off mid-transfer. `tests/test_can_contract.py` checks every frame the dash builds
against the modules' own builders. Both firmwares are compiled by their GitHub
workflows. None of this has run on the car: the first real transfer is the test of
the wiring and timing.
