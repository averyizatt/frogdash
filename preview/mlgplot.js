/* Log viewer (Drive > Log viewer): the dash's MLG logs, MegaLogViewer style.
   (Named mlgplot, not logview: blockers' privacy lists drop files named like logging, and the
   owner's browser never loaded logview.js, November 2026.)
   First the logs, as a list to choose from; then the chosen one, six ways:
   - Graph: the channels picked beside it, on one graph or stacked one under another, each on
     its own scale (fitting the screen or the whole log). Drag to zoom; tap to put mark A, and
     each channel shows its change from A. Play runs the cursor through the drive; Find jumps
     to each time a condition comes true (RPM > 6000 and AFR > 13); bookmarks and alerts are
     marks on the time line. Ready-made and saved layouts; calculated fields from formulas.
   - Scatter: one channel against another, coloured by a third.
   - Table: a third channel's average (lowest, highest, samples, time) in cells of two others,
     like a VE table.
   - Data: the rows themselves. Track: the GPS position, coloured by a channel.
   - Summary: the drive's peaks and where they were, and each channel's lowest, average, highest.
   Scatter, Table and Track can take only the rows where a condition holds (warm engine, boost).
   The Pi reads only the channels and the time asked for (hardware/frogdash/logview.py): the
   graph thinned so a spike is never lost, the rest as whole rows. Drawn with uPlot
   (uPlot.iife.min.js, MIT) and canvas. */
