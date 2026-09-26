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
    lastlap: ['Last lap', '@last', 's', 0, 180, 2], bestlap: ['Best lap', '@best', 's', 0, 180, 2]
  };
  const layouts = {street: ['coolant', 'oil', 'fuelp', 'iat', 'batt', 'fuel'], tuning: ['afr', 'target', 'boost', 'fuelp', 'meth', 'tank'], track: ['coolant', 'oil', 'iat', 'boost', 'lastlap', 'bestlap']};
  let prefs = {layout: 'street', layouts: structuredClone(layouts), lighting: 'auto', day: 100, night: 55, nightAccent: '#ffc77d', shift: 5800};
  try {
    const p = JSON.parse(localStorage.getItem('frogdash.driving.v1'));
    if (p && typeof p === 'object') {
      if (Object.hasOwn(layouts, p.layout)) prefs.layout = p.layout;
      if (['auto', 'day', 'night'].includes(p.lighting)) prefs.lighting = p.lighting;
      for (const key of ['street', 'tuning', 'track']) if (Array.isArray(p.layouts?.[key]) && p.layouts[key].length === 6 && p.layouts[key].every(k => Object.hasOwn(metricDefs, k))) prefs.layouts[key] = p.layouts[key];
      for (const [key, lo, hi] of [['day', 35, 100], ['night', 20, 100], ['shift', 2000, 9000]]) if (Number.isFinite(p[key]) && p[key] >= lo && p[key] <= hi) prefs[key] = p[key];
      if (/^#[0-9a-f]{6}$/i.test(p.nightAccent)) prefs.nightAccent = p.nightAccent;
    }
  } catch { /* Use defaults when browser storage is unavailable. */ }
  let latest = {values: {}}, online = false, loadedSettings = false, alertSignature = '', ackBusy = false, markBusy = false, audio, lastChime = 0, seenAlerts = null;
  const get = key => online && latest.values?.[key]?.quality === 'live' ? latest.values[key].value : null;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
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
    const label = el('label', `Position ${i + 1}`), select = el('select'); select.id = `layout-slot-${i}`;
    for (const [key, [name]] of Object.entries(metricDefs)) { const option = el('option', name); option.value = key; select.append(option); }
    select.onchange = () => { prefs.layouts[prefs.layout][i] = select.value; saveDisplay(); };
    label.append(select); $('layout-instruments').append(label);
  }
  function syncDisplayForm() {
    prefs.layouts[prefs.layout].forEach((v, i) => { $(`layout-slot-${i}`).value = v; });
    $('lighting-mode').value = prefs.lighting; $('day-brightness').value = prefs.day; $('night-brightness').value = prefs.night;
    $('night-accent').value = prefs.nightAccent; $('shift-rpm').value = prefs.shift;
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
    const race = (latest.mode === 'demo' ? window.frogdashRaceView : latest.race) || {};
    const last = race.laps?.at(-1)?.seconds, best = race.best_lap;
    const lapText = n => Number.isFinite(n) ? `${n.toFixed(2)} s` : '—';
    $('track-last').textContent = lapText(last); $('track-best').textContent = lapText(best);
    $('track-lap-readout').hidden = $('shift-lights').hidden = prefs.layout !== 'track';
    const rpm = get('engine.rpm');
    [...$('shift-lights').children].forEach((light, i) => { light.dataset.on = rpm !== null && rpm >= prefs.shift - (7 - i) * 150; });
    $('shift-lights').dataset.shift = rpm !== null && rpm >= prefs.shift;
    if (!native) prefs.layouts[prefs.layout].forEach((key, i) => {
      const [title, signal, unit, min, max, digits, convert] = metricDefs[key], tile = tiles[i];
      const raw = signal === '@last' ? online ? last : null : signal === '@best' ? online ? best : null : get(signal);
      const valid = Number.isFinite(raw), v = valid ? (convert ? convert(raw) : raw) : null;
      tile.title.textContent = title; tile.unit.textContent = unit; tile.lo.textContent = min; tile.hi.textContent = max;
      tile.value.textContent = valid ? v.toFixed(digits) : '—'; tile.quality.textContent = valid ? 'Live' : online ? latest.values?.[signal]?.quality || 'No signal' : 'Stale';
      tile.card.dataset.quality = valid ? 'live' : !online ? 'stale' : latest.values?.[signal]?.quality || 'unavailable';
      tile.fill.style.width = valid ? `${Math.max(0, Math.min(100, (v - min) / (max - min) * 100))}%` : '0%';
    });
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
    button.onkeydown = e => { const buttons = [...document.querySelectorAll('[data-driver-tab]')], i = buttons.indexOf(button); const n = e.key === 'ArrowDown' ? (i + 1) % 4 : e.key === 'ArrowUp' ? (i + 3) % 4 : e.key === 'Home' ? 0 : e.key === 'End' ? 3 : null; if (n !== null) { e.preventDefault(); buttons[n].click(); buttons[n].focus(); } };
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
      if (settings.chime) await enableAudio();
    } catch (error) { $('alert-settings-status').textContent = error.message; }
    finally { button.disabled = false; }
  };
  async function enableAudio() {
    try { audio ||= new (window.AudioContext || window.webkitAudioContext)(); await audio.resume(); $('audio-status').textContent = audio.state === 'running' ? 'Chime ready on this display.' : 'Audio blocked; tap Test chime.'; }
    catch { $('audio-status').textContent = 'Audio unavailable; visual alerts remain active.'; }
  }
  async function chime(test = false) {
    if (test) await enableAudio();
    if (!audio || audio.state !== 'running' || !test && performance.now() - lastChime < 3000) return;
    lastChime = performance.now();
    for (const delay of [0, .2]) { const o = audio.createOscillator(), g = audio.createGain(), start = audio.currentTime + delay; o.frequency.value = 880; g.gain.setValueAtTime(.0001, start); g.gain.exponentialRampToValueAtTime(.10, start + .015); g.gain.exponentialRampToValueAtTime(.0001, start + .15); o.connect(g); g.connect(audio.destination); o.start(start); o.stop(start + .16); o.onended = () => { o.disconnect(); g.disconnect(); }; }
  }
  $('test-chime').onclick = () => chime(true);
  document.addEventListener('pointerdown', () => { if (currentDrive().settings?.chime && audio?.state !== 'running') enableAudio(); }, {passive: true});
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
  function renderHealth() {
    const demoMode = latest.mode === 'demo';
    const health = demoMode ? {cpu_c: 51, disk: {free_bytes: 24 * 1073741824}, power: {undervoltage_now: false, undervoltage_since_boot: false, throttled_now: false, throttled_since_boot: false}, can: {state: 'ERROR-ACTIVE', bitrate: 500000, rx_errors: 0, tx_errors: 0}, notes: ['Simulated system health; no Pi hardware is accessed']} : latest.system || {};
    const num = (v, suffix = '') => online && Number.isFinite(v) ? v.toFixed(1) + suffix : 'Unavailable';
    const flag = v => !online || v === undefined ? 'Unavailable' : v ? 'Detected' : 'Clear';
    const hz = demoMode ? 10 : latest.race?.interval ? 1 / latest.race.interval : null;
    const entries = [['Storage free', num(health.disk?.free_bytes == null ? null : health.disk.free_bytes / 1073741824, ' GiB')], ['Pi temperature', num(health.cpu_c, ' °C')], ['Undervoltage now / boot', `${flag(health.power?.undervoltage_now)} / ${flag(health.power?.undervoltage_since_boot)}`], ['Throttling now / boot', `${flag(health.power?.throttled_now)} / ${flag(health.power?.throttled_since_boot)}`], ['USB GPS update rate', demoMode || latest.race?.fresh ? num(hz, ' Hz') : 'No fresh USB fix'], ['CAN controller', online ? health.can?.state || 'Unavailable' : 'Disconnected'], ['CAN RX / TX errors', online ? `${health.can?.rx_errors ?? '—'} / ${health.can?.tx_errors ?? '—'}` : 'Unavailable'], ['Recorder dropped samples', online ? `${latest.recording?.dropped ?? '—'}` : 'Unavailable']];
    $('health-cards').replaceChildren(...entries.map(([label, text]) => { const card = el('div', undefined, 'setting-card'); card.append(el('span', label), el('strong', text)); return card; }));
    $('health-detail').textContent = `${demoMode ? 'SIMULATED · ' : ''}CAN bitrate ${health.can?.bitrate ?? '—'} bit/s · received error frames ${latest.can_errors?.frames ?? 0} · bus-off events ${latest.can_errors?.bus_off ?? 0} · restarts ${latest.can_errors?.restarts ?? 0} · ${latest.recording?.state || 'recording unavailable'}`;
    $('health-notes').textContent = [!online ? 'Dashboard connection lost; values unavailable.' : 'System diagnostics refresh every five seconds.', ...(health.notes || [])].join(' ');
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
        info.onclick = () => { $('alert-capture').textContent = Object.entries(a.context || {}).map(([k, v]) => `${k}: ${v.quality === 'live' ? v.value : v.quality}`).join(' · '); };
        const acknowledge = el('button', 'ACK'); acknowledge.type = 'button'; acknowledge.disabled = a.acknowledged; acknowledge.onclick = () => ack(a.key); card.append(info, acknowledge); return card;
      }));
      if (!alerts.length) $('driver-alerts').append(el('p', 'No active or unacknowledged alerts.', 'control-note'));
    }
    if (seenAlerts !== null && d.alert_seq > seenAlerts && d.settings?.chime) chime();
    seenAlerts = d.alert_seq || 0;
    $('drive-summary').textContent = `${latest.mode === 'demo' ? 'DEMO · ' : ''}${d.current ? `Recording drive · ${Math.round(d.current.duration_s)} s · ${d.current.event_count} events` : 'Display preferences, advisory alerts and recorded sessions'}`;
    if (d.error) $('driver-feedback').textContent = d.error;
    if ($('drive-dialog').open && !document.querySelector('[data-driver-panel="health"]').hidden) renderHealth();
  }
  window.addEventListener('frogdash-state', e => { latest = e.detail.snapshot; online = e.detail.connected; if (latest.mode === 'demo') { simulateAlerts(); latest.drive = demo; } render(); });
  selectTab('display'); render();
})();
