/* Live graphs: the engine over the last minutes, drawn with uPlot (uPlot.iife.min.js,
   MIT, github.com/leeoniya/uPlot). Every state update is sampled four times a second
   from the moment the page loads, so the history is there when the screen opens: up to
   15 minutes, kept in the browser only. Hold freezes the view to read a pull while the
   recording carries on. Opened from the app menu. */
(() => {
  'use strict';
  const u = window.FrogdashUnits;
  const KEEP_S = 15 * 60, EVERY_MS = 250, DRAW_MS = 500, WINDOWS = [60, 300, 900];
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#a6b6c0';
  // Each chart: title, then its lines: [label, signal names (the first live one), convert, digits, colour, axis].
  const pressureUnit = () => u.metric ? 'kPa' : 'psi', tempUnit = () => u.metric ? '°C' : '°F';
  const CHARTS = [
    ['Boost and water/meth', [
      [() => `Boost ${pressureUnit()}`, ['engine.boost_kpa'], v => u.boost(v), 1, '#8befc4', 'l'],
      [() => 'Water/meth duty %', ['meth.duty_pct'], v => v, 0, '#8fcfff', 'r']]],
    ['Engine speed', [
      [() => 'RPM', ['engine.rpm'], v => v, 0, '#ffd080', 'l'],
      [() => `Speed ${u.speedUnit}`, ['vehicle.speed_kph'], v => u.distance(v), 0, '#8befc4', 'r']]],
    ['Mixture and timing', [
      [() => 'AFR', ['engine.afr'], v => v, 1, '#ff9f6b', 'l'],
      [() => 'Timing °', ['ecu.spark_deg'], v => v, 1, '#c9a2ff', 'r']]],
    ['Knock', [
      [() => 'Knock energy', ['knock.energy'], v => v, 0, '#ff7979', 'l'],
      [() => 'Threshold', ['knock.threshold'], v => v, 0, '#a6b6c0', 'l', [6, 6]]]],
    ['Temperatures', [
      [() => `Coolant ${tempUnit()}`, ['engine.coolant_c'], v => u.temperature(v), 0, '#ff9f6b', 'l'],
      [() => `Intake air ${tempUnit()}`, ['ecu.iat_c', 'engine.iat_c'], v => u.temperature(v), 0, '#8fcfff', 'l']]],
    ['Oil and fuel pressure', [
      [() => `Oil ${pressureUnit()}`, ['engine.oil_pressure_psi'], v => u.pressure(v), 0, '#ffd080', 'l'],
      [() => `Fuel ${pressureUnit()}`, ['engine.fuel_pressure_psi'], v => u.pressure(v), 0, '#8befc4', 'l']]],
  ];
  const LINES = CHARTS.flatMap(([, lines]) => lines);
  const times = [], columns = LINES.map(() => []);
  let last = 0, windowS = 300, held = null, plots = [], drawn = 0, timer = null, connectedNow = false;

  const dialog = document.createElement('dialog');
  dialog.id = 'graphs-dialog'; dialog.className = 'workspace-dialog graphs-dialog'; dialog.setAttribute('aria-labelledby', 'graphs-title');
  dialog.innerHTML = '<header class="dialog-header"><div><span class="eyebrow">LIVE GRAPHS</span><h2 id="graphs-title">The engine over time</h2>' +
    '<p id="graphs-note">Recorded while the dash is on, up to 15 minutes. Kept on this screen only.</p></div>' +
    '<div class="graphs-tools"><div class="graphs-windows" role="group" aria-label="Time shown">' +
    WINDOWS.map(s => `<button type="button" data-window="${s}">${s / 60} min</button>`).join('') + '</div>' +
    '<button type="button" id="graphs-hold" aria-pressed="false">Hold</button>' +
    '<button type="button" class="close-button" id="graphs-close">Close ×</button></div></header>' +
    '<div class="graphs-grid" id="graphs-grid" data-wheel-scroll tabindex="0" aria-label="Graphs"></div>';
  document.body.append(dialog);
  const $ = id => document.getElementById(id);

  function reading(values, names) {
    for (const name of names) {
      const v = values?.[name];
      if (v && v.quality === 'live' && Number.isFinite(v.value)) return v.value;
    }
    return null;
  }
  function sample(snapshot, connected) {
    connectedNow = connected;
    const now = Date.now();
    if (now - last < EVERY_MS) return;
    last = now;
    const values = connected ? snapshot.values : null;
    times.push(now / 1000);
    LINES.forEach(([, names, convert], i) => {
      const raw = reading(values, names);
      columns[i].push(raw === null ? null : convert(raw));
    });
    const over = times.length - KEEP_S * 1000 / EVERY_MS;
    if (over > 40) {               // Trimmed in steps: one shift of thousands of points is cheaper than one per sample
      times.splice(0, over);
      columns.forEach(c => c.splice(0, over));
    }
    if (dialog.open && !held && now - drawn >= DRAW_MS) draw();
  }

  function shown() {
    const end = held ?? times.at(-1) ?? Date.now() / 1000, start = end - windowS;
    let from = 0;
    while (from < times.length && times[from] < start) from += 1;
    let to = times.length;
    while (to > from && times[to - 1] > end) to -= 1;
    return [from, to, start, end];
  }
  function draw() {
    drawn = Date.now();
    const [from, to, start, end] = shown();
    let column = 0;
    CHARTS.forEach(([, lines], index) => {
      const data = [times.slice(from, to), ...lines.map(() => columns[column++].slice(from, to))];
      const plot = plots[index];
      if (!plot) return;
      plot.batch(() => {
        plot.setData(data);
        plot.setScale('x', {min: start, max: end});
      });
      newest(plot);
    });
    const empty = to - from < 2;
    $('graphs-note').textContent = held ? `Held at ${new Date(held * 1000).toLocaleTimeString()}: still recording · press Hold again to follow`
      : empty ? (connectedNow ? 'Collecting: the lines fill in as readings arrive' : 'Not connected to the dash')
        : 'Recorded while the dash is on, up to 15 minutes. Kept on this screen only.';
  }

  // The chart fills its card, leaving room for uPlot's legend under it.
  function size(plot, box) {
    const legend = plot.root.querySelector('.u-legend')?.offsetHeight || 0;
    plot.setSize({width: Math.max(240, Math.floor(box.clientWidth) - 2), height: Math.max(120, Math.floor(box.clientHeight) - legend - 4)});
  }
  // The legend shows the newest values, or the ones under the pointer while it is over a chart.
  function newest(plot) {
    if (plot.over.matches(':hover')) return;
    const count = plot.data[0].length;
    plot.setLegend({idx: count ? count - 1 : null});
  }
  // One line of time under each chart: hours and minutes, with seconds when the ticks are closer than a minute.
  const clock = (self, ticks) => {
    const seconds = ticks.length > 1 && ticks[1] - ticks[0] < 60;
    return ticks.map(t => new Date(t * 1000).toLocaleTimeString([], seconds
      ? {hour: 'numeric', minute: '2-digit', second: '2-digit'} : {hour: 'numeric', minute: '2-digit'}));
  };
  function build() {
    if (!window.uPlot) {
      $('graphs-grid').replaceChildren(Object.assign(document.createElement('p'), {className: 'graphs-missing', textContent: 'The graph library did not load'}));
      return;
    }
    const muted = css('--muted'), line = css('--line');
    const axis = (scale, side) => ({scale, side, stroke: muted, size: 52, font: '13px "DejaVu Sans", sans-serif',
      grid: {stroke: line, width: 1, show: side === 3}, ticks: {stroke: line, width: 1}});
    plots = CHARTS.map(([title, lines]) => {
      const card = document.createElement('section');
      card.className = 'graphs-card';
      card.innerHTML = '<h3></h3><div class="graphs-plot"></div>';
      card.querySelector('h3').textContent = title;
      $('graphs-grid').append(card);
      const box = card.querySelector('.graphs-plot');
      const right = lines.some(l => l[5] === 'r');
      const plot = new window.uPlot({
        width: 600, height: 200, pxAlign: 0,
        scales: {x: {time: true}, l: {auto: true}, r: {auto: true}},
        axes: [{stroke: muted, font: '13px "DejaVu Sans", sans-serif', grid: {stroke: line, width: 1}, ticks: {stroke: line, width: 1},
          values: clock, space: 90, size: 34},
          axis('l', 3), ...(right ? [axis('r', 1)] : [])],
        series: [{value: (self, v) => v == null ? '—' : new Date(v * 1000).toLocaleTimeString()},
          ...lines.map(([label, , , digits, stroke, scale, dash]) => ({
            label: label(), scale, stroke, width: 2, dash, spanGaps: false, points: {show: false},
            value: (self, v) => v == null ? '—' : v.toFixed(digits)}))],
        cursor: {drag: {x: false, y: false}, points: {size: 7}},
        legend: {live: true},
      }, [[], ...lines.map(() => [])], box);
      new ResizeObserver(() => size(plot, box)).observe(box);
      return plot;
    });
  }

  function setWindow(seconds) {
    windowS = seconds;
    for (const button of dialog.querySelectorAll('[data-window]')) button.setAttribute('aria-pressed', String(Number(button.dataset.window) === seconds));
    draw();
  }
  function open() {
    if (!plots.length) build();
    if (!dialog.open) dialog.showModal();
    // Labels follow the unit setting (it may have changed since they were made).
    CHARTS.forEach(([, lines], index) => lines.forEach(([label], i) => {
      const plot = plots[index];
      if (plot) plot.series[i + 1].label = label();
      const shownLabel = plot?.root.querySelectorAll('.u-series .u-label')[i + 1];
      if (shownLabel) shownLabel.textContent = label();
    }));
    setWindow(windowS);
    clearInterval(timer);
    timer = setInterval(() => { if (dialog.open && !held) draw(); }, 1000);   // Moves on even when no update arrives
  }
  dialog.addEventListener('close', () => clearInterval(timer));
  dialog.querySelector('.graphs-windows').addEventListener('click', event => {
    const button = event.target.closest('[data-window]');
    if (button) setWindow(Number(button.dataset.window));
  });
  $('graphs-hold').onclick = () => {
    held = held ? null : times.at(-1) ?? Date.now() / 1000;
    $('graphs-hold').setAttribute('aria-pressed', String(!!held));
    $('graphs-hold').textContent = held ? 'Follow' : 'Hold';
    draw();
  };
  $('graphs-close').onclick = () => dialog.close();
  window.addEventListener('frogdash-state', ({detail}) => sample(detail.snapshot, detail.connected));
  window.FrogdashGraphs = {open, get points() { return times.length; }, latest: () => LINES.map(([label], i) => [label(), columns[i].at(-1)])};
})();
