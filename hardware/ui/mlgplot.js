/* Log viewer (Drive > Log viewer): the dash's MLG logs as a graph, MegaLogViewer style.
   (Named mlgplot, not logview: blockers' privacy lists drop files named like logging, and the
   owner's browser never loaded logview.js, November 2026.)
   First the logs, as a list to choose from; then the chosen one as one graph of the channels
   picked beside it, each on its own scale. The channel list is every channel in the log: a
   tap puts one on the graph or takes it off, and the ones on it show their value at the cursor
   with their lowest, average and highest on the screen. Drag across the graph to zoom;
   bookmarks and alerts are marks on the time line. The Pi reads only the channels and the time
   on screen (hardware/frogdash/logview.py), thinned so a spike is never lost. Drawn with uPlot
   (uPlot.iife.min.js, MIT). */
(() => {
  'use strict';
  const host = document.getElementById('log-viewer');
  if (!host) return;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
  const COLORS = ['#ffb14a', '#5fd0ff', '#8befc4', '#ff6b8b', '#c59bff', '#f2e46b', '#ff8f3d', '#7aa7ff'];
  const MOST = COLORS.length, STORE = 'frogdash-logview-channels';
  // What a fresh viewer shows: what a tuner looks at first, from what the log has.
  const DEFAULTS = ['RPM', 'AFR', 'AFR Target 1', 'Boost psi'];
  let latest = {}, logs = [], info = null, view = null, data = null, plot = null, chosen = [], cursorIdx = null, loading = 0, built = false, find = '';
  const demo = () => latest.mode === 'demo';

  // ---- Where the logs come from: the Pi, or in the preview simulated drives ----
  const request = async url => { const r = await fetch(url, {cache: 'no-store'}); if (!r.ok) throw new Error(await r.text() || r.statusText); return r.json(); };
  const DEMO_CHANNELS = [['RPM', 'RPM', 'engine', 0], ['MAP', 'kPa', 'ecu', 0], ['Boost psi', 'psi', 'engine', 1], ['TPS', '%', 'ecu', 0],
    ['AFR', 'AFR', 'engine', 1], ['AFR Target 1', 'AFR', 'ecu', 1], ['CLT', 'F', 'engine', 0], ['MAT', 'F', 'engine', 0],
    ['Vehicle Speed', 'MPH', 'vehicle', 0], ['SPK: Spark Advance', 'deg', 'ecu', 1], ['Batt V', 'V', 'vehicle', 1], ['Meth flow', 'ml/min', 'meth', 0],
    ['OilPressure', 'psi', 'engine', 0], ['FuelPressure', 'psi', 'engine', 0], ['EGO cor1', '%', 'engine', 0], ['PW', 'ms', 'ecu', 2]];
  // Four simulated drives: the same car, a different stretch of road each.
  const DEMO_LOGS = [['20261105T221000Z', 900, 1.8], ['20261104T171500Z', 1680, 3.3], ['20261102T090500Z', 420, .8], ['20261029T193000Z', 2460, 4.9]]
    .map(([stamp, seconds, mb], i) => ({name: `frogdash-demo-${stamp}-preview${i}.mlg`, bytes: mb * 1048576, seconds, offset: i * 311}));
  function demoValue(name, t) {
    const pull = Math.max(0, Math.sin(t / 37) * 1.6 - .6), rpm = 900 + 2600 * (1 + Math.sin(t / 23)) / 2 + 2400 * pull;
    const boost = Math.max(-9, -9 + 21 * pull + Math.sin(t * 1.7) * .4);
    return ({RPM: rpm, MAP: 101 + boost * 6.9, 'Boost psi': boost, TPS: Math.min(100, 12 + 80 * pull + Math.sin(t / 5) * 4),
      AFR: 14.7 - 3 * pull + Math.sin(t * 2.3) * .25, 'AFR Target 1': 14.7 - 3.1 * pull, CLT: 150 + Math.min(45, t / 8) + Math.sin(t / 90) * 3,
      MAT: 85 + 40 * pull, 'Vehicle Speed': Math.max(0, 25 + 35 * Math.sin(t / 61) + 15 * pull), 'SPK: Spark Advance': 30 - 14 * pull,
      'Batt V': 14.1 + Math.sin(t / 13) * .08, 'Meth flow': boost > 8 ? 320 * pull : 0, OilPressure: 18 + rpm / 120,
      FuelPressure: 43 + Math.max(0, boost), 'EGO cor1': 100 + Math.sin(t / 7) * 4, PW: 1.6 + 9 * pull + rpm / 4000})[name];
  }
  const demoLog = name => DEMO_LOGS.find(l => l.name === name) || DEMO_LOGS[0];
  const source = {
    list: async () => demo() ? DEMO_LOGS.map(l => ({name: l.name, bytes: l.bytes, modified_ms: started(l.name) + l.seconds * 1000, active: false}))
      : (await request('/logs')).files.filter(f => f.bytes > 0),
    describe: async name => demo() ? {name, rows: demoLog(name).seconds * 20, duration_s: demoLog(name).seconds, started_s: started(name) / 1000,
      channels: DEMO_CHANNELS.map(([n, units, category, digits]) => ({name: n, units, category, digits})),
      markers: [{t: Math.round(demoLog(name).seconds * .35), text: 'Bookmark 1'}],
      events: [{t: Math.round(demoLog(name).seconds * .6), label: 'AFR LEAN', kind: 'alert'}], recording: false} : request(`/logs/${encodeURIComponent(name)}/view`),
    series: async (name, channels, start, end, points) => {
      if (demo()) {
        const offset = demoLog(name).offset, count = Math.max(2, Math.min(points, Math.round((end - start) * 20))), t = [], series = Object.fromEntries(channels.map(c => [c, []]));
        for (let i = 0; i <= count; i++) { const at = start + (end - start) * i / count; t.push(at); for (const c of channels) series[c].push(demoValue(c, at + offset)); }
        const stats = Object.fromEntries(channels.map(c => { const v = series[c]; return [c, {min: Math.min(...v), max: Math.max(...v), avg: v.reduce((a, b) => a + b, 0) / v.length}]; }));
        return {t, series, stats, thinned: false};
      }
      const q = new URLSearchParams({channels: channels.join(','), start: start.toFixed(3), end: end.toFixed(3), points: String(points)});
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

  // ---- Layout: the list of logs, or one log ----
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
          <button type="button" data-lv="in" title="Zoom in (Up)">Zoom in</button><button type="button" data-lv="out" title="Zoom out (Down)">Zoom out</button>
          <button type="button" data-lv="left" aria-label="Earlier" title="Earlier (Left)">◀</button><button type="button" data-lv="right" aria-label="Later" title="Later (Right)">▶</button>
          <button type="button" data-lv="all">Whole log</button><span id="lv-range" class="lv-range"></span></header>
        <div class="lv-body">
          <div class="lv-graph">
            <div id="lv-plot" class="lv-plot" tabindex="0" data-wheel-edit="SET / COAST: earlier, later, zoom in or out  |  ON: done" aria-label="Graph: press ON (Enter), then Left and Right move in time, Up and Down zoom"></div>
            <p id="lv-note" class="control-note" role="status"></p>
          </div>
          <aside class="lv-side">
            <input id="lv-find" type="search" placeholder="Find a channel, e.g. oil or AFR" autocomplete="off" aria-label="Find a channel">
            <div class="lv-channel lv-channel-head" aria-hidden="true"><span>Channel</span><span id="lv-at">At cursor</span><span>Min</span><span>Avg</span><span>Max</span></div>
            <div id="lv-channels" class="lv-channels" data-wheel-scroll tabindex="0" aria-label="Channels: tap one to show or hide it"></div>
          </aside>
        </div>
      </section>`;
    host.querySelector('#lv-refresh').onclick = () => load(true);
    host.querySelector('#lv-back').onclick = back;
    host.querySelector('#lv-find').oninput = event => { find = event.target.value.trim().toLowerCase(); channelList(); };
    host.querySelector('.lv-viewer .lv-toolbar').addEventListener('click', event => {
      const action = event.target.closest('[data-lv]')?.dataset.lv;
      if (action) move(action);
    });
    // The steering wheel or the arrow keys, after ON on the graph (navigation.js, [data-wheel-edit]).
    host.querySelector('#lv-plot').addEventListener('wheel-adjust', event => {
      const action = {left: 'left', right: 'right', up: 'in', down: 'out'}[event.detail];
      if (action) move(action);
    });
  }
  const note = text => { host.querySelector(info && !host.querySelector('#lv-viewer').hidden ? '#lv-note' : '#lv-browser-note').textContent = text; };
  const clock = s => { s = Math.max(0, s); const m = Math.floor(s / 60), r = s - m * 60; return `${m}:${r < 10 ? '0' : ''}${r.toFixed(r < 60 && view && view.end - view.start < 30 ? 1 : 0)}`; };
  const channel = name => info?.channels.find(c => c.name === name);
  const shown = (value, name) => value == null || !isFinite(value) ? '—' : `${value.toFixed(channel(name)?.digits ?? 1)}`;
  const color = name => COLORS[chosen.indexOf(name) % COLORS.length];

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
    note(logs.length ? 'Choose a log to see it as a graph.' : 'No logs yet: the dash records every drive, and they appear here.');
  }
  function back() {
    info = null; data = null;
    plot?.destroy(); plot = null;
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
    chosen = restore();
    host.querySelector('#lv-browser').hidden = true;
    host.querySelector('#lv-viewer').hidden = false;
    const when = new Date(started(name, Date.now()));
    host.querySelector('#lv-title').textContent = `${when.toLocaleString([], {weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})} · ${length(info.duration_s)}${info.recording ? ' · recording now' : ''}`;
    find = ''; host.querySelector('#lv-find').value = '';
    graph();
  }
  function restore() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(STORE) || 'null'); } catch { saved = null; }
    const has = name => !!channel(name);
    let result = (Array.isArray(saved) ? saved : DEFAULTS).filter(has).slice(0, MOST);
    if (!result.length) result = DEFAULTS.filter(has);
    if (!result.length) result = info.channels.slice(0, 3).map(c => c.name);
    return result;
  }
  function save() { try { localStorage.setItem(STORE, JSON.stringify(chosen)); } catch { /* Kept for this visit only */ } }
  function toggle(name) {
    if (chosen.includes(name)) chosen = chosen.filter(n => n !== name);
    else if (chosen.length >= MOST) { note(`Up to ${MOST} channels on the graph: take one off first.`); return; }
    else chosen = [...chosen, name];
    save();
    graph();
  }

  // The graph: every chosen channel on its own scale; the first two have their scales drawn.
  function graph() {
    plot?.destroy(); plot = null;
    const area = host.querySelector('#lv-plot');
    area.replaceChildren();
    if (!window.uPlot) { note('The graph library did not load'); return; }
    const muted = css('--muted'), line = css('--line'), font = '12px "DejaVu Sans", sans-serif';
    plot = new window.uPlot({
      width: Math.max(240, area.clientWidth), height: Math.max(120, area.clientHeight), pxAlign: 0,
      scales: {x: {time: false}, ...Object.fromEntries(chosen.map((n, i) => [`y${i}`, {auto: true}]))},
      axes: [{stroke: muted, grid: {stroke: line, width: 1}, ticks: {stroke: line, width: 1}, font, size: 30, values: (self, ticks) => ticks.map(clock)},
        ...chosen.slice(0, 2).map((n, i) => ({scale: `y${i}`, side: i ? 1 : 3, stroke: COLORS[i], size: 56, font,
          grid: {show: i === 0, stroke: line, width: 1}, ticks: {stroke: line, width: 1}}))],
      series: [{value: (self, v) => v == null ? '—' : clock(v)},
        ...chosen.map((n, i) => ({label: n, scale: `y${i}`, stroke: COLORS[i], width: 1.8, spanGaps: false, points: {show: false}, value: (self, v) => shown(v, n)}))],
      cursor: {drag: {x: true, y: false, setScale: false}, points: {size: 7}},
      legend: {show: false},
      hooks: {
        setSelect: [u => {
          if (u.select.width > 6) zoom(u.posToVal(u.select.left, 'x'), u.posToVal(u.select.left + u.select.width, 'x'));
          u.setSelect({left: 0, top: 0, width: 0, height: 0}, false);
        }],
        setCursor: [u => { if (u.cursor.idx !== cursorIdx) { cursorIdx = u.cursor.idx; channelList(); } }],
        draw: [marks],
      },
    }, [[], ...chosen.map(() => [])], area);
    new ResizeObserver(() => plot?.setSize({width: Math.max(240, area.clientWidth), height: Math.max(120, area.clientHeight)})).observe(area);
    fetchRange();
  }
  // Bookmarks (from the log) and the drive's alerts and bookmarks, as lines across the graph.
  function marks(u) {
    const all = [...(info?.markers || []).map(m => ({t: m.t, text: m.text, kind: 'bookmark'})), ...(info?.events || []).map(e => ({t: e.t, text: e.label, kind: e.kind}))];
    const ctx = u.ctx, top = u.bbox.top, height = u.bbox.height;
    ctx.save();
    for (const mark of all) {
      if (mark.t < u.scales.x.min || mark.t > u.scales.x.max) continue;
      const x = Math.round(u.valToPos(mark.t, 'x', true));
      ctx.strokeStyle = mark.kind === 'alert' ? '#ff6b6b' : '#ffd166'; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + height); ctx.stroke();
      ctx.setLineDash([]); ctx.fillStyle = ctx.strokeStyle; ctx.font = `${13 * devicePixelRatio}px "DejaVu Sans", sans-serif`; ctx.fillText(mark.text, x + 4, top + 14 * devicePixelRatio);
    }
    ctx.restore();
  }
  // Every channel in the log: the ones on the graph first, with their values; the rest by group.
  function channelList() {
    const box = host.querySelector('#lv-channels');
    if (!box || !info) return;
    const at = cursorIdx == null || !data ? null : data.t[cursorIdx];
    host.querySelector('#lv-at').textContent = at == null ? 'At cursor' : `At ${clock(at)}`;
    const matches = c => !find || `${c.name} ${c.units} ${c.category}`.toLowerCase().includes(find);
    const row = c => {
      const on = chosen.includes(c.name), stat = data?.stats?.[c.name];
      const button = el('button', undefined, 'lv-channel'); button.type = 'button'; button.dataset.channel = c.name;
      button.setAttribute('aria-pressed', String(on)); button.title = on ? `Take ${c.name} off the graph` : `Put ${c.name} on the graph`;
      const name = el('span', undefined, 'lv-name'), swatch = el('i', undefined, 'lv-swatch');
      if (on) swatch.style.background = color(c.name);
      name.append(swatch, el('span', c.name), el('small', c.units ? ` ${c.units}` : ''));
      const value = cursorIdx == null ? null : data?.series?.[c.name]?.[cursorIdx];
      button.append(name, ...(on ? [el('b', cursorIdx == null ? '—' : shown(value, c.name)), el('span', shown(stat?.min, c.name)), el('span', shown(stat?.avg, c.name)), el('span', shown(stat?.max, c.name))] : []));
      button.onclick = () => toggle(c.name);
      return button;
    };
    const rows = chosen.map(channel).filter(Boolean).filter(matches).map(row);
    const groups = {};
    for (const c of info.channels) if (!chosen.includes(c.name) && matches(c)) (groups[c.category || 'Other'] ??= []).push(c);
    for (const [group, list] of Object.entries(groups).sort()) rows.push(el('h4', group, 'lv-group'), ...list.map(row));
    if (!rows.length) rows.push(el('p', `No channel matches "${find}".`, 'control-note'));
    const focused = document.activeElement?.dataset?.channel, scroll = box.scrollTop;
    box.replaceChildren(...rows);
    box.scrollTop = scroll;
    if (focused) box.querySelector(`[data-channel="${CSS.escape(focused)}"]`)?.focus();
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
  async function fetchRange() {
    if (!info || !plot) return;
    const ticket = ++loading;
    host.querySelector('#lv-range').textContent = `${clock(view.start)} – ${clock(view.end)} of ${clock(info.duration_s)}`;
    if (!chosen.length) { data = null; channelList(); note('Choose channels from the list to draw them.'); return; }
    let got;
    try {
      got = await source.series(info.name, chosen, view.start, view.end, Math.min(4000, Math.round(host.clientWidth * 1.5) || 1500));
    } catch (error) { note(`The readings could not be read: ${error.message}`); return; }
    if (ticket !== loading || !plot) return;          // A newer range was asked for meanwhile
    data = got;
    plot.setData([data.t, ...chosen.map(n => data.series[n] || [])], false);
    plot.setScale('x', {min: view.start, max: view.end});
    cursorIdx = null;
    channelList();
    note(`${info.recording ? 'Still recording: ‹ Logs and open it again for the newest. ' : ''}${data.thinned ? 'Zoomed out: each point is the lowest and highest of its stretch, so no peak is lost. ' : ''}Drag across the graph to zoom in.`);
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
  window.FrogdashLogView = {open: () => safeLoad(), openLog: name => reporting(openLog)(name), back, toggle, zoom, move,
    get info() { return info; }, get view() { return view; }, get channels() { return chosen; }, get logs() { return logs; }};
  // It starts the moment its panel is on the screen, however it got there: the tab pressed,
  // the workspace opened again on this tab, or this file arriving after the tab was opened.
  new ResizeObserver(() => { if (!built && host.offsetWidth > 0) safeLoad(); }).observe(host);
  if (!built && host.offsetWidth > 0) safeLoad();
})();
