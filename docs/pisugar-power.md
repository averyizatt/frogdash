# PiSugar 3 Plus ignition power

This replaces the former BCM23 ACC input / BCM24 relay shutdown design. The
PiSugar supplies the Pi through cranking, while an independent Linux service
watches its external input. No CAN message, browser, GPS fix or Wi-Fi connection
is needed for power management. The target remains a Pi 4 with a systemd-based
console Linux installation; the exact installed distribution still needs checking.

## Behavior

| Event | Action |
| --- | --- |
| Ignition supplies the UPS input | PiSugar auto power-on starts a cold Pi boot. |
| Input drops for less than 8 seconds | Battery keeps the Pi running; restoration cancels the countdown. |
| Input remains absent for 8 seconds | Frogdash's power monitor requests normal `systemctl poweroff`. |
| Linux stops services | Frogdash closes its current MLG log and saves trip/review state through its existing cleanup. |
| Services have stopped and filesystems are unmounted/read-only | A final systemd shutdown hook asks PiSugar to turn off its output. |
| Next ignition/input restoration | PiSugar starts the Pi again. |

The default **8 seconds starts shutdown**, not a hard power cutoff. Actual output
off occurs later, after Linux shutdown and a final 3-second vendor countdown.
Set 5 through 10 seconds in `/etc/default/frogdash-power`. Detection polls about
twice per second, so timing includes polling/communication latency. Each new dip
gets a new countdown; it is not accumulated across cranking attempts. At boot,
counting starts with the first valid absent-input sample, even if the service has
never seen external power. The UPS must support the load during boot as well.

The detector uses `battery_power_plugged`, not `battery_charging`: a full battery
can stop charging while external power is still present. Missing/invalid I2C or
socket replies mean **unknown**, clear the countdown, and appear in the journal.
An observation gap longer than two seconds also restarts the countdown. The
vendor daemon's separate low-battery shutdown remains a fallback if this monitor
fails; it cannot protect against a dead battery or a completely hung OS.

Once Linux has accepted shutdown it is committed, even if ignition returns.
PiSugar documents automatic startup when external power is restored while off;
it does **not establish what happens when power returns during Linux shutdown**.
Bench-test that sequence on the installed firmware. It may need another off/on
input cycle after output turns off. Do not assume instant resume or guaranteed
restart for that race. A normal reboot deliberately does not cut UPS output.

## Debugging: UPS and previous shutdown

Open **Drive > Dash health**. The first four cards show UPS battery percentage
and voltage, charging state, external-input presence, the reported automatic
startup setting, and evidence from the previous recorded boot. UPS percentage
is the vendor's estimate, not the vehicle fuel/battery reading. Missing or stale
readings show **Unavailable**, never a fabricated 0% or a remembered full battery.
The monitor samples UPS telemetry independently every five seconds; the health
screen refreshes about every five seconds. A full battery may correctly show
external power present and not charging.

**Previous shutdown** has four outcomes:

- **Data synced:** the previous boot's final Frogdash run completed cleanup,
  drained accepted MLG samples, closed/synced its log, saved trip/review/race
  state, and wrote a synced completion record. The completion time is displayed.
- **Unconfirmed:** the previous run left an in-progress record. Power loss,
  a service crash, forced termination or an interrupted shutdown can cause this.
- **Save failed:** orderly cleanup returned a storage error; the detail appears
  below the cards. This is not labeled a successful save.
- **No record:** first use or unavailable/unreadable history. It is not proof of
  an unsafe shutdown.

Evidence is stored in `/var/lib/frogdash/shutdown.json` (or the selected data
folder; replay is isolated). Startup first writes and fsyncs an in-progress
marker; only completed cleanup replaces it with a completion record. Linux boot
IDs distinguish a real new boot from a dashboard service restart. A restart
within the same boot keeps the previous boot's result and counts any earlier
unclean service exits. The UI also discloses dropped recorder samples or disabled
recording: successful storage flush does not mean every telemetry sample was
captured. On platforms without Linux boot IDs the scope is explicitly a previous
service run. History is local diagnostic evidence, not a portable backup item.

This confirms **application save/flush completion reported by the filesystem**.
It cannot certify SD-card electronics, prove that every other Linux service
stopped cleanly, or prove the UPS physically cut output. Writing a successful
"whole OS powered off" marker after power has gone away is not possible. The
late cutoff hook still supplies the actual ordering described above.

