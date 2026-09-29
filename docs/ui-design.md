# Driver display design

The production design lives in `hardware/ui/`. The standalone preview copies that design and substitutes `preview/demo.js` for the network transport. The Python service serves only production assets.

## Visual hierarchy

Speed and RPM receive the largest type. Boost and AFR occupy the right column. Six matched sensor cards group the remaining routine readings. The bottom row holds water/meth status, module health, and navigation. Dark solid surfaces, warm white text, restrained mint accents, and consistent spacing replace the original decorative background.

Wide panels (aspect ratio above 2.2:1) scale proportionally from 1920 × 720, including 1980 × 720 panels. Their submenus retain the 1864 × 680 layout and receive the same scale explicitly because native dialogs render in the browser's top layer.

Standard 16:9 monitors, 4:3 screens and portrait displays automatically use a responsive layout. Instruments and sensor cards reflow into fewer columns as space narrows, navigation wraps, and the page scrolls vertically when necessary. Menus use the available viewport, with fixed headers/close buttons and scrollable contents. Below 900 CSS pixels, menu tabs wrap across the top. Resizing or rotating an open menu updates its layout immediately; the visual viewport also tracks the on-screen keyboard. No screen-resolution setting or reset of appearance preferences is needed. Layout initialization is independent of the live-data connection.

Buttons have visible keyboard focus, and native dialogs trap focus and support Escape. Control tabs use Up/Down, Home, and End. Leaving the water/meth tab stops a locally requested pump test, as does closing the dialog.

Fonts are local: DejaVu Sans on Linux, with Segoe UI and Arial fallbacks. No font download is required. Reduced-motion preferences disable gauge transitions.

Appearance has a six-look gallery and eight mixable CSS backgrounds, with
thumbnail previews and a visible selection marker. Presets coordinate accent,
panel and border colors while keeping warning/fault colors and opaque instrument
surfaces. The gallery and custom/splash controls occupy separate full-width tabs
within the same dialog; Left/Right, Home and End navigate those tabs. Existing
appearance preferences load without losing saved images or splash settings.

## Instrument semantics

| Instrument | Display behavior |
| --- | --- |
| Speed | GPS speed converted to MPH; no live fix shows a dash. |
| RPM | 0–7,000 arc; the existing 6,000 RPM red zone is a display reference, not an ECU limit or engine calibration. |
| Manifold pressure | Gauge pressure, −15 to +30 psi. Vacuum extends left from zero in blue; boost extends right in mint. |
| AFR | 10–18 scale, with measured AFR and a separate ECU target marker. Target unavailable is stated explicitly. Lambda is gasoline-equivalent AFR / 14.7. |
| Coolant | 100–250 °F scale; the existing 112 °C warning threshold highlights the card and warning banner. |
| Oil / fuel pressure | 0–100 psi scales. |
| Intake air | 0–200 °F scale. |
| Battery | 10–16 V scale. |
| Fuel | 0–100%; external CAN percentage; unavailable until a valid report arrives. |

Bars clamp to their drawn scales; live numeric readings retain their measured values. Scales are visual references, not new control thresholds. The UI never assumes that an AFR of 14.7 is the requested ECU target. Pressure, voltage, and fuel cards do not invent fault thresholds.

Stale or unavailable readings show dashes and a quality label. Sensor faults, excessive coolant temperature, knock alerts, and water/meth faults appear in the warning banner. The lighting indicators follow received module states. The unused high-beam source remains unavailable.

Control inputs express requested settings; module telemetry and command feedback remain separate. The lighting controller cannot acknowledge mode changes. The design does not change backend command validation or controller ownership requirements; see [controls](controls.md).

## Reviewing the preview

Open `preview/index.html`. Its badge and control feedback identify simulated data; it never opens a WebSocket or accesses CAN/GPS. It starts a repeating 34-second driving cycle with gear changes, boost/vacuum, AFR targets, pressure changes and brake/turn inputs. Temperatures and voltage vary gently; fuel is a simulated amount that decreases slowly. Armed demo water/meth responds to boost. Header **Pause / Play** freezes/resumes the simulation; **Park / Drive** selects idle or returns to the drive. Preview configuration remains editable during motion; appearance, transparency, layouts, fuel settings, alerts, management and simulated calibration commands do not require parking the demo. Physical LCD backlight controls explicitly identify their Pi hardware requirement. Controller-state requirements such as disarming before a pump test still show their reason. These controls exist only in the preview.

In the browser console, use `frogdashDemo.scenario('warning')`, `'vacuum'`, `'offline'`, `'night'`, `'parked'`, or `'normal'` for repeatable design checks. `normal` retains the old fixed readings and unavailable fuel fixture; `drive` resumes animation. These are illustrative values, not a vehicle physics model.

Run `python tests/browser_demo.py` to check default animation, pause/resume, editing and header fit. `tests/browser_interactions.py` exercises a fresh moving preview with mouse clicks, slider drags, touch taps, native slider keys and menu toggles at five screen sizes, including 16:9 and portrait, then verifies the production parked gates.

Run `python tests/browser_smoke.py` for saved screenshots and interaction checks. Review readability on the physical panel, including sunlight and night conditions, before vehicle use; browser screenshots alone cannot establish panel brightness or viewing-angle performance.

Run `python tests/browser_layout.py` to check all twenty submenu views at fourteen sizes, from 320 × 568 through 2560 × 1440, including native 1920/1980 × 720 panels. It verifies dashboard navigation, viewport bounds, reachable controls after scrolling, and resizing an open submenu across layout modes. Pass `--url` to run the same checks against the hosted preview.
