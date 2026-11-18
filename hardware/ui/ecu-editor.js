/* The custom ECU editor: describe an engine computer's CAN frames on the dash's own screen.

   Opened from the setup wizard's ECU page (Custom ECU). The left column lists the CAN IDs on
   the bus right now (/raw); tapping one adds it as a frame. Each frame's bytes are shown live,
   and each reading in it is set with buttons: which bytes (a byte, two, four, a float, one
   bit, or any run of bits as a DBC file gives them), byte order, signed or not, scale and
   offset, and the unit the ECU sends it in. Its value is decoded from the bus as it is set,
   the same way the dash will (hardware/frogdash/ecu/__init__.py), so a wrong byte shows at once.

   A DBC file (many ECU makers publish one) can be imported: the dash reads its frames and
   guesses each reading from its name; guesses are marked to be checked. Done checks the
   profile on the dash (/system/custom/check); the wizard's Apply saves it as
   /etc/frogdash/ecu/custom.json with the rest of the setup.

   window.frogdashEcuEditor.open({profile, catalog, demo, onDone}). */
(() => {
  'use strict';
  const FROM_LABEL = {degF: '°F', K: 'K', psi: 'psi', bar: 'bar', mph: 'mph'};
  const FROM = {degF: v => (v - 32) * 5 / 9, K: v => v - 273.15, psi: v => v * 6.894757293168361, bar: v => v * 100, mph: v => v * 1.609344};
  const SPEEDS = [[125000, '125k'], [250000, '250k'], [500000, '500k'], [1000000, '1M']];
  const SIZES = [['u8', '1 byte'], ['u16', '2 bytes'], ['u32', '4 bytes'], ['f32', 'Float'], ['bit', '1 bit'], ['bits', 'Bits (DBC)']];
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const hex = (n, ext) => '0x' + n.toString(16).toUpperCase().padStart(ext ? 8 : 3, '0');
  const idOf = text => { const t = String(text).trim(); return /^0x[0-9a-f]{1,8}$/i.test(t) ? parseInt(t, 16) : /^\d{1,10}$/.test(t) ? Number(t) : NaN; };

  let prof = null, catalog = [], known = {}, demo = null, onDone = null, sel = {frame: 0, signal: 0}, bus = new Map(), timer = null, tick = 0;

  const dialog = document.createElement('dialog');
  dialog.id = 'ecu-editor'; dialog.className = 'workspace-dialog wizard ecu-editor'; dialog.setAttribute('aria-labelledby', 'ee-title');
  dialog.innerHTML = `<header class="wizard-head ee-head"><div><span class="eyebrow">CUSTOM ECU</span><h2 id="ee-title">ECU profile</h2></div>
      <div class="ee-top" id="ee-top"></div><button type="button" class="close-button" id="ee-cancel">Cancel ×</button></header>
    <section class="ee-body"><aside class="ee-col ee-bus"><h3>On the bus now</h3><p class="wizard-small">Tap an ID to read it.</p><div id="ee-bus"></div></aside>
      <div class="ee-col ee-frames" id="ee-frames"></div><div class="ee-col ee-signal" id="ee-signal"></div></section>
    <footer class="wizard-foot"><p id="ee-note" role="status"></p>
      <div class="wizard-nav"><label class="ee-import"><input type="file" id="ee-dbc" accept=".dbc,.json,text/plain" hidden>Import DBC</label>
        <button type="button" id="ee-export">Export</button><button type="button" id="ee-done" class="wizard-primary">Done</button></div></footer>`;
  document.body.append(dialog);
  const $ = id => dialog.querySelector('#' + id);
  const note = (text, bad = false) => { $('ee-note').textContent = text; $('ee-note').classList.toggle('bad', bad); };

  // --- Layouts: the same kinds as ecu/__init__.py ---
  function parse(layout) {
    let m;
    if ((m = /^([us])(8|16|32)(le)?@(\d)$/.exec(layout))) return {kind: 'u' + m[2], signed: m[1] === 's', little: !!m[3], byte: +m[4]};
    if ((m = /^f32(le)?@(\d)$/.exec(layout))) return {kind: 'f32', little: !!m[1], byte: +m[2]};
    if ((m = /^bit@(\d)\.(\d)$/.exec(layout))) return {kind: 'bit', byte: +m[1], bit: +m[2]};
    if ((m = /^nib@(\d)\.(\d)$/.exec(layout))) return {kind: 'bits', signed: false, little: true, start: +m[1] * 8 + +m[2], size: 4};
    if ((m = /^([us])(le|be)@(\d{1,2}):(\d{1,2})$/.exec(layout))) return {kind: 'bits', signed: m[1] === 's', little: m[2] === 'le', start: +m[3], size: +m[4]};
    return {kind: 'u8', signed: false, little: false, byte: 0};
  }
  function build(p) {
    if (p.kind === 'f32') return `f32${p.little ? 'le' : ''}@${p.byte}`;
    if (p.kind === 'bit') return `bit@${p.byte}.${p.bit}`;
    if (p.kind === 'bits') return `${p.signed ? 's' : 'u'}${p.little ? 'le' : 'be'}@${p.start}:${p.size}`;
    return `${p.signed ? 's' : 'u'}${p.kind.slice(1)}${p.little && p.kind !== 'u8' ? 'le' : ''}@${p.byte}`;
  }
  const width = p => ({u8: 1, u16: 2, u32: 4, f32: 4}[p.kind] || 0);
  // The frame's bits a layout reads, as [byte, bit] (for the byte boxes), or null if it does not fit.
  function covered(p, length) {
    const out = [];
    if (p.kind === 'bit') return p.byte < length ? [[p.byte, p.bit]] : null;
    if (p.kind === 'bits') {
      for (let i = 0; i < p.size; i++) {
        let at;
        if (p.little) at = p.start + i;                      // Intel: up from the start bit
        else { const first = Math.floor(p.start / 8) * 8 + 7 - p.start % 8; const pos = first + p.size - 1 - i; at = Math.floor(pos / 8) * 8 + 7 - pos % 8; }
        if (at < 0 || at >= length * 8) return null;
        out.push([Math.floor(at / 8), at % 8]);
      }
      return out;
    }
    if (p.byte + width(p) > length) return null;
    for (let b = p.byte; b < p.byte + width(p); b++) for (let i = 0; i < 8; i++) out.push([b, i]);
    return out;
  }
  function raw(p, bytes, length) {
    if (!bytes || bytes.length < length || !covered(p, length)) return null;
    if (p.kind === 'bit') return bytes[p.byte] >> p.bit & 1;
    if (p.kind === 'f32') return new DataView(Uint8Array.from(bytes).buffer).getFloat32(p.byte, p.little);
    if (p.kind === 'bits') {
      let all = 0n;
      const order = p.little ? [...bytes.slice(0, length)].reverse() : bytes.slice(0, length);
      for (const b of order) all = all << 8n | BigInt(b);
      const first = Math.floor(p.start / 8) * 8 + 7 - p.start % 8;
      const shift = p.little ? p.start : length * 8 - first - p.size;
      let v = Number(all >> BigInt(shift) & ((1n << BigInt(p.size)) - 1n));
      return p.signed && v >= 2 ** (p.size - 1) ? v - 2 ** p.size : v;
    }
    const n = width(p), part = bytes.slice(p.byte, p.byte + n);
    let v = (p.little ? [...part].reverse() : part).reduce((a, b) => a * 256 + b, 0);
    return p.signed && v >= 2 ** (8 * n - 1) ? v - 2 ** (8 * n) : v;
  }
  function value(spec, length, bytes) {
    const r = raw(parse(spec.layout), bytes, length);
    if (r === null || !Number.isFinite(r)) return null;
    let v = r * (Number(spec.scale ?? 1)) + Number(spec.offset ?? 0);
    if (spec.from && FROM[spec.from]) v = FROM[spec.from](v);
    return v;
  }
  const shown = v => v === null ? '—' : Math.abs(v) >= 1000 || Number.isInteger(v) ? String(Math.round(v * 100) / 100) : v.toFixed(Math.abs(v) < 10 ? 3 : 2);

  // --- The bus ---
  async function readBus() {
    if (demo) {                       // The preview: the reference car's frames, a new sample each second
      tick++;
      bus = new Map(demo.map(f => [`${f.extended ? 'x' : 's'}${f.id}`, {id: f.id, extended: f.extended, data: f.samples[tick % f.samples.length]}]));
      return;
    }
    try {
      const frames = await (await fetch('/raw', {cache: 'no-store'})).json();
      const newest = Math.max(0, ...frames.map(f => f.timestamp_ms || 0));
      bus = new Map(frames.filter(f => !f.error && !f.remote && newest - (f.timestamp_ms || 0) < 3000)
        .map(f => [`${f.extended ? 'x' : 's'}${f.id}`, {id: f.id, extended: f.extended, data: f.data}]));
    } catch { bus = new Map(); }
  }
  const bytesOf = data => (data || '').match(/../g)?.map(b => parseInt(b, 16)) || [];
  const heard = frame => { const id = idOf(frame.ids?.[0]); return bus.get(`${prof.extended ? 'x' : 's'}${id}`); };
  const frameIds = () => new Set(prof.frames.map(f => idOf(f.ids?.[0])));

  // --- Drawing ---
  function seg(key, options, now) {
    return `<div class="signal-sources">${options.map(([v, text]) => `<button type="button" data-ee-pick="${key}" data-value="${esc(v)}" aria-pressed="${String(now) === String(v)}">${esc(text)}</button>`).join('')}</div>`;
  }
  function drawTop() {
    $('ee-top').innerHTML = `<label class="ee-inline"><span>Name</span><input type="text" data-ee-field="label" value="${esc(prof.label)}" autocomplete="off" spellcheck="false"></label>
      <div class="ee-inline"><span>Bus speed</span>${seg('bitrate', SPEEDS, prof.bitrate)}</div>
      <div class="ee-inline"><span>IDs</span>${seg('extended', [[false, '11-bit'], [true, '29-bit']], !!prof.extended)}</div>`;
  }
  function drawBus() {
    const mine = frameIds();
    const rows = [...bus.values()].filter(f => !!f.extended === !!prof.extended).sort((a, b) => a.id - b.id);
    const other = bus.size - rows.length;
    $('ee-bus').innerHTML = (rows.length ? rows.map(f => `<button type="button" class="ee-bus-row${mine.has(f.id) ? ' mine' : ''}" data-ee-bus="${f.id}">
        <b>${hex(f.id, f.extended)}</b><code>${esc((f.data || '').replace(/(..)/g, '$1 ').trim())}</code><i>${mine.has(f.id) ? 'in profile' : '+ add'}</i></button>`).join('')
      : `<p class="wizard-small">${demo ? 'Nothing in the preview.' : 'Nothing heard in the last 3 s: is the ECU on, at this bus speed?'}</p>`)
      + (other ? `<p class="wizard-small">${other} ${prof.extended ? '11' : '29'}-bit ID${other === 1 ? '' : 's'} not shown.</p>` : '');
  }
  function label(key) { return known[key]?.[0] || key; }
  function drawFrames() {
    const f = prof.frames[sel.frame];
    const tabs = prof.frames.map((fr, i) => `<button type="button" data-ee-frame="${i}" aria-pressed="${i === sel.frame}">${esc(fr.ids?.[0] || '?')}<small>${fr.signals.length}</small></button>`).join('');
    let body = `<p class="wizard-lead">No frames yet. Tap an ID on the bus, add one by hand, or import your ECU's DBC file.</p>`;
    if (f) {
      body = `<div class="ee-frame-fields"><label class="ee-inline"><span>CAN ID</span><input type="text" data-ee-field="frame.id" value="${esc(f.ids?.[0] || '')}" autocomplete="off" spellcheck="false"></label>
          <label class="ee-inline"><span>Name</span><input type="text" data-ee-field="frame.name" value="${esc(f.name || '')}" autocomplete="off" spellcheck="false"></label>
          <div class="ee-inline"><span>Bytes</span>${seg('frame.length', [1, 2, 3, 4, 5, 6, 7, 8].map(n => [n, n]), f.length || 8)}</div>
          <button type="button" class="ee-remove" data-ee-remove="frame">Remove frame</button></div>
        <div class="ee-bytes" id="ee-bytes"></div>
        <div class="ee-signals">${f.signals.map((s, i) => `<button type="button" class="ee-sig-row" data-ee-signal="${i}" aria-pressed="${i === sel.signal}">
            <b>${esc(label(s.key))}${s.guessed === false ? ' <em>check</em>' : ''}</b><code>${esc(s.layout)}${s.scale !== undefined && s.scale !== 1 ? ` × ${esc(s.scale)}` : ''}${s.offset ? ` ${s.offset > 0 ? '+' : '−'} ${esc(Math.abs(s.offset))}` : ''}${s.from ? ` from ${FROM_LABEL[s.from]}` : ''}</code>
            <span class="ee-value" data-ee-value="${i}"></span></button>`).join('')}
          <button type="button" class="ee-add" data-ee-add="signal">+ Add a reading</button></div>`;
    }
    $('ee-frames').innerHTML = `<div class="ee-tabs">${tabs}<button type="button" class="ee-add" data-ee-add="frame">+ Frame</button></div>${body}`;
  }
  function drawSignal() {
    const f = prof.frames[sel.frame], s = f?.signals[sel.signal];
    if (!s) { $('ee-signal').innerHTML = f ? '<p class="wizard-small">Add a reading to this frame.</p>' : ''; return; }
    const p = parse(s.layout), entry = known[s.key], units = entry ? entry.slice(1) : [];
    const options = catalog.map(([group, items]) => `<optgroup label="${esc(group)}">${items.map(([key, text, unit]) =>
      `<option value="${key}"${key === s.key ? ' selected' : ''}>${esc(text)}${unit ? ` (${esc(unit)})` : ''}</option>`).join('')}</optgroup>`).join('');
    const other = !entry;
    const where = p.kind === 'bits'
      ? `<div class="ee-pair"><label class="ee-inline"><span>Start bit</span><input type="text" inputmode="numeric" data-ee-field="bits.start" value="${p.start}"></label>
         <label class="ee-inline"><span>Length</span><input type="text" inputmode="numeric" data-ee-field="bits.size" value="${p.size}"></label></div>
         <div class="ee-inline"><span>Order</span>${seg('little', [[false, 'Motorola'], [true, 'Intel']], p.little)}</div>`
      : `<div class="ee-inline"><span>Byte</span>${seg('byte', Array.from({length: f.length || 8}, (_, i) => [i, i]), p.byte)}</div>
         ${p.kind === 'bit' ? `<div class="ee-inline"><span>Bit</span>${seg('bit', [0, 1, 2, 3, 4, 5, 6, 7].map(n => [n, n]), p.bit)}</div>` : ''}
         ${width(p) > 1 ? `<div class="ee-inline"><span>Order</span>${seg('little', [[false, 'Big-endian (Motorola)'], [true, 'Little-endian (Intel)']], p.little)}</div>` : ''}`;
    $('ee-signal').innerHTML = `<label class="wizard-field"><span>Reading</span><select data-ee-field="key">${options}<option value=""${other ? ' selected' : ''}>Something else…</option></select></label>
      ${other ? `<label class="ee-inline"><span>ecu.</span><input type="text" data-ee-field="other" value="${esc(s.key.replace(/^ecu\./, ''))}" placeholder="name, a-z 0-9 _" autocomplete="off" spellcheck="false"></label><p class="wizard-small">Kept in the drive logs; the gauges show the readings in the list.</p>` : ''}
      <div class="ee-inline"><span>Size</span>${seg('kind', SIZES.map(([k, t]) => [k, t]), p.kind)}</div>
      ${['u8', 'u16', 'u32', 'bits'].includes(p.kind) ? `<div class="ee-inline"><span>Sign</span>${seg('signed', [[false, 'Unsigned'], [true, 'Signed']], p.signed)}</div>` : ''}
      ${where}
      <div class="ee-pair"><label class="ee-inline"><span>Scale ×</span><input type="text" inputmode="decimal" data-ee-field="scale" value="${esc(s.scale ?? 1)}"></label>
        <label class="ee-inline"><span>Offset +</span><input type="text" inputmode="decimal" data-ee-field="offset" value="${esc(s.offset ?? 0)}"></label></div>
      ${units.length > 1 ? `<div class="ee-inline"><span>ECU sends</span>${seg('from', units.map((u, i) => [i ? u : '', i ? FROM_LABEL[u] : u]), s.from || '')}</div>` : ''}
      <div class="ee-live" id="ee-live"></div>
      <button type="button" class="ee-remove" data-ee-remove="signal">Remove reading</button>`;
  }
  // The parts that change with the bus: redrawn each second without touching the fields.
  function live() {
    drawBus();
    const f = prof.frames[sel.frame];
    if (!f) return;
    const length = f.length || 8, got = heard(f), bytes = got ? bytesOf(got.data) : null;
    const s = f.signals[sel.signal], mark = new Set((s && covered(parse(s.layout), length) || []).map(([b, i]) => `${b}.${i}`));
    const box = $('ee-bytes');
    if (box) box.innerHTML = Array.from({length}, (_, b) => `<button type="button" class="ee-byte${[...Array(8).keys()].some(i => mark.has(`${b}.${i}`)) ? ' on' : ''}" data-ee-byte="${b}">
        <small>byte ${b}</small><b>${bytes && b < bytes.length ? bytes[b].toString(16).toUpperCase().padStart(2, '0') : '··'}</b>
        <span class="ee-bits">${[7, 6, 5, 4, 3, 2, 1, 0].map(i => `<i class="${mark.has(`${b}.${i}`) ? 'on' : ''}${bytes && bytes[b] >> i & 1 ? ' set' : ''}"></i>`).join('')}</span></button>`).join('')
      + `<p class="wizard-small ee-heard">${got ? 'Live from the bus' : `${f.ids?.[0] || 'This ID'} is not on the bus now`}</p>`;
    dialog.querySelectorAll('[data-ee-value]').forEach(el => {
      const spec = f.signals[Number(el.dataset.eeValue)];
      el.textContent = bytes ? shown(value(spec, length, bytes)) : '—';
    });
    const panel = $('ee-live');
    if (panel && s) {
      const p = parse(s.layout), r = bytes ? raw(p, bytes, length) : null, v = bytes ? value(s, length, bytes) : null;
      const unit = known[s.key]?.[1] || '';
      panel.innerHTML = !covered(p, length) ? `<b class="bad">Outside the frame's ${length} bytes</b>`
        : `<span>Raw <b>${r === null ? '—' : shown(r)}</b></span><span>Value <b>${shown(v)}</b> ${esc(unit)}</span>`;
    }
  }
  function draw() {
    drawTop(); drawFrames(); drawSignal(); live();
  }

  // --- Changes ---
  function signalChange(key, raw) {
    const f = prof.frames[sel.frame], s = f?.signals[sel.signal];
    if (!s) return;
    const p = parse(s.layout);
    if (key === 'kind') {
      const was = p.kind === 'bits' ? Math.floor(p.start / 8) : p.byte || 0;
      const next = raw === 'bits' ? {kind: 'bits', signed: false, little: p.little, start: p.kind === 'bits' ? p.start : (p.little ? was * 8 : was * 8 + 7), size: p.size || 8}
        : raw === 'bit' ? {kind: 'bit', byte: was, bit: 0} : {kind: raw, signed: !!p.signed, little: !!p.little, byte: Math.min(was, (f.length || 8) - ({u8: 1, u16: 2, u32: 4, f32: 4}[raw]))};
      if (next.byte < 0) next.byte = 0;
      s.layout = build(next);
    } else if (['byte', 'bit', 'little', 'signed'].includes(key)) {
      p[key] = key === 'little' || key === 'signed' ? raw === 'true' : Number(raw);
      s.layout = build(p);
    } else if (key === 'from') {
      if (raw) s.from = raw; else delete s.from;
    }
    s.guessed = undefined;
  }
  dialog.addEventListener('click', event => {
    const t = event.target;
    const pick = t.closest('[data-ee-pick]');
    if (pick) {
      const key = pick.dataset.eePick, raw = pick.dataset.value;
      if (key === 'bitrate') prof.bitrate = Number(raw);
      else if (key === 'extended') prof.extended = raw === 'true';
      else if (key === 'frame.length') prof.frames[sel.frame].length = Number(raw);
      else signalChange(key, raw);
      draw(); return;
    }
    const busRow = t.closest('[data-ee-bus]');
    if (busRow) {
      const id = Number(busRow.dataset.eeBus), at = prof.frames.findIndex(f => idOf(f.ids?.[0]) === id);
      if (at >= 0) sel = {frame: at, signal: 0};
      else {
        const got = bus.get(`${prof.extended ? 'x' : 's'}${id}`);
        prof.frames.push({name: '', ids: [hex(id, prof.extended)], length: Math.max(1, bytesOf(got?.data).length || 8), signals: []});
        prof.frames.sort((a, b) => idOf(a.ids[0]) - idOf(b.ids[0]));
        sel = {frame: prof.frames.findIndex(f => idOf(f.ids?.[0]) === id), signal: 0};
      }
      draw(); return;
    }
    const tab = t.closest('[data-ee-frame]');
    if (tab) { sel = {frame: Number(tab.dataset.eeFrame), signal: 0}; draw(); return; }
    const row = t.closest('[data-ee-signal]');
    if (row) { sel.signal = Number(row.dataset.eeSignal); draw(); return; }
    const byte = t.closest('[data-ee-byte]');
    if (byte) {
      const s = prof.frames[sel.frame]?.signals[sel.signal];
      if (s) {
        const p = parse(s.layout), b = Number(byte.dataset.eeByte);
        if (p.kind === 'bits') p.start = p.little ? b * 8 : b * 8 + 7; else p.byte = Math.min(b, Math.max(0, (prof.frames[sel.frame].length || 8) - (width(p) || 1)));
        s.layout = build(p); draw();
      }
      return;
    }
    const add = t.closest('[data-ee-add]');
    if (add) {
      if (add.dataset.eeAdd === 'frame') {
        const used = frameIds(); let id = prof.extended ? 0x18FF0000 : 0x600;
        while (used.has(id)) id++;
        prof.frames.push({name: '', ids: [hex(id, prof.extended)], length: 8, signals: []});
        sel = {frame: prof.frames.length - 1, signal: 0};
      } else {
        const f = prof.frames[sel.frame], taken = new Set(prof.frames.flatMap(fr => fr.signals.map(s => s.key)));
        const key = catalog.flatMap(([, items]) => items.map(i => i[0])).find(k => !taken.has(k)) || 'ecu.reading';
        f.signals.push({key, layout: 'u8@0', scale: 1, offset: 0});
        sel.signal = f.signals.length - 1;
      }
      draw(); return;
    }
    const remove = t.closest('[data-ee-remove]');
    if (remove) {
      if (remove.dataset.eeRemove === 'frame') { prof.frames.splice(sel.frame, 1); sel = {frame: Math.max(0, sel.frame - 1), signal: 0}; }
      else { prof.frames[sel.frame].signals.splice(sel.signal, 1); sel.signal = Math.max(0, sel.signal - 1); }
      draw();
    }
  });
  dialog.addEventListener('change', event => {
    const field = event.target.closest('[data-ee-field]');
    if (!field) return;
    const key = field.dataset.eeField, v = field.value.trim();
    const f = prof.frames[sel.frame], s = f?.signals[sel.signal];
    if (key === 'label') prof.label = v.slice(0, 60) || 'My ECU';
    else if (key === 'frame.name') f.name = v.slice(0, 40);
    else if (key === 'frame.id') {
      const id = idOf(v);
      if (Number.isNaN(id) || id > (prof.extended ? 0x1FFFFFFF : 0x7FF)) note(`${v} is not a${prof.extended ? ' 29' : 'n 11'}-bit CAN ID: write it as 0x360 or as a number`, true);
      else { f.ids = [hex(id, prof.extended)]; note(''); }
    } else if (key === 'key') {
      s.key = v || (known[s.key] ? 'ecu.my_reading' : s.key);     // Something else: a name of its own, typed below
      s.guessed = undefined;
      if (!(known[s.key]?.length > 2)) delete s.from;
    }
    else if (key === 'other') { const name = v.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 48); if (name) s.key = 'ecu.' + name; }
    else if (key === 'scale' || key === 'offset') {
      const n = Number(v.replace(',', '.'));
      if (!Number.isFinite(n) || (key === 'scale' && n === 0)) note(`${key === 'scale' ? 'Scale' : 'Offset'} should be a number${key === 'scale' ? ' (not 0)' : ''}`, true);
      else { s[key] = n; note(''); }
    } else if (key === 'bits.start' || key === 'bits.size') {
      const p = parse(s.layout), n = Number(v);
      if (Number.isInteger(n) && n >= (key === 'bits.size' ? 1 : 0) && n <= (key === 'bits.size' ? 32 : 63)) { p[key.slice(5)] = n; s.layout = build(p); }
    }
    draw();
  });

  // --- Checking, import, export ---
  function cleaned() {
    const out = JSON.parse(JSON.stringify(prof));
    out.frames.forEach(f => { if (!f.name) f.name = f.ids[0]; f.signals.forEach(s => { delete s.guessed; if (s.scale === 1) delete s.scale; if (!s.offset) delete s.offset; }); });
    return out;
  }
  function problems(p) {
    if (!p.frames.length) return 'Add at least one frame';
    const seen = new Set();
    for (const f of p.frames) {
      const id = idOf(f.ids[0]);
      if (seen.has(id)) return `${f.ids[0]} is listed twice`;
      seen.add(id);
      if (!f.signals.length) return `${f.ids[0]} has no readings: add one or remove the frame`;
      for (const s of f.signals) if (!covered(parse(s.layout), f.length || 8)) return `${f.ids[0]}: ${label(s.key)} is outside the frame's ${f.length} bytes`;
    }
    const keys = p.frames.flatMap(f => f.signals.map(s => s.key));
    const twice = keys.find((k, i) => keys.indexOf(k) !== i);
    return twice ? `${label(twice)} is read from two places: keep one` : '';
  }
  $('ee-done').onclick = async () => {
    const out = cleaned(), problem = problems(out);
    if (problem) { note(problem, true); return; }
    if (!demo) {
      try {
        const response = await fetch('/system/custom/check', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({profile: out})});
        if (!response.ok) throw new Error(await response.text());
      } catch (error) { note(`Not right yet: ${error.message || error}`, true); return; }
    }
    close(); onDone?.(out);
  };
  $('ee-cancel').onclick = () => close();
  $('ee-export').onclick = () => {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([JSON.stringify(cleaned(), null, 1)], {type: 'application/json'}));
    link.download = 'custom.json'; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  };
  $('ee-dbc').onchange = async event => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const text = await file.text();
    if (/^\s*\{/.test(text)) {                                 // A profile exported before
      try {
        const loaded = JSON.parse(text);
        if (!Array.isArray(loaded.frames)) throw new Error('no frames');
        prof = {...loaded, id: 'custom'}; sel = {frame: 0, signal: 0}; note(`Loaded ${file.name}: ${prof.frames.length} frames`); draw();
      } catch (error) { note(`${file.name} is not a profile: ${error.message}`, true); }
      return;
    }
    if (demo) { note('Preview: a DBC file is read by the dash itself', true); return; }
    note(`Reading ${file.name}…`);
    try {
      const response = await fetch('/system/custom/dbc', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})});
      if (!response.ok) throw new Error(await response.text());
      const got = await response.json(), have = frameIds();
      const added = got.frames.filter(f => !have.has(idOf(f.ids[0])));
      if (!prof.frames.length) prof.extended = got.extended;
      prof.frames.push(...added); prof.frames.sort((a, b) => idOf(a.ids[0]) - idOf(b.ids[0]));
      const check = added.reduce((n, f) => n + f.signals.filter(s => s.guessed === false).length, 0);
      note(`${file.name}: ${added.length} frames added${got.frames.length > added.length ? ` (${got.frames.length - added.length} already here)` : ''}.`
        + `${check ? ` ${check} readings marked "check" kept their own names: pick what each is.` : ''}${got.skipped.length ? ` Left out: ${got.skipped.slice(0, 3).join('; ')}${got.skipped.length > 3 ? '…' : ''}` : ''}`);
      sel = {frame: 0, signal: 0}; draw();
    } catch (error) { note(`Not imported: ${error.message || error}`, true); }
  };

  function close() { clearInterval(timer); timer = null; if (dialog.open) dialog.close(); }
  async function open(options) {
    catalog = options.catalog || [];
    known = Object.fromEntries(catalog.flatMap(([, items]) => items.map(([key, text, ...units]) => [key, [text, ...units]])));
    demo = options.demo || null; onDone = options.onDone;
    prof = JSON.parse(JSON.stringify(options.profile || {id: 'custom', label: 'My ECU', bitrate: 500000, extended: false, status: 'documented', frames: []}));
    prof.frames = prof.frames || [];
    sel = {frame: 0, signal: 0}; note('');
    if (!dialog.open) dialog.showModal();
    await readBus(); draw();
    clearInterval(timer);
    timer = setInterval(async () => { await readBus(); if (dialog.open) live(); }, 1000);
  }
  window.frogdashEcuEditor = {open, parse, build, raw, value};
})();
