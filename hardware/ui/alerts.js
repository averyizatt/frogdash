/* The Alerts tab: every advisory alert as a small widget with its own switch, grouped by
   system. A widget shows its live reading and whether it is going off; pressing it opens
   its details on the right: what it watches, what to check, its limits (in the display's
   units) and how long the condition must last, and the readings from the last time it went
   off. The alerts and their limits are in alert-rules.json, the same file the Pi checks them
   with (hardware/frogdash/alerts.py). In the preview the same rules run here (simulate). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), u = window.FrogdashUnits, drive = window.FrogdashDrive;
  if (!drive) return;
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  let catalogue = null, rules = {}, selected = null, filter = 'all', details = null, detailsAt = 0, saving = false, signature = '';

  // Units: thresholds are stored as the Pi reads them (psi, kPa of boost, °C) and shown in the
  // display's units (Display modes > Units).
  const KINDS = {
    pressure: {unit: () => u.metric ? 'kPa' : 'psi', show: v => u.pressure(v), store: v => u.metric ? v / 6.894757293 : v, digits: () => 0},
    boost: {unit: () => u.metric ? 'kPa' : 'psi', show: v => u.boost(v), store: v => u.metric ? v : v / .145037738, digits: () => u.metric ? 0 : 1},
    temp: {unit: () => u.metric ? '°C' : '°F', show: v => u.temperature(v), store: v => u.metric ? v : (v - 32) / 1.8, digits: () => 0},
    rpm: {unit: () => 'RPM', digits: () => 0}, pct: {unit: () => '%', digits: () => 0}, afr: {unit: () => 'AFR', digits: () => 1},
    // The ECU's fuel correction, 100 % for none: shown as + or − from none.
    trim: {unit: () => '%', digits: () => 0, show: v => v - 100, signed: true},
    volt: {unit: () => 'V', digits: () => 1}, min: {unit: () => 'min', digits: () => 0}, deg: {unit: () => '°', digits: () => 1}, count: {unit: () => '', digits: () => 0},
    text: {unit: () => '', digits: () => 0}, module: {unit: () => '', digits: () => 0},
    // An alert of the owner's own on a reading with no unit the dash knows, and one on a speed.
    plain: {unit: () => '', digits: () => 2},
    speed: {unit: () => u.metric ? 'km/h' : 'mph', show: v => u.metric ? v : v / 1.609344, store: v => u.metric ? v : v * 1.609344, digits: () => 0},
  };
  const kind = name => KINDS[name] || KINDS.count;
  const showValue = (value, name) => {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'boolean') return value ? 'ON' : 'OFF';
    if (typeof value !== 'number') return String(value).toUpperCase();
    const k = kind(name), shown = k.show ? k.show(value) : value;
    const text = shown.toFixed(k.digits());
    return `${k.signed && shown > 0 && Number(text) !== 0 ? '+' : ''}${text}${k.unit() ? ' ' + k.unit() : ''}`;
  };
  const NAMES = {'engine.rpm': 'Engine speed', 'engine.oil_pressure_psi': 'Oil pressure', 'engine.fuel_pressure_psi': 'Fuel pressure',
    'engine.boost_kpa': 'Boost', 'engine.afr': 'Air/fuel ratio', 'ecu.afr_target': 'AFR target', 'engine.coolant_c': 'Coolant',
    'ecu.iat_c': 'Intake air', 'vehicle.battery_v': 'Battery', 'vehicle.fuel_pct': 'Fuel level', 'engine.ego_correction_pct': 'Fuel correction',
    'ecu.knock_retard_deg': 'Knock retard', 'meth.tank_pct': 'Water/meth tank', 'meth.state': 'Water/meth', 'knock.energy': 'Knock level',
    'ecu.sync_loss_count': 'Sync losses', 'lighting.parking_brake': 'Parking brake'};
  const KIND_OF = {'engine.oil_pressure_psi': 'pressure', 'engine.fuel_pressure_psi': 'pressure', 'engine.boost_kpa': 'boost',
    'engine.coolant_c': 'temp', 'ecu.iat_c': 'temp', 'engine.rpm': 'rpm', 'vehicle.fuel_pct': 'pct', 'meth.tank_pct': 'pct',
    'engine.ego_correction_pct': 'trim', 'engine.afr': 'afr', 'ecu.afr_target': 'afr', 'vehicle.battery_v': 'volt', 'ecu.knock_retard_deg': 'deg'};

  // ---- The owner's own alerts (the alert builder): rules like the built-in ones ----
  const CUSTOM_KINDS = [['_c', 'temp'], ['_psi', 'pressure'], ['_kpa', 'boost'], ['_kph', 'speed'], ['_pct', 'pct'], ['_v', 'volt'], ['rpm', 'rpm']];
  const RUNNING_RPM = 400, MAX_CUSTOM = 24, SIGNAL_KEY = /^[a-z][a-z0-9_]{0,30}\.[a-z0-9_.]{1,60}$/;
  const customKind = signal => CUSTOM_KINDS.find(([end]) => signal.endsWith(end))?.[1] || 'plain';
  function customRule(d) {      // alerts.py custom_rule
    const when = [[d.signal, d.op, {param: 'limit'}]];
    if (d.running) when.unshift(['engine.rpm', '>=', RUNNING_RPM]);
    return {key: d.key, code: `USR-${String(Number(d.key.slice(1))).padStart(2, '0')}`, title: d.name.toUpperCase(), name: d.name,
      group: 'custom', severity: d.severity, custom: true,
      about: `${d.signal} ${d.op === '>' ? 'above' : 'below'} the limit${d.running ? ', with the engine running' : ''}. Made in the alert builder.`,
      check: 'Set by you: check what this reading means for your car.',
      show: [d.signal, customKind(d.signal)], enabled: true, delay: 2,
      params: [{key: 'limit', label: d.op === '>' ? 'Above' : 'Below', kind: customKind(d.signal), min: -1e9, max: 1e9, step: 0.001, default: d.limit}], when};
  }
  const allRules = settings => [...catalogue.rules, ...(settings?.custom || []).map(customRule)];
  // A reading's name, as the screen editor gives it (driving.js).
  const humanize = key => window.FrogdashMetrics?.name?.(key) || key;
  // A reading's name in the details: the list's, else the alert's own for the reading it watches.
  const nameOf = (key, rule) => NAMES[key] || (rule?.custom && key === rule.show[0] ? humanize(key) : null);

  // ---- The same rules as the Pi (alerts.py), for the preview's simulated car ----
  const live = (snapshot, key) => { const v = snapshot?.values?.[key]; return v && v.quality === 'live' && v.value !== null && v.value !== undefined ? v.value : null; };
  function term(value, settings, snapshot) {
    if (value === null || typeof value !== 'object') return value;
    if (value.sum) { const parts = value.sum.map(part => term(part, settings, snapshot)); return parts.some(p => p === null) ? null : parts.reduce((a, b) => a + b, 0); }
    const base = 'param' in value ? settings[value.param] : live(snapshot, value.signal);
    return base === null || base === undefined ? null : base * (value.scale ?? 1);
  }
  const OPS = {'<': (a, b) => a < b, '<=': (a, b) => a <= b, '>': (a, b) => a > b, '>=': (a, b) => a >= b, '==': (a, b) => a === b, '!=': (a, b) => a !== b, 'trim>': (a, b) => Math.abs(a - 100) > b};   // 100 % = no correction
  function condition(rule, settings, snapshot) {
    if (!settings.enabled) return false;
    if (rule.special === 'knock') { const w = live(snapshot, 'knock.warning'), c = live(snapshot, 'knock.critical'); return w === null || c === null ? null : !!(w || c); }
    if (rule.special === 'meth') {
      const flags = live(snapshot, 'meth.fault_flags'), mode = live(snapshot, 'meth.state'), flow = live(snapshot, 'meth.flow');
      if (flags || mode === 'FAULT') return true;
      if (flags === null || mode === null) return null;
      return mode !== 'SPRAYING' ? false : !['OK', 'LOW_FLOW', 'NO_FLOW'].includes(flow) ? null : flow !== 'OK';
    }
    if (rule.special?.startsWith('module:')) {
      // As on the Pi: silent while another module is heard (the demo has no bus to check).
      const modules = snapshot?.modules || {}, name = rule.special.slice(7);
      if (!['taillights', 'comfort', 'watermeth'].some(other => other !== name && modules[other] === 'live')) return null;
      return modules[name] !== 'live';
    }
    if (rule.special === 'charging') {   // The preview leaves out the minutes after a start
      const rpm = live(snapshot, 'engine.rpm'), volts = live(snapshot, 'vehicle.battery_v');
      return rpm === null ? null : rpm < 500 ? false : volts === null ? null : volts < settings.v;
    }
    if (rule.special) return null;   // The Pi and ignition sync: only the car has them
    let unknown = false;
    for (const [signal, op, right] of rule.when) {
      const a = live(snapshot, signal), b = term(right, settings, snapshot);
      if (a === null || b === null) { unknown = true; continue; }
      if (!OPS[op](a, b)) return false;
    }
    return unknown ? null : true;
  }
  function reading(rule, snapshot) {
    const [key] = rule.show;
    if (key.startsWith('module:')) return snapshot?.modules?.[key.slice(7)] ?? null;
    if (key === 'pi:cpu_c') return snapshot?.system?.cpu_c ?? null;
    if (key === 'pi:power') return null;
    return live(snapshot, key);
  }
  function defaults(custom = []) {
    const result = {version: 2, chime: false, rules: {}, custom: structuredClone(custom)};
    for (const rule of allRules({custom})) result.rules[rule.key] = {enabled: rule.enabled, delay: rule.delay, ...Object.fromEntries(rule.params.map(p => [p.key, p.default]))};
    return result;
  }
  // The demo (driving.js) keeps its alerts here: the same fields the Pi sends.
  function simulate(snapshot, demo) {
    if (!catalogue) return;
    if (!demo.settings?.rules || !Object.keys(demo.settings.rules).length) demo.settings = {...defaults(demo.settings?.custom || []), chime: !!demo.settings?.chime};
    const now = performance.now();
    const live = allRules(demo.settings);
    demo.alerts = demo.alerts.filter(a => live.some(r => r.key === a.key));
    for (const rule of live) {
      let a = demo.alerts.find(x => x.key === rule.key);
      if (!a) { a = {key: rule.key, code: rule.code, title: rule.title, severity: rule.severity, group: rule.group, active: false, latched: false, acknowledged: false, condition: 'unknown', since_ms: null, context: {}, count: 0, last_ms: null, pending: null}; demo.alerts.push(a); }
      const settings = demo.settings.rules[rule.key], active = condition(rule, settings, snapshot);
      a.value = reading(rule, snapshot);
      a.condition = active === null ? 'unknown' : active ? 'active' : 'normal';
      if (active !== true) { a.pending = null; if (active === false && a.active) { a.active = false; if (a.acknowledged) a.latched = false; } continue; }
      if (a.active) continue;
      a.pending ??= now;
      if (now - a.pending < settings.delay * 1000) continue;
      Object.assign(a, {active: true, latched: true, acknowledged: false, since_ms: Date.now(), last_ms: Date.now(), count: a.count + 1,
        context: Object.fromEntries(Object.entries(snapshot.values || {}).filter(([k]) => NAMES[k]))});
      demo.alert_seq++;
    }
  }

  // ---- The widgets ----
  function stateOf(rule, alert, settings) {
    if (!settings?.enabled) return 'off';
    if (alert?.active) return 'active';
    if (alert?.latched && !alert.acknowledged) return 'latched';
    return alert?.condition === 'unknown' ? 'unknown' : 'normal';
  }
  const STATE_WORDS = {off: 'Off', active: 'Going off', latched: 'Went off', unknown: 'No reading', normal: 'OK'};
  function widget(rule) {
    const card = el('article', undefined, 'alert-widget'); card.dataset.key = rule.key; card.dataset.severity = rule.severity;
    const main = el('button', undefined, 'alert-widget-main'); main.type = 'button';
    const group = catalogue.groups.find(([key]) => key === rule.group)?.[1];
    main.append(el('span', group ? `${rule.code} · ${group}` : rule.code, 'alert-code'), el('strong', rule.name, 'alert-name'), el('span', '—', 'alert-reading'), el('span', '', 'alert-state'));
    main.onclick = () => { selected = rule.key; details = null; renderDetail(); highlight(); loadDetails(); };
    const toggle = el('label', undefined, 'alert-switch'), input = el('input'); input.type = 'checkbox'; input.setAttribute('role', 'switch');
    input.setAttribute('aria-label', `${rule.name}: on or off`);
    input.onchange = () => change(rule.key, {enabled: input.checked}, `${rule.name} ${input.checked ? 'on' : 'off'}.`);
    toggle.append(input, el('span'));
    card.append(main, toggle);
    return card;
  }
  // One grid of every alert, in group order, each card naming its group: a row per group left
  // most of each row empty on the car's wide screen (November 2026).
  function build() {
    const host = $('alert-widgets'); host.replaceChildren();
    const section = el('section', undefined, 'alert-group'), grid = el('div', undefined, 'alert-group-grid');
    for (const [group] of catalogue.groups) for (const rule of Object.values(rules).filter(r => r.group === group)) grid.append(widget(rule));
    section.append(grid);
    host.append(section);
  }
  function closeDetail() {
    const card = document.querySelector(`.alert-widget[data-key="${selected}"] .alert-widget-main`);
    selected = null; details = null;
    delete $('alert-detail').dataset.open;
    highlight();
    card?.focus();
  }
  function highlight() { for (const card of document.querySelectorAll('.alert-widget')) card.classList.toggle('selected', card.dataset.key === selected); }
  let customShown = null;
  function render() {
    if (!catalogue) return;
    const d = drive.current(), settings = d.settings?.rules || {}, alerts = Object.fromEntries((d.alerts || []).map(a => [a.key, a]));
    // An alert of the owner's own added, changed or removed: the cards again.
    const custom = JSON.stringify(d.settings?.custom || []);
    if (custom !== customShown) {
      customShown = custom;
      rules = Object.fromEntries(allRules(d.settings).map(r => [r.key, r]));
      if (selected && !rules[selected]) closeDetail();
      build(); signature = '';
    }
    let going = 0, on = 0;
    for (const card of document.querySelectorAll('.alert-widget')) {
      const rule = rules[card.dataset.key], alert = alerts[rule.key], s = settings[rule.key], state = stateOf(rule, alert, s);
      if (s?.enabled) on++;
      if (state === 'active') going++;
      if (card.dataset.state !== state) card.dataset.state = state;
      const value = showValue(alert?.value ?? null, rule.show[1]);
      const readingNode = card.querySelector('.alert-reading'), stateNode = card.querySelector('.alert-state');
      if (readingNode.textContent !== value) readingNode.textContent = value;
      if (stateNode.textContent !== STATE_WORDS[state]) stateNode.textContent = STATE_WORDS[state];
      const input = card.querySelector('input');
      if (document.activeElement !== input && input.checked !== !!s?.enabled) input.checked = !!s?.enabled;
      input.disabled = saving || !s;
      card.hidden = filter === 'active' ? !['active', 'latched'].includes(state) : filter === 'off' ? state !== 'off' : false;
    }
    for (const section of document.querySelectorAll('.alert-group')) section.hidden = [...section.querySelectorAll('.alert-widget')].every(card => card.hidden);
    const summary = `${going ? `${going} going off · ` : ''}${on} of ${Object.keys(rules).length} alerts on${d.mode === 'demo' || window.FrogdashDrive.demo === d ? ' · simulated' : ''}`;
    if ($('alerts-summary').textContent !== summary) $('alerts-summary').textContent = summary;
    const sig = JSON.stringify([selected, alerts[selected], settings[selected]]);
    if (sig !== signature) { signature = sig; renderDetail(); }
  }

  // ---- The details of one alert ----
  async function loadDetails() {
    if (window.FrogdashDrive.demo === drive.current()) return;   // The demo has them already
    try {
      const response = await fetch('/drive/alerts', {cache: 'no-store', signal: AbortSignal.timeout(4000)});
      if (response.ok) { details = await response.json(); detailsAt = performance.now(); renderDetail(); }
    } catch { /* The live picture still shows; only the last readings are missing. */ }
  }
  function renderDetail() {
    const host = $('alert-detail');
    if (!selected || !rules[selected]) return;
    const rule = rules[selected], d = drive.current(), settings = d.settings?.rules?.[selected];
    const alert = (d.alerts || []).find(a => a.key === selected), full = details?.alerts?.find(a => a.key === selected) || alert;
    if (host.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') { updateLive(rule, alert, settings); return; }
    const state = stateOf(rule, alert, settings);
    host.replaceChildren();
    host.dataset.open = 'true';   // Slides in at the side only once an alert is chosen (no empty panel)
    const head = el('header', undefined, 'alert-detail-head');
    const shut = el('button', 'Close', 'alert-detail-close'); shut.type = 'button'; shut.onclick = closeDetail;
    head.append(shut, el('span', `${rule.code} · ${rule.severity === 'critical' ? 'Critical' : 'Warning'}`, 'alert-code'), el('h3', rule.name), el('span', STATE_WORDS[state], 'alert-detail-state'));
    head.dataset.state = state; head.dataset.severity = rule.severity;
    host.append(head, el('p', rule.about, 'alert-about'), el('p', undefined, 'alert-check'));
    host.lastChild.append(el('b', 'Check: '), document.createTextNode(rule.check));
    // What it watches, now.
    const watched = [...new Set([rule.show[0], ...(rule.when || []).map(clause => clause[0])])].filter(key => nameOf(key, rule));
    const now = el('dl', undefined, 'alert-live'); now.id = 'alert-live';
    for (const key of watched) { const dd = el('dd', '—'); dd.id = `alert-live-${key.replace(/\W/g, '-')}`; dd.dataset.key = key; now.append(el('dt', nameOf(key, rule)), dd); }
    if (watched.length) host.append(el('h4', 'Now'), now);
    // Its limits.
    if (settings) {
      const form = el('form', undefined, 'alert-limits'); form.noValidate = true;
      for (const param of rule.params) {
        const k = kind(param.kind), label = el('label', param.label), input = el('input');
        const shown = k.show ? k.show(settings[param.key]) : settings[param.key];
        Object.assign(input, {type: 'number', step: 'any', value: Number(shown.toFixed(Math.max(k.digits(), param.step < 1 ? 1 : 0))), required: true});
        input.dataset.param = param.key;
        label.append(input, el('span', k.unit(), 'alert-unit'));
        form.append(label);
      }
      const delay = el('label', 'Must last'), input = el('input');
      Object.assign(input, {type: 'number', step: 'any', min: 0, max: 60, value: settings.delay}); input.dataset.param = 'delay';
      delay.append(input, el('span', 's', 'alert-unit')); form.append(delay);
      const row = el('div', undefined, 'control-row'), save = el('button', 'Save limits'), reset = el('button', 'Defaults');
      save.type = 'submit'; reset.type = 'button';
      reset.onclick = () => { const base = defaults().rules[rule.key]; change(rule.key, {...base, enabled: settings.enabled}, `${rule.name}: limits back to their defaults.`); };
      row.append(save, reset);
      if (alert?.latched && !alert.acknowledged) { const ack = el('button', 'Acknowledge'); ack.type = 'button'; ack.onclick = () => drive.ack(rule.key); row.append(ack); }
      if (rule.custom) { const edit = el('button', 'Change'); edit.type = 'button'; edit.onclick = () => openBuilder(rule.key); row.append(edit); }
      form.append(row);
      form.onsubmit = event => { event.preventDefault(); submit(rule, form); };
      host.append(el('h4', 'Limits'), form);
    }
    // The last time it went off.
    const last = full?.last_ms ? new Date(full.last_ms) : null;
    host.append(el('h4', 'History'), el('p', last ? `Last went off ${last.toLocaleString()} · ${full.count || 1} time${(full.count || 1) === 1 ? '' : 's'} since the dash started` : 'Has not gone off since the dash started.', 'alert-history'));
    const context = full?.last_context && Object.keys(full.last_context).length ? full.last_context : full?.context;
    if (context && Object.keys(context).length) {
      const then = el('dl', undefined, 'alert-then');
      for (const [key, sample] of Object.entries(context)) {
        if (!NAMES[key]) continue;
        const value = sample && typeof sample === 'object' && 'value' in sample ? (sample.quality === 'live' ? sample.value : null) : sample;
        then.append(el('dt', NAMES[key]), el('dd', showValue(value, KIND_OF[key] || 'count')));
      }
      if (then.children.length) host.append(el('p', 'The readings when it went off:', 'control-note'), then);
    }
    updateLive(rule, alert, settings);
  }
  function updateLive(rule, alert, settings) {
    const snapshot = window.frogdashLatestSnapshot || {};
    for (const node of document.querySelectorAll('#alert-live dd')) {
      const key = node.dataset.key;
      const value = key === rule.show[0] ? alert?.value ?? live(snapshot, key) : live(snapshot, key);
      const text = showValue(value, KIND_OF[key] || rule.show[1]);
      if (node.textContent !== text) node.textContent = text;
    }
  }
  function submit(rule, form) {
    const changes = {}, problems = [];
    for (const input of form.querySelectorAll('input[data-param]')) {
      const key = input.dataset.param, raw = Number(input.value);
      if (input.value === '' || !Number.isFinite(raw)) { problems.push(`${input.parentElement.firstChild.textContent}: a number`); continue; }
      if (key === 'delay') { if (raw < 0 || raw > 60) problems.push('Must last: 0 to 60 s'); changes.delay = Math.round(raw * 10) / 10; continue; }
      const param = rule.params.find(p => p.key === key), k = kind(param.kind);
      let stored = k.store ? k.store(raw) : raw;
      stored = Math.round(stored / param.step) * param.step;
      stored = Number(stored.toFixed(4));
      if (stored < param.min || stored > param.max) {
        const lo = k.show ? k.show(param.min) : param.min, hi = k.show ? k.show(param.max) : param.max;
        problems.push(`${param.label}: ${lo.toFixed(k.digits())} to ${hi.toFixed(k.digits())} ${k.unit()}`);
      }
      changes[key] = stored;
    }
    if (problems.length) { $('alert-settings-status').textContent = 'Not saved. ' + problems.join(' · '); return; }
    document.activeElement?.blur?.();
    change(rule.key, changes, `${rule.name}: limits saved.`);
  }
  async function change(key, changes, said) {
    const d = drive.current();
    const settings = structuredClone(d.settings?.rules && Object.keys(d.settings.rules).length ? d.settings : defaults(d.settings?.custom));
    settings.rules[key] = {...settings.rules[key], ...changes};
    await saveSettings(settings, said);
  }
  async function saveSettings(settings, said) {
    saving = true; render();
    try {
      await drive.save(settings);
      $('alert-settings-status').textContent = said + (window.FrogdashDrive.demo === drive.current() ? ' (simulated)' : ' Saved on the Pi.');
      details = null; signature = ''; loadDetails();
    } catch (error) { $('alert-settings-status').textContent = error.message; }
    finally { saving = false; render(); }
  }

  // ---- The alert builder: an alert on any reading, above or below a limit ----
  const builder = el('dialog', undefined, 'workspace-dialog alert-builder'); builder.id = 'alert-builder'; builder.setAttribute('aria-labelledby', 'alert-builder-title');
  builder.innerHTML = `<header class="dialog-header"><div><span class="eyebrow">ALERT BUILDER</span><h2 id="alert-builder-title">New alert</h2><p>Any reading the dash has, above or below a limit. It goes off, chimes, latches and marks the log like the built-in ones.</p></div>
    <button id="alert-builder-close" class="close-button" type="button">Cancel <span aria-hidden="true">×</span></button></header>
    <div class="alert-builder-body">
      <div class="alert-builder-readings"><label for="alert-builder-filter">Reading</label><input id="alert-builder-filter" type="search" placeholder="Find a reading" autocomplete="off">
        <div id="alert-builder-list" class="alert-builder-list" role="listbox" aria-label="Readings"></div></div>
      <div class="alert-builder-form">
        <p class="alert-builder-now"><span id="alert-builder-signal">No reading picked</span><strong id="alert-builder-value">—</strong></p>
        <label>Name <input id="alert-builder-name" maxlength="40" autocomplete="off" placeholder="Transmission hot"></label>
        <div class="alert-builder-row"><span>Goes off when it is</span><div class="segments" role="group" aria-label="Above or below"><button type="button" data-ab-op=">">Above</button><button type="button" data-ab-op="<">Below</button></div>
          <label class="alert-builder-limit"><input id="alert-builder-limit" type="number" step="any" aria-label="Limit"><span id="alert-builder-unit"></span></label></div>
        <div class="alert-builder-row"><label>For <input id="alert-builder-delay" type="number" min="0" max="60" step="0.5" value="2"> s</label>
          <label class="check-label"><input id="alert-builder-running" type="checkbox"> Only with the engine running</label></div>
        <div class="alert-builder-row"><span>How serious</span><div class="segments" role="group" aria-label="Severity"><button type="button" data-ab-severity="warning">Warning</button><button type="button" data-ab-severity="critical">Critical</button></div></div>
        <p id="alert-builder-problem" class="alert-builder-problem" role="alert"></p>
        <div class="alert-builder-buttons"><button id="alert-builder-delete" type="button">Delete alert</button><button id="alert-builder-save" class="primary" type="button">Save alert</button></div>
      </div>
    </div>`;
  document.body.append(builder);
  let building = null;      // {key: null for a new one, signal, op, severity}
  function builderKeys() {
    const values = (window.frogdashLatestSnapshot || {}).values || {};
    const keys = Object.entries(values).filter(([, v]) => typeof v?.value === 'number' || v?.value === null).map(([k]) => k);
    if (building?.signal && !keys.includes(building.signal)) keys.push(building.signal);
    return keys.filter(k => SIGNAL_KEY.test(k)).sort();
  }
  function renderBuilder() {
    if (!builder.open || !building) return;
    const values = (window.frogdashLatestSnapshot || {}).values || {}, filter = $('alert-builder-filter').value.trim().toLowerCase();
    const list = $('alert-builder-list'), keys = builderKeys().filter(k => !filter || k.includes(filter) || (NAMES[k] || humanize(k)).toLowerCase().includes(filter));
    if (list.dataset.keys !== keys.join('|')) {
      list.dataset.keys = keys.join('|'); list.replaceChildren();
      for (const key of keys) {
        const button = el('button'); button.type = 'button'; button.dataset.reading = key; button.setAttribute('role', 'option');
        button.append(el('strong', NAMES[key] || humanize(key)), el('code', key), el('small'));
        button.onclick = () => { if (!$('alert-builder-name').value.trim() || $('alert-builder-name').value === building.autoName) { building.autoName = `${NAMES[key] || humanize(key)} ${building.op === '>' ? 'high' : 'low'}`; $('alert-builder-name').value = building.autoName; } building.signal = key; renderBuilder(); };
        list.append(button);
      }
    }
    for (const button of list.children) {
      const v = values[button.dataset.reading];
      button.setAttribute('aria-selected', String(button.dataset.reading === building.signal));
      button.querySelector('small').textContent = v?.quality === 'live' && Number.isFinite(v.value) ? showValue(v.value, customKind(button.dataset.reading)) : v?.quality || 'no signal';
    }
    for (const b of builder.querySelectorAll('[data-ab-op]')) b.setAttribute('aria-pressed', String(b.dataset.abOp === building.op));
    for (const b of builder.querySelectorAll('[data-ab-severity]')) b.setAttribute('aria-pressed', String(b.dataset.abSeverity === building.severity));
    const k = kind(building.signal ? customKind(building.signal) : 'plain');
    $('alert-builder-unit').textContent = building.signal ? k.unit() : '';
    $('alert-builder-signal').textContent = building.signal || 'No reading picked';
    const v = building.signal ? values[building.signal] : null;
    $('alert-builder-value').textContent = v?.quality === 'live' && Number.isFinite(v.value) ? `Now ${showValue(v.value, customKind(building.signal))}` : building.signal ? (v?.quality || 'no signal') : '—';
    const form = builderForm();
    $('alert-builder-problem').textContent = form.problem && building.touched ? form.problem : '';
    $('alert-builder-save').disabled = !!form.problem;
  }
  function builderForm() {
    if (!building.signal) return {problem: 'Pick the reading it watches.'};
    const name = $('alert-builder-name').value.trim(), limit = $('alert-builder-limit').value.trim(), delay = Number($('alert-builder-delay').value);
    if (!name) return {problem: 'Give it a name.'};
    if (limit === '' || !Number.isFinite(Number(limit))) return {problem: 'Set the limit.'};
    if (!Number.isFinite(delay) || delay < 0 || delay > 60) return {problem: 'For: 0 to 60 seconds.'};
    const k = kind(customKind(building.signal)), stored = Number((k.store ? k.store(Number(limit)) : Number(limit)).toFixed(4));
    return {definition: {key: building.key, name, signal: building.signal, op: building.op, limit: stored, severity: building.severity, running: $('alert-builder-running').checked},
            delay: Math.round(delay * 10) / 10};
  }
  function openBuilder(key = null) {
    const d = drive.current(), def = key ? (d.settings?.custom || []).find(c => c.key === key) : null, s = key ? d.settings?.rules?.[key] : null;
    building = {key, signal: def?.signal || null, op: def?.op || '>', severity: def?.severity || 'warning', touched: false, autoName: ''};
    $('alert-builder-title').textContent = def ? `Change ${def.name}` : 'New alert';
    $('alert-builder-name').value = def?.name || '';
    const k = kind(def ? customKind(def.signal) : 'plain'), limit = s?.limit ?? def?.limit;
    $('alert-builder-limit').value = limit === undefined ? '' : String(Number((k.show ? k.show(limit) : limit).toFixed(2)));
    $('alert-builder-delay').value = String(s?.delay ?? 2);
    $('alert-builder-running').checked = !!def?.running;
    $('alert-builder-filter').value = '';
    $('alert-builder-delete').hidden = !def;
    delete $('alert-builder-list').dataset.keys;
    if (!builder.open) builder.showModal();
    renderBuilder();
  }
  builder.addEventListener('input', () => { if (building) { building.touched = true; renderBuilder(); } });
  builder.addEventListener('click', event => {
    const op = event.target.closest('[data-ab-op]'), severity = event.target.closest('[data-ab-severity]');
    if (!building || !(op || severity)) return;
    if (op) {
      building.op = op.dataset.abOp;
      if ($('alert-builder-name').value === building.autoName && building.signal) { building.autoName = `${NAMES[building.signal] || humanize(building.signal)} ${building.op === '>' ? 'high' : 'low'}`; $('alert-builder-name').value = building.autoName; }
    }
    if (severity) building.severity = severity.dataset.abSeverity;
    renderBuilder();
  });
  $('alert-builder-close').onclick = () => builder.close();
  builder.addEventListener('close', () => { building = null; window.FrogdashKeyboard?.close?.(); });
  $('alert-builder-save').onclick = async () => {
    building.touched = true;
    const form = builderForm();
    if (form.problem) { renderBuilder(); return; }
    const d = drive.current();
    const settings = structuredClone(d.settings?.rules && Object.keys(d.settings.rules).length ? d.settings : defaults(d.settings?.custom));
    settings.custom = settings.custom || [];
    let key = form.definition.key;
    if (!key) {
      if (settings.custom.length >= MAX_CUSTOM) { $('alert-builder-problem').textContent = `At most ${MAX_CUSTOM} alerts of your own.`; return; }
      let n = 1; while (settings.custom.some(c => c.key === `u${n}`)) n++; key = `u${n}`;
    }
    const definition = {...form.definition, key};
    const at = settings.custom.findIndex(c => c.key === key);
    if (at >= 0) settings.custom[at] = definition; else settings.custom.push(definition);
    settings.rules[key] = {enabled: settings.rules[key]?.enabled ?? true, delay: form.delay, limit: definition.limit};
    builder.close();
    selected = key; details = null;
    await saveSettings(settings, `${definition.name}: saved.`);
    highlight(); renderDetail();
  };
  $('alert-builder-delete').onclick = async () => {
    const key = building?.key;
    if (!key) return;
    const d = drive.current(), settings = structuredClone(d.settings);
    const name = settings.custom.find(c => c.key === key)?.name || key;
    settings.custom = settings.custom.filter(c => c.key !== key);
    delete settings.rules[key];
    builder.close();
    await saveSettings(settings, `${name}: deleted.`);
  };
  $('alert-new').onclick = () => openBuilder(null);

  for (const button of document.querySelectorAll('[data-alert-filter]')) button.onclick = () => {
    filter = button.dataset.alertFilter;
    for (const b of document.querySelectorAll('[data-alert-filter]')) b.setAttribute('aria-pressed', String(b === button));
    render();
  };
  window.addEventListener('frogdash-state', event => {
    window.frogdashLatestSnapshot = event.detail.snapshot;
    if (!document.querySelector('[data-driver-panel="alerts"]').hidden && $('drive-dialog').open) render();
    renderBuilder();
    if (selected && details && performance.now() - detailsAt > 5000) loadDetails();
  });
  window.addEventListener('frogdash-units', () => { signature = ''; render(); });
  // The preview has the catalogue as a script (alert-rules.js); the Pi serves the file.
  (window.frogdashAlertRules ? Promise.resolve(window.frogdashAlertRules) : fetch('alert-rules.json', {cache: 'no-cache'}).then(r => r.json())).then(data => {
    catalogue = data; rules = Object.fromEntries(data.rules.map(r => [r.key, r]));
    build(); render();
  }).catch(() => { $('alert-widgets').replaceChildren(el('p', 'The list of alerts could not be read.', 'control-note')); });
  window.frogdashAlertRuleOf = key => rules[key] ? structuredClone(rules[key]) : null;     // For the tests
  window.FrogdashAlerts = {simulate, get ready() { return !!catalogue; }, open(key) { selected = key; renderDetail(); highlight(); }, build: openBuilder};
})();
