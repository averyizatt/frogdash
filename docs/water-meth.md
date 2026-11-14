# Water/meth: flow, failsafes, presets and intake temperatures

Written for this car: 2.3 L Lima turbo at up to 10 psi, a 0.9 MPa (130 psi) 4–6 L/min
pump, a nozzle sold as 60 ml/min (1 GPH) that measures about 160 ml/min on this pump,
a metal check valve right before it, and a 2 L tank.

The water/meth controller is an **ESP32-S3**, with the pump on a MOSFET at GPIO15.
It runs full on or full off in long pulses, with a 0.4 s soft start on each run.
There is no master relay; GPIO17 is unused. Boost and RPM come from the MicroSquirt.

Use current DIYWaterMethInjection firmware (CAN contract extension 10). The dash
also understands the earlier ESP32 PWM drive until the new firmware is installed.
Knock listening is off in the firmware for now ([knock.md](knock.md)); injection
does not depend on it.

## How much fluid the engine can use

The numbers are estimates: 85% volumetric efficiency, 50 °C charge air, 12:1 air/fuel
at full load, and about 85 kPa of air pressure at Grand Junction's altitude. The nozzle
is taken at the 160 ml/min measured on the pump test (November 2026): a 3 s test at full
pressure gave a very fine mist and about 8 g of water, counting what the still-pressurised
line sprayed after the pump stopped. To measure again: a 3 s pump test into a cup on a
scale; grams × 20 = ml/min.

| Boost | RPM | Fuel burned | Nozzle running flat out |
|---|---|---|---|
| 5 psi | 2500 | 262 g/min | 61% of fuel |
| 5 psi | 4000 | 420 g/min | 38% |
| 10 psi | 3000 | 406 g/min | 39% |
| 10 psi | 4000 | 541 g/min | 30% |
| 10 psi | 5500 | 744 g/min | 22% |

Water-only injection is usually run at roughly 10–15% of fuel. So:

- **On all the time, this nozzle is too much everywhere.** Even at 10 psi and 5500 RPM
  it is 22% of fuel, and at 5 psi and 2500 RPM 61%: enough to misfire and bog. So the
  pump runs in pulses and the dose limit sets them: at 10% of fuel, 0.85 s of every 4 s
  at 2500 RPM and 10 psi, 1.7 s at 5000 RPM.
- **Keep the dose limit on**, and the nozzle size at what it measures. With the label's
  60 ml/min the limit would let through nearly three times the water it means to.
- **A running engine cannot hydrolock from this nozzle.** A cylinder needs about 80 ml
  of liquid at once to lock (575 cc per cylinder at 8:1). The nozzle delivers under 3 ml
  per second to all four cylinders, about 0.03 ml per intake stroke at 2500 RPM.

Hydrolock comes from fluid collecting while the engine is **not** running: the pump
running with the engine stopped, or fluid draining or siphoning into the intake while
parked. The failsafes below are aimed there.

## Failsafes

### In the controller (always on)

- **No fresh manifold pressure or engine RPM, no injection.** The ESP32 reads the
  MicroSquirt directly over CAN and expires its readings after half a second. The
  dash sends `0x309` as an RPM backup; it cannot replace missing manifold pressure.
  RPM below your minimum also holds the pump off.
- **Extra triggers stay inside the rules.** The early start and the hot-air addition
  below never override disarmed, tank low, a fault, the RPM requirement, the dose
  limit or the spray time limit.
- **Dose limit.** The controller estimates fuel flow from RPM and manifold pressure from CAN
  and holds fluid to a set share of it (10% for water by default). At low airflow the
  pump runs for less of each cycle, or not at all.
- **Spray time limit.** After the longest continuous spray it rests, and short lifts
  do not reset the clock.
- **Tank low, missing manifold pressure or controller fault** stop injection.
- **Settings are limited and checked.** Out-of-range values are clamped by the
  controller, one setting never raises another, and corrupt saved settings fall back
  to the conservative defaults.

### For the pump

The MOSFET runs the pump in slow pulses at full pressure:

- The pump runs for **at least half a second** or not at all.
- It rests for **at least half a second**, or stays on continuously.
- It starts **at most once per cycle**, and the cycle cannot be shorter than 1 s. The
  presets use 4 s.
