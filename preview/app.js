// frogdash v0.2 — browser preview simulator (DESIGN REVIEW ONLY)
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
    coolant: 235,
    iat: 92,
    // fuel: simulate resistance (Ω), derive % for display
    fuelR: 42,
    fuel: 0, // computed
    battery: 14.2,
    boost: 12.4,
    oilP: 62,
    oilT: 218,
    afr: 12.4,
    ego: 3.1,
    ext: 54,
    sats: 11,
    turnLeft: false,
    turnRight: false,
    highbeam: false,
    ecu: false,
    brake: false,
    coolantWarn: true,

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
    topbarFuelPct: $('topbar-fuel-pct'),
    battVal: $('batt-val'),   battFill: $('batt-fill'),
    boostVal: $('boost-val'), boostFill: $('boost-fill'),
    oilpVal: $('oilp-val'),
    oiltVal: $('oilt-val'),
    egoVal: $('ego-val'),
    afrVal: $('afr-val'), afrLambda: $('afr-lambda'), afrState: $('afr-state'),
    afrPointer: $('afr-pointer'),
    topbarExt: $('topbar-ext'),
    gpsSats: $('gps-sats'),
    clockTime: $('clock-time'),
    warnBanner: $('warn-banner'),
    iconHigh: $('icon-highbeam'), iconEcu: $('icon-ecu'),
    iconBrake: $('icon-brake'),
    turnLeft:  $('turn-left'),
    turnRight: $('turn-right'),
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

    state.iat = lerp(state.iat, state.ext + 30 + state.throttle * 15, 0.005);
    state.battery = lerp(state.battery, 14.0 + Math.sin(t * 0.3) * 0.3, 0.05);
    state.oilP = lerp(state.oilP, 25 + (state.rpm / 6000) * 55, 0.05);
    state.oilT = lerp(state.oilT, 195 + (state.throttle) * 35, 0.005);
    state.sats = Math.round(lerp(state.sats, 10 + Math.sin(t * 0.2) * 2, 0.05));
    state.ext = Math.round(54 + Math.sin(t * 0.02) * 3);

    // fuel % tracks the slider (which sets resistance)
    state.fuel = fuelPctFromResistance(state.fuelR);
  }

  // ---------- render ----------
  function render() {
    // RPM
    els.rpmVal.textContent = Math.round(state.rpm).toLocaleString().replace(/,/g, ' ');
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
    els.topbarFuelPct.textContent = Math.round(state.fuel);
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
    els.oiltVal.textContent = Math.round(state.oilT);
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
    els.topbarExt.textContent = state.ext;
    els.gpsSats.textContent = `FIX ${state.sats} SAT`;

    // clock
    const now = new Date();
    els.clockTime.textContent = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;

    // turn signals (chevron ticker)
    els.turnLeft.dataset.on  = state.turnLeft  ? 'true' : 'false';
    els.turnRight.dataset.on = state.turnRight ? 'true' : 'false';

    // topbar icons
    els.iconHigh.classList.toggle('on', state.highbeam);
    els.iconEcu.classList.toggle('amber', state.ecu);
    els.iconBrake.classList.toggle('warn', state.brake);

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
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // ---------- sim controls ----------
  $('sim-turn-left').addEventListener('change',  (e) => state.turnLeft  = e.target.checked);
  $('sim-turn-right').addEventListener('change', (e) => state.turnRight = e.target.checked);
  $('sim-highbeam').addEventListener('change',   (e) => state.highbeam  = e.target.checked);
  $('sim-ecu').addEventListener('change',        (e) => state.ecu       = e.target.checked);
  $('sim-brake').addEventListener('change',      (e) => state.brake     = e.target.checked);
  $('sim-warn-coolant').addEventListener('click', () => { state.coolantWarn = true; });
  $('sim-clear-warn').addEventListener('click',   () => { state.coolantWarn = false; });

  // fuel slider drives resistance directly
  const fuelR = $('sim-fuel-r'), fuelRVal = $('sim-fuel-r-val');
  fuelR.addEventListener('input', () => {
    state.fuelR = Number(fuelR.value);
    fuelRVal.textContent = state.fuelR;
  });

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

  // menu
  const menu = $('menu-overlay');
  $('sim-toggle-menu').addEventListener('click', () => { menu.hidden = !menu.hidden; });
  menu.addEventListener('click', (e) => { if (e.target === menu) menu.hidden = true; });

  // keyboard
  window.addEventListener('keydown', (e) => {
    if (e.key === 'm' || e.key === 'M') { menu.hidden = !menu.hidden; }
    if (e.key === 't' || e.key === 'T') { state.turnLeft = !state.turnLeft; $('sim-turn-left').checked = state.turnLeft; }
    if (e.key === 'y' || e.key === 'Y') { state.turnRight = !state.turnRight; $('sim-turn-right').checked = state.turnRight; }
  });
})();
