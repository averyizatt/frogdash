/* Water/meth pulse tuning (can_protocol.h extension 4). The pump is switched directly by
   a mechanical relay, so flow is set by how long the pump runs in each slow cycle: at
   least half a second on, at least half a second off, or on continuously. Every value
   shown is the controller's own reported setting (0x30F), and the controller enforces
   the limits. Changes apply at once; Save stores them on the controller. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const u = window.FrogdashUnits;
  const send = (action, value) => window.FrogdashControls?.send(action, value);
  // name, key, label, unit, display divisor, minimum, maximum, step (all in display units)
  const FIELDS = [
    ['period_ms', 1, 'Cycle length', 's', 1000, 1, 10, .5],
    ['min_on_ms', 2, 'Pump runs at start boost', 's', 1000, .5, 10, .1],
    ['max_on_ms', 3, 'Pump runs at full boost', 's', 1000, .5, 10, .1],
    ['start_psi_x10', 4, 'Start boost', 'psi', 10, 1, 30, .5],
    ['full_psi_x10', 5, 'Full boost', 'psi', 10, 2, 35, .5],
    ['min_rpm', 6, 'Minimum engine RPM', '', 1, 0, 8000, 100],
    ['max_spray_s', 7, 'Longest continuous spray', 's', 1, 1, 120, 1],
    ['rest_s', 8, 'Rest after that (0 = no time limit)', 's', 1, 0, 60, 1],
    ['ramp_ms', 9, 'Run-time growth per cycle (0 = none)', 's', 1000, 0, 5, .1],
    ['max_dose_pct', 14, 'Most fluid, as % of fuel (0 = off)', '%', 1, 0, 40, 1],
    ['nozzle_ml_min', 13, 'Nozzle size', 'ml/min', 1, 20, 1000, 5],
    ['min_pre_temp_c', 10, 'Only spray above intake temp (0 = off)', 'temp', 1, 0, 120, 1],
  ];
  // Raw limits and conservative defaults; the controller's are the authority (meth_tune.h).
  const RULES = {period_ms: [1000, 10000, 4000], min_on_ms: [500, 10000, 1000], max_on_ms: [500, 10000, 2000], start_psi_x10: [10, 300, 50],
    full_psi_x10: [20, 350, 100], min_rpm: [0, 8000, 2500], max_spray_s: [1, 120, 12], rest_s: [0, 60, 6], ramp_ms: [0, 5000, 500],
    min_pre_temp_c: [0, 120, 0], overboost_assist: [0, 1, 0], meth_pct: [0, 100, 0], nozzle_ml_min: [20, 1000, 60], max_dose_pct: [0, 40, 10]};
  const NAMES = Object.keys(RULES);
  const DEFAULTS = Object.fromEntries(NAMES.map(name => [name, RULES[name][2]]));
  // Flow presets cover pulse timing and limits; the tank mix and nozzle are separate.
  const TIMING = NAMES.filter(name => !['meth_pct', 'nozzle_ml_min', 'max_dose_pct'].includes(name));
  const timing = values => Object.fromEntries(TIMING.map(name => [name, values[name]]));
  const BUILT_IN = [
    {name: 'Conservative', builtin: true, values: timing(DEFAULTS)},
    {name: 'Mild', builtin: true, values: timing({...DEFAULTS, min_on_ms: 1500, max_on_ms: 3000, start_psi_x10: 45, full_psi_x10: 90, max_spray_s: 20, rest_s: 5, ramp_ms: 1000})},
    {name: 'Standard', builtin: true, values: timing({...DEFAULTS, min_on_ms: 2000, max_on_ms: 4000, start_psi_x10: 40, full_psi_x10: 80, max_spray_s: 30, rest_s: 4, ramp_ms: 2000})},
  ];
  const FLUIDS = [
    {name: 'Water', values: {meth_pct: 0, max_dose_pct: 10}}, {name: '18% meth', values: {meth_pct: 18, max_dose_pct: 12}},
    {name: '36% meth', values: {meth_pct: 36, max_dose_pct: 15}}, {name: '53% meth', values: {meth_pct: 53, max_dose_pct: 18}},
  ];
  const SLOTS = ['Custom 1', 'Custom 2', 'Custom 3'];
  const HOLD = {NONE: 'Injecting', DISARMED: 'Disarmed', BELOW_BOOST: 'Armed: waiting for boost', RPM_LOW: 'Held: engine RPM is below the minimum',
    RPM_MISSING: 'Held: no engine RPM reaching the controller', AIR_COLD: 'Held: intake air is below the temperature limit',
    TEMP_SENSOR: 'Held: a temperature limit is set but the sensor is not reading', RESTING: 'Resting after the longest allowed spray',
    TANK_LOW: 'Held: tank low', FAULT: 'Held: controller fault', DOSE_LIMIT: 'Held: too little airflow for the dose limit'};
  const ACTION = {save: 0, revert: 1, defaults: 2};
  // One setting changed the way the controller does it: clamped to its range and its
  // partner, and never raising another setting (used by the preview's stand-in controller).
  function applySetting(values, name, requested) {
    const [low, high] = RULES[name];
    let value = Math.min(Math.max(requested, low), high);
    if (name === 'min_on_ms') value = Math.min(value, values.max_on_ms);
    else if (name === 'max_on_ms') value = Math.max(Math.min(value, values.period_ms), values.min_on_ms);
    else if (name === 'start_psi_x10') value = Math.min(value, values.full_psi_x10 - 10);
    else if (name === 'full_psi_x10') value = Math.max(value, values.start_psi_x10 + 10);
    values[name] = value;
    if (name === 'period_ms') { values.max_on_ms = Math.min(values.max_on_ms, value); values.min_on_ms = Math.min(values.min_on_ms, values.max_on_ms); }
    return value;
  }
  // The relay's rules for one cycle: no blips, no gaps too short to be worth a switch.
  function relayOn(on, period) {
    if (on >= period) return period;
    if (period - on < 500) on = Math.max(0, period - 500);
    return on < 500 ? 0 : on;
  }
  // Fuel flow estimate shared with the controller's dose limit (2.3 L, see meth_tune.h).
  const fuelGPerMin = (rpm, mapKpa) => rpm * mapKpa * 8.79e-4;
  window.FrogdashMethTune = {RULES, DEFAULTS, applySetting, relayOn, fuelGPerMin, keyName: key => NAMES[key - 1]};

  let latest = {}, presets = BUILT_IN.map(p => ({...p})), demoCustom = {}, loaded = false, busy = false;
  const mirror = () => latest.meth_tune || {supported: false, settings: {}};
  const demo = () => latest.mode === 'demo';
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const tempUnit = () => u.metric ? '°C' : '°F';
  const tidy = value => String(Math.round(value * 100) / 100);
  // The temperature limit is stored in whole degrees C with 0 meaning off.
  const shown = ([, , , unit, divisor], raw) => unit === 'temp' ? (raw === 0 || u.metric ? raw : Math.round(raw * 1.8 + 32)) : raw / divisor;
  const rawFrom = ([, , , unit, divisor], value) => unit === 'temp' ? (value <= 0 ? 0 : Math.max(1, Math.round(u.metric ? value : (value - 32) / 1.8))) : Math.round(value * divisor);
  const seconds = ms => `${tidy(ms / 1000)} s`;

  // ---- Tuning tab ----
  const panel = $('panel-tune');
  panel.innerHTML = '<p class="tl-sync control-note" id="mt-sync" role="status"></p>' +
    '<div class="mt-presets"><label class="tl-field">In the tank<select id="mt-fluid"></select></label>' +
    '<label class="tl-field">Flow preset<select id="mt-preset"></select></label>' +
    '<button type="button" id="mt-apply">APPLY PRESET</button><button type="button" id="mt-store">STORE CURRENT HERE</button></div>' +
    '<div class="mt-grid" id="mt-grid"></div><p class="control-note" id="mt-summary"></p>' +
    '<div class="control-row"><button type="button" id="mt-save">SAVE TO CONTROLLER</button><button type="button" id="mt-revert">REVERT TO SAVED</button>' +
    '<button type="button" id="mt-defaults">CONSERVATIVE DEFAULTS</button></div>';
  const inputs = {};
  for (const field of FIELDS) {
    const [name, key, , , , , , step] = field;
    const input = el('input'); input.type = 'number'; input.id = `mt-${name}`; input.step = step; input.disabled = true;
    const label = el('label', 'tl-field'); label.append(el('span'), input);
    $('mt-grid').append(label);
    inputs[name] = input;
    input.addEventListener('change', () => {
      if (input.value === '' || !Number.isFinite(input.valueAsNumber)) return render();
      const [rawLow, rawHigh] = RULES[name];
      send('meth.setting', key * 65536 + Math.min(Math.max(rawFrom(field, input.valueAsNumber), rawLow), rawHigh));
    });
  }
  const assist = el('select'); assist.id = 'mt-overboost_assist'; assist.disabled = true;
  assist.append(Object.assign(el('option', null, 'Off: stay inside the limits'), {value: 0}), Object.assign(el('option', null, 'On: force high flow when overboosting'), {value: 1}));
  const assistLabel = el('label', 'tl-field'); assistLabel.append('Overboost assist', assist); $('mt-grid').append(assistLabel);
  assist.addEventListener('change', () => send('meth.setting', 11 * 65536 + Number(assist.value)));
  for (const name of ['save', 'revert', 'defaults']) $(`mt-${name}`).onclick = () => send('meth.tune_action', ACTION[name]);
  $('mt-fluid').append(...FLUIDS.map(f => Object.assign(el('option', null, f.name === 'Water' ? 'Water only' : f.name), {value: f.name})),
    Object.assign(el('option', null, 'Other mix'), {value: '', disabled: true}));

  const result = (text, status) => { $('command-result').textContent = text; $('command-result').dataset.status = status; };
  async function presetRequest(action, name) {
    if (demo()) {
      if (action === 'save') { demoCustom[name] = timing(mirror().settings); refreshPresets(); result(`Current flow settings stored as ${name} in the preview.`, 'simulated'); return; }
      const values = action === 'fluid' ? FLUIDS.find(f => f.name === name).values : presets.find(p => p.name === name).values;
      window.frogdashDemo.methPreset(values); result(`${name} applied in the preview.`, 'simulated');
      return;
    }
    busy = true; render();
    result(action === 'save' ? `Storing ${name}…` : `Applying ${name}…`, 'pending');
    try {
      const response = await fetch('/meth/presets', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action, name})});
      if (!response.ok) throw new Error(await response.text());
      const body = await response.json();
      usePresets(body); result(body.message, 'acknowledged');
    } catch (error) { result(error.message || 'Preset request failed', 'rejected'); }
    busy = false; render();
  }
  function usePresets(body) {
    const saved = Object.fromEntries((body.presets || []).filter(p => !p.builtin).map(p => [p.name, p.values]));
    presets = [...BUILT_IN.map(p => ({...p})), ...SLOTS.map(name => ({name, builtin: false, values: saved[name] || null}))];
    const select = $('mt-preset'), keep = select.value;
    select.replaceChildren(...presets.map(p => Object.assign(el('option', null, p.values ? p.name : `${p.name} (empty)`), {value: p.name})));
    if (presets.some(p => p.name === keep)) select.value = keep;
  }
  async function refreshPresets() {
    if (demo()) return usePresets({presets: Object.entries(demoCustom).map(([name, values]) => ({name, builtin: false, values}))});
    try { usePresets(await (await fetch('/meth/presets', {cache: 'no-store'})).json()); } catch { usePresets({}); }
  }
  usePresets({});
  $('mt-apply').onclick = () => presetRequest('apply', $('mt-preset').value);
  $('mt-store').onclick = () => presetRequest('save', $('mt-preset').value);
  $('mt-preset').addEventListener('change', () => render());
  $('mt-fluid').addEventListener('change', () => { if ($('mt-fluid').value) presetRequest('fluid', $('mt-fluid').value); });

  const matches = (subset, s) => !!subset && Object.entries(subset).every(([name, value]) => s[name] === value);
  function render() {
    const m = mirror(), s = m.settings || {}, ready = m.supported && m.complete;
    const active = ready ? presets.find(p => matches(p.values, s))?.name : null;
    const fluid = ready ? FLUIDS.find(f => f.values.meth_pct === s.meth_pct)?.name ?? '' : null;
    const sync = $('mt-sync');
    sync.dataset.state = !m.supported ? 'off' : m.unsaved ? 'unsaved' : 'saved';
    sync.textContent = !m.supported ? 'Tuning needs the current water/meth controller firmware. Once it is flashed, this page fills in from the controller.'
      : !m.complete ? 'Reading settings from the controller…'
      : (m.unsaved ? 'Unsaved changes: they work now but are lost at power-off until you Save to controller.' : 'Saved on the controller.') + (active ? ` Matches preset: ${active}.` : ' Custom flow settings.');
    for (const field of FIELDS) {
      const [name, , text, unit] = field, input = inputs[name], title = input.previousSibling;
      const label = `${text}${unit === 'temp' ? ` · ${tempUnit()}` : unit ? ` · ${unit}` : ''}`;
      if (title.textContent !== label) title.textContent = label;
      input.disabled = !ready || busy;
      const editing = document.activeElement === input || input.classList.contains('wheel-editing');
      if (ready && !editing && s[name] !== undefined) { const value = tidy(shown(field, s[name])); if (input.value !== value) input.value = value; }
      if (unit === 'temp') { input.min = 0; input.max = u.metric ? 120 : 248; input.step = u.metric ? 1 : 5; } else { input.min = field[5]; input.max = field[6]; }
    }
    assist.disabled = !ready || busy;
    if (ready && document.activeElement !== assist) assist.value = String(s.overboost_assist ?? 0);
    $('mt-fluid').disabled = !ready || busy;
    if (ready && document.activeElement !== $('mt-fluid')) $('mt-fluid').value = fluid;
    const chosen = presets.find(p => p.name === $('mt-preset').value);
    $('mt-apply').disabled = !ready || busy || !chosen?.values || active === chosen.name;
    $('mt-store').disabled = !ready || busy || !chosen || chosen.builtin;
    $('mt-save').disabled = !ready || busy || !m.unsaved;
    $('mt-revert').disabled = !ready || busy || !m.unsaved;
    $('mt-defaults').disabled = !ready || busy || matches(DEFAULTS, s);
    $('mt-summary').textContent = ready ? summary(s) : '';
    renderLive(m);
  }
  // What the settings mean in fluid, in words: the reason for the numbers above.
  function summary(s) {
    const flow = ms => { const on = relayOn(ms, s.period_ms); return `${seconds(on)} in every ${seconds(s.period_ms)} (${Math.round(s.nozzle_ml_min * on / s.period_ms)} ml/min)`; };
    const top = relayOn(s.max_on_ms, s.period_ms);
    return `At ${tidy(s.start_psi_x10 / 10)} psi the pump runs ${flow(s.min_on_ms)}, rising to ${top >= s.period_ms ? `on continuously (${s.nozzle_ml_min} ml/min)` : flow(s.max_on_ms)} at ${tidy(s.full_psi_x10 / 10)} psi. ` +
      `${s.max_dose_pct ? `Never more than ${s.max_dose_pct}% of the engine's fuel flow. ` : 'No dose limit. '}` +
      `The relay switches at most once every ${seconds(s.period_ms)}. Needs ${s.min_rpm} RPM from the dash` +
      `${s.rest_s ? `; rests ${s.rest_s} s after ${s.max_spray_s} s of spraying` : '; no spray time limit'}.`;
  }

  // ---- Live card on the Water / meth tab ----
  function renderLive(m) {
    const value = key => { const v = latest.values?.[key]; return v && v.quality === 'live' && v.value !== null ? v.value : null; };
    const temp = (key, delta) => { const v = value(key); return v === null ? 'No sensor reading' : `${(u.metric ? v : delta ? v * 1.8 : v * 1.8 + 32).toFixed(1)} ${tempUnit()}`; };
    const flow = value('meth.flow_ml_min'), dose = value('meth.dose_pct');
    const text = {
      'meth-live-hold': !m.supported ? 'Needs the current controller firmware' : HOLD[m.hold] || 'Waiting for the controller',
      'meth-live-pulse': !m.supported ? '—' : !m.on_ms ? 'Pump off' : m.on_ms >= m.period_ms ? 'Pump on continuously' : `Pump runs ${seconds(m.on_ms)} in every ${seconds(m.period_ms)}`,
      'meth-live-flow': !m.supported || flow === null ? '—' : !flow ? 'None' : `About ${Math.round(flow)} ml/min${dose === null ? '' : ` · ${dose.toFixed(1)}% of fuel`}`,
      'meth-live-rpm': !m.supported ? '—' : m.rpm_ok ? 'OK: above the minimum' : 'Not met',
      'meth-live-pre': temp('meth.pre_temp_c'), 'meth-live-post': temp('meth.post_temp_c'),
      'meth-live-drop': value('meth.temp_drop_c') === null ? 'Needs both sensors' : temp('meth.temp_drop_c', true),
    };
    for (const [id, content] of Object.entries(text)) if ($(id).textContent !== content) $(id).textContent = content;
    $('meth-live-hold').dataset.state = m.hold === 'NONE' ? 'on' : !m.hold || ['DISARMED', 'BELOW_BOOST'].includes(m.hold) ? 'idle' : 'held';
  }

  window.addEventListener('frogdash-state', event => {
    latest = event.detail.snapshot;
    if (!$('controls-dialog').open) return;  // Nothing to draw while the page is closed.
    if (!loaded) { loaded = true; refreshPresets(); }
    render();
  });
  $('controls-dialog').addEventListener('close', () => { loaded = false; });
  window.addEventListener('frogdash-units', render);
})();
