/* On-screen keyboard, for the dash's screen with only a mouse or a finger: it comes up
   when a text field (a Wi-Fi password, the Terminal, a show text) is clicked or tapped,
   types into that field, and goes away with Done, Escape or a click elsewhere. A real
   keyboard keeps working as before. A field opts out with data-no-osk. */
(() => {
  const FIELDS = 'input[type="text"], input[type="password"], input[type="search"], input:not([type]), textarea';
  const ROWS = {
    lower: ['1234567890', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm'],
    upper: ['1234567890', 'QWERTYUIOP', 'ASDFGHJKL', 'ZXCVBNM'],
    symbols: ['1234567890', '!@#$%^&*()', "-_=+[]{};:'", '"\\|,.<>/?`~'],
  };
  const pad = document.createElement('div');
  pad.id = 'osk'; pad.className = 'osk'; pad.hidden = true;
  pad.setAttribute('role', 'group'); pad.setAttribute('aria-label', 'On-screen keyboard');
  const popover = typeof pad.showPopover === 'function';
  if (popover) pad.setAttribute('popover', 'manual');   // The top layer: above the open dialog
  let target = null, layout = 'lower', pointerAt = 0, pointed = null;

  function key(label, action, wide) {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = label; button.dataset.key = action;
    if (wide) button.dataset.wide = wide;
    button.tabIndex = -1;
    return button;
  }
  function draw() {
    const rows = ROWS[layout].map((letters, i) => {
      const row = document.createElement('div'); row.className = 'osk-row';
      if (i === 3) row.append(key(layout === 'symbols' ? 'ABC' : layout === 'upper' ? '⇧ ABC' : '⇧', layout === 'symbols' ? 'letters' : 'shift', 'shift'));
      for (const letter of letters) row.append(key(letter, letter));
      if (i === 3) row.append(key('⌫', 'backspace', 'shift'));
      return row;
    });
    const last = document.createElement('div'); last.className = 'osk-row';
    last.append(key(layout === 'symbols' ? 'ABC' : '?123', layout === 'symbols' ? 'letters' : 'symbols', 'mode'),
      key('◀', 'left'), key('space', ' ', 'space'), key('▶', 'right'), key('Enter', 'enter', 'mode'), key('Done', 'done', 'done'));
    pad.replaceChildren(...rows, last);
  }
  function emit() { target.dispatchEvent(new Event('input', {bubbles: true})); }
  function type(text) {
    const start = target.selectionStart ?? target.value.length, end = target.selectionEnd ?? start;
    const limit = target.maxLength > 0 ? target.maxLength : Infinity;
    if (target.value.length - (end - start) + text.length > limit) return;
    target.setRangeText(text, start, end, 'end');
    emit();
  }
  function press(action) {
    if (!target) return;
    if (action === 'done') return close();
    if (action === 'shift') { layout = layout === 'upper' ? 'lower' : 'upper'; return draw(); }
    if (action === 'symbols' || action === 'letters') { layout = action === 'symbols' ? 'symbols' : 'lower'; return draw(); }
    const start = target.selectionStart ?? target.value.length, end = target.selectionEnd ?? start;
    if (action === 'backspace') {
      if (start !== end) target.setRangeText('', start, end, 'end');
      else if (start > 0) target.setRangeText('', start - 1, start, 'end');
      return emit();
    }
    if (action === 'left' || action === 'right') {
      const at = Math.max(0, Math.min(target.value.length, (action === 'left' ? Math.min(start, end) - (start === end) : Math.max(start, end) + (start === end))));
      return target.setSelectionRange(at, at);
    }
    if (action === 'enter') {
      if (target.tagName === 'TEXTAREA') return type('\n');
      for (const kind of ['keydown', 'keypress', 'keyup']) target.dispatchEvent(new KeyboardEvent(kind, {key: 'Enter', code: 'Enter', bubbles: true}));
      return;
    }
    type(action);
    if (layout === 'upper') { layout = 'lower'; draw(); }   // A capital at a time, like a phone
  }
  function open(field) {
    target = field;
    layout = 'lower'; draw();
    // Inside the field's dialog, so the dialog's modality does not make the keys inert.
    const home = field.closest('dialog') || document.body;
    if (pad.parentElement !== home) home.append(pad);
    pad.hidden = false;
    if (popover && !pad.matches(':popover-open')) pad.showPopover();
    document.body.classList.add('osk-open');
    requestAnimationFrame(() => {
      // Keep the field above the keyboard.
      const covered = field.getBoundingClientRect().bottom - pad.getBoundingClientRect().top + 16;
      if (covered <= 0) return;
      for (let box = field.parentElement; box; box = box.parentElement) {
        const style = getComputedStyle(box);
        if (/(auto|scroll)/.test(style.overflowY) && box.scrollHeight > box.clientHeight) { box.scrollTop += covered; return; }
      }
      field.scrollIntoView({block: 'center'});
    });
  }
  function close() {
    if (popover && pad.matches(':popover-open')) pad.hidePopover();
    pad.hidden = true; target = null;
    document.body.classList.remove('osk-open');
  }
  // Keys never take the focus, so the field keeps its caret.
  pad.addEventListener('pointerdown', event => {
    event.preventDefault();
    const button = event.target.closest('button[data-key]');
    if (button) press(button.dataset.key);
  });
  pad.addEventListener('click', event => event.preventDefault());
  document.addEventListener('pointerdown', event => { pointerAt = performance.now(); pointed = event.target; }, true);
  document.addEventListener('focusin', event => {
    const field = event.target;
    if (!(field instanceof HTMLElement) || !field.matches(FIELDS) || field.closest('[data-no-osk]') || field.readOnly || field.disabled) return;
    // Only a click or tap on the field (or its label); reached with Tab on a real keyboard, no.
    const clicked = pointed instanceof Node && (field.contains(pointed) || pointed.closest?.('label')?.control === field);
    if (!clicked || performance.now() - pointerAt > 800) return;
    open(field);
  });
  // A click on a field that already has the focus (no focusin then) brings it up too.
  document.addEventListener('click', event => {
    const field = event.target instanceof Element ? event.target.closest(FIELDS) : null;
    if (field && field !== target && document.activeElement === field && !field.closest('[data-no-osk]') && !field.readOnly && !field.disabled) open(field);
  }, true);
  document.addEventListener('focusout', event => {
    if (target && event.target === target && !pad.contains(event.relatedTarget)) setTimeout(() => { if (target && document.activeElement !== target) close(); }, 0);
  });
  document.addEventListener('keydown', event => { if (target && event.key === 'Escape') close(); }, true);
  window.FrogdashKeyboard = {open, close, get target() { return target; }};
})();
