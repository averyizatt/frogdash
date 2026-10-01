/* Display preferences and the GPS race workspace. No vehicle actuator commands. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  // A look sets structure (gauges, typeface, panel shape/edges, glow) as well as color.
  const looks = {
    original: {name: 'Fox Mint', note: 'Electric mint · cyan duotone · soft panels', accent: '#1cf29a', accent2: '#00c3ff', finish: 'midnight', surface: '#111a20', raised: '#18232b', line: '#2b3943'},
    glacier: {name: 'Glacier', note: 'Arctic blue · rounded glass · soft glow', accent: '#29b6ff', accent2: '#8ae6ff', finish: 'horizon', surface: '#111c29', raised: '#1b2c3c', line: '#34485c', shape: 'round', edge: 'glow', glow: 25, transparency: 15},
    heritage: {name: 'Heritage', note: 'Amber analog dials · serif numerals', accent: '#ffa000', accent2: '#ff6a00', needle: '#ff5a1f', numeral: '#fff1d6', gauges: 'analog', font: 'serif', finish: 'graphite', surface: '#211c17', raised: '#2c251e', line: '#4b4035', shape: 'round'},
    afterhours: {name: 'After hours', note: 'Ultraviolet · magenta glow · dusk', accent: '#a24dff', accent2: '#ff2fd0', finish: 'dusk', surface: '#1b1726', raised: '#292137', line: '#443853', shape: 'round', edge: 'glow', glow: 55},
    apex: {name: 'Apex', note: 'Platinum mono type · red rail · carbon', accent: '#eef3f6', accent2: '#ff2a2a', font: 'mono', finish: 'carbon', surface: '#191d22', raised: '#272c32', line: '#434a53', shape: 'sharp', edge: 'rail'},
    expedition: {name: 'Expedition', note: 'Trail green · signal orange · cut corners', accent: '#7ed321', accent2: '#ff9f0a', finish: 'contour', surface: '#192018', raised: '#263024', line: '#3e4c39', shape: 'chamfer', edge: 'accent'},
    sprint: {name: 'GT Sprint', note: 'Acid yellow / racing italic / square rails', accent: '#d4ff00', accent2: '#ffffff', font: 'racing', finish: 'pitlane', surface: '#141a13', raised: '#242c20', line: '#424d37', style: 'race', shape: 'sharp', edge: 'rail', transparency: 15},
    endurance: {name: 'Endurance', note: 'Platinum analog / red needles / pit stripes', accent: '#e8eef2', accent2: '#ff1e1e', needle: '#ff1e1e', gauges: 'analog', font: 'racing', finish: 'apexline', surface: '#171b22', raised: '#262c35', line: '#424b58', style: 'race', shape: 'sharp', transparency: 20},
    rally: {name: 'Rally Stage', note: 'Stage cyan / yellow meters / cut corners', accent: '#00e1ff', accent2: '#ffd400', font: 'racing', finish: 'technical', surface: '#101e25', raised: '#1d3039', line: '#355361', style: 'race', shape: 'chamfer', edge: 'rail', transparency: 15},
    clubsport: {name: 'Club Sport', note: 'Safety orange / outlined panels / carbon', accent: '#ff7a00', accent2: '#ffd000', finish: 'carbon', surface: '#201b17', raised: '#31271e', line: '#504132', style: 'race', shape: 'sharp', edge: 'accent', transparency: 10},
    obsidian: {name: 'Obsidian', note: 'Monochrome mono type / borderless satin', accent: '#dfe7ee', accent2: '#8a9aa8', font: 'mono', finish: 'satin', surface: '#171b21', raised: '#252b33', line: '#3d4854', style: 'touring', shape: 'round', edge: 'none', transparency: 25},
    executive: {name: 'Executive', note: 'Champagne analog / serif / midnight blue', accent: '#f0c060', accent2: '#ffe3a3', needle: '#f0c060', numeral: '#fff6e0', gauges: 'analog', font: 'serif', finish: 'horizon', surface: '#151d2a', raised: '#253145', line: '#42526a', style: 'touring', shape: 'round', transparency: 20},
    foxbody: {name: 'Foxbody LX', note: 'Charcoal binnacle / orange needles', accent: '#f2ecd2', accent2: '#ff6a1a', needle: '#ff5a1f', gauges: 'foxbody', collection: 'retro', finish: 'charcoal', surface: '#161b18', raised: '#252a27', line: '#454a43', shape: 'sharp'},
    foxnight: {name: 'Foxbody Afterdark', note: 'Green illumination / factory spirit', accent: '#2dff6a', accent2: '#2dff6a', needle: '#ff5a1f', numeral: '#c8ffd6', gauges: 'foxbody', collection: 'retro', finish: 'phosphor', surface: '#101e17', raised: '#20372a', line: '#385844', shape: 'sharp', glow: 30},
    svo: {name: 'Turbo Heritage', note: 'Amber serif dials / copper', accent: '#ffae00', accent2: '#ff3b1f', needle: '#ff3b1f', numeral: '#ffe7c2', gauges: 'analog', font: 'serif', collection: 'retro', finish: 'copper', surface: '#211811', raised: '#35251c', line: '#614c36', shape: 'round'},
    outrun: {name: 'Midnight Runner', note: '1986 tomorrow / slanted pink LEDs', accent: '#ff2bd6', accent2: '#00e5ff', needle: '#00e5ff', gauges: 'digital', font: 'racing', collection: 'retro', finish: 'synthwave', surface: '#171128', raised: '#2b1d3d', line: '#66426c', style: 'race', shape: 'sharp', edge: 'glow', glow: 60, transparency: 15},
    terminal: {name: 'Green Terminal', note: 'Phosphor display / segmented meters', accent: '#33ff66', accent2: '#33ff66', gauges: 'digital', font: 'mono', collection: 'retro', finish: 'phosphor', surface: '#091b13', raised: '#153525', line: '#346447', style: 'race', shape: 'sharp', edge: 'accent', glow: 40},
    vector: {name: 'Vector Interceptor', note: 'Ice cyan / red needles / cut-corner pod', accent: '#00d4ff', accent2: '#ff2d55', needle: '#ff2d55', gauges: 'analog', collection: 'retro', finish: 'blueprint', surface: '#0b1925', raised: '#173043', line: '#34566b', shape: 'chamfer', edge: 'glow', glow: 25, transparency: 10},
    cyberdeck: {name: 'Cyberdeck', note: 'Neon HUD / magenta + cyan / neon city', accent: '#ff2bd6', accent2: '#00f0ff', numeral: '#ffffff', gauges: 'cyber', font: 'mono', collection: 'cyber', finish: 'neoncity', surface: '#120b1c', raised: '#1f1230', line: '#4a2a5e', shape: 'chamfer', edge: 'glow', glow: 65, transparency: 20},
    netrunner: {name: 'Netrunner', note: 'Neon HUD / acid green on circuit traces', accent: '#39ff14', accent2: '#00a8ff', numeral: '#eaffe4', gauges: 'cyber', font: 'mono', collection: 'cyber', finish: 'circuit', surface: '#07140c', raised: '#0e2416', line: '#1f4a2c', shape: 'sharp', edge: 'accent', glow: 45, transparency: 15},
    ronin: {name: 'Chrome Ronin', note: 'Neon HUD / blood red + chrome / italic', accent: '#ff1f3d', accent2: '#e8eef2', numeral: '#ffffff', gauges: 'cyber', font: 'racing', collection: 'cyber', finish: 'void', surface: '#0e0c0d', raised: '#1c1718', line: '#3b2a2d', shape: 'chamfer', edge: 'rail', glow: 20},
    hologram: {name: 'Hologram', note: 'Floating glass / cyan-violet glow / aurora', accent: '#00f0ff', accent2: '#b44dff', numeral: '#e6fdff', collection: 'cyber', finish: 'aurora', surface: '#0a1622', raised: '#12283a', line: '#1e4a66', shape: 'round', edge: 'glow', glow: 80, transparency: 55},
    toxic: {name: 'Toxic', note: 'Segment LEDs / hazard yellow + hot pink', accent: '#c6ff00', accent2: '#ff0a8c', needle: '#ff0a8c', gauges: 'digital', font: 'mono', collection: 'cyber', finish: 'hazard', surface: '#11120a', raised: '#1f2210', line: '#44471d', style: 'race', shape: 'sharp', edge: 'accent', glow: 50},
    blackout: {name: 'Blackout', note: 'Neon HUD / pure white on true black', accent: '#ffffff', accent2: '#ff2020', numeral: '#ffffff', gauges: 'cyber', collection: 'cyber', finish: 'void', surface: '#000000', raised: '#0b0b0b', line: '#2a2a2a', shape: 'sharp', edge: 'none'}
  };
  const finishes = {midnight: 'Midnight', graphite: 'Graphite', carbon: 'Carbon weave', glow: 'Accent glow', horizon: 'Horizon', grid: 'Blueprint', contour: 'Contours', dusk: 'Dusk', pitlane: 'Pit lane', apexline: 'Redline', technical: 'Telemetry', satin: 'Satin', charcoal: 'Charcoal', phosphor: 'Phosphor', synthwave: 'Neon grid', sunset: 'Afterglow', blueprint: 'Vector grid', copper: 'Copper', void: 'True black', duotone: 'Duotone', neoncity: 'Neon city', circuit: 'Circuit', hazard: 'Hazard', aurora: 'Aurora', image: 'Custom image'};
  const fonts = {sans: ['Modern sans', '"DejaVu Sans","Segoe UI",Arial,sans-serif', 'normal'], mono: ['Mechanical mono', '"DejaVu Sans Mono",Consolas,monospace', 'normal'], serif: ['Classic serif', '"DejaVu Serif",Georgia,serif', 'normal'], racing: ['Racing italic', '"DejaVu Sans","Segoe UI",Arial,sans-serif', 'italic']};
  const shapes = {soft: 'Soft corners', sharp: 'Sharp / square', round: 'Rounded', chamfer: 'Chamfered / cut corners'};
  const edges = {hairline: 'Hairline', accent: 'Accent outline', rail: 'Top accent rail', glow: 'Neon glow', none: 'Borderless'};
  const layouts = ['standard', 'foxbody', 'analog', 'digital', 'cyber'];
  const colorFields = ['accent', 'accent2', 'numeral', 'needle'];
  const styleOf = look => ({accent: look.accent, accent2: look.accent2 || look.accent, numeral: look.numeral || '#f4f7f6', needle: look.needle || '#f5f0df', finish: look.finish, transparency: look.transparency || 0, gauges: look.gauges || 'standard', font: look.font || 'sans', shape: look.shape || 'soft', edge: look.edge || 'hairline', glow: look.glow || 0});
  const collectionOf = look => look.collection || (look.style ? 'performance' : 'signature');
  const defaults = {look: 'original', ...styleOf(looks.original), background: '', splash: 'off', splashImage: '', title: 'FOX BODY', duration: 2};
  const key = 'frogdash.appearance.v1';
  const isHex = value => /^#[0-9a-f]{6}$/i.test(value);
  const validImage = value => typeof value === 'string' && value.length < 1500000 && /^data:image\/(jpeg|png|webp);base64,[a-z0-9+/=]+$/i.test(value);
  let prefs = {...defaults}, splashTimer, splashPreview = false, slot = 'accent', paintTimer, postedPaint = '';
  try {
    const stored = JSON.parse(localStorage.getItem(key));
    if (stored && typeof stored === 'object') {
      if (Object.hasOwn(looks, stored.look)) { prefs.look = stored.look; Object.assign(prefs, styleOf(looks[stored.look])); }
      // Profiles saved before the color studio only held the old pastel palette;
      // they adopt the look's current colors and keep every other choice.
      if (isHex(stored.accent2)) for (const field of colorFields) if (isHex(stored[field])) prefs[field] = stored[field].toLowerCase();
      if (layouts.includes(stored.gauges)) prefs.gauges = stored.gauges;
      if (Object.hasOwn(fonts, stored.font)) prefs.font = stored.font;
      if (Object.hasOwn(shapes, stored.shape)) prefs.shape = stored.shape;
      if (Object.hasOwn(edges, stored.edge)) prefs.edge = stored.edge;
      if (Number.isFinite(stored.glow)) prefs.glow = Math.max(0, Math.min(100, stored.glow));
      if (Object.hasOwn(finishes, stored.finish)) prefs.finish = stored.finish;
      if (['off', 'wordmark', 'image'].includes(stored.splash)) prefs.splash = stored.splash;
      if (validImage(stored.background)) prefs.background = stored.background;
      if (validImage(stored.splashImage)) prefs.splashImage = stored.splashImage;
      if (typeof stored.title === 'string') prefs.title = stored.title.slice(0, 32);
      if ([1, 2, 3, 5].includes(stored.duration)) prefs.duration = stored.duration;
      if (Number.isFinite(stored.transparency)) prefs.transparency = Math.max(0, Math.min(100, stored.transparency));
    }
  } catch { /* Unavailable storage falls back to a fully usable dash. */ }

  function hexToHsl(hex) {
    const [r, g, b] = hex.slice(1).match(/../g).map(v => parseInt(v, 16) / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
    if (!d) return [0, 0, l * 100];
    const s = d / (1 - Math.abs(2 * l - 1));
    const h = max === r ? ((g - b) / d + 6) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h * 60, s * 100, l * 100];
  }
  function hslToHex(h, s, l) {
    s /= 100; l /= 100;
    const f = n => { const k = (n + h / 30) % 12; return l - s * Math.min(l, 1 - l) * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
    return '#' + [f(0), f(8), f(4)].map(v => Math.round(v * 255).toString(16).padStart(2, '0')).join('');
  }
  const luminance = hex => hex.slice(1).match(/../g).map(v => parseInt(v, 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((n, v, i) => n + v * [.2126, .7152, .0722][i], 0);
  // Keep hue and saturation; only raise lightness until the color reads on a dark panel.
  // Fully saturated reds, blues and violets therefore stay vivid instead of turning pastel.
  function readableAccent(hex) {
    hex = hex.toLowerCase();
    if (luminance(hex) >= .13) return hex;
    const [h, s, l] = hexToHsl(hex);
    for (let next = Math.ceil(l); next <= 100; next++) { const candidate = hslToHex(h, s, next); if (luminance(candidate) >= .13) return candidate; }
    return '#ffffff';
  }

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
    const style = styleOf(look);
    const button = document.createElement('button'); button.type = 'button'; button.dataset.look = id;
    Object.assign(button.dataset, {collection: collectionOf(look), instrumentStyle: look.style || 'classic', gaugePreview: style.gauges, shape: style.shape, edge: style.edge});
    button.className = 'look-card'; button.setAttribute('aria-label', `Apply ${look.name} look`);
    for (const [token, value] of [['accent', style.accent], ['accent-2', style.accent2], ['numeral', style.numeral], ['needle', style.needle], ['surface', look.surface], ['numeral-font', fonts[style.font][1]], ['numeral-style', fonts[style.font][2]], ['glow-blur', `${Math.round(style.glow * .3)}px`], ['glow-mix', `${Math.round(style.glow * .75)}%`]]) button.style.setProperty(`--${token}`, value);
    // Static, local catalogue text only; uploaded artwork never enters markup.
    button.innerHTML = `<span class="look-art" data-scene="${look.finish}" aria-hidden="true"><span class="mini-gauge"></span><span class="mini-speed">76<small>MPH</small></span><span class="mini-bars"></span></span><span class="look-caption"><strong>${look.name}</strong><span class="look-check" aria-hidden="true">✓</span><small>${look.note}</small></span>`;
    button.onclick = () => { Object.assign(prefs, styleOf(look)); prefs.look = id; applyAppearance(); };
    $('appearance-looks').append(button);
  }
  function collection(name) {
    for (const button of document.querySelectorAll('button[data-collection-filter]')) button.setAttribute('aria-pressed', String(button.dataset.collectionFilter === name));
    for (const card of document.querySelectorAll('.look-card')) card.hidden = card.dataset.collection !== name;
  }
  for (const button of document.querySelectorAll('button[data-collection-filter]')) button.onclick = () => collection(button.dataset.collectionFilter);
  collection(collectionOf(looks[prefs.look]));
  $('appearance-finish').replaceChildren();
  for (const [id, name] of Object.entries(finishes)) {
    const option = document.createElement('option'); option.value = id; option.textContent = name; $('appearance-finish').append(option);
    if (id === 'image') continue;
    const button = document.createElement('button'); button.type = 'button'; button.dataset.background = id;
    button.innerHTML = `<span data-scene="${id}" aria-hidden="true"></span><strong>${name}</strong>`;
    button.onclick = () => { prefs.finish = id; applyAppearance(); };
    $('appearance-backgrounds').append(button);
  }
  for (const [id, choices] of [['font', fonts], ['shape', shapes], ['edge', edges]]) {
    $(`appearance-${id}`).replaceChildren(...Object.entries(choices).map(([value, label]) => Object.assign(document.createElement('option'), {value, textContent: Array.isArray(label) ? label[0] : label})));
  }

  function syncStudio(fromSlider = false) {
    for (const button of document.querySelectorAll('[data-color-slot]')) {
      const field = button.dataset.colorSlot;
      button.setAttribute('aria-checked', String(field === slot));
      button.style.setProperty('--chip', prefs[field]);
      button.querySelector('code').textContent = prefs[field].toUpperCase();
    }
    for (const button of document.querySelectorAll('[data-swatch]')) button.setAttribute('aria-pressed', String(button.dataset.swatch === prefs[slot]));
    if (!fromSlider) {
      const [h, s, l] = hexToHsl(prefs[slot]);
      $('appearance-hue').value = Math.round(h); $('appearance-sat').value = Math.round(s); $('appearance-light').value = Math.round(l);
    }
    const h = +$('appearance-hue').value, s = +$('appearance-sat').value, l = +$('appearance-light').value;
    $('appearance-hue-value').textContent = `${h}°`; $('appearance-sat-value').textContent = `${s}%`; $('appearance-light-value').textContent = `${l}%`;
    $('appearance-sat').style.setProperty('--track', `linear-gradient(90deg,hsl(${h} 0% ${l}%),hsl(${h} 100% ${l}%))`);
    $('appearance-light').style.setProperty('--track', `linear-gradient(90deg,hsl(${h} ${s}% 12%),hsl(${h} ${s}% 50%),hsl(${h} ${s}% 96%))`);
    $('appearance-studio-target').textContent = document.querySelector(`[data-color-slot="${slot}"] span`).firstChild.textContent;
  }
  function applyAppearance(save = true, fromSlider = false) {
    for (const field of colorFields) prefs[field] = readableAccent(prefs[field]);
    const root = document.documentElement;
    const look = looks[prefs.look];
    for (const [token, value] of [['accent', prefs.accent], ['accent-2', prefs.accent2], ['numeral', prefs.numeral], ['needle', prefs.needle], ['numeral-font', fonts[prefs.font][1]], ['numeral-style', fonts[prefs.font][2]], ['glow-blur', `${Math.round(prefs.glow * .3)}px`], ['glow-mix', `${Math.round(prefs.glow * .75)}%`], ['edge-glow', `${Math.round(6 + prefs.glow * .18)}px`]]) root.style.setProperty(`--${token}`, value);
    for (const token of ['surface', 'raised', 'line']) root.style.setProperty(`--${token}`, look[token]);
    root.style.setProperty('--bg', {graphite: '#191d22', void: '#000000'}[prefs.finish] || '#090f13');
    root.dataset.instrumentStyle = look.style || 'classic';
    Object.assign(root.dataset, {gauges: prefs.gauges, preset: prefs.look, font: prefs.font, shape: prefs.shape, edge: prefs.edge, glow: prefs.glow > 0 ? 'on' : 'off'});
    for (const id of ['gauges', 'font', 'shape', 'edge', 'glow', ...colorFields]) $(`appearance-${id}`).value = prefs[id];
    $('appearance-glow-value').textContent = `${prefs.glow}%`;
    root.style.setProperty('--widget-fill', `${100 - prefs.transparency}%`);
    root.dataset.finish = prefs.finish;
    root.dataset.scene = prefs.finish;
    root.style.setProperty('--custom-background', prefs.background ? `url("${prefs.background}")` : 'none');
    $('appearance-transparency').value = prefs.transparency;
    $('appearance-transparency-value').textContent = `${prefs.transparency}%`;
    $('appearance-transparency').setAttribute('aria-valuetext', `${prefs.transparency}% transparent`);
    $('appearance-finish').value = prefs.finish;
    $('appearance-splash').value = prefs.splash;
    $('appearance-title-input').value = prefs.title;
    $('appearance-duration').value = prefs.duration;
    syncStudio(fromSlider);
    const preset = styleOf(look), exact = Object.keys(preset).every(field => prefs[field] === preset[field]);
    $('appearance-current').textContent = `${look.name}${exact ? '' : ' · customized'} / ${finishes[prefs.finish]}`;
    for (const button of document.querySelectorAll('button[data-look]')) button.setAttribute('aria-pressed', String(button.dataset.look === prefs.look && exact));
    for (const button of document.querySelectorAll('button[data-background]')) button.setAttribute('aria-pressed', String(button.dataset.background === prefs.finish));
    window.dispatchEvent(new Event('frogdash-appearance'));
    // Snapshot for boot.js, which applies it before first paint on the next start.
    // The uploaded background stays only in the main profile to avoid storing it twice.
    try {
      // Built per property: an image data URL contains ';', so trimming the string is unsafe.
      const style = [...root.style].filter(name => name !== '--custom-background').map(name => `${name}: ${root.style.getPropertyValue(name)}`).join('; ');
      const data = Object.fromEntries(['instrumentStyle', 'gauges', 'preset', 'font', 'shape', 'edge', 'glow', 'finish', 'scene'].map(name => [name, root.dataset[name]]));
      const snapshot = JSON.stringify({style, data, splash: prefs.splash !== 'off'});
      localStorage.setItem('frogdash.appearance.paint.v1', snapshot);
      // The Pi also keeps it on disk: browser storage may not be flushed before key-off.
      if (typeof FrogdashDemoSocket === 'undefined' && location.protocol.startsWith('http') && snapshot !== postedPaint) {
        clearTimeout(paintTimer);
        paintTimer = setTimeout(() => fetch('/ui/appearance', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: snapshot})
          .then(response => { if (response.ok) postedPaint = snapshot; }).catch(() => {}), 400);
      }
    } catch { /* The page still applies the look normally on the next start. */ }
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
    $('splash-title').textContent = prefs.title || 'FOX BODY';
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
  // Full-saturation spectrum plus a few instrument whites; any other color comes from the sliders.
  const palette = [['Red', '#ff1a1a'], ['Blood orange', '#ff4d00'], ['Orange', '#ff8000'], ['Amber', '#ffb300'], ['Yellow', '#ffe600'], ['Lime', '#b3ff00'], ['Green', '#22ff22'], ['Emerald', '#00e676'],
    ['Aqua', '#00ffb0'], ['Teal', '#00e5c8'], ['Cyan', '#00e5ff'], ['Sky', '#00a2ff'], ['Blue', '#2962ff'], ['Indigo', '#6a4dff'], ['Violet', '#9d00ff'], ['Purple', '#c800ff'],
    ['Magenta', '#ff00ff'], ['Hot pink', '#ff2d95'], ['Rose', '#ff0055'], ['Gold', '#ffc933'], ['White', '#ffffff'], ['Ivory', '#f2ecd2'], ['Silver', '#b8c4cc'], ['Tungsten', '#ffd9a0']];
  Object.assign(window.FrogdashAppearance, {hexToHsl, hslToHex, palette});
  const swatches = $('appearance-swatches'); swatches.replaceChildren();
  for (const [name, color] of palette) {
    const button = document.createElement('button'); button.type = 'button'; button.dataset.swatch = color;
    button.style.setProperty('--swatch', color); button.setAttribute('aria-label', name); button.title = name;
    button.onclick = () => { prefs[slot] = color; applyAppearance(); };
    swatches.append(button);
  }
  for (const button of document.querySelectorAll('[data-color-slot]')) button.onclick = () => { slot = button.dataset.colorSlot; syncStudio(); };
  for (const id of ['hue', 'sat', 'light']) $(`appearance-${id}`).addEventListener('input', () => {
    prefs[slot] = hslToHex(+$('appearance-hue').value, +$('appearance-sat').value, +$('appearance-light').value);
    applyAppearance(true, true);
  });
  const harmonies = {match: 0, analogous: 35, triad: 120, complement: 180};
  for (const button of document.querySelectorAll('[data-harmony]')) button.onclick = () => {
    const [h, s, l] = hexToHsl(prefs.accent);
    prefs.accent2 = hslToHex((h + harmonies[button.dataset.harmony]) % 360, s, l);
    slot = 'accent2'; applyAppearance();
  };
  for (const [id, field] of [['gauges', 'gauges'], ['font', 'font'], ['shape', 'shape'], ['edge', 'edge'], ['needle', 'needle'], ['accent', 'accent'], ['accent2', 'accent2'], ['numeral', 'numeral'], ['finish', 'finish'], ['splash', 'splash'], ['title-input', 'title'], ['duration', 'duration']]) {
    $(`appearance-${id}`).addEventListener('change', event => {
      prefs[field] = field === 'duration' ? Number(event.target.value) : event.target.value;
      if (colorFields.includes(field)) slot = field;
      applyAppearance();
    });
  }
  $('appearance-glow').addEventListener('input', event => { prefs.glow = Number(event.target.value); applyAppearance(); });
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
      applyAppearance(); storeImage(field);
    } catch (error) { $('appearance-feedback').textContent = error.message || 'Could not read this image.'; }
    finally {
      if (url) URL.revokeObjectURL(url);
      input.value = ''; imageBusy = false;
      for (const el of document.querySelectorAll('#appearance-dialog input[type=file], #appearance-reset')) el.disabled = false;
    }
  }
  // Images are also kept on the Pi's disk; browser storage may not be flushed before key-off.
  const onPi = typeof FrogdashDemoSocket === 'undefined' && location.protocol.startsWith('http');
  const imageUrl = field => `/ui/appearance/image/${field === 'background' ? 'background' : 'splash'}`;
  function storeImage(field) {
    if (!onPi) return;
    const data = prefs[field];
    fetch(imageUrl(field), data ? {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({data})} : {method: 'DELETE'})
      .then(response => { if (!response.ok) throw new Error(); })
      .catch(() => appearanceMessage('Image applied, but the Pi could not save it to disk.'));
  }
  async function restoreImages() {
    if (!onPi) return;
    for (const field of ['background', 'splashImage']) {
      const wanted = field === 'background' ? prefs.finish === 'image' : prefs.splash === 'image';
      if (!wanted || prefs[field]) continue;
      try {
        const response = await fetch(imageUrl(field), {cache: 'no-store'});
        const {data} = response.ok ? await response.json() : {};
        if (validImage(data)) { prefs[field] = data; applyAppearance(); }
      } catch { /* Offline server: keep the look without the image. */ }
    }
  }
  $('appearance-background').onchange = event => uploadImage(event.target, 'background');
  $('appearance-splash-image').onchange = event => uploadImage(event.target, 'splashImage');
  $('appearance-clear-background').onclick = () => { prefs.background = ''; prefs.finish = 'midnight'; applyAppearance(); storeImage('background'); };
  $('appearance-clear-splash').onclick = () => { prefs.splashImage = ''; prefs.splash = 'wordmark'; applyAppearance(); storeImage('splashImage'); };
  $('appearance-transparency').addEventListener('input', event => { prefs.transparency = Number(event.target.value); applyAppearance(); });
  $('appearance-reset').onclick = () => { prefs = {...defaults}; slot = 'accent'; collection('signature'); applyAppearance(); storeImage('background'); storeImage('splashImage'); };
  applyAppearance(false);
  restoreImages();
  if (prefs.splash !== 'off') showSplash();
  // boot.js hid the dashboard until the splash could cover it; it is now open (or off).
  delete document.documentElement.dataset.splashPending;

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