- A pulse cut short (for example RPM lost) stays off for the rest of that cycle.

Each run ramps from 5% to full duty over 0.4 s. Continuous runs across cycle
boundaries do not restart the ramp.

### Hardware the software cannot replace

These matter more than any setting:

- **Check valve at the nozzle** (or a solenoid). Without one the line can drain or
  siphon into the intake with the engine off. Mount the tank lower than the nozzle if
  you can.
- **There is no independent pump cutoff.** If the MOSFET fails switched on,
  software cannot stop the pump; its power must be removed.
- **Pump power from an ignition-switched fuse**, never straight from the battery.

## Where it is on the dash

- **The water/meth tile on the main dashboard turns solid green and reads PUMP ON**
  while the pump is running. Between pulses it keeps a thin green outline and
  reads *INJECTING · PUMP RESTING*. The controller reports the pump output the moment it
  switches.
- **Controls → Water / meth**: arm, disarm, pump test, and a live card: what the
  controller is doing and why, the pump run time, the estimated flow in ml/min and as
  a share of fuel, and the intake temperature before and after the nozzle.
- **Controls → Meth tuning**: the tank mix, flow presets, every setting, and
  Save / Revert / Defaults.

Values on the tuning page are read back from the controller, never assumed. A change
applies at once and is marked unsaved; **Save to controller** stores it in the ESP32.

## In the tank

Pick what is in the tank; it sets the blend and a matching dose limit.

| In the tank | Methanol | Dose limit (fluid as % of fuel) |
|---|---|---|
| Water only | 0% | 10% |
| 18% meth | 18% | 12% |
| 36% meth | 36% | 15% |
| 53% meth | 53% | 18% |

Methanol burns, so the engine tolerates more fluid as the methanol share rises. It
also adds a little fuel: with 53% methanol through this nozzle the mixture is about
1–2% richer at full power, and up to about 4% richer at the dose limit. The dose
limits are starting points; change the number on the tuning page if your plugs and
air/fuel readings say otherwise.

## Flow presets

All use a 4 s cycle, need engine RPM and leave overboost assist off.

| | Conservative | Mild | Standard |
|---|---|---|---|
| Pump runs, start → full boost | 1 s → 2 s in every 4 s | 1.5 s → 3 s | 2 s → on continuously |
| Flow, start → full boost | 40 → 80 ml/min | 60 → 120 ml/min | 80 → 160 ml/min |
| Boost, start → full | 0.5 → 10 psi | 4.5 → 9 psi | 4 → 8 psi |
| Spray limit / rest | 12 s / 6 s | 20 s / 5 s | 30 s / 4 s |
| Run-time growth per cycle | 0.5 s | 1 s | 2 s |

With the measured 160 ml/min nozzle, Conservative at full boost is about 11% of fuel
at 5500 RPM, already at the 10% dose limit, and the dose limit shortens it below
that. Mild and Standard ask for more than the dose limit allows almost everywhere: it
then sets the pulses, so they differ mainly in how soon a spray reaches that limit.

**Custom 1–3** hold your own flow settings: choose a slot and press **Store current
here**. A flow preset leaves the tank mix, nozzle size, early-start RPM and hot-air
temperatures alone.

Pulsing a pump is a coarse way to meter fluid: the charge is wet for part of each
cycle and dry for the rest. It is fine for testing and for cooling, but do not add
ignition timing that depends on it.

## Cooling before boost and in hot air

Boost is not the only reason to inject when the goal is cooling and knock prevention.

- **Early start at high RPM.** Above the RPM you set (3500 by default) injection starts
  **before boost builds**, as long as the throttle is open: manifold pressure within
  about 1.5 psi of atmospheric. Coasting at high RPM with the throttle shut is deep
  vacuum and never triggers it. It runs the start-boost run time until boost takes
  over. The intake is already cool and wet when boost arrives. Set it to 0 to wait
  for boost.
- **More when the intake is hot.** With *Hot air adds run time from* set, air before
  the nozzle hotter than that makes the pump run longer, reaching the full run time
  at the second temperature. Whichever asks for more, boost or temperature, wins. It
  only adds to injection that is already running; heat-soaked air at idle or cruise
  sprays nothing. It needs the before-nozzle sensor and is off until you set it.

