/* Shared offline-capable drive review, used by the dash and authenticated Wi-Fi page. */
(() => {
  'use strict';
  const ns = 'http://www.w3.org/2000/svg';
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };
  const value = (v, digits = 1) => Number.isFinite(v) ? v.toFixed(digits) : '—';
  const METRICS = {
    'engine.rpm': ['RPM', '', 1], 'engine.boost_kpa': ['Boost', 'psi', .145037738],
    'engine.afr': ['AFR', '', 1], 'meth.duty_pct': ['Injection duty', '%', 1],
    'engine.fuel_pressure_psi': ['Fuel pressure', 'psi', 1], 'engine.oil_pressure_psi': ['Oil pressure', 'psi', 1],
    'engine.coolant_c': ['Coolant', '°F', 1.8, 32], 'engine.iat_c': ['Intake air', '°F', 1.8, 32],
    'knock.energy': ['Knock energy', '', 1], 'vehicle.speed_kph': ['Speed', 'MPH', 1 / 1.609344]
  };
  class DriveReview {
    constructor(host, source) {
      this.host = host; this.source = source; this.data = null; this.cursor = 0; this.window = 'all'; this.loading = false;
      host.classList.add('review');
      this.toolbar = node('div', undefined, 'review-toolbar');
      this.select = node('select'); this.select.setAttribute('aria-label', 'Recorded drive');
      this.refresh = node('button', 'Refresh drives'); this.refresh.type = 'button';
      this.export = node('button', 'Export review'); this.export.type = 'button'; this.export.disabled = true;
      this.toolbar.append(this.select, this.refresh, this.export);
      this.message = node('p', '', 'review-message'); this.message.setAttribute('role', 'status');
      this.stats = node('div', undefined, 'review-stats');
      const body = node('div', undefined, 'review-body');
      const sidebar = node('aside', undefined, 'review-sidebar');
      sidebar.append(node('h3', 'Bookmarks & faults'));
      this.events = node('div', undefined, 'review-events');
      this.eventDetail = node('p', '', 'review-event-detail');
      this.races = node('p', '', 'review-races');
      sidebar.append(this.events, this.eventDetail, this.races);
      const plots = node('div', undefined, 'review-plots');
      const options = node('div', undefined, 'review-options');
      this.metric = node('select'); this.metric.setAttribute('aria-label', 'Fourth graph channel');
      for (const [key, [label]] of Object.entries(METRICS)) { const o = node('option', label); o.value = key; this.metric.append(o); }
      this.metric.value = 'meth.duty_pct';
      this.zoom = node('select'); this.zoom.setAttribute('aria-label', 'Graph time window');
      for (const [key, text] of [['all', 'Whole drive'], ['event', '±15 s around selection']]) { const o = node('option', text); o.value = key; this.zoom.append(o); }
      options.append(this.metric, this.zoom);
      this.svg = document.createElementNS(ns, 'svg'); this.svg.setAttribute('viewBox', '0 0 800 288'); this.svg.setAttribute('role', 'img'); this.svg.setAttribute('aria-label', 'Synchronized RPM, boost, AFR and selected channel graphs');
      this.slider = node('input'); this.slider.type = 'range'; this.slider.min = 0; this.slider.max = 1; this.slider.step = .1; this.slider.value = 0; this.slider.setAttribute('aria-label', 'Review time');
      this.readout = node('p', '', 'review-readout');
      plots.append(options, this.svg, this.slider, this.readout); body.append(sidebar, plots);
      host.append(this.toolbar, this.message, this.stats, body);
      this.refresh.onclick = () => this.load();
      this.select.onchange = () => this.open(this.select.value);
      this.metric.onchange = this.zoom.onchange = () => this.draw();
      this.slider.oninput = () => { this.cursor = Number(this.slider.value); this.draw(); };
      this.export.onclick = () => {
        if (!this.data) return;
        const url = URL.createObjectURL(new Blob([JSON.stringify(this.data)], {type: 'application/json'}));
        const link = node('a'); link.href = url; link.download = this.data.name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
      this.observer = new ResizeObserver(() => { if (this.data && host.clientWidth) this.draw(); });
      this.observer.observe(host);
    }
    async load() {
      if (this.loading) return;
      this.loading = true; this.refresh.disabled = true;
      try {
        const {drives} = await this.source.list();
        const previous = this.select.value;
        this.select.replaceChildren(...drives.map(d => { const o = node('option', `${new Date(d.started_ms).toLocaleString()} · ${d.status} · ${d.mode === 'demo' ? 'SIMULATED' : d.mode}`); o.value = d.name; return o; }));
        if (drives.some(d => d.name === previous)) this.select.value = previous;
        if (drives.length) await this.open(this.select.value);
        else { this.data = null; this.export.disabled = true; this.stats.replaceChildren(); this.events.replaceChildren(); this.svg.replaceChildren(); this.readout.textContent = this.eventDetail.textContent = this.races.textContent = ''; this.message.textContent = 'No drives yet. Reviews start with engine activity, movement, or a bookmark.'; }
      } catch (error) { this.message.textContent = error.message; }
      finally { this.loading = false; this.refresh.disabled = false; }
    }
    async open(name) {
      this.export.disabled = true;
      const request = this.request = (this.request || 0) + 1;
      try {
        const data = await this.source.read(name);
        if (request !== this.request) return;
        this.data = data; this.cursor = 0; this.slider.max = Math.max(1, data.duration_s); this.slider.value = 0;
        this.message.textContent = `${data.status === 'recording' ? 'Current drive · refresh for new samples' : data.status === 'interrupted' ? 'Recovered checkpoint · recording was interrupted' : 'Completed drive'} · ${Math.round(data.duration_s)} s · chart interval ≥${data.sample_seconds}s`;
        const s = data.stats || {};
        this.stats.replaceChildren(...[
          ['Peak boost', value(s['engine.boost_kpa'] == null ? null : s['engine.boost_kpa'] * .145037738) + ' psi'],
          ['Max coolant', value(s['engine.coolant_c'] == null ? null : s['engine.coolant_c'] * 1.8 + 32, 0) + ' °F'],
          ['Max intake air', value(s['engine.iat_c'] == null ? null : s['engine.iat_c'] * 1.8 + 32, 0) + ' °F'],
          ['Min oil ≥1500 RPM', value(s.oil_min_above_1500) + ' psi'],
          ['Max speed', value(s['vehicle.speed_kph'] == null ? null : s['vehicle.speed_kph'] / 1.609344) + ' MPH'], ['Events', `${data.event_count || 0}`]
        ].map(([label, v]) => { const card = node('div'); card.append(node('span', label), node('strong', v)); return card; }));
        this.events.replaceChildren(...(data.events || []).map(event => {
          const b = node('button', `${event.t.toFixed(1)}s · ${event.label}`); b.type = 'button'; b.dataset.kind = event.kind;
          b.onclick = () => {
            this.cursor = event.t; this.slider.value = event.t; this.zoom.value = 'event';
            const c = event.context || {};
            const capture = ['engine.rpm', 'engine.afr', 'ecu.afr_target', 'meth.state', 'meth.flow'].map(k => `${k}: ${c[k]?.quality === 'live' ? c[k].value : c[k]?.quality || 'unavailable'}`).join(' · ');
            this.eventDetail.textContent = `Marker #${event.id}${event.log ? ` · ${event.log.name} · MLG Time ≈${event.log.time_s.toFixed(2)}s` : ' · No active MLG file at this event'}. ${capture}`;
            this.draw();
          }; return b;
        }));
        if (!this.events.children.length) this.events.append(node('p', 'No bookmarks or faults.'));
        this.eventDetail.textContent = 'Select an event to inspect its capture and surrounding samples. MLG files are available in Saved logs.';
        const results = (data.race_results || []).filter(r => r.phase !== 'invalid');
        this.races.textContent = results.length ? 'Race results: ' + results.map(r => r.mode === 'laps' ? `Best lap ${value(r.best_lap, 2)}s` : `0–60 ${value(r.splits?.['0_60'], 2)}s / ¼ mile ${value(r.splits?.quarter, 2)}s`).join(' · ') : 'No completed race results in this drive.';
        this.export.disabled = false; this.draw();
      } catch (error) { if (request === this.request) this.message.textContent = error.message; }
    }
    draw() {
      if (!this.data) return;
      const d = this.data, keys = ['engine.rpm', 'engine.boost_kpa', 'engine.afr', this.metric.value];
      const start = this.zoom.value === 'event' ? Math.max(0, this.cursor - 15) : 0;
      const end = Math.max(start + .1, this.zoom.value === 'event' ? Math.min(d.duration_s, this.cursor + 15) : d.duration_s);
      const points = d.points.filter(p => p[0] >= start && p[0] <= end);
      const width = Math.max(280, this.svg.clientWidth || 800), height = Math.max(180, this.svg.clientHeight || 288), right = width - 15, left = 125;
      this.svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      this.svg.replaceChildren();
      const add = (tag, attrs, text) => { const el = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); if (text !== undefined) el.textContent = text; this.svg.append(el); };
      const x = t => left + (t - start) / (end - start) * (right - left);
      let nearest = null;
      for (const point of d.points) if (!nearest || Math.abs(point[0] - this.cursor) < Math.abs(nearest[0] - this.cursor)) nearest = point;
      if (nearest && Math.abs(nearest[0] - this.cursor) > Math.max(1, d.sample_seconds * 1.5)) nearest = null;
      const readouts = [];
      keys.forEach((key, row) => {
        const [label, unit, factor, offset = 0] = METRICS[key], index = d.channels.indexOf(key) + 1, band = (height - 20) / 4, top = row * band + 2;
        const samples = points.map(p => index > 0 ? p[index] : null).filter(Number.isFinite);
        let lo = samples.length ? Math.min(...samples) : 0, hi = samples.length ? Math.max(...samples) : 1;
        if (key === 'engine.afr') { lo = Math.min(lo, 10); hi = Math.max(hi, 18); }
        if (hi - lo < 1) hi = lo + 1;
        const y = n => top + band - 8 - (n - lo) / (hi - lo) * (band - 15);
        add('line', {x1: left, x2: right, y1: top + band - 6, y2: top + band - 6, class: 'review-grid'});
        add('text', {x: 4, y: top + 14}, label);
        add('text', {x: 4, y: top + 28, class: 'review-scale'}, `${value(lo * factor + offset)}–${value(hi * factor + offset)} ${unit}`);
        const path = column => {
          let result = '', pen = false, previous = null;
          for (const p of points) {
            const v = column > 0 ? p[column] : null;
            if (!Number.isFinite(v)) { pen = false; continue; }
            if (previous !== null && p[0] - previous > d.sample_seconds * 2.5) pen = false;
            result += `${pen ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(v).toFixed(1)} `; pen = true; previous = p[0];
          } return result;
        };
        add('path', {d: path(index), class: 'review-trace'});
        if (key === 'engine.afr') add('path', {d: path(d.channels.indexOf('ecu.afr_target') + 1), class: 'review-target'});
        const reading = nearest && index > 0 && Number.isFinite(nearest[index]) ? nearest[index] * factor + offset : null;
        readouts.push(`${label} ${value(reading, key === 'engine.rpm' ? 0 : 1)} ${unit}`);
      });
      for (const event of d.events || []) if (event.t >= start && event.t <= end) add('line', {x1: x(event.t), x2: x(event.t), y1: 0, y2: height - 23, class: 'review-event-line'});
      if (this.cursor >= start && this.cursor <= end) add('line', {x1: x(this.cursor), x2: x(this.cursor), y1: 0, y2: height - 23, class: 'review-cursor'});
      add('text', {x: left, y: height - 4, class: 'review-scale'}, `${start.toFixed(1)}s`);
      add('text', {x: right, y: height - 4, 'text-anchor': 'end', class: 'review-scale'}, `${end.toFixed(1)}s`);
      this.readout.textContent = `${this.cursor.toFixed(1)}s · ${readouts.join(' · ')} · dashed AFR = target`;
    }
  }
  window.FrogdashReview = DriveReview;
})();
