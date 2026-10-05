/* Offline moving map. Draws streets from a compact OpenStreetMap extract
   (tools/make_map.py) on a canvas, centred on the GPS position. No internet, no tiles. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const dialog = $('map-dialog'), canvas = $('map-canvas'), ctx = canvas.getContext('2d');
  const KEY = 'frogdash.map.v1';
  const ZOOMS = [150, 300, 600, 1200, 2500, 5000, 10000]; // metres across half the screen width
  // class: [colour, width at close zoom, hidden beyond this half-width in metres]
  const STYLE = [['#ffb347', 7, Infinity], ['#ffe08a', 5, Infinity], ['#f1f5f4', 4, 6000], ['#9fb0bb', 2.5, 3000], ['#5d6f7a', 1.5, 1300],
                 ['#3b82c4', 5, Infinity], ['#8a6d5a', 1.5, 6000]];
  let prefs = {zoom: 2, heading: true};
  try { const saved = JSON.parse(localStorage.getItem(KEY)); if (saved) prefs = {zoom: Math.max(0, Math.min(ZOOMS.length - 1, saved.zoom | 0)), heading: saved.heading !== false}; } catch { /* Defaults. */ }
  let map = null, grid = null, error = '', latest = {}, fix = null, lastFix = null, track = 0, demoAngle = 0, timer = null;
  const CELL = 1000; // grid cell in map units (0.01 degree)

  async function load() {
    try {
      const maps = await (await fetch('maps/index.json', {cache: 'no-cache'})).json();
      const data = await (await fetch(`maps/${maps[0].name}.json`, {cache: 'no-cache'})).json();
      const [south, west] = data.bounds, baseLat = Math.round(south * data.scale), baseLon = Math.round(west * data.scale);
      grid = new Map();
      data.ways = data.ways.map(([kind, name, deltas], index) => {
        const points = new Int32Array(deltas.length);
        let lat = baseLat, lon = baseLon, last = '';
        for (let i = 0; i < deltas.length; i += 2) {
          lat += deltas[i]; lon += deltas[i + 1]; points[i] = lat; points[i + 1] = lon;
          const cell = `${Math.floor(lat / CELL)},${Math.floor(lon / CELL)}`;
          if (cell !== last) { last = cell; (grid.get(cell) || grid.set(cell, new Set()).get(cell)).add(index); }
        }
        return {kind, name: data.names[name], points};
      });
      map = data;
      $('map-credit').textContent = `${data.title} · ${data.attribution}`;
    } catch { error = 'Map data unavailable'; }
    draw();
  }
  const live = key => { const v = latest.values?.[key]; return v && v.quality === 'live' ? v.value : null; };
  function position() {
    if (latest.mode === 'demo' || location.protocol === 'file:') { // Preview: circle downtown.
      demoAngle += .01;
      return {lat: 39.0672 + Math.sin(demoAngle) * .006, lon: -108.5645 + Math.cos(demoAngle) * .009, track: (90 - demoAngle * 180 / Math.PI + 360 * 10) % 360, demo: true};
    }
    // Fused position (hardware/frogdash/nav.py): GPS, or wheel-speed dead reckoning, or last known.
    const value = key => latest.values?.[key]?.value ?? null;
    const lat = value('nav.latitude'), lon = value('nav.longitude'), source = value('nav.source');
    if (lat === null || lon === null || !source || source === 'none') return null;
    track = value('nav.track_deg') ?? track;
    return {lat, lon, track, source, accuracy: value('nav.accuracy_m')};
  }
  function draw() {
    const w = canvas.width = canvas.clientWidth, h = canvas.height = canvas.clientHeight;
    ctx.fillStyle = '#0b1014'; ctx.fillRect(0, 0, w, h);
    if (!map) { ctx.fillStyle = '#9fb0bb'; ctx.font = '20px system-ui'; ctx.textAlign = 'center'; ctx.fillText(error || 'Loading map…', w / 2, h / 2); return; }
    fix = position();
    if (fix) lastFix = fix;
    const [south, west, north, east] = map.bounds;
    const centre = lastFix || {lat: (south + north) / 2, lon: (west + east) / 2, track: 0};
    const half = ZOOMS[prefs.zoom], cosLat = Math.cos(centre.lat * Math.PI / 180);
    const mPerUnit = 111320 / map.scale, pxPerM = (w / 2) / half;
    const cLat = centre.lat * map.scale, cLon = centre.lon * map.scale;
    const rotation = prefs.heading ? -centre.track * Math.PI / 180 : 0, sin = Math.sin(rotation), cos = Math.cos(rotation);
    const originY = prefs.heading ? h * .68 : h / 2; // Heading-up shows more road ahead.
    const project = (lat, lon) => {
      const x = (lon - cLon) * mPerUnit * cosLat * pxPerM, y = -(lat - cLat) * mPerUnit * pxPerM;
      return [w / 2 + x * cos - y * sin, originY + x * sin + y * cos];
    };
    // Ways from grid cells within reach of the screen.
    const reachM = Math.hypot(w, h) / pxPerM, dLat = reachM / mPerUnit, dLon = dLat / cosLat;
    const wanted = new Set();
    for (let a = Math.floor((cLat - dLat) / CELL); a <= Math.floor((cLat + dLat) / CELL); a++)
      for (let b = Math.floor((cLon - dLon) / CELL); b <= Math.floor((cLon + dLon) / CELL); b++)
        for (const index of grid.get(`${a},${b}`) || []) wanted.add(index);
    const visible = [...wanted].sort((a, b) => a - b).map(i => map.ways[i]).filter(way => half <= STYLE[way.kind][2]);
    ctx.lineCap = ctx.lineJoin = 'round';
    const widthScale = Math.max(.6, Math.min(2.2, 600 / half));
    for (const way of visible) {
      const [colour, width] = STYLE[way.kind];
      ctx.beginPath();
      for (let i = 0; i < way.points.length; i += 2) {
        const [x, y] = project(way.points[i], way.points[i + 1]);
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.strokeStyle = colour; ctx.lineWidth = width * widthScale; ctx.stroke();
    }
    // Street names at close zooms, one label per name, kept upright.
    if (half <= 1300) {
      const labelled = new Set();
      ctx.font = '600 15px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (const way of visible) {
        if (!way.name || way.kind > 4 || labelled.has(way.name) || (way.kind === 4 && half > 400)) continue;
        const mid = (way.points.length >> 2) << 1, a = project(way.points[mid ? mid - 2 : 0], way.points[mid ? mid - 1 : 1]), b = project(way.points[mid ? mid : 2], way.points[mid ? mid + 1 : 3]);
        const x = (a[0] + b[0]) / 2, y = (a[1] + b[1]) / 2;
        if (x < 60 || x > w - 60 || y < 20 || y > h - 20 || Math.hypot(b[0] - a[0], b[1] - a[1]) < 4) continue;
        labelled.add(way.name);
        let angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
        if (angle > Math.PI / 2 || angle < -Math.PI / 2) angle += Math.PI;
        ctx.save(); ctx.translate(x, y); ctx.rotate(angle);
        ctx.lineWidth = 4; ctx.strokeStyle = '#0b1014'; ctx.strokeText(way.name, 0, 0);
        ctx.fillStyle = '#e8eef2'; ctx.fillText(way.name, 0, 0); ctx.restore();
      }
    }
    // The car: an arrow at the position, pointing along the heading.
    const [px, py] = project(cLat, cLon);
    ctx.save(); ctx.translate(px, py); ctx.rotate(prefs.heading ? 0 : centre.track * Math.PI / 180);
    ctx.beginPath(); ctx.moveTo(0, -18); ctx.lineTo(12, 14); ctx.lineTo(0, 7); ctx.lineTo(-12, 14); ctx.closePath();
    const estimated = fix?.source === 'estimated', remembered = !fix || fix.source === 'last-known';
    ctx.fillStyle = remembered ? '#7b8791' : estimated ? '#ffb347' : '#1cf29a'; ctx.strokeStyle = '#0b1014'; ctx.lineWidth = 3; ctx.stroke(); ctx.fill(); ctx.restore();
    if (estimated && fix.accuracy > 12) { // Uncertainty grows with distance since the last fix.
      ctx.beginPath(); ctx.arc(px, py, Math.min(fix.accuracy * pxPerM, Math.min(w, h) / 2), 0, Math.PI * 2);
      ctx.strokeStyle = '#ffb34799'; ctx.lineWidth = 2; ctx.setLineDash([6, 6]); ctx.stroke(); ctx.setLineDash([]);
    }
    // Scale bar.
    const barM = [50, 100, 200, 500, 1000, 2000, 5000].find(m => m * pxPerM >= 90) || 5000;
    ctx.fillStyle = '#e8eef2'; ctx.fillRect(24, h - 28, barM * pxPerM, 4);
    ctx.font = '14px system-ui'; ctx.textAlign = 'left'; ctx.fillText(barM >= 1000 ? `${barM / 1000} km · ${(barM / 1609.34).toFixed(1)} mi` : `${barM} m · ${Math.round(barM * 3.281)} ft`, 24, h - 40);
    // Readouts.
    const inside = centre.lat >= south && centre.lat <= north && centre.lon >= west && centre.lon <= east;
    const road = nearestRoad(centre, cLat, cLon, cosLat, mPerUnit);
    const speed = live('vehicle.speed_kph'), units = window.FrogdashUnits;
    $('map-road').textContent = road || (inside ? '—' : 'Outside the map area');
    $('map-speed').textContent = speed === null ? '—' : Math.round(units ? units.distance(speed) : speed * .621371);
    $('map-speed-unit').textContent = units ? units.speedUnit : 'MPH';
    $('map-status').textContent = fix?.demo ? 'Preview position (no GPS)'
      : fix?.source === 'gps' ? `GPS fix · ${live('gps.satellites') ?? '—'} satellites`
      : fix?.source === 'estimated' ? `GPS lost: estimating position${fix.accuracy ? ` · within about ${Math.round(fix.accuracy)} m` : ''}`
      : fix?.source === 'last-known' ? 'No GPS fix yet: last known position'
      : lastFix ? 'GPS lost: showing the last position' : 'No GPS fix: showing the map centre';
    $('map-heading').setAttribute('aria-pressed', String(prefs.heading));
    $('map-heading').textContent = prefs.heading ? 'HEADING UP' : 'NORTH UP';
    $('map-zoom-level').textContent = half >= 1000 ? `${half / 1000} km` : `${half} m`;
  }
  function nearestRoad(centre, cLat, cLon, cosLat, mPerUnit) {
    let best = null, bestDistance = 40; // metres
    for (const index of grid.get(`${Math.floor(cLat / CELL)},${Math.floor(cLon / CELL)}`) || []) {
      const way = map.ways[index];
      if (!way.name || way.kind > 4) continue;
      for (let i = 0; i + 3 < way.points.length; i += 2) {
        const ax = (way.points[i + 1] - cLon) * mPerUnit * cosLat, ay = (way.points[i] - cLat) * mPerUnit;
        const bx = (way.points[i + 3] - cLon) * mPerUnit * cosLat, by = (way.points[i + 2] - cLat) * mPerUnit;
        const dx = bx - ax, dy = by - ay, t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy || 1)));
        const distance = Math.hypot(ax + t * dx, ay + t * dy);
        if (distance < bestDistance) { bestDistance = distance; best = way.name; }
      }
    }
    return best;
  }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* Session only. */ } draw(); }
  $('map-zoom-in').onclick = () => { prefs.zoom = Math.max(0, prefs.zoom - 1); save(); };
  $('map-zoom-out').onclick = () => { prefs.zoom = Math.min(ZOOMS.length - 1, prefs.zoom + 1); save(); };
  $('map-heading').onclick = () => { prefs.heading = !prefs.heading; save(); };
  function open() {
    if (dialog.open) return;
    dialog.showModal();
    if (!map && !error) load(); else draw();
    clearInterval(timer); timer = setInterval(draw, 500);
  }
  function close() { clearInterval(timer); if (dialog.open) dialog.close(); }
  $('map-launch').onclick = open;
  $('map-close').onclick = close;
  dialog.addEventListener('close', () => clearInterval(timer));
  window.addEventListener('frogdash-state', event => { latest = event.detail.snapshot; });
  window.FrogdashMap = {open, close};
})();
