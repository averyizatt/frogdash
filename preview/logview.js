/* Log viewer (Drive > Log viewer): the dash's MLG logs as graphs, MegaLogViewer style.
   Stacked graphs on one time line, each with up to four channels on their own scales; the
   cursor shows every channel at one moment; drag across a graph to zoom; min, average and
   max of what is on the screen; bookmarks and alerts as marks on the time line. The Pi reads
   only the channels and the time on screen (hardware/frogdash/logview.py), thinned so a
   spike is never lost. Drawn with uPlot (uPlot.iife.min.js, MIT). */
(() => {
  'use strict';
  const host = document.getElementById('log-viewer');
  if (!host) return;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
  const COLORS = ['#ffb14a', '#5fd0ff', '#8befc4', '#ff6b8b', '#c59bff', '#f2e46b', '#ff8f3d', '#7aa7ff'];
  const PER_PANE = 4, MOST_PANES = 4, STORE = 'frogdash-logview-panes';
  // Where a fresh viewer starts: the graphs a tuner opens first, from what the log has.
  const DEFAULTS = [['RPM'], ['AFR', 'AFR Target 1', 'Boost psi', 'MAP'], ['CLT', 'MAT'], ['TPS', 'Vehicle Speed', 'SPK: Spark Advance']];
  let latest = {}, logs = [], info = null, view = null, data = null, plots = [], panes = [], cursorIdx = null, loading = 0, built = false;
  const demo = () => latest.mode === 'demo';

  // ---- Where the logs come from: the Pi, or in the preview a simulated drive ----
  const request = async url => { const r = await fetch(url, {cache: 'no-store'}); if (!r.ok) throw new Error(await r.text() || r.statusText); return r.json(); };
  const DEMO_CHANNELS = [['RPM', 'RPM', 'engine', 0], ['MAP', 'kPa', 'ecu', 0], ['Boost psi', 'psi', 'engine', 1], ['TPS', '%', 'ecu', 0],
    ['AFR', 'AFR', 'engine', 1], ['AFR Target 1', 'AFR', 'ecu', 1], ['CLT', 'F', 'engine', 0], ['MAT', 'F', 'engine', 0],
    ['Vehicle Speed', 'MPH', 'vehicle', 0], ['SPK: Spark Advance', 'deg', 'ecu', 1], ['Batt V', 'V', 'vehicle', 1], ['Meth flow', 'ml/min', 'meth', 0]];
  function demoValue(name, t) {
    const pull = Math.max(0, Math.sin(t / 37) * 1.6 - .6), rpm = 900 + 2600 * (1 + Math.sin(t / 23)) / 2 + 2400 * pull;
    const boost = Math.max(-9, -9 + 21 * pull + Math.sin(t * 1.7) * .4);
    return ({RPM: rpm, MAP: 101 + boost * 6.9, 'Boost psi': boost, TPS: Math.min(100, 12 + 80 * pull + Math.sin(t / 5) * 4),
      AFR: 14.7 - 3 * pull + Math.sin(t * 2.3) * .25, 'AFR Target 1': 14.7 - 3.1 * pull, CLT: 150 + Math.min(45, t / 8) + Math.sin(t / 90) * 3,
      MAT: 85 + 40 * pull, 'Vehicle Speed': Math.max(0, 25 + 35 * Math.sin(t / 61) + 15 * pull), 'SPK: Spark Advance': 30 - 14 * pull,
      'Batt V': 14.1 + Math.sin(t / 13) * .08, 'Meth flow': boost > 8 ? 320 * pull : 0})[name];
  }
  const source = {
    list: async () => demo() ? [{name: 'frogdash-demo-20261105T221000Z-preview.mlg', bytes: 1_800_000, modified_ms: Date.now(), active: false}]
      : (await request('/logs')).files.filter(f => f.bytes > 0),
    describe: async name => demo() ? {name, rows: 18000, duration_s: 900, started_s: Date.now() / 1000 - 1200,
      channels: DEMO_CHANNELS.map(([n, units, category, digits]) => ({name: n, units, category, digits})), markers: [{t: 312.4, text: 'Bookmark 1'}],
      events: [{t: 528, label: 'AFR LEAN', kind: 'alert'}], recording: false} : request(`/logs/${encodeURIComponent(name)}/view`),
    series: async (name, channels, start, end, points) => {
      if (demo()) {
        const count = Math.min(points, Math.round((end - start) * 20)), t = [], series = Object.fromEntries(channels.map(c => [c, []]));
        for (let i = 0; i <= count; i++) { const at = start + (end - start) * i / count; t.push(at); for (const c of channels) series[c].push(demoValue(c, at)); }
        const stats = Object.fromEntries(channels.map(c => { const v = series[c]; return [c, {min: Math.min(...v), max: Math.max(...v), avg: v.reduce((a, b) => a + b, 0) / v.length}]; }));
        return {t, series, stats, thinned: false};
      }
      const q = new URLSearchParams({channels: channels.join(','), start: start.toFixed(3), end: end.toFixed(3), points: String(points)});
      return request(`/logs/${encodeURIComponent(name)}/series?${q}`);
    },
  };

  // ---- Layout ----
  function build() {
    built = true;
    host.classList.add('logview');
    host.innerHTML = `<div class="lv-toolbar">
        <select id="lv-file" aria-label="Log"></select><button type="button" id="lv-refresh">Refresh</button>
        <span class="lv-gap"></span>
        <button type="button" data-lv="in" title="Zoom in (Up)">Zoom in</button><button type="button" data-lv="out" title="Zoom out (Down)">Zoom out</button>
        <button type="button" data-lv="left" aria-label="Earlier" title="Earlier (Left)">◀</button><button type="button" data-lv="right" aria-label="Later" title="Later (Right)">▶</button>
        <button type="button" data-lv="all">Whole log</button><button type="button" data-lv="pane">+ Graph</button>
        <span id="lv-range" class="lv-range"></span></div>
      <div class="lv-body">
        <div id="lv-panes" class="lv-panes" tabindex="0" data-wheel-edit="SET / COAST: earlier, later, zoom in or out  |  ON: done" aria-label="Log graphs: press ON (Enter), then Left and Right move in time, Up and Down zoom"></div>
        <aside class="lv-side">
          <div class="lv-stats" data-wheel-scroll tabindex="0" aria-label="Channel values"><table><thead><tr><th>Channel</th><th>At cursor</th><th>Min</th><th>Avg</th><th>Max</th></tr></thead><tbody id="lv-stats"></tbody></table></div>
          <p id="lv-note" class="control-note" role="status"></p>
        </aside>
      </div>`;
    host.querySelector('#lv-file').onchange = event => open(event.target.value);
    host.querySelector('#lv-refresh').onclick = () => load(true);
    host.querySelector('.lv-toolbar').addEventListener('click', event => {
      const action = event.target.closest('[data-lv]')?.dataset.lv;
      if (action === 'pane') { if (panes.length < MOST_PANES) { panes.push([]); save(); layout(); } }
      else if (action) move(action);
    });
    // The steering wheel or the arrow keys, after ON on the graphs (navigation.js, [data-wheel-edit]).
    host.querySelector('#lv-panes').addEventListener('wheel-adjust', event => {
      const action = {left: 'left', right: 'right', up: 'in', down: 'out'}[event.detail];
      if (action) move(action);
    });
  }
  const note = text => { host.querySelector('#lv-note').textContent = text; };
  const clock = s => { s = Math.max(0, s); const m = Math.floor(s / 60), r = s - m * 60; return `${m}:${r < 10 ? '0' : ''}${r.toFixed(r < 60 && view && view.end - view.start < 30 ? 1 : 0)}`; };
  const channel = name => info?.channels.find(c => c.name === name);
  const shown = (value, name) => value == null || !isFinite(value) ? '—' : `${value.toFixed(channel(name)?.digits ?? 1)}`;

  // ---- The logs, the one open, and its graphs ----
  // The first state update says whether this is the car or the preview. This file loads after
  // the gauges, so it can start before one has arrived here: it waits for it (the live preview
  // asked the web site for the Pi's logs and said they could not be listed, November 2026).
  const firstState = () => latest.mode ? Promise.resolve() : new Promise(resolve => {
    const done = () => { window.removeEventListener('frogdash-state', done); clearTimeout(timer); resolve(); };
    const timer = setTimeout(done, 4000);
    window.addEventListener('frogdash-state', done);
  });
  async function load(refresh = false) {
    if (!built) build();
    note('Opening the logs…');
    await firstState();
    try {
      logs = await source.list();
    } catch (error) { note(`The logs could not be listed: ${error.message}`); return; }
    const select = host.querySelector('#lv-file'), previous = info?.name || select.value;
    select.replaceChildren(...logs.map(f => {
      const started = f.name.match(/(\d{8}T\d{6}Z)/)?.[1], when = started ? new Date(started.replace(/(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)Z/, '$1-$2-$3T$4:$5:$6Z')) : new Date(f.modified_ms);
      const option = el('option', `${when.toLocaleString([], {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})} · ${(f.bytes / 1048576).toFixed(1)} MB${f.active ? ' · recording now' : ''}`);
      option.value = f.name; return option;
    }));
    if (!logs.length) { note('No logs yet: the dash records every drive, and they appear here.'); return; }
    const name = logs.some(f => f.name === previous) ? previous : logs[0].name;   // The one open stays open
    select.value = name;
    await open(name, refresh);
  }
  async function open(name, keepView = false) {
    note('Opening the log…');
    try {
      info = await source.describe(name);
    } catch (error) { note(`This log cannot be shown: ${error.message}`); return; }
    if (!keepView || !view) view = {start: 0, end: Math.max(1, info.duration_s)};
    view.end = Math.min(view.end, Math.max(1, info.duration_s));
    panes = restore();
    layout();
  }
  function restore() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(STORE) || 'null'); } catch { saved = null; }
    const has = name => !!channel(name);
    let result = (Array.isArray(saved) ? saved : DEFAULTS).map(p => (Array.isArray(p) ? p : []).filter(has).slice(0, PER_PANE)).filter(p => p.length);
    if (!result.length) result = DEFAULTS.map(p => p.filter(has).slice(0, 3)).filter(p => p.length);
    if (!result.length && info.channels.length) result = [info.channels.slice(0, 3).map(c => c.name)];
    return result.slice(0, MOST_PANES);
  }
  function save() { try { localStorage.setItem(STORE, JSON.stringify(panes)); } catch { /* Kept for this visit only */ } }

  function layout() {
    for (const plot of plots) plot.destroy();
    plots = [];
    const box = host.querySelector('#lv-panes');
    box.replaceChildren();
    if (!window.uPlot) { note('The graph library did not load'); return; }
    const muted = css('--muted'), line = css('--line');
    panes.forEach((names, index) => {
      const pane = el('section', undefined, 'lv-pane'), head = el('header'), area = el('div', undefined, 'lv-plot');
      names.forEach((name, i) => {
        const chip = el('button', '', 'lv-chip'); chip.type = 'button';
        chip.style.setProperty('--chip', COLORS[(index * PER_PANE + i) % COLORS.length]);
        chip.append(el('span', name), el('small', channel(name)?.units || ''), el('b', '×'));
        chip.title = `Remove ${name}`; chip.onclick = () => { names.splice(i, 1); if (!names.length && panes.length > 1) panes.splice(index, 1); save(); layout(); };
        head.append(chip);
      });
      if (names.length < PER_PANE) {
        const add = el('select', undefined, 'lv-add'); add.setAttribute('aria-label', `Add a channel to graph ${index + 1}`);
        add.append(Object.assign(el('option', '+ Channel'), {value: ''}));
        const groups = {};
        for (const c of info.channels) if (!names.includes(c.name)) (groups[c.category || 'Other'] ??= []).push(c);
        for (const [group, list] of Object.entries(groups).sort()) {
          const optgroup = el('optgroup'); optgroup.label = group;
          for (const c of list) optgroup.append(Object.assign(el('option', c.units ? `${c.name} (${c.units})` : c.name), {value: c.name}));
          add.append(optgroup);
        }
        add.onchange = () => { if (add.value) { names.push(add.value); save(); layout(); } };
        head.append(add);
      }
      if (panes.length > 1) { const remove = el('button', 'Remove graph', 'lv-remove'); remove.type = 'button'; remove.onclick = () => { panes.splice(index, 1); save(); layout(); }; head.append(remove); }
      pane.append(head, area); box.append(pane);
      const plot = new window.uPlot({
        width: 600, height: 150, pxAlign: 0,
        scales: {x: {time: false}, ...Object.fromEntries(names.map((n, i) => [`y${i}`, {auto: true}]))},
        axes: [{stroke: muted, grid: {stroke: line, width: 1}, ticks: {stroke: line, width: 1}, font: '12px "DejaVu Sans", sans-serif', size: 28,
                values: (self, ticks) => ticks.map(clock), show: index === panes.length - 1},
          ...names.slice(0, 2).map((n, i) => ({scale: `y${i}`, side: i ? 1 : 3, stroke: COLORS[(index * PER_PANE + i) % COLORS.length], size: 54,
            font: '12px "DejaVu Sans", sans-serif', grid: {show: i === 0, stroke: line, width: 1}, ticks: {stroke: line, width: 1}}))],
        series: [{value: (self, v) => v == null ? '—' : clock(v)},
          ...names.map((n, i) => ({label: n, scale: `y${i}`, stroke: COLORS[(index * PER_PANE + i) % COLORS.length], width: 1.6, spanGaps: false,
            points: {show: false}, value: (self, v) => shown(v, n)}))],
        cursor: {sync: {key: 'frogdash-logview'}, drag: {x: true, y: false, setScale: false}, points: {size: 6}},
        legend: {show: false},
        hooks: {
          setSelect: [u => {
            if (u.select.width > 6) zoom(u.posToVal(u.select.left, 'x'), u.posToVal(u.select.left + u.select.width, 'x'));
            u.setSelect({left: 0, top: 0, width: 0, height: 0}, false);
          }],
          setCursor: [u => { if (u.cursor.idx !== cursorIdx) { cursorIdx = u.cursor.idx; table(); } }],
          draw: [u => marks(u, index === 0)],
        },
      }, [[], ...names.map(() => [])], area);
      new ResizeObserver(() => plot.setSize({width: Math.max(240, area.clientWidth), height: Math.max(90, area.clientHeight)})).observe(area);
      plots.push(plot);
    });
    host.querySelector('[data-lv="pane"]').disabled = panes.length >= MOST_PANES;
    fetchRange();
  }
  // Bookmarks (from the log) and the drive's alerts and bookmarks, as lines across the graphs.
  function marks(u, labels) {
    const all = [...(info?.markers || []).map(m => ({t: m.t, text: m.text, kind: 'bookmark'})), ...(info?.events || []).map(e => ({t: e.t, text: e.label, kind: e.kind}))];
    const ctx = u.ctx, top = u.bbox.top, height = u.bbox.height;
    ctx.save();
    for (const mark of all) {
      if (mark.t < u.scales.x.min || mark.t > u.scales.x.max) continue;
      const x = Math.round(u.valToPos(mark.t, 'x', true));
      ctx.strokeStyle = mark.kind === 'alert' ? '#ff6b6b' : '#ffd166'; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke();
      if (labels) { ctx.setLineDash([]); ctx.fillStyle = ctx.strokeStyle; ctx.font = `${13 * devicePixelRatio}px "DejaVu Sans", sans-serif`; ctx.fillText(mark.text, x + 4, top + 14 * devicePixelRatio); }
    }
    ctx.restore();
  }

  // ---- The time on screen ----
  function zoom(start, end) {
    const length = Math.max(1, info?.duration_s || 1), width = Math.max(.5, end - start);
    start = Math.max(0, Math.min(start, length - width));
    view = {start, end: Math.min(length, start + width)};
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
  async function fetchRange() {
    if (!info || !plots.length) return;
    const names = [...new Set(panes.flat())], ticket = ++loading;
    host.querySelector('#lv-range').textContent = `${clock(view.start)} – ${clock(view.end)} of ${clock(info.duration_s)}`;
    if (!names.length) { table(); return; }
    let got;
    try {
      got = await source.series(info.name, names, view.start, view.end, Math.min(4000, Math.round(host.clientWidth * 1.5) || 1500));
    } catch (error) { note(`The readings could not be read: ${error.message}`); return; }
    if (ticket !== loading) return;          // A newer range was asked for meanwhile
    data = got;
    panes.forEach((list, i) => {
      const plot = plots[i];
      if (!plot) return;
      plot.setData([data.t, ...list.map(n => data.series[n] || [])], false);
      plot.setScale('x', {min: view.start, max: view.end});
    });
    cursorIdx = null;
    table();
    note(`${info.recording ? 'Still recording: Refresh for the newest. ' : ''}${data.thinned ? 'Zoomed out: each point is the lowest and highest of its stretch, so no peak is lost. ' : ''}Drag across a graph to zoom in.`);
  }
  function table() {
    const body = host.querySelector('#lv-stats');
    if (!body || !data) return;
    const rows = [];
    panes.forEach((list, p) => list.forEach((name, i) => {
      const row = el('tr'), stat = data.stats?.[name], color = COLORS[(p * PER_PANE + i) % COLORS.length];
      const label = el('td'); label.append(Object.assign(el('i'), {className: 'lv-swatch'}), el('span', `${name}${channel(name)?.units ? ' (' + channel(name).units + ')' : ''}`));
      label.firstChild.style.background = color;
      label.title = label.textContent;   // The whole name when it is cut short
      const at = cursorIdx == null ? null : data.series[name]?.[cursorIdx];
      row.append(label, el('td', cursorIdx == null ? '—' : `${shown(at, name)}`), el('td', shown(stat?.min, name)), el('td', shown(stat?.avg, name)), el('td', shown(stat?.max, name)));
      rows.push(row);
    }));
    const when = cursorIdx == null ? null : data.t[cursorIdx];
    host.querySelector('thead th:nth-child(2)').textContent = when == null ? 'At cursor' : `At ${clock(when)}`;
    body.replaceChildren(...rows);
  }

  window.addEventListener('frogdash-state', ({detail}) => { latest = detail.snapshot || {}; });
  window.FrogdashLogView = {open: () => load(), get info() { return info; }, get view() { return view; }, get panes() { return panes; }, zoom, move};
  // Opened before this file had loaded: start now.
  if (!host.closest('[hidden]')) load();
})();
