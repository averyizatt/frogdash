// frogdash v0.2.10 — browser preview simulator (DESIGN REVIEW ONLY)
// No hardware, no CAN, no GPIO, no GPS. All values are simulated.
(() => {
  'use strict';

  // ---------- helpers ----------
  const $ = (id) => document.getElementById(id);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const fmt = (v, digits = 0) => Number(v).toFixed(digits);

  // ============================================================
  //  Ford Foxbody stock fuel sender curve
  //  Stock sender (typical): 10 Ω empty → 73 Ω full (E-series)
  //  Some years/senders use 12 Ω empty → 150 Ω full; we use the
  //  common 10..73 range. Linear in Ω; the gauge is non-linear
  //  (gauge faces are tapered) but for the sim we model the
  //  *sender* resistance only and let the gauge display the
  //  resulting percentage. Document this in /docs.
  // ============================================================
  const FUEL_R_EMPTY = 10;
  const FUEL_R_FULL  = 73;
  const FUEL_LOW_PCT = 12.5; // 1/8 tank warning

  function fuelPctFromResistance(r) {
    const pct = (r - FUEL_R_EMPTY) / (FUEL_R_FULL - FUEL_R_EMPTY) * 100;
    return clamp(pct, 0, 100);
  }

  // ============================================================
  //  Water/meth model — mirrors the CCM's EngineMethState frame
  //  (CAN ID 0x300, DLC 8) and the EngineMethFault frame (0x302).
  //  See include/can_contract/can_protocol.h in the CCM repo.
  // ============================================================
  const METH_STATES = ['OFF', 'ARMED', 'SPRAYING', 'FAULT', 'TEST'];
  const METH_FLOWS  = ['UNKNOWN', 'OK', 'LOW_FLOW', 'NO_FLOW'];
  // from can_protocol::meth_fault_code
  const METH_FAULT_NAMES = {
    0x01: 'LOW_TANK',
    0x02: 'NO_FLOW',
    0x03: 'LOW_FLOW',
    0x04: 'PUMP_OC',
    0x05: 'SENSOR_FAIL',
    0x06: 'OVER_TEMP',
    0x07: 'CAN_TIMEOUT',
    0x08: 'CONFIG_INVALID',
    0x09: 'SAFETY_SHUTDOWN',
  };
  const METH_TANK_LOW_PCT = 10; // matches canArm() rule in the CCM

  // ---------- simulated state ----------
  const state = {
    t: 0,
    speed: 47,
    rpm: 3450,
    throttle: 0.0,
    coolant: 205,
    iat: 92,
    // fuel: simulate resistance (Ω), derive % for display
    fuelR: 42,
    fuel: 0, // computed
    battery: 14.2,
    boost: 12.4,
    oilP: 62,
    fuelP: 39,
    afr: 12.4,
    ego: 3.1,
    sats: 11,
    // === knock (CCM EngineKnockState 0x307, DLC 8) ===
    // B0 status_flags, B1 energy, B2 baseline, B3 threshold,
    // B4 event_count, B5 last_event_rpm_div100, B6 last_event_boost_kpa
    knockEnergy: 20,
    knockBaseline: 15,
    knockThreshold: 180,
    knockEvents: 0,
    knockLastRpm: 0,
    knockLastBoost: 0,
    // ring buffer of last N samples for the live trace
    knockTrace: [],
    turnLeft: false,
    turnRight: false,
    highbeam: false,
    coolantWarn: false,

    // water/meth
    methState: 'ARMED',
    methDuty: 0,    // % 0..100
    methTank: 50,   // %
    methFlow: 'OK',
    methFaults: new Set(), // codes
  };
  state.fuel = fuelPctFromResistance(state.fuelR);

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
    fuelpVal: $('fuelp-val'),
    fuelpFill: $('fuelp-fill'),
    egoVal: $('ego-val'),
    afrVal: $('afr-val'), afrLambda: $('afr-lambda'), afrState: $('afr-state'),
    afrPointer: $('afr-pointer'),
    gpsSats: $('gps-sats'),
    clockTime: $('clock-time'),
    clockTz: $('clock-tz'),
    warnBanner: $('warn-banner'),
    iconHigh: $('icon-highbeam'),
    turnLeft:  $('turn-left'),
    turnRight: $('turn-right'),
    // knock overlay
    knockOverlay: $('knock-overlay'),
    knockGraph: $('knock-graph'),
    knockBaseline: $('knock-baseline'),
    knockBaselineArea: $('knock-baseline-area'),
    knockEnergy: $('knock-energy'),
    knockThresh: $('knock-thresh'),
    knockThreshLabel: $('knock-thresh-label'),
    knockEventsGroup: $('knock-events'),
    knockEnergyNum: $('knock-energy-num'),
    knockBaselineNum: $('knock-baseline-num'),
    knockEventsNum: $('knock-events-num'),
    knockLastRpm: $('knock-last-rpm'),
    knockLastBoost: $('knock-last-boost'),
    knockStatus: $('knock-status'),
    methStatePill: $('meth-state-pill'),
    methDutyVal: $('meth-duty-val'),
    methTankVal: $('meth-tank-val'),
    methFlowPill: $('meth-flow-pill'),
    methFaults: $('meth-faults'),
  };

  // ---------- sim profile ----------
  function tickSim(dt) {
    state.t += dt;
    const t = state.t;

    const throtTarget = 0.5 + 0.5 * Math.sin(t * 0.18);
    state.throttle = lerp(state.throttle, throtTarget, 0.04);

    const speedTarget = state.throttle * 85;
    state.speed = lerp(state.speed, speedTarget, 0.02);

    const idleRpm = 800;
    const load = state.speed * 32 + state.throttle * 1200;
    const noise = (Math.sin(t * 7.3) + Math.sin(t * 11.1)) * 40;
    state.rpm = clamp(idleRpm + load + noise, 700, 6200);

    const boostTarget = 4 + state.throttle * 14;
    state.boost = lerp(state.boost, boostTarget, 0.08);

    const afrTarget = 14.2 + Math.sin(t * 0.6) * 0.6 + (state.throttle - 0.5) * 0.8;
    state.afr = lerp(state.afr, afrTarget, 0.1);
    state.ego = lerp(state.ego, (14.7 - state.afr) * 4, 0.1);

    const coolTarget = state.coolantWarn ? 235 : 200 + Math.sin(t * 0.05) * 8;
    state.coolant = lerp(state.coolant, coolTarget, 0.01);

    state.iat = lerp(state.iat, 84 + state.throttle * 15, 0.005);
    state.battery = lerp(state.battery, 14.0 + Math.sin(t * 0.3) * 0.3, 0.05);
    state.oilP = lerp(state.oilP, 25 + (state.rpm / 6000) * 55, 0.05);
    state.sats = Math.round(lerp(state.sats, 10 + Math.sin(t * 0.2) * 2, 0.05));

    // fuel % tracks the slider (which sets resistance)
    state.fuel = fuelPctFromResistance(state.fuelR);
  }

  // ---------- render ----------
  function render() {
    // RPM
    els.rpmVal.textContent = String(Math.round(state.rpm));
    els.rpmFill.style.width = clamp(state.rpm / 6000 * 100, 0, 100) + '%';

    els.speed.textContent = Math.round(state.speed);

    // Coolant
    els.coolVal.textContent = Math.round(state.coolant);
    els.coolFill.style.width = clamp((state.coolant - 140) / (240 - 140) * 100, 0, 100) + '%';
    if (state.coolant >= 230) { els.coolVal.style.color = 'var(--crit)'; els.coolFill.className = 'fill crit'; }
    else if (state.coolant >= 210) { els.coolVal.style.color = 'var(--warn)'; els.coolFill.className = 'fill warn'; }
    else { els.coolVal.style.color = 'var(--text-0)'; els.coolFill.className = 'fill warm'; }

    els.iatVal.textContent = Math.round(state.iat);
    els.iatFill.style.width = clamp((state.iat - 60) / 140 * 100, 0, 100) + '%';

    // Fuel (from sender resistance)
    els.fuelVal.textContent = Math.round(state.fuel);
    els.fuelFill.style.width = state.fuel + '%';
    els.fuelFill.style.background = 'var(--accent)';
    if (state.fuel <= FUEL_LOW_PCT) {
      els.fuelVal.style.color = 'var(--warn)';
    } else {
      els.fuelVal.style.color = 'var(--text-0)';
    }

    els.battVal.textContent = fmt(state.battery, 1);
    els.battFill.style.width = clamp((state.battery - 11.5) / 3 * 100, 0, 100) + '%';
    els.boostVal.textContent = fmt(state.boost, 1);
    els.boostFill.style.width = clamp(state.boost / 20 * 100, 0, 100) + '%';
    els.oilpVal.textContent = Math.round(state.oilP);
    els.fuelpVal.textContent = Math.round(state.fuelP);
    els.fuelpFill.style.width = clamp(state.fuelP / 60 * 100, 0, 100) + '%';
    if (state.fuelP < 15) {
      els.fuelpVal.style.color = 'var(--crit)';
      els.fuelpFill.className = 'fill crit';
      els.fuelpFill.style.background = 'var(--crit)';
    } else if (state.fuelP < 25) {
      els.fuelpVal.style.color = 'var(--warn)';
      els.fuelpFill.className = 'fill warn';
      els.fuelpFill.style.background = 'var(--warn)';
    } else {
      els.fuelpVal.style.color = 'var(--text-0)';
      els.fuelpFill.className = 'fill';
      els.fuelpFill.style.background = 'var(--ok)';
    }
    els.egoVal.textContent = (state.ego >= 0 ? '+' : '') + fmt(state.ego, 1);

    // AFR
    els.afrVal.textContent = fmt(state.afr, 1);
    els.afrLambda.textContent = fmt(state.afr / 14.7, 2);
    if (state.afr < 13.5) els.afrState.textContent = 'rich';
    else if (state.afr > 15.2) els.afrState.textContent = 'lean';
    else els.afrState.textContent = 'stoich';
    const afrNorm = (state.afr - 14.7) / (16.0 - 11.0) * 2;
    const afrAngle = clamp(afrNorm, -1, 1) * 90;
    els.afrPointer.setAttribute('transform', `rotate(${afrAngle.toFixed(1)} 120 120)`);

    // topbar
    els.gpsSats.textContent = `FIX ${state.sats} SAT`;

    // clock — 12-hour format
    const now = new Date();
    let h12 = now.getHours() % 12;
    if (h12 === 0) h12 = 12;
    els.clockTime.textContent = `${h12}:${String(now.getMinutes()).padStart(2,'0')}`;
    els.clockTz.textContent = now.getHours() >= 12 ? 'PM' : 'AM';

    // turn signals (chevron ticker)
    els.turnLeft.dataset.on  = state.turnLeft  ? 'true' : 'false';
    els.turnRight.dataset.on = state.turnRight ? 'true' : 'false';

    // topbar icons
    els.iconHigh.classList.toggle('on', state.highbeam);

    // === water/meth cell ===
    els.methStatePill.dataset.state = state.methState;
    els.methStatePill.textContent = state.methState;

    // If state is SPRAYING and user hasn't set a duty, ramp it with throttle for visual life
    const dutyTarget = state.methState === 'SPRAYING'
      ? clamp(Math.round(40 + state.throttle * 50), 0, 100)
      : state.methState === 'TEST'
        ? state.methDuty
        : 0;
    state.methDuty = lerp(state.methDuty, dutyTarget, 0.1);
    els.methDutyVal.textContent = Math.round(state.methDuty);

    els.methTankVal.textContent = Math.round(state.methTank);
    els.methFlowPill.dataset.flow = state.methFlow;
    els.methFlowPill.textContent = state.methFlow === 'UNKNOWN' ? '—' : state.methFlow;

    // fault tags (latched, like updateFaultLatch in the CCM)
    els.methFaults.innerHTML = '';
    for (const code of state.methFaults) {
      const tag = document.createElement('span');
      tag.className = 'ftag';
      tag.textContent = METH_FAULT_NAMES[code] || `0x${code.toString(16).toUpperCase()}`;
      els.methFaults.appendChild(tag);
    }
    // auto-add LOW_TANK and NO_FLOW tags if sim states are set, even if user didn't check the boxes
    if (state.methTank <= METH_TANK_LOW_PCT && !state.methFaults.has(0x01)) {
      // not auto-added; user controls via sim checkboxes. Just color the tank value.
    }
    if (state.methTank <= METH_TANK_LOW_PCT) {
      els.methTankVal.style.color = 'var(--crit)';
    } else if (state.methTank <= 25) {
      els.methTankVal.style.color = 'var(--warn)';
    } else {
      els.methTankVal.style.color = 'var(--text-1)';
    }

    // === warning banner: priority order coolant > fuel > meth ===
    const showCoolant = state.coolantWarn;
    const showFuel = state.fuel <= FUEL_LOW_PCT && !showCoolant;
    const showMeth = state.methFaults.size > 0 && !showCoolant && !showFuel;
    if (showCoolant) {
      els.warnBanner.hidden = false;
      els.warnBanner.className = 'warn-banner coolant';
      els.warnBanner.textContent = `Coolant temperature critical — ${Math.round(state.coolant)} °F`;
    } else if (showFuel) {
      els.warnBanner.hidden = false;
      els.warnBanner.className = 'warn-banner fuel';
      els.warnBanner.textContent = `Low fuel — ${Math.round(state.fuel)} %`;
    } else if (showMeth) {
      els.warnBanner.hidden = false;
      els.warnBanner.className = 'warn-banner meth';
      const names = [...state.methFaults].map(c => METH_FAULT_NAMES[c] || `0x${c.toString(16)}`).join(', ');
      els.warnBanner.textContent = `Water/Meth fault — ${names}`;
    } else {
      els.warnBanner.hidden = true;
    }
  }

  // ---------- main loop ----------
  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    tickSim(dt);
    render();
    knockTick(dt);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // ---------- sim controls ----------
  const simControls = $('sim-controls');
  const simToggle = $('sim-toggle');
  simToggle.addEventListener('click', () => {
    simControls.hidden = !simControls.hidden;
    const expanded = !simControls.hidden;
    simToggle.setAttribute('aria-expanded', String(expanded));
    simToggle.textContent = expanded ? 'HIDE SIM CONTROLS' : 'SHOW SIM CONTROLS';
  });

  $('sim-turn-left').addEventListener('change',  (e) => state.turnLeft  = e.target.checked);
  $('sim-turn-right').addEventListener('change', (e) => state.turnRight = e.target.checked);
  $('sim-highbeam').addEventListener('change',   (e) => state.highbeam  = e.target.checked);
  $('sim-warn-coolant').addEventListener('click', () => { state.coolantWarn = true; });
  $('sim-clear-warn').addEventListener('click',   () => { state.coolantWarn = false; });

  // fuel slider drives resistance directly
  const fuelR = $('sim-fuel-r'), fuelRVal = $('sim-fuel-r-val');
  fuelR.addEventListener('input', () => {
    state.fuelR = Number(fuelR.value);
    fuelRVal.textContent = state.fuelR;
  });

  // fuel pressure slider drives value directly (0-60 psi)
  const fuelp = $('sim-fuelp'), fuelpVal = $('sim-fuelp-val');
  fuelp.addEventListener('input', () => {
    state.fuelP = Number(fuelp.value);
    fuelpVal.textContent = state.fuelP;
  });

  // === knock sim controls ===
  // sliders directly drive the corresponding state.energy / baseline / threshold
  // values that the overlay reads.
  const kEnergy = $('sim-knock-energy'), kEnergyVal = $('sim-knock-energy-val');
  kEnergy.addEventListener('input', () => {
    state.knockEnergy = Number(kEnergy.value);
    kEnergyVal.textContent = state.knockEnergy;
  });
  const kBase = $('sim-knock-baseline'), kBaseVal = $('sim-knock-baseline-val');
  kBase.addEventListener('input', () => {
    state.knockBaseline = Number(kBase.value);
    kBaseVal.textContent = state.knockBaseline;
  });
  const kThresh = $('sim-knock-threshold'), kThreshVal = $('sim-knock-threshold-val');
  kThresh.addEventListener('input', () => {
    state.knockThreshold = Number(kThresh.value);
    kThreshVal.textContent = state.knockThreshold;
  });
  // manual +1 event button (matches how the CCM would auto-fire when energy >= threshold)
  $('sim-knock-event').addEventListener('click', () => {
    state.knockEvents = (state.knockEvents + 1) & 0xFF;
    state.knockLastRpm = Math.round(state.rpm / 100);
    state.knockLastBoost = Math.round(state.boost * 6.895); // psi → kPa
  });
  // open the knock submenu (option a: modal overlay)
  const knockOverlay = $('knock-overlay');
  const openKnock = () => { knockOverlay.hidden = false; $('knock-close').focus(); };
  const closeKnock = () => { knockOverlay.hidden = true; };
  $('sim-open-knock').addEventListener('click', openKnock);
  $('knock-launch').addEventListener('click', openKnock);
  $('knock-close').addEventListener('click', closeKnock);
  knockOverlay.addEventListener('click', (e) => { if (e.target === knockOverlay) closeKnock(); });

  // meth controls
  $('sim-meth-state').addEventListener('change', (e) => { state.methState = e.target.value; });
  $('sim-meth-flow').addEventListener('change',  (e) => { state.methFlow  = e.target.value; });
  const methDuty = $('sim-meth-duty'), methDutyVal = $('sim-meth-duty-val');
  methDuty.addEventListener('input', () => {
    state.methDuty = Number(methDuty.value);
    methDutyVal.textContent = state.methDuty;
  });
  const methTank = $('sim-meth-tank'), methTankVal = $('sim-meth-tank-val');
  methTank.addEventListener('input', () => {
    state.methTank = Number(methTank.value);
    methTankVal.textContent = state.methTank;
  });

  // fault toggles (latched — set/clear individually, like updateFaultLatch)
  function bindFault(id, code) {
    $(id).addEventListener('change', (e) => {
      if (e.target.checked) state.methFaults.add(code);
      else state.methFaults.delete(code);
    });
  }
  bindFault('sim-meth-fault-low-tank', 0x01);
  bindFault('sim-meth-fault-no-flow',  0x02);
  bindFault('sim-meth-fault-pump-oc',  0x04);
  bindFault('sim-meth-fault-sensor',   0x05);
  bindFault('sim-meth-fault-overtemp', 0x06);
  bindFault('sim-meth-fault-can',      0x07);

  // keyboard
  window.addEventListener('keydown', (e) => {
    if (e.key === 't' || e.key === 'T') { state.turnLeft = !state.turnLeft; $('sim-turn-left').checked = state.turnLeft; }
    if (e.key === 'y' || e.key === 'Y') { state.turnRight = !state.turnRight; $('sim-turn-right').checked = state.turnRight; }
    if (e.key === 'k' || e.key === 'K') { knockOverlay.hidden ? openKnock() : closeKnock(); }
    if (e.key === 'Escape' && !knockOverlay.hidden) closeKnock();
  });

  // === knock live trace ===
  // ring buffer: keep last 200 samples, push every animation frame
  const KNOCK_TRACE_LEN = 200;
  function pushKnockSample() {
    state.knockTrace.push(state.knockEnergy);
    if (state.knockTrace.length > KNOCK_TRACE_LEN) state.knockTrace.shift();
  }
  // auto-fire a knock event when the simulated energy crosses the threshold
  // (mirrors how the CCM's adaptive threshold logic would push 0x308)
  let knockAboveThreshold = false;
  function maybeFireKnockEvent() {
    const aboveThreshold = state.knockEnergy >= state.knockThreshold;
    if (aboveThreshold && !knockAboveThreshold) {
      state.knockEvents = (state.knockEvents + 1) & 0xFF;
      state.knockLastRpm = Math.round(state.rpm / 100);
      state.knockLastBoost = Math.round(state.boost * 6.895);
    }
    knockAboveThreshold = aboveThreshold;
  }
  // baseline trail (slower, lighter) so the noise floor is visible underneath energy
  const KNOCK_BASELINE_LEN = 200;
  const baselineTrace = [];
  function pushBaselineSample() {
    // baseline drifts slowly with throttle for visual interest
    const drift = state.throttle * 6 + Math.sin(state.t * 0.3) * 2;
    const v = clamp(state.knockBaseline + drift, 0, 255);
    baselineTrace.push(v);
    if (baselineTrace.length > KNOCK_BASELINE_LEN) baselineTrace.shift();
  }

  // === knock graph renderer ===
  // SVG viewBox is 0..800 wide × 0..280 tall, but the y axis maps energy 0..255
  // (so bigger energy is HIGHER on screen, smaller y). y = 280 - (v/255)*280.
  function renderKnock() {
    if (knockOverlay.hidden) return;
    const w = 800, h = 280;
    const xy = (i, v) => {
      const x = (i / (KNOCK_TRACE_LEN - 1)) * w;
      const y = h - (clamp(v, 0, 255) / 255) * h;
      return [x, y];
    };
    // energy line
    let d = '';
    for (let i = 0; i < state.knockTrace.length; i++) {
      const [x, y] = xy(i, state.knockTrace[i]);
      d += (i === 0 ? `M ${x.toFixed(1)} ${y.toFixed(1)}` : ` L ${x.toFixed(1)} ${y.toFixed(1)}`);
    }
    els.knockEnergy.setAttribute('d', d);
    // baseline line + area
    let db = '';
    for (let i = 0; i < baselineTrace.length; i++) {
      const [x, y] = xy(i, baselineTrace[i]);
      db += (i === 0 ? `M ${x.toFixed(1)} ${y.toFixed(1)}` : ` L ${x.toFixed(1)} ${y.toFixed(1)}`);
    }
    els.knockBaseline.setAttribute('d', db);
    // area: baseline line + drop to bottom
    const lastIdx = baselineTrace.length - 1;
    if (lastIdx >= 0) {
      const [x0, y0] = xy(0, baselineTrace[0]);
      const [x1] = xy(lastIdx, baselineTrace[lastIdx]);
      els.knockBaselineArea.setAttribute('d', `${db} L ${x1.toFixed(1)} ${h} L ${x0.toFixed(1)} ${h} Z`);
    }
    // threshold dashed line at current threshold value
    const [, ty] = xy(0, state.knockThreshold);
    els.knockThresh.setAttribute('y1', ty);
    els.knockThresh.setAttribute('y2', ty);
    els.knockThreshLabel.setAttribute('y', ty - 4);
    els.knockThreshLabel.textContent = `MAX ${state.knockThreshold}`;
    // event markers: tiny vertical ticks where event_count incremented
    // (we don't keep per-event history, so just pulse the right edge when an event fired recently)
    els.knockEventsGroup.innerHTML = '';
    // right-edge pulse: a tall thin line at the very right when energy >= threshold
    if (state.knockEnergy >= state.knockThreshold) {
      const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      ln.setAttribute('x1', '798'); ln.setAttribute('x2', '798');
      ln.setAttribute('y1', '0');   ln.setAttribute('y2', '280');
      ln.setAttribute('class', 'knock-event');
      els.knockEventsGroup.appendChild(ln);
    }
    // readout text
    els.knockEnergyNum.textContent = String(state.knockEnergy);
    els.knockBaselineNum.textContent = `base ${state.knockBaseline}`;
    els.knockEventsNum.textContent = String(state.knockEvents);
    els.knockLastRpm.textContent  = state.knockLastRpm ? String(state.knockLastRpm * 100) : '—';
    els.knockLastBoost.textContent = state.knockLastBoost ? `${state.knockLastBoost} kPa` : '—';
    // status
    const energyClass = state.knockEnergy >= state.knockThreshold ? 'crit' : (state.knockEnergy >= state.knockThreshold * 0.75 ? 'warn' : '');
    els.knockEnergyNum.setAttribute('class', energyClass);
    els.knockStatus.textContent = state.knockEnergy >= state.knockThreshold ? 'KNOCK!' : (state.knockEnergy >= state.knockThreshold * 0.75 ? 'NEAR' : 'OK');
    els.knockStatus.className = 'kval' + (energyClass ? ' ' + energyClass : '');
  }

  // wire knock sampling into the main loop. Add a sample every frame; the
  // trace length caps at 200 so old samples age out.
  let knockTickAccum = 0;
  const KNOCK_SAMPLE_HZ = 30; // 30 Hz matches typical knock sample rate
  function knockTick(dt) {
    knockTickAccum += dt;
    if (knockTickAccum < 1 / KNOCK_SAMPLE_HZ) return;
    knockTickAccum = 0;
    pushKnockSample();
    pushBaselineSample();
    maybeFireKnockEvent();
    renderKnock();
  }

})();