(() => {
  'use strict';
  const host = document.getElementById('log-viewer');
  if (!host) return;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
  const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
  const COLORS = ['#ffb14a', '#5fd0ff', '#8befc4', '#ff6b8b', '#c59bff', '#f2e46b', '#ff8f3d', '#7aa7ff'];
  const MOST = COLORS.length, SAMPLE = 20000;
  const STORE = 'frogdash-logview-channels', CALC_STORE = 'frogdash-logview-calc', LAYOUT_STORE = 'frogdash-logview-layouts', OPTION_STORE = 'frogdash-logview-options';
  // What a fresh viewer shows: what a tuner looks at first, from what the log has.
  const DEFAULTS = ['RPM', 'AFR', 'AFR Target 1', 'Boost psi'];
  const PRESETS = [['Fueling', ['RPM', 'AFR', 'AFR Target 1', 'EGO cor1', 'PW', 'VE1']], ['Boost', ['RPM', 'Boost psi', 'MAP', 'TPS', 'Meth flow']],
    ['Ignition', ['RPM', 'SPK: Spark Advance', 'MAP', 'MAT', 'Dwell']], ['Temperatures and pressures', ['CLT', 'MAT', 'OilPressure', 'FuelPressure', 'Batt V']],
    ['Water/meth', ['Boost psi', 'Meth flow', 'Meth % of fuel', 'Intake before inj', 'Intake after inj', 'Injection temp drop']],
    ['Driving', ['Vehicle Speed', 'RPM', 'TPS', 'Altitude']]];
  const EXAMPLES = [{name: 'AFR error', formula: '[AFR] - [AFR Target 1]', units: 'AFR'}, {name: 'Lambda', formula: '[AFR] / 14.7', units: 'λ'},
    {name: 'Boost from baro', formula: '([MAP] - [Barometer]) * 0.145', units: 'psi'}, {name: 'Injector duty', formula: '[PW] * [RPM] / 1200', units: '%'}];
  const FILTERS = [['Every row', ''], ['Warm engine', '[CLT] > 160'], ['Under boost', '[Boost psi] > 0'], ['Wide open', '[TPS] > 90'], ['Cruising', '[TPS] < 40 and [Boost psi] < 0']];
  // The Summary's channels, those the log has.
  const SUMMARY = ['RPM', 'Vehicle Speed', 'Boost psi', 'MAP', 'TPS', 'AFR', 'AFR Target 1', 'EGO cor1', 'SPK: Spark Advance', 'CLT', 'MAT', 'OilPressure', 'FuelPressure', 'Batt V', 'Meth flow', 'Intake after inj'];
  const OPTIONS = {stacked: false, scales: 'screen', speed: '4', filter: '', scatter: {x: 'RPM', y: 'MAP', z: 'AFR', range: 'all'},
    table: {x: 'RPM', y: 'MAP', z: 'AFR', stat: 'avg', xbins: '', ybins: '', range: 'all'}, track: {z: 'Vehicle Speed', range: 'all'}};
  const PICKS = {'scatter.x': ['RPM'], 'scatter.y': ['MAP', 'Boost psi', 'TPS'], 'scatter.z': ['AFR', 'EGO cor1'], 'table.x': ['RPM'], 'table.y': ['MAP', 'Boost psi', 'TPS'],
    'table.z': ['AFR', 'VE1', 'EGO cor1'], 'track.z': ['Vehicle Speed', 'RPM']};
  const stored = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; } catch { return fallback; } };
  const keep = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Kept for this visit only */ } };
  const options = (() => {
    const saved = stored(OPTION_STORE, {}), out = JSON.parse(JSON.stringify(OPTIONS));
    if (saved && typeof saved === 'object') for (const [k, v] of Object.entries(saved)) if (k in out) out[k] = typeof out[k] === 'object' && v && typeof v === 'object' ? {...out[k], ...v} : v;
    return out;
  })();
  const option = path => path.split('.').reduce((o, k) => o?.[k], options);
  function setOption(path, value) { const keys = path.split('.'), last = keys.pop(); keys.reduce((o, k) => o[k], options)[last] = value; keep(OPTION_STORE, options); }

  let latest = {}, logs = [], info = null, view = null, data = null, plots = [], chosen = [], cursorT = null, markA = null, loading = 0, built = false, find = '';
  let mode = 'graph', whole = null, scaleRanges = {}, playing = null, dragged = false, usable = [];
  let calcs = (stored(CALC_STORE, []) || []).filter(c => c && typeof c.name === 'string' && typeof c.formula === 'string');
  const formulas = new Map(), models = {}, tickets = {};
  const demo = () => latest.mode === 'demo';

  // ---- Where the logs come from: the Pi, or in the preview simulated drives ----
  const request = async url => { const r = await fetch(url, {cache: 'no-store'}); if (!r.ok) throw new Error(await r.text() || r.statusText); return r.json(); };
  const DEMO_CHANNELS = [['RPM', 'RPM', 'engine', 0], ['MAP', 'kPa', 'ecu', 0], ['Boost psi', 'psi', 'engine', 1], ['TPS', '%', 'ecu', 0],
    ['AFR', 'AFR', 'engine', 1], ['AFR Target 1', 'AFR', 'ecu', 1], ['CLT', 'F', 'engine', 0], ['MAT', 'F', 'engine', 0],
    ['Vehicle Speed', 'MPH', 'vehicle', 0], ['SPK: Spark Advance', 'deg', 'ecu', 1], ['Batt V', 'V', 'vehicle', 1], ['Meth flow', 'ml/min', 'meth', 0],
    ['OilPressure', 'psi', 'engine', 0], ['FuelPressure', 'psi', 'engine', 0], ['EGO cor1', '%', 'engine', 0], ['PW', 'ms', 'ecu', 2],
    ['Barometer', 'kPa', 'ecu', 1], ['Latitude', 'deg', 'gps', 6], ['Longitude', 'deg', 'gps', 6], ['Altitude', 'm', 'gps', 0]];
  // Four simulated drives: the same car, a different stretch of a made-up loop each.
  const DEMO_LOGS = [['20261105T221000Z', 900, 1.8], ['20261104T171500Z', 1680, 3.3], ['20261102T090500Z', 420, .8], ['20261029T193000Z', 2460, 4.9]]
    .map(([stamp, seconds, mb], i) => ({name: `frogdash-demo-${stamp}-preview${i}.mlg`, bytes: mb * 1048576, seconds, offset: i * 311}));
  function demoValue(name, t) {
    const pull = Math.max(0, Math.sin(t / 37) * 1.6 - .6), rpm = 900 + 2600 * (1 + Math.sin(t / 23)) / 2 + 2400 * pull;
    const boost = Math.max(-9, -9 + 21 * pull + Math.sin(t * 1.7) * .4), lap = t / 260 * 2 * Math.PI;
    return ({RPM: rpm, MAP: 84 + boost * 6.895, 'Boost psi': boost, TPS: Math.min(100, 12 + 80 * pull + Math.sin(t / 5) * 4),
      AFR: 14.7 - 3 * pull + Math.sin(t * 2.3) * .25 + (pull > .7 && Math.sin(t / 97) > .7 ? 1.4 : 0), 'AFR Target 1': 14.7 - 3.1 * pull, CLT: 150 + Math.min(45, t / 8) + Math.sin(t / 90) * 3,
      MAT: 85 + 40 * pull, 'Vehicle Speed': Math.max(0, 25 + 35 * Math.sin(t / 61) + 15 * pull), 'SPK: Spark Advance': 30 - 14 * pull,
      'Batt V': 14.1 + Math.sin(t / 13) * .08, 'Meth flow': boost > 8 ? 320 * pull : 0, OilPressure: 18 + rpm / 120,
      FuelPressure: 43 + Math.max(0, boost), 'EGO cor1': 100 + Math.sin(t / 7) * 4, PW: 1.6 + 9 * pull + rpm / 4000, Barometer: 84,
      Latitude: 39.705 + .0105 * Math.sin(lap) + .0032 * Math.sin(2 * lap), Longitude: -105.08 + .0165 * Math.cos(lap), Altitude: 1600 + 25 * Math.sin(lap)})[name];
  }
  const demoLog = name => DEMO_LOGS.find(l => l.name === name) || DEMO_LOGS[0];
  const source = {
    list: async () => demo() ? DEMO_LOGS.map(l => ({name: l.name, bytes: l.bytes, modified_ms: started(l.name) + l.seconds * 1000, active: false}))
      : (await request('/logs')).files.filter(f => f.bytes > 0),
    describe: async name => demo() ? {name, rows: demoLog(name).seconds * 20, duration_s: demoLog(name).seconds, started_s: started(name) / 1000,
      channels: DEMO_CHANNELS.map(([n, units, category, digits]) => ({name: n, units, category, digits})),
      markers: [{t: Math.round(demoLog(name).seconds * .35), text: 'Bookmark 1'}],
      events: [{t: Math.round(demoLog(name).seconds * .6), label: 'AFR LEAN', kind: 'alert'}], recording: false} : request(`/logs/${encodeURIComponent(name)}/view`),
    // mode 'thin': the graph's lowest and highest of each stretch; 'sample': whole rows.
    series: async (name, channels, start, end, points, mode = 'thin') => {
      if (demo()) {
        const log = demoLog(name);
        start = Math.max(0, start); end = Math.min(log.seconds, end);
        const rows = Math.max(1, Math.round((end - start) * 20)), step = Math.max(1, Math.ceil(rows / points)), count = Math.max(2, Math.floor(rows / step));
        const t = [], series = Object.fromEntries(channels.map(c => [c, []]));
        for (let i = 0; i <= count; i++) { const at = start + (end - start) * i / count; t.push(+at.toFixed(3)); for (const c of channels) series[c].push(demoValue(c, at + log.offset)); }
        return {t, series, stats: Object.fromEntries(channels.map(c => [c, statsOf(series[c], t)])), thinned: false, step};
      }
      const q = new URLSearchParams({channels: channels.join(','), start: start.toFixed(3), end: end.toFixed(3), points: String(points)});
      if (mode === 'sample') q.set('mode', 'sample');
      return request(`/logs/${encodeURIComponent(name)}/series?${q}`);
    },
  };
  // When a log began: in its name (frogdash-live-20261105T221000Z-…), else its file's time.
  function started(name, fallback = Date.now()) {
    const stamp = name.match(/(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)Z/);
    return stamp ? Date.UTC(stamp[1], stamp[2] - 1, stamp[3], stamp[4], stamp[5], stamp[6]) : fallback;
  }
  const length = seconds => seconds >= 3600 ? `${Math.floor(seconds / 3600)} h ${Math.round(seconds % 3600 / 60)} min`
    : seconds >= 60 ? `${Math.round(seconds / 60)} min` : `${Math.max(1, Math.round(seconds))} s`;
  function statsOf(values, t) {
    let low = -1, high = -1, total = 0, count = 0;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (v == null || !Number.isFinite(v)) continue;
      total += v; count++;
      if (low < 0 || v < values[low]) low = i;
      if (high < 0 || v > values[high]) high = i;
    }
    return count ? {min: values[low], avg: total / count, max: values[high], min_t: t[low], max_t: t[high]} : null;
  }

  // ---- Formulas: calculated fields, Find and "Only when" ----
  // [Channel name] (or a name without spaces: RPM), numbers, + - * / % ^, > < >= <= == !=,
  // and / or / not (&& || !), and abs min max sqrt round floor ceil log exp if(test, then, else).
  // Read into functions of a row, never run as code.
  const FUNCTIONS = {abs: Math.abs, min: Math.min, max: Math.max, sqrt: Math.sqrt, round: Math.round, floor: Math.floor, ceil: Math.ceil, log: Math.log, exp: Math.exp,
    if: (test, a, b) => (test ? a : b)};
  const OPS = {'+': (a, b) => g => a(g) + b(g), '-': (a, b) => g => a(g) - b(g), '*': (a, b) => g => a(g) * b(g), '/': (a, b) => g => a(g) / b(g),
    '%': (a, b) => g => a(g) % b(g), '>': (a, b) => g => +(a(g) > b(g)), '<': (a, b) => g => +(a(g) < b(g)), '>=': (a, b) => g => +(a(g) >= b(g)),
    '<=': (a, b) => g => +(a(g) <= b(g)), '==': (a, b) => g => +(a(g) === b(g)), '!=': (a, b) => g => +(a(g) !== b(g)),
    '&&': (a, b) => g => +(!!a(g) && !!b(g)), '||': (a, b) => g => +(!!a(g) || !!b(g))};
  const LEVELS = [['||'], ['&&'], ['>', '<', '>=', '<=', '==', '!='], ['+', '-'], ['*', '/', '%']];
  function known(raw) {
    const lower = raw.toLowerCase(), all = [...(info?.channels || []), ...calcs];
    return (all.find(c => c.name === raw) || all.find(c => c.name.toLowerCase() === lower))?.name;
  }
  function parse(text) {
    const tokens = [], pattern = /\s*(?:(\d+(?:\.\d*)?(?:e[+-]?\d+)?|\.\d+)|\[([^\]]*)\]|([A-Za-z_][\w.]*)|(>=|<=|==|!=|&&|\|\||[-+*/%^()<>!=,]))/iy;
    for (let at = 0; at < text.length && text.slice(at).trim();) {
      pattern.lastIndex = at;
      const m = pattern.exec(text);
      if (!m) throw new Error(`Cannot read "${text.slice(at).trim().slice(0, 12)}"`);
      at = pattern.lastIndex;
      if (m[1] !== undefined) tokens.push({k: 'num', v: Number(m[1])});
      else if (m[2] !== undefined) tokens.push({k: 'name', v: m[2].trim()});
      else if (m[3] !== undefined) { const w = m[3].toLowerCase(); tokens.push(w === 'and' ? {k: 'op', v: '&&'} : w === 'or' ? {k: 'op', v: '||'} : w === 'not' ? {k: 'op', v: '!'} : {k: 'word', v: m[3]}); }
      else tokens.push({k: 'op', v: m[4] === '=' ? '==' : m[4]});
    }
    if (!tokens.length) throw new Error('The formula is empty');
    let pos = 0;
    const names = new Set(), is = v => tokens[pos]?.k === 'op' && tokens[pos].v === v;
    const expect = v => { if (!is(v)) throw new Error(`"${v}" missing`); pos++; };
    const resolve = raw => { const found = known(raw); if (!found) throw new Error(`No channel "${raw}" in this log`); names.add(found); return g => g(found); };
    const level = n => {
      if (n === LEVELS.length) return unary();
      let left = level(n + 1);
      while (LEVELS[n].some(is)) { const op = tokens[pos++].v; left = OPS[op](left, level(n + 1)); }
      return left;
    };
    function unary() {
      if (is('-')) { pos++; const a = unary(); return g => -a(g); }
      if (is('+')) { pos++; return unary(); }
      if (is('!')) { pos++; const a = unary(); return g => +!a(g); }
      const base = atom();
      if (is('^')) { pos++; const b = unary(); return g => base(g) ** b(g); }
      return base;
    }
    function atom() {
      const t = tokens[pos++];
      if (!t) throw new Error('The formula ends too soon');
      if (t.k === 'num') return () => t.v;
      if (t.k === 'name') return resolve(t.v);
      if (t.k === 'word') {
        const fn = FUNCTIONS[t.v.toLowerCase()];
        if (fn && is('(')) {
          pos++;
          const args = [];
          if (!is(')')) do args.push(level(0)); while (is(',') && ++pos);
          expect(')');
          return g => fn(...args.map(a => a(g)));
        }
        return resolve(t.v);
      }
      if (t.v === '(') { const inner = level(0); expect(')'); return inner; }
      throw new Error(`"${t.v}" in the wrong place`);
    }
    const fn = level(0);
    if (pos < tokens.length) throw new Error(`"${tokens[pos].v}" in the wrong place`);
    return {fn, names: [...names]};
  }
  function compiled(text) {
    if (!formulas.has(text)) { try { formulas.set(text, parse(text)); } catch (error) { formulas.set(text, error); } }
    const out = formulas.get(text);
    if (out instanceof Error) throw out;
    return out;
  }
  // A formula over rows already read: a number per row, or null where it has no answer.
  function evaluate(text, cols, count) {
    const {fn} = compiled(text), out = new Array(count);
    let i = 0;
    const get = name => { const v = cols[name]?.[i]; return v == null ? NaN : v; };
    for (; i < count; i++) { const v = fn(get); out[i] = Number.isFinite(v) ? v : null; }
    return out;
  }
  const calc = name => calcs.find(c => c.name === name);
  // The log's own channels a set of channels needs: a calculated field needs what it uses.
  function bases(names, seen = new Set()) {
    const out = new Set();
    for (const name of names) {
      const c = calc(name);
      if (!c) { if (info.channels.some(ch => ch.name === name)) out.add(name); continue; }
      if (seen.has(name)) throw new Error(`${name} uses itself`);
      seen.add(name);
      for (const b of bases(compiled(c.formula).names, seen)) out.add(b);
      seen.delete(name);
    }
    return [...out];
  }
  // Calculated fields from the rows read, each after the fields it uses.
  function fill(names, cols, count) {
    for (const name of names) {
      const c = calc(name);
      if (!c || cols[name]) continue;
      fill(compiled(c.formula).names, cols, count);
      cols[name] = evaluate(c.formula, cols, count);
    }
  }
  // The calculated fields this log can work out (a field using a channel it lacks cannot).
  function refreshCalcs() {
    formulas.clear();
    usable = info ? calcs.filter(c => { try { bases([c.name]); return !info.channels.some(ch => ch.name === c.name); } catch { return false; } }) : [];
  }

  // ---- Reading: the Pi's channels, then the calculated ones from them ----
  async function fetchBase(base, start, end, points, mode) {
    const parts = [];
    for (let i = 0; i < base.length; i += 16) parts.push(base.slice(i, i + 16));
    const got = await Promise.all((parts.length ? parts : [[]]).map(part => source.series(info.name, part, start, end, points, mode)));
    const out = {t: got[0].t, series: {}, stats: {}, thinned: false, step: got[0].step || 1};
    for (const g of got) { Object.assign(out.series, g.series); Object.assign(out.stats, g.stats || {}); out.thinned ||= !!g.thinned; }
    return out;
  }
  async function rows(names, start, end, points, mode) {
    const got = await fetchBase(bases(names), start, end, points, mode);
    fill(names, got.series, got.t.length);
    for (const name of names) if (calc(name)) got.stats[name] = statsOf(got.series[name], got.t);
    return got;
  }
  // The whole log as whole rows (every nth of a long one), kept while it is open.
  async function wholeRows(names) {
    whole ??= {t: null, cols: {}, stats: {}, step: 1};
    const need = bases(names).filter(n => !(n in whole.cols));
    if (need.length || !whole.t) {
      const got = await fetchBase(need, 0, info.duration_s + 1, SAMPLE, 'sample');
      whole.t = got.t; whole.step = got.step;
      Object.assign(whole.cols, got.series); Object.assign(whole.stats, got.stats);
    }
    fill(names, whole.cols, whole.t.length);
    for (const name of names) if (calc(name) && !whole.stats[name]) whole.stats[name] = statsOf(whole.cols[name], whole.t);
    return {t: whole.t, series: whole.cols, stats: whole.stats, step: whole.step};
  }
  const ranged = (names, range) => range === 'screen' ? rows(names, view.start, view.end, SAMPLE, 'sample') : wholeRows(names);

  // ---- Layout: the list of logs, or one log ----
  const pickTools = (path, label, none) => `<label>${label} <select data-opt="${path}" data-channels${none ? ` data-none="${none}"` : ''}></select></label>`;
  const rangeTool = path => `<label>Of <select data-opt="${path}"><option value="all">the whole log</option><option value="screen">the time on the graph</option></select></label>`;
  const filterTools = () => `<label class="lv-filter">Only when <select data-filter-preset>${FILTERS.map(([label, text]) => `<option value="${esc(text)}">${label}</option>`).join('')}<option value="custom">Other…</option></select>
    <input type="text" data-opt="filter" placeholder="e.g. [CLT] > 160 and [TPS] > 50" autocomplete="off" spellcheck="false" aria-label="Only the rows where"></label>`;
  function build() {
    built = true;
    host.classList.add('logview');
    host.innerHTML = `<section class="lv-browser" id="lv-browser">
        <header class="lv-toolbar"><h3>Logs on the dash</h3><span id="lv-count" class="lv-range"></span><span class="lv-gap"></span><button type="button" id="lv-refresh">Refresh</button></header>
        <div class="lv-files" data-wheel-scroll tabindex="0" aria-label="Logs: newest first">
          <div class="lv-file lv-file-head" aria-hidden="true"><span>Date</span><span>Started</span><span>Length</span><span>Size</span><span></span></div>
          <div id="lv-files"></div></div>
        <p id="lv-browser-note" class="control-note" role="status"></p>
      </section>
      <section class="lv-viewer" id="lv-viewer" hidden>
        <header class="lv-toolbar">
          <button type="button" id="lv-back">‹ Logs</button><strong id="lv-title" class="lv-title"></strong><span class="lv-gap"></span>
          <div class="lv-modes" aria-label="How to show the log">${[['graph', 'Graph'], ['scatter', 'Scatter'], ['table', 'Table'], ['data', 'Data'], ['track', 'Track'], ['summary', 'Summary']]
            .map(([key, label]) => `<button type="button" data-mode="${key}" aria-pressed="${key === 'graph'}">${label}</button>`).join('')}</div></header>
        <section class="lv-mode" data-mode-panel="graph">
          <div class="lv-toolbar lv-tools">
            <button type="button" data-lv="in" title="Zoom in (Up)">Zoom in</button><button type="button" data-lv="out" title="Zoom out (Down)">Zoom out</button>
            <button type="button" data-lv="left" aria-label="Earlier" title="Earlier (Left)">◀</button><button type="button" data-lv="right" aria-label="Later" title="Later (Right)">▶</button>
            <button type="button" data-lv="all">Whole log</button><span id="lv-range" class="lv-range"></span><span class="lv-gap"></span>
            <button type="button" id="lv-play" title="Run the cursor through the log">▶ Play</button>
            <select data-opt="speed" aria-label="Playback speed">${[1, 2, 4, 8, 16, 32].map(n => `<option value="${n}">${n}×</option>`).join('')}</select>
            <button type="button" id="lv-stack" aria-pressed="false" title="Each channel on its own strip">Stacked</button>
            <select data-opt="scales" aria-label="Scales"><option value="screen">Scales fit the screen</option><option value="log">Scales fit the whole log</option></select>
            <select id="lv-marks" aria-label="Go to a bookmark or an alert"></select></div>
          <div class="lv-toolbar lv-tools">
            <input id="lv-cond" type="text" placeholder="Find: e.g. RPM > 6000 and AFR > 13" autocomplete="off" spellcheck="false" aria-label="Find when">
            <button type="button" id="lv-find-prev" aria-label="Find the time before">◀ Find</button><button type="button" id="lv-find-next" aria-label="Find the next time">Find ▶</button>
            <span id="lv-found" class="lv-range"></span><span class="lv-gap"></span>
            <span id="lv-a" class="lv-range">Tap the graph to put mark A</span><button type="button" id="lv-clear-a" hidden>Clear A</button></div>
          <div class="lv-body">
            <div class="lv-graph">
              <div id="lv-plot" class="lv-plot" tabindex="0" data-wheel-edit="SET / COAST: earlier, later, zoom in or out  |  ON: done" aria-label="Graph: press ON (Enter), then Left and Right move in time, Up and Down zoom"></div>
              <p id="lv-note" class="control-note" role="status"></p>
            </div>
            <aside class="lv-side">
              <div class="lv-side-tools"><select id="lv-layout" aria-label="Layouts"></select><button type="button" id="lv-save-layout" title="Keep these channels as a layout">Save</button><button type="button" id="lv-clear" title="Take every channel off">Clear</button></div>
              <div class="lv-side-list">
                <input id="lv-find" type="search" placeholder="Find a channel, e.g. oil or AFR" autocomplete="off" aria-label="Find a channel">
                <div class="lv-channel lv-channel-head" aria-hidden="true"><span>Channel</span><span id="lv-at">At cursor</span><span id="lv-d-head" hidden title="The change from mark A">Δ A</span><span>Min</span><span>Avg</span><span>Max</span></div>
                <div id="lv-channels" class="lv-channels" data-wheel-scroll tabindex="0" aria-label="Channels: tap one to show or hide it"></div>
                <button type="button" id="lv-new-calc">+ Calculated field</button>
              </div>
              <form id="lv-calc" class="lv-calc" hidden>
                <select id="lv-calc-pick" aria-label="Field to change"></select>
                <div class="lv-calc-row"><label>Name <input id="lv-calc-name" type="text" maxlength="40" autocomplete="off"></label><label>Units <input id="lv-calc-units" type="text" maxlength="12" autocomplete="off"></label></div>
                <label>Formula <input id="lv-calc-formula" type="text" maxlength="240" autocomplete="off" spellcheck="false" placeholder="[AFR] - [AFR Target 1]"></label>
                <div id="lv-examples" class="lv-examples"></div>
                <p id="lv-calc-note" class="control-note">Channels in [brackets]; + − * / ^; &gt; &lt; and or not; abs, min, max, sqrt, round, if(test, a, b).</p>
                <div class="lv-side-tools"><button type="submit">Save</button><button type="button" id="lv-calc-delete">Delete</button><button type="button" id="lv-calc-cancel">Cancel</button></div>
              </form>
            </aside>
          </div>
        </section>
        <section class="lv-mode" data-mode-panel="scatter" hidden>
          <div class="lv-toolbar lv-tools">${pickTools('scatter.x', 'Across')}${pickTools('scatter.y', 'Up')}${pickTools('scatter.z', 'Colour', 'None')}${rangeTool('scatter.range')}${filterTools()}</div>
          <div id="lv-scatter" class="lv-canvas"><canvas></canvas><div class="lv-readout" aria-live="polite"></div></div>
          <p class="control-note" data-note="scatter" role="status"></p>
        </section>
        <section class="lv-mode" data-mode-panel="table" hidden>
          <div class="lv-toolbar lv-tools">${pickTools('table.x', 'Across')}<input type="text" data-opt="table.xbins" placeholder="12 columns" aria-label="Columns: how many, or their values" autocomplete="off">
            ${pickTools('table.y', 'Up')}<input type="text" data-opt="table.ybins" placeholder="12 rows" aria-label="Rows: how many, or their values" autocomplete="off">
            ${pickTools('table.z', 'Cells')}<select data-opt="table.stat" aria-label="In each cell"><option value="avg">Average</option><option value="min">Lowest</option><option value="max">Highest</option><option value="count">Samples</option><option value="time">Time</option></select>
            ${rangeTool('table.range')}${filterTools()}</div>
          <div id="lv-table" class="lv-scroll" data-wheel-scroll tabindex="0"></div>
          <p class="control-note" data-note="table" role="status"></p>
        </section>
        <section class="lv-mode" data-mode-panel="data" hidden>
          <div class="lv-toolbar lv-tools"><span class="lv-range">The rows of the time on the graph, of the channels on it</span><span class="lv-gap"></span><button type="button" id="lv-rows-graph">Show the chosen row on the graph</button></div>
          <div id="lv-rows" class="lv-scroll" data-wheel-scroll tabindex="0"></div>
          <p class="control-note" data-note="data" role="status"></p>
        </section>
        <section class="lv-mode" data-mode-panel="track" hidden>
          <div class="lv-toolbar lv-tools">${pickTools('track.z', 'Colour', 'None')}${rangeTool('track.range')}</div>
          <div id="lv-track" class="lv-canvas"><canvas></canvas><div class="lv-readout" aria-live="polite"></div></div>
          <p class="control-note" data-note="track" role="status"></p>
        </section>
        <section class="lv-mode" data-mode-panel="summary" hidden>
          <div id="lv-summary" class="lv-scroll" data-wheel-scroll tabindex="0"></div>
          <p class="control-note" data-note="summary" role="status"></p>
        </section>
      </section>`;
    const $ = id => host.querySelector(`#${id}`);
    $('lv-refresh').onclick = () => load(true);
    $('lv-back').onclick = back;
    $('lv-find').oninput = event => { find = event.target.value.trim().toLowerCase(); channelList(); };
    host.querySelector('.lv-modes').onclick = event => { const key = event.target.closest('[data-mode]')?.dataset.mode; if (key) setMode(key); };
    host.querySelector('[data-mode-panel="graph"]').addEventListener('click', event => {
      const action = event.target.closest('[data-lv]')?.dataset.lv;
      if (action) move(action);
    });
    // The steering wheel or the arrow keys, after ON on the graph (navigation.js, [data-wheel-edit]).
    $('lv-plot').addEventListener('wheel-adjust', event => {
      const action = {left: 'left', right: 'right', up: 'in', down: 'out'}[event.detail];
      if (action) move(action);
    });
    new ResizeObserver(() => sizePlots()).observe($('lv-plot'));
    $('lv-play').onclick = play;
    $('lv-stack').onclick = () => { setOption('stacked', !options.stacked); graph(); };
    $('lv-marks').onchange = event => { const t = Number(event.target.value); event.target.value = ''; if (Number.isFinite(t)) goTo(t, Math.min(view.end - view.start, 30)); };
    $('lv-find-next').onclick = () => findNext(1);
    $('lv-find-prev').onclick = () => findNext(-1);
    $('lv-cond').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); findNext(event.shiftKey ? -1 : 1); } };
    $('lv-clear-a').onclick = () => setMarkA(null);
    $('lv-layout').onchange = event => { layout(event.target.value); event.target.value = ''; };
    $('lv-save-layout').onclick = saveLayout;
    $('lv-clear').onclick = () => { chosen = []; save(); graph(); };
    $('lv-new-calc').onclick = () => calcForm(true);
    $('lv-calc-cancel').onclick = () => calcForm(false);
    $('lv-calc-pick').onchange = event => calcEdit(event.target.value);
    $('lv-calc-delete').onclick = calcDelete;
    $('lv-calc').onsubmit = event => { event.preventDefault(); calcSave(); };
    $('lv-examples').onclick = event => {
      const example = EXAMPLES[event.target.closest('[data-example]')?.dataset.example];
      if (example) { $('lv-calc-name').value = example.name; $('lv-calc-formula').value = example.formula; $('lv-calc-units').value = example.units; }
    };
    $('lv-rows').onclick = event => { const row = event.target.closest('tr[data-t]'); if (row) { cursorT = Number(row.dataset.t); markRow(); } };
    $('lv-rows-graph').onclick = () => { if (cursorT != null) { setMode('graph'); goTo(cursorT); } };
    $('lv-table').onclick = event => { const cell = event.target.closest('td[data-cell]'); if (cell) tableCell(cell); };
    $('lv-summary').onclick = event => { const t = event.target.closest('[data-t]')?.dataset.t; if (t !== undefined) { setMode('graph'); goTo(Number(t), Math.min(view.end - view.start, 30)); } };
    for (const [key, draw] of [['scatter', drawScatter], ['track', drawTrack]]) {
      const box = $(`lv-${key}`), canvas = box.querySelector('canvas');
      new ResizeObserver(() => draw()).observe(box);
      canvas.onmousemove = event => hover(key, event);
      canvas.onmouseleave = () => { box.querySelector('.lv-readout').textContent = ''; models[key] && (models[key].hover = null); };
      canvas.onclick = () => { const p = models[key]?.hover; if (p) { setMode('graph'); goTo(p.t); } };
    }
    bindOptions();
  }
  const note = text => { host.querySelector(info && !host.querySelector('#lv-viewer').hidden ? '#lv-note' : '#lv-browser-note').textContent = text; };
  const modeNote = (key, text) => { const n = host.querySelector(`[data-note="${key}"]`); if (n) n.textContent = text; };
  // m:ss, rounded before it is split (9.97 s is 0:10, not 0:010).
  const stamp = (s, digits) => { const whole = Math.round(Math.max(0, s) * 10 ** digits) / 10 ** digits, m = Math.floor(whole / 60), r = (whole - m * 60).toFixed(digits); return `${m}:${r.length < (digits ? 3 + digits : 2) ? '0' : ''}${r}`; };
  const clock = s => stamp(s, view && view.end - view.start < 30 ? 1 : 0);
  const precise = s => stamp(s, 2);
  const nth = n => `${n}${n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th'}`;
  const channel = name => info?.channels.find(c => c.name === name) || (usable.find(c => c.name === name) && {...calc(name), category: 'Calculated', digits: 2});
  const has = name => !!channel(name);
  const shown = (value, name) => value == null || !isFinite(value) ? '—' : `${value.toFixed(channel(name)?.digits ?? 1)}`;
  const label = name => { const c = channel(name); return c?.units ? `${name} (${c.units})` : name; };
  const color = name => COLORS[chosen.indexOf(name) % COLORS.length];
  const signed = (v, name) => v == null ? '—' : `${v > 0 ? '+' : ''}${shown(v, name)}`;
  let queued = false;
  const soon = () => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; values(); }); } };

  // Settings shown in more than one place ([data-opt]) stay the same in each; a change redraws.
  function bindOptions() {
    host.addEventListener('change', event => {
      const target = event.target;
      if (target.matches('select[data-opt]')) {
        setOption(target.dataset.opt, target.value);
        sync(target.dataset.opt);
        if (target.dataset.opt === 'scales') fetchRange();
        else if (target.dataset.opt !== 'speed') render();
      } else if (target.matches('[data-filter-preset]')) {
        if (target.value === 'custom') { target.closest('.lv-filter').querySelector('input').focus(); return; }
        setOption('filter', target.value); sync('filter'); render();
      }
    });
    let typing = null;
    host.addEventListener('input', event => {
      const target = event.target;
      if (!target.matches('input[data-opt]')) return;
      clearTimeout(typing);
      typing = setTimeout(() => { setOption(target.dataset.opt, target.value.trim()); sync(target.dataset.opt, target); render(); }, 600);
    });
  }
  function sync(path, except) {
    for (const node of host.querySelectorAll(`[data-opt="${path}"]`)) if (node !== except) node.value = node.dataset.channels !== undefined ? pick(path) : option(path);
    if (path === 'filter') for (const preset of host.querySelectorAll('[data-filter-preset]')) preset.value = FILTERS.some(([, text]) => text === options.filter) ? options.filter : 'custom';
    if (path === 'stacked' || path === undefined) host.querySelector('#lv-stack')?.setAttribute('aria-pressed', String(!!options.stacked));
  }
  // The channel a setting names, or one the log has: the scatter's RPM, else the first channel.
  function pick(path) {
    const value = option(path);
    if (value && has(value)) return value;
    if (value === '' && path.endsWith('.z') && path !== 'table.z') return '';
    return (PICKS[path] || []).find(has) || info?.channels[0]?.name || '';
  }
  function grouped() {
    const groups = {};
    for (const c of info.channels) (groups[c.category || 'Other'] ??= []).push(c);
    const out = Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
    if (usable.length) out.unshift(['Calculated', usable.map(c => channel(c.name))]);
    return out;
  }
  function fillPicks() {
    const groups = grouped();
    for (const select of host.querySelectorAll('select[data-channels]')) {
      select.replaceChildren();
      if (select.dataset.none) select.append(new Option(select.dataset.none, ''));
      for (const [group, list] of groups) {
        const g = document.createElement('optgroup'); g.label = group;
        for (const c of list) g.append(new Option(c.units ? `${c.name} (${c.units})` : c.name, c.name));
        select.append(g);
      }
    }
    for (const path of new Set([...host.querySelectorAll('[data-opt]')].map(n => n.dataset.opt))) sync(path);
    sync('filter');
  }

  // ---- The list of logs ----
  // The first state update says whether this is the car or the preview. This file loads after
  // the gauges, so it can start before one has arrived here: it waits for it (the live preview
  // asked the web site for the Pi's logs and said they could not be listed, November 2026).
  const firstState = () => latest.mode ? Promise.resolve() : new Promise(resolve => {
    const done = () => { window.removeEventListener('frogdash-state', done); clearTimeout(timer); resolve(); };
    const timer = setTimeout(done, 4000);
    window.addEventListener('frogdash-state', done);
  });
  // One start at a time: the tab and the panel showing can ask together.
  let starting = null;
  const load = (refresh = false) => (starting ??= loadNow(refresh).finally(() => { starting = null; }));
  async function loadNow(refresh = false) {
    if (!built) build();
    if (info && !refresh) return;                          // A log is open: it stays open
    note('Finding the logs…');
    await firstState();
    try {
      logs = await source.list();
    } catch (error) { note(`The logs could not be listed: ${error.message}`); return; }
    const rows = logs.map(f => {
      const begun = started(f.name, f.modified_ms), when = new Date(begun), seconds = Math.max(0, (f.modified_ms - begun) / 1000);
      const row = el('button', undefined, 'lv-file'); row.type = 'button'; row.dataset.log = f.name;
      row.append(el('span', when.toLocaleDateString([], {weekday: 'short', month: 'short', day: 'numeric'})),
        el('span', when.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'})), el('span', seconds ? length(seconds) : '—'),
        el('span', `${(f.bytes / 1048576).toFixed(1)} MB`), el('span', f.active ? 'Recording now' : '', 'lv-live'));
      row.onclick = () => reporting(openLog)(f.name);
      return row;
    });
    host.querySelector('#lv-files').replaceChildren(...rows);
    host.querySelector('#lv-count').textContent = logs.length ? `${logs.length} · newest first` : '';
    note(logs.length ? 'Choose a log to see it.' : 'No logs yet: the dash records every drive, and they appear here.');
  }
  function back() {
    stopPlay();
    info = null; data = null; whole = null;
    for (const p of plots) p.destroy();
    plots = [];
    host.querySelector('#lv-viewer').hidden = true;
    host.querySelector('#lv-browser').hidden = false;
    load(true);
    host.querySelector('.lv-file')?.focus();
  }

  // ---- One log ----
  async function openLog(name) {
    note('Opening the log…');
    try {
      info = await source.describe(name);
    } catch (error) { info = null; note(`This log cannot be shown: ${error.message}`); return; }
    view = {start: 0, end: Math.max(1, info.duration_s)};
    whole = null; scaleRanges = {}; markA = null; cursorT = null;
    for (const key of Object.keys(models)) delete models[key];
    refreshCalcs();
    chosen = restore();
    host.querySelector('#lv-browser').hidden = true;
    host.querySelector('#lv-viewer').hidden = false;
    const when = new Date(started(name, Date.now()));
    host.querySelector('#lv-title').textContent = `${when.toLocaleString([], {weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})} · ${length(info.duration_s)}${info.recording ? ' · recording now' : ''}`;
    find = ''; host.querySelector('#lv-find').value = '';
    host.querySelector('#lv-found').textContent = '';
    fillPicks(); fillMarks(); fillLayouts(); calcForm(false); setMarkA(null);
    setMode(mode);
    graph();
  }
  function restore() {
    let saved = stored(STORE, null);
    let result = (Array.isArray(saved) ? saved : DEFAULTS).filter(has).slice(0, MOST);
    if (!result.length) result = DEFAULTS.filter(has);
    if (!result.length) result = info.channels.slice(0, 3).map(c => c.name);
    return result;
  }
  function save() { keep(STORE, chosen); }
  function toggle(name) {
    if (chosen.includes(name)) chosen = chosen.filter(n => n !== name);
    else if (chosen.length >= MOST) { note(`Up to ${MOST} channels on the graph: take one off first.`); return; }
    else chosen = [...chosen, name];
    save();
    graph();
  }
  function setMode(key) {
    if (key !== 'graph') stopPlay();
    mode = key;
    for (const button of host.querySelectorAll('[data-mode]')) button.setAttribute('aria-pressed', String(button.dataset.mode === key));
    for (const panel of host.querySelectorAll('[data-mode-panel]')) panel.hidden = panel.dataset.modePanel !== key;
    if (key === 'graph') { sizePlots(); showAt(cursorT); } else render();
  }
  const RENDER = {scatter: () => scatter(), table: () => table(), data: () => rowsView(), track: () => track(), summary: () => summary()};
  function render() {
    if (!info || !RENDER[mode]) return;
    const key = mode;
    Promise.resolve().then(RENDER[key]).catch(error => modeNote(key, `This could not be shown: ${error?.message || error}`));
  }

  // ---- Layouts: ready-made sets of channels, and the owner's own ----
  function layouts() {
    const saved = (stored(LAYOUT_STORE, []) || []).filter(l => l && Array.isArray(l.list));
    return {ready: PRESETS.map(([name, list]) => ({name, list: list.filter(has)})).filter(l => l.list.length >= 2), saved};
  }
  function fillLayouts() {
    const select = host.querySelector('#lv-layout'), {ready, saved} = layouts();
    select.replaceChildren(new Option('Layouts…', ''));
    const group = (title, list, prefix) => {
      if (!list.length) return;
      const g = document.createElement('optgroup'); g.label = title;
      list.forEach((l, i) => g.append(new Option(l.name, `${prefix}${i}`)));
      select.append(g);
    };
    group('Ready-made', ready, 'r');
    group('Saved', saved, 's');
    group('Delete a saved layout', saved.map(l => ({name: `Delete ${l.name}`})), 'd');
  }
  function layout(value) {
    const {ready, saved} = layouts(), kind = value[0], index = Number(value.slice(1));
    if (kind === 'd') { keep(LAYOUT_STORE, saved.filter((_, i) => i !== index)); fillLayouts(); return; }
    const chosenLayout = (kind === 'r' ? ready : kind === 's' ? saved : [])[index];
    if (!chosenLayout) return;
    chosen = chosenLayout.list.filter(has).slice(0, MOST);
    save(); graph();
    note(`Layout: ${chosenLayout.name}.`);
  }
  function saveLayout() {
    if (!chosen.length) { note('Put channels on the graph first, then Save keeps them as a layout.'); return; }
    const {saved} = layouts(), name = chosen.slice(0, 2).join(' + ') + (chosen.length > 2 ? ` + ${chosen.length - 2} more` : '');
    keep(LAYOUT_STORE, [{name, list: chosen}, ...saved.filter(l => l.list.join() !== chosen.join())].slice(0, 12));
    fillLayouts();
    note(`Saved as the layout "${name}": Layouts… brings it back, on any log.`);
  }

  // ---- Calculated fields ----
  function calcForm(open) {
    const form = host.querySelector('#lv-calc');
    form.hidden = !open;
    host.querySelector('.lv-side-list').hidden = open;
    if (!open) return;
    const pickList = host.querySelector('#lv-calc-pick');
    pickList.replaceChildren(new Option('A new calculated field', ''), ...calcs.map(c => new Option(`Change ${c.name}`, c.name)));
    host.querySelector('#lv-examples').replaceChildren(...EXAMPLES.map((e, i) => { const b = el('button', e.name); b.type = 'button'; b.dataset.example = i; b.title = e.formula; return b; }));
    calcEdit('');
    host.querySelector('#lv-calc-name').focus();
  }
  function calcEdit(name) {
    const c = calc(name) || {name: '', formula: '', units: ''};
    host.querySelector('#lv-calc-pick').value = calc(name) ? name : '';
    host.querySelector('#lv-calc-name').value = c.name;
    host.querySelector('#lv-calc-formula').value = c.formula;
    host.querySelector('#lv-calc-units').value = c.units || '';
    host.querySelector('#lv-calc-delete').hidden = !calc(name);
  }
  function calcsChanged() {
    keep(CALC_STORE, calcs);
    refreshCalcs();
    if (whole) for (const key of Object.keys(whole.cols)) if (!info.channels.some(c => c.name === key)) { delete whole.cols[key]; delete whole.stats[key]; }
    scaleRanges = {};
    chosen = chosen.filter(has);
    fillPicks();
    graph();
  }
  function calcSave() {
    const editing = host.querySelector('#lv-calc-pick').value, say = text => { host.querySelector('#lv-calc-note').textContent = text; };
    const name = host.querySelector('#lv-calc-name').value.trim(), formula = host.querySelector('#lv-calc-formula').value.trim(), units = host.querySelector('#lv-calc-units').value.trim();
    if (!name || /[[\]]/.test(name)) { say('Give it a name (without [ or ]).'); return; }
    if (info.channels.some(c => c.name.toLowerCase() === name.toLowerCase())) { say(`${name} is already a channel in the log: choose another name.`); return; }
    if (calcs.some(c => c.name.toLowerCase() === name.toLowerCase() && c.name !== editing)) { say(`There is already a calculated field called ${name}.`); return; }
    const before = calcs;
    calcs = [...calcs.filter(c => c.name !== editing), {name, formula, units}];
    formulas.clear();
    try { bases([name]); } catch (error) { calcs = before; formulas.clear(); say(`That formula does not work: ${error.message}`); return; }
    if (editing && editing !== name) chosen = chosen.map(n => n === editing ? name : n);
    if (!chosen.includes(name) && chosen.length < MOST) chosen = [...chosen, name];
    save();
    calcForm(false);
    calcsChanged();
    note(`${name} = ${formula}: on the graph, and in the Scatter, Table and Track choices (it is kept for every log that has what it uses).`);
  }
  function calcDelete() {
    const name = host.querySelector('#lv-calc-pick').value;
    if (!calc(name)) return;
    calcs = calcs.filter(c => c.name !== name);
    calcForm(false);
    calcsChanged();
  }

  // ---- The graph: every chosen channel on its own scale, on one graph or stacked ----
  function graph() {
    for (const p of plots) p.destroy();
    plots = [];
    const area = host.querySelector('#lv-plot');
    area.replaceChildren();
    sync('stacked');
    if (!window.uPlot) { note('The graph library did not load'); return; }
    const groups = options.stacked && chosen.length > 1 ? chosen.map(n => [n]) : [chosen];
    area.classList.toggle('lv-stacked', groups.length > 1);
    groups.forEach((names, i) => { const pane = el('div', undefined, 'lv-pane'); area.append(pane); plots.push(makePlot(pane, names, groups.length > 1, i === groups.length - 1)); });
    sizePlots();
    fetchRange();
  }
  const padded = (lo, hi) => {
    if (lo == null || !Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
    if (lo === hi) return [lo - 1, hi + 1];
    const pad = (hi - lo) * .05;
    return [lo - pad, hi + pad];
  };
  function makePlot(pane, names, stacked, last) {
    const muted = css('--muted'), line = css('--line'), font = '12px "DejaVu Sans", sans-serif', at = n => chosen.indexOf(n);
    const xAxis = {stroke: muted, grid: {stroke: line, width: 1}, ticks: {stroke: line, width: 1}, font, size: stacked && !last ? 8 : 30,
      values: (self, ticks) => ticks.map(v => stacked && !last ? '' : clock(v))};
    const yAxes = (stacked ? names : names.slice(0, 2)).map((n, i) => ({scale: `y${at(n)}`, side: i ? 1 : 3, stroke: COLORS[at(n)], size: 56, font,
      grid: {show: i === 0, stroke: line, width: 1}, ticks: {stroke: line, width: 1}}));
    const plot = new window.uPlot({
      width: Math.max(240, pane.clientWidth), height: Math.max(60, pane.clientHeight), pxAlign: 0,
      scales: {x: {time: false}, ...Object.fromEntries(names.map(n => [`y${at(n)}`, {auto: true, range: (u, lo, hi) => padded(...(options.scales === 'log' && scaleRanges[n] || [lo, hi]))}]))},
      axes: [xAxis, ...yAxes],
      series: [{value: (self, v) => v == null ? '—' : clock(v)},
        ...names.map(n => ({label: n, scale: `y${at(n)}`, stroke: COLORS[at(n)], width: 1.8, spanGaps: false, points: {show: false}, value: (self, v) => shown(v, n)}))],
      cursor: {sync: {key: 'frogdash-logview', setSeries: false}, drag: {x: true, y: false, setScale: false}, points: {size: 7}},
      legend: {show: false},
      hooks: {
        setSelect: [u => {
          if (u.select.width > 6) { dragged = true; zoom(u.posToVal(u.select.left, 'x'), u.posToVal(u.select.left + u.select.width, 'x')); }
          u.setSelect({left: 0, top: 0, width: 0, height: 0}, false);
        }],
        setCursor: [u => {
          if (u.cursor.idx == null || u.cursor.left < 0 || !data) return;
          const t = data.t[u.cursor.idx];
          if (t !== cursorT) { cursorT = t; soon(); }
        }],
        draw: [u => marks(u, stacked ? names[0] : null)],
      },
    }, [[], ...names.map(() => [])], pane);
    plot.names = names;
    // A tap (not a drag) puts mark A there; off the graph, the cursor stays where it was.
    plot.over.addEventListener('mousedown', () => { dragged = false; });
    plot.over.addEventListener('click', event => { if (!dragged) setMarkA(plot.posToVal(event.offsetX, 'x')); });
    plot.over.addEventListener('mouseleave', () => setTimeout(() => showAt(cursorT), 0));
    return plot;
  }
  function sizePlots() {
    for (const p of plots) { const pane = p.root.parentElement; p.setSize({width: Math.max(240, pane.clientWidth), height: Math.max(60, pane.clientHeight)}); }
  }
  // Bookmarks (from the log), the drive's alerts and bookmarks, and mark A, as lines across the graph.
  const allMarks = () => [...(info?.markers || []).map(m => ({t: m.t, text: m.text, kind: 'bookmark'})), ...(info?.events || []).map(e => ({t: e.t, text: e.label, kind: e.kind}))].sort((a, b) => a.t - b.t);
  function marks(u, name) {
    const ctx = u.ctx, top = u.bbox.top, height = u.bbox.height, r = devicePixelRatio || 1;
    ctx.save();
    ctx.font = `${13 * r}px "DejaVu Sans", sans-serif`;
    const line = (t, colour, text, dash) => {
      if (t < u.scales.x.min || t > u.scales.x.max) return;
      const x = Math.round(u.valToPos(t, 'x', true));
      ctx.strokeStyle = colour; ctx.setLineDash(dash); ctx.lineWidth = 1.5 * r;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke();
      ctx.setLineDash([]); ctx.fillStyle = colour; ctx.fillText(text, x + 4 * r, top + 14 * r);
    };
    for (const mark of allMarks()) line(mark.t, mark.kind === 'alert' ? '#ff6b6b' : '#ffd166', mark.text, [4 * r, 4 * r]);
    if (markA) line(markA.t, '#e8eef2', 'A', []);
    if (name) { ctx.fillStyle = color(name); ctx.textAlign = 'right'; ctx.fillText(label(name), u.bbox.left + u.bbox.width - 6 * r, top + 14 * r); }
    ctx.restore();
  }
  function fillMarks() {
    const select = host.querySelector('#lv-marks'), list = allMarks();
    select.replaceChildren(new Option(list.length ? `Marks (${list.length})…` : 'No marks', ''), ...list.map(m => new Option(`${clock(m.t)} ${m.text}`, String(m.t))));
    select.disabled = !list.length;
  }
  // Every channel in the log: the ones on the graph first, with their values; the rest by group.
  function channelList() {
    const box = host.querySelector('#lv-channels');
    if (!box || !info) return;
    const matches = c => !find || `${c.name} ${c.units} ${c.category}`.toLowerCase().includes(find);
    const row = c => {
      const on = chosen.includes(c.name);
      const button = el('button', undefined, 'lv-channel'); button.type = 'button'; button.dataset.channel = c.name;
      button.setAttribute('aria-pressed', String(on)); button.title = c.formula ? `${c.name} = ${c.formula}` : on ? `Take ${c.name} off the graph` : `Put ${c.name} on the graph`;
      const name = el('span', undefined, 'lv-name'), swatch = el('i', undefined, 'lv-swatch');
      if (on) swatch.style.background = color(c.name);
      name.append(swatch, el('span', c.name), el('small', c.units ? ` ${c.units}` : ''));
      button.append(name);
      if (on) button.append(el('b', '—', 'lv-v-at'), ...(markA ? [el('span', '—', 'lv-v-d')] : []), el('span', '—', 'lv-v-min'), el('span', '—', 'lv-v-avg'), el('span', '—', 'lv-v-max'));
      button.onclick = () => toggle(c.name);
      return button;
    };
    const rows = chosen.map(channel).filter(Boolean).filter(matches).map(row);
    for (const [group, list] of grouped()) {
      const rest = list.filter(c => !chosen.includes(c.name) && matches(c));
      if (rest.length) rows.push(el('h4', group, 'lv-group'), ...rest.map(row));
    }
    if (!rows.length) rows.push(el('p', `No channel matches "${find}".`, 'control-note'));
    const focused = document.activeElement?.dataset?.channel, scroll = box.scrollTop;
    box.replaceChildren(...rows);
    box.scrollTop = scroll;
    if (focused) box.querySelector(`[data-channel="${CSS.escape(focused)}"]`)?.focus();
    host.querySelector('.lv-side').classList.toggle('lv-with-a', !!markA);
    host.querySelector('#lv-d-head').hidden = !markA;
    values();
  }
  // The nearest reading on screen to a time.
  function nearest(times, t) {
    let lo = 0, hi = times.length - 1;
    if (hi < 0) return -1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (times[mid] < t) lo = mid; else hi = mid; }
    return Math.abs(times[lo] - t) <= Math.abs(times[hi] - t) ? lo : hi;
  }
  const valueAt = (name, t) => {
    if (!data || t == null || t < view.start - 1 || t > view.end + 1) return null;
    const i = nearest(data.t, t);
    return i < 0 ? null : data.series[name]?.[i] ?? null;
  };
  // The values at the cursor, the change from mark A, and each channel's range on screen.
  function values() {
    if (!info) return;
    host.querySelector('#lv-at').textContent = cursorT == null ? 'At cursor' : `At ${clock(cursorT)}`;
    if (markA) host.querySelector('#lv-a').textContent = `A at ${clock(markA.t)}${cursorT == null ? '' : ` · cursor ${signed(cursorT - markA.t)} s from A`}`;
    for (const button of host.querySelectorAll('#lv-channels .lv-channel[aria-pressed="true"]')) {
      const n = button.dataset.channel, stat = data?.stats?.[n], v = valueAt(n, cursorT), set = (cls, text) => { const c = button.querySelector(cls); if (c) c.textContent = text; };
      set('.lv-v-at', cursorT == null ? '—' : shown(v, n));
      set('.lv-v-d', markA && v != null && markA.values[n] != null ? signed(v - markA.values[n], n) : '—');
      set('.lv-v-min', shown(stat?.min, n)); set('.lv-v-avg', shown(stat?.avg, n)); set('.lv-v-max', shown(stat?.max, n));
    }
  }
  function setMarkA(t) {
    markA = t == null ? null : {t, values: Object.fromEntries(chosen.map(n => [n, valueAt(n, t)]))};
    host.querySelector('#lv-clear-a').hidden = !markA;
    if (!markA) host.querySelector('#lv-a').textContent = 'Tap the graph to put mark A';
    for (const p of plots) p.redraw(false);
    channelList();
  }
  // The cursor to a time on the graph (from Find, Play, a mark, a table, the summary).
  function showAt(t) {
    if (t == null || mode !== 'graph') return;
    for (const p of plots) if (t >= p.scales.x.min && t <= p.scales.x.max) p.setCursor({left: p.valToPos(t, 'x'), top: p.over.clientHeight / 2});
    values();
  }
  function goTo(t, width) {
    cursorT = t;
    const span = view.end - view.start;
    if (width || t < view.start + span * .05 || t > view.end - span * .05) { const w = width || span; zoom(t - w / 2, t + w / 2); }
    else showAt(t);
  }

  // ---- The time on screen ----
  function zoom(start, end) {
    const total = Math.max(1, info?.duration_s || 1), width = Math.max(.5, end - start);
    start = Math.max(0, Math.min(start, total - width));
    view = {start, end: Math.min(total, start + width)};
    fetchRange();
  }
  function move(action) {
    if (!info || !view) return;
    const width = view.end - view.start, middle = (view.start + view.end) / 2;
    if (action === 'all') zoom(0, info.duration_s);
    else if (action === 'in') zoom(middle - width / 4, middle + width / 4);
    else if (action === 'out') zoom(middle - width, middle + width);
    else if (action === 'left') zoom(view.start - width * .4, view.end - width * .4);
    else if (action === 'right') zoom(view.start + width * .4, view.end + width * .4);
  }
  // Whole-log scales: each channel's lowest and highest in the whole log, so zooming keeps them.
  async function logScales(names) {
    const missing = names.filter(n => !scaleRanges[n]);
    if (!missing.length) return;
    const base = missing.filter(n => !calc(n)), calcOnly = missing.filter(calc);
    if (base.length) { const got = await fetchBase(base, 0, info.duration_s + 1, 10, 'thin'); for (const n of base) if (got.stats[n]) scaleRanges[n] = [got.stats[n].min, got.stats[n].max]; }
    if (calcOnly.length) { const got = await wholeRows(calcOnly); for (const n of calcOnly) if (got.stats[n]) scaleRanges[n] = [got.stats[n].min, got.stats[n].max]; }
  }
  async function fetchRange() {
    if (!info || !plots.length) return;
    const ticket = ++loading;
    host.querySelector('#lv-range').textContent = `${clock(view.start)} – ${clock(view.end)} of ${clock(info.duration_s)}`;
    if (!chosen.length) { data = null; channelList(); note('Choose channels from the list to draw them, or a layout.'); return; }
    // A calculated field needs whole rows: its channels from the same moments.
    const calculated = chosen.some(calc);
    let got;
    try {
      got = await rows(chosen, view.start, view.end, calculated ? 3000 : Math.min(4000, Math.round(host.clientWidth * 1.5) || 1500), calculated ? 'sample' : 'thin');
      if (options.scales === 'log') await logScales(chosen);
    } catch (error) { note(`The readings could not be read: ${error.message}`); return; }
    if (ticket !== loading || !plots.length) return;          // A newer range was asked for meanwhile
    data = got;
    for (const p of plots) {
      p.setData([data.t, ...p.names.map(n => data.series[n] || [])], false);
      p.setScale('x', {min: view.start, max: view.end});
    }
    if (markA) for (const n of chosen) if (markA.values[n] == null) markA.values[n] = valueAt(n, markA.t);
    channelList();
    showAt(cursorT);
    note(`${info.recording ? 'Still recording: ‹ Logs and open it again for the newest. ' : ''}${data.thinned ? 'Zoomed out: each point is the lowest and highest of its stretch, so no peak is lost. ' : ''}${calculated && data.step > 1 ? `Calculated fields: every ${nth(data.step)} row until zoomed in. ` : ''}Drag across the graph to zoom in; tap it to put mark A.`);
  }

  // ---- Play: the cursor runs through the log, the graph following it ----
  function play() {
    if (playing) { stopPlay(); return; }
    if (!info) return;
    let t = cursorT ?? view.start, last = performance.now();
    if (t >= info.duration_s - .2) t = 0;
    host.querySelector('#lv-play').textContent = '❚❚ Pause';
    playing = setInterval(() => {
      const now = performance.now();
      t += (now - last) / 1000 * Number(options.speed || 1); last = now;
      if (t >= info.duration_s) { stopPlay(); return; }
      const width = view.end - view.start;
      cursorT = t;
      if (t > view.end - width * .05 || t < view.start) zoom(t - width * .1, t + width * .9);
      else showAt(t);
    }, 60);
  }
  function stopPlay() {
    if (!playing) return;
    clearInterval(playing); playing = null;
    host.querySelector('#lv-play').textContent = '▶ Play';
  }

  // ---- Find: each time a condition comes true ----
  async function findNext(direction) {
    const text = host.querySelector('#lv-cond').value.trim(), say = t => { host.querySelector('#lv-found').textContent = t; };
    if (!text || !info) { say('Type what to find, e.g. RPM > 6000'); return; }
    let names;
    try { names = compiled(text).names; } catch (error) { say(error.message); return; }
    say('Looking…');
    const w = await wholeRows(names), hits = evaluate(text, w.series, w.t.length), starts = [];
    for (let i = 0; i < hits.length; i++) if (hits[i] && !(i && hits[i - 1])) starts.push(w.t[i]);
    if (!starts.length) { say('Never in this log'); return; }
    const from = cursorT ?? (direction > 0 ? -1 : Infinity);
    let index = direction > 0 ? starts.findIndex(s => s > from + .05) : starts.findLastIndex(s => s < from - .05);
    if (index < 0) index = direction > 0 ? 0 : starts.length - 1;        // Round again from the other end
    say(`${index + 1} of ${starts.length}`);
    goTo(starts[index], Math.min(view.end - view.start, 60));
  }

  // ---- Drawing on a canvas: scatter and track ----
  function canvasIn(box) {
    const canvas = box.querySelector('canvas'), w = Math.max(200, box.clientWidth), h = Math.max(150, box.clientHeight), r = devicePixelRatio || 1;
    canvas.width = Math.round(w * r); canvas.height = Math.round(h * r); canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(r, 0, 0, r, 0, 0); ctx.clearRect(0, 0, w, h);
    return {ctx, w, h};
  }
  const decimals = step => { for (let d = 0; d < 5; d++) if (Math.abs(Math.round(step * 10 ** d) - step * 10 ** d) < 1e-6) return d; return 4; };
  function niceStep(rough) { const mag = 10 ** Math.floor(Math.log10(rough)); return [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= rough * .999) || mag * 10; }
  function niceTicks(lo, hi, count) {
    if (!(hi > lo)) return [lo];
    const step = niceStep((hi - lo) / count), out = [];
    for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toPrecision(12));
    return out;
  }
  const HEAT = Array.from({length: 32}, (_, i) => `hsl(${Math.round(240 - 240 * i / 31)} 85% 56%)`);
  const heat = f => HEAT[Math.round(clamp(f) * 31)];
  function frame(ctx, w, h, xr, yr, xLabel, yLabel, right) {
    const area = {x: 66, y: 12, w: Math.max(40, w - 66 - right), h: Math.max(40, h - 12 - 44)};
    const X = v => area.x + (v - xr[0]) / (xr[1] - xr[0]) * area.w, Y = v => area.y + area.h - (v - yr[0]) / (yr[1] - yr[0]) * area.h;
    const xt = niceTicks(...xr, Math.max(3, Math.round(area.w / 110))), yt = niceTicks(...yr, Math.max(3, Math.round(area.h / 60)));
    ctx.font = '12px "DejaVu Sans", sans-serif'; ctx.lineWidth = 1; ctx.strokeStyle = css('--line'); ctx.fillStyle = css('--muted');
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (const v of xt) { const x = Math.round(X(v)) + .5; ctx.beginPath(); ctx.moveTo(x, area.y); ctx.lineTo(x, area.y + area.h); ctx.stroke(); ctx.fillText(v.toFixed(decimals(xt[1] - xt[0] || 1)), x, area.y + area.h + 5); }
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (const v of yt) { const y = Math.round(Y(v)) + .5; ctx.beginPath(); ctx.moveTo(area.x, y); ctx.lineTo(area.x + area.w, y); ctx.stroke(); ctx.fillText(v.toFixed(decimals(yt[1] - yt[0] || 1)), area.x - 6, y); }
    ctx.strokeRect(area.x + .5, area.y + .5, area.w, area.h);
    ctx.fillStyle = css('--text'); ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    ctx.fillText(xLabel, area.x + area.w / 2, h - 2);
    ctx.save(); ctx.translate(4, area.y + area.h / 2); ctx.rotate(-Math.PI / 2); ctx.textBaseline = 'top'; ctx.fillText(yLabel, 0, 0); ctx.restore();
    return {area, X, Y};
  }
  function legend(ctx, w, area, zr, name) {
    const x = w - 70, steps = 40;
    for (let i = 0; i < steps; i++) { ctx.fillStyle = heat(1 - i / (steps - 1)); ctx.fillRect(x, area.y + area.h * i / steps, 14, area.h / steps + 1); }
    ctx.fillStyle = css('--text'); ctx.font = '12px "DejaVu Sans", sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(shown(zr[1], name), x + 18, area.y);
    ctx.textBaseline = 'bottom'; ctx.fillText(shown(zr[0], name), x + 18, area.y + area.h);
    ctx.save(); ctx.translate(x + 30, area.y + area.h / 2); ctx.rotate(-Math.PI / 2); ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillText(label(name), 0, 0); ctx.restore();
  }
  const extent = list => { let lo = Infinity, hi = -Infinity; for (const v of list) { if (v < lo) lo = v; if (v > hi) hi = v; } return lo <= hi ? [lo, hi] : [0, 1]; };
  // The rows that pass "Only when", or every row.
  function passing(got) {
    if (!options.filter) return null;
    return evaluate(options.filter, got.series, got.t.length);
  }
  const filterNames = () => options.filter ? compiled(options.filter).names : [];
  const rowsNote = (got, range) => `${range === 'screen' ? 'The time on the graph' : 'The whole log'}${got.step > 1 ? `, every ${nth(got.step)} row` : ''}${options.filter ? `, only when ${options.filter}` : ''}`;
  function hover(key, event) {
    const m = models[key], box = host.querySelector(`#lv-${key}`);
    if (!m?.X || !m.pts.length) return;
    const mx = event.offsetX, my = event.offsetY;
    let best = null, bestD = 14 * 14;
    for (const p of m.pts) { const dx = m.X(p) - mx, dy = m.Y(p) - my, d = dx * dx + dy * dy; if (d < bestD) { bestD = d; best = p; } }
    m.hover = best;
    box.querySelector('.lv-readout').textContent = best ? m.describe(best) : '';
  }

  // ---- Scatter: one channel against another, coloured by a third ----
  async function scatter() {
    const ticket = tickets.scatter = (tickets.scatter || 0) + 1, x = pick('scatter.x'), y = pick('scatter.y'), z = pick('scatter.z'), range = options.scatter.range;
    let names;
    try { names = [x, y, z, ...filterNames()].filter(Boolean); } catch (error) { modeNote('scatter', `Only when: ${error.message}`); return; }
    modeNote('scatter', 'Reading the log…');
    const got = await ranged(names, range);
    if (ticket !== tickets.scatter) return;
    const pass = passing(got), xs = got.series[x], ys = got.series[y], zs = z ? got.series[z] : null, pts = [];
    for (let i = 0; i < got.t.length; i++) if (xs[i] != null && ys[i] != null && (!pass || pass[i])) pts.push({x: xs[i], y: ys[i], z: zs ? zs[i] : null, t: got.t[i]});
    if (zs) pts.sort((a, b) => (a.z ?? -Infinity) - (b.z ?? -Infinity));        // The highest drawn last, on top
    models.scatter = {x, y, z, pts, xr: padded(...extent(pts.map(p => p.x))), yr: padded(...extent(pts.map(p => p.y))), zr: extent(pts.filter(p => p.z != null).map(p => p.z)),
      describe: p => `${x} ${shown(p.x, x)} · ${y} ${shown(p.y, y)}${z ? ` · ${z} ${shown(p.z, z)}` : ''} · at ${clock(p.t)}: tap for the graph`};
    drawScatter();
    modeNote('scatter', pts.length ? `${pts.length} points. ${rowsNote(got, range)}. Point at a dot to read it; tap it to see that moment on the graph.` : `No rows to draw. ${rowsNote(got, range)}.`);
  }
  function drawScatter() {
    const m = models.scatter, box = host.querySelector('#lv-scatter');
    if (!m || !box || box.offsetWidth === 0) return;
    const {ctx, w, h} = canvasIn(box);
    if (!m.pts.length) return;
    const {area, X, Y} = frame(ctx, w, h, m.xr, m.yr, label(m.x), label(m.y), m.z ? 92 : 16);
    m.X = p => X(p.x); m.Y = p => Y(p.y);
    const span = m.zr[1] - m.zr[0] || 1, buckets = new Map();
    for (const p of m.pts) { const c = !m.z ? css('--accent') : p.z == null ? '#6b7780' : heat((p.z - m.zr[0]) / span); (buckets.get(c) || buckets.set(c, []).get(c)).push(p); }
    ctx.save(); ctx.beginPath(); ctx.rect(area.x, area.y, area.w, area.h); ctx.clip();
    for (const [c, list] of buckets) { ctx.fillStyle = c; for (const p of list) ctx.fillRect(X(p.x) - 1.6, Y(p.y) - 1.6, 3.2, 3.2); }
    ctx.restore();
    if (m.z) legend(ctx, w, area, m.zr, m.z);
  }

  // ---- Table: a channel in cells of two others, like a VE table ----
  // "12" is twelve columns, round numbers across what the log reached; "500, 1000, 1500" are the values.
  function centres(spec, list) {
    const given = String(spec || '').split(/[\s,;]+/).filter(Boolean).map(Number).filter(Number.isFinite);
    if (given.length > 1) return [...new Set(given)].sort((a, b) => a - b);
    const count = clamp(Math.round(given[0] || 12), 2, 40), [lo, hi] = extent(list);
    if (!(hi > lo)) return [lo];
    const step = niceStep((hi - lo) / (count - 1)), out = [];
    for (let v = Math.round(lo / step) * step; out.length < count + 2 && v <= hi + step / 2; v += step) out.push(+v.toPrecision(12));
    return out;
  }
  const bin = nearest;
  async function table() {
    const ticket = tickets.table = (tickets.table || 0) + 1, o = options.table, x = pick('table.x'), y = pick('table.y'), z = pick('table.z'), stat = o.stat;
    let names;
    try { names = [x, y, z, ...filterNames()]; } catch (error) { modeNote('table', `Only when: ${error.message}`); return; }
    modeNote('table', 'Reading the log…');
    const got = await ranged(names, o.range);
    if (ticket !== tickets.table) return;
    const pass = passing(got), xs = got.series[x], ys = got.series[y], zs = got.series[z], counting = stat === 'count' || stat === 'time', idx = [];
    for (let i = 0; i < got.t.length; i++) if (xs[i] != null && ys[i] != null && (counting || zs[i] != null) && (!pass || pass[i])) idx.push(i);
    const box = host.querySelector('#lv-table');
    if (!idx.length) { box.replaceChildren(); models.table = {samples: 0}; modeNote('table', `No rows to put in the table. ${rowsNote(got, o.range)}.`); return; }
    const cols = centres(o.xbins, idx.map(i => xs[i])), rowsY = centres(o.ybins, idx.map(i => ys[i])), dt = got.t.length > 1 ? (got.t[got.t.length - 1] - got.t[0]) / (got.t.length - 1) : .05;
    const cells = rowsY.map(() => cols.map(() => ({n: 0, sum: 0, min: Infinity, max: -Infinity, first: null})));
    for (const i of idx) {
      const cell = cells[bin(rowsY, ys[i])][bin(cols, xs[i])], v = zs[i];
      cell.n++; cell.first ??= got.t[i];
      if (v != null) { cell.sum += v; cell.min = Math.min(cell.min, v); cell.max = Math.max(cell.max, v); }
    }
    const valueOf = c => !c.n ? null : stat === 'count' ? c.n : stat === 'time' ? c.n * dt : stat === 'min' ? c.min : stat === 'max' ? c.max : c.sum / c.n;
    const all = cells.flat().map(valueOf).filter(v => v != null && Number.isFinite(v)), [lo, hi] = extent(all);
    const digits = stat === 'count' ? 0 : stat === 'time' ? 1 : channel(z)?.digits ?? 1, axisDigits = list => decimals(list.length > 1 ? list[1] - list[0] : 1);
    const at = cursorT == null ? -1 : nearest(got.t, cursorT), atCell = at >= 0 && xs[at] != null && ys[at] != null ? [bin(rowsY, ys[at]), bin(cols, xs[at])] : null;
    const tableEl = el('table', undefined, 'lv-hist'), head = el('tr');
    head.append(el('th', `${y} ↑ · ${x} →`, 'lv-corner'), ...cols.map(c => el('th', c.toFixed(axisDigits(cols)))));
    const thead = el('thead'); thead.append(head);
    const tbody = el('tbody');
    for (let r = rowsY.length - 1; r >= 0; r--) {
      const tr = el('tr');
      tr.append(el('th', rowsY[r].toFixed(axisDigits(rowsY))));
      cols.forEach((_, c) => {
        const v = valueOf(cells[r][c]), td = el('td', v == null || !Number.isFinite(v) ? '' : v.toFixed(digits));
        td.dataset.cell = `${r},${c}`;
        if (v != null && Number.isFinite(v)) { td.className = 'lv-filled'; td.style.background = `hsl(${Math.round(240 - 240 * (hi > lo ? (v - lo) / (hi - lo) : .5))} 70% 30%)`; }
        if (atCell && atCell[0] === r && atCell[1] === c) td.classList.add('lv-at');
        tr.append(td);
      });
      tbody.append(tr);
    }
    tableEl.append(thead, tbody);
    box.replaceChildren(tableEl);
    models.table = {x, y, z, stat, cols, rows: rowsY, cells, dt, samples: idx.length};
    const what = {avg: `average ${z}`, min: `lowest ${z}`, max: `highest ${z}`, count: 'samples', time: 'seconds'}[stat];
    modeNote('table', `Each cell: the ${what} where ${x} and ${y} were nearest its column and row; ${idx.length} rows. ${rowsNote(got, o.range)}. Tap a cell for more.`);
  }
  function tableCell(td) {
    const m = models.table, [r, c] = td.dataset.cell.split(',').map(Number), cell = m?.cells?.[r]?.[c];
    if (!cell) return;
    for (const other of host.querySelectorAll('#lv-table td.lv-chosen')) other.classList.remove('lv-chosen');
    td.classList.add('lv-chosen');
    const noteEl = host.querySelector('[data-note="table"]');
    if (!cell.n) { noteEl.textContent = `${m.x} ${m.cols[c]} · ${m.y} ${m.rows[r]}: never there.`; return; }
    noteEl.replaceChildren(`${m.x} ${m.cols[c]} · ${m.y} ${m.rows[r]}: ${cell.n} samples (${(cell.n * m.dt).toFixed(1)} s)` +
      (cell.min <= cell.max ? `; ${m.z} average ${shown(cell.sum / cell.n, m.z)}, lowest ${shown(cell.min, m.z)}, highest ${shown(cell.max, m.z)}. ` : '. '));
    const show = el('button', `Show the first, at ${clock(cell.first)}, on the graph`); show.type = 'button';
    show.onclick = () => { setMode('graph'); goTo(cell.first, Math.min(view.end - view.start, 30)); };
    noteEl.append(show);
  }

  // ---- Data: the rows themselves ----
  async function rowsView() {
    const ticket = tickets.data = (tickets.data || 0) + 1, names = chosen.length ? chosen : DEFAULTS.filter(has);
    modeNote('data', 'Reading the log…');
    const got = await rows(names, view.start, view.end, 600, 'sample');
    if (ticket !== tickets.data) return;
    const tableEl = el('table', undefined, 'lv-rows-table'), head = el('tr');
    head.append(el('th', 'Time'), ...names.map(n => { const th = el('th', n); const c = channel(n); if (c?.units) th.append(el('small', ` ${c.units}`)); return th; }));
    const thead = el('thead'); thead.append(head);
    const tbody = el('tbody');
    for (let i = 0; i < got.t.length; i++) {
      const tr = el('tr'); tr.dataset.t = got.t[i];
      tr.append(el('th', precise(got.t[i]), 'lv-time'), ...names.map(n => el('td', shown(got.series[n]?.[i], n))));
      tbody.append(tr);
    }
    tableEl.append(thead, tbody);
    host.querySelector('#lv-rows').replaceChildren(tableEl);
    models.data = {rows: got.t.length, step: got.step, names};
    markRow();
    modeNote('data', `${got.t.length} rows, ${clock(view.start)} to ${clock(view.end)}${got.step > 1 ? `: every ${nth(got.step)} row (zoom in on the graph for every row)` : ': every row'}. Tap a row to choose it.`);
  }
  function markRow() {
    const box = host.querySelector('#lv-rows'), list = [...box.querySelectorAll('tr[data-t]')];
    for (const row of box.querySelectorAll('tr.lv-chosen')) row.classList.remove('lv-chosen');
    if (cursorT == null || !list.length) return;
    const i = nearest(list.map(r => Number(r.dataset.t)), cursorT), row = list[i];
    row.classList.add('lv-chosen');
    box.scrollTop = Math.max(0, row.offsetTop - box.clientHeight / 2);
  }

  // ---- Track: where the car was, from the GPS ----
  const PAIRS = [['Latitude', 'Longitude'], ['Nav Latitude', 'Nav Longitude']];
  async function track() {
    const ticket = tickets.track = (tickets.track || 0) + 1, pairs = PAIRS.filter(p => p.every(has)), z = pick('track.z'), range = options.track.range;
    if (!pairs.length) { models.track = null; canvasIn(host.querySelector('#lv-track')); modeNote('track', 'This log has no GPS position channels.'); return; }
    modeNote('track', 'Reading the log…');
    const got = await ranged([...pairs.flat(), z].filter(Boolean), range);
    if (ticket !== tickets.track) return;
    // The GPS's own fix first; the dead-reckoned position only if the GPS has none.
    let best = [];
    for (const [lat, lon] of pairs) {
      const pts = [];
      for (let i = 0; i < got.t.length; i++) {
        const a = got.series[lat][i], o = got.series[lon][i];
        if (a != null && o != null && (a || o) && Math.abs(a) <= 90 && Math.abs(o) <= 180) pts.push({lat: a, lon: o, z: z ? got.series[z][i] : null, t: got.t[i]});
      }
      if (pts.length > best.length * 2) best = pts;
    }
    if (!best.length) { models.track = null; canvasIn(host.querySelector('#lv-track')); modeNote('track', `No GPS fix in ${range === 'screen' ? 'the time on the graph' : 'this log'}.`); return; }
    models.track = {pts: best, z, zr: extent(best.filter(p => p.z != null).map(p => p.z)),
      describe: p => `${clock(p.t)}${z ? ` · ${z} ${shown(p.z, z)}` : ''} · ${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}: tap for the graph`};
    drawTrack();
    modeNote('track', `${best.length} positions. ${rowsNote(got, range)}. Green is where it starts, red where it ends, white the graph's cursor; tap the line to see that moment on the graph.`);
  }
  function drawTrack() {
    const m = models.track, box = host.querySelector('#lv-track');
    if (!m || !box || box.offsetWidth === 0) return;
    const {ctx, w, h} = canvasIn(box), right = m.z ? 92 : 16;
    const lat0 = (extent(m.pts.map(p => p.lat))[0] + extent(m.pts.map(p => p.lat))[1]) / 2, k = Math.cos(lat0 * Math.PI / 180);
    const [x0, x1] = extent(m.pts.map(p => p.lon * k)), [y0, y1] = extent(m.pts.map(p => p.lat));
    const room = {w: w - 32 - right, h: h - 40}, scale = Math.min(room.w / (x1 - x0 || 1e-5), room.h / (y1 - y0 || 1e-5));
    const ox = 16 + (room.w - (x1 - x0) * scale) / 2, oy = 16 + (room.h - (y1 - y0) * scale) / 2;
    m.X = p => ox + (p.lon * k - x0) * scale; m.Y = p => oy + (y1 - p.lat) * scale;
    const span = m.zr[1] - m.zr[0] || 1;
    ctx.lineWidth = 3; ctx.lineCap = 'round';
    for (let i = 1; i < m.pts.length; i++) {
      const a = m.pts[i - 1], b = m.pts[i];
      if (b.t - a.t > 5) continue;                                   // A gap in the fix: no line across it
      ctx.strokeStyle = !m.z ? css('--accent') : b.z == null ? '#6b7780' : heat((b.z - m.zr[0]) / span);
      ctx.beginPath(); ctx.moveTo(m.X(a), m.Y(a)); ctx.lineTo(m.X(b), m.Y(b)); ctx.stroke();
    }
    const dot = (p, fill, size) => { ctx.fillStyle = fill; ctx.strokeStyle = '#0a1116'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(m.X(p), m.Y(p), size, 0, 2 * Math.PI); ctx.fill(); ctx.stroke(); };
    dot(m.pts[0], '#3ddc84', 7); dot(m.pts[m.pts.length - 1], '#ff5c5c', 7);
    const near = t => m.pts[nearest(m.pts.map(p => p.t), t)];
    if (markA) dot(near(markA.t), '#ffd166', 6);
    if (cursorT != null) dot(near(cursorT), '#ffffff', 6);
    // A scale bar: about 120 px of road, in round metres.
    const metresPerPx = 111320 / scale, metres = niceStep(metresPerPx * 120), px = metres / metresPerPx;
    ctx.strokeStyle = css('--text'); ctx.fillStyle = css('--text'); ctx.lineWidth = 2; ctx.font = '12px "DejaVu Sans", sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
    ctx.beginPath(); ctx.moveTo(16, h - 12); ctx.lineTo(16 + px, h - 12); ctx.stroke();
    ctx.fillText(metres >= 1000 ? `${metres / 1000} km` : `${metres} m`, 16, h - 16);
    if (m.z) legend(ctx, w, {y: 16, h: h - 40}, m.zr, m.z);
  }

  // ---- Summary: the drive's peaks, and every channel's range ----
  async function summary() {
    const ticket = tickets.summary = (tickets.summary || 0) + 1, names = [...new Set([...SUMMARY.filter(has), ...chosen])].slice(0, 30);
    modeNote('summary', 'Reading the whole log…');
    const w = await wholeRows(names);
    if (ticket !== tickets.summary) return;
    const n = w.t.length, col = name => has(name) ? w.series[name] : null, stat = name => has(name) ? w.stats[name] : null;
    const dt = i => i + 1 < n ? Math.min(1, w.t[i + 1] - w.t[i]) : 0;
    const time = test => { let s = 0; for (let i = 0; i < n; i++) if (test(i)) s += dt(i); return s; };
    const runs = (test, least = 0) => { const out = []; let begun = null; for (let i = 0; i <= n; i++) { const on = i < n && test(i); if (on && begun == null) begun = i; if (!on && begun != null) { if (w.t[i - 1] - w.t[begun] >= least) out.push(begun); begun = null; } } return out; };
    const extreme = (name, test, low) => { const c = col(name); let best = -1; if (!c) return null; for (let i = 0; i < n; i++) if (c[i] != null && test(i) && (best < 0 || (low ? c[i] < c[best] : c[i] > c[best]))) best = i; return best < 0 ? null : {v: c[best], t: w.t[best]}; };
    const v = (name, i) => col(name)?.[i];
    const at = (name, t) => { const c = col(name); return c ? c[nearest(w.t, t)] : null; };
    const cards = [];
    const card = (title, value, detail, t) => cards.push({title, value, detail, t});
    const when = new Date(started(info.name, Date.now()));
    card('Drive', length(info.duration_s), `Started ${when.toLocaleString([], {weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})}`);
    if (col('Vehicle Speed')) {
      let miles = 0, moving = 0;
      for (let i = 0; i < n; i++) { const s = v('Vehicle Speed', i); if (s != null) { miles += s * dt(i) / 3600; if (s > 2) moving += dt(i); } }
      card('Distance', `${miles.toFixed(1)} mi`, moving ? `Average ${(miles / (moving / 3600)).toFixed(0)} MPH while moving` : 'Not moving');
      const top = stat('Vehicle Speed');
      if (top) card('Top speed', `${top.max.toFixed(0)} MPH`, `At ${clock(top.max_t)}`, top.max_t);
    }
    const rpm = stat('RPM');
    if (rpm) card('Highest RPM', rpm.max.toFixed(0), `At ${clock(rpm.max_t)}`, rpm.max_t);
    const boost = stat('Boost psi');
    if (boost) card('Peak boost', `${boost.max.toFixed(1)} psi`, `At ${clock(boost.max_t)}${col('RPM') ? `, ${Math.round(at('RPM', boost.max_t))} RPM` : ''}`, boost.max_t);
    if (col('TPS')) { const pulls = runs(i => v('TPS', i) > 90, .5); card('Wide open throttle', `${time(i => v('TPS', i) > 90).toFixed(0)} s`, `${pulls.length} pull${pulls.length === 1 ? '' : 's'} over 90 %`, pulls.length ? w.t[pulls[0]] : undefined); }
    if (col('Boost psi')) card('In boost', `${time(i => v('Boost psi', i) > 0).toFixed(0)} s`, 'Above 0 psi');
    if (col('AFR') && col('Boost psi')) {
      const lean = col('AFR Target 1') ? i => v('Boost psi', i) > 2 && v('AFR', i) - v('AFR Target 1', i) > 1 : i => v('Boost psi', i) > 2 && v('AFR', i) > 13.5;
      const moments = runs(i => v('AFR', i) != null && lean(i), .3), worst = extreme('AFR', i => v('Boost psi', i) > 2, false);
      card('Lean under boost', `${moments.length}`, `${col('AFR Target 1') ? 'Over 1 AFR leaner than the target' : 'Above 13.5 AFR'} above 2 psi, for 0.3 s or more${worst ? `; leanest ${worst.v.toFixed(1)} at ${clock(worst.t)}` : ''}`, moments.length ? w.t[moments[0]] : worst?.t);
    }
    for (const [name, title, unit] of [['CLT', 'Hottest coolant', '°F'], ['MAT', 'Hottest intake air', '°F']]) { const s = stat(name); if (s) card(title, `${s.max.toFixed(0)} ${unit}`, `At ${clock(s.max_t)}`, s.max_t); }
    if (col('OilPressure') && col('RPM')) { const low = extreme('OilPressure', i => v('RPM', i) > 2500, true); if (low) card('Lowest oil pressure over 2500 RPM', `${low.v.toFixed(0)} psi`, `At ${clock(low.t)}`, low.t); }
    if (col('Batt V') && col('RPM')) { const low = extreme('Batt V', i => v('RPM', i) > 500, true); if (low) card('Lowest battery, running', `${low.v.toFixed(1)} V`, `At ${clock(low.t)}`, low.t); }
    if (col('Meth flow')) { const sprays = runs(i => v('Meth flow', i) > 0); card('Water/meth sprayed', `${time(i => v('Meth flow', i) > 0).toFixed(0)} s`, `${sprays.length} time${sprays.length === 1 ? '' : 's'}`, sprays.length ? w.t[sprays[0]] : undefined); }
    const markList = allMarks();
    card('Bookmarks and alerts', String(markList.length), markList.slice(0, 3).map(m => `${m.text} ${clock(m.t)}`).join(' · ') || 'None', markList[0]?.t);
    const box = host.querySelector('#lv-summary'), grid = el('div', undefined, 'lv-cards');
    for (const c of cards) {
      const item = el('div', undefined, 'lv-card');
      item.append(el('h5', c.title), el('strong', c.value), el('small', c.detail));
      if (c.t !== undefined) { const b = el('button', 'Show'); b.type = 'button'; b.dataset.t = c.t; item.append(b); }
      grid.append(item);
    }
    const tableEl = el('table', undefined, 'lv-stats'), head = el('tr');
    head.append(...['Channel', 'Lowest', 'Average', 'Highest'].map(t => el('th', t)));
    const thead = el('thead'); thead.append(head);
    const tbody = el('tbody');
    for (const name of names) {
      const s = stat(name), tr = el('tr'), th = el('th', name);
      if (channel(name)?.units) th.append(el('small', ` ${channel(name).units}`));
      const timed = (value, t) => { const td = el('td'); if (value == null) { td.textContent = '—'; return td; } const b = el('button', shown(value, name)); b.type = 'button'; b.dataset.t = t; b.title = `At ${clock(t)}: show it on the graph`; td.append(b, el('small', ` ${clock(t)}`)); return td; };
      tr.append(th, timed(s?.min, s?.min_t), el('td', shown(s?.avg, name)), timed(s?.max, s?.max_t));
      tbody.append(tr);
    }
    tableEl.append(thead, tbody);
    box.replaceChildren(el('h4', 'This drive', 'lv-group'), grid, el('h4', 'Channels: the whole log', 'lv-group'), tableEl);
    models.summary = {cards: cards.map(c => c.title), channels: names.length};
    modeNote('summary', `Lowest and highest from every row of the log${w.step > 1 ? `; the rest from every ${nth(w.step)} row` : ''}. Show, or a value, opens the graph at that moment.`);
  }

  window.addEventListener('frogdash-state', ({detail}) => { latest = detail.snapshot || {}; });
  // Anything that goes wrong is said on the panel, not left as "Loading" (November 2026: the
  // owner's browser kept "Loading the log viewer" and nothing said why).
  function reporting(start) {
    return (...args) => Promise.resolve().then(() => start(...args)).catch(error => {
      if (!built) host.replaceChildren(el('p', '', 'control-note'));
      (host.querySelector('#lv-browser-note') || host.firstChild).textContent = `The log viewer stopped: ${error?.message || error}`;
    });
  }
  const safeLoad = reporting(load);
  window.FrogdashLogView = {open: () => safeLoad(), openLog: name => reporting(openLog)(name), back, toggle, zoom, move, mode: setMode, goTo, find: findNext, play, stopPlay,
    model: key => models[key], get info() { return info; }, get view() { return view; }, get channels() { return chosen; }, get logs() { return logs; },
    get cursor() { return cursorT; }, get markA() { return markA; }, get playing() { return !!playing; }, get calculated() { return usable.map(c => c.name); }};
  // It starts the moment its panel is on the screen, however it got there: the tab pressed,
  // the workspace opened again on this tab, or this file arriving after the tab was opened.
  new ResizeObserver(() => { if (!built && host.offsetWidth > 0) safeLoad(); }).observe(host);
  if (!built && host.offsetWidth > 0) safeLoad();
})();
