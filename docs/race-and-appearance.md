# Race mode and appearance

Open **Race** or **Appearance** from the dashboard footer. Both use the same
1920 × 720 design space as the instruments and fit the 1980 × 720 panel size too.
The published preview includes simulated race sessions and working appearance
settings, without contacting the Pi or sending CAN commands.

## GPS performance timing

This is inspired by the comfort controller's
[race manager at the reviewed revision](https://github.com/averyizatt/DIYComfortControlModule/blob/69c73f86a61e9892836a1006f8a676e7e1e750a3/src/race/race_manager.cpp).
Frogdash computes its own times on the Pi from the USB receiver through gpsd.
No additional CAN message IDs or controller firmware changes are needed.

- **Acceleration:** stop, select **Arm acceleration**, and hold stationary until
  the screen says **Ready for launch**. Measures 0–30 MPH, 0–60 MPH, 0–100 km/h,
  eighth mile and quarter mile, with GPS speed at each distance crossing.
- **Automatic laps:** save **Set start / finish here** at your track's timing
  point, then select **Start laps**. Leave the area and cross back into it to
  begin timing. Subsequent crossings record last lap, best lap and delta to best.
- **Manual laps:** with no saved gate, **Start laps** starts immediately;
  **Mark lap** records a lap using the latest GPS epoch. Mark lap also works in
  an active automatic session. Minimum lap duration is 15 seconds.
  **Clear gate** removes a saved start/finish while stopped to use manual timing.
- **Stop** ends and saves the session. **Reset** clears the current display after
  stopping; it preserves the start/finish point and saved history.
- **Export results** downloads the saved sessions as JSON. The display shows
  the latest ten; the Pi retains up to fifty sessions, each with its last fifty
  laps. Total lap count and session best include earlier laps.

The service keeps timing with the Race menu or browser closed. A service restart
restores completed history and the gate, but never resumes or arms a run.
History and the gate are saved atomically to `/var/lib/frogdash/race.json` by
default; override with `--race-file /path/to/race.json` when running outside the
supplied systemd service. Its existing `StateDirectory=frogdash` supplies the
writable directory. Disk failures appear on the Race screen. Replay mode cannot
start race timing. CAN GPS speed alone cannot supply the timestamped positions
needed by this implementation; enable `--gpsd` for the local USB receiver.

MLG recordings also contain race phase, elapsed time, distance, speed splits,
distance splits, crossing speeds, lap count and best lap. The usual quality
channels apply; invalid-session measurements become NaN/quality 3. JSON exports
retain diagnostic splits from invalid sessions with an explicit `invalid` phase
and reason. Do not treat these as completed valid runs.

### Timing method and limits

These are **GPS estimates**, not certified track timing. Validate them with the
actual receiver on a closed course. Displaying hundredths does not imply
hundredth-second measurement accuracy.

The timer processes one speed sample per receiver timestamp. gpsd can deliver
multiple TPV messages for one measurement epoch, and fields are optional; those
messages must not be counted as independent fixes. See the
[official gpsd TPV protocol](https://gpsd.io/gpsd_json.html#_tpv).

Acceleration requires speed at or below 0.5 MPH for at least one second after
arming. Timing begins at the last stationary sample when speed first rises
above that threshold. It includes the launch sampling interval and applies no
one-foot rollout correction. Speed thresholds are interpolated between fixes.
Distance integrates speed using the trapezoidal rule; distance crossing time
solves that segment's speed integral. Crossing speed is instantaneous GPS speed,
not a drag strip's averaged trap speed. A run ends at the quarter mile or after
180 seconds. Stops preserve only the splits actually reached.

Missing fixes, backwards timestamps, sample gaps above 1.5 seconds, rates above
50 Hz, or speed jumps above 16 m/s² invalidate an active session and require
rearming. Duplicate or partial speed reports never extend freshness. Intervals
above 250 ms receive a coarse-timing warning. The screen shows the observed GPS
update rate; the dashboard's refresh rate cannot improve the receiver's rate.

The automatic lap gate uses a 20 m radius, rearms only after leaving by 40 m,
and requires at least 2 MPH at reentry and 15 seconds between counted laps.
Crossing time interpolates the radius entry between consecutive positions.
This avoids repeated laps while idling near the marker. It is a circular area,
not a direction-aware timing line: a nearby section of track entering the same
circle can trigger it. Choose the location accordingly. Missing positions or
implausible position jumps invalidate a lap session. No live sector delta or
track map is claimed; delta compares the latest completed lap to session best.

## Appearance and splash screens

- **Appearance → Preset gallery** has four collections with six looks each. Signature includes Frogdash,
  Glacier, Heritage, After hours, Apex and Expedition. Track & touring adds GT Sprint,
  Endurance, Rally Stage, Club Sport, Obsidian and Executive. Retro & future and Cyber
  are detailed below. A look sets structure as well as color: gauge layout, numeral
  typeface, panel shape, panel edges, glow, accent, secondary, numeral and needle colors,
  transparency and background. For example, Heritage uses serif analog dials, Apex uses
  mono type with a red rail, and Expedition uses cut corners. The selected look is
  marked with a tick.
- Twenty-four built-in backgrounds: midnight, graphite, carbon weave, accent glow,
  horizon, blueprint, contours, dusk, pit lane, redline, telemetry, satin, charcoal, phosphor,
  neon grid, afterglow, vector grid, copper, true black, duotone, neon city, circuit, hazard
  and aurora. Accent glow, duotone, circuit and aurora follow your chosen colors. Mix any background with any look;
  the label shows when a look has been customized. These are static local CSS
  patterns, with no downloads, animation or additional image storage.
- **Customize & splash** retains the individual controls and image uploads.
  Applying a preset keeps uploaded artwork and splash settings, and does not
  change your Street/Tuning/Track layout. Select **Custom image** again to reuse
  an uploaded background. Day/night mode still uses the brightness and night
  accent set in the Drive workspace; preset colors return in day mode.
- **Customize & splash > Your display > Widget transparency** adjusts dashboard
  panel backgrounds from 0% (solid) to 100% (clear), with a live surface preview.
  Numbers, labels, gauge strokes and borders keep their opacity. Warning banners,
  danger-card backgrounds and settings dialogs remain solid. Presets apply their
  own starting transparency; changing it marks the look customized. The setting
  persists with your appearance profile and is included in display backups.
- **Gauges & colors > Color studio** edits four color slots: Accent (arcs, labels,
  highlights), Secondary (bar meters, tach gradient, duotone backgrounds), Numerals and
  Needles. Select a slot, then use the 24 full-saturation spectrum swatches, the Hue,
  Saturation and Lightness sliders, or the slot's system color picker. **Secondary from
  accent** sets a matching, analogous, triad or complementary secondary color.
- **Instrument style** sets the numeral typeface (modern sans, mechanical mono, classic
  serif or racing italic), panel shape (soft, sharp, rounded or chamfered), panel edges
  (hairline, accent outline, top rail, neon glow or borderless) and glow intensity. Glow
  is off by default and adds no rendering work while off.
- Optional Frogdash/custom-title splash or uploaded splash image; duration of
  1, 2, 3 or 5 seconds, with **Preview splash** and **Skip** controls.
- PNG, JPEG and WebP uploads up to 10 MB, resized to fit 1920 × 720. Uploaded
  images stay in this browser's storage; they are not uploaded to a server.
- **Restore default style** removes saved images and restores the default
  palette and immediate dashboard startup.

Preferences save automatically in local storage for the current browser/profile
and origin. Use the same Chromium profile and `http://127.0.0.1:8080/` address
on the Pi; clearing site data or using an ephemeral/incognito profile loses
them. Preview preferences are separate from the Pi's. Storage errors are shown
and changes remain usable for that page session. Keep an original copy of your
artwork. Very dark color selections gain lightness to stay readable on the dark panels,
keeping their hue and saturation, so fully saturated reds, blues and violets stay vivid.
Profiles saved before the color studio adopt their look's updated colors once.
Warning/fault colors remain unchanged. Background images are dimmed behind
the adjustable instrument surfaces, and splash images use contain rather than cropping.

**Bundled artwork.** `hardware/art/` ships generated backgrounds (Fox-body stripes,
night highway, carbon and red, blueprint coupe, tach glow), darkened photo backgrounds
of Fox-body Mustangs, and eight splash screens: Made by Avery Izatt, Ford oval,
Mustang, Mustang script, Fox body, Fox body front, 5.0 and Built not bought. The car in
every splash (and in the blueprint background) is Avery Izatt's own artwork
(`tools/art-src/fox-side-avery.png`, `fox-front-avery.png`), alongside the Ford oval
and the 1980s Mustang script badge; captions stay clear of the dash hump
at the bottom centre. They update with `git pull` and appear first in the file picker
as **Bundled art**. Chosen images are also saved on the Pi, so they survive key-off.
To change or add designs, edit `tools/make_art.py`, run it, then `python tools/update_preview.py`.

Photo backgrounds come from Wikimedia Commons under Creative Commons licenses, and the
Ford oval and Mustang script are public-domain images of Ford trademarks; sources and
credits are in `tools/art-src/CREDITS.md`. This project is not affiliated with Ford.
To use other images, copy them to `/var/lib/frogdash/import/` on the Pi. A file there
with the same name as a bundled image replaces it in the picker.

**Startup appearance.** The dashboard sends a small snapshot of the current look
(colors, layout, shape and splash on/off; never uploaded images) to the Pi, which
writes it atomically to `/var/lib/frogdash/appearance-paint.json` and serves it inside
the page. The first paint therefore uses your look, and an enabled splash appears
before the dashboard, even if Chromium's own storage was not flushed before key-off.
Only CSS custom properties and simple layout names are accepted, from the Pi itself.
If the dashboard is still hidden three seconds after the page loads, it is shown
regardless. The first start after updating uses the look saved on the previous run.

The splash is the dashboard application's startup screen, not the Raspberry Pi
firmware or Linux boot logo. It defaults off and starts when the page loads.
Startup splash automatically dismisses for moving GPS telemetry or reported
critical knock/water-meth fault; deliberate splash previews can always be
skipped. The service continues CAN, GPS and recording work beneath it.

## Validation

`tests/test_race.py` covers analytic acceleration and distance crossings, GPS
failure/duplicate handling, stationary launch, lap gate rearming, persistence,
MLG quality values and local API boundaries. `tests/browser_personalize.py`
exercises actual HTTP commands, timing while the menu is closed, exports,
reload, local appearance persistence, image uploads and splash previews.
`tests/browser_layout.py` checks all fifteen submenu views at seven viewport sizes.
Appearance browser checks include every preset/background, persistence,
day/night interaction, keyboard tab navigation and retaining uploaded artwork.
Physical GPS and Raspberry Pi validation are still pending.

Settings remain editable during the animated preview and on the Pi without
stationary telemetry. Local appearance preferences also work offline.
After clicking/touching a range, number or select field, native keyboard editing
works normally; steering-wheel selection still enters its explicit edit mode.


### Retro instruments and colors

**Appearance > Preset gallery > Retro & future** adds Foxbody LX, Foxbody
Afterdark, Turbo Heritage, Midnight Runner, Green Terminal and Vector Interceptor.
The Foxbody designs are original vector interpretations of the factory cluster,
not exact OEM reproductions. All artwork is local SVG/CSS; no fonts or images
are downloaded at runtime.

**Gauges & colors** selects the original layout, a six-gauge Foxbody binnacle
(tachometer left, speedometer right, like the factory cluster), round analog
instruments, a seven-segment digital cluster, or the Neon HUD. Mix these with any
look, typeface, shape and color. Presets choose matching gauges and colors; custom
selections persist in the existing appearance profile and are included in display backups.

**Appearance > Preset gallery > Cyber** has Cyberdeck, Netrunner, Chrome Ronin,
Hologram, Toxic and Blackout. Four use the **Neon HUD** layout: a full-width
skewed-segment tachometer with its redline, a split-color speed readout, and
cut-corner data blocks for coolant, fuel, oil pressure and volts over faint static
scanlines. Hologram uses the original layout with rounded glowing glass, and Toxic
uses segmented digital meters. Nothing flashes or animates; meter segments blend from
the secondary to the accent color.

The four alternative layouts show speed, RPM, coolant, fuel level, oil pressure and
voltage, with a lower strip for boost, AFR, intake temperature and fuel pressure.
The original layout retains the configurable Drive sensor slots. Track mode's
shift lights and lap readouts also appear on the new clusters. Signal warnings,
turn/brake indicators and the control menus remain available. Analog pointers
hide when their data is unavailable/stale/faulted; digital values show a dash.
US/metric speed and pressure scales follow the Units setting. Scales clamp at
their printed limits while the numerical reading continues to show the value.

Retro backgrounds are Charcoal, Phosphor, Neon grid, Afterglow, Vector grid and
Copper; cyber backgrounds are True black, Duotone, Neon city, Circuit, Hazard and Aurora. The gallery and customization panels scroll within the display
when needed, keeping their header and Close button accessible.
