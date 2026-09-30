/* Reverse camera view. Opens on the CAN reverse signal; never sends vehicle commands.
   A stalled or missing feed is shown as CAMERA LOST, never as a frozen live image. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const key = 'frogdash.camera.v1';
  const guideDefaults = {width: 70, taper: 45, reach: 55, offset: 0};
  const defaults = {auto: true, mirror: true, guides: true, linger: 0, ...guideDefaults};
  const ranges = {width: [20, 100], taper: [20, 90], reach: [20, 85], offset: [-25, 25]};
  let prefs = {...defaults};
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    if (saved && typeof saved === 'object') {
      for (const field of ['auto', 'mirror', 'guides']) if (typeof saved[field] === 'boolean') prefs[field] = saved[field];
      if ([0, 3, 5, 10].includes(saved.linger)) prefs.linger = saved.linger;
      for (const [field, [lo, hi]] of Object.entries(ranges)) if (Number.isFinite(saved[field])) prefs[field] = Math.max(lo, Math.min(hi, saved[field]));
    }
  } catch { /* Defaults stay usable. */ }
  const dialog = $('camera-dialog'), feed = $('camera-feed'), demoCanvas = $('camera-demo');
  let latest = {}, connected = false, demo = false, available = false, checked = false;
  let reason = null, wasReverse = false, closeTimer = null, pollTimer = null, retryTimer = null, openedAt = 0, animation = null;

  function save() {
    try { localStorage.setItem(key, JSON.stringify(prefs)); } catch { /* Applied for this session. */ }
    render();
  }
  function drawGuides() {
    const svg = $('camera-guides'); svg.replaceChildren();
    svg.hidden = !prefs.guides;
    const ns = 'http://www.w3.org/2000/svg', center = 500 + prefs.offset * 10, bottom = prefs.width * 5, top = bottom * prefs.taper / 100;
    const at = t => [1000 - prefs.reach * 10 * t, bottom + (top - bottom) * t];
    [['near', 0, 1 / 3], ['mid', 1 / 3, 2 / 3], ['far', 2 / 3, 1]].forEach(([band, t0, t1]) => {
      const [y0, h0] = at(t0), [y1, h1] = at(t1);
      for (const side of [-1, 1]) {
        const line = document.createElementNS(ns, 'line');
        Object.entries({x1: center + side * h0, y1: y0, x2: center + side * h1, y2: y1, class: `guide ${band}`}).forEach(([k, v]) => line.setAttribute(k, v));
        svg.append(line);
        const tick = document.createElementNS(ns, 'line');
        Object.entries({x1: center + side * h1, y1: y1, x2: center + side * h1 * .78, y2: y1, class: `guide ${band}`}).forEach(([k, v]) => tick.setAttribute(k, v));
        svg.append(tick);
      }
    });
  }
  function render() {
    dialog.dataset.mirror = String(prefs.mirror);
    $('camera-guides-toggle').setAttribute('aria-pressed', String(prefs.guides));
    $('camera-mirror-toggle').setAttribute('aria-pressed', String(prefs.mirror));
    $('camera-auto').checked = prefs.auto;
    $('camera-linger').value = prefs.linger;
    for (const field of Object.keys(ranges)) { $(`camera-${field}`).value = prefs[field]; $(`camera-${field}-value`).textContent = field === 'offset' ? `${prefs[field] > 0 ? '+' : ''}${prefs[field]}` : `${prefs[field]}%`; }
    $('camera-launch').hidden = !available;
    drawGuides();
  }

  function setLost(lost, detail = '') {
    $('camera-lost').hidden = !lost;
    $('camera-lost-detail').textContent = detail || 'Check mirrors and surroundings';
    dialog.dataset.lost = String(lost);
  }
  function connectFeed() {
    clearTimeout(retryTimer);
    feed.hidden = demo;
    feed.src = `/camera/stream?t=${Date.now()}`;
  }
  async function poll() {
    if (!dialog.open || demo) return;
    let status;
    try {
      const response = await fetch('/camera/status', {cache: 'no-store', signal: AbortSignal.timeout(1500)});
      status = await response.json();
    } catch { status = null; }
    if (!dialog.open) return;
    const age = status?.frame_age_ms;
    if (!status || !status.enabled) setLost(true, 'Camera service unavailable');
    else if (status.error && !status.running) setLost(true, status.error);
    else if (age == null) setLost(performance.now() - openedAt > 3000, 'Waiting for the first frame');
    else if (age > 1000) setLost(true, `No new frame for ${(age / 1000).toFixed(1)} s`);
    else { setLost(false); $('camera-state').textContent = `REAR CAMERA · ${Math.round(status.fps)} FPS`; }
    if (status?.width && status?.height) document.querySelector('.camera-stage').style.aspectRatio = `${status.width} / ${status.height}`;
    if (dialog.dataset.lost === 'true' && performance.now() - openedAt > 3000 && !retryTimer) retryTimer = setTimeout(() => { retryTimer = null; if (dialog.open) connectFeed(); }, 2000);
  }
  // A failed stream hides the broken image and asks the service for the actual reason.
  feed.addEventListener('error', () => { if (dialog.open && !demo) { feed.hidden = true; setLost(true, 'Camera stream interrupted'); poll(); } });

  function drawDemo(now) {
    const ctx = demoCanvas.getContext('2d'), w = demoCanvas.width, h = demoCanvas.height, t = now / 1000;
    const sky = ctx.createLinearGradient(0, 0, 0, h); sky.addColorStop(0, '#39424d'); sky.addColorStop(.38, '#5b636b'); sky.addColorStop(.4, '#3a3d40'); sky.addColorStop(1, '#23262a');
    ctx.fillStyle = sky; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#1a1c1f'; ctx.fillRect(0, h * .3, w, h * .1);
    for (let i = 0; i < 6; i++) { ctx.fillStyle = ['#6b2a2a', '#2c3e57', '#555', '#3e5a3a', '#6a6a70', '#2a2a2e'][i]; ctx.fillRect(20 + i * 110, h * .29, 90, h * .09); }
    ctx.strokeStyle = '#d8d3c4'; ctx.lineWidth = 3;
    for (const x of [-1.3, -.45, .45, 1.3]) { ctx.beginPath(); ctx.moveTo(w / 2 + x * 80, h * .4); ctx.lineTo(w / 2 + x * 420, h); ctx.stroke(); }
    const approach = (Math.sin(t / 3) + 1) / 2, cone = h * (.5 + approach * .35), size = 18 + approach * 40;
    ctx.fillStyle = '#ff7a1a'; ctx.beginPath(); ctx.moveTo(w * .62, cone - size); ctx.lineTo(w * .62 - size * .4, cone); ctx.lineTo(w * .62 + size * .4, cone); ctx.fill();
    animation = requestAnimationFrame(drawDemo);
  }

  function open(why) {
    clearTimeout(closeTimer); closeTimer = null;
    reason = why;
    if (dialog.open) return;
    openedAt = performance.now();
    demoCanvas.hidden = !demo; feed.hidden = demo;
    setLost(false);
    $('camera-state').textContent = demo ? 'REAR CAMERA · SIMULATED' : 'REAR CAMERA · CONNECTING';
    $('camera-settings').hidden = true; $('camera-settings-toggle').setAttribute('aria-expanded', 'false');
    dialog.showModal();
    if (demo) animation = requestAnimationFrame(drawDemo);
    else { connectFeed(); poll(); pollTimer = setInterval(poll, 500); }
    update();
  }
  function close() {
    clearTimeout(closeTimer); clearTimeout(retryTimer); clearInterval(pollTimer);
    closeTimer = retryTimer = pollTimer = null; reason = null;
    cancelAnimationFrame(animation);
    feed.removeAttribute('src'); // Ends the stream so the Pi can stop the camera.
    if (dialog.open) dialog.close();
  }
  dialog.addEventListener('close', () => { if (reason) close(); });

  function update() {
    const value = latest.values?.['vehicle.speed_kph'];
    const speed = connected && value?.quality === 'live' && Number.isFinite(value.value) ? value.value : null;
    $('camera-speed').textContent = speed === null ? '—' : Math.round(window.FrogdashUnits.distance(speed));
    $('camera-speed-unit').textContent = window.FrogdashUnits.speedUnit;
    const banner = $('warn-banner');
    $('camera-warning').hidden = banner.hidden; $('camera-warning').textContent = banner.textContent;
    return speed;
  }
  window.addEventListener('frogdash-state', event => {
    latest = event.detail.snapshot; connected = event.detail.connected;
    demo = latest.mode === 'demo';
    if (demo && !available) { available = true; render(); }
    if (!demo && !checked) {
      checked = true;
      fetch('/camera/status', {cache: 'no-store'}).then(r => r.json()).then(s => { available = !!s.enabled; render(); }).catch(() => {});
    }
    const signal = latest.values?.['lighting.reverse'];
    const reverse = connected && signal?.quality === 'live' && signal.value === true;
    if (reverse && !wasReverse && prefs.auto && available) open('reverse');
    if (reverse && dialog.open) { clearTimeout(closeTimer); closeTimer = null; }
    if (!reverse && wasReverse && reason === 'reverse' && !closeTimer) closeTimer = setTimeout(close, prefs.linger * 1000);
    const speed = dialog.open ? update() : null;
    // A manually opened view must not keep covering the gauges once the car is driving forward.
    if (reason === 'manual' && !reverse && speed !== null && speed > 16) close();
    wasReverse = reverse;
  });

  // Dash management > Support & testing: camera status and a test view that does not need reverse.
  const support = document.querySelector('[data-ops-panel="support"] .ops-columns');
  support.firstElementChild.insertAdjacentHTML('beforeend', '<div class="setting-card camera-test" data-state="unknown"><div><span>Reverse camera</span><strong id="camera-test-status">Checking…</strong><small id="camera-test-detail">Opens without reverse, for aiming the camera and setting guides.</small></div><button id="camera-test" type="button">Open camera test</button></div>');
  async function testStatus() {
    const card = document.querySelector('.camera-test');
    if (!card?.checkVisibility()) return;
    let text, detail, state;
    if (demo) [state, text, detail] = ['good', 'Simulated', 'Preview uses a simulated camera image.'];
    else {
      let s = null;
      try { s = await (await fetch('/camera/status', {cache: 'no-store', signal: AbortSignal.timeout(1500)})).json(); } catch { /* Reported below. */ }
      if (!s) [state, text, detail] = ['warning', 'Service unreachable', 'The Frogdash backend did not answer.'];
      else if (!s.enabled) [state, text, detail] = ['off', 'Not enabled', 'Add --camera to FROGDASH_ARGS in /etc/default/frogdash, then restart frogdash.service. See docs/reverse-camera.md.'];
      else if (s.error && !s.running) [state, text, detail] = ['warning', 'Camera error', s.error];
      else if (s.running) [state, text, detail] = ['good', `Running · ${Math.round(s.fps)} fps`, `${s.width}×${s.height}${s.rotate ? ' · rotated 180°' : ''} · ${s.viewers} viewer${s.viewers === 1 ? '' : 's'}`];
      else [state, text, detail] = ['good', 'Ready', `${s.width}×${s.height} · starts when a view opens`];
    }
    card.dataset.state = state;
    $('camera-test-status').textContent = text;
    $('camera-test-detail').textContent = detail;
    $('camera-test').disabled = state === 'off';
  }
  setInterval(testStatus, 2000);
  new MutationObserver(testStatus).observe(document.querySelector('[data-ops-panel="support"]'), {attributes: true, attributeFilter: ['hidden']});
  $('camera-test').onclick = () => open('manual');
  $('camera-launch').onclick = () => open('manual');
  $('camera-close').onclick = close;
  $('camera-guides-toggle').onclick = () => { prefs.guides = !prefs.guides; save(); };
  $('camera-mirror-toggle').onclick = () => { prefs.mirror = !prefs.mirror; save(); };
  $('camera-settings-toggle').onclick = () => {
    const show = $('camera-settings').hidden;
    $('camera-settings').hidden = !show; $('camera-settings-toggle').setAttribute('aria-expanded', String(show));
  };
  $('camera-auto').onchange = event => { prefs.auto = event.target.checked; save(); };
  $('camera-linger').onchange = event => { prefs.linger = Number(event.target.value); save(); };
  for (const field of Object.keys(ranges)) $(`camera-${field}`).addEventListener('input', event => { prefs[field] = Number(event.target.value); save(); });
  $('camera-guides-reset').onclick = () => { Object.assign(prefs, guideDefaults); save(); };
  window.FrogdashCamera = {open, close, get prefs() { return {...prefs}; }};
  render();
})();
