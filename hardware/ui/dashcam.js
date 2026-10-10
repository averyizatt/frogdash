/* Wi-Fi dash cam view. Opens from the Dashcam button; never sends vehicle commands.
   A stalled or missing feed is shown as DASHCAM OFFLINE, never as a frozen live image. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const dialog = $('dashcam-dialog'), feed = $('dashcam-feed');
  const demo = () => typeof FrogdashDemoSocket !== 'undefined' || location.protocol === 'file:';
  let status = null, pollTimer = null, retryTimer = null, openedAt = 0, side = 'front', busy = false;
  // Reverse view: the dash cam's rear camera opens in reverse when no Pi camera is fitted.
  const KEY = 'frogdash.dashcam.v1';
  let prefs = {auto: true, mirror: true}, enabled = false, csiCamera = false, reversing = false, openedForReverse = false, sideBeforeReverse = 'front';
  // The dash keeps the rear picture arriving in the background, so reverse shows at once.
  // The Dashcam button opens the side last chosen by hand.
  let warm = true, manualSide = 'front';
  try { const saved = JSON.parse(localStorage.getItem(KEY)); if (saved) prefs = {auto: saved.auto !== false, mirror: saved.mirror !== false}; } catch { /* Defaults. */ }
  function savePrefs() { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* Session only. */ } renderSide(); }

  function setLost(lost, detail = '') {
    $('dashcam-lost').hidden = !lost;
    $('dashcam-lost-detail').textContent = detail;
    dialog.dataset.lost = String(lost);
  }
  function renderSide() {
    $('dashcam-front').setAttribute('aria-pressed', String(side === 'front'));
    $('dashcam-rear').setAttribute('aria-pressed', String(side === 'rear'));
    $('dashcam-state').textContent = openedForReverse ? 'REVERSE · DASH CAM REAR' : `DASHCAM · ${side.toUpperCase()}`;
    $('dashcam-mirror').setAttribute('aria-pressed', String(prefs.mirror));
    $('dashcam-auto').checked = prefs.auto;
    dialog.dataset.mirror = String(prefs.mirror && side === 'rear');
  }
  function connectFeed() {
    clearTimeout(retryTimer);
    feed.hidden = true; // Shown on the first frame, so no broken-image icon appears.
    feed.src = `/dashcam/stream?t=${Date.now()}`;
  }
  async function poll() {
    try {
      status = await (await fetch('/dashcam/status', {cache: 'no-store'})).json();
    } catch { status = null; }
    if (status && typeof status.keep_warm === 'boolean') { warm = status.keep_warm; $('dashcam-warm').checked = warm; }
    if (!dialog.open) return;
    if (status?.held) { feed.hidden = true; setLost(true, status.held); $('dashcam-status').textContent = 'Cameras off'; return; }
    const age = status?.frame_age_ms;
    // Live mode, RTSP and ffmpeg take a few seconds to deliver the first frame.
    if (!status) setLost(true, 'Dash service unreachable');
    else if (age != null && age < 1500) {
      setLost(false); feed.hidden = false;
      $('dashcam-status').textContent = `Live · ${status.fps} fps`;
    } else if (age == null) {
      const waiting = performance.now() - openedAt < 8000;
      setLost(!waiting, status.error || 'No picture yet: check the dash cam is on and the Pi is on its Wi-Fi');
      $('dashcam-status').textContent = waiting ? 'Starting live view…' : 'No picture';
    } else {
      setLost(true, status.error || 'Picture stopped: reconnecting');
      if (!status.running) { clearTimeout(retryTimer); retryTimer = setTimeout(connectFeed, 1000); }
    }
  }
  function open() {
    if (dialog.open) return;
    openedAt = performance.now();
    setLost(false); renderSide();
    $('dashcam-status').textContent = 'Starting live view…';
    dialog.showModal();
    if (demo()) { feed.hidden = true; setLost(true, 'The preview has no dash cam'); $('dashcam-status').textContent = 'Not available in the preview'; return; }
    connectFeed();
    clearInterval(pollTimer); pollTimer = setInterval(poll, 1000);
  }
  function close() {
    clearInterval(pollTimer); clearTimeout(retryTimer);
    feed.removeAttribute('src'); // Ends the stream so the dash cam's live mode can stop.
    if (dialog.open) dialog.close();
    if (openedForReverse) {
      openedForReverse = false;
      // While the picture is kept ready the dash stays on the rear camera for the next reverse.
      if (warm) { side = 'rear'; renderSide(); } else choose(sideBeforeReverse);
    }
  }
  async function choose(next, force = false) {
    if (busy || (!force && next === side)) return;
    busy = true;
    const previous = side;
    side = next; renderSide();
    try {
      if (!demo()) {
        const response = await fetch('/dashcam/side', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({side})});
        if (!response.ok) throw new Error(await response.text());
      }
    } catch (error) {
      side = previous; renderSide();
      $('dashcam-status').textContent = `${error.message || 'Could not switch camera'}`.slice(0, 120);
    } finally { busy = false; }
  }
  feed.addEventListener('error', () => { if (dialog.open && !demo()) { feed.hidden = true; setLost(true, 'Stream interrupted: reconnecting'); retryTimer = setTimeout(connectFeed, 2000); } });
  feed.addEventListener('load', () => { feed.hidden = false; });
  // The dash may have returned to the rear camera since this view was last open: ask again.
  $('dashcam-launch').onclick = () => { open(); if (!demo()) choose(manualSide, true); };
  $('dashcam-close').onclick = close;
  dialog.addEventListener('close', close);
  $('dashcam-front').onclick = () => { if (!openedForReverse) manualSide = 'front'; choose('front'); };
  $('dashcam-rear').onclick = () => { if (!openedForReverse) manualSide = 'rear'; choose('rear'); };
  $('dashcam-warm').onchange = async event => {
    warm = event.target.checked;
    if (demo()) return;
    try {
      const response = await fetch('/dashcam/warm', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: warm})});
      if (!response.ok) throw new Error();
    } catch { warm = !warm; event.target.checked = warm; $('dashcam-status').textContent = 'Could not change the setting'; }
  };
  async function detect() {
    if (demo()) return;
    try {
      const s = await (await fetch('/dashcam/status', {cache: 'no-store'})).json();
      $('dashcam-launch').hidden = !s.enabled;
      enabled = !!s.enabled;
      try { csiCamera = !!(await (await fetch('/camera/status', {cache: 'no-store'})).json()).enabled; } catch { csiCamera = false; }
      if (s.side) { side = s.side; renderSide(); }
      if (typeof s.keep_warm === 'boolean') { warm = s.keep_warm; $('dashcam-warm').checked = warm; }
    } catch { setTimeout(detect, 5000); }
  }
  detect();
  $('dashcam-mirror').onclick = () => { prefs.mirror = !prefs.mirror; savePrefs(); };
  $('dashcam-auto').onchange = event => { prefs.auto = event.target.checked; savePrefs(); };
  window.addEventListener('frogdash-state', ({detail}) => {
    const value = detail.snapshot.values?.['lighting.reverse'];
    const now = detail.connected && value?.quality === 'live' && value.value === true;
    if (now === reversing) return;
    reversing = now;
    if (demo() || !enabled || csiCamera || !prefs.auto) return;
    if (reversing) {
      if (!dialog.open) { openedForReverse = true; sideBeforeReverse = side; }
      choose('rear', true); open(); renderSide();
    } else if (openedForReverse) close();
  });
  window.FrogdashDashcam = {open, close};
})();
