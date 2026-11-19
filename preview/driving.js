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
    // Intake air each side of the water/meth nozzle (controller thermistors) and the difference.
    airpre: ['Air before inj', 'meth.pre_temp_c', '°F', 0, 300, 0, n => n * 1.8 + 32],
    airpost: ['Air after inj', 'meth.post_temp_c', '°F', 0, 300, 0, n => n * 1.8 + 32],
    aircool: ['Inj cooling', 'meth.temp_drop_c', 'Δ°F', 0, 100, 0, n => n * 1.8],
    knock: ['Knock energy', 'knock.energy', '', 0, 255, 0],
    tripa: ['Trip A', 'trip.a_km', 'mi', 0, 500, 1, n => n / 1.609344],
    tripb: ['Trip B', 'trip.b_km', 'mi', 0, 500, 1, n => n / 1.609344],
    range: ['Est. range', 'fuel.range_km', 'mi', 0, 400, 0, n => n / 1.609344],
    economy: ['Est. economy', 'fuel.instant_mpg', 'US MPG', 0, 60, 1],
    average: ['Avg. economy', 'fuel.average_mpg', 'US MPG', 0, 60, 1],
    lastlap: ['Last lap', '@last', 's', 0, 180, 2], bestlap: ['Best lap', '@best', 's', 0, 180, 2]
  };
  // Gauges of the owner's own (the screen editor): any reading the dash has, named, with its
  // range and decimals. Values are kept in the reading's own units (°C, kPa, psi, km/h) and
  // shown in the display's (Display modes > Units): the kind comes from the reading's name.
  const UNIT_KINDS = [['_c', 'temp'], ['_kpa', 'kpa'], ['_psi', 'psi'], ['_kph', 'speed'], ['_km', 'distance']];
  const same = n => n;
  const KINDS = {
    temp: {us: ['°F', c => c * 1.8 + 32, f => (f - 32) / 1.8], metric: ['°C', same, same]},
    kpa: {us: ['psi', k => k * .145037738, p => p / .145037738], metric: ['kPa', same, same]},
    psi: {us: ['psi', same, same], metric: ['kPa', p => p * 6.894757293, k => k / 6.894757293]},
    speed: {us: ['mph', k => k / 1.609344, m => m * 1.609344], metric: ['km/h', same, same]},
    distance: {us: ['mi', k => k / 1.609344, m => m * 1.609344], metric: ['km', same, same]},
  };
  const kindOf = signal => UNIT_KINDS.find(([end]) => signal.endsWith(end))?.[1] || null;
  const system = () => window.FrogdashUnits?.metric ? 'metric' : 'us';
  // [unit, raw → shown, shown → raw] for a reading, or its own unit label.
  const shownAs = (signal, unit = '') => { const k = kindOf(signal); return k ? KINDS[k][system()] : [unit, same, same]; };
  const CUSTOM_KEY = /^my\d{1,3}$/, SIGNAL_KEY = /^[a-z][a-z0-9_]{0,30}\.[a-z0-9_.]{1,60}$/;
  const finite = n => typeof n === 'number' && Number.isFinite(n);
  function cleanCustom(c) {
    if (!c || typeof c !== 'object' || !SIGNAL_KEY.test(c.signal) || typeof c.title !== 'string') return null;
    if (!finite(c.min) || !finite(c.max) || c.max <= c.min || ![0, 1, 2, 3].includes(c.digits)) return null;
    return {signal: c.signal, title: c.title.slice(0, 24) || c.signal, unit: typeof c.unit === 'string' ? c.unit.slice(0, 8) : '', min: c.min, max: c.max, digits: c.digits};
  }
  function cleanZone(z) {
    if (!z || typeof z !== 'object') return null;
    const out = {};
    for (const side of ['low', 'high']) if (finite(z[side])) out[side] = z[side];
    if (!('low' in out) && !('high' in out)) return null;
    return 'low' in out && 'high' in out && out.low >= out.high ? null : out;
  }
  const layouts = {street: ['coolant', 'oil', 'fuelp', 'iat', 'batt', 'fuel'], tuning: ['afr', 'target', 'boost', 'fuelp', 'meth', 'tank'], track: ['coolant', 'oil', 'iat', 'boost', 'lastlap', 'bestlap']};
  let prefs = {layout: 'street', layouts: structuredClone(layouts), lighting: 'auto', day: 100, night: 85, nightAccent: '#ffc77d', shift: 5800, chimeVolume: 50, custom: {}, zones: {}};
  // A custom gauge in the picker's list: its name, reading and unit as defined.
  const register = (key, c) => { metricDefs[key] = [c.title, c.signal, shownAs(c.signal, c.unit)[0], c.min, c.max, c.digits]; };
  try {
    const p = JSON.parse(localStorage.getItem('frogdash.driving.v1'));
    if (p && typeof p === 'object') {
      for (const [key, c] of Object.entries(p.custom || {})) { const clean = CUSTOM_KEY.test(key) && cleanCustom(c); if (clean) { prefs.custom[key] = clean; register(key, clean); } }
      for (const [key, z] of Object.entries(p.zones || {})) { const clean = Object.hasOwn(metricDefs, key) && cleanZone(z); if (clean) prefs.zones[key] = clean; }
      if (Object.hasOwn(layouts, p.layout)) prefs.layout = p.layout;
      if (['auto', 'day', 'night'].includes(p.lighting)) prefs.lighting = p.lighting;
      for (const key of ['street', 'tuning', 'track']) if (Array.isArray(p.layouts?.[key]) && p.layouts[key].length === 6 && p.layouts[key].every(k => Object.hasOwn(metricDefs, k))) prefs.layouts[key] = p.layouts[key];
      for (const [key, lo, hi] of [['day', 35, 100], ['night', 20, 100], ['shift', 2000, 9000], ['chimeVolume', 0, 100]]) if (Number.isFinite(p[key]) && p[key] >= lo && p[key] <= hi) prefs[key] = p[key];
      if (/^#[0-9a-f]{6}$/i.test(p.nightAccent)) prefs.nightAccent = p.nightAccent;
      // At night the gauges now light up (they glow, the panels go dark), so the old default
      // of 55 % for the whole screen only dulled them: a dash still on it moves to 85 %.
      if (p.nightSet === true) prefs.nightSet = true;
      else if (p.night === 55) prefs.night = 85;
    }
  } catch { /* Use defaults when browser storage is unavailable. */ }
  let latest = {values: {}}, online = false, ackBusy = false, markBusy = false;
  let audio, audioAttempted = false, audioError = false, lastChime = -Infinity, seenAlerts = null, pendingChime = 0, pendingTest = 0;
  const get = key => online && latest.values?.[key]?.quality === 'live' ? latest.values[key].value : null;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  // One reading for any metric, in display units, with the same quality rules everywhere.
  function definition(key) {
    const c = prefs.custom[key];
    if (!c) return window.FrogdashUnits.definition(metricDefs[key]);
    const [unit, show] = shownAs(c.signal, c.unit);
    return [c.title, c.signal, unit, +show(c.min).toFixed(c.digits), +show(c.max).toFixed(c.digits), c.digits, show];
  }
  function read(key, snapshot = latest, connected = online) {
    if (!Object.hasOwn(metricDefs, key)) key = 'coolant';     // A gauge deleted while shown
    const [title, signal, unit, min, max, digits, convert] = definition(key);
    const race = (snapshot.mode === 'demo' ? window.frogdashRaceView : snapshot.race) || {};
    const live = connected && snapshot.values?.[signal]?.quality === 'live' ? snapshot.values[signal].value : null;
    const raw = !connected ? null : signal === '@last' ? race.laps?.at(-1)?.seconds : signal === '@best' ? race.best_lap : live;
    const v = Number.isFinite(raw) ? (convert ? convert(raw) : raw) : null, value = Number.isFinite(v) ? v : null;
    const quality = value !== null ? 'live' : !connected ? 'stale' : snapshot.values?.[signal]?.quality || 'unavailable';
    const label = value !== null ? signal.startsWith('fuel.') ? 'Estimated' : signal.startsWith('trip.') ? 'Tracked' : 'Live' : !connected ? 'Stale' : snapshot.values?.[signal]?.quality || 'No signal';
    // Warning zones, kept in the reading's own units: outside them the gauge turns red.
    const zone = prefs.zones[key], show = convert || same, at = n => Math.max(0, Math.min(1, (show(n) - min) / (max - min)));
    const tone = zone && Number.isFinite(raw) ? (raw < zone.low ? 'low' : raw > zone.high ? 'high' : null) : null;
    return {key, title, signal, unit, min, max, digits, value, quality, label, tone, custom: Object.hasOwn(prefs.custom, key),
      zones: zone ? {low: zone.low === undefined ? null : at(zone.low), high: zone.high === undefined ? null : at(zone.high)} : null,
      text: value === null ? '\u2014' : value.toFixed(digits), ratio: value === null ? 0 : Math.max(0, Math.min(1, (value - min) / (max - min)))};
  }
  // Press and hold any [data-gauge-slot] element; its owner listens for 'gauge-hold'.
  const picker = el('dialog', undefined, 'workspace-dialog gauge-picker'); picker.id = 'gauge-picker'; picker.setAttribute('aria-labelledby', 'gauge-picker-title');
  picker.innerHTML = '<header class="dialog-header"><div><span class="eyebrow">PRESS AND HOLD ANY GAUGE</span><h2 id="gauge-picker-title">Change gauge</h2><p id="gauge-picker-note"></p></div><button id="gauge-picker-new" class="gauge-picker-action" type="button">+ New gauge</button><button id="gauge-picker-edit" class="gauge-picker-action" type="button">Edit this gauge</button><button id="gauge-picker-default" type="button">Restore default</button><button id="gauge-picker-close" class="close-button" type="button">Close <span aria-hidden="true">\u00d7</span></button></header><div id="gauge-picker-options" class="gauge-picker-options" role="group" aria-label="Readings"></div>';
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
  function buildOptions() {
    $('gauge-picker-options').replaceChildren();
    for (const key of Object.keys(metricDefs)) {
      const button = el('button'); button.type = 'button'; button.dataset.metric = key;
      if (Object.hasOwn(prefs.custom, key)) button.dataset.custom = 'true';
      button.append(el('strong', metricDefs[key][0]), el('small'));
      button.onclick = () => { const request = pickRequest; picker.close(); request?.onPick(key); };
      $('gauge-picker-options').append(button);
    }
  }
  buildOptions();
  $('gauge-picker-close').onclick = () => picker.close();
  $('gauge-picker-new').onclick = () => { const request = pickRequest; picker.close(); editGauge(null, request); };
  $('gauge-picker-edit').onclick = () => { const request = pickRequest; picker.close(); editGauge(request.current, request); };
  $('gauge-picker-default').onclick = () => { const request = pickRequest; picker.close(); request?.onPick(request.fallback); };
  picker.addEventListener('close', () => { pickRequest = null; });
  function pick(request) {
    pickRequest = request;
    $('gauge-picker-title').textContent = `Change ${request.title}`;
    $('gauge-picker-note').textContent = `Default: ${metricDefs[request.fallback][0]}. Speed and RPM stay fixed. Edit sets its warning zones; New makes a gauge for any reading.`;
    $('gauge-picker-edit').hidden = !Object.hasOwn(metricDefs, request.current) || metricDefs[request.current][1].startsWith('@');
    if (!picker.open) picker.showModal();
    renderPicker();
  }
  // The screen editor: a gauge for any reading, or the warning zones of one already there.
  const editor = el('dialog', undefined, 'workspace-dialog gauge-editor'); editor.id = 'gauge-editor'; editor.setAttribute('aria-labelledby', 'gauge-editor-title');
  editor.innerHTML = `<header class="dialog-header"><div><span class="eyebrow">SCREEN EDITOR</span><h2 id="gauge-editor-title">New gauge</h2><p id="gauge-editor-note"></p></div>
    <button id="gauge-editor-close" class="close-button" type="button">Cancel <span aria-hidden="true">×</span></button></header>
    <div class="gauge-editor-body">
      <div class="gauge-editor-readings" id="gauge-editor-readings-box"><label for="gauge-editor-filter">Reading</label><input id="gauge-editor-filter" type="search" placeholder="Find a reading" autocomplete="off">
        <div id="gauge-editor-readings" class="gauge-editor-readings-list" role="listbox" aria-label="Readings the dash has now"></div></div>
      <div class="gauge-editor-form">
        <div class="gauge-editor-preview"><span id="gauge-editor-signal">—</span><strong id="gauge-editor-now">—</strong><div class="track"><div class="fill" id="gauge-editor-fill"></div><i class="zone zone-low" id="gauge-editor-zlow"></i><i class="zone zone-high" id="gauge-editor-zhigh"></i></div></div>
        <div class="gauge-editor-fields">
          <label class="ge-custom">Name <input id="gauge-editor-name" maxlength="24" autocomplete="off"></label>
          <label class="ge-custom ge-unit">Unit <input id="gauge-editor-unit" maxlength="8" autocomplete="off" placeholder="bar, %, V…"></label>
          <label class="ge-custom">Lowest shown <input id="gauge-editor-min" type="number" step="any"></label>
          <label class="ge-custom">Highest shown <input id="gauge-editor-max" type="number" step="any"></label>
          <label class="ge-custom">Decimals <select id="gauge-editor-digits"><option value="0">0</option><option value="1">1</option><option value="2">2</option><option value="3">3</option></select></label>
          <label>Warn below <input id="gauge-editor-low" type="number" step="any" placeholder="No limit"></label>
          <label>Warn above <input id="gauge-editor-high" type="number" step="any" placeholder="No limit"></label>
        </div>
        <p id="gauge-editor-problem" class="gauge-editor-problem" role="alert"></p>
        <div class="gauge-editor-buttons"><button id="gauge-editor-delete" type="button">Delete gauge</button><button id="gauge-editor-save" class="primary" type="button">Save</button></div>
      </div>
    </div>`;
  document.body.append(editor);
  let editing = null;      // {key: null for a new gauge, request, signal}
  // A reading's name: a built-in gauge's where one shows it, else made from its key.
  const ACRONYMS = new Set(['afr', 'iat', 'rpm', 'map', 'tps', 'egt', 'ego', 'mpg', 'gps', 'vss', 'clt', 'ecu', 'pw', 've', 'mat', 'iac']);
  function humanize(key) {
    const known = Object.entries(metricDefs).find(([k, d]) => !Object.hasOwn(prefs.custom, k) && d[1] === key);
    if (known) return known[1][0];
    const words = key.split('.').slice(1).join(' ').replace(/_/g, ' ').replace(/ (c|kpa|psi|kph|km|pct|v|deg|ms)$/i, '').trim().split(' ');
    const text = words.map(w => ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w).join(' ');
    return text ? text[0].toUpperCase() + text.slice(1) : key;
  }
  const numberIn = id => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
  const fmt = (n, digits = 2) => n === null || n === undefined ? '' : String(+n.toFixed(digits));
  // Every reading the dash has a number for now (and the one being edited), grouped by source.
  function readingKeys() {
    const keys = Object.entries(latest.values || {}).filter(([, v]) => typeof v?.value === 'number' || v?.value === null).map(([k]) => k);
    if (editing?.signal && !keys.includes(editing.signal)) keys.push(editing.signal);
    return keys.filter(k => SIGNAL_KEY.test(k)).sort();
  }
  function renderReadings() {
    const list = $('gauge-editor-readings'), filter = $('gauge-editor-filter').value.trim().toLowerCase();
    const keys = readingKeys().filter(k => !filter || k.includes(filter) || humanize(k).toLowerCase().includes(filter));
    const sig = keys.join('|') + '#' + editing?.signal;
    if (list.dataset.keys !== sig) {
      list.dataset.keys = sig; list.replaceChildren();
      for (const key of keys) {
        const button = el('button'); button.type = 'button'; button.dataset.reading = key; button.setAttribute('role', 'option');
        button.append(el('strong', humanize(key)), el('code', key), el('small'));
        button.onclick = () => chooseReading(key);
        list.append(button);
      }
    }
    for (const button of list.children) {
      const v = latest.values?.[button.dataset.reading], [unit, show] = shownAs(button.dataset.reading);
      button.setAttribute('aria-selected', String(button.dataset.reading === editing?.signal));
      button.querySelector('small').textContent = v?.quality === 'live' && finite(v.value) ? `${+show(v.value).toFixed(2)} ${unit}`.trim() : v?.quality || 'no signal';
    }
  }
  function chooseReading(key) {
    const before = editing.signal; editing.signal = key;
    if (!$('gauge-editor-name').value || $('gauge-editor-name').value === humanize(before || '')) $('gauge-editor-name').value = humanize(key);
    $('gauge-editor-unit').closest('label').hidden = !!kindOf(key);
    if ($('gauge-editor-min').value === '' && $('gauge-editor-max').value === '') {
      const v = latest.values?.[key]?.value, [, show] = shownAs(key), now = finite(v) ? show(v) : null;
      // A round top about half again above what it reads now: 205 °F gives 400.
      const top = now === null || now <= 0 ? 100 : now * 1.5, step = Math.pow(10, Math.floor(Math.log10(top)));
      $('gauge-editor-min').value = 0; $('gauge-editor-max').value = fmt(Math.ceil(top / step) * step, 3);
    }
    renderReadings(); renderEditor();
  }
  // What the form says now, in the reading's own units; or a problem to show.
  function formGauge() {
    const signal = editing.signal, [, , back] = shownAs(signal || '');
    if (!signal) return {problem: 'Pick the reading this gauge shows.'};
    const custom = editing.key === null || Object.hasOwn(prefs.custom, editing.key);
    const low = numberIn('gauge-editor-low'), high = numberIn('gauge-editor-high');
    if ([low, high].some(n => n !== null && !Number.isFinite(n))) return {problem: 'The warning limits should be numbers.'};
    if (low !== null && high !== null && low >= high) return {problem: 'Warn below should be lower than warn above.'};
    const zone = cleanZone({low: low === null ? undefined : back(low), high: high === null ? undefined : back(high)});
    if (!custom) return {zone};
    const min = numberIn('gauge-editor-min'), max = numberIn('gauge-editor-max');
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return {problem: 'Highest shown should be above lowest shown.'};
    const gauge = cleanCustom({signal, title: $('gauge-editor-name').value.trim() || humanize(signal), unit: $('gauge-editor-unit').value.trim(),
      min: back(min), max: back(max), digits: Number($('gauge-editor-digits').value)});
    return gauge ? {gauge, zone} : {problem: 'Check the name and the range.'};
  }
  function renderEditor() {
    if (!editor.open || !editing) return;
    renderReadings();
    const form = formGauge(), signal = editing.signal;
    $('gauge-editor-problem').textContent = form.problem && signal ? form.problem : '';
    $('gauge-editor-save').disabled = !!form.problem;
    const [unit, show] = shownAs(signal || '', $('gauge-editor-unit').value.trim());
    const v = signal ? latest.values?.[signal] : null, live = v?.quality === 'live' && finite(v.value) ? v.value : null;
    $('gauge-editor-signal').textContent = signal || 'No reading picked';
    const digits = Number($('gauge-editor-digits').value) || 0;
    const zone = form.zone, tone = zone && live !== null ? (live < zone.low ? 'low' : live > zone.high ? 'high' : null) : null;
    $('gauge-editor-now').textContent = live === null ? (v?.quality || '—') : `${show(live).toFixed(editing.key && !Object.hasOwn(prefs.custom, editing.key) ? read(editing.key).digits : digits)} ${unit}${tone ? tone === 'low' ? ' · LOW' : ' · HIGH' : ''}`;
    editor.querySelector('.gauge-editor-preview').dataset.tone = tone ? 'danger' : 'normal';
    const [min, max] = form.gauge ? [show(form.gauge.min), show(form.gauge.max)] : editing.key ? [read(editing.key).min, read(editing.key).max] : [0, 100];
    const at = n => Math.max(0, Math.min(100, (show(n) - min) / (max - min) * 100));
    $('gauge-editor-fill').style.width = live === null ? '0%' : `${at(live)}%`;
    $('gauge-editor-zlow').hidden = zone?.low === undefined; $('gauge-editor-zhigh').hidden = zone?.high === undefined;
    if (zone?.low !== undefined) $('gauge-editor-zlow').style.width = `${at(zone.low)}%`;
    if (zone?.high !== undefined) $('gauge-editor-zhigh').style.left = `${at(zone.high)}%`;
  }
  // key null: a new gauge (put in the slot asked from, if any); otherwise that gauge.
  function editGauge(key, request = null) {
    const custom = key !== null && Object.hasOwn(prefs.custom, key);
    const def = key === null ? null : custom ? prefs.custom[key] : {signal: metricDefs[key][1]};
    editing = {key, request, signal: def?.signal || null};
    $('gauge-editor-title').textContent = key === null ? 'New gauge' : `Edit ${metricDefs[key][0]}`;
    $('gauge-editor-note').textContent = key === null ? 'Any reading the dash has, from the ECU, the car signals or the sensors. It goes where you held.'
      : custom ? 'Its reading, name, range and warning zones.' : 'Its warning zones: outside them the gauge turns red. For another range, make a new gauge on the same reading.';
    editor.dataset.kind = key === null || custom ? 'custom' : 'zones';
    $('gauge-editor-readings-box').hidden = !(key === null || custom);
    $('gauge-editor-delete').hidden = !custom;
    const [, show] = shownAs(editing.signal || '', def?.unit || '');
    $('gauge-editor-name').value = custom ? def.title : '';
    $('gauge-editor-unit').value = custom ? def.unit : '';
    $('gauge-editor-unit').closest('label').hidden = !!(editing.signal && kindOf(editing.signal));
    $('gauge-editor-min').value = custom ? fmt(show(def.min)) : '';
    $('gauge-editor-max').value = custom ? fmt(show(def.max)) : '';
    $('gauge-editor-digits').value = String(custom ? def.digits : 0);
    const zone = key === null ? null : prefs.zones[key];
    $('gauge-editor-low').value = zone?.low === undefined ? '' : fmt(show(zone.low));
    $('gauge-editor-high').value = zone?.high === undefined ? '' : fmt(show(zone.high));
    $('gauge-editor-filter').value = '';
    delete $('gauge-editor-readings').dataset.keys;
    if (!editor.open) editor.showModal();
    renderEditor();
  }
  for (const id of ['gauge-editor-name', 'gauge-editor-unit', 'gauge-editor-min', 'gauge-editor-max', 'gauge-editor-low', 'gauge-editor-high', 'gauge-editor-digits', 'gauge-editor-filter'])
    $(id).addEventListener('input', renderEditor);
  $('gauge-editor-digits').addEventListener('change', renderEditor);
  $('gauge-editor-close').onclick = () => editor.close();
  editor.addEventListener('close', () => { editing = null; window.FrogdashKeyboard?.close?.(); });
  $('gauge-editor-save').onclick = () => {
    const form = formGauge();
    if (form.problem || !editing) return;
    let key = editing.key;
    if (form.gauge) {
      if (key === null) { let n = 1; while (Object.hasOwn(prefs.custom, `my${n}`)) n++; key = `my${n}`; }
      prefs.custom[key] = form.gauge; register(key, form.gauge);
    }
    if (form.zone) prefs.zones[key] = form.zone; else delete prefs.zones[key];
    const request = editing.key === null ? editing.request : null;
    editor.close();
    buildOptions(); buildSlotChoices();
    if (request) request.onPick(key); else saveDisplay();
  };
  $('gauge-editor-delete').onclick = () => {
    const key = editing?.key;
    if (!key || !Object.hasOwn(prefs.custom, key)) return;
    delete prefs.custom[key]; delete prefs.zones[key]; delete metricDefs[key];
    for (const name of Object.keys(prefs.layouts)) prefs.layouts[name] = prefs.layouts[name].map((k, i) => k === key ? layouts[name][i] : k);
    editor.close(); buildOptions(); buildSlotChoices(); saveDisplay();
  };
  window.FrogdashMetrics = {defs: metricDefs, read, pick, edit: editGauge, name: humanize};
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
    const track = el('div', undefined, 'track'), fill = el('div', undefined, 'fill'), zlow = el('i', undefined, 'zone zone-low'), zhigh = el('i', undefined, 'zone zone-high'); track.append(fill, zlow, zhigh);
    const scale = el('div', undefined, 'scale-labels'), lo = el('span'), hi = el('span'); scale.append(lo, hi); card.append(heading, readout, track, scale); row.append(card);
    tiles.push({card, title, quality, value, unit, fill, lo, hi, zlow, zhigh});
    const native = document.querySelectorAll('.sensor-row:not(.profile-sensors) .sensor-card')[i];
    for (const target of [card, native].filter(Boolean)) {
      target.dataset.gaugeSlot = `sensor-${i}`;
      target.addEventListener('gauge-hold', () => pick({title: `position ${i + 1}`, current: prefs.layouts[prefs.layout][i], fallback: layouts[prefs.layout][i], onPick: key => { prefs.layouts[prefs.layout][i] = key; saveDisplay(); }}));
    }
    const label = el('label', `Position ${i + 1}`), select = el('select'); select.id = `layout-slot-${i}`;
    select.onchange = () => { prefs.layouts[prefs.layout][i] = select.value; saveDisplay(); };
    label.append(select); $('layout-instruments').append(label);
  }
  function buildSlotChoices() {
    for (let i = 0; i < 6; i++) {
      const select = $(`layout-slot-${i}`);
      select.replaceChildren(...Object.entries(metricDefs).map(([key, [name]]) => { const option = el('option', name); option.value = key; return option; }));
    }
  }
  buildSlotChoices();
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
    window.dispatchEvent(new Event('frogdash-gauges-changed'));
  }
  for (const b of document.querySelectorAll('button[data-layout]')) b.onclick = () => { prefs.layout = b.dataset.layout; saveDisplay(); };
  $('layout-reset').onclick = () => { prefs.layouts[prefs.layout] = [...layouts[prefs.layout]]; saveDisplay(); };
  $('lighting-mode').onchange = e => { prefs.lighting = e.target.value; saveDisplay(); };
  for (const key of ['day', 'night']) $(`${key}-brightness`).oninput = e => { prefs[key] = Number(e.target.value); if (key === 'night') prefs.nightSet = true; saveDisplay(); };
  $('night-accent').onchange = e => { prefs.nightAccent = window.FrogdashAppearance.readableAccent(e.target.value); saveDisplay(); };
  $('shift-rpm').onchange = e => { if (e.target.reportValidity() && e.target.value !== '') { prefs.shift = Number(e.target.value); saveDisplay(); } };
  function renderDisplay() {
    const lights = get('lighting.running');
    const night = prefs.lighting === 'night' || prefs.lighting === 'auto' && lights === true;
    document.documentElement.dataset.lighting = night ? 'night' : 'day';
    document.documentElement.style.setProperty('--display-brightness', (night ? prefs.night : prefs.day) / 100);
    document.documentElement.style.setProperty('--night-accent', prefs.nightAccent);
    $('lighting-status').textContent = `${night ? 'Night' : 'Day'} mode · ${prefs.lighting === 'auto' ? lights === null ? 'running-light signal unavailable; day fallback' : 'following running lights' : 'manual override'}`;
    const native = prefs.layout === 'street' && JSON.stringify(prefs.layouts.street) === JSON.stringify(layouts.street) && !layouts.street.some(k => prefs.zones[k]);
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
      tile.card.dataset.tone = m.tone ? 'danger' : 'normal';
      tile.fill.style.width = `${m.ratio * 100}%`;
      tile.zlow.hidden = m.zones?.low == null; tile.zhigh.hidden = m.zones?.high == null;
      if (m.zones?.low != null) tile.zlow.style.width = `${m.zones.low * 100}%`;
      if (m.zones?.high != null) tile.zhigh.style.left = `${m.zones.high * 100}%`;
    });
    renderPicker();
    renderEditor();
  }
  syncDisplayForm();
  // The alerts themselves, their words and limits: alert-rules.json, shown and set in the
  // Alerts tab by alerts.js (loaded after the gauges). Until then, the settings say only
  // whether chimes are on.
  const defaults = {version: 2, chime: false, rules: {}};
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
  function simulateAlerts() { window.FrogdashAlerts?.simulate(latest, demo); }
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
    if (name === 'logs') {
      // Loaded after the first screens: it starts by itself once it is here. Until then, ask
      // for it now, and say so if it never comes.
      if (window.FrogdashLogView) window.FrogdashLogView.open();
      else {
        window.frogdashLoadLater?.();
        setTimeout(() => {
          if (!window.FrogdashLogView && $('log-viewer')) $('log-viewer').textContent = 'The log viewer did not load: Refresh the page (Ctrl+F5). If it stays, the browser blocked mlgplot.js.';
        }, 20000);
      }
    }
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
  // Settings to the Pi (or the demo): the Alerts tab and the chime switch use this.
  async function saveSettings(settings) {
    if (latest.mode === 'demo') { demo.settings = settings; return demo; }
    const result = await request('/drive/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(settings)});
    latest.drive = result;
    if (result.error) throw new Error(result.error);
    return result;
  }
  $('alert-chime').onchange = async e => {
    const settings = {...structuredClone(currentDrive().settings || defaults), chime: e.target.checked};
    try {
      await saveSettings(settings);
      $('alert-settings-status').textContent = settings.chime ? 'Warning chimes on.' : 'Warning chimes off.';
      if (settings.chime) enableAudio();
    } catch (error) { $('alert-settings-status').textContent = error.message; e.target.checked = !e.target.checked; }
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
    finally { ackBusy = false; render(); }
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
    const chime = !!d.settings?.chime;
    if (document.activeElement !== $('alert-chime') && $('alert-chime').checked !== chime) $('alert-chime').checked = chime;
    const alerts = (d.alerts || []).filter(a => a.active || a.latched);
    $('alert-count').textContent = alerts.filter(a => !a.acknowledged).length;
    $('alerts-launch').dataset.warning = alerts.length > 0;
    $('bookmark-launch').disabled = !online || markBusy;
    $('ack-all').disabled = !online || ackBusy || !alerts.some(a => !a.acknowledged);
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
  // For the Alerts tab (alerts.js): what the dash says, saving, acknowledging, the demo.
  window.FrogdashDrive = {current: currentDrive, save: saveSettings, ack, online: () => online, demo};
  selectTab('display'); render();
})();