Without load there is little knock to prevent, and the dose limit keeps the early
amount small: at 3500 RPM with no boost, 10% of fuel is about 26 ml/min.

The live card says when either is acting: *Injecting: early start, before boost* or
*extra for hot intake air*.

## Settings

| Setting | Range | Default | What it does |
|---|---|---|---|
| Cycle length | 1–10 s | 4 s | One pump run per cycle. |
| Pump runs at start boost | 0.5–10 s | 1 s | Run time per cycle when injection begins. |
| Pump runs at full boost | 0.5–10 s | 2 s | Longest run. Equal to the cycle length means on continuously. |
| Start boost | 0.5–30 psi | 0.5 psi | Injection begins here. |
| Full boost | 2–35 psi | 10 psi | Run time rises in a straight line from start to here. |
| Minimum engine RPM | 0–8000 | 2500 | No injection below this. |
| Start above this RPM before boost | 0–8000 | 3500 | Early start with the throttle open. 0 turns it off. |
| Longest continuous spray | 1–120 s | 12 s | Then the controller rests. |
| Rest after that | 0–60 s | 6 s | 0 turns the time limit off. |
| Run-time growth per cycle | 0–5 s | 0.5 s | Each new spray starts at the minimum run time and grows by this much per cycle. 0 jumps straight to the target. |
| Most fluid, as % of fuel | 0–40% | 10% | The dose limit. 0 turns it off. |
| Nozzle size | 20–1000 ml/min | 160 | Measured on the pump test (the label says 60). Used by the dose limit and the flow readout. |
| Hot air adds run time from | off, or a temperature | off | Air before the nozzle hotter than this lengthens the pump run. |
| Hot air: full run time at | 68–302 °F | 158 °F | Where the hot-air addition reaches the full-boost run time. |
| Only spray above intake temp | off, or a temperature | off | Uses the sensor before the nozzle. If set and that sensor is not reading, injection is held. |
| Overboost assist | off / on | off | On restores the older behaviour: 85% above 13.5 psi and 100% above 15 psi. The dose limit still applies. |

The line under the settings spells out the result, for example: *At 5 psi the pump
runs 1 s in every 4 s (15 ml/min), rising to 2 s in every 4 s (30 ml/min) at 10 psi.*

## Starting out

1. Flash the ESP32, open **Meth tuning** and check it says *Matches preset: Conservative*
   with *Water only* in the tank.
2. Engine off, disarmed, nozzle pointed into a container: set the test duty to 25%
   and **Run 3-second test**. The pump should run for about a second and the nozzle
   should mist, not dribble. Measure what comes out over a few tests if you want to
   check the nozzle size setting.
3. Arm it and drive. The live card says why it is or is not injecting: waiting for
   boost, RPM below the minimum, resting, dose limit.
4. Change one thing at a time and compare logs.

## Intake temperature

### On the car: one sensor before the nozzle, the MicroSquirt's after it

Since November 2026 there are two intake air temperatures, one each side of the nozzle:

| | Sensor | On the live card |
|---|---|---|
| Air before the nozzle | The ESP32 board's own intake sensor (GPIO5 or GPIO6) | *Air before the nozzle* |
| Air after the nozzle | The MicroSquirt's MAT, after the throttle | *Air after the nozzle … (MicroSquirt IAT)* |

The firmware reads both GPIO5 and GPIO6 with pull-ups and rejects disconnected or
shorted inputs. With one valid sensor, either input is used as **before the nozzle**;
the serial heartbeat identifies it, for example `pre=22.4@6`. With two valid sensors,
GPIO5 is before the nozzle and GPIO6 after it. Wire each thermistor from its input
to ground, with a 2.49 kΩ pull-up to **3.3 V**, never 5 V.

- *Hot air adds run time* and *Only spray above intake temp* use the sensor before the
  nozzle: the air on its way in, before any spray. That removes the loop described
  below.
- **Cooling** is worked out from the two around each spray: how much further the air
  after the nozzle falls below the air before it than it was just before the spray.
  Boost heats both at the same time, so that cancels out, and so does the steady
  difference between two sensors in two places (the MAT sits in a warm manifold). On the
  live card while spraying: *14 °F cooler since injection began (against the air before
  the nozzle)*; afterwards *Last spray: 14 °F cooler after the nozzle, measured against
  the air before it, in 6 s at 30 ml/min*. In the logs, *Intake before inj* is the
  board's sensor, *Intake after inj* the MAT, and *MAT change while injecting* the
  cooling.
