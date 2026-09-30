/* Taillight studio: modes, 33 shows, test overrides and one-shots over CAN, plus an
   LED-accurate mirror of both lamps. The mirror plays frames recorded from the actual
   CustomTaillights firmware (tools/taillight_recorder), chosen from live telemetry. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const STATES = ['Off', 'Running', 'Brake', 'Turn', 'Reverse', 'Brake + turn', 'Hazard'];
  const PARKED = ['lighting.show', 'lighting.demo', 'lighting.override', 'lighting.custom'];
  const DEMO_STEP_MS = 5000; // CustomTaillights canbus.cpp: demo advances every 5 s.
  // Physical order: driver lamp on the left, passenger on the right, outer edges outward.
  const LAMP = {strip: [21, 5], main: [17, 10], bytes: 590};

  const dialog = document.createElement('dialog');
  dialog.id = 'taillight-dialog'; dialog.className = 'workspace-dialog taillight-dialog';
  dialog.setAttribute('aria-labelledby', 'taillight-title');
  dialog.innerHTML = `<header class="dialog-header"><div><span class="eyebrow">CUSTOM TAILLIGHTS</span><h2 id="taillight-title">Taillights</h2><p id="tl-status">Waiting for the taillight controller</p></div>
    <nav class="appearance-tabs" role="tablist" aria-label="Taillight sections">${[['modes', 'Mode'], ['shows', 'Shows'], ['tests', 'Test & effects']].map(([key, label], i) =>
      `<button id="tl-tab-${key}" data-tl-tab="${key}" type="button" role="tab" aria-selected="${!i}" aria-controls="tl-panel-${key}"${i ? ' tabindex="-1"' : ''}>${label}</button>`).join('')}</nav>
    <button type="button" class="tl-normal" data-action="lighting.clear">Normal lights</button>
    <button id="tl-close" class="close-button" type="button">Close <span aria-hidden="true">×</span></button></header>
  <div class="tl-body">
    <section class="tl-mirror" aria-label="Live taillight mirror"><canvas id="tl-canvas" width="880" height="400" aria-hidden="true"></canvas>
      <div class="tl-sides"><div><strong>Driver</strong><span id="tl-left-state">—</span><span id="tl-left-inputs" class="tl-inputs"></span></div><p id="tl-mirror-note"></p><div><strong>Passenger</strong><span id="tl-right-state">—</span><span id="tl-right-inputs" class="tl-inputs"></span></div></div>
    </section>
    <div class="tl-controls">
      <p id="tl-gate" class="tl-gate"></p>
      <section id="tl-panel-modes" role="tabpanel" aria-labelledby="tl-tab-modes" class="tl-panel">
        <h3>Turn signals</h3><div class="control-row"><button type="button" data-action="lighting.mode" data-value="0">STOCK</button><button type="button" data-action="lighting.mode" data-value="1">SEQUENTIAL</button></div>
        <h3>Brightness</h3><label class="tl-range" for="tl-brightness">Level <output id="tl-brightness-value">255</output></label><input id="tl-brightness" type="range" min="0" max="255" step="5" value="255">
        <button type="button" data-action="lighting.brightness" data-input="tl-brightness">APPLY BRIGHTNESS</button>
        <p class="control-note">Stock/Sequential and brightness work anytime. Brake and reverse always come from the car, whatever is selected.</p>
      </section>
      <section id="tl-panel-shows" role="tabpanel" aria-labelledby="tl-tab-shows" class="tl-panel" hidden>
        <div id="tl-shows" class="tl-shows" data-wheel-grid></div>
        <div class="control-row"><button type="button" data-action="lighting.demo">DEMO · CYCLE ALL</button></div>
      </section>
      <section id="tl-panel-tests" role="tabpanel" aria-labelledby="tl-tab-tests" class="tl-panel" hidden>
        <h3>Test each side</h3><div class="tl-pair"><label for="tl-left">Driver<select id="tl-left">${STATES.map((s, i) => `<option value="${i}"${i === 2 ? ' selected' : ''}>${s}</option>`).join('')}</select></label>
          <label for="tl-right">Passenger<select id="tl-right">${STATES.map((s, i) => `<option value="${i}"${i === 2 ? ' selected' : ''}>${s}</option>`).join('')}</select></label>
          <button type="button" data-action="lighting.override" data-compute="override">TEST</button></div>
        <h3>One-shot effects</h3><div class="control-row"><button type="button" data-action="lighting.custom" data-value="1">BRAKE CHECK</button><button type="button" data-action="lighting.custom" data-value="2">AMBER FLASH</button></div>
        <div class="tl-pair"><label for="tl-text">Scroll 2 characters<input id="tl-text" type="text" maxlength="2" value="V8" autocomplete="off"></label><button type="button" data-action="lighting.custom" data-compute="text">SCROLL</button></div>
      </section>
    </div>
  </div>`;
  document.body.append(dialog);

  let index = null, frames = null, loadError = '', latest = {}, connected = false, animation = null;
  let requested = null; // {kind: 'show', index} | {kind: 'demo', since} made from this dash.
  let turnStyle = 'seq';
  const sides = [{key: null, since: 0}, {key: null, since: 0}];
  const SHOW_NAMES = [];

  async function load() {
    try {
      const [meta, packed] = await Promise.all([fetch('taillights/frames.json').then(r => r.json()), fetch('taillights/frames.bin').then(r => r.arrayBuffer())]);
      const stream = new Blob([packed]).stream().pipeThrough(new DecompressionStream('deflate'));
      frames = new Uint8Array(await new Response(stream).arrayBuffer());
      index = Object.fromEntries(meta.clips.map(clip => [clip.name, clip]));
      index.fps = meta.fps;
      meta.clips.filter(c => c.group === 'show').forEach(c => { SHOW_NAMES[+c.name.split('-')[1]] = c.title; });
      buildShows();
    } catch (error) { loadError = 'Mirror recordings unavailable here'; buildShows(); }
  }
  // Buttons are created once, before app.js wires every [data-action]; loading only relabels them.
  function buildShows() {
    const grid = $('tl-shows');
    if (!grid.children.length) for (let i = 0; i < 33; i++) {
      const b = document.createElement('button'); b.type = 'button';
      Object.assign(b.dataset, {action: 'lighting.show', value: String(i)});
      b.addEventListener('click', () => { requested = {kind: 'show', index: i, at: performance.now()}; });
      grid.append(b);
    }
    [...grid.children].forEach((b, i) => { b.innerHTML = `<small>${String(i).padStart(2, '0')}</small>${SHOW_NAMES[i] || `Show ${i}`}`; });
  }

  const live = key => { const v = latest.values?.[key]; return connected && v?.quality === 'live' ? v.value : null; };
  function clipFor(side, state, now) {
    const lr = side ? 'right' : 'left';
    switch (state) {
      case 'SHOW': {
        if (requested?.kind === 'demo') {
          const step = Math.floor((now - requested.since) / DEMO_STEP_MS);
          return {clip: `show-${step % 33}`, lamp: side, since: requested.since + step * DEMO_STEP_MS, label: `Demo · ${SHOW_NAMES[step % 33] || ''}`};
        }
        const n = requested?.kind === 'show' ? requested.index : 0;
        return {clip: `show-${n}`, lamp: side, label: requested?.kind === 'show' ? `Show · ${SHOW_NAMES[n] || n}` : 'Show started from the taillight Wi-Fi page (shown as Rainbow)'};
      }
      case 'TURN': return {clip: `turn-${lr}-${turnStyle}`, lamp: side};
      case 'BRAKE_TURN': return {clip: `brake-turn-${lr}-${turnStyle}`, lamp: side};
      case 'HAZARD': return {clip: `hazard-${turnStyle}`, lamp: side};
      case 'RUNNING': return {clip: 'running', lamp: side};
      case 'BRAKE': return {clip: 'brake', lamp: side};
      case 'REVERSE': return {clip: 'reverse', lamp: side};
      case 'OFF': return {clip: 'off', lamp: side};
      case 'CUSTOM': return {clip: 'off', lamp: side, label: 'One-shot effect playing on the lights'};
      default: return null;
    }
  }
  function paint(now) {
    const canvas = $('tl-canvas'), ctx = canvas.getContext('2d'), W = canvas.width, H = canvas.height;
    ctx.fillStyle = '#060708'; ctx.fillRect(0, 0, W, H);
    const cols = 21 * 2 + 5 + 2, rows = 5 + 5 + 10 + 2 + 2, s = Math.min(W / cols, H / rows);
    const ox = (W - cols * s) / 2, oy = (H - rows * s) / 2;
    const brightness = live('lighting.brightness');
    const gain = brightness === null ? 1 : .35 + .65 * brightness / 255;
    let note = loadError || (!connected ? 'No taillight data' : '');
    for (let side = 0; side < 2; side++) {
      const state = live(`lighting.${side ? 'right' : 'left'}_state`);
      const source = frames && state ? clipFor(side, state, now) : null;
      const key = source ? source.clip : null;
      if (key !== sides[side].key) sides[side] = {key, since: now};
      if (source?.label) note = source.label;
      const clip = source && index[source.clip];
      const start = source?.since ?? sides[side].since;
      const frame = clip ? Math.floor((now - start) / (1000 / index.fps)) % clip.frames : 0;
      const base = clip ? clip.offset + Math.max(0, frame) * LAMP.bytes * 2 + source.lamp * LAMP.bytes : -1;
      const lampX = ox + side * (21 + 5) * s;
      // Segments stacked as in the firmware's own preview: top strip, bottom strip, main panel.
      for (const [seg, w, h, rowOffset, colOffset] of [[0, 21, 5, 0, 0], [1, 21, 5, 6, 0], [2, 17, 10, 12, 2]]) {
        for (let row = 0; row < h; row++) for (let x = 0; x < w; x++) {
          const col = w - 1 - x; // Outer edges outward: recorded sweeps run from the car's centre.
          let r = 0, g = 0, b = 0;
          if (base >= 0) {
            if (seg === 0) { const i = base + (row * 21 + (row % 2 ? 20 - col : col)) * 3; r = frames[i]; g = frames[i + 1]; b = frames[i + 2]; }
            else if (seg === 1) r = frames[base + 315 + row * 21 + (row % 2 ? 20 - col : col)];
            else { const rr = 9 - row; r = frames[base + 420 + rr * 17 + (rr % 2 ? 16 - col : col)]; }
          }
          const lit = r + g + b > 0;
          ctx.fillStyle = lit ? `rgb(${Math.round(r * gain)},${Math.round(g * gain)},${Math.round(b * gain)})` : (seg ? '#1a0b0c' : '#16181c');
          ctx.fillRect(lampX + (x + colOffset) * s + s * .12, oy + (row + rowOffset) * s + s * .12, s * .76, s * .76);
        }
      }
    }
    $('tl-mirror-note').textContent = note;
  }
  function frame(now) { paint(now); animation = requestAnimationFrame(frame); }

  function inputs(mask) {
    if (!Number.isInteger(mask)) return '';
    return [[1, 'BRAKE'], [2, 'RUN'], [4, 'TURN'], [8, 'REV']].filter(([bit]) => mask & bit).map(([, name]) => name).join(' · ') || 'no inputs';
  }
  function render() {
    const controls = latest.controls || {reasons: {}};
    const temp = live('lighting.die_c'), derate = live('lighting.thermal_derate'), brightness = live('lighting.brightness');
    $('tl-status').textContent = live('lighting.left_state') === null ? 'Taillight controller offline or no data' :
      `Live · brightness ${brightness ?? '—'} / 255${temp !== null ? ` · ${temp} °C` : ''}${derate ? ` · thermal dimming ${derate}` : ''}`;
    for (const [side, name] of [['left', 'driver'], ['right', 'passenger']]) {
      const state = live(`lighting.${side}_state`);
      $(`tl-${side}-state`).textContent = state === null ? 'No data' : state.replace('_', ' + ');
      $(`tl-${side}-inputs`).textContent = inputs(live(`lighting.${name}_inputs`));
    }
    $('tl-gate').textContent = controls.reasons['lighting.show'] || 'Parked: shows and tests available. They stop automatically if the car starts moving.';
    $('tl-gate').dataset.blocked = String(!!controls.reasons['lighting.show']);
    // Forget the requested show once it has ended (normal lights, auto-clear, or another source).
    if (requested && performance.now() - requested.at > 2000 && !controls.lighting_active && !['SHOW', 'CUSTOM'].includes(live('lighting.left_state'))) requested = null;
    $('tl-brightness-value').textContent = $('tl-brightness').value;
  }
  window.addEventListener('frogdash-state', event => {
    latest = event.detail.snapshot; connected = event.detail.connected;
    if (dialog.open) render();
  });

  function compute(kind) {
    if (kind === 'override') return Number($('tl-left').value) << 4 | Number($('tl-right').value);
    const text = $('tl-text').value.toUpperCase().padEnd(2, ' ');
    if (!/^[\x20-\x7E]{2}$/.test(text)) return null;
    return 3 << 16 | text.charCodeAt(0) << 8 | text.charCodeAt(1);
  }
  for (const button of dialog.querySelectorAll('[data-compute]')) button.addEventListener('click', () => {
    const value = compute(button.dataset.compute);
    if (value !== null) window.FrogdashControls?.send(button.dataset.action, value);
  });
  dialog.querySelector('[data-action="lighting.demo"]').addEventListener('click', () => { requested = {kind: 'demo', since: performance.now(), at: performance.now()}; });
  dialog.querySelector('.tl-normal').addEventListener('click', () => { requested = null; });
  for (const button of dialog.querySelectorAll('[data-action="lighting.mode"]')) button.addEventListener('click', () => { turnStyle = button.dataset.value === '0' ? 'stock' : 'seq'; });
  $('tl-brightness').addEventListener('input', () => { $('tl-brightness-value').textContent = $('tl-brightness').value; });

  const tabs = [...dialog.querySelectorAll('[data-tl-tab]')];
  tabs.forEach(tab => tab.addEventListener('click', () => {
    for (const other of tabs) {
      const on = other === tab;
      other.setAttribute('aria-selected', String(on)); other.tabIndex = on ? 0 : -1;
      $(`tl-panel-${other.dataset.tlTab}`).hidden = !on;
    }
  }));
  function open() {
    if (!frames && !loadError) load();
    dialog.showModal(); render();
    animation = requestAnimationFrame(frame);
  }
  $('tl-close').onclick = () => dialog.close();
  dialog.addEventListener('close', () => cancelAnimationFrame(animation));
  document.getElementById('tl-launch')?.addEventListener('click', open);
  buildShows();
  window.FrogdashTaillights = {open, get requested() { return requested; }};
})();
