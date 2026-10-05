/* Shared steering-wheel and keyboard navigation. CAN gestures arrive once via state. */
(() => {
  'use strict';
  let editing = null, session = null, cursor = null, enterAt = null, enterTimer, nativeInput = null;
  const selector = 'button, a[href], input:not([type="hidden"]), select, textarea, summary, [tabindex]';
  const hint = document.createElement('output');
  hint.id = 'wheel-hint'; hint.hidden = true; hint.setAttribute('aria-live', 'polite');
  document.body.append(hint);
  const visible = el => el.checkVisibility({checkVisibilityCSS: true}) && !el.closest('[hidden], [inert]') && !el.matches(':disabled') && el.getAttribute('aria-disabled') !== 'true';
  // :modal tracks the active modal even when several dialog elements are open.
  const scope = () => [...document.querySelectorAll('dialog:modal')].at(-1) || document.getElementById('display');
  const candidates = () => [...scope().querySelectorAll(selector)].filter(visible);
  const editable = el => el?.matches('select, input[type="number"], input[type="range"]');
  const textInput = el => el?.matches('textarea, input:not([type]), input[type="text"], input[type="search"], input[type="password"], input[type="url"], input[type="email"]');
  function message(text) {
    // Put the hint in the modal top layer so it remains visible in submenus.
    const parent = scope().matches('dialog') ? scope() : document.body;
    if (hint.parentElement !== parent) parent.append(hint);
    hint.textContent = text; hint.hidden = false;
  }
  function clearEdit() {
    editing?.classList.remove('wheel-editing'); editing = null;
  }
  function focus(el) {
    document.querySelectorAll('.wheel-focus').forEach(item => item.classList.remove('wheel-focus'));
    el?.classList.add('wheel-focus'); el?.focus({preventScroll: true});
    // Centre the focused control so the text around it scrolls into view too.
    el?.scrollIntoView({block: 'center', inline: 'nearest'});
  }
  function describe() {
    const root = scope(), el = document.activeElement;
    const tabs = root.matches('dialog') && typeof sections === 'function' ? sections(root) : [];
    message(editing ? 'SET / COAST: change value  |  ON: done'
      : root.dataset.wheelHint ? root.dataset.wheelHint
      : tabs.includes(el) ? 'SET / COAST: choose section  |  ON: open  |  OFF: close  |  Hold OFF: home'
      : el?.matches?.('[data-wheel-scroll]') ? 'SET / COAST: scroll this list, then move on  |  OFF: back'
      : tabs.length ? 'SET / COAST: move  |  ON: select  |  OFF: back to sections'
      : 'SET / COAST: move  |  ON: select  |  OFF: back  |  Hold OFF: home');
  }
  // Grids (keyboard keys, swatches, files) move in two dimensions; elsewhere arrows walk the list.
  function spatial(items, from, direction) {
    const r = from.getBoundingClientRect(), cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    let best = null, bestScore = Infinity;
    for (const el of items) {
      if (el === from) continue;
      const b = el.getBoundingClientRect(), x = b.x + b.width / 2 - cx, y = b.y + b.height / 2 - cy;
      const along = {up: -y, down: y, left: -x, right: x}[direction];
      const across = direction === 'up' || direction === 'down' ? Math.abs(x) : Math.abs(y);
      if (along <= 4) continue;
      const score = along + across * 2;
      if (score < bestScore) { best = el; bestScore = score; }
    }
    return best;
  }

  // ---- Steering-wheel tools: keyboard, color picker and Pi file picker ----
  const ns = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  function tool(id, eyebrow, hintText) {
    const dialog = ns('dialog', 'workspace-dialog wheel-tool'); dialog.id = id; dialog.dataset.wheelHint = hintText;
    const header = ns('header', 'dialog-header'), titles = ns('div');
    const title = ns('h2'); title.id = `${id}-title`; dialog.setAttribute('aria-labelledby', title.id);
    const note = ns('p', 'wheel-tool-note');
    titles.append(ns('span', 'eyebrow', eyebrow), title, note);
    const cancel = ns('button', 'close-button', 'Cancel'); cancel.type = 'button'; cancel.onclick = () => dialog.close();
    header.append(titles, cancel); dialog.append(header); document.body.append(dialog);
    return {dialog, title, note, body: dialog.appendChild(ns('div', 'wheel-tool-body'))};
  }
  const labelFor = el => (el.id && document.querySelector(`label[for="${el.id}"]`)?.textContent.trim()) || el.getAttribute('aria-label') || el.closest('label')?.firstChild?.textContent?.trim() || el.placeholder || 'Value';
  function commit(target, value) {
    target.value = value;
    target.dispatchEvent(new Event('input', {bubbles: true}));
    target.dispatchEvent(new Event('change', {bubbles: true}));
  }
  function button(text, onclick, extra = {}) { const b = ns('button', extra.cls, text); b.type = 'button'; b.onclick = onclick; Object.assign(b.dataset, extra.data || {}); return b; }
  function returnTo(target) { const dialog = target.closest('dialog'); if (!dialog || dialog.open) focus(target); describe(); }

  // On-screen keyboard for text boxes.
  const kb = tool('wheel-keyboard', 'STEERING WHEEL KEYBOARD', 'KEYBOARD: arrows move | OK type | Hold OK cancel');
  const kbText = ns('output', 'wheel-text'); kb.body.append(kbText);
  const kbGrid = ns('div', 'wheel-keys'); kbGrid.dataset.wheelGrid = ''; kb.body.append(kbGrid);
  let kbTarget = null, kbValue = '', kbCaps = true;
  function kbRender() {
    const limit = kbTarget?.maxLength > 0 ? kbTarget.maxLength : 60;
    kbText.textContent = kbValue + '\u258F';
    kb.note.textContent = `${kbValue.length} / ${limit} characters`;
    for (const key of kbGrid.querySelectorAll('[data-char]')) key.textContent = kbCaps ? key.dataset.char.toUpperCase() : key.dataset.char.toLowerCase();
    kbGrid.querySelector('[data-key="caps"]').setAttribute('aria-pressed', String(kbCaps));
  }
  function kbType(text) {
    const limit = kbTarget?.maxLength > 0 ? kbTarget.maxLength : 60;
    if (kbValue.length < limit) kbValue += text;
    kbRender();
  }
  for (const row of ['1234567890', 'QWERTYUIOP', 'ASDFGHJKL-', "ZXCVBNM.'&", ',/()!?#+:@', '_$%*=;"<>~']) {
    for (const char of row) kbGrid.append(button(char, () => kbType(/[A-Z]/.test(char) && !kbCaps ? char.toLowerCase() : char), {cls: 'wheel-key', data: /[A-Z]/.test(char) ? {char} : {}}));
  }
  kbGrid.append(
    button('Shift', () => { kbCaps = !kbCaps; kbRender(); }, {cls: 'wheel-key wide', data: {key: 'caps'}}),
    button('Space', () => kbType(' '), {cls: 'wheel-key space', data: {key: 'space'}}),
    button('Delete', () => { kbValue = kbValue.slice(0, -1); kbRender(); }, {cls: 'wheel-key wide', data: {key: 'delete'}}),
    button('Clear', () => { kbValue = ''; kbRender(); }, {cls: 'wheel-key wide', data: {key: 'clear'}}),
    button('Done', () => { const target = kbTarget; kb.dialog.close(); commit(target, kbValue); returnTo(target); }, {cls: 'wheel-key wide done', data: {key: 'done'}}));
  kb.dialog.addEventListener('close', () => { if (kbTarget) returnTo(kbTarget); });
  function openKeyboard(target) {
    kbTarget = target; kbValue = target.value || ''; kbCaps = !kbValue || kbValue === kbValue.toUpperCase();
    kb.title.textContent = labelFor(target);
    kbRender();
    kbGrid.querySelectorAll('[data-wheel-start]').forEach(el => el.removeAttribute('data-wheel-start'));
    kbGrid.querySelector('[data-char="A"]').dataset.wheelStart = '';
    kb.dialog.showModal();
  }

  // Color picker for color squares: spectrum swatches plus hue, saturation and lightness.
  const cp = tool('wheel-color', 'STEERING WHEEL COLOR', 'COLOR: arrows move | OK pick or edit slider | Hold OK cancel');
  const cpPreview = ns('div', 'wheel-color-preview'), cpHex = ns('output'); cpPreview.append(ns('i'), cpHex);
  const cpSwatches = ns('div', 'wheel-swatches'); cpSwatches.dataset.wheelGrid = '';
  const cpSliders = ns('div', 'wheel-color-sliders');
  const cpDone = button('Done', () => { const target = cpTarget; cp.dialog.close(); commit(target, cpValue); returnTo(target); }, {cls: 'wheel-done'});
  cp.body.append(cpPreview, cpSwatches, cpSliders, cpDone);
  const cpRanges = {};
  for (const [key, label, max] of [['h', 'Hue', 359], ['s', 'Saturation', 100], ['l', 'Lightness', 100]]) {
    const wrap = ns('label', 'wheel-slider'), out = ns('output'), input = ns('input');
    Object.assign(input, {type: 'range', min: 0, max, step: 1, id: `wheel-color-${key}`});
    wrap.append(ns('span', null, label), out, input); cpSliders.append(wrap);
    cpRanges[key] = {input, out};
    input.addEventListener('input', () => { const c = window.FrogdashAppearance; cpSet(c.hslToHex(+cpRanges.h.input.value, +cpRanges.s.input.value, +cpRanges.l.input.value), true); });
  }
  let cpTarget = null, cpValue = '#ffffff';
  function cpSet(hex, fromSlider = false) {
    cpValue = hex; cpHex.textContent = hex.toUpperCase(); cpPreview.style.setProperty('--chip', hex);
    const [h, s, l] = window.FrogdashAppearance.hexToHsl(hex);
    for (const [key, value, unit] of [['h', h, '°'], ['s', s, '%'], ['l', l, '%']]) {
      if (!fromSlider) cpRanges[key].input.value = Math.round(value);
      cpRanges[key].out.textContent = `${cpRanges[key].input.value}${unit}`;
    }
    for (const b of cpSwatches.children) b.setAttribute('aria-pressed', String(b.dataset.color === hex));
  }
  function openColor(target) {
    cpTarget = target;
    cp.title.textContent = labelFor(target);
    cp.note.textContent = 'Pick a swatch, or fine-tune with the sliders, then Done.';
    if (!cpSwatches.children.length) for (const [name, color] of window.FrogdashAppearance.palette) {
      const b = button('', () => cpSet(color), {cls: 'wheel-swatch', data: {color}}); b.style.setProperty('--swatch', color); b.setAttribute('aria-label', name); b.title = name; cpSwatches.append(b);
    }
    cpSet((target.value || '#ffffff').toLowerCase());
    cpSwatches.querySelectorAll('[data-wheel-start]').forEach(el => el.removeAttribute('data-wheel-start'));
    (cpSwatches.querySelector('[aria-pressed="true"]') || cpSwatches.firstElementChild).dataset.wheelStart = '';
    cp.dialog.showModal();
  }
  cp.dialog.addEventListener('close', () => { if (cpTarget) returnTo(cpTarget); });

  // Pi file picker: images and backups copied into the Pi's import folder.
  const fp = tool('wheel-files', 'STEERING WHEEL FILES', 'FILES: arrows move | OK load | Hold OK cancel');
  const fpList = ns('div', 'wheel-files'); fpList.dataset.wheelGrid = ''; fp.body.append(fpList);
  let fpTarget = null;
  const demoMode = () => typeof FrogdashDemoSocket !== 'undefined' || location.protocol === 'file:';
  function accepts(target, file) {
    const rules = (target.accept || '').split(',').map(r => r.trim().toLowerCase()).filter(Boolean);
    return !rules.length || rules.some(r => r.startsWith('.') ? file.name.toLowerCase().endsWith(r) : r.endsWith('/*') ? file.type.startsWith(r.slice(0, -1)) : file.type === r);
  }
  async function sampleImages() {
    // The standalone preview has no Pi; offer generated images so the flow can be tried.
    return Promise.all([['preview-sunset.png', ['#ff5f6d', '#2b1055']], ['preview-carbon.png', ['#1d2b34', '#05080a']]].map(([name, [a, b]]) => new Promise(resolve => {
      const c = document.createElement('canvas'); c.width = 960; c.height = 360;
      const ctx = c.getContext('2d'), g = ctx.createLinearGradient(0, 0, 960, 360); g.addColorStop(0, a); g.addColorStop(1, b);
      ctx.fillStyle = g; ctx.fillRect(0, 0, 960, 360);
      c.toBlob(blob => resolve({name, type: 'image/png', size: blob.size, blob, url: URL.createObjectURL(blob)}), 'image/png');
    })));
  }
  // The kiosk has no usable system file browser: mouse and touch open this picker too.
  document.addEventListener('click', event => {
    const target = event.target.closest?.('input[type="file"]');
    const kiosk = ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname) || demoMode();
    if (!kiosk || !target || target.disabled || target.dataset.nativePicker !== undefined) return;
    event.preventDefault();
    openFiles(target);
  }, true);
  async function openFiles(target) {
    fpTarget = target;
    fp.title.textContent = labelFor(target);
    fp.note.textContent = 'Loading files…';
    fpList.replaceChildren();
    fp.dialog.showModal(); focus(fp.dialog.querySelector('.close-button')); describe();
    let files = [], folder = '/var/lib/frogdash/import';
    try {
      if (demoMode()) {
        // The published preview ships the same bundled art; opened from disk it cannot be fetched.
        try {
          const manifest = await (await fetch('art/index.json', {cache: 'no-store'})).json();
          files = manifest.map(item => ({...item, type: 'image/jpeg', size: 0, source: 'Bundled art', url: `art/${encodeURIComponent(item.name)}`}));
          folder = 'Bundled art';
        } catch { files = await sampleImages(); folder = 'the preview (generated samples)'; }
      }
      else {
        const listing = await (await fetch('/ui/import', {cache: 'no-store'})).json();
        folder = listing.directory || folder;
        files = listing.files.map(f => ({...f, url: `/ui/import/${encodeURIComponent(f.name)}`}));
        if (listing.error && !files.length) throw new Error(listing.error);
        if (listing.error) folder += ` (import folder unavailable: ${listing.error})`;
      }
    } catch (error) { fp.note.textContent = `Could not list files: ${error.message}`; return; }
    if (!fp.dialog.open || fpTarget !== target) return;
    files = files.filter(f => accepts(target, f));
    const wanted = /splash/i.test(target.id) ? 'splash' : 'background';
    files.sort((a, b) => (a.kind === wanted ? 0 : a.kind ? 2 : 1) - (b.kind === wanted ? 0 : b.kind ? 2 : 1));
    fp.note.textContent = files.length ? `From ${folder}` : `No matching files. Copy them to ${folder} on the Pi (SSH or USB stick), then try again.`;
    for (const file of files) {
      const b = button('', async () => {
        try {
          const blob = file.blob || await (await fetch(file.url, {cache: 'no-store'})).blob();
          const transfer = new DataTransfer(); transfer.items.add(new File([blob], file.name, {type: file.type}));
          fp.dialog.close(); target.files = transfer.files;
          target.dispatchEvent(new Event('change', {bubbles: true})); returnTo(target);
        } catch (error) { fp.note.textContent = `Could not load ${file.name}: ${error.message}`; }
      }, {cls: 'wheel-file'});
      if (file.type.startsWith('image/')) { const img = ns('img'); img.src = file.url; img.alt = ''; img.loading = 'lazy'; b.append(img); }
      const size = !file.size ? '' : file.size < 1024 ? ` · ${file.size} bytes` : ` · ${Math.round(file.size / 1024)} KB`;
      b.append(ns('strong', null, file.title || file.name), ns('small', null, `${file.source || 'Your imports'}${size}`));
      fpList.append(b);
    }
    if (fpList.firstElementChild) focus(fpList.firstElementChild);
    describe();
  }

  // Gauges become reachable by the wheel; OK opens the same picker as press-and-hold.
  document.querySelectorAll('[data-gauge-slot]').forEach(el => { el.tabIndex = 0; });
  // Holding an arrow repeats; long ranges speed up (x1, x10, x100, x1000) so large values stay reachable.
  let run = {el: null, direction: 0, at: 0, count: 0};
  function multiplier(el, direction) {
    const now = performance.now();
    run = run.el === el && run.direction === direction && now - run.at < 400 ? {...run, at: now, count: run.count + 1} : {el, direction, at: now, count: 0};
    const step = Number(el.step) || 1, span = (Number(el.max) - Number(el.min)) / step;
    const want = run.count < 6 ? 1 : run.count < 14 ? 10 : run.count < 24 ? 100 : 1000;
    return Number.isFinite(span) ? Math.max(1, Math.min(want, Math.floor(span / 20))) : want;
  }
  function adjust(el, direction) {
    if (el.matches('select')) {
      const options = [...el.options].filter(o => !o.disabled && !o.parentElement.disabled && !o.hidden);
      const index = options.indexOf(el.selectedOptions[0]);
      const next = options[Math.max(0, Math.min(options.length - 1, index + direction))];
      if (!next) return;
      el.value = next.value;
    } else {
      if (el.readOnly || el.step === 'any') { message('Use touch or a keyboard to edit this field'); return; }
      const times = multiplier(el, direction);
      try { direction > 0 ? el.stepUp(times) : el.stepDown(times); } catch { return; }
    }
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  }
  // ---- Menu model for five buttons (SET up, COAST down, RESUME right, ON select, OFF back) ----
  // A menu with sections has two levels: the section list, then the open section's controls.
  // SET/COAST stay inside the current level; ON or RESUME opens a section; OFF steps back out.
  const TAB = '[role="tab"], [data-driver-tab], [data-ops-tab]';
  const PANEL = '[role="tabpanel"], [data-driver-panel], [data-ops-panel]';
  const closes = el => el.classList.contains('close-button') && /^(close|cancel|skip)/i.test(el.textContent.trim());
  const selected = el => el.getAttribute('aria-selected') === 'true';
  function sections(root) {
    const first = [...root.querySelectorAll(TAB)].find(visible);
    if (!first) return [];
    const list = first.closest('[role="tablist"], nav') || first.parentElement;
    return [...list.querySelectorAll(TAB)].filter(visible);
  }
  function openPanel(root, tabs) {
    const active = tabs.find(selected) || tabs[0];
    const named = document.getElementById(active?.getAttribute('aria-controls') || '');
    return named && named.checkVisibility() ? named : [...root.querySelectorAll(PANEL)].find(panel => panel.checkVisibility()) || null;
  }
  const step = (list, current, direction) => list[(list.indexOf(current) + direction + list.length) % list.length];
  function startOf(root) {
    const all = candidates(), tabs = root.matches('dialog') ? sections(root) : [];
    return all.find(el => el.hasAttribute('data-wheel-start')) || tabs.find(selected) || tabs[0] || all.find(el => !closes(el)) || all[0];
  }
  function clearFocus(blur = true) {
    document.querySelectorAll('.wheel-focus').forEach(el => el.classList.remove('wheel-focus'));
    if (blur) document.activeElement?.blur?.(); // Otherwise keep the focus the browser restored to the opener.
    hint.hidden = true;
  }
  let pendingFocus = null; // A menu entry may name where the highlight should land.

  // Destinations shared by the quick menu (tap) and the dock (hold ON): title, detail, action,
  // shown, icon path (24 x 24 line art) and tile colour.
  function destinations() {
    const byId = id => document.getElementById(id);
    const into = () => { const root = scope(), panel = openPanel(root, sections(root)); pendingFocus = candidates().find(el => panel?.contains(el)) || null; };
    const launch = (id, tab) => () => { byId(id)?.click(); if (tab) { byId(tab)?.click(); into(); } };
    const shown = id => byId(id) && !byId(id).hidden;
    return [
      ['Map', 'Street map with your position', launch('map-launch'), shown('map-launch'), 'M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14', '#2f9e6b'],
      ['Dashcam', 'Live front and rear view', launch('dashcam-launch'), shown('dashcam-launch'), 'M3 8h12v8H3zM15 10.5l6-3v9l-6-3', '#3d6fd6'],
      ['Reverse camera', 'Rear camera view', launch('camera-launch'), shown('camera-launch'), 'M4 8h3l2-2h6l2 2h3v10H4zM12 10.5a2.8 2.8 0 1 0 .01 0', '#5a6b7a'],
      ['Interior lights', 'Colour, brightness, on and off', launch('controls-launch', 'tab-interior'), true, 'M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5V15h8v-1.5A6 6 0 0 0 12 3z', '#d99a1c'],
      ['Taillights', 'Shows, styles, colours and profiles', () => window.FrogdashTaillights?.open(), !!window.FrogdashTaillights, 'M3 8h18v8H3zM9 8v8M15 8v8', '#c8342f'],
      ['Water / meth', 'Arm, test and boost start', launch('controls-launch', 'tab-meth'), true, 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z', '#1f9bc4'],
      ['Knock monitor', 'Live knock energy and events', launch('knock-launch'), true, 'M2 13h5l3-8 4 15 3-7h5', '#c2572b'],
      ['Drive & alerts', 'Display modes, trips, fuel and alerts', launch('drive-launch'), true, 'M3 15a9 9 0 0 1 18 0M12 15l4-5M3 19h18', '#22a37a'],
      ['Race timer', 'Acceleration and lap timing', launch('race-launch'), true, 'M5 21V4M5 4h13l-3 4 3 4H5', '#8a4fd1'],
      ['Appearance', 'Looks, gauges, backgrounds and splash', launch('appearance-launch'), true, 'M12 3a9 9 0 1 0 0 18c1.7 0 2-1.3 1.3-2.4-.8-1.2 0-2.6 1.4-2.6H17a4 4 0 0 0 4-4c0-5-4-9-9-9zM7.5 11h.01M10 7h.01M15 7h.01', '#c2408f'],
      ['Sensors & system check', 'Every signal, CAN check and tests', launch('diagnostics-launch'), true, 'M5 20v-5M12 20V9M19 20V3', '#3f8fb5'],
      ['Wi-Fi', 'Hotspot and internet for updates', launch('controls-launch', 'tab-wifi'), true, 'M2 9a15 15 0 0 1 20 0M5.5 12.5a10 10 0 0 1 13 0M9 16a5 5 0 0 1 6 0M12 19.5h.01', '#3566c9'],
      ['Dash management', 'Update, backup, units and setup', () => { byId('drive-launch')?.click(); byId('operations-launch')?.click(); }, !!byId('operations-launch'), 'M12 9a3 3 0 1 0 .01 0M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1', '#66727e'],
      ['Edit gauges', 'Change what each gauge shows', () => { pendingFocus = document.querySelector('[data-gauge-slot]'); }, !!document.querySelector('[data-gauge-slot]'), 'M4 20l4-1L19 8l-3-3L5 16zM14 6l3 3', '#b08a2a'],
    ].filter(entry => entry[3]);
  }
  const SVG = 'http://www.w3.org/2000/svg';
  function appButton([title, detail, run, , icon, colour], host, label = title) {
    const item = button('', () => { host.close(); run(); }, {cls: 'wheel-app'});
    const tile = ns('span', 'wheel-app-icon'); tile.style.setProperty('--tile', colour);
    const svg = document.createElementNS(SVG, 'svg'); svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(SVG, 'path'); path.setAttribute('d', icon); svg.append(path); tile.append(svg);
    item.append(tile, ns('strong', null, label));
    item.dataset.detail = detail; item.setAttribute('aria-label', `${title}: ${detail}`);
    return item;
  }
  // Clicking the see-through area around the icons closes either overlay.
  const dismissable = dialog => dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });

  // Quick menu: every destination as a centred grid of icons over the dashboard.
  const menu = {dialog: ns('dialog', 'wheel-launch')};
  menu.dialog.id = 'wheel-menu'; menu.dialog.setAttribute('aria-label', 'Menu');
  menu.dialog.dataset.wheelHint = 'SET / COAST: previous / next  |  ON: open  |  OFF: close';
  const menuGrid = ns('div', 'wheel-launch-grid'), menuDetail = ns('p', 'wheel-launch-detail');
  menu.dialog.append(menuGrid, menuDetail); document.body.append(menu.dialog); dismissable(menu.dialog);
  menu.dialog.addEventListener('focusin', event => { menuDetail.textContent = event.target.dataset?.detail || ''; });
  function openMenu() {
    const entries = destinations();
    menuGrid.style.setProperty('--columns', Math.ceil(entries.length / 2));
    menuGrid.replaceChildren(...entries.map((entry, index) => {
      const item = appButton(entry, menu.dialog);
      if (!index) item.dataset.wheelStart = '';
      return item;
    }));
    menu.dialog.showModal();
    focus(menuGrid.firstElementChild); describe();
  }
  // Dock: hold ON on the plain dashboard for the places used most.
  const SHORTCUTS = ['Taillights', 'Knock monitor', 'Interior lights', 'Water / meth', 'Map', 'Dashcam', 'Sensors & system check'];
  const taskbar = ns('dialog', 'wheel-taskbar'); taskbar.id = 'wheel-taskbar';
  taskbar.setAttribute('aria-label', 'Shortcuts');
  taskbar.dataset.wheelHint = 'SET / COAST: previous / next  |  ON: open  |  OFF: close';
  document.body.append(taskbar); dismissable(taskbar);
  function openTaskbar() {
    const entries = destinations().filter(entry => SHORTCUTS.includes(entry[0])).sort((a, b) => SHORTCUTS.indexOf(a[0]) - SHORTCUTS.indexOf(b[0]));
    taskbar.replaceChildren(...entries.map(entry => appButton(entry, taskbar, entry[0] === 'Sensors & system check' ? 'System check' : entry[0])));
    taskbar.showModal();
    focus(taskbar.firstElementChild); describe();
  }
  // Long read-only lists scroll with SET/COAST while highlighted, then let the highlight move on.
  const canScroll = (el, direction) => direction < 0 ? el.scrollTop > 2 : el.scrollTop + el.clientHeight < el.scrollHeight - 2;
  const page = (el, direction) => el.scrollBy({top: direction * Math.max(60, el.clientHeight * .8)});
  function scrollHost(el, root) {
    for (let node = el.parentElement; node && node !== root.parentElement; node = node.parentElement) {
      if (node.scrollHeight > node.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(node).overflowY)) return node;
    }
    return null;
  }

  function activate(current) {
    if (editable(current)) { editing = current; current.classList.add('wheel-editing'); }
    else if (textInput(current)) openKeyboard(current);
    else if (current.matches('input[type="color"]')) openColor(current);
    else if (current.matches('input[type="file"]')) { openFiles(current); return false; }
    else if (current.matches('[data-gauge-slot]')) current.dispatchEvent(new Event('gauge-hold'));
    else if (current.matches('input[type="date"], input[type="time"]')) { message('Use a keyboard for dates and times'); return false; }
    else current.click();
    return true;
  }
  function action(name) {
    nativeInput = null; // Wheel navigation explicitly takes ownership again.
    if (document.hidden || !['up', 'down', 'left', 'right', 'ok', 'back', 'home', 'hold'].includes(name)) return;
    pendingFocus = null;
    if (name === 'hold') {
      // Holding ON: shortcuts on the plain dashboard, back everywhere else.
      if (!scope().matches('dialog') && !candidates().includes(document.activeElement)) { openTaskbar(); return; }
      name = 'back';
    }
    if (name === 'home') {
      // Long hold: leave edit mode and close every open menu, innermost first.
      clearEdit();
      for (let guard = 0; guard < 8; guard++) {
        const open = [...document.querySelectorAll('dialog[open]')].pop();
        if (!open) break;
        const close = [...open.querySelectorAll('.close-button')].find(visible);
        if (close) close.click();
        if (open.open) open.close();
      }
      clearFocus();
      message('HOME: all menus closed');
      return;
    }
    const root = scope(), inDialog = root.matches('dialog'), all = candidates();
    if (editing && (!visible(editing) || !root.contains(editing))) clearEdit();
    const tabs = inDialog ? sections(root) : [];
    const panel = tabs.length ? openPanel(root, tabs) : null;
    const inner = panel ? all.filter(el => panel.contains(el)) : [];
    const outer = tabs.length ? [...tabs, ...all.filter(el => !tabs.includes(el) && !panel?.contains(el) && !closes(el))]
      : all.some(el => !closes(el)) ? all.filter(el => !closes(el)) : all;
    // A Close button focused by the browser when a menu opens does not count as the highlight.
    const current = [...outer, ...inner].includes(document.activeElement) ? document.activeElement : null;
    const deep = !!(current && panel?.contains(current));

    if (name === 'back') {
      if (editing) { clearEdit(); describe(); return; }
      if (deep) { focus(tabs.find(selected) || tabs[0]); describe(); return; } // Out of the section, back to the list.
      if (!inDialog) { clearFocus(); return; }
      const close = [...root.querySelectorAll('.close-button')].find(visible);
      if (close) close.click();
      else if (root.dispatchEvent(new Event('cancel', {cancelable: true}))) root.close();
      if (scope().matches('dialog')) { focus(startOf(scope())); describe(); } else clearFocus(false);
      return;
    }
    if (!inDialog && !current) { openMenu(); return; }   // Any button on the plain dashboard opens the menu.
    if (!current) { focus(startOf(root)); describe(); return; } // Opened by touch or mouse: first press shows the highlight.
    const enter = () => {
      if (!selected(current)) current.click();
      const target = openPanel(root, sections(root));
      const inside = candidates().filter(el => target?.contains(el));
      const first = inside.find(el => el.hasAttribute('data-wheel-first')) || inside[0];
      if (first) focus(first); else message('Nothing to adjust in this section');
    };

    if (name === 'ok') {
      if (editing) clearEdit();
      else if (tabs.includes(current)) { enter(); if (!hint.hidden && hint.textContent.startsWith('Nothing')) return; }
      else if (!activate(current)) return;
      const after = scope();
      if (after !== root) {
        if (after.matches('dialog') || (pendingFocus && visible(pendingFocus))) focus(pendingFocus && visible(pendingFocus) ? pendingFocus : startOf(after));
        else { clearFocus(false); return; }
      } else if (!visible(current)) focus(startOf(root));
    } else if (editing) adjust(editing, ['up', 'right'].includes(name) ? 1 : -1);
    else if (tabs.length && !deep) {
      // Section level: SET/COAST choose a section (shown live); RESUME or ON opens it.
      if (name === 'right' && tabs.includes(current)) enter();
      else {
        const next = step(outer, current, ['up', 'left'].includes(name) ? -1 : 1);
        if (tabs.includes(next) && !selected(next)) next.click();
        focus(next);
      }
    } else {
      const list = tabs.length ? inner : outer;
      const tablist = current.closest('[role="tablist"]');
      const grid = current.closest('[data-wheel-grid]');
      const neighbour = grid && spatial([...grid.querySelectorAll(selector)].filter(visible), current, name);
      if (current.matches('[role="tab"]') && tablist && ['left', 'right'].includes(name)) {
        // A tab row inside a section: RESUME cycles through it.
        const row = [...tablist.querySelectorAll('[role="tab"]')].filter(visible);
        const next = step(row, current, name === 'left' ? -1 : 1);
        next.click(); focus(next);
      } else if (neighbour) focus(neighbour);
      else {
        const direction = ['up', 'left'].includes(name) ? -1 : 1;
        const index = list.indexOf(current), atEdge = direction > 0 ? index === list.length - 1 : index <= 0;
        const host = atEdge ? scrollHost(current, root) : null;
        if (current.matches('[data-wheel-scroll]') && canScroll(current, direction)) page(current, direction);
        else if (host && canScroll(host, direction)) page(host, direction); // Text beyond the last control.
        else focus(step(list, current, direction));
      }
    }
    describe();
  }
  window.addEventListener('frogdash-state', ({detail}) => {
    const wheel = detail.snapshot.wheel;
    if (!detail.connected) { session = cursor = null; clearEdit(); return; }
    if (!wheel || detail.snapshot.mode === 'replay') { session = cursor = null; return; }
    if (session !== wheel.session || cursor === null || wheel.seq < cursor) {
      session = wheel.session; cursor = wheel.seq; return; // Never replay input on reload/reconnect.
    }
    for (const event of wheel.events || []) {
      if (event.id > cursor && event.age_ms <= 750) action(event.action);
    }
    cursor = wheel.seq;
  });
  document.addEventListener('pointerdown', event => {
    nativeInput = editable(event.target) ? event.target : null;
    clearEdit(); hint.hidden = true;
    document.querySelectorAll('.wheel-focus').forEach(el => el.classList.remove('wheel-focus'));
  }, true);
  // Keyboard stand-ins for the five wheel buttons (preview and a keyboard on the Pi):
  // W = SET/ACCEL, S = COAST, D = RESUME, A = OFF, E / Space / Enter = ON, with the same holds.
  let homeTimer, offTimer, offAt = null;
  function cancelEnter() { clearTimeout(enterTimer); clearTimeout(homeTimer); clearTimeout(offTimer); enterAt = offAt = null; }
  document.addEventListener('visibilitychange', () => { cancelEnter(); clearEdit(); });
  window.addEventListener('blur', cancelEnter);
  const MOVES = {ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Escape: 'back', w: 'up', s: 'down', d: 'right'};
  const keyOf = event => event.key.length === 1 ? event.key.toLowerCase() : event.key;
  const isOn = key => key === 'Enter' || key === 'e' || key === ' ';
  document.addEventListener('keydown', event => {
    // After a touch/click, use the browser's normal slider/select/number keys.
    if (event.target === nativeInput && !editing && event.key !== 'Escape') return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || textInput(event.target)) return;
    const key = keyOf(event), name = MOVES[key];
    if (!name && !isOn(key) && key !== 'a') return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (name) { if (name !== 'back' || !event.repeat) action(name); return; }
    if (key === 'a') {  // OFF: back at once, home after 1.5 s.
      if (event.repeat || offAt !== null) return;
      offAt = performance.now();
      action('back');
      offTimer = setTimeout(() => action('home'), 1500);
      return;
    }
    if (event.repeat || enterAt !== null) return;
    enterAt = performance.now();  // ON: select on release, hold at 0.8 s, home at 3 s.
    enterTimer = setTimeout(() => { if (enterAt !== null) { action('hold'); enterAt = -1; } }, 800);
    homeTimer = setTimeout(() => { if (enterAt !== null) action('home'); }, 3000);
  }, true);
  document.addEventListener('keyup', event => {
    const key = keyOf(event);
    if (key === 'a') { clearTimeout(offTimer); offAt = null; return; }
    if (!isOn(key) || enterAt === null) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (enterAt >= 0) action('ok');
    cancelEnter();
  }, true);
})();
