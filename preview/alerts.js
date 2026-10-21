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
    volt: {unit: () => 'V', digits: () => 1}, deg: {unit: () => '°', digits: () => 1}, count: {unit: () => '', digits: () => 0},
    text: {unit: () => '', digits: () => 0}, module: {unit: () => '', digits: () => 0},
  };
  const kind = name => KINDS[name] || KINDS.count;
  const showValue = (value, name) => {
    if (value === null || value === undefined) return '—';
    if (typeof value !== 'number') return String(value).toUpperCase();
    const k = kind(name), shown = k.show ? k.show(value) : value;
    return `${shown.toFixed(k.digits())}${k.unit() ? ' ' + k.unit() : ''}`;
  };
  const NAMES = {'engine.rpm': 'Engine speed', 'engine.oil_pressure_psi': 'Oil pressure', 'engine.fuel_pressure_psi': 'Fuel pressure',
    'engine.boost_kpa': 'Boost', 'engine.afr': 'Air/fuel ratio', 'ecu.afr_target': 'AFR target', 'engine.coolant_c': 'Coolant',
    'ecu.iat_c': 'Intake air', 'vehicle.battery_v': 'Battery', 'vehicle.fuel_pct': 'Fuel level', 'engine.ego_correction_pct': 'Fuel correction',
    'ecu.knock_retard_deg': 'Knock retard', 'meth.tank_pct': 'Water/meth tank', 'meth.state': 'Water/meth', 'knock.energy': 'Knock level',
    'ecu.sync_loss_count': 'Sync losses'};
  const KIND_OF = {'engine.oil_pressure_psi': 'pressure', 'engine.fuel_pressure_psi': 'pressure', 'engine.boost_kpa': 'boost',
    'engine.coolant_c': 'temp', 'ecu.iat_c': 'temp', 'engine.rpm': 'rpm', 'vehicle.fuel_pct': 'pct', 'meth.tank_pct': 'pct',
    'engine.ego_correction_pct': 'pct', 'engine.afr': 'afr', 'ecu.afr_target': 'afr', 'vehicle.battery_v': 'volt', 'ecu.knock_retard_deg': 'deg'};

  // ---- The same rules as the Pi (alerts.py), for the preview's simulated car ----
  const live = (snapshot, key) => { const v = snapshot?.values?.[key]; return v && v.quality === 'live' && v.value !== null && v.value !== undefined ? v.value : null; };
  function term(value, settings, snapshot) {
    if (value === null || typeof value !== 'object') return value;
    if (value.sum) { const parts = value.sum.map(part => term(part, settings, snapshot)); return parts.some(p => p === null) ? null : parts.reduce((a, b) => a + b, 0); }
    const base = 'param' in value ? settings[value.param] : live(snapshot, value.signal);
    return base === null || base === undefined ? null : base * (value.scale ?? 1);
  }
  const OPS = {'<': (a, b) => a < b, '<=': (a, b) => a <= b, '>': (a, b) => a > b, '>=': (a, b) => a >= b, '==': (a, b) => a === b, '!=': (a, b) => a !== b, 'abs>': (a, b) => Math.abs(a) > b};
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
  function defaults() {
    const result = {version: 2, chime: false, rules: {}};
    for (const rule of catalogue.rules) result.rules[rule.key] = {enabled: rule.enabled, delay: rule.delay, ...Object.fromEntries(rule.params.map(p => [p.key, p.default]))};
    return result;
  }
  // The demo (driving.js) keeps its alerts here: the same fields the Pi sends.
  function simulate(snapshot, demo) {
    if (!catalogue) return;
    if (!demo.settings?.rules || !Object.keys(demo.settings.rules).length) demo.settings = {...defaults(), chime: !!demo.settings?.chime};
    const now = performance.now();
    for (const rule of catalogue.rules) {
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
    main.append(el('span', rule.code, 'alert-code'), el('strong', rule.name, 'alert-name'), el('span', '—', 'alert-reading'), el('span', '', 'alert-state'));
    main.onclick = () => { selected = rule.key; details = null; renderDetail(); highlight(); loadDetails(); };
    const toggle = el('label', undefined, 'alert-switch'), input = el('input'); input.type = 'checkbox'; input.setAttribute('role', 'switch');
    input.setAttribute('aria-label', `${rule.name}: on or off`);
    input.onchange = () => change(rule.key, {enabled: input.checked}, `${rule.name} ${input.checked ? 'on' : 'off'}.`);
    toggle.append(input, el('span'));
    card.append(main, toggle);
    return card;
  }
  function build() {
    const host = $('alert-widgets'); host.replaceChildren();
    for (const [group, label] of catalogue.groups) {
      const members = catalogue.rules.filter(r => r.group === group);
      if (!members.length) continue;
      const section = el('section', undefined, 'alert-group'); section.dataset.group = group;
      section.append(el('h3', label), el('div', undefined, 'alert-group-grid'));
      for (const rule of members) section.lastChild.append(widget(rule));
      host.append(section);
    }
  }
  function highlight() { for (const card of document.querySelectorAll('.alert-widget')) card.classList.toggle('selected', card.dataset.key === selected); }
  function render() {
    if (!catalogue) return;
    const d = drive.current(), settings = d.settings?.rules || {}, alerts = Object.fromEntries((d.alerts || []).map(a => [a.key, a]));
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
    const summary = `${going ? `${going} going off · ` : ''}${on} of ${catalogue.rules.length} alerts on${d.mode === 'demo' || window.FrogdashDrive.demo === d ? ' · simulated' : ''}`;
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
    const head = el('header', undefined, 'alert-detail-head');
    head.append(el('span', `${rule.code} · ${rule.severity === 'critical' ? 'Critical' : 'Warning'}`, 'alert-code'), el('h3', rule.name), el('span', STATE_WORDS[state], 'alert-detail-state'));
    head.dataset.state = state; head.dataset.severity = rule.severity;
    host.append(head, el('p', rule.about, 'alert-about'), el('p', undefined, 'alert-check'));
    host.lastChild.append(el('b', 'Check: '), document.createTextNode(rule.check));
    // What it watches, now.
    const watched = [...new Set([rule.show[0], ...(rule.when || []).map(clause => clause[0])])].filter(key => NAMES[key]);
    const now = el('dl', undefined, 'alert-live'); now.id = 'alert-live';
    for (const key of watched) now.append(el('dt', NAMES[key]), Object.assign(el('dd', '—'), {id: `alert-live-${key.replace(/\W/g, '-')}`}));
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
      const key = Object.keys(NAMES).find(k => node.id === `alert-live-${k.replace(/\W/g, '-')}`);
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
    const settings = structuredClone(d.settings?.rules && Object.keys(d.settings.rules).length ? d.settings : defaults());
    settings.rules[key] = {...settings.rules[key], ...changes};
    saving = true; render();
    try {
      await drive.save(settings);
      $('alert-settings-status').textContent = said + (window.FrogdashDrive.demo === drive.current() ? ' (simulated)' : ' Saved on the Pi.');
      details = null; signature = ''; loadDetails();
    } catch (error) { $('alert-settings-status').textContent = error.message; }
    finally { saving = false; render(); }
  }

  for (const button of document.querySelectorAll('[data-alert-filter]')) button.onclick = () => {
    filter = button.dataset.alertFilter;
    for (const b of document.querySelectorAll('[data-alert-filter]')) b.setAttribute('aria-pressed', String(b === button));
    render();
  };
  window.addEventListener('frogdash-state', event => {
    window.frogdashLatestSnapshot = event.detail.snapshot;
    if (!document.querySelector('[data-driver-panel="alerts"]').hidden && $('drive-dialog').open) render();
    if (selected && details && performance.now() - detailsAt > 5000) loadDetails();
  });
  window.addEventListener('frogdash-units', () => { signature = ''; render(); });
  // The preview has the catalogue as a script (alert-rules.js); the Pi serves the file.
  (window.frogdashAlertRules ? Promise.resolve(window.frogdashAlertRules) : fetch('alert-rules.json', {cache: 'no-cache'}).then(r => r.json())).then(data => {
    catalogue = data; rules = Object.fromEntries(data.rules.map(r => [r.key, r]));
    build(); render();
  }).catch(() => { $('alert-widgets').replaceChildren(el('p', 'The list of alerts could not be read.', 'control-note')); });
  window.FrogdashAlerts = {simulate, get ready() { return !!catalogue; }, open(key) { selected = key; renderDetail(); highlight(); }};
})();
