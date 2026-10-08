# Water/meth: flow, failsafes, presets and intake temperatures

Written for this car: 2.3 L Lima turbo at up to 10 psi, a 0.9 MPa (130 psi) 4–6 L/min
pump switched directly by a mechanical relay, a 60 ml/min (1 GPH) nozzle and a 2 L tank.

Everything here needs the current firmware on the water/meth Nano
(DIYWaterMethInjection, CAN contract extension 4). With older firmware the tuning page
says so and the rest of the dash works as before.

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

## Intake temperature sensors

Two thermistors on the Nano show the air temperature before and after the nozzle, so
you can see how much each setting actually cools the charge.

- **Sensor:** GM-style open-element intake air temperature sensor (2-wire thermistor,
  about 3.5 kΩ at 68 °F). Open-element types react in well under a second.
- **Wiring, each sensor:** Nano 5 V → 2.49 kΩ resistor → analog pin → sensor → GND.
  The sensor has no polarity.
  - Before the nozzle: **A1**
  - After the nozzle: **A2**
- An unplugged or shorted sensor reads *No sensor reading*; nothing else is affected
  unless you have set the intake temperature limit.

All three readings (before, after, cooling) can be put on the dashboard with **Edit
gauges**, and they are in every data log next to boost, RPM, pump run time, cycle
length, flow in ml/min, share of fuel and the hold reason, so MegaLogViewer can plot
cooling against flow.

## CAN messages (contract extension 4)

Additive: no existing message changed.

| ID | From | Content |
|---|---|---|
| `0x301` cmd `0x10` | Dash | Set one setting: key, value (u16) |
| `0x301` cmd `0x11` | Dash | Save, revert, defaults, or report all settings |
| `0x30F` | Controller | Acknowledgements, settings, status every 0.5 s (why it is holding, run time, cycle), temperatures every 0.2 s |
