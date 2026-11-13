# Water/meth: flow, failsafes, presets and intake temperatures

Written for this car: 2.3 L Lima turbo at up to 10 psi, a 0.9 MPa (130 psi) 4–6 L/min
pump, a 60 ml/min (1 GPH) nozzle and a 2 L tank.

**Since November 2026 the water/meth controller is the ESP32 board**: the pump on a
MOSFET with PWM instead of the Nano's relay, and boost and RPM read straight from the
MicroSquirt. The dash works with either and tells them apart by itself; what changes
with the ESP32 board is in [The ESP32 board](#the-esp32-board-pump-speed-instead-of-pulses)
below. Everything else on this page applies to both, and the parts about the relay
apply only while the Nano is fitted.

Everything here needs current firmware on the controller (DIYWaterMethInjection, CAN
contract extension 4, and 5 for the ESP32 board). With older firmware the tuning page
says so and the rest of the dash works as before. Knock listening is off in both
boards' firmware for now ([knock.md](knock.md)); injection never depended on it.

## How much fluid the engine can use

The numbers are estimates: 85% volumetric efficiency, 50 °C charge air, 12:1 air/fuel
at full load, and about 85 kPa of air pressure at Grand Junction's altitude. The nozzle
is taken at its rated 60 ml/min; at your pump pressure it may flow 10–20% more.

| Boost | RPM | Fuel burned | Nozzle running flat out |
|---|---|---|---|
| 5 psi | 2500 | 262 g/min | 23% of fuel |
| 5 psi | 4000 | 420 g/min | 14% |
| 10 psi | 3000 | 406 g/min | 15% |
| 10 psi | 4000 | 541 g/min | 11% |
| 10 psi | 5500 | 744 g/min | 8% |

Water-only injection is usually run at roughly 10–15% of fuel. So:

- **At full boost and high RPM this nozzle is on the small side.** Even on continuously
  it is 8–11% of fuel. It cannot over-inject there.
- **Too much water is a low-RPM, low-boost problem.** At 5 psi and 2500 RPM the same
  nozzle is 23% of fuel, enough to misfire and bog. This is what the dose limit is for.
- **A running engine cannot hydrolock from this nozzle.** A cylinder needs about 80 ml
  of liquid at once to lock (575 cc per cylinder at 8:1). The nozzle delivers 1 ml per
  second to all four cylinders, about 0.01 ml per intake stroke at 2500 RPM.

Hydrolock comes from fluid collecting while the engine is **not** running: the pump
running with the engine stopped, or fluid draining or siphoning into the intake while
parked. The failsafes below are aimed there.

## Failsafes

### In the controller (always on)

- **No engine RPM, no pump.** The dash sends engine RPM (`0x309`). If that stops, or
  RPM is below your minimum, the pump stays off. A stalled engine cannot be filled.
  This also means **no injection if the dash is off or its CAN link fails**.
- **Extra triggers stay inside the rules.** The early start and the hot-air addition
  below never override disarmed, tank low, a fault, the RPM requirement, the dose
  limit or the spray time limit.
- **Dose limit.** The controller estimates fuel flow from RPM and its own boost sensor
  and holds fluid to a set share of it (10% for water by default). At low airflow the
  pump runs for less of each cycle, or not at all.
- **Spray time limit.** After the longest continuous spray it rests, and short lifts
  do not reset the clock.
- **Tank low, bad boost sensor or controller fault** stop injection.
- **Settings are limited and checked.** Out-of-range values are clamped by the
  controller, one setting never raises another, and corrupt saved settings fall back
  to the conservative defaults.

### For the relay

The relay is mechanical, so the pump is never clicked quickly:

- The pump runs for **at least half a second** or not at all.
- It rests for **at least half a second**, or stays on continuously.
- It starts **at most once per cycle**, and the cycle cannot be shorter than 1 s. The
  presets use 4 s.
- A pulse cut short (for example RPM lost) stays off for the rest of that cycle.

A typical automotive relay is good for something like 100,000 switching cycles. On a
4 s cycle, 30 seconds of boost is 8 cycles. A flyback diode across the pump motor makes
the contacts last longer.

### Hardware the software cannot replace

These matter more than any setting:

- **Check valve at the nozzle** (or a solenoid). Without one the line can drain or
  siphon into the intake with the engine off. Mount the tank lower than the nozzle if
  you can.
- **A boost pressure switch in series with the relay** (a 3–5 psi Hobbs switch). If the
  relay ever welds shut, the pump still cannot run without boost. This is the only
  protection against a stuck relay.
- **Pump power from an ignition-switched fuse**, never straight from the battery.

## Where it is on the dash

- **The water/meth tile on the main dashboard turns solid green and reads PUMP ON**
  while the pump relay is closed. Between pulses it keeps a thin green outline and
  reads *INJECTING · PUMP RESTING*. The controller reports the relay the moment it
  switches.
- **Controls → Water / meth**: arm, disarm, pump test, and a live card: what the
  controller is doing and why, the pump run time, the estimated flow in ml/min and as
  a share of fuel, and the intake temperature before and after the nozzle.
- **Controls → Meth tuning**: the tank mix, flow presets, every setting, and
  Save / Revert / Defaults.

Values on the tuning page are read back from the controller, never assumed. A change
applies at once and is marked unsaved; **Save to controller** stores it in the Nano.

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
| Flow, start → full boost | 15 → 30 ml/min | 23 → 45 ml/min | 30 → 60 ml/min |
| Boost, start → full | 5 → 10 psi | 4.5 → 9 psi | 4 → 8 psi |
| Spray limit / rest | 12 s / 6 s | 20 s / 5 s | 30 s / 4 s |
| Run-time growth per cycle | 0.5 s | 1 s | 2 s |

Conservative at full boost is about 4% of fuel at 5500 RPM: a gentle start for
checking that nothing misfires. Standard holds the pump on at full boost, which is
also the kindest to the relay because it does not switch at all there.

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
| Start boost | 1–30 psi | 5 psi | Injection begins here. |
| Full boost | 2–35 psi | 10 psi | Run time rises in a straight line from start to here. |
| Minimum engine RPM | 0–8000 | 2500 | No injection below this. |
| Start above this RPM before boost | 0–8000 | 3500 | Early start with the throttle open. 0 turns it off. |
| Longest continuous spray | 1–120 s | 12 s | Then the controller rests. |
| Rest after that | 0–60 s | 6 s | 0 turns the time limit off. |
| Run-time growth per cycle | 0–5 s | 0.5 s | Each new spray starts at the minimum run time and grows by this much per cycle. 0 jumps straight to the target. |
| Most fluid, as % of fuel | 0–40% | 10% | The dose limit. 0 turns it off. |
| Nozzle size | 20–1000 ml/min | 60 | Used by the dose limit and the flow readout. |
| Hot air adds run time from | off, or a temperature | off | Air before the nozzle hotter than this lengthens the pump run. |
| Hot air: full run time at | 68–302 °F | 158 °F | Where the hot-air addition reaches the full-boost run time. |
| Only spray above intake temp | off, or a temperature | off | Uses the sensor before the nozzle. If set and that sensor is not reading, injection is held. |
| Overboost assist | off / on | off | On restores the older behaviour: 85% above 13.5 psi and 100% above 15 psi. The dose limit still applies. |

The line under the settings spells out the result, for example: *At 5 psi the pump
runs 1 s in every 4 s (15 ml/min), rising to 2 s in every 4 s (30 ml/min) at 10 psi.*

## Starting out

1. Flash the Nano, open **Meth tuning** and check it says *Matches preset: Conservative*
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
| Air before the nozzle | The ESP32 board's own intake sensor (GPIO5) | *Air before the nozzle* |
| Air after the nozzle | The MicroSquirt's MAT, after the throttle | *Air after the nozzle … (MicroSquirt IAT)* |

The board's second input (GPIO6) is not used and not read
(`POST_INJECTION_TEMP_FITTED` in the firmware's `pins_esp32.h`): with nothing on it, it
would float and could read back a made-up temperature.

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

### The Nano board: two sensors on the controller

Two thermistors on the Nano show the air temperature before and after the nozzle at
the same moment, which measures the cooling directly. Once the one before the nozzle
is fitted, the controller uses it instead of the MicroSquirt's.

- **Sensor:** GM-style open-element intake air temperature sensor (2-wire thermistor,
  about 3.5 kΩ at 68 °F). Open-element types react in well under a second.
- **Wiring, each sensor:** Nano 5 V → 2.49 kΩ resistor → analog pin → sensor → GND.
  The sensor has no polarity.
  - Before the nozzle: **A1**
  - After the nozzle: **A2**
- An unplugged or shorted sensor reads *No sensor reading*; nothing else is affected
  unless you have set the intake temperature limit.
- So does a pin with nothing wired to it yet: before each reading the Nano turns on the
  pin's own pull-up for a moment, and an empty pin then reads full scale. (Without that
  check an empty pin read back a made-up temperature and a cooling figure from it;
  fixed in DIYWaterMethInjection `bc52b07`, which goes on the Nano by USB.)

All three readings (before, after, cooling) can be put on the dashboard with **Edit
gauges**, and they are in every data log next to boost, RPM, pump run time, cycle
length, flow in ml/min, share of fuel and the hold reason, so MegaLogViewer can plot
cooling against flow.

## The ESP32 board: pump speed instead of pulses

Wiring and first start-up: `docs/ESP32_HARDWARE.md` in DIYWaterMethInjection.

With this board fitted the tuning page shows two settings in place of cycle length and
the two run times:

| Setting | Default | Range |
|---|---|---|
| Pump duty at start boost | 25% | 10–100% |
| Pump duty at full boost | 50% | 10–100% |

The pump runs continuously while injecting, at a duty that rises in a straight line
from the first to the second between start boost and full boost.

- **Flow is not proportional to duty.** It goes roughly with the square root: 25% duty
  is about half the nozzle's rating (30 ml/min from the 60 ml/min nozzle), 50% about
  70% (42 ml/min), 100% all of it. The page shows the estimate next to each duty. It is
  an estimate; a pump test into a measuring cup at a known duty is the way to check it.
- **The least it can spray is more than the relay's least.** The relay board's
  Conservative preset starts at 15 ml/min; this board cannot go below about 19 ml/min
  (10% duty), and below roughly 25% the spray may dribble rather than atomise. So at low
  RPM and low boost the dose limit holds the pump off more often than with the relay:
  the status line then says "Held: too little airflow for the dose limit". That is the
  limit working, not a fault.
- The flow presets carry duty as well: Conservative 25–50%, Mild 30–70%, Standard
  35–100%. Tank mixes, the dose limit, minimum RPM, early start, hot air, the longest
  spray and the rest work as described above. "Run-time growth" becomes the time the
  duty may take to climb from lowest to highest.
- **No data from the MicroSquirt means no injection.** The board has no MAP sensor: it
  needs the ECU's manifold pressure and RPM on CAN, less than half a second old. If they
  stop, the dash shows "WATER/METH OFF: NO MANIFOLD PRESSURE".
- The Pump line on the Water / meth tab reads "Pump at 37% duty" instead of run time
  and cycle.
- **Its firmware is updated from the dash**, over CAN: Update now downloads the newest
  published build (`watermeth-latest`), and Dash management → Software & power installs
  it, engine off ([firmware-updates.md](firmware-updates.md)). Only the first flash is by
  USB from VS Code; the dash then shows build `00000000` with the published build ready
  to install over it. Settings saved in the board stay through an update.

The Nano board keeps working exactly as before for as long as it is fitted. Its
firmware and its build are unchanged in the repository, next to the new board's.

To see the new board's tuning page without the hardware, open the preview with
`?meth=pwm` at the end of the address.

### The pump: started gently, never chattered

The pump is an ordinary diaphragm water pump. It takes PWM, but it is a motor, not a
valve, and it does not like being switched about. So the board treats it gently,
whatever the settings say:

- **Soft start.** From rest the duty climbs from 5% to what is asked over 0.4 s, instead
  of jumping straight there. A motor starting draws its largest current, and slamming it
  on dips the 12 V supply: the likely reason the Nano went silent at the start of its
  tenth spray (November 2026). The spray reaches full strength within half a second; a
  low duty is reached sooner. The pump test starts the same way.
- **A rest between runs.** Once it stops it stays off at least 0.5 s: never more than two
  starts a second, however boost wanders around the start point.
- **No chatter at the dose limit.** At low airflow the dose limit can sit right at the
  minimum duty. A run then starts only when the limit allows a little more than the
  minimum (3% of duty), and stops only when it falls under the minimum.
- **Gentler still after trouble.** If the board ever resets while the pump is running
  (a supply dip or a crash), the soft start doubles for the rest of that drive, up to
  1.6 s.

For a stronger spray, raise **Pump duty at start boost** and **at full boost**, or choose
the Mild or Standard preset; a higher minimum also keeps the pump out of the low duties
where it labours. To find the least that sprays well: engine off, disarmed, nozzle into a
container, run the pump test at 20, 25, 30, 40% and watch for a fine cone rather than a
dribble. Set *Pump duty at start boost* at or above the lowest that gives a cone.

### When something goes wrong, it comes back by itself

What happened with the Nano on 6 November 2026 (it went silent on CAN during a spray and
stayed silent until the ignition was cycled) is covered three ways:

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

## CAN messages (contract extension 4, and 5, 8 and 9 for the ESP32 board)

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

Extension 5 adds settings 18 and 19 (lowest and highest pump duty) and one byte in each
setting report saying how the pump is driven (0 relay, 1 PWM). A PWM controller reports
its duty in the status message as run time out of a cycle of 1000. Firmware from
extension 4 reports 17 settings and a zero in that byte, and is read as a relay board.

Extension 8 (November 2026) adds the start report above: byte 2 is the reset reason as
ESP-IDF numbers it (1 power on, 3 software restart, 4 crash, 5-7 watchdogs, 9 brownout),
byte 3 flags: 1 the pump was running, 2 armed again by itself, 4 holding injection after
crashes, 8 new firmware on trial, 16 restarted itself over a silent CAN bus, 32 over a
quiet ADC, 64 pump soft start lengthened. In the state message (`0x300`), fault bit 6
(64) means the ESP32 board is resting after three crashes since the ignition came on.
The bit was unused and the Nano never sets it.

Extension 9 adds the black box: a header `FF vv nn ww rr ff sH sL` (layout version, samples,
window in 10 ms, reset reason, data frames, 16-bit sum of the bytes) and data frames
`ii` + seven bytes, oldest sample first, ten bytes a sample as `black_box.h` in
DIYWaterMethInjection lays them out. The dash checks the sum, writes each record once, and
answers `0x301 0x13`; the board tries six times, five seconds apart.
