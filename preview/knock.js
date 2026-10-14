/* The knock page: what the knock listening hears, and its settings.

   Live view: the knock-band level against what is normal for this RPM and the threshold;
   the spectrum of the sensor signal with the band being listened in, the frequency the
   bore suggests and the one the engine itself rings at; and the amplifier, the second
   resonance and the sensor signal as numbers.
   Settings view: everything the controller lets the dash set. Each field shows the
   controller's own value and sends a change at once; the ESP32 keeps it through a
   restart, the Nano only until power-off.

   The spectrum, the frequency it finds and the amplifier gain come from the ESP32
   water/meth controller (0x30E, can_protocol.h extension 6). With the Nano controller
   those parts say so and the rest works as before. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const send = (action, value) => window.FrogdashControls?.send(action, value);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const svg = (tag, attrs) => { const n = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  const clamp = (n, low, high) => Math.min(Math.max(n, low), high);
  const absent = {value: null, quality: 'unavailable'};
  const QUALITY = {live: 'LIVE', stale: 'STALE', unavailable: 'UNAVAILABLE', fault: 'FAULT'};
  let snapshot = {values: {}, controls: {reasons: {}}}, connected = false;
  const history = [];   // Level and normal level over the last seconds

  const signal = key => { const v = snapshot.values?.[key] || absent; return connected ? v : {...v, quality: v.value === null ? 'unavailable' : 'stale'}; };
  const live = key => { const v = signal(key); return v.quality === 'live' ? v.value : null; };
  const set = (id, text) => { const node = $(id); if (node.textContent !== text) node.textContent = text; };
  const kHz = hz => `${(hz / 1000).toFixed(2)} kHz`;
  const detail = () => snapshot.knock_detail || {supported: false};

  // The dash refuses a command while another awaits its reply, and the same command twice
  // within 1.5 s of that reply (a late reply could be taken for the second one's). So a
  // change waits its turn here, and only the latest value of each setting goes out.
  const waiting = new Map(), sentAt = new Map();
  let lastSend = -1e9;
  function request(action, value) { waiting.set(action, {value, at: performance.now()}); flush(); }
  function flush() {
    const now = performance.now(), reasons = snapshot.controls?.reasons || {};
    for (const [action, item] of waiting) {
      // Never became possible: dropped, and the field goes back to the controller's value.
      if (now - item.at > 6000) { waiting.delete(action); continue; }
      if (!connected || reasons[action] || now - lastSend < 400 || now - (sentAt.get(action) ?? -1e9) < 2000) continue;
      waiting.delete(action); sentAt.set(action, now); lastSend = now;
      send(action, item.value);
      break;
    }
  }
  // A field keeps what the driver put in while it is being changed, while the change
  // waits to go out, and for a moment after: then it shows the controller's value again,
  // which is the new one if the controller took it.
  const holds = new WeakMap();
  const changing = node => { node.dataset.changing = '1'; };
  const changed = node => { delete node.dataset.changing; holds.set(node, performance.now() + 2500); };
  const editing = (node, ...actions) => node.classList.contains('wheel-editing') || node.dataset.changing === '1' ||
    actions.some(action => waiting.has(action)) || performance.now() < (holds.get(node) ?? 0);

  // ---------------------------------------------------------------- live view
  function show(id, key, convert = v => v) {
    const v = signal(key), node = $(id);
    node.dataset.quality = v.quality;
    const value = v.quality === 'live' ? convert(v.value) : null;
    set(id, value === null ? '—' : String(value));
    return v.quality === 'live' ? v.value : null;
  }

  function renderLevel() {
    const energy = show('knock-energy-num', 'knock.energy');
    show('knock-baseline-num', 'knock.baseline');
    const threshold = show('knock-threshold-num', 'knock.threshold');
    show('knock-events-num', 'knock.event_count');
    show('knock-last-rpm', 'knock.last_rpm');
    show('knock-last-boost', 'knock.last_boost_kpa', n => `${n} kPa`);
    set('knock-headroom-num', energy === null || threshold === null ? '—' : String(threshold - energy));
    const status = energy === null ? signal('knock.energy').quality.toUpperCase() :
      live('knock.critical') ? 'CRITICAL' : live('knock.warning') ? 'WARNING' : !live('knock.learned') ? 'LEARNING' : 'OK';
    set('knock-status', status);
    $('knock-status').dataset.status = status;
    const share = live('knock.band_share_pct');
    set('knock-share', share === null ? '—' : `${share}%`);

    const now = performance.now();
    while (history.length && history[0].at < now - 6700) history.shift();
    const y = n => 220 - clamp(n, 0, 255) / 255 * 202;
    const path = key => {
      let d = '', pen = false;
      for (const p of history) {
        if (p[key] === null) { pen = false; continue; }
        d += `${pen ? 'L' : 'M'}${(936 - (now - p.at) / 6700 * 888).toFixed(1)},${y(p[key]).toFixed(1)} `;
        pen = true;
      }
      return d;
    };
    $('knock-energy').setAttribute('d', path('energy'));
    $('knock-baseline').setAttribute('d', path('baseline'));
    $('knock-thresh').setAttribute('visibility', threshold === null ? 'hidden' : 'visible');
    $('knock-thresh').setAttribute('y1', y(threshold || 0));
    $('knock-thresh').setAttribute('y2', y(threshold || 0));
    set('knock-thresh-label', threshold === null ? '' : `THRESHOLD ${threshold}`);
    $('knock-thresh-label').setAttribute('y', Math.max(30, y(threshold || 0) - 7));
    $('knock-danger-zone').setAttribute('height', threshold === null ? 0 : y(threshold) - 18);
    $('knock-current-dot').setAttribute('visibility', energy === null ? 'hidden' : 'visible');
    $('knock-current-dot').setAttribute('cy', y(energy || 0));
    const samples = history.filter(p => p.energy !== null);
    set('knock-peak', samples.length ? String(Math.max(...samples.map(p => p.energy))) : '—');
  }

  // Where the filter is and why; the amplifier; the numbers under the graphs.
  function renderNumbers() {
    const d = detail(), filter = live('knock.freq.filter_hz') ?? live('knock.config.center_hz');
    const byHand = live('knock.config.flags') !== null && !(live('knock.config.flags') & 2);
    set('knock-freq', filter ? kHz(filter) : '—');
    const bore = live('knock.freq.bore_hz');
    set('knock-freq-note', !filter ? '' : byHand ? 'SET BY HAND' : live('knock.freq.learned') ? `LEARNED${bore ? ` · BORE ${(bore / 1000).toFixed(2)}` : ''}`
      : d.supported ? 'FROM THE BORE, NOT LEARNED YET' : 'FROM THE BORE');

    const gain = live('knock.amp.gain'), step = live('knock.amp.step'), top = live('knock.amp.top_step');
    set('knock-amp', gain === null ? '—' : `${gain.toFixed(1)}×`);
    const trouble = live('knock.amp.overloaded') ? 'TOO LOUD AT THE LOWEST GAIN' : live('knock.amp.silent') ? 'NOTHING HEARD AT FULL GAIN'
      : live('knock.amp.ineffective') ? 'GAIN CONTROL NOT RESPONDING' : null;
    set('knock-amp-note', gain === null ? (d.supported ? '' : 'FIXED BY THE CIRCUIT') :
      trouble || `${live('knock.amp.fixed') ? 'HELD' : live('knock.amp.automatic') ? 'AUTOMATIC' : 'FIXED'}${step === null ? '' : ` · POSITION ${step} OF ${top}`}`);
    $('knock-amp-note').dataset.state = trouble ? 'warn' : '';

    const swing = live('knock.amp.swing_mv'), room = live('knock.amp.room_mv'), rest = live('knock.amp.rest_mv');
    if (swing !== null) set('knock-swing', `${swing} mV${room ? ` · ${Math.round(swing * 100 / room)}% of room` : ''}`);
    else {
      // The Nano reports its swing as a share of its ADC range.
      const envelope = live('knock.hook.envelope');
      set('knock-swing', envelope === null ? '—' : `${Math.round(envelope * 2 * 100 / 512)}% of range`);
    }
    const nanoRest = live('knock.hook.bias_adc');
    set('knock-rest', rest !== null ? `${(rest / 1000).toFixed(2)} V` : nanoRest !== null ? `${(nanoRest * 5 / 1024).toFixed(1)} V` : '—');

    const second = live('knock.listen.second'), secondNormal = live('knock.listen.second_normal');
    set('knock-second', !d.supported ? '—' : live('knock.freq.second_active') === false ? 'Not used' : second === null ? '—' :
      `${second} · normal ${secondNormal}${live('knock.listen.confirmed') ? ' · RINGING' : ''}`);
    const crest = live('knock.listen.crest');
    set('knock-crest', crest === null ? '—' : `${crest.toFixed(1)}×${live('knock.listen.notable') ? ' · NOTABLE' : ''}`);
    const found = live('knock.freq.found_hz'), votes = live('knock.freq.votes'), agree = live('knock.freq.agreement_pct');
    set('knock-found', !d.supported ? '—' : found === null ? (votes ? `${votes} votes so far` : 'Not heard yet') : `${kHz(found)} · ${agree}% of ${votes} agree`);
    const tone = live('knock.freq.tone_hz');
    set('knock-tone', tone === null ? '—' : tone ? kHz(tone) : 'None');
    $('knock-tone').dataset.state = tone ? 'warn' : '';
    const rate = live('knock.freq.sample_rate_hz') ?? live('knock.config.sample_rate_hz');
    set('knock-rate', rate ? rate.toLocaleString('en-US') : '—');

    set('knock-source', `${snapshot.mode === 'demo' ? 'SIMULATED' : snapshot.mode === 'replay' ? 'REPLAY' : 'KNOCK SENSOR'} · ${QUALITY[signal('knock.energy').quality]}` +
      `${filter ? ` · LISTENING AT ${(filter / 1000).toFixed(1)} kHz` : ''}${d.supported ? ' · ESP32 CONTROLLER' : ''}`);
  }

  // The spectrum: frequency across, level in dB up. Built once, then only its paths move.
  const AXIS = {left: 48, right: 936, top: 18, bottom: 220};
  let axisKey = '';
  function renderSpectrum() {
    const d = detail(), have = d.supported && Array.isArray(d.normal);
    $('knock-spectrum-missing').hidden = d.supported;
    $('knock-spectrum').classList.toggle('empty', !have);
    if (!have) {
      for (const id of ['knock-spectrum-normal', 'knock-spectrum-burst']) $(id).setAttribute('d', '');
      for (const id of ['knock-band', 'knock-band-second']) $(id).setAttribute('width', 0);
      $('knock-marks').replaceChildren();
      if (d.supported) { $('knock-spectrum-missing').hidden = false; set('knock-spectrum-missing', 'Waiting for the first spectrum from the controller…'); }
      else set('knock-spectrum-missing', 'The spectrum comes from the ESP32 water/meth controller. The controller fitted now does not send one.');
      return;
    }
    const normal = d.normal, burst = Array.isArray(d.burst) ? d.burst : normal;
    const startHz = d.start_hz, endHz = d.start_hz + d.step_hz * (normal.length - 1);
    // The level scale follows what is there, in steps of 10 dB so it does not jitter.
    const low = Math.floor((Math.min(...normal) - 3) / 10) * 10;
    const high = Math.max(low + 30, Math.ceil((Math.max(...burst, ...normal) + 3) / 10) * 10);
    const x = hz => AXIS.left + clamp((hz - startHz) / (endHz - startHz), 0, 1) * (AXIS.right - AXIS.left);
    const y = db => AXIS.bottom - clamp((db - low) / (high - low), 0, 1) * (AXIS.bottom - AXIS.top);
    const key = `${startHz}|${endHz}|${low}|${high}`;
    if (key !== axisKey) {
      axisKey = key;
      const labels = [], ticks = [];
      for (let step = 0; step <= 4; step++) {
        const db = low + (high - low) * step / 4;
        labels.push(Object.assign(svg('text', {x: 38, y: y(db) + 4, 'text-anchor': 'end'}), {textContent: `${Math.round(db)}`}));
      }
      labels.push(Object.assign(svg('text', {x: AXIS.left, y: 12, 'text-anchor': 'start'}), {textContent: 'dB'}));
      for (let hz = Math.ceil(startHz / 2000) * 2000; hz <= endHz; hz += 2000) {
        ticks.push(svg('line', {x1: x(hz), y1: AXIS.top, x2: x(hz), y2: AXIS.bottom}));
        labels.push(Object.assign(svg('text', {x: x(hz), y: 242, 'text-anchor': 'middle'}), {textContent: `${hz / 1000} kHz`}));
      }
      $('knock-spectrum-axis').replaceChildren(...labels);
      $('knock-spectrum-ticks').replaceChildren(...ticks);
    }
    const line = values => values.map((db, i) => `${i ? 'L' : 'M'}${x(startHz + i * d.step_hz).toFixed(1)},${y(db).toFixed(1)}`).join(' ');
    $('knock-spectrum-normal').setAttribute('d', `${line(normal)} L${AXIS.right},${AXIS.bottom} L${AXIS.left},${AXIS.bottom} Z`);
    $('knock-spectrum-burst').setAttribute('d', line(burst));

    // The band being listened in, and the second resonance beside it.
    const filter = live('knock.freq.filter_hz') ?? live('knock.config.center_hz');
    const width = (live('knock.config.bandwidth_hz') ?? 1500) < 1000 ? 900 : 1500;
    const band = (id, centre) => {
      const from = centre ? x(centre - width / 2) : 0, to = centre ? x(centre + width / 2) : 0;
      $(id).setAttribute('x', from); $(id).setAttribute('width', Math.max(0, to - from));
    };
    band('knock-band', filter);
    band('knock-band-second', filter && live('knock.freq.second_active') ? filter * 1.659 : null);
    const marks = [];
    const mark = (hz, cls, label, row) => {
      if (!hz || hz < startHz || hz > endHz) return;
      marks.push(svg('line', {class: `knock-mark ${cls}`, x1: x(hz), y1: AXIS.top, x2: x(hz), y2: AXIS.bottom}));
      marks.push(Object.assign(svg('text', {class: `knock-mark-label ${cls}`, x: x(hz) + 5, y: AXIS.top + 14 + row * 15}), {textContent: label}));
    };
    mark(live('knock.freq.bore_hz'), 'bore', 'BORE', 0);
    mark(live('knock.freq.found_hz'), 'found', 'ENGINE', 1);
    mark(live('knock.freq.tone_hz'), 'tone', 'TONE', 2);
    $('knock-marks').replaceChildren(...marks);
  }

  // ---------------------------------------------------------------- settings view
  // id, label, command, where the controller reports it, unit, shown value from reported,
  // command value from shown, minimum, maximum, step, needs the ESP32 controller
  const NUMBERS = {
    detect: [
      ['multiplier', 'Knock is this many times normal', 'knock.multiplier', 'knock.config.multiplier', '×', v => v, v => Math.round(v * 10), 1.2, 3.8, .1],
      ['offset', 'Plus a fixed margin', 'knock.threshold', 'knock.config.threshold_offset', 'level', v => v, v => Math.round(v), 0, 200, 1],
      ['hold', 'A warning stays up for', 'knock.hold', 'knock.config.debounce_ms', 's', v => v / 1000, v => Math.round(v * 100), .1, 2.5, .1],
      ['level-gain', 'Level gain (leave at 1)', 'knock.level_gain', 'knock.config.gain', '×', v => v, v => Math.round(v * 10), .1, 20, .1],
    ],
    arm: [
      ['min-rpm', 'Only above engine speed', 'knock.min_rpm', 'knock.config.min_rpm', 'RPM', v => v, v => Math.round(v / 100), 0, 8000, 100],
      ['min-map', 'Only above manifold pressure', 'knock.min_map', 'knock.config.min_map_kpa', 'kPa absolute', v => v, v => Math.round(v), 0, 250, 5],
    ],
    frequency: [
      ['center', 'Frequency, when set by hand', 'knock.center', 'knock.config.center_hz', 'kHz', v => v / 1000, v => Math.round(v * 10), 3, 9, .1],
      ['bore', 'Cylinder bore', 'knock.bore', 'knock.config.bore_mm', 'mm', v => v, v => Math.round(v), 40, 200, 1, true],
    ],
  };
  const fields = [];
  const tidy = value => String(Math.round(value * 100) / 100);
  function card(title, note) {
    const box = el('section', 'knock-card');
    box.append(el('h3', null, title));
    if (note) box.append(el('p', 'control-note', note));
    $('knock-view-settings').append(box);
    return box;
  }
  function numberField(box, definition) {
    const [id, label, action, key, unit, shown, command, min, max, step, esp32] = definition;
    const input = el('input'); input.type = 'number'; input.id = `knock-set-${id}`; input.min = min; input.max = max; input.step = step; input.disabled = true;
    const wrap = el('label', 'tl-field'); wrap.append(el('span', null, `${label}${unit ? ` · ${unit}` : ''}`), input);
    box.append(wrap);
    input.addEventListener('input', () => changing(input));
    input.addEventListener('change', () => {
      if (input.value === '' || !Number.isFinite(input.valueAsNumber)) { delete input.dataset.changing; return renderSettings(); }
      changed(input);
      request(action, command(clamp(input.valueAsNumber, min, max)));
    });
    fields.push({input, action, key, shown, esp32});
    return input;
  }
  function selectField(box, id, label, options) {
    const select = el('select'); select.id = `knock-set-${id}`; select.disabled = true;
    select.append(...options.map(([value, text]) => Object.assign(el('option', null, text), {value})));
    const wrap = el('label', 'tl-field'); wrap.append(el('span', null, label), select);
    box.append(wrap);
    return select;
  }
  const button = (box, text, action, value) => {
    const b = el('button', null, text); b.type = 'button'; b.dataset.action = action;
    if (value !== undefined) b.dataset.value = value;
    box.append(b); return b;
  };

  // Why nothing can be changed just now (the car is moving, the controller is offline):
  // a greyed-out field does not explain itself on a touchscreen.
  const blockedNote = Object.assign(el('p', 'knock-blocked'), {id: 'knock-set-blocked', hidden: true});
  blockedNote.setAttribute('role', 'status');
  $('knock-view-settings').append(blockedNote);

  const detect = card('What counts as knock', 'Louder than normal for this RPM by the multiplier, plus the margin; narrow-band; and a burst.');
  const power = el('div', 'control-row');
  button(power, 'LISTENING ON', 'knock.enable', 1).id = 'knock-set-on';
  button(power, 'OFF', 'knock.enable', 0).id = 'knock-set-off';
  detect.append(power);
  NUMBERS.detect.forEach(d => numberField(detect, d));

  const arm = card('When it is judged', 'Knock matters under load. Manifold pressure is absolute: at 5,000 ft the air outside is about 85 kPa, so 100 is about 2 psi of boost.');
  NUMBERS.arm.forEach(d => numberField(arm, d));
  const actions = el('div', 'control-row');
  button(actions, 'CLEAR EVENTS', 'knock.clear_events');
  button(actions, 'READ SETTINGS', 'knock.refresh');
  arm.append(actions, Object.assign(el('p', 'control-note'), {id: 'knock-result', role: 'status'}));

  const frequency = card('Knock frequency');
  const freqMode = selectField(frequency, 'freq-mode', 'Where it listens', [['auto', 'Found from the engine'], ['manual', 'Set by hand']]);
  NUMBERS.frequency.slice(0, 1).forEach(d => numberField(frequency, d));
  const bandwidth = selectField(frequency, 'bandwidth', 'Band width', [['15', 'Wide · 1500 Hz'], ['9', 'Narrow · 900 Hz']]);
  NUMBERS.frequency.slice(1).forEach(d => numberField(frequency, d));
  const relearn = el('div', 'control-row');
  // Not a data-action button: app.js would enable it whenever the command is allowed,
  // and it is also off while the frequency is set by hand.
  const relearnButton = Object.assign(el('button', null, 'LEARN IT AGAIN'), {type: 'button', id: 'knock-set-relearn', disabled: true});
  relearnButton.onclick = () => request('knock.relearn');
  relearn.append(relearnButton);
  frequency.append(relearn, Object.assign(el('p', 'control-note'), {id: 'knock-set-freq-note'}));

  const amplifier = card('Amplifier gain');
  const ampMode = selectField(amplifier, 'amp-mode', 'Who sets it', [['auto', 'Automatic'], ['hold', 'Hold a position']]);
  const ampStep = el('input'); ampStep.type = 'range'; ampStep.id = 'knock-set-amp-step'; ampStep.min = 0; ampStep.max = 30; ampStep.step = 1; ampStep.disabled = true;
  const ampLabel = el('label', 'tl-field'); ampLabel.append(el('span', null, 'Position'), ampStep);
  amplifier.append(ampLabel, Object.assign(el('p', 'control-note'), {id: 'knock-set-amp-note'}));

  freqMode.addEventListener('change', () => {
    changed(freqMode);
    waiting.delete('knock.center'); waiting.delete('knock.auto_frequency');
    if (freqMode.value === 'auto') return request('knock.auto_frequency', 1);
    // Setting it by hand starts from where the filter is now.
    const now = live('knock.freq.filter_hz') ?? live('knock.config.center_hz') ?? 6000;
    request('knock.center', clamp(Math.round(now / 100), 30, 90));
  });
  bandwidth.addEventListener('change', () => { changed(bandwidth); request('knock.bandwidth', Number(bandwidth.value)); });
  ampMode.addEventListener('change', () => { changed(ampMode); request('knock.amp_gain', ampMode.value === 'auto' ? 0 : (live('knock.amp.step') ?? 0) + 1); });
  ampStep.addEventListener('input', () => changing(ampStep));
  ampStep.addEventListener('change', () => { changed(ampStep); request('knock.amp_gain', Number(ampStep.value) + 1); });

  function renderSettings() {
    const d = detail(), reasons = snapshot.controls?.reasons || {};
    // While a command awaits its reply every command has a reason; a change made then waits
    // its turn (request), so the fields stay usable.
    const busy = !!snapshot.controls?.pending;
    const blocked = (action, esp32) => !connected || snapshot.mode === 'replay' || (!!reasons[action] && !busy) || (esp32 && !d.supported);
    const why = (action, esp32) => esp32 && !d.supported ? 'Needs the ESP32 water/meth controller' : busy ? '' : reasons[action] || '';
    if (!busy) {
      const general = !connected ? 'Not connected to the dash: settings cannot be changed.' : snapshot.mode === 'replay' ? 'Replay: settings cannot be changed.'
        : reasons['knock.multiplier'] ? `${reasons['knock.multiplier']}.` : '';
      blockedNote.hidden = !general; set('knock-set-blocked', general);
    }
    const flags = live('knock.config.flags'), byHand = flags !== null && !(flags & 2);
    for (const f of fields) {
      const manualOnly = f.action === 'knock.center' && !byHand;
      f.input.disabled = blocked(f.action, f.esp32) || manualOnly;
      f.input.title = manualOnly ? 'Choose "Set by hand" to type a frequency' : why(f.action, f.esp32);
      const reported = live(f.key);
      if (reported !== null && !editing(f.input, f.action)) { const text = tidy(f.shown(reported)); if (f.input.value !== text) f.input.value = text; }
    }
    const enabled = live('knock.enabled');
    $('knock-set-on').classList.toggle('active', enabled === true);
    $('knock-set-off').classList.toggle('active', enabled === false);

    freqMode.disabled = blocked('knock.auto_frequency'); freqMode.title = why('knock.auto_frequency');
    freqMode.options[0].textContent = d.supported ? 'Found from the engine' : 'From the bore';
    if (flags !== null && !editing(freqMode, 'knock.center', 'knock.auto_frequency')) freqMode.value = byHand ? 'manual' : 'auto';
    bandwidth.disabled = blocked('knock.bandwidth'); bandwidth.title = why('knock.bandwidth');
    const width = live('knock.config.bandwidth_hz');
    if (width !== null && !editing(bandwidth, 'knock.bandwidth')) bandwidth.value = width < 1000 ? '9' : '15';
    $('knock-set-relearn').disabled = blocked('knock.relearn', true) || byHand;
    $('knock-set-relearn').title = byHand ? 'Only when the frequency is found from the engine' : why('knock.relearn', true);
    const filter = live('knock.freq.filter_hz') ?? live('knock.config.center_hz'), bore = live('knock.freq.bore_hz'), found = live('knock.freq.found_hz');
    set('knock-set-freq-note', !filter ? 'Waiting for the controller.' :
      `Listening at ${kHz(filter)}${byHand ? ', set by hand' : live('knock.freq.learned') ? ', learned from the engine' : d.supported ? ', the bore\'s figure until the engine has been heard under boost' : ', from the bore'}.` +
      `${bore ? ` The bore suggests ${kHz(bore)}.` : ''}${found ? ` The engine's own ringing points to ${kHz(found)}.` : ''}` +
      `${d.supported ? '' : ' Finding it from the engine needs the ESP32 controller.'}`);

    const step = live('knock.amp.step'), top = live('knock.amp.top_step'), gain = live('knock.amp.gain'), held = live('knock.amp.fixed');
    ampMode.disabled = blocked('knock.amp_gain', true); ampMode.title = why('knock.amp_gain', true);
    if (held !== null && !editing(ampMode, 'knock.amp_gain')) ampMode.value = held ? 'hold' : 'auto';
    ampStep.disabled = blocked('knock.amp_gain', true) || !held;
    ampStep.title = !held && d.supported ? 'Choose "Hold a position" to set it yourself' : why('knock.amp_gain', true);
    if (top !== null) ampStep.max = top;
    if (step !== null && !editing(ampStep, 'knock.amp_gain')) ampStep.value = step;
    set('knock-set-amp-note', !d.supported ? 'The gain is fixed by the circuit on this controller. Setting it from here needs the ESP32 controller and its gain potentiometer.' :
      gain === null ? 'Waiting for the controller.' :
      `${gain.toFixed(1)}× at position ${step} of ${top}, ${held ? 'held here' : live('knock.amp.automatic') ? 'set by the controller to keep normal engine noise in the lower part of its range' : 'not under control'}.` +
      `${live('knock.amp.ineffective') ? ' Changing the gain shows no effect: check the potentiometer and its three control wires.' : ''}` +
      `${live('knock.amp.overloaded') ? ' The signal clips even at the lowest gain.' : ''}${live('knock.amp.silent') ? ' Nothing is heard even at the highest gain.' : ''}`);
  }

  // ---------------------------------------------------------------- the page
  function view(name) {
    for (const each of ['live', 'settings']) {
      $(`knock-view-${each}`).hidden = each !== name;
      $(`knock-view-${each}-tab`).setAttribute('aria-selected', String(each === name));
    }
    render();
  }
  function render() {
    if (!$('knock-overlay').open) return;
    if ($('knock-view-settings').hidden) { renderLevel(); renderNumbers(); renderSpectrum(); }
    else { renderNumbers(); renderSettings(); }
  }
  $('knock-view-live-tab').onclick = () => view('live');
  $('knock-view-settings-tab').onclick = () => view('settings');
  $('knock-open-settings').onclick = () => { $('controls-dialog').close(); window.FrogdashKnock.open('settings'); };
  // What the controller answered, where the settings are.
  new MutationObserver(() => {
    const source = $('command-result'), target = $('knock-result');
    target.textContent = source.textContent; target.dataset.status = source.dataset.status || '';
  }).observe($('command-result'), {childList: true, characterData: true, subtree: true, attributes: true});

  window.FrogdashKnock = {open(name = 'live') { if (!$('knock-overlay').open) $('knock-overlay').showModal(); view(name); }, render};
  window.addEventListener('frogdash-state', event => {
    snapshot = event.detail.snapshot; connected = event.detail.connected;
    history.push({at: performance.now(), energy: live('knock.energy'), baseline: live('knock.baseline')});
    while (history.length > 600) history.shift();
    flush();
    render();
  });
})();
