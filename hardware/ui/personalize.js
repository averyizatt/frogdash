/* Display preferences and the GPS race workspace. No vehicle actuator commands. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const looks = {
    original: {name: 'Frogdash', note: 'Signature mint · midnight', accent: '#8befc4', finish: 'midnight', surface: '#111a20', raised: '#18232b', line: '#2b3943'},
    glacier: {name: 'Glacier', note: 'Ice blue · alpine horizon', accent: '#8fcfff', finish: 'horizon', surface: '#111c29', raised: '#1b2c3c', line: '#34485c'},
    heritage: {name: 'Heritage', note: 'Warm amber · graphite', accent: '#ffc77d', finish: 'graphite', surface: '#211c17', raised: '#2c251e', line: '#4b4035'},
    afterhours: {name: 'After hours', note: 'Soft violet · dusk', accent: '#c6a6ff', finish: 'dusk', surface: '#1b1726', raised: '#292137', line: '#443853'},
    apex: {name: 'Apex', note: 'Platinum · carbon weave', accent: '#e3e9ee', finish: 'carbon', surface: '#191d22', raised: '#272c32', line: '#434a53'},
    expedition: {name: 'Expedition', note: 'Sage green · contours', accent: '#b9dfa2', finish: 'contour', surface: '#192018', raised: '#263024', line: '#3e4c39'},
    sprint: {name: 'GT Sprint', note: 'Acid yellow / precision instruments', accent: '#e3f58a', finish: 'pitlane', surface: '#141a13', raised: '#242c20', line: '#424d37', style: 'race', transparency: 15},
    endurance: {name: 'Endurance', note: 'Platinum / red pit-lane stripes', accent: '#e3e9ee', finish: 'apexline', surface: '#171b22', raised: '#262c35', line: '#424b58', style: 'race', transparency: 20},
    rally: {name: 'Rally Stage', note: 'Glacier cyan / technical grid', accent: '#85e6ee', finish: 'technical', surface: '#101e25', raised: '#1d3039', line: '#355361', style: 'race', transparency: 15},
    clubsport: {name: 'Club Sport', note: 'Hot amber / exposed carbon', accent: '#ffc48a', finish: 'carbon', surface: '#201b17', raised: '#31271e', line: '#504132', style: 'race', transparency: 10},
    obsidian: {name: 'Obsidian', note: 'Monochrome / brushed satin', accent: '#dce5ec', finish: 'satin', surface: '#171b21', raised: '#252b33', line: '#3d4854', style: 'touring', transparency: 25},
    executive: {name: 'Executive', note: 'Champagne / midnight blue', accent: '#e7d3a5', finish: 'horizon', surface: '#151d2a', raised: '#253145', line: '#42526a', style: 'touring', transparency: 20}
  };
  const finishes = {midnight: 'Midnight', graphite: 'Graphite', carbon: 'Carbon weave', glow: 'Accent glow', horizon: 'Horizon', grid: 'Blueprint', contour: 'Contours', dusk: 'Dusk', pitlane: 'Pit lane', apexline: 'Redline', technical: 'Telemetry', satin: 'Satin', image: 'Custom image'};
  const defaults = {look: 'original', accent: '#8befc4', finish: 'midnight', background: '', splash: 'off', splashImage: '', title: 'FROGDASH', duration: 2, transparency: 0};
  const key = 'frogdash.appearance.v1';
  const validImage = value => typeof value === 'string' && value.length < 1500000 && /^data:image\/(jpeg|png|webp);base64,[a-z0-9+/=]+$/i.test(value);
  let prefs = {...defaults}, splashTimer, splashPreview = false;
  try {
    const stored = JSON.parse(localStorage.getItem(key));
    if (stored && typeof stored === 'object') {
      if (/^#[0-9a-f]{6}$/i.test(stored.accent)) prefs.accent = stored.accent;
      if (Object.hasOwn(looks, stored.look)) prefs.look = stored.look;
      if (Object.hasOwn(finishes, stored.finish)) prefs.finish = stored.finish;
      if (['off', 'wordmark', 'image'].includes(stored.splash)) prefs.splash = stored.splash;
      if (validImage(stored.background)) prefs.background = stored.background;
      if (validImage(stored.splashImage)) prefs.splashImage = stored.splashImage;
      if (typeof stored.title === 'string') prefs.title = stored.title.slice(0, 32);
      if ([1, 2, 3, 5].includes(stored.duration)) prefs.duration = stored.duration;
      if (Number.isFinite(stored.transparency)) prefs.transparency = Math.max(0, Math.min(100, stored.transparency));
    }
  } catch { /* Unavailable storage falls back to a fully usable dash. */ }

  function appearanceMessage(message) {
    $('appearance-feedback').textContent = message;
    $('appearance-gallery-feedback').textContent = message;
  }
  function selectAppearanceTab(name) {
    for (const button of document.querySelectorAll('[data-appearance-tab]')) {
      const selected = button.dataset.appearanceTab === name;
      button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
      $(button.getAttribute('aria-controls')).hidden = !selected;
    }
  }
  const tabs = [...document.querySelectorAll('[data-appearance-tab]')];
  tabs.forEach((button, index) => {
    button.onclick = () => selectAppearanceTab(button.dataset.appearanceTab);
    button.onkeydown = event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
      next.click(); next.focus();
    };
  });
  for (const [id, look] of Object.entries(looks)) {
    const button = document.createElement('button'); button.type = 'button'; button.dataset.look = id;
    button.dataset.collection = look.style ? 'performance' : 'signature';
    button.dataset.instrumentStyle = look.style || 'classic';
    button.className = 'look-card'; button.setAttribute('aria-label', `Apply ${look.name} look`);
    button.style.setProperty('--accent', look.accent); button.style.setProperty('--surface', look.surface);
    // Static, local catalogue text only; uploaded artwork never enters markup.
    button.innerHTML = `<span class="look-art" data-scene="${look.finish}" aria-hidden="true"><span class="mini-gauge"></span><span class="mini-speed">76<small>MPH</small></span><span class="mini-bars"></span></span><span class="look-caption"><strong>${look.name}</strong><span class="look-check" aria-hidden="true">✓</span><small>${look.note}</small></span>`;
    button.onclick = () => { prefs.look = id; prefs.accent = look.accent; prefs.finish = look.finish; prefs.transparency = look.transparency || 0; applyAppearance(); };
    $('appearance-looks').append(button);
  }
  function collection(name) {
    for (const button of document.querySelectorAll('button[data-collection-filter]')) button.setAttribute('aria-pressed', String(button.dataset.collectionFilter === name));
    for (const card of document.querySelectorAll('.look-card')) card.hidden = card.dataset.collection !== name;
  }
  for (const button of document.querySelectorAll('button[data-collection-filter]')) button.onclick = () => collection(button.dataset.collectionFilter);
  collection(looks[prefs.look].style ? 'performance' : 'signature');
  $('appearance-finish').replaceChildren();
  for (const [id, name] of Object.entries(finishes)) {
    const option = document.createElement('option'); option.value = id; option.textContent = name; $('appearance-finish').append(option);
    if (id === 'image') continue;
    const button = document.createElement('button'); button.type = 'button'; button.dataset.background = id;
    button.innerHTML = `<span data-scene="${id}" aria-hidden="true"></span><strong>${name}</strong>`;
    button.onclick = () => { prefs.finish = id; applyAppearance(); };
    $('appearance-backgrounds').append(button);
  }

  function readableAccent(hex) {
    const rgb = hex.slice(1).match(/../g).map(v => parseInt(v, 16));
    const luminance = () => rgb.map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((n, v, i) => n + v * [.2126, .7152, .0722][i], 0);
    while (luminance() < .4) for (let i = 0; i < 3; i++) rgb[i] = Math.min(255, rgb[i] + 3);
    return '#' + rgb.map(v => v.toString(16).padStart(2, '0')).join('');
  }
  function applyAppearance(save = true) {
    prefs.accent = readableAccent(prefs.accent);
    const root = document.documentElement;
    const look = looks[prefs.look];
    root.style.setProperty('--accent', prefs.accent);
    for (const token of ['surface', 'raised', 'line']) root.style.setProperty(`--${token}`, look[token]);
    root.style.setProperty('--bg', prefs.finish === 'graphite' ? '#191d22' : '#090f13');
    root.dataset.instrumentStyle = look.style || 'classic';
    root.style.setProperty('--widget-fill', `${100 - prefs.transparency}%`);
    root.dataset.finish = prefs.finish;
    root.dataset.scene = prefs.finish;
    root.style.setProperty('--custom-background', prefs.background ? `url("${prefs.background}")` : 'none');
    $('appearance-transparency').value = prefs.transparency;
    $('appearance-transparency-value').textContent = `${prefs.transparency}%`;
    $('appearance-transparency').setAttribute('aria-valuetext', `${prefs.transparency}% transparent`);
    $('appearance-accent').value = prefs.accent;
    $('appearance-finish').value = prefs.finish;
    $('appearance-splash').value = prefs.splash;
    $('appearance-title-input').value = prefs.title;
    $('appearance-duration').value = prefs.duration;
    for (const button of document.querySelectorAll('[data-accent]')) button.setAttribute('aria-pressed', String(button.dataset.accent === prefs.accent));
    const exact = prefs.accent === look.accent && prefs.finish === look.finish && prefs.transparency === (look.transparency || 0);
    $('appearance-current').textContent = `${look.name}${exact ? '' : ' · customized'} / ${finishes[prefs.finish]}`;
    for (const button of document.querySelectorAll('button[data-look]')) button.setAttribute('aria-pressed', String(button.dataset.look === prefs.look && exact));
    for (const button of document.querySelectorAll('button[data-background]')) button.setAttribute('aria-pressed', String(button.dataset.background === prefs.finish));
    if (save) {
      try { localStorage.setItem(key, JSON.stringify(prefs)); appearanceMessage('Saved on this display. Night mode uses your Drive workspace colors and brightness.'); }
      catch { appearanceMessage('Applied for now, but browser storage is full or unavailable. Remove an image to save.'); }
    }
  }
  window.FrogdashAppearance = {readableAccent};
  function hideSplash() { clearTimeout(splashTimer); $('splash-dialog').close(); }
  function showSplash(preview = false) {
    if (prefs.splash === 'off') { $('appearance-feedback').textContent = 'Choose a splash style to preview it.'; return; }
    splashPreview = preview;
    const hasImage = prefs.splash === 'image' && !!prefs.splashImage;
    $('splash-image').hidden = !hasImage;
    if (hasImage) $('splash-image').src = prefs.splashImage;
    else $('splash-image').removeAttribute('src');
    document.querySelector('.splash-wordmark').hidden = hasImage;
    $('splash-title').textContent = prefs.title || 'FROGDASH';
    $('splash-dialog').showModal();
    clearTimeout(splashTimer);
    splashTimer = setTimeout(hideSplash, prefs.duration * 1000);
  }
  for (const name of ['appearance', 'race']) {
    $(`${name}-launch`).onclick = () => $(`${name}-dialog`).showModal();
    $(`${name}-close`).onclick = () => $(`${name}-dialog`).close();
  }
  $('splash-skip').onclick = hideSplash;
  $('splash-dialog').addEventListener('close', () => clearTimeout(splashTimer));
  $('appearance-preview').onclick = () => showSplash(true);
  for (const button of document.querySelectorAll('[data-accent]')) button.onclick = () => { prefs.accent = button.dataset.accent; applyAppearance(); };
  for (const [id, field] of [['accent', 'accent'], ['finish', 'finish'], ['splash', 'splash'], ['title-input', 'title'], ['duration', 'duration']]) {
    $(`appearance-${id}`).addEventListener('change', event => {
      prefs[field] = field === 'duration' ? Number(event.target.value) : event.target.value;
      applyAppearance();
    });
  }
  let imageBusy = false;
  async function uploadImage(input, field) {
    const file = input.files[0];
    if (!file || imageBusy) return;
    imageBusy = true;
    for (const el of document.querySelectorAll('#appearance-dialog input[type=file], #appearance-reset')) el.disabled = true;
    let url;
    try {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024) throw new Error('Choose a PNG, JPEG or WebP under 10 MB.');
      url = URL.createObjectURL(file);
      const img = new Image(); img.src = url; await img.decode();
      if (img.naturalWidth * img.naturalHeight > 40000000) throw new Error('Image is too large; use an image below 40 megapixels.');
      const ratio = Math.min(1, 1920 / img.naturalWidth, 720 / img.naturalHeight);
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(img.naturalWidth * ratio)); canvas.height = Math.max(1, Math.round(img.naturalHeight * ratio));
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#090f13'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      const data = canvas.toDataURL('image/jpeg', .82);
      if (!validImage(data)) throw new Error('Image is too detailed to save; try a smaller image.');
      prefs[field] = data;
      if (field === 'background') prefs.finish = 'image'; else prefs.splash = 'image';
      applyAppearance();
    } catch (error) { $('appearance-feedback').textContent = error.message || 'Could not read this image.'; }
    finally {
      if (url) URL.revokeObjectURL(url);
      input.value = ''; imageBusy = false;
      for (const el of document.querySelectorAll('#appearance-dialog input[type=file], #appearance-reset')) el.disabled = false;
    }
  }
  $('appearance-background').onchange = event => uploadImage(event.target, 'background');
  $('appearance-splash-image').onchange = event => uploadImage(event.target, 'splashImage');
  $('appearance-clear-background').onclick = () => { prefs.background = ''; prefs.finish = 'midnight'; applyAppearance(); };
  $('appearance-clear-splash').onclick = () => { prefs.splashImage = ''; prefs.splash = 'wordmark'; applyAppearance(); };
  $('appearance-transparency').addEventListener('input', event => { prefs.transparency = Number(event.target.value); applyAppearance(); });
  $('appearance-reset').onclick = () => { prefs = {...defaults}; collection('signature'); applyAppearance(); };
  applyAppearance(false);
  if (prefs.splash !== 'off') showSplash();

  let latest = {}, online = false, raceBusy = false, raceError = '';
  let demoStart = 0;
  const emptyRace = () => ({phase: 'idle', mode: 'accel', message: 'Choose acceleration or laps', fresh: true, interval: .1, elapsed: 0, distance_m: 0, splits: {}, laps: [], lap_count: 0, history: [], warnings: []});
  let demoRace = emptyRace();
  const seconds = value => Number.isFinite(value) ? `${value.toFixed(2)} s` : '—';
  function renderRace(r = latest.race || {}) {
    const demo = latest.mode === 'demo';
    if (demo) r = demoRace;
    window.frogdashRaceView = r;
    const active = ['armed', 'running'].includes(r.phase);
    $('race-phase').textContent = `${demo ? 'DEMO · ' : ''}${r.phase || 'idle'}`.toUpperCase();
    $('race-phase').dataset.phase = r.phase;
    $('race-source').textContent = demo ? 'SIMULATED RUNS · accelerated preview · no GPS or hardware access' : 'USB GPS timing · continues with this menu closed';
    $('race-quality').textContent = !online ? 'Data connection lost' : !r.fresh ? r.gps_reason || 'Waiting for fresh GPS' : r.interval ? `${(1 / r.interval).toFixed(1)} Hz GPS · estimated timing` : 'GPS ready';
    $('race-elapsed').textContent = (r.elapsed || 0).toFixed(2);
    $('race-message').textContent = r.message || 'Connect a USB GPS to use performance timing';
    $('race-gate').textContent = r.gate ? `Start/finish saved: ${r.gate.map(v => v.toFixed(5)).join(', ')} · leave the gate before crossing` : 'No GPS start/finish saved · manual lap marks available';
    for (const name of ['0_30', '0_60', '0_100kph', 'eighth', 'quarter']) $(`race-${name}`).textContent = seconds(r.splits?.[name]);
    for (const name of ['eighth', 'quarter']) $(`race-${name}-mph`).textContent = Number.isFinite(r.splits?.[name + '_mph']) ? `${r.splits[name + '_mph'].toFixed(1)} MPH at crossing` : 'GPS crossing speed';
    $('race-distance').textContent = `${(r.distance_m || 0).toFixed(0)} m`;
    const last = r.laps?.at(-1);
    $('race-last-lap').textContent = seconds(last?.seconds);
    $('race-best-lap').textContent = seconds(r.best_lap);
    $('race-lap-count').textContent = r.lap_count || 0;
    $('race-lap-delta').textContent = last ? `+${seconds(last.delta)} · ${last.source}` : '—';
    if (!raceBusy) $('race-feedback').textContent = [raceError, r.storage_error, ...(r.warnings || [])].filter(Boolean).join(' · ');
    for (const button of document.querySelectorAll('[data-race]')) {
      const action = button.dataset.race;
      button.disabled = raceBusy || !online || (['accel', 'laps', 'gate'].includes(action) ? active || !r.fresh : action === 'lap' ? r.mode !== 'laps' || r.phase !== 'running' || !r.fresh : action === 'stop' ? !active : active);
    }
    const history = $('race-history'); history.replaceChildren();
    for (const entry of [...(r.history || [])].reverse()) {
      const row = document.createElement('li');
      row.textContent = `${entry.mode === 'laps' ? `Laps · best ${seconds(entry.best_lap)}` : `0–60 ${seconds(entry.splits?.['0_60'])} · ¼ mile ${seconds(entry.splits?.quarter)}`} · ${entry.phase}${entry.warnings?.length ? ' · coarse GPS' : ''}`;
      if (entry.phase === 'invalid') row.textContent += ` · ${entry.message}`;
      history.append(row);
    }
    if (!history.children.length) { const row = document.createElement('li'); row.textContent = 'No sessions recorded yet.'; history.append(row); }
  }
  function demoFinish() { demoRace.history = [...demoRace.history, {...demoRace, history: undefined, timestamp_ms: Date.now()}].slice(-10); }
  function demoCommand(action) {
    if (action === 'gate') { demoRace.gate = [40.0, -105.0]; demoRace.message = 'Demo start/finish saved'; }
    else if (action === 'clear_gate') { demoRace.gate = null; demoRace.message = 'Demo start/finish cleared'; }
    else if (action === 'stop') { demoRace.phase = 'stopped'; demoRace.message = 'Simulated session stopped'; demoFinish(); }
    else if (action === 'reset') demoRace = {...emptyRace(), history: demoRace.history, gate: demoRace.gate};
    else if (action === 'lap') {
      const lap = Math.max(.1, demoRace.elapsed); demoRace.best_lap = Math.min(demoRace.best_lap || Infinity, lap);
      demoRace.lap_count++; demoRace.laps.push({seconds: lap, delta: lap - demoRace.best_lap, source: 'demo'}); demoStart = performance.now();
    } else { demoRace = {...emptyRace(), history: demoRace.history, gate: demoRace.gate, mode: action, phase: 'running', message: 'Simulated session running at 4× speed'}; demoStart = performance.now(); }
  }
  setInterval(() => {
    if (latest.mode !== 'demo' || demoRace.phase !== 'running') return;
    demoRace.elapsed = (performance.now() - demoStart) / 250;
    if (demoRace.mode === 'accel') {
      for (const [key, value] of Object.entries({'0_30': 2.15, '0_60': 5.82, '0_100kph': 6.13, eighth: 9.1, quarter: 13.82})) if (demoRace.elapsed >= value) demoRace.splits[key] = value;
      if (demoRace.splits.eighth) demoRace.splits.eighth_mph = 79.3;
      if (demoRace.splits.quarter) demoRace.splits.quarter_mph = 101.7;
      demoRace.distance_m = Math.min(402.336, 402.336 * (demoRace.elapsed / 13.82) ** 1.5);
      if (demoRace.elapsed >= 13.82) { demoRace.phase = 'complete'; demoRace.elapsed = 13.82; demoRace.message = 'Simulated quarter mile complete'; demoFinish(); }
    }
    renderRace();
  }, 100);
  for (const button of document.querySelectorAll('[data-race]')) button.onclick = async () => {
    if (raceBusy) return;
    raceError = '';
    if (latest.mode === 'demo') { demoCommand(button.dataset.race); renderRace(); return; }
    raceBusy = true; renderRace(); $('race-feedback').textContent = 'Updating race session…';
    try {
      const response = await fetch('/race', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action: button.dataset.race}), signal: AbortSignal.timeout(3000)});
      if (!response.ok) throw new Error(await response.text());
      latest.race = await response.json();
      raceBusy = false; renderRace();
    } catch (error) {
      raceBusy = false; raceError = error.message; renderRace();
    }
  };
  $('race-export').onclick = () => {
    if (latest.mode !== 'demo') { window.location.assign('/race/results'); return; }
    const url = URL.createObjectURL(new Blob([JSON.stringify({simulated: true, history: demoRace.history}, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'frogdash-demo-race-results.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  window.addEventListener('frogdash-state', event => {
    latest = event.detail.snapshot; online = event.detail.connected;
    if ($('splash-dialog').open && !splashPreview) {
      const values = latest.values || {};
      if (values['vehicle.speed_kph']?.value > 1 || values['knock.critical']?.value || values['meth.fault_flags']?.value) hideSplash();
    }
    renderRace();
  });
  renderRace();
})();
