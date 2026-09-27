# Trip counters, fuel economy and range

Open **Drive → Trips & economy** for independent Trip A/B, engine runtime,
moving average speed, sampled average US MPG, instant US MPG, estimated fuel
flow and range. Reset A or B with two taps within five seconds. Total tracked
distance cannot be reset from this screen and is not the vehicle's odometer.
Trip A/B, range, instant MPG and average MPG are available as lower instruments
under **Drive → Display modes**. The preview shows explicitly simulated values;
its trip data resets on page reload and never contacts the Pi.

Choose US or metric display units under **Drive > Dash management**. Calibration
fields and recorded channels retain their explicitly labelled engineering units.

## Your configuration

The production defaults contain the supplied **15.4 US gallon tank (58.295 L)**
and **four 440 cc/min injectors**, with fuel estimation **disabled**. The supplied
TunerStudio screen confirms **2 squirts per cycle, alternating, four-stroke,
untimed injection**, so the pulse-rate default is **0.5 per injector per crank
revolution** (one pulse per 720 degrees). Older disabled configurations with a
zero/unconfigured pulse rate adopt this value; other saved pulse rates are kept.
The screen's **8.8 ms Required Fuel is not injector dead time**. In
**Drive → Fuel setup**, verify these values and enter:

- Pulses per injector per crank revolution. For a four-stroke engine, use
  TunerStudio's squirts per engine cycle / 2 for simultaneous injection or / 4
  for alternating injection. Your confirmed setting is 2 / 4 = 0.5.
- Number of injectors represented by PW2; the remainder uses PW1. Zero uses
  PW1 for every injector. Check the actual wiring and tune before enabling.
- Effective injector dead time in milliseconds, appropriate to the operating
  voltage. Zero is an uncalibrated placeholder, not a measured dead time.
- Rated flow at your actual differential fuel pressure, a correction multiplier
  (initially 1), and the range reserve (initially 3 L / approximately 0.79 gal).

Then check **Calibration verified** and save. These settings only affect dash
estimates; they do not write to the ECU or alter injection. Changing calibration
clears the learned range average and manual fuel inventory; trip counters remain.

For each configured injector bank, the estimate is:

```
effective duty = max(0, pulse_width_ms - dead_time_ms) * RPM * pulses_per_rev / 60000
litres/hour = sum(bank_injector_count * effective_duty) * injector_cc_min * 0.06 * correction
```

RPM and pulse widths come from the existing decoded ECU CAN signals. Each
required bank must be fresh; an electrical duty above 100% is rejected. A live
zero RPM gives zero flow. Idling still consumes estimated fuel; instant MPG is
unavailable while stopped and fuel flow remains visible. Moving with zero
estimated flow shows **COAST**, not infinite MPG.

The [MegaSquirt setup manual](https://www.msextra.com/doc/pdf/Megasquirt2_Setting_Up-3.4.pdf)
describes squirts, staging and injector dead-time settings. This implementation
is an estimate with a fixed effective dead time: it does not model voltage
correction curves, short-pulse nonlinearity, changing fuel pressure or staged
injectors with different flow ratings. Compare estimated use against measured
fill-to-fill consumption before relying on it. Multiply the correction by
actual fuel used / estimated fuel used for comparable, completely recorded trips.

## Fuel amount and range

Until CAN fuel level is available, use **Set amount** to enter
the total fuel currently in the tank, or **Tank is full** after filling it.
This is an absolute amount, not fuel added. The service subtracts estimated use.
It never presents this inventory as a measured fuel-level percentage.

After a service restart, a sampling gap above one second, or missing required
fuel telemetry while the engine could be running, the manual inventory must be
reconfirmed. The last tracked amount is shown as a reference, but range stays
unavailable. The [external fuel controller](fuel-can.md) supplies `vehicle.fuel_pct` over CAN
and takes priority when fresh. Calibration and filtering live on the controller.

Range = max(0, remaining litres − reserve litres) / learned litres per km.
Learning requires at least 1 km (0.62 mi) and 0.02 L of paired fresh speed/fuel
data. The learned average persists across restarts and excludes intervals
without both signals. It includes idle fuel when fresh GPS reports zero speed.
Trip MPG uses the same paired-data rule; **partial data** identifies gaps.
Future driving conditions can change the actual distance achievable.

## Recording and persistence

The Pi samples independently of browser clients at approximately 10 Hz,
integrating adjacent fresh speed and flow values with the trapezoid rule.
Speeds below 1 km/h count as stationary; invalid or above-360-km/h readings are
ignored. A service sampling gap above one second is never bridged. Between
sensor reports, values can be held only within their existing freshness timeout
(USB GPS speed: two seconds). No distance is inferred through GPS loss or while
the service is stopped. Engine time requires fresh RPM of at least 300.

Counters/settings save atomically to `/var/lib/frogdash/trip.json` every 15
seconds, on settings/reset/fuel actions, and on orderly service exit. An abrupt
power loss can lose up to the last checkpoint interval. Existing power and
shutdown services, GPIO23 and GPIO24 are untouched. Replay uses a separate
`replay/trip.json`. Storage failures remain visible in the Trips screen.

Local same-origin `GET /trip` returns state. `POST /trip` accepts exactly one of
`{"settings": {...}}`, `{"reset": "a"}` (or `b`) and `{"remaining_l": 20}`.
The Wi-Fi download portal does not expose these write operations.

New MLG files use schema 4 and include `trip.a_km`, `trip.b_km`, `trip.total_km`,
`fuel.flow_lph`, `fuel.remaining_l`, `fuel.range_km`, `fuel.instant_mpg` and
`fuel.average_mpg`, with quality fields. Fuel channels are estimates even when
quality is live; unavailable estimates record NaN.

## Validation

`tests/test_trip.py` covers analytic two-bank fuel/distance integration, range,
idling, coasting, stale readings, gaps, independent resets, validation, local
API boundaries and persisted restart recovery. `tests/browser_trip.py` covers
real HTTP calibration and fuel entry, counting with menus closed, resets,
reload and offline/demo behavior. All 15 submenu views are checked at seven
viewport sizes by `tests/browser_layout.py`. Physical vehicle calibration and
Pi hardware checks are still required.