For an existing installation, update/restart the backend and refresh the kiosk
as usual. Also update the independently installed monitor for battery telemetry:

```sh
# Use stable external input while replacing the running power monitor.
sudo install -m 0644 /opt/frogdash/hardware/power/monitor.py /usr/local/lib/frogdash-power/monitor.py
sudo systemctl restart frogdash-power
```

The public preview shows labeled simulated UPS and shutdown evidence; it does
not query local Pi hardware. Older monitors without the new telemetry fields
show unavailable until updated.

## Ignition returning: what restarts, and when

| When input returns | Current behavior |
| --- | --- |
| Before the 8-second loss deadline | Cancel the timer; keep the current session running. |
| After UPS output has switched off | PiSugar's enabled power-restore feature turns output on and cold-boots the Pi. |
| After Linux accepted poweroff, but before UPS output is off | Complete shutdown. Firmware behavior for this overlapping input edge must be tested on the actual board. |

The second case is a PiSugar hardware function; Linux does not need to be alive
or poll anything to wake it. The dashboard's **Startup on power return** card
shows the daemon's configured setting, not proof of a successful physical wake.
The official datasheet specifies restoration **while PiSugar is off**; it does
not guarantee the third case. SCL wake is described for a Pi already halted when
PiSugar turns on, and is not documented as a latch for an earlier ignition edge.

First verify the installed firmware with input returning at several points in
shutdown. If it handles the overlap, no extra hardware is needed. If it remains
off, cycling ignition off/on after cutoff is the immediate recovery. Increasing
the grace period to 10 seconds can cover more quick key cycles, but does not
eliminate the race.

For unattended restart even with such firmware, the robust fallback would be an
external controller that **remembers the restart request, waits for confirmed
UPS output-off, then reapplies the regulated 5 V input** through a suitable
converter-enable/input switch. It needs a shutdown-committed indication or an
equivalent coordinated state machine to distinguish a brief crank from committed
shutdown, plus output sensing; an arbitrary delay alone is not confirmation.
The existing vehicle MCU could be considered once its wiring is defined. This is
a proposed hardware fallback, not implemented or tested by this update. It must
never interrupt UPS output ahead of Linux cleanup. A Pi-only process cannot act
after its own power has been removed, and blindly arming a periodic wake timer
would also wake the dash with ignition off.

## Wiring and power budget

```text
Ignition-switched vehicle supply
  -> fused, automotive-protected regulated 5 V supply
  -> PiSugar 3 Plus input
  -> PiSugar battery-backed output / Pi mounting contacts
  -> Raspberry Pi 4
```

PiSugar 3 Plus accepts **5 V, not vehicle 12 V**; its documented input and output
maximum is **5 V / 3 A**. Size the upstream converter for the complete load and
charging, and measure voltage/current under load. Keep the HDMI screen on its
own suitable supply unless its measured consumption fits within the UPS budget.
Keeping the Pi alive does not keep a separately powered display lit during crank.
Avoid another supply to the Pi USB-C input or USB back-power from the display or
a powered hub: those can bypass the intended cutoff. Mount the battery within
its manufacturer's environmental limits; charging-chip temperature telemetry is
not a battery-temperature measurement.

PiSugar communicates on **I2C1, BCM2/SDA and BCM3/SCL** (header pins 3 and 5),
with addresses **0x57 and 0x68**. The vendor model selection is **PiSugar 3**,
including the Plus. This does not conflict with the current MCP2515 SPI0 wiring
or BCM25 interrupt. No Pi fuel-sender ADC or BCM23/24 power GPIO is used.
Retire the old relay/ACC wiring while everything is unpowered; it must not cut
the UPS output or back-feed the Pi. Input to the UPS must actually follow ignition,
not an always-live battery feed, for input-loss detection to serve as key-off.

Output-off is the UPS's low-power standby/hibernate state, not a mechanical
battery disconnect with zero standby current. Keep auto-hibernate enabled and
avoid RTC wake schedules, SCL wake or a watchdog configuration that would wake
the Pi unexpectedly while parked. These hardware features are not blindly
rewritten by Frogdash.

## Install on the Pi

