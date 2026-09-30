/* Shared steering-wheel and keyboard navigation. CAN gestures arrive once via state. */
(() => {
  'use strict';
  let editing = null, session = null, cursor = null, enterAt = null, enterTimer, nativeInput = null;
  const selector = 'button, a[href], input:not([type="hidden"]), select, textarea, [tabindex]';
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
    el?.scrollIntoView({block: 'nearest', inline: 'nearest'});
  }
  function describe() {
    message(editing ? 'EDIT: arrows change value | OK done | Hold OK back' : scope().dataset.wheelHint || 'WHEEL: arrows move | OK select | Hold OK back');
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
  for (const row of ['1234567890', 'QWERTYUIOP', 'ASDFGHJKL-', "ZXCVBNM.'&", ',/()!?#+:@']) {
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
          files = manifest.map(item => ({...item, type: 'image/jpeg', size: 0, source: 'Frogdash art', url: `art/${encodeURIComponent(item.name)}`}));
          folder = 'Frogdash art';
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
  function action(name) {
    nativeInput = null; // Wheel navigation explicitly takes ownership again.
    if (document.hidden || !['up', 'down', 'left', 'right', 'ok', 'back'].includes(name)) return;
    const before = scope();
    const items = candidates();
    if (editing && (!visible(editing) || !before.contains(editing))) clearEdit();
    let current = items.includes(document.activeElement) ? document.activeElement : null;
    if (name === 'back') {
      if (editing) { clearEdit(); describe(); return; }
      if (before.matches('dialog')) {
        const close = [...before.querySelectorAll('.close-button')].find(visible);
        if (close) close.click();
        else if (before.dispatchEvent(new Event('cancel', {cancelable: true}))) before.close();
      }
      focus(candidates().includes(document.activeElement) ? document.activeElement : candidates()[0]);
      describe(); return;
    }
    if (!current) {
      current = before.matches('dialog') ? items[0] : document.getElementById('controls-launch');
      focus(current);
      if (name !== 'ok' || before.matches('dialog')) { describe(); return; }
    }
    if (name === 'ok') {
      if (editing) clearEdit();
      else if (editable(current)) { editing = current; current.classList.add('wheel-editing'); }
      else if (textInput(current)) openKeyboard(current);
      else if (current.matches('input[type="color"]')) openColor(current);
      else if (current.matches('input[type="file"]')) { openFiles(current); return; }
      else if (current.matches('[data-gauge-slot]')) current.dispatchEvent(new Event('gauge-hold'));
      else if (current.matches('input[type="date"], input[type="time"]')) { message('Use a keyboard for dates and times'); return; }
      else current.click();
      // Newly opened dialogs get a stable starting point, then Up/Down visits every control.
      const after = scope();
      if (after !== before) {
        const start = candidates().find(el => el.hasAttribute('data-wheel-start'));
        const tab = candidates().find(el => el.getAttribute('aria-selected') === 'true');
        focus(start || tab || candidates()[0]);
      } else if (!visible(current)) focus(candidates()[0]);
    } else if (editing) adjust(editing, ['up', 'right'].includes(name) ? 1 : -1);
    else {
      const tablist = current.closest('[role="tablist"]');
      if (current.matches('[role="tab"]') && tablist) {
        const vertical = tablist.getAttribute('aria-orientation') === 'vertical';
        if ((vertical ? ['up', 'down'] : ['left', 'right']).includes(name)) {
          const tabs = [...tablist.querySelectorAll('[role="tab"]')].filter(visible);
          const step = ['up', 'left'].includes(name) ? -1 : 1;
          const next = tabs[(tabs.indexOf(current) + step + tabs.length) % tabs.length];
          next.click(); focus(next); describe(); return;
        }
        if (name === (vertical ? 'right' : 'down')) {
          const panel = document.getElementById(current.getAttribute('aria-controls'));
          const first = panel && [...panel.querySelectorAll(selector)].find(visible);
          if (first) { focus(first); describe(); return; }
        }
      }
      const grid = current.closest('[data-wheel-grid]');
      const neighbour = grid && spatial([...grid.querySelectorAll(selector)].filter(visible), current, name);
      if (neighbour) { focus(neighbour); describe(); return; }
      const index = items.indexOf(current), step = ['up', 'left'].includes(name) ? -1 : 1;
      focus(items[(index + step + items.length) % items.length]);
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
  function cancelEnter() { clearTimeout(enterTimer); enterAt = null; }
  document.addEventListener('visibilitychange', () => { cancelEnter(); clearEdit(); });
  window.addEventListener('blur', cancelEnter);
  document.addEventListener('keydown', event => {
    // After a touch/click, use the browser's normal slider/select/number keys.
    if (event.target === nativeInput && !editing && event.key !== 'Escape') return;
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || textInput(event.target)) return;
    const name = {ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Escape: 'back'}[event.key];
    if (!name && event.key !== 'Enter') return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (name) { if (name !== 'back' || !event.repeat) action(name); return; }
    if (event.repeat || enterAt !== null) return;
    enterAt = performance.now();
    enterTimer = setTimeout(() => { if (enterAt !== null) { action('back'); enterAt = -1; } }, 800);
  }, true);
  document.addEventListener('keyup', event => {
    if (event.key !== 'Enter' || enterAt === null) return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (enterAt >= 0) action('ok');
    cancelEnter();
  }, true);
})();
