// frogdash — browser preview simulator (DESIGN REVIEW ONLY)
// No hardware, no CAN, no GPIO, no GPS. All values are simulated.
(() => {
  'use strict';

  // ---------- helpers ----------
  const $ = (id) => document.getElementById(id);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const fmt = (v, digits = 0) => Number(v).toFixed(digits);

  // ---------- simulated state ----------
  const state = {
    // time-based driver profile (slow oscillation to feel alive)
    t: 0,
    speed: 47,           // mph
    rpm: 3450,           // rpm
    throttle: 0.0,       // 0..1
    coolant: 235,        // °F
    iat: 92,             // °F
    fuel: 38,            // %
    battery: 14.2,       // V
    boost: 12.4,         // psi
    oilP: 62,            // psi
    oilT: 218,           // °F
    afr: 12.4,
    ego: 3.1,            // %
    ext: 54,             // °F
    sats: 11,
    gear: 'N',
    turnLeft: false,
    turnRight: false,
    highbeam: false,
    ecu: false,
    brake: false,
    coolantWarn: true,
    gearIdx: 0,
  };

  const GEARS = ['N', '1', '2', '3', '4', '5'];

  // ---------- DOM refs ----------
  const els = {
    rpmVal: $('rpm-value'), rpmFill: $('rpm-bar-fill'),
    speed: $('speed-digits'),
    coolVal: $('coolant-val'), coolFill: $('coolant-fill'),
    iatVal: $('iat-val'),     iatFill: $('iat-fill'),
    fuelVal: $('fuel-val'),   fuelFill: $('fuel-fill'),
    battVal: $('batt-val'),   battFill: $('batt-fill'),
    boostVal: $('boost-val'), boostFill: $('boost-fill'),
    oilpVal: $('oilp-val'),
    oiltVal: $('oilt-val'),
    egoVal: $('ego-val'),
    afrVal: $('afr-val'), afrLambda: $('afr-lambda'), afrState: $('afr-state'),
    afrPointer: $('afr-pointer'),
    gearPill: $('gear-pill'), gearSub: $('gear-sub'),
    topbarFuelPct: $('topbar-fuel-pct'), topbarExt: $('topbar-ext'),
    gpsSats: $('gps-sats'),
    clockTime: $('clock-time'),
    warnBanner: $('warn-banner'),
    iconLeft: $('icon-leftturn'), iconRight: $('icon-rightturn'),
    iconHigh: $('icon-highbeam'), iconEcu: $('icon-ecu'),
    iconBrake: $('icon-brake'),
  };

  // ---------- sim profile ----------
  // Slow driving loop: accel -> cruise -> decel -> idle. Realistic-ish, no chaos.
  function tickSim(dt) {
    state.t += dt;
    const t = state.t;

    // Throttle follows a slow sinusoid
    const throtTarget = 0.5 + 0.5 * Math.sin(t * 0.18);
    state.throttle = lerp(state.throttle, throtTarget, 0.04);

    // Speed follows throttle with delay
    const speedTarget = state.gear === 'N' ? 0 : 15 + 70 * state.throttle;
    state.speed = lerp(state.speed, speedTarget, 0.02);

    // RPM = idle (800) + speed-loaded curve + small noise
    const idleRpm = 800;
    const load = state.speed * 32 + state.throttle * 1200;
    const noise = (Math.sin(t * 7.3) + Math.sin(t * 11.1)) * 40;
    state.rpm = clamp(idleRpm + load + noise, 700, 6200);

    // Boost tracks throttle
    const boostTarget = 4 + state.throttle * 14;
    state.boost = lerp(state.boost, boostTarget, 0.08);

    // AFR oscillates around 13.5-14.7 cruise
    const afrTarget = 14.2 + Math.sin(t * 0.6) * 0.6 + (state.throttle - 0.5) * 0.8;
    state.afr = lerp(state.afr, afrTarget, 0.1);

    // EGO correction
    state.ego = lerp(state.ego, (14.7 - state.afr) * 4, 0.1);

    // Coolant warms toward 200-235 range; can spike to trigger warning
    const coolTarget = state.coolantWarn ? 235 : 200 + Math.sin(t * 0.05) * 8;
    state.coolant = lerp(state.coolant, coolTarget, 0.01);

    // IAT tracks ambient + slight rise under load
    state.iat = lerp(state.iat, state.ext + 30 + state.throttle * 15, 0.005);

    // Battery 13.8-14.4V
    state.battery = lerp(state.battery, 14.0 + Math.sin(t * 0.3) * 0.3, 0.05);

    // Oil pressure tracks RPM
    state.oilP = lerp(state.oilP, 25 + (state.rpm / 6000) * 55, 0.05);
    state.oilT = lerp(state.oilT, 195 + (state.throttle) * 35, 0.005);

    // GPS sats 8-13
    state.sats = Math.round(lerp(state.sats, 10 + Math.sin(t * 0.2) * 2, 0.05));

    // External temp
    state.ext = Math.round(54 + Math.sin(t * 0.02) * 3);
  }

  // ---------- render ----------
  function render() {
    // RPM
    els.rpmVal.textContent = Math.round(state.rpm).toLocaleString().replace(/,/g, ' ');
    els.rpmFill.style.width = clamp(state.rpm / 6000 * 100, 0, 100) + '%';

    // Speed
    els.speed.textContent = Math.round(state.speed);

    // Coolant — color shifts at thresholds
    els.coolVal.textContent = Math.round(state.coolant);
    const coolPct = clamp((state.coolant - 140) / (240 - 140) * 100, 0, 100);
    els.coolFill.style.width = coolPct + '%';
    if (state.coolant >= 230) { els.coolVal.style.color = 'var(--crit)'; els.coolFill.className = 'fill crit'; }
    else if (state.coolant >= 210) { els.coolVal.style.color = 'var(--warn)'; els.coolFill.className = 'fill warn'; }
    else { els.coolVal.style.color = 'var(--text-0)'; els.coolFill.className = 'fill warm'; }

    // IAT
    els.iatVal.textContent = Math.round(state.iat);
    els.iatFill.style.width = clamp((state.iat - 60) / 140 * 100, 0, 100) + '%';

    // Fuel
    els.fuelVal.textContent = Math.round(state.fuel);
    els.fuelFill.style.width = state.fuel + '%';
    els.topbarFuelPct.textContent = Math.round(state.fuel);

    // Battery
    els.battVal.textContent = fmt(state.battery, 1);
    els.battFill.style.width = clamp((state.battery - 11.5) / 3 * 100, 0, 100) + '%';

    // Boost
    els.boostVal.textContent = fmt(state.boost, 1);
    els.boostFill.style.width = clamp(state.boost / 20 * 100, 0, 100) + '%';

    // Oil
    els.oilpVal.textContent = Math.round(state.oilP);
    els.oiltVal.textContent = Math.round(state.oilT);

    // EGO
    els.egoVal.textContent = (state.ego >= 0 ? '+' : '') + fmt(state.ego, 1);

    // AFR
    els.afrVal.textContent = fmt(state.afr, 1);
    els.afrLambda.textContent = fmt(state.afr / 14.7, 2);
    if (state.afr < 13.5) els.afrState.textContent = 'rich';
    else if (state.afr > 15.2) els.afrState.textContent = 'lean';
    else els.afrState.textContent = 'stoich';

    // AFR pointer: map 11.0..16.0 across -90°..+90° on a semicircle
    // 14.7 is the top (stoich). Left of 14.7 = rich; right = lean.
    const afrNorm = (state.afr - 14.7) / (16.0 - 11.0) * 2; // -1..+1-ish, 0 at stoich
    const afrAngle = clamp(afrNorm, -1, 1) * 90;
    els.afrPointer.setAttribute('transform', `rotate(${afrAngle.toFixed(1)} 120 120)`);

    // Gear
    els.gearPill.textContent = state.gear;
    els.gearSub.textContent = state.gear === 'N' ? '—' : 'D';

    // Topbar
    els.topbarExt.textContent = state.ext;
    els.gpsSats.textContent = `FIX ${state.sats} SAT`;

    // Clock
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    els.clockTime.textContent = `${hh}:${mm}`;

    // Warning banner
    els.warnBanner.hidden = !state.coolantWarn;
    els.warnBanner.textContent = state.coolantWarn
      ? `Coolant temperature critical — ${Math.round(state.coolant)} °F`
      : '';

    // Icons
    els.iconLeft.classList.toggle('on', state.turnLeft);
    els.iconLeft.classList.toggle('blink', state.turnLeft);
    els.iconRight.classList.toggle('on', state.turnRight);
    els.iconRight.classList.toggle('blink', state.turnRight);
    els.iconHigh.classList.toggle('on', state.highbeam);
    els.iconEcu.classList.toggle('amber', state.ecu);
    els.iconBrake.classList.toggle('warn', state.brake);
  }

  // ---------- main loop ----------
  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.1, (now - last) / 1000); // cap to 100ms
    last = now;
    tickSim(dt);
    render();
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // ---------- sim controls (design review only) ----------
  $('sim-turn-left').addEventListener('change', (e) => state.turnLeft = e.target.checked);
  $('sim-turn-right').addEventListener('change', (e) => state.turnRight = e.target.checked);
  $('sim-highbeam').addEventListener('change', (e) => state.highbeam = e.target.checked);
  $('sim-ecu').addEventListener('change', (e) => state.ecu = e.target.checked);
  $('sim-brake').addEventListener('change', (e) => state.brake = e.target.checked);
  $('sim-warn-coolant').addEventListener('click', () => { state.coolantWarn = true; });
  $('sim-clear-warn').addEventListener('click', () => { state.coolantWarn = false; });

  // Menu
  const menu = $('menu-overlay');
  $('sim-toggle-menu').addEventListener('click', () => { menu.hidden = !menu.hidden; });
  menu.addEventListener('click', (e) => { if (e.target === menu) menu.hidden = true; });

  // Keyboard: M = menu, ←/→ cycle gear, T = toggle left turn
  window.addEventListener('keydown', (e) => {
    if (e.key === 'm' || e.key === 'M') { menu.hidden = !menu.hidden; }
    if (e.key === 'ArrowRight') { state.gearIdx = (state.gearIdx + 1) % GEARS.length; state.gear = GEARS[state.gearIdx]; }
    if (e.key === 'ArrowLeft')  { state.gearIdx = (state.gearIdx - 1 + GEARS.length) % GEARS.length; state.gear = GEARS[state.gearIdx]; }
    if (e.key === 't' || e.key === 'T') { state.turnLeft = !state.turnLeft; $('sim-turn-left').checked = state.turnLeft; }
  });
})();