Do this on a bench with stable external input and a charged UPS. These files are
prepared in the repository; they have not been installed or tested on your Pi.
Commands assume Raspberry Pi OS/Debian with `/usr` on the root filesystem,
`/usr/bin/python3`, `/usr/bin/systemctl` and systemd's
`/usr/lib/systemd/system-shutdown/` hook directory. Confirm paths for another OS.
The final hook cannot rely on networking, a running daemon, `/var`, or a writable
filesystem. Its vendor binary, shared libraries and config must remain readable
at final shutdown; do not use a separate unmounted `/usr` for this setup.

1. Identify and disable the **actual old ACC/relay service** before enabling
   either new shutdown policy. Its filename is not in this repository. Inspect
   `systemctl cat YOUR_OLD_POWER.service`, then disable/stop that identified unit
   on the bench. Disconnect the old relay control so cleanup of the old script
   cannot remove the Pi's new supply. Keep the script/unit as a rollback copy.
   Search any custom shutdown hooks for other early power cuts as well.
2. Enable I2C with `sudo raspi-config` (Interface Options > I2C), following its
   reboot instruction. Install the official PiSugar Power Manager from the
   [vendor instructions](https://docs.pisugar.com/docs/product-wiki/battery/pisugar3/pisugar-3-series),
   selecting **PiSugar 3**. Check `systemctl cat pisugar-server` and
   `command -v pisugar-poweroff`. Do not enable two power-loss monitors.
3. Replace the vendor's early poweroff unit with the late hook. The vendor unit
   has `DefaultDependencies=no` and runs before `shutdown.target`; its short
   cutoff countdown can overlap application shutdown. Merely setting that
   countdown to eight seconds would not fix ordering. **Do not start that unit
   or run `pisugar-poweroff` manually on a mounted, running system.**

From a reviewed checkout at `/opt/frogdash`:

```sh
# Disable and mask, without --now: this is a shutdown-only vendor unit.
sudo systemctl disable pisugar-poweroff.service
sudo systemctl mask pisugar-poweroff.service
sudo install -d -m 0755 /usr/local/lib/frogdash-power
sudo install -m 0644 /opt/frogdash/hardware/power/monitor.py /usr/local/lib/frogdash-power/monitor.py
sudo install -m 0755 /opt/frogdash/hardware/power/frogdash-pisugar-poweroff /usr/lib/systemd/system-shutdown/frogdash-pisugar-poweroff
sudo install -m 0644 /opt/frogdash/hardware/systemd/frogdash-power.service /etc/systemd/system/
sudo install -m 0644 /opt/frogdash/config/frogdash-power.env /etc/default/frogdash-power
```

If masking reports an existing local unit file, inspect and back up that unit,
then resolve the local override before continuing; verify it is actually masked.
The hook runs for `poweroff` and `halt`, including low-battery and manually
requested shutdowns. It skips `reboot`/`kexec`. It calls the official direct-I2C
binary after the daemon has stopped; no raw register writes are added here.

The vendor's usual defaults also expose TCP/HTTP/WebSocket control listeners.
For this car, use its **root-only local Unix socket** so Wi-Fi log sharing cannot
expose UPS commands. Back up `/etc/default/pisugar-server` before replacing it:

```sh
sudo cp -a /etc/default/pisugar-server /etc/default/pisugar-server.before-frogdash
sudo install -m 0644 /opt/frogdash/config/pisugar-server.default /etc/default/pisugar-server
sudo systemctl restart pisugar-server
sudo python3 /usr/local/lib/frogdash-power/monitor.py --configure-vendor
sudo systemctl restart pisugar-server
sudo python3 /usr/local/lib/frogdash-power/monitor.py --check
```

Configuration enables auto power-on, the physical button's soft shutdown, and
low-battery shutdown at **10% after 5 seconds**, preserving unrelated settings.
The button requests `/usr/bin/systemctl poweroff`. The 5-second low-battery setting
is independent of the 8-second ignition-loss timer, and can end a crank grace
period early if the battery is depleted. Restart/readback verifies the persisted
settings; command errors stop configuration rather than claiming success. The
helper supports the vendor's old and current low-battery command spellings.
`--check` verifies reported UPS settings; it is not a wiring/cutoff hardware test.
`--uds-mode` must be supported by the installed vendor server; update it if not.
After vendor package/firmware updates, repeat configuration/readback and confirm
the early cutoff service is still masked and network listeners remain disabled.

Run the observer first; **dry-run is the default** and never requests shutdown:

```sh
sudo python3 /usr/local/lib/frogdash-power/monitor.py --dry-run --loss-delay 8
```

With a charged battery, unplug/reconnect the **UPS input** for short intervals.
Look for `external_power`, `on_battery`, and (after eight seconds) `would_shutdown`.
Press Ctrl+C to stop the observer. The vendor's low-battery policy and physical
button remain active even during this observer test. After that works:

```sh
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/frogdash-power.service
systemctl is-enabled pisugar-poweroff.service  # must print masked
sudo systemctl enable --now frogdash-power.service
journalctl -u frogdash-power -u pisugar-server -f
```

The root-owned monitor is installed separately from application releases and
runs even if Frogdash/Chromium crashes or restarts. It uses only Python's standard
library. The ordinary Frogdash process retains its existing limited permissions;
it gains neither I2C access nor a web shutdown endpoint. The service deliberately
shares `/tmp` to reach the vendor socket; it must not use `PrivateTmp=yes`.
Read-only runtime status is in `/run/frogdash-power/status.json`, including
input state, time remaining, errors and timestamp. Writes stay in RAM. A stopped
service or an old timestamp must be treated as unavailable, not a live reading.

To adjust the delay, edit `/etc/default/frogdash-power` and restart only
`frogdash-power`. The installed service uses `--execute`; do not put `--dry-run`
in that environment file. For maintenance, stop the monitor while external input
is stable; this does not disable the vendor's independent low-battery policy.
Ordinary Frogdash release installation does not replace these power files.

## Acceptance checks before vehicle use

- Measure the Pi/USB load and battery voltage while powered only by the UPS.
- Repeat 1-, 3- and 5-second input drops; the Pi should stay up and retain its log.
- Drop input beyond the configured delay: confirm the orderly shutdown messages,
  actual UPS output-off, and a clean latest MLG/trip checkpoint on the next boot.
- Restore input after output-off: verify automatic cold boot repeatedly.
- Restore just before eight seconds, during shutdown, and just after cutoff;
  record whether the during-shutdown case needs another ignition cycle.
- Reboot normally with input present: output should stay on and the Pi reboot.
- Stop the vendor daemon: the monitor should report unavailable, not infer key-off.
  Restart it and confirm the monitor recovers without accumulating the unknown gap.
- Verify low-battery and physical-button shutdown on the bench. Check behavior
  after a deeply depleted battery; do not assume immediate cold boot while charging.
- Recheck boot timing and actual cranking voltage/USB/display back-feed in the car.

`tests/test_power.py` exercises continuous-loss timing, restoration, boot on
battery, communication failure, dry-run, retry/commit semantics, vendor protocol,
Unix socket transport and hook action selection. Hardware changeover, voltage
headroom, final I2C cutoff and firmware wake behavior require the real board.
The vendor cutoff binary's exit status alone is not proof that power went off.

## Source basis

- [PiSugar 3 series](https://docs.pisugar.com/docs/product-wiki/battery/pisugar3/pisugar-3-series):
  Pi 4 compatibility, ratings, model selection and restore behavior.
- [PiSugar 3 I2C registers](https://docs.pisugar.com/docs/product-wiki/battery/pisugar3/pisugar-3-i2c):
  input presence at 0x02 bit 7, restore at bit 4, delayed output-off at bit 5;
  hibernate behavior and wake sources. The vendor library handles write protection.
- [Power Manager API](https://docs.pisugar.com/docs/product-wiki/battery/pisugar-power-manager)
  and [audited source](https://github.com/PiSugar/pisugar-power-manager-rs/tree/b1e9388dd7984766458f018e7927d9e343a38a34):
  socket replies, config persistence, poweroff unit and direct-I2C cutoff binary.
- [systemd shutdown ordering](https://github.com/systemd/systemd/blob/main/man/systemd-poweroff.service.xml):
  final shutdown hooks run after services stop and filesystem teardown.

Research checked September 28, 2026. Firmware and Power Manager have separate
version numbers; verify the actual installed versions during commissioning.
