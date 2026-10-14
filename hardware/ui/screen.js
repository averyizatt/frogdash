/* The screen mode (tools/frogdash_screen.py, through /screen): try exact 1920 x 720, keep
   it, or go back to the screen's own modes. Trying restarts the Pi into a one-time trial;
   the dash then asks whether the picture is right, and without an answer the Pi goes back
   by itself. Not in the preview: there is no Pi behind it. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const columns = document.querySelector('[data-ops-panel="support"] .ops-columns');
  if (!columns) return;
  columns.firstElementChild.insertAdjacentHTML('beforeend',
    '<div class="speaker-test" id="screen-row" hidden><div><span>Screen mode</span><small id="screen-status">Checking…</small></div>' +
    '<div class="speaker-test-buttons"><button type="button" id="screen-try">Try exact 1920 × 720</button>' +
    '<button type="button" id="screen-back" hidden>Use the screen’s own modes</button></div></div>');
  const dialog = document.createElement('dialog');
  dialog.id = 'screen-trial';
  dialog.className = 'screen-trial';
  dialog.setAttribute('aria-labelledby', 'screen-trial-title');
  dialog.innerHTML = '<h2 id="screen-trial-title">Is the dash showing properly?</h2>' +
    '<p>The Pi is trying exact 1920 × 720. If the whole dash fits the screen and looks sharp, keep it.</p>' +
    '<p class="screen-trial-count" id="screen-trial-count" role="status"></p>' +
    '<div class="screen-trial-buttons"><button type="button" id="screen-keep">KEEP 1920 × 720</button>' +
    '<button type="button" id="screen-undo">Go back now</button></div>';
  document.body.append(dialog);

  let status = null, armed = '', armTimer = null, timer = null, note = '', noteUntil = 0;
  const busy = () => status && (status.pending || ['restarting', 'trial', 'reverting'].includes(status.state));

  // What the Pi sees on its HDMI ports, in a few words.
  function screens(s) {
    return (s.connectors || []).filter(c => c.status === 'connected').map(c => {
      const sees = c.edid_ok ? (c.panel_1920x720 ? '' : ', none of them 1920 × 720') : ', its own description cannot be read';
      return `${c.name}: ${c.mode_count} mode${c.mode_count === 1 ? '' : 's'}${sees}`;
    }).join(' · ');
  }

  function render() {
    const row = $('screen-row');
    row.hidden = !status;
    if (!status) return;
    const extra = [screens(status), (status.boot_time || [])[0], (status.first_render || [])[0]?.replace(/^.*Frogdash kiosk: /, 'Dash: ')]
      .filter(Boolean).join(' · ');
    const text = Date.now() < noteUntil ? note : status.pending ? 'Waiting for the screen helper… (is frogdash-screen.path enabled?)' : status.message;
    $('screen-status').textContent = armed ? $('screen-status').textContent : `${text}${extra ? ` · ${extra}` : ''}`;
    $('screen-try').hidden = !!status.applied;
    $('screen-back').hidden = !status.applied;
    $('screen-try').disabled = $('screen-back').disabled = busy();
    if (!armed) {
      $('screen-try').textContent = 'Try exact 1920 × 720';
      $('screen-back').textContent = 'Use the screen’s own modes';
    }
    // The question during a trial, over everything else.
    if (status.state === 'trial') {
      if (!dialog.open) { dialog.showModal(); $('screen-keep').focus(); }
      const left = Math.max(0, Math.round((status.started || 0) + (status.deadline_s || 60) - Date.now() / 1000));
      $('screen-trial-count').textContent = status.pending ? 'Answer sent…' : `Without an answer it goes back by itself in ${left} s.`;
      $('screen-keep').disabled = $('screen-undo').disabled = !!status.pending;
    } else if (dialog.open) dialog.close();
  }

  async function poll() {
    clearTimeout(timer);
    try {
      const response = await fetch('/screen', {cache: 'no-store'});
      status = response.ok ? await response.json() : null;
    } catch { status = status && busy() ? status : null; }
    render();
    timer = setTimeout(poll, busy() ? 1000 : 20000);
  }

  async function ask(action) {
    try {
      const response = await fetch('/screen', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action})});
      if (!response.ok) { note = (await response.text()).slice(0, 160); noteUntil = Date.now() + 6000; }
    } catch { note = 'The dash did not answer'; noteUntil = Date.now() + 6000; }
    poll();
  }

  // Trying and going back restart the Pi: two presses, like installing firmware.
  function twoPress(button, action, warning) {
    button.onclick = () => {
      if (armed !== action) {
        armed = action; button.textContent = 'Press again';
        $('screen-status').textContent = warning;
        clearTimeout(armTimer); armTimer = setTimeout(() => { armed = ''; render(); }, 6000);
        return;
      }
      armed = ''; clearTimeout(armTimer);
      ask(action);
    };
  }
  twoPress($('screen-try'), 'trial', 'The dash restarts to try it. If the screen stays dark, wait: it goes back by itself within two minutes. Press again to try.');
  twoPress($('screen-back'), 'revert', 'The dash restarts with the screen’s own modes. Press again to go back.');
  $('screen-keep').onclick = () => ask('keep');
  $('screen-undo').onclick = () => ask('revert');
  dialog.addEventListener('cancel', event => event.preventDefault());   // Escape is not an answer.
  window.FrogdashScreen = {poll};
  poll();
})();
