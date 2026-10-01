/* Taillight settings over CAN (can_protocol.h extension 3): styles, colors, timing,
   show text, profiles and save/revert/defaults. Values shown are the controller's own
   reported settings (0x103 reports), so they always reflect what the lamps will do.
   Changes apply live; Save stores them in the controller's flash. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const send = (action, value) => window.FrogdashControls?.send(action, value);
  // can_protocol.h taillight_setting keys, matching the firmware's own web UI labels.
  const STYLES = [
    ['brake_anim', 12, 'Brake', ['Solid fill', 'Pulse / breathe', 'Center-out fill', 'Strobe flash', 'Outer-in fill', 'Heartbeat', 'Edge lock']],
    ['turn_anim', 13, 'Turn signal', ['Sequential sweep', 'Simple flash', 'Group chase', 'Bounce sweep', 'Split out', 'Fast chase', 'Arrowhead sweep', 'Three-bar relay']],
    ['reverse_anim', 14, 'Reverse', ['Solid', 'Pulse / breathe', 'Sparkle', 'Scanner']],
    ['run_anim', 15, 'Running light', ['Dim solid', 'Breathe', 'Shimmer', 'Slow comet', 'Contour glide', 'Fox louvers']],
    ['lens_preset', 16, 'Taillight style', ['Full panel', 'GT cheese grater (87-93 GT)', 'LX / base (87-93 LX)', 'Cobra bar']],
    ['turn_custom', 4, 'Turn timing', ['Simple: equal on / off', 'Custom: sweep / hold / off']],
  ];
  const TOGGLES = [['startup_anim', 17, 'Startup animation'], ['rest_mode', 18, 'Rest mode (dim running light when parked)']];
  const NUMBERS = [
    ['brightness', 1, 'Saved brightness', 10, 255, 5, ''], ['brightness_dim', 2, 'Running light level', 5, 35, 1, '%'],
    ['turn_blink_ms', 3, 'Blink period', 200, 1500, 50, 'ms'], ['turn_sweep_ms', 5, 'Sweep time', 50, 1500, 50, 'ms'],
    ['turn_hold_ms', 6, 'Hold time', 0, 1500, 50, 'ms'], ['turn_off_ms', 7, 'Off time', 50, 1500, 50, 'ms'],
    ['brake_speed', 8, 'Brake animation speed', 50, 200, 5, '%'], ['reverse_speed', 9, 'Reverse animation speed', 50, 200, 5, '%'],
    ['run_speed', 10, 'Running animation speed', 50, 200, 5, '%'], ['show_speed', 19, 'Show speed', 50, 200, 5, '%'],
    ['frame_ms', 11, 'Frame time (lower = smoother)', 10, 100, 1, 'ms'],
  ];
  const COLORS = [['brake', 0, 'Brake'], ['turn', 1, 'Turn'], ['reverse', 2, 'Reverse'], ['running', 3, 'Running']];
  const ACTION = {save: 0, revert: 1, defaults: 2, report: 3, load: 4, store: 5, remove: 6};
  const ACK = {0: 'Done', 3: 'Adjusted to the allowed range', 4: 'Save to flash failed', 5: 'That profile slot is empty'};
  let latest = {}, confirmDefaults = 0, confirmDelete = null;

  const label = (text, control) => { const l = document.createElement('label'); l.className = 'tl-field'; l.append(text, control); return l; };
  const option = (value, text) => Object.assign(document.createElement('option'), {value, textContent: text});

  // ---- Style tab ----
  const style = $('tl-panel-style');
  style.innerHTML = '<p class="tl-sync control-note" data-tl-sync></p><h3>Animations</h3><div class="tl-grid" id="tl-style-grid"></div><h3>Options</h3><div class="tl-grid" id="tl-toggle-grid"></div><h3>Show text</h3>';
  for (const [name, key, text, choices] of STYLES) {
    const select = document.createElement('select');
    select.id = `tl-set-${name}`; select.dataset.setting = name; select.dataset.key = key;
    choices.forEach((choice, i) => select.append(option(i, choice)));
    $('tl-style-grid').append(label(text, select));
  }
  for (const [name, key, text] of TOGGLES) {
    const select = document.createElement('select');
    select.id = `tl-set-${name}`; select.dataset.setting = name; select.dataset.key = key;
    select.append(option(0, 'Off'), option(1, 'On'));
    $('tl-toggle-grid').append(label(text, select));
  }
  const textRow = document.createElement('div'); textRow.className = 'tl-pair';
  const textInput = Object.assign(document.createElement('input'), {id: 'tl-show-text', type: 'text', maxLength: 63, autocomplete: 'off', spellcheck: false});
  const textButton = Object.assign(document.createElement('button'), {type: 'button', textContent: 'APPLY TEXT'});
  textButton.dataset.action = 'lighting.text'; textButton.dataset.compute = 'text';
  textRow.append(label('Scrolling text for text shows', textInput), textButton);
  style.append(textRow);

  // ---- Colors & timing tab ----
  const colors = $('tl-panel-colors');
  colors.innerHTML = '<p class="tl-sync control-note" data-tl-sync></p><h3>Colors</h3><div class="tl-grid tl-colors" id="tl-color-grid"></div><h3>Levels and timing</h3><div class="tl-grid" id="tl-number-grid"></div><p class="control-note">Changes apply when you leave a field. Turn sweep, hold and off times are used when Turn timing is Custom.</p>';
  for (const [name, which, text] of COLORS) {
    const input = Object.assign(document.createElement('input'), {id: `tl-color-${name}`, type: 'color', value: '#ff0000'});
    input.dataset.color = which;
    $('tl-color-grid').append(label(text, input));
  }
  for (const [name, key, text, min, max, step, unit] of NUMBERS) {
    const input = Object.assign(document.createElement('input'), {id: `tl-set-${name}`, type: 'number', min, max, step, inputMode: 'numeric'});
    input.dataset.setting = name; input.dataset.key = key;
    $('tl-number-grid').append(label(`${text}${unit ? ` (${unit})` : ''}`, input));
  }

  // ---- Profiles tab ----
  const profiles = $('tl-panel-profiles');
  profiles.innerHTML = `<p class="tl-sync control-note" data-tl-sync></p>
    <h3>Current settings</h3><div class="control-row">
      <button type="button" data-action="lighting.action" data-compute="save">SAVE TO TAILLIGHTS</button>
      <button type="button" data-action="lighting.action" data-compute="revert">UNDO UNSAVED</button>
      <button type="button" class="stop-control" data-action="lighting.action" data-compute="defaults" id="tl-defaults">FACTORY DEFAULTS</button></div>
    <p class="control-note">Changes apply right away but are lost when the taillights power off until you save.</p>
    <h3>Profiles</h3><div class="tl-profiles" id="tl-profile-list"></div>
    <p id="tl-ack" class="control-note" role="status"></p>`;
  for (let slot = 0; slot < 6; slot++) {
    const row = document.createElement('div'); row.className = 'tl-profile'; row.dataset.slot = slot;
    row.innerHTML = `<strong>Profile ${slot + 1}</strong><span data-profile-state>—</span>
      <button type="button" data-action="lighting.action" data-compute="load">LOAD</button>
      <button type="button" data-action="lighting.action" data-compute="store">SAVE HERE</button>
      <button type="button" class="stop-control" data-action="lighting.action" data-compute="remove">DELETE</button>`;
    $('tl-profile-list').append(row);
  }

  // ---- Sending ----
  for (const control of document.querySelectorAll('#taillight-dialog [data-setting]')) control.addEventListener('change', () => {
    const value = Number(control.value);
    if (control.type === 'number' && (!control.reportValidity() || control.value === '')) return;
    send('lighting.setting', Number(control.dataset.key) * 65536 + value);
  });
  for (const input of document.querySelectorAll('#taillight-dialog [data-color]')) input.addEventListener('change', () => {
    send('lighting.color', Number(input.dataset.color) * 2 ** 24 + parseInt(input.value.slice(1), 16));
  });
  textButton.addEventListener('click', () => {
    const text = textInput.value.toUpperCase();
    if (/^[\x20-\x7E]{0,63}$/.test(text)) send('lighting.text', text);
  });
  for (const button of document.querySelectorAll('#taillight-dialog [data-action="lighting.action"]')) button.addEventListener('click', () => {
    const kind = button.dataset.compute, slot = Number(button.closest('[data-slot]')?.dataset.slot ?? 0);
    if (kind === 'defaults' && performance.now() - confirmDefaults > 4000) {
      confirmDefaults = performance.now(); button.textContent = 'PRESS AGAIN TO RESET'; return;
    }
    if (kind === 'remove' && (confirmDelete?.slot !== slot || performance.now() - confirmDelete.at > 4000)) {
      confirmDelete = {slot, at: performance.now()}; button.textContent = 'PRESS AGAIN'; return;
    }
    confirmDefaults = 0; confirmDelete = null;
    $('tl-defaults').textContent = 'FACTORY DEFAULTS';
    for (const del of document.querySelectorAll('#tl-profile-list [data-compute="remove"]')) del.textContent = 'DELETE';
    send('lighting.action', ACTION[kind] * 256 + slot);
  });

  // ---- Readback ----
  const editing = el => document.activeElement === el || el.classList.contains('wheel-editing');
  function render() {
    const tl = latest.taillight || {}, controls = latest.controls || {reasons: {}};
    const reason = controls.reasons['lighting.setting'];
    const sync = !tl.supported ? (reason || 'Taillight controller offline, or its firmware has no CAN settings')
      : !tl.complete ? 'Reading settings from the taillights…'
      : tl.unsaved ? 'Unsaved changes: they apply now, and are lost at power off until you Save (Profiles tab).'
      : 'Settings match the taillights. Changes apply immediately.';
    for (const note of document.querySelectorAll('#taillight-dialog [data-tl-sync]')) {
      note.textContent = sync; note.dataset.state = !tl.supported ? 'off' : tl.unsaved ? 'unsaved' : 'ok';
    }
    const ready = !!tl.supported && !!tl.complete;
    for (const control of document.querySelectorAll('#taillight-dialog [data-setting], #taillight-dialog [data-color], #tl-show-text')) control.disabled = !ready;
    const settings = tl.settings || {};
    for (const control of document.querySelectorAll('#taillight-dialog [data-setting]')) {
      const value = settings[control.dataset.setting];
      if (value != null && !editing(control) && String(control.value) !== String(value)) control.value = value;
    }
    for (const [name] of COLORS) {
      const input = $(`tl-color-${name}`), value = (tl.colors || {})[name];
      if (value && !editing(input) && input.value !== value) input.value = value;
    }
    if (tl.text != null && !editing(textInput) && textInput.dataset.shown !== tl.text) { textInput.value = tl.text; textInput.dataset.shown = tl.text; }
    (tl.profiles || []).forEach((used, slot) => {
      const row = document.querySelector(`#tl-profile-list [data-slot="${slot}"]`);
      row.querySelector('[data-profile-state]').textContent = used ? 'Saved' : 'Empty';
      row.dataset.used = String(used);
    });
    const ack = tl.last_ack;
    if (ack && ack.command === 9) $('tl-ack').textContent = ACK[ack.status] || 'The taillights rejected that request';
  }
  window.addEventListener('frogdash-state', event => {
    latest = event.detail.snapshot;
    if ($('taillight-dialog')?.open) render();
  });
})();