- *Injection temp drop* (before minus after, at any moment) includes that steady
  difference: with no spray the MAT usually reads a few degrees warmer, so it shows
  below zero. The cooling above is the number to compare.

If the board's sensor is not reading (unplugged, or a broken wire), the controller falls
back on the MicroSquirt's temperature as below, and the tuning page says so.

### Without the board's sensor: the MicroSquirt's sensor alone

Until the controller has its own sensor, the dash forwards the MicroSquirt's intake
air temperature to the controller about four times a second, and everything that
needs a temperature uses it: *Hot air adds run time* and *Only spray above intake
temp*. The tuning page says so when it is the source.

That sensor sits after the throttle, so it is **after the nozzle** and reads the
air once it has been sprayed. Two things follow:

- *Hot air adds run time* works as a loop: hot air lengthens the pump run, the air
  cools, the run shortens again. That is fine for cooling, but expect it to settle
  around the temperature you set, not far below it.
- A sensor in wet air can read lower than the air really is.

**Before and after from that one sensor.** The dash keeps the last reading before
each spray starts, follows the change while it sprays, and keeps the finished result:
*Last spray: 131 °F to 112 °F, 19 °F cooler in 6 s at 30 ml/min*. It is on the live
card and in the logs (*MAT change while injecting*). Boost heats the air during the
same seconds, so this understates the cooling; compare a pull with injection armed
against the same pull disarmed to see the real difference.

All three readings (before, after, cooling) can be put on the dashboard with **Edit
gauges**, and they are in every data log next to boost, RPM, pump run time, cycle
length, flow in ml/min, share of fuel and the hold reason, so MegaLogViewer can plot
cooling against flow.

## Full-pressure pulses and continuous spray

Wiring and first start-up: `docs/ESP32_HARDWARE.md` in DIYWaterMethInjection.

The current firmware uses cycle length and the two pump run times. Equal run time
and cycle length requests continuous operation; the dose limit, spray/rest limit,
RPM, tank and fault rules still apply. The dose limit can shorten the run or hold
it off, even when continuous operation is requested. Settings 18 and 19 (PWM duty)
remain in the wire contract but are ignored by this drive.

The earlier ESP32 firmware reports drive 1 and still shows the two PWM duty settings.
Its flow estimate follows the square root of duty. The new firmware reports drive 2
and estimates average flow from the share of each cycle the pump runs. The preview
defaults to pulse drive; `?meth=pwm` demonstrates the earlier firmware.

Each pump run starts with a 0.4 s ramp from 5% to full duty. After a reset while the
pump was running, the ramp can grow to 1.6 s. Once stopped, the pump rests at least
0.5 s. The pump test follows the same soft-start rules.

**No data from the MicroSquirt means no injection.** The board has no MAP sensor.
Without fresh manifold pressure, the dash shows "WATER/METH OFF: NO MANIFOLD PRESSURE".

Firmware updates arrive over CAN: Update now downloads `watermeth-latest`, then
Dash management → Software & power installs it with the engine off. Only the first
flash needs USB. Saved settings survive an update ([firmware-updates.md](firmware-updates.md)).

### When something goes wrong, it comes back by itself

The ESP32 recovers from communication failures and resets in three ways:

- **CAN goes silent.** With the ignition on the bus is never quiet: the MicroSquirt
  broadcasts many times a second. Nothing at all for 1.5 s and the board sets its CAN
  controller up again, every 2 s while it lasts; still nothing after 15 s and the whole
  board restarts (three times at most per drive). Injection is off meanwhile anyway: the
  manifold pressure comes over CAN.
- **Any reset nobody asked for** (a crash, a watchdog, a supply dip, a restart over a
  fault) comes back **armed**, and sprays again as soon as the MicroSquirt's data is
  fresh: under a second, without waiting for the dash. Power on, a firmware update and
  the dash's Restart still start disarmed, and the dash arms it again if you had it armed.
