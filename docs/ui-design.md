# Driver display design

The production design lives in `hardware/ui/`. The standalone preview copies that design and substitutes `preview/demo.js` for the network transport. The Python service serves only production assets.

## Visual hierarchy

Speed and RPM receive the largest type. Boost and AFR occupy the right column. Six matched sensor cards group the remaining routine readings. The bottom row holds water/meth status, module health, and navigation. Dark solid surfaces, warm white text, restrained mint accents, and consistent spacing replace the original decorative background.

The cluster scales proportionally from 1920 × 720 to fit the display, including 1980 × 720 panels. Every submenu uses a 1864 × 680 layout centered inside that same scaled area. Native dialogs receive the same scale explicitly because the browser renders them in its top layer. Resizing a preview preserves the wide panel layout, including open menus. Controls and the knock graph fit without scrolling; the long diagnostics list scrolls beneath its fixed header and search controls. Buttons have visible keyboard focus, and native dialogs trap focus and support Escape. Control tabs use Up/Down, Home, and End. Leaving the water/meth tab stops a locally requested pump test, as does closing the dialog.

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

Open `preview/index.html`. Its badge and control feedback identify simulated data; it never opens a WebSocket or accesses CAN/GPS. In the browser console, use `frogdashDemo.scenario('warning')`, `'vacuum'`, `'offline'`, or `'normal'` to review those states. Fuel stays unavailable.

Run `python tests/browser_smoke.py` for saved screenshots and interaction checks. Review readability on the physical panel, including sunlight and night conditions, before vehicle use; browser screenshots alone cannot establish panel brightness or viewing-angle performance.

Run `python tests/browser_layout.py` to check all fifteen submenu views at native 1920/1980 × 720 and scaled sizes. It verifies that menus stay inside the dashboard, controls remain unobscured, and resizing an open submenu preserves the layout. Pass `--url` to run the same checks against the hosted preview.
