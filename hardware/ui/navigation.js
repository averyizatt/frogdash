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
    message(editing ? 'EDIT: arrows change value | OK done | Hold OK back' : 'WHEEL: arrows move | OK select | Hold OK back');
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
      try { direction > 0 ? el.stepUp() : el.stepDown(); } catch { return; }
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
      else if (textInput(current) || current.matches('input[type="file"], input[type="color"], input[type="date"], input[type="time"]')) {
        message('Use touch or a keyboard for text, files and color pickers'); return;
      } else current.click();
      // Newly opened dialogs get a stable starting point, then Up/Down visits every control.
      const after = scope();
      if (after !== before) {
        const tab = candidates().find(el => el.getAttribute('aria-selected') === 'true');
        focus(tab || candidates()[0]);
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
