# frogdash

Custom car dash UI on Linux. Tach/speed/fuel/temp/OBD2/CAN-bus, headless Linux driving a small TFT or HDMI panel mounted in-dash.

A 1920×720 automotive dashboard UI for a 12.3" LCD, themed for a Foxbody Mustang.

> **Phase 1 status:** browser preview only. No hardware integration yet.
> Pi/CAN/GPIO/GPS implementation is planned but **not started** — this repo currently
> contains the design preview for review.

## Repo layout

```
frogdash/
├── preview/         Browser-only design preview (HTML/CSS/JS, simulated data)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── config/          Future hardware/calibration config (placeholder, Phase 2)
├── hardware/        Future Pi-side implementation (placeholder, Phase 2)
├── docs/            Design notes, decisions, datasheets (placeholder, Phase 2)
└── .github/
    └── workflows/
        └── pages.yml   GitHub Pages: publish preview/
```

## Browser preview (design review)

A self-contained 1920×720 simulated dashboard. No hardware calls. Open it locally:

```bash
xdg-open preview/index.html
# or just double-click preview/index.html
```

Or visit the GitHub Pages URL once Pages is enabled (see below).

### What's in the preview

- Tachometer (RPM, 800–6000)
- Huge center speed (MPH, GPS-sourced)
- Boost / MAP gauge
- AFR ring gauge (rich/stoich/lean, λ readout)
- Coolant, IAT, fuel, oil pressure, oil temp, battery, EGO
- Topbar: turn signals (L/R), high beam, check-engine, parking brake, brake warning, fuel %, ext temp, clock
- Warning banner (e.g. coolant critical)
- Menu overlay (M key, or sim control)
- Knock Monitor — large bottom-right button, touch-friendly modal with live graph

### Sim controls (toggle button, bottom-left)

For design review only. **Not part of the production dashboard.** Hidden by
default since v0.2.8; tap the small `SHOW SIM CONTROLS` button at the bottom-left
to expand it.

- Checkboxes: turn signals, high beam, ECU, brake warning
- Sliders: fuel pressure, fuel resistance, knock energy/baseline/threshold, meth duty/tank
- Buttons: trigger coolant warning, clear warnings, +1 knock event, open knock monitor
- Keyboard: `M` menu, `←/→` cycle gear, `T` toggle left turn, `Esc` close overlays

## Design review checklist

When reviewing the preview, please comment on:

1. **Layout / proportions** — does 1920×720 feel right for a 12.3" display? Anything too cramped / too sparse?
2. **Information density** — too much, too little, right amount?
3. **Color/contrast** — readable in bright daylight? At night?
4. **Warning states** — does the coolant warning grab attention without being obnoxious?
5. **Menus** — layout of the menu overlay
6. **Foxbody theming** — accent color, typography, any other "feel" tweaks?

## Roadmap

- [x] **Phase 1a** — static HTML prototype (`frogdash-prototype-v1.html`, pre-repo)
- [x] **Phase 1b** — animated sim in `preview/`, GitHub Pages published (← **you are here**)
- [ ] **Phase 1c** — design review + iterations
- [ ] **Phase 2** — QML/Pi implementation, CAN bus, GPIO, GPS
- [ ] **Phase 3** — vehicle integration

## Notes for future me

- Repo is on `main`, SSH alias `github-frogdash`, deploy key `~/.ssh/frogdash_deploy`
- Browser preview is **design review only** — Pi implementation is authoritative
- `preview/` is intentionally a separate, self-contained folder; do not import from it into the production app
