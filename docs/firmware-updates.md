# Module firmware from the dash, over the CAN bus

The sensor gateway's firmware can be replaced from the dash through the CAN wire that
already connects them. No USB cable, and no Wi-Fi in the gateway.

## Using it

1. **Update now** (with Wi-Fi connected) downloads the newest gateway firmware onto the
   Pi along with the dash's own update. **System check → Updates → Gateway firmware
   file** shows which build is on the Pi.
2. With the car stopped: **Dash management → Support → Install gateway firmware**, and
   press again to confirm. The same button is on the phone page under *Software*.
3. The status line shows progress. It takes about a minute. The gateway then restarts,
   and the dash confirms it is talking to the new build.

The button only appears when the build on the Pi differs from the one the gateway
reports. While the transfer runs the gateway does nothing else: speed, fuel level, the
steering wheel buttons and the interior lights pause, and come back when it restarts.

**The first time, the gateway needs flashing once by USB** from VS Code, because the
firmware it has now cannot receive an update. Until then the dash says the gateway is
not answering.

## Where the firmware comes from

The gateway's repository builds its firmware on GitHub on every change and publishes it
as the `gateway-latest` release, with a manifest holding the build number, size and
SHA-256. The Pi setup (`tools/frogdash_setup.sh`, step *Gateway firmware file*)
downloads both and only keeps a file that matches its SHA-256. The build number is the
first eight hex digits of the commit; a build flashed from the editor reports
`00000000`.

## What keeps it safe

| | |
|---|---|
| Moving | The dash refuses to start while a speed reading says the car is moving, and stops the transfer if it starts moving. The gateway then simply carries on |
| A bad frame | The image goes in blocks of 448 bytes. The gateway writes a block only when every frame arrived and its CRC-16 matches; otherwise the dash sends that block again, more slowly |
| A bad image | Before restarting, the gateway checks the CRC-32 of everything received and the image's own checksum. A wrong or incomplete image is discarded and the old firmware keeps running |
| A firmware that does not work | The new firmware starts on trial. If the dash has not confirmed it within 90 seconds, or it hangs or crashes, the gateway restarts into the firmware it had before. The dash reports that it went back |
| An interrupted transfer | The running firmware is never overwritten: the image goes into a spare slot. A transfer the dash abandons is dropped after 5 seconds |

## Messages

Two additive messages (`hardware/can_contract/include/can_contract/firmware_update.h`,
the same file the gateway is built with). They sit in the block reserved for future
use, clear of the MicroSquirt's broadcast range (0x5F0–0x62F). Modules without this
simply ignore them.

| ID | Direction | DLC | Content |
|---|---|---:|---|
| 0x680 | dash → module | 8 | Commands (query, begin, block end, end, abort, confirm) naming a target module, and the image data, seven bytes a frame |
| 0x681 | module → dash | 8 | Build and state, and an acknowledgement of every command |

Target 1 is the sensor gateway. Target 2 is reserved for the taillight controller,
which does not implement it yet. The water/meth Nano cannot be updated this way.

## Tests

`tests/test_fwupdate.py` runs the dash's sender against the gateway's real receiver code,
compiled for the computer from the shared header: a complete transfer, lost frames and
lost answers, a gateway that goes back to its old firmware, one that never comes back,
refusals, and the car moving off mid-transfer. `tests/test_can_contract.py` checks every
frame the dash builds against the gateway's own builders. None of this has run on the
car: the first real transfer is the test of the wiring and timing.