- **A board that keeps crashing rests, then tries again.** One crash is a restart (the
  pump is switched off first) and nothing more. Three in one drive and it holds
  injection off for 30 s, then tries again; three more and it rests 60 s, then 2, 4, at
  most 5 minutes. The dash says *Injection disabled: the controller crashed and restarted
  three times since the ignition came on, so it rests*; **Clear faults** on the Water /
  meth tab lets it inject at once and starts the next rest short again.

Each start is reported to the dash (contract extension 8), and the dash's event log, which
goes up with each drive report, says why and what the board did: for example *water/meth
controller started (brownout (supply dip)): the pump was running, armed again by itself,
gentler pump start after resets*. A power-on start is logged as information; anything
else as a warning, since it is the board recovering from something.

**A black box of the last ten seconds.** The board keeps what it was doing, ten times a
second, in memory a reset does not clear: pump duty (at the end of each tenth of a second
and its highest), manifold pressure and RPM from the MicroSquirt, why it was holding, armed
and soft-start, the pump starting and stopping, how long since anything was heard on CAN,
the CAN controller set up again or frames not getting out, the longest gap between control
passes, the pump keeper stepping in, the air before the nozzle and the free memory. No
extra wiring. After a reset nobody asked for, it sends the record left behind to the dash
(contract extension 9) and again every 5 s until the dash answers. The dash writes it to
the event log with every sample, so it goes up with the next report, and in words: for
example *water/meth black box (brownout (supply dip)), the 10.0 s before it: pump on at
30%, started 0.4 s before the end (still in its soft start); 132 kPa, 3392 rpm; CAN heard
to the end; longest control gap 21 ms*. The Water / meth tab shows the latest under *Last
controller restart*. After power on, a firmware update or the dash's Restart there is
nothing to send.

What software cannot do: if the CAN module itself latches up (a transient can leave a
CAN chip stuck until its power is removed), no reset of the ESP32 brings it back, because
the module keeps its power. Powering the CAN module through a small switch that a spare
ESP32 pin controls would let the board power-cycle it as a last step; say if you want
that, and which pin.

## CAN messages (contract extensions 4–10)

Additive: no existing message changed.

| ID | From | Content |
|---|---|---|
| `0x301` cmd `0x10` | Dash | Set one setting: key, value (u16) |
| `0x301` cmd `0x11` | Dash | Save, revert, defaults, or report all settings |
| `0x301` cmd `0x12` | Dash | The MicroSquirt's intake temperature, about four times a second, not acknowledged |
| `0x30F` | Controller | Acknowledgements, settings, status every 0.5 s (why it is holding, run time, cycle), temperatures every 0.2 s |
| `0x302` code `0x0A` | ESP32 board | Once after each start: why it started (the chip's reset reason) and what it did (extension 8) |
| `0x310` | ESP32 board | After a reset nobody asked for: its black box, the last 10 s, a header and the samples seven bytes a frame (extension 9) |
| `0x301` cmd `0x13` | Dash | The black box arrived: stop sending it (extension 9) |

Extension 5 adds settings 18 and 19 (lowest and highest pump duty) and a drive-type
byte in each setting report. The earlier ESP32 PWM drive is 1, reporting duty as
run time out of 1000. **Extension 10 adds drive 2 (`meth_drive::PULSE`)**, reporting
actual run time and cycle length in milliseconds. Value 0 is reserved for the retired
drive; existing wire values remain unchanged.

Extension 8 (November 2026) adds the start report above: byte 2 is the reset reason as
ESP-IDF numbers it (1 power on, 3 software restart, 4 crash, 5-7 watchdogs, 9 brownout),
byte 3 flags: 1 the pump was running, 2 armed again by itself, 4 holding injection after
crashes, 8 new firmware on trial, 16 restarted itself over a silent CAN bus, 32 over a
quiet ADC, 64 pump soft start lengthened. In the state message (`0x300`), fault bit 6
(64) means the ESP32 board is resting after three crashes since the ignition came on.
The bit was previously unused.

Extension 9 adds the black box: a header `FF vv nn ww rr ff sH sL` (layout version, samples,
window in 10 ms, reset reason, data frames, 16-bit sum of the bytes) and data frames
`ii` + seven bytes, oldest sample first, ten bytes a sample as `black_box.h` in
DIYWaterMethInjection lays them out. The dash checks the sum, writes each record once, and
answers `0x301 0x13`; the board tries six times, five seconds apart.
