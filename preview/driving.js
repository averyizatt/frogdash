/* Driver preferences, advisory alerts and read-only review. No GPIO/power control. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const metricDefs = {
    coolant: ['Coolant', 'engine.coolant_c', '°F', 100, 250, 0, n => n * 1.8 + 32],
    oil: ['Oil pressure', 'engine.oil_pressure_psi', 'psi', 0, 100, 1],
    fuelp: ['Fuel pressure', 'engine.fuel_pressure_psi', 'psi', 0, 100, 1],
    iat: ['Intake air', 'engine.iat_c', '°F', 0, 200, 0, n => n * 1.8 + 32],
    batt: ['Battery', 'vehicle.battery_v', 'V', 10, 16, 1], fuel: ['Fuel level', 'vehicle.fuel_pct', '%', 0, 100, 0],
    afr: ['Air / fuel', 'engine.afr', 'AFR', 10, 18, 1], target: ['AFR target', 'ecu.afr_target', 'AFR', 10, 18, 1],
    boost: ['Boost', 'engine.boost_kpa', 'psi', -15, 30, 1, n => n * .145037738],
    meth: ['Injection', 'meth.duty_pct', '%', 0, 100, 0], tank: ['Meth tank', 'meth.tank_pct', '%', 0, 100, 0],
    knock: ['Knock energy', 'knock.energy', '', 0, 255, 0],
    tripa: ['Trip A', 'trip.a_km', 'mi', 0, 500, 1, n => n / 1.609344],
    tripb: ['Trip B', 'trip.b_km', 'mi', 0, 500, 1, n => n / 1.609344],
    range: ['Est. range', 'fuel.range_km', 'mi', 0, 400, 0, n => n / 1.609344],
    economy: ['Est. economy', 'fuel.instant_mpg', 'US MPG', 0, 60, 1],
    average: ['Avg. economy', 'fuel.average_mpg', 'US MPG', 0, 60, 1],
    lastlap: ['Last lap', '@last', 's', 0, 180, 2], bestlap: ['Best lap', '@best', 's', 0, 180, 2]
  };
  const layouts = {street: ['coolant', 'oil', 'fuelp', 'iat', 'batt', 'fuel'], tuning: ['afr', 'target', 'boost', 'fuelp', 'meth', 'tank'], track: ['coolant', 'oil', 'iat', 'boost', 'lastlap', 'bestlap']};
  let prefs = {layout: 'street', layouts: structuredClone(layouts), lighting: 'auto', day: 100, night: 55, nightAccent: '#ffc77d', shift: 5800, chimeVolume: 50};
  try {
    const p = JSON.parse(localStorage.getItem('frogdash.driving.v1'));
    if (p && typeof p === 'object') {
      if (Object.hasOwn(layouts, p.layout)) prefs.layout = p.layout;
      if (['auto', 'day', 'night'].includes(p.lighting)) prefs.lighting = p.lighting;
      for (const key of ['street', 'tuning', 'track']) if (Array.isArray(p.layouts?.[key]) && p.layouts[key].length === 6 && p.layouts[key].every(k => Object.hasOwn(metricDefs, k))) prefs.layouts[key] = p.layouts[key];
      for (const [key, lo, hi] of [['day', 35, 100], ['night', 20, 100], ['shift', 2000, 9000], ['chimeVolume', 0, 100]]) if (Number.isFinite(p[key]) && p[key] >= lo && p[key] <= hi) prefs[key] = p[key];
      if (/^#[0-9a-f]{6}$/i.test(p.nightAccent)) prefs.nightAccent = p.nightAccent;
    }
  } catch { /* Use defaults when browser storage is unavailable. */ }
  let latest = {values: {}}, online = false, loadedSettings = false, alertSignature = '', ackBusy = false, markBusy = false;
  let audio, audioAttempted = false, audioError = false, lastChime = -Infinity, seenAlerts = null, pendingChime = 0, pendingTest = 0;
  const get = key => online && latest.values?.[key]?.quality === 'live' ? latest.values[key].value : null;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  // One reading for any metric, in display units, with the same quality rules everywhere.
  function read(key, snapshot = latest, connected = online) {
    const [title, signal, unit, min, max, digits, convert] = window.FrogdashUnits.definition(metricDefs[key]);
    const race = (snapshot.mode === 'demo' ? window.frogdashRaceView : snapshot.race) || {};
    const live = connected && snapshot.values?.[signal]?.quality === 'live' ? snapshot.values[signal].value : null;
    const raw = !connected ? null : signal === '@last' ? race.laps?.at(-1)?.seconds : signal === '@best' ? race.best_lap : live;
    const v = Number.isFinite(raw) ? (convert ? convert(raw) : raw) : null, value = Number.isFinite(v) ? v : null;
    const quality = value !== null ? 'live' : !connected ? 'stale' : snapshot.values?.[signal]?.quality || 'unavailable';
    const label = value !== null ? signal.startsWith('fuel.') ? 'Estimated' : signal.startsWith('trip.') ? 'Tracked' : 'Live' : !connected ? 'Stale' : snapshot.values?.[signal]?.quality || 'No signal';
    return {key, title, signal, unit, min, max, digits, value, quality, label, text: value === null ? '\u2014' : value.toFixed(digits), ratio: value === null ? 0 : Math.max(0, Math.min(1, (value - min) / (max - min)))};
  }
  // Press and hold any [data-gauge-slot] element; its owner listens for 'gauge-hold'.
  const picker = el('dialog', undefined, 'workspace-dialog gauge-picker'); picker.id = 'gauge-picker'; picker.setAttribute('aria-labelledby', 'gauge-picker-title');
  picker.innerHTML = '<header class="dialog-header"><div><span class="eyebrow">PRESS AND HOLD ANY GAUGE</span><h2 id="gauge-picker-title">Change gauge</h2><p id="gauge-picker-note"></p></div><button id="gauge-picker-default" type="button">Restore default</button><button id="gauge-picker-close" class="close-button" type="button">Close <span aria-hidden="true">\u00d7</span></button></header><div id="gauge-picker-options" class="gauge-picker-options" role="group" aria-label="Readings"></div>';
  document.body.append(picker);
  let pickRequest = null;
  function renderPicker() {
    if (!picker.open || !pickRequest) return;
    for (const button of $('gauge-picker-options').children) {
      const m = read(button.dataset.metric);
      button.setAttribute('aria-pressed', String(button.dataset.metric === pickRequest.current));
      button.querySelector('small').textContent = m.value === null ? m.label : `${m.text} ${m.unit}`.trim();
    }
  }
  for (const key of Object.keys(metricDefs)) {
    const button = el('button'); button.type = 'button'; button.dataset.metric = key;
    button.append(el('strong', metricDefs[key][0]), el('small'));
    button.onclick = () => { const request = pickRequest; picker.close(); request?.onPick(key); };
    $('gauge-picker-options').append(button);
  }
  $('gauge-picker-close').onclick = () => picker.close();
  $('gauge-picker-default').onclick = () => { const request = pickRequest; picker.close(); request?.onPick(request.fallback); };
  picker.addEventListener('close', () => { pickRequest = null; });
  function pick(request) {
    pickRequest = request;
    $('gauge-picker-title').textContent = `Change ${request.title}`;
    $('gauge-picker-note').textContent = `Default: ${metricDefs[request.fallback][0]}. Speed and RPM stay fixed.`;
    if (!picker.open) picker.showModal();
    renderPicker();
  }
  window.FrogdashMetrics = {defs: metricDefs, read, pick};
  let hold = null;
  const cancelHold = () => { if (hold) { clearTimeout(hold.timer); hold.target.classList.remove('gauge-holding'); } hold = null; };
  const fireHold = target => { cancelHold(); if (!picker.open) target.dispatchEvent(new Event('gauge-hold')); };
  document.addEventListener('pointerdown', event => {
    const target = event.target.closest?.('[data-gauge-slot]');
    if (!target || event.button > 0) return;
    cancelHold(); target.classList.add('gauge-holding');
    hold = {target, x: event.clientX, y: event.clientY, timer: setTimeout(() => fireHold(target), 650)};
  });
  document.addEventListener('pointermove', event => { if (hold && Math.hypot(event.clientX - hold.x, event.clientY - hold.y) > 14) cancelHold(); });
  for (const type of ['pointerup', 'pointercancel', 'scroll']) document.addEventListener(type, cancelHold, true);
  // Touch long-press and mouse right-click both raise contextmenu in Chromium.
  document.addEventListener('contextmenu', event => { const target = event.target.closest?.('[data-gauge-slot]'); if (target) { event.preventDefault(); fireHold(target); } });
  const row = el('section', undefined, 'sensor-row profile-sensors'); row.id = 'profile-sensors'; row.hidden = true;
  document.querySelector('.sensor-row').after(row);
  const tiles = [];
  for (let i = 0; i < 6; i++) {
    const card = el('article', undefined, 'sensor-card');
    const heading = el('div', undefined, 'card-heading'), title = el('h2'), quality = el('span', '', 'quality-label'); heading.append(title, quality);
    const readout = el('div', undefined, 'sensor-reading'), value = el('span'), unit = el('span', '', 'unit'); readout.append(value, unit);
    const track = el('div', undefined, 'track'), fill = el('div', undefined, 'fill'); track.append(fill);
    const scale = el('div', undefined, 'scale-labels'), lo = el('span'), hi = el('span'); scale.append(lo, hi); card.append(heading, readout, track, scale); row.append(card);
    tiles.push({card, title, quality, value, unit, fill, lo, hi});
    const native = document.querySelectorAll('.sensor-row:not(.profile-sensors) .sensor-card')[i];
    for (const target of [card, native].filter(Boolean)) {
      target.dataset.gaugeSlot = `sensor-${i}`;
      target.addEventListener('gauge-hold', () => pick({title: `position ${i + 1}`, current: prefs.layouts[prefs.layout][i], fallback: layouts[prefs.layout][i], onPick: key => { prefs.layouts[prefs.layout][i] = key; saveDisplay(); }}));
    }
    const label = el('label', `Position ${i + 1}`), select = el('select'); select.id = `layout-slot-${i}`;
    for (const [key, [name]] of Object.entries(metricDefs)) { const option = el('option', name); option.value = key; select.append(option); }
    select.onchange = () => { prefs.layouts[prefs.layout][i] = select.value; saveDisplay(); };
    label.append(select); $('layout-instruments').append(label);
  }
  function syncDisplayForm() {
    prefs.layouts[prefs.layout].forEach((v, i) => { $(`layout-slot-${i}`).value = v; });
    $('lighting-mode').value = prefs.lighting; $('day-brightness').value = prefs.day; $('night-brightness').value = prefs.night;
    $('night-accent').value = prefs.nightAccent; $('shift-rpm').value = prefs.shift;
    $('alert-volume').value = prefs.chimeVolume; $('alert-volume-value').textContent = `${prefs.chimeVolume}%`;
    $('day-brightness-value').textContent = `${prefs.day}%`; $('night-brightness-value').textContent = `${prefs.night}%`;
    for (const b of document.querySelectorAll('button[data-layout]')) b.setAttribute('aria-pressed', String(b.dataset.layout === prefs.layout));
  }
  function saveDisplay() {
    try { localStorage.setItem('frogdash.driving.v1', JSON.stringify(prefs)); $('display-save-status').textContent = 'Saved on this display.'; }
    catch { $('display-save-status').textContent = 'Applied for this session; browser storage unavailable.'; }
    syncDisplayForm(); renderDisplay();
  }
  for (const b of document.querySelectorAll('button[data-layout]')) b.onclick = () => { prefs.layout = b.dataset.layout; saveDisplay(); };
  $('layout-reset').onclick = () => { prefs.layouts[prefs.layout] = [...layouts[prefs.layout]]; saveDisplay(); };
  $('lighting-mode').onchange = e => { prefs.lighting = e.target.value; saveDisplay(); };
  for (const key of ['day', 'night']) $(`${key}-brightness`).oninput = e => { prefs[key] = Number(e.target.value); saveDisplay(); };
  $('night-accent').onchange = e => { prefs.nightAccent = window.FrogdashAppearance.readableAccent(e.target.value); saveDisplay(); };
  $('shift-rpm').onchange = e => { if (e.target.reportValidity() && e.target.value !== '') { prefs.shift = Number(e.target.value); saveDisplay(); } };
  function renderDisplay() {
    const lights = get('lighting.running');
    const night = prefs.lighting === 'night' || prefs.lighting === 'auto' && lights === true;
    document.documentElement.dataset.lighting = night ? 'night' : 'day';
    document.documentElement.style.setProperty('--display-brightness', (night ? prefs.night : prefs.day) / 100);
    document.documentElement.style.setProperty('--night-accent', prefs.nightAccent);
    $('lighting-status').textContent = `${night ? 'Night' : 'Day'} mode · ${prefs.lighting === 'auto' ? lights === null ? 'running-light signal unavailable; day fallback' : 'following running lights' : 'manual override'}`;
    const native = prefs.layout === 'street' && JSON.stringify(prefs.layouts.street) === JSON.stringify(layouts.street);
    document.querySelector('.sensor-row:not(.profile-sensors)').hidden = !native;
    row.hidden = native;
    $('display').dataset.layout = prefs.layout;
    $('track-last').textContent = read('lastlap').value === null ? '—' : `${read('lastlap').text} s`;
    $('track-best').textContent = read('bestlap').value === null ? '—' : `${read('bestlap').text} s`;
    $('track-lap-readout').hidden = $('shift-lights').hidden = prefs.layout !== 'track';
    const rpm = get('engine.rpm');
    [...$('shift-lights').children].forEach((light, i) => { light.dataset.on = rpm !== null && rpm >= prefs.shift - (7 - i) * 150; });
    $('shift-lights').dataset.shift = rpm !== null && rpm >= prefs.shift;
    if (!native) prefs.layouts[prefs.layout].forEach((key, i) => {
      const m = read(key), tile = tiles[i];
      tile.title.textContent = m.title; tile.unit.textContent = m.unit; tile.lo.textContent = m.min; tile.hi.textContent = m.max;
      tile.value.textContent = m.text; tile.quality.textContent = m.label;
      tile.card.dataset.quality = m.quality;
      tile.fill.style.width = `${m.ratio * 100}%`;
    });
    renderPicker();
  }
  syncDisplayForm();
  const rules = [
    ['oil', 'Low oil pressure', [['oil_psi', 'Below psi', 1, 100, 1], ['oil_rpm', 'Above RPM', 500, 7000, 100]]],
    ['lean', 'Lean under boost', [['lean_delta', 'AFR over target', .2, 5, .1], ['lean_boost_kpa', 'Boost ≥ kPa', 0, 250, 1], ['lean_rpm', 'Above RPM', 500, 7000, 100]]],
    ['coolant', 'High coolant', [['coolant_c', 'Above °C', 70, 140, 1]]], ['meth', 'Water/meth faults', []]
  ];
  for (const [key, name, fields] of rules) {
    const group = el('div', undefined, 'alert-setting-row'), label = el('label', undefined, 'check-label'), enabled = el('input'); enabled.type = 'checkbox'; enabled.id = `setting-${key}_enabled`; label.append(enabled, document.createTextNode(name)); group.append(label);
    const inputs = el('div', undefined, 'alert-number-fields');
    for (const [key, name, min, max, step] of fields) { const l = el('label', name), input = el('input'); Object.assign(input, {type: 'number', min, max, step, id: `setting-${key}`, required: true}); l.append(input); inputs.append(l); }
    group.append(inputs); $('alert-fields').append(group);
  }
  const defaults = {oil_enabled: true, oil_psi: 15, oil_rpm: 1500, lean_enabled: true, lean_delta: 1, lean_boost_kpa: 20, lean_rpm: 1500, coolant_enabled: true, coolant_c: 112, meth_enabled: true, chime: false};
  const demo = {settings: {...defaults}, alerts: [], alert_seq: 0, marker_seq: 2, current: null, error: ''};
  const demoReview = {version: 1, name: 'drive-demo.json', started_ms: Date.now() - 60000, ended_ms: Date.now(), duration_s: 60, mode: 'demo', status: 'complete', sample_seconds: .5,
    channels: ['engine.rpm', 'vehicle.speed_kph', 'engine.boost_kpa', 'engine.afr', 'ecu.afr_target', 'engine.fuel_pressure_psi', 'engine.oil_pressure_psi', 'engine.coolant_c', 'engine.iat_c', 'meth.duty_pct', 'meth.tank_pct', 'knock.energy'],
    points: [], events: [], event_count: 0, stats: {'engine.boost_kpa': 85, 'engine.coolant_c': 96, 'engine.iat_c': 40, 'vehicle.speed_kph': 120, oil_min_above_1500: 42}, logs: [], race_results: []};
  for (let t = 0; t <= 60; t += .5) { const wave = Math.sin(t / 8) ** 2; demoReview.points.push([t, 1800 + wave * 3800, 40 + wave * 80, -20 + wave * 105, 14.7 - wave * 2.4, 14.7 - wave * 2.2, 39, 42 + wave * 20, 88 + t / 8, 30 + t / 6, wave > .5 ? wave * 70 : 0, 85 - t / 15, 18 + wave * 15]); }
  function demoMark(label, kind = 'manual', rule = null) {
    demo.marker_seq++; const event = {id: demo.marker_seq, t: 35 + (performance.now() / 1000) % 20, timestamp_ms: Date.now(), label, kind, rule, log: null, context: structuredClone(latest.values || {})};
    demoReview.events.push(event); demoReview.events = demoReview.events.slice(-250); demoReview.event_count++; demo.last_event = event; return event;
  }
  demoMark('Simulated tuning pull');
  function simulateAlerts() {
    const p = demo.settings;
    const compare = (keys, fn) => { const values = keys.map(get); return values.some(v => v === null) ? null : fn(...values); };
    const conditions = {
      knock: compare(['knock.warning', 'knock.critical'], (w, c) => w || c),
      coolant: p.coolant_enabled ? compare(['engine.coolant_c'], c => c >= p.coolant_c) : false,
      oil: p.oil_enabled ? compare(['engine.rpm', 'engine.oil_pressure_psi'], (r, o) => r >= p.oil_rpm && o < p.oil_psi) : false,
      lean: p.lean_enabled ? compare(['engine.rpm', 'engine.boost_kpa', 'engine.afr', 'ecu.afr_target'], (r, b, a, t) => r >= p.lean_rpm && b >= p.lean_boost_kpa && a > t + p.lean_delta) : false,
      meth: p.meth_enabled ? compare(['meth.fault_flags', 'meth.state', 'meth.flow'], (f, s, flow) => f !== 0 || s === 'FAULT' || s === 'SPRAYING' && ['LOW_FLOW', 'NO_FLOW'].includes(flow)) : false
    };
    const titles = {oil: 'LOW OIL PRESSURE', lean: 'LEAN UNDER BOOST', coolant: 'COOLANT HIGH', meth: 'WATER/METH FAULT', knock: 'KNOCK DETECTED'};
    for (const [key, active] of Object.entries(conditions)) {
      let a = demo.alerts.find(a => a.key === key);
      if (active === null) { if (a) a.condition = 'unknown'; continue; }
      if (active && !a?.active) {
        a = {key, title: titles[key], active: true, latched: true, acknowledged: false, condition: 'active', context: structuredClone(latest.values)};
        demo.alerts = demo.alerts.filter(x => x.key !== key).concat(a); demo.alert_seq++; demoMark(a.title, 'alert', key);
      } else if (!active && a) { a.active = false; a.condition = 'normal'; if (a.acknowledged) a.latched = false; }
      else if (a) a.condition = 'active';
    }
  }
  function currentDrive() { return latest.mode === 'demo' ? demo : latest.drive || {settings: defaults, alerts: []}; }
  async function request(path, options = {}) {
    const response = await fetch(path, {...options, signal: AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  }
  const review = new FrogdashReview($('drive-review'), {
    list: () => { demoReview.race_results = window.frogdashRaceView?.history || []; return latest.mode === 'demo' ? Promise.resolve({drives: [demoReview]}) : request('/drives'); },
    read: name => latest.mode === 'demo' ? Promise.resolve(structuredClone(demoReview)) : request('/drives/' + encodeURIComponent(name))
  });
  function selectTab(name) {
    for (const button of document.querySelectorAll('[data-driver-tab]')) { const active = button.dataset.driverTab === name; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; }
    for (const panel of document.querySelectorAll('[data-driver-panel]')) panel.hidden = panel.dataset.driverPanel !== name;
    if (name === 'review') review.load();
  }
  document.querySelector('.driver-tabs').setAttribute('role', 'tablist');
  document.querySelector('.driver-tabs').setAttribute('aria-orientation', 'vertical');
  for (const button of document.querySelectorAll('[data-driver-tab]')) {
    const key = button.dataset.driverTab, panel = document.querySelector(`[data-driver-panel="${key}"]`);
    button.id = `drive-tab-${key}`; button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', `drive-panel-${key}`);
    panel.id = `drive-panel-${key}`; panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', button.id);
    button.onclick = () => selectTab(button.dataset.driverTab);
    button.onkeydown = e => { const buttons = [...document.querySelectorAll('[data-driver-tab]')], i = buttons.indexOf(button); const n = e.key === 'ArrowDown' ? (i + 1) % buttons.length : e.key === 'ArrowUp' ? (i + buttons.length - 1) % buttons.length : e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length - 1 : null; if (n !== null) { e.preventDefault(); buttons[n].click(); buttons[n].focus(); } };
  }
  $('drive-launch').onclick = () => { $('drive-dialog').showModal(); render(); };
  $('drive-close').onclick = () => $('drive-dialog').close();
  $('alerts-launch').onclick = () => { selectTab('alerts'); $('drive-launch').click(); };
  function formSettings(settings) {
    for (const [key, v] of Object.entries(settings)) { const input = key === 'chime' ? $('alert-chime') : $(`setting-${key}`); if (input) { if (typeof v === 'boolean') input.checked = v; else input.value = v; } }
  }
  formSettings(defaults);
  $('alert-settings').onsubmit = async e => {
    e.preventDefault(); if (!$('alert-settings').reportValidity()) return;
    const settings = {};
    for (const [key, v] of Object.entries(defaults)) { const input = key === 'chime' ? $('alert-chime') : $(`setting-${key}`); settings[key] = typeof v === 'boolean' ? input.checked : Number(input.value); }
    const button = $('alert-settings').querySelector('[type=submit]'); button.disabled = true;
    try {
      if (latest.mode === 'demo') demo.settings = settings;
      else { const result = await request('/drive/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(settings)}); latest.drive = result; if (result.error) throw new Error(result.error); }
      $('alert-settings-status').textContent = latest.mode === 'demo' ? 'Simulated alert settings applied.' : 'Alert settings saved on the Pi.';
      if (settings.chime) enableAudio();
    } catch (error) { $('alert-settings-status').textContent = error.message; }
    finally { button.disabled = false; }
  };
  function audioStatus() {
    const status = audioError ? 'Audio unavailable; visual alerts remain active.'
      : prefs.chimeVolume === 0 ? 'Chime volume muted on this display.'
      : !currentDrive().settings?.chime ? 'Warning chimes off. Test chime checks the selected volume.'
      : audio?.state === 'running' ? 'Browser audio ready. Test chime to verify the screen speakers and Linux output.'
      : 'Audio needs activation; tap Test chime. Visual alerts remain active.';
    if ($('audio-status').textContent !== status) $('audio-status').textContent = status;
  }
  function enableAudio() {
    audioAttempted = true;
    try {
      audioError = false;
      if (!audio || audio.state === 'closed') {
        audio = new (window.AudioContext || window.webkitAudioContext)();
        audio.addEventListener('statechange', flushAudio);
      }
      // A blocked resume may remain pending indefinitely. Never block settings or startup on it.
      audio.resume().then(flushAudio).catch(() => { audioError = true; audioStatus(); });
      flushAudio();
    } catch { audioError = true; audioStatus(); }
  }
  // HDMI audio has no Linux volume control, so loudness comes from the level played here.
  // 100% is 0.9 of full scale (headroom against clipping); small display speakers are far
  // more efficient near 1-2 kHz than at the old 880 Hz pure tone.
  const outputLevel = () => .9 * prefs.chimeVolume / 100;
  function soundChime() {
    try {
      for (const delay of [0, .2]) {
        const start = audio.currentTime + delay, g = audio.createGain();
        g.gain.setValueAtTime(.0001, start);
        g.gain.exponentialRampToValueAtTime(outputLevel(), start + .015);
        g.gain.exponentialRampToValueAtTime(.0001, start + .15);
        g.connect(audio.destination);
        // A bell-like fundamental plus a softer octave; the mix peaks at the output level.
        for (const [frequency, share] of [[1047, 1 / 1.35], [2094, .35 / 1.35]]) {
          const o = audio.createOscillator(), mix = audio.createGain();
          o.frequency.value = frequency; mix.gain.value = share;
          o.connect(mix); mix.connect(g); o.start(start); o.stop(start + .16);
          o.onended = () => { o.disconnect(); mix.disconnect(); };
        }
        setTimeout(() => g.disconnect(), (delay + .3) * 1000);
      }
      lastChime = performance.now();
    } catch { audioError = true; }
  }
  function flushAudio() {
    const now = performance.now(), d = currentDrive();
    const active = online && (d.alerts || []).some(a => a.active && !a.acknowledged && a.condition === 'active');
    if (!d.settings?.chime || !active || prefs.chimeVolume === 0 || pendingChime < now) pendingChime = 0;
    if (prefs.chimeVolume === 0 || pendingTest < now) pendingTest = 0;
    if (audio?.state === 'running' && !audioError && (pendingTest || pendingChime && now - lastChime >= 3000)) {
      pendingTest = pendingChime = 0; soundChime();
    }
    audioStatus();
  }
  $('alert-volume').oninput = e => {
    prefs.chimeVolume = Number(e.target.value); saveDisplay(); flushAudio();
  };
  $('test-chime').onclick = () => { pendingTest = performance.now() + 2000; enableAudio(); };
  // Speaker test: left, right, a full-range sweep, or the warning chime, at the chime volume.
  async function speakerTest(kind) {
    if (prefs.chimeVolume === 0) return 'Chime volume is muted (Drive > Alerts). Raise it to hear the test.';
    enableAudio();
    for (let i = 0; i < 20 && audio?.state !== 'running' && !audioError; i++) await new Promise(r => setTimeout(r, 100));
    if (audioError || audio?.state !== 'running') return 'Audio could not start. Check the Linux audio output (see docs/screen-audio.md).';
    if (kind === 'chime') { soundChime(); return 'Playing the warning chime.'; }
    const level = outputLevel(), start = audio.currentTime + .05;
    const length = kind === 'sweep' ? 3 : 1;
    const o = audio.createOscillator(), g = audio.createGain(), pan = audio.createStereoPanner();
    o.type = kind === 'sweep' ? 'sine' : 'triangle';
    if (kind === 'sweep') { o.frequency.setValueAtTime(80, start); o.frequency.exponentialRampToValueAtTime(8000, start + length); }
    else o.frequency.value = kind === 'left' ? 880 : 1320;
    pan.pan.value = kind === 'left' ? -1 : kind === 'right' ? 1 : 0;
    g.gain.setValueAtTime(.0001, start);
    g.gain.exponentialRampToValueAtTime(level, start + .03);
    g.gain.setValueAtTime(level, start + length - .06);
    g.gain.exponentialRampToValueAtTime(.0001, start + length);
    o.connect(g); g.connect(pan); pan.connect(audio.destination);
    o.start(start); o.stop(start + length + .02);
    o.onended = () => { o.disconnect(); g.disconnect(); pan.disconnect(); };
    const mono = audio.destination.maxChannelCount < 2;
    return {left: 'Playing a lower tone on the LEFT speaker only.', right: 'Playing a higher tone on the RIGHT speaker only.',
      sweep: 'Sweeping from 80 Hz to 8 kHz on both speakers. Listen for rattles or dropouts.'}[kind] + (mono ? ' The audio output is mono, so both speakers play everything.' : '');
  }
  window.FrogdashAudio = {speakerTest};
  function unlockAudio() { if (currentDrive().settings?.chime && (!audio || audio.state !== 'running' || audioError)) enableAudio(); }
  document.addEventListener('pointerdown', unlockAudio, {passive: true});
  document.addEventListener('keydown', unlockAudio, {passive: true});
  async function ack(key) {
    if (ackBusy) return; ackBusy = true;
    try {
      if (latest.mode === 'demo') { for (const a of demo.alerts) if (key === 'all' || a.key === key) { a.acknowledged = true; if (!a.active) a.latched = false; } }
      else await request('/drive/ack', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key})});
      $('driver-feedback').textContent = 'Acknowledged. Active conditions remain visible until they recover.';
    } catch (error) { $('driver-feedback').textContent = error.message; }
    finally { ackBusy = false; alertSignature = ''; render(); }
  }
  $('ack-all').onclick = () => ack('all');
  $('bookmark-launch').onclick = async () => {
    if (markBusy || !online) return; markBusy = true; $('bookmark-launch').disabled = true;
    try {
      const event = latest.mode === 'demo' ? demoMark('Driver bookmark') : await request('/drive/mark', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({label: 'Driver bookmark'})});
      $('bookmark-launch').textContent = `Marked #${event.id}`; $('driver-feedback').textContent = `Bookmark #${event.id} saved. Open Drive review to inspect this moment.`;
    } catch (error) { $('bookmark-launch').textContent = 'Mark failed'; $('driver-feedback').textContent = error.message; }
    finally { setTimeout(() => { markBusy = false; $('bookmark-launch').disabled = !online; $('bookmark-launch').textContent = 'Mark log'; }, 1500); }
  };
  document.addEventListener('keydown', e => { if (e.key.toLowerCase() === 'b' && !e.repeat && !e.target.matches('input,select,textarea') && !document.querySelector('dialog[open]')) $('bookmark-launch').click(); });
  // Pi <-> MCP2515 link, judged from the driver handshake rather than bus traffic.
  function canModuleCard(online, health) {
    const m = health.can_module, can = health.can || {};
    const label = 'CAN module link';
    if (!online || !m) return [label, 'Unavailable', 'unknown', 'Needs the Pi'];
    if (!m.present) return [label, 'Not detected', 'warning', 'No SPI answer at boot: check wiring, overlay, oscillator'];
    const traffic = `RX ${can.rx_packets ?? '—'} · TX ${can.tx_packets ?? '—'}`;
    const where = m.spi || 'SPI';
    if (!m.up) return [label, 'Found, interface down', 'warning', `${where} · bring can0 up`];
    if (can.state === 'BUS-OFF') return [label, 'Talking, bus-off', 'warning', `${where} · no node ACKs: check CAN-H/L, termination`];
    return [label, 'Talking to Pi', 'good', `${where} · ${can.state || 'state ?'} · ${can.rx_packets ? traffic : 'bus quiet'}`];
  }
  function renderHealth() {
    const demoMode = latest.mode === 'demo';
    const health = demoMode ? {cpu_c: 51, disk: {free_bytes: 24 * 1073741824}, power: {undervoltage_now: false, undervoltage_since_boot: false, throttled_now: false, throttled_since_boot: false}, can: {state: 'ERROR-ACTIVE', bitrate: 500000, rx_errors: 0, tx_errors: 0, rx_packets: 0, tx_packets: 0}, can_module: {present: true, driver: 'mcp251x', spi: 'spi0.0', up: true, interrupts: 0}, ups: {available: true, battery_percent: 86, battery_volts: 4.05, input_present: true, charging: true, auto_power_on: true}, shutdown: {tracking: true, scope: 'boot', previous: {state: 'saved', ended_ms: Date.now() - 3600000, recording_enabled: true, dropped_samples: 0}}, notes: ['Simulated system health; no Pi hardware is accessed']} : latest.system || {};
    const num = (v, suffix = '') => online && Number.isFinite(v) ? v.toFixed(1) + suffix : 'Unavailable';
    const flag = v => !online || v === undefined ? 'Unavailable' : v ? 'Detected' : 'Clear';
    const hz = demoMode ? 10 : latest.race?.interval ? 1 / latest.race.interval : null;
    const entries = [['Storage free', num(health.disk?.free_bytes == null ? null : health.disk.free_bytes / 1073741824, ' GiB')], ['Pi temperature', num(health.cpu_c, ' °C')], ['Undervoltage now / boot', `${flag(health.power?.undervoltage_now)} / ${flag(health.power?.undervoltage_since_boot)}`], ['Throttling now / boot', `${flag(health.power?.throttled_now)} / ${flag(health.power?.throttled_since_boot)}`], ['USB GPS update rate', demoMode || latest.race?.fresh ? num(hz, ' Hz') : 'No fresh USB fix'], ['CAN RX / TX errors', online ? `${health.can?.rx_errors ?? '—'} / ${health.can?.tx_errors ?? '—'}` : 'Unavailable'], ['Recorder dropped samples', online ? `${latest.recording?.dropped ?? '—'}` : 'Unavailable']];
    const ups = online && health.ups?.available ? health.ups : {};
    const previous = online ? health.shutdown?.previous : null;
    const shutdownState = !online ? 'Unavailable' : !previous ? 'No record' : ({saved: 'Data synced', running: 'Unconfirmed', save_failed: 'Save failed'}[previous.state] || 'Unconfirmed');
    const shutdownQuality = previous?.state === 'saved' ? 'good' : previous ? 'warning' : 'unknown';
    const stamp = Number.isFinite(previous?.ended_ms) ? new Date(previous.ended_ms).toLocaleString() : 'No completed save recorded';
    entries.unshift(canModuleCard(online, health),
      ['UPS battery', num(ups.battery_percent, '%'), Number.isFinite(ups.battery_percent) ? (ups.battery_percent <= 15 ? 'warning' : 'good') : 'unknown', `${num(ups.battery_volts, ' V')} \u00b7 ${ups.charging === true ? 'Charging' : ups.charging === false ? 'Not charging' : 'Charge state unavailable'}`],
      ['UPS input power', ups.input_present === true ? 'External power' : ups.input_present === false ? 'On battery' : 'Unavailable', ups.input_present === true ? 'good' : ups.input_present === false ? 'warning' : 'unknown', health.ups?.dry_run ? 'Observer only; shutdown disabled' : ups.state === 'shutdown_failed' ? 'Shutdown request failed' : ups.state === 'shutdown_requested' ? 'Linux shutdown requested' : ups.input_present === false ? 'Input-loss shutdown policy active' : 'PiSugar 3 Plus'],
      ['Startup on power return', ups.auto_power_on === true ? 'Enabled' : ups.auto_power_on === false ? 'Disabled' : 'Unavailable', ups.auto_power_on === true ? 'good' : ups.auto_power_on === false ? 'warning' : 'unknown', 'After UPS output turns off'],
      ['Previous shutdown', shutdownState, shutdownQuality, previous?.state === 'saved' ? stamp : 'Completion cannot be confirmed']
    );
    $('health-cards').replaceChildren(...entries.map(([label, text, quality, detail]) => {
      const card = el('div', undefined, 'setting-card');
      if (quality) card.dataset.quality = quality;
      card.append(el('span', label), el('strong', text));
      if (detail) card.append(el('small', detail));
      return card;
    }));
    const shutdownNotes = [];
    if (previous?.state === 'saved') {
      shutdownNotes.push('Previous ' + (health.shutdown?.scope === 'service' ? 'service run' : 'boot') + ': the dash saved and synced its data before exiting.');
      if (previous.recording_enabled === false) shutdownNotes.push('MLG recording was disabled.');
      if (previous.recording_enabled && previous.log_rows === 0) shutdownNotes.push('No MLG rows were recorded.');
      if (previous.dropped_samples) shutdownNotes.push(`${previous.dropped_samples} recording samples were dropped during that run.`);
    } else if (previous?.state === 'save_failed') {
      shutdownNotes.push('The previous service exit reported a storage error.');
      if (Array.isArray(previous.errors)) shutdownNotes.push(previous.errors.join(' '));
    } else if (previous) shutdownNotes.push('No completed cleanup record: possible power loss, service crash or interrupted shutdown.');
    else shutdownNotes.push('No previous shutdown evidence yet; a completed run is needed.');
    if (previous?.interruptions) shutdownNotes.push(`${previous.interruptions} earlier service interruption(s) in that boot.`);
    shutdownNotes.push('This confirms application saves, not SD-card health or physical UPS cutoff.');
    if (health.shutdown?.error) shutdownNotes.push(health.shutdown.error);
    if (online && health.shutdown?.tracking === false) shutdownNotes.push('Current shutdown tracking is unavailable.');
    $('health-shutdown-note').textContent = (demoMode ? 'SIMULATED \u00b7 ' : '') + shutdownNotes.join(' ');
    $('health-detail').textContent = `${demoMode ? 'SIMULATED · ' : ''}CAN bitrate ${health.can?.bitrate ?? '—'} bit/s · received error frames ${latest.can_errors?.frames ?? 0} · bus-off events ${latest.can_errors?.bus_off ?? 0} · restarts ${latest.can_errors?.restarts ?? 0} · ${latest.recording?.state || 'recording unavailable'}`;
    $('health-notes').textContent = [!online ? 'Dashboard connection lost; values unavailable.' : 'System diagnostics refresh every five seconds.', ...(health.ups?.error ? ['UPS: ' + health.ups.error] : []), ...(health.notes || [])].join(' ');
  }
  function render() {
    renderDisplay();
    const d = currentDrive();
    if (!loadedSettings && latest.drive?.settings || !loadedSettings && latest.mode === 'demo') { formSettings(d.settings); loadedSettings = true; }
    const alerts = (d.alerts || []).filter(a => a.active || a.latched);
    $('alert-count').textContent = alerts.filter(a => !a.acknowledged).length;
    $('alerts-launch').dataset.warning = alerts.length > 0;
    $('bookmark-launch').disabled = !online || markBusy;
    $('ack-all').disabled = !online || ackBusy || !alerts.some(a => !a.acknowledged);
    const signature = JSON.stringify(alerts);
    if (signature !== alertSignature) {
      alertSignature = signature; $('driver-alerts').replaceChildren(...alerts.map(a => {
        const card = el('div', undefined, 'driver-alert-row'), info = el('button', `${a.title} · ${a.condition === 'unknown' ? 'SIGNAL LOST' : a.active ? 'ACTIVE' : 'RECOVERED'}${a.acknowledged ? ' · ACK' : ''}`); info.type = 'button';
        info.onclick = () => { const shown = v => v.quality !== 'live' ? v.quality : typeof v.value === 'number' && !Number.isInteger(v.value) ? v.value.toFixed(1) : v.value; const flags = a.context?.['meth.fault_flags']; $('alert-capture').textContent = (a.key === 'meth' && flags?.quality === 'live' && flags.value ? window.FrogdashMethFault(flags.value) + ' — ' : '') + Object.entries(a.context || {}).map(([k, v]) => `${k}: ${shown(v)}`).join(' · '); };
        const acknowledge = el('button', 'ACK'); acknowledge.type = 'button'; acknowledge.disabled = a.acknowledged; acknowledge.onclick = () => ack(a.key); card.append(info, acknowledge); return card;
      }));
      if (!alerts.length) $('driver-alerts').append(el('p', 'No active or unacknowledged alerts.', 'control-note'));
    }
    if (online && Number.isFinite(d.alert_seq)) {
      if ((seenAlerts === null || d.alert_seq > seenAlerts) && d.settings?.chime) pendingChime = performance.now() + 5000;
      seenAlerts = d.alert_seq;
      if (d.settings?.chime && !audioAttempted) enableAudio();
    }
    flushAudio();
    $('drive-summary').textContent = `${latest.mode === 'demo' ? 'DEMO · ' : ''}${d.current ? `Recording drive · ${Math.round(d.current.duration_s)} s · ${d.current.event_count} events` : 'Display preferences, advisory alerts and recorded sessions'}`;
    if (d.error) $('driver-feedback').textContent = d.error;
    if ($('drive-dialog').open && !document.querySelector('[data-driver-panel="health"]').hidden) renderHealth();
  }
  window.addEventListener('frogdash-state', e => { latest = e.detail.snapshot; online = e.detail.connected; if (latest.mode === 'demo') { simulateAlerts(); latest.drive = demo; } render(); });
  selectTab('display'); render();
})();
