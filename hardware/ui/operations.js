/* Commissioning and ownership tools. Uses the production APIs; demo stays local. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), u = window.FrogdashUnits;
  const keys = ['frogdash.appearance.v1', 'frogdash.driving.v1', 'frogdash.units.v1', 'frogdash.cluster.v1', 'frogdash.camera.v1'];
  const checks = {boot: 'Cold start: time until live gauges', crank: 'Cranking: power and display stay stable', gps_loss: 'Unplug GPS: speed becomes unavailable', can_loss: 'Disconnect CAN / modules: stale state visible', storage: 'Low storage: rotation and warnings verified', recording: 'Long drive: MLG opens in MegaLogViewer', display: 'Physical screen: touch, daylight and night', controls: 'Controller commands and readback checked'};
  let latest = {}, online = false, busy = false, pending = null, backlight = {};
  const simulated = {version: '0.4.0 preview', os: 'Simulated Raspberry Pi', maintenance: [], checks: {}, capabilities: []};
  const demo = () => latest.mode === 'demo';
  const status = () => demo() ? simulated : latest.operations || {};
  const parked = () => online && (demo() ? latest.values?.['vehicle.speed_kph']?.quality === 'live' && latest.values['vehicle.speed_kph'].value < 1 : status().parked === true);
  const canConfigure = () => online;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const dialog = el('dialog', null, 'workspace-dialog'); dialog.id = 'operations-dialog'; dialog.setAttribute('aria-labelledby', 'operations-title');
  dialog.innerHTML = `<header class="dialog-header"><div><span class="eyebrow">SETUP / SERVICE / SUPPORT</span><h2 id="operations-title">Dash management</h2><p id="operations-summary"></p></div><button id="demo-park" class="close-button" type="button" hidden>Park demo</button><button id="operations-close" class="close-button" type="button">Close ×</button></header>
    <div class="control-workspace"><nav class="control-tabs driver-tabs" aria-label="Management sections">
    ${[['setup','Setup checklist'],['service','Maintenance'],['backup','Backup & restore'],['display','Units & backlight'],['support','Support & testing'],['tune','TunerStudio'],['terminal','Terminal']].map(([key,label]) => `<button type="button" data-ops-tab="${key}" aria-selected="false">${label}</button>`).join('')}</nav>
    <div class="driver-panels">
      <section class="driver-panel ops-panel control-section" data-ops-panel="setup"><div class="ops-columns"><div class="setting-card"><h3>1 · Check connected hardware</h3><div id="setup-hardware"></div><p class="control-note">Live presence confirms data is arriving. Verify wiring, CAN oscillator/bitrate and sensor accuracy during commissioning.</p></div><div class="setting-card"><h3>2 · Complete calibration and display</h3><div id="setup-calibration"></div><p class="control-note">3 · Run the vehicle checks under Support & testing. Completion is recorded only when you mark a physical test passed.</p><button type="button" data-ops-go="support">Vehicle test checklist</button></div></div></section>
      <section class="driver-panel ops-panel control-section" data-ops-panel="service" hidden><div class="ops-columns"><form id="maintenance-form" class="setting-card ops-edit"><h3>Add a service reminder</h3><label>Service name<input id="maintenance-name" maxlength="60" required placeholder="Engine oil & filter"></label><div class="ops-fields"><label id="maintenance-distance-label">Distance · km<input id="maintenance-distance" type="number" min="0" max="100000" value="0" required></label><label>Engine hours<input id="maintenance-hours" type="number" min="0" max="10000" value="0" required></label><label>Days<input id="maintenance-days" type="number" min="0" max="3650" value="0" required></label></div><p class="control-note">Zero disables an interval. Due when any enabled interval is reached. Distance and engine hours count only while the dash receives live data; enter intervals remaining until your next service.</p><button type="submit">Add reminder</button></form><div class="setting-card ops-list" id="maintenance-list" aria-live="polite"></div></div></section>
      <section class="driver-panel ops-panel control-section" data-ops-panel="backup" hidden><div class="ops-columns"><div class="setting-card"><h3>One portable configuration file</h3><p class="control-note">Includes this display’s appearance, layouts and units, plus Pi alerts, fuel estimate settings, trip totals, economy history, race results and service records.</p><p class="control-note">Download recordings separately. Hotspot credentials and Linux configuration are not included.</p><button id="backup-download" type="button">Download backup</button><button id="profile-save" class="ops-edit" type="button">Save display profile to Pi</button><button id="profile-load" class="ops-edit" type="button">Use saved Pi display profile</button></div><div class="setting-card ops-edit"><h3>Review and restore</h3><label>Dash backup JSON<input id="backup-file" type="file" accept="application/json,.json"></label><p id="backup-review" class="control-note">Choose a file to review before replacing your settings.</p><button id="backup-restore" type="button" disabled>Restore reviewed backup</button><p class="control-note">Restore replaces counters and calibration. The display reloads. Manually entered fuel inventory must be reconfirmed afterward.</p></div></div></section>
      <section class="driver-panel ops-panel control-section" data-ops-panel="display" hidden><div class="ops-columns"><div class="setting-card ops-edit"><h3>Display units</h3><label>Road instruments<select id="units-system"><option value="us">US · MPH / °F / psi / US MPG</option><option value="metric">Metric · km/h / °C / kPa / L/100 km</option></select></label><p class="control-note">Changes gauges, trip, range and economy displays. Calibration, diagnostics and recorded channels retain their explicitly labelled engineering units.</p></div><form id="backlight-form" class="setting-card"><h3>Physical LCD backlight</h3><p id="backlight-status" class="control-note">Checking device support…</p><label>Brightness · %<input id="backlight-percent" type="number" min="10" max="100" value="80" required></label><button id="backlight-apply" type="submit" disabled>Apply to LCD</button><p class="control-note">Requires a selected, writable Linux backlight device. Day/night dimming under Drive remains a software display effect.</p></form></div></section>
      <section class="driver-panel ops-panel control-section" data-ops-panel="support" hidden><div class="ops-columns"><div class="setting-card"><h3>Support report</h3><p id="support-version" class="control-note"></p><button id="diagnostic-download" type="button">Download diagnostics</button><p class="control-note">Includes connection quality, CAN errors, GPS status, recorder and Pi health, fuel level quality. Excludes GPS coordinates, raw logs, Wi-Fi secrets and artwork.</p><div id="controller-capabilities" class="ops-capabilities"></div></div><div class="setting-card ops-list"><h3>Vehicle acceptance checks</h3><p class="control-note">Mark passed only after performing each test on the car. These are records, not automatic hardware certification.</p><div id="acceptance-list"></div></div></div></section>
    </div></div><footer class="command-result" id="operations-result" role="status">Connect to the dash service to save configuration.</footer>`;
  document.body.append(dialog);
  dialog.querySelector('[data-ops-panel="support"] .ops-columns').firstElementChild.insertAdjacentHTML('beforeend',
    '<div class="speaker-test"><div><span>Speaker test</span><small id="speaker-test-status">Uses the chime volume from Drive &gt; Alerts.</small></div>' +
    '<div class="speaker-test-buttons">' + [['left', 'Left'], ['right', 'Right'], ['sweep', 'Sweep'], ['chime', 'Chime']].map(([kind, label]) => `<button type="button" data-speaker-test="${kind}">${label}</button>`).join('') + '</div></div>');
  dialog.querySelectorAll('[data-speaker-test]').forEach(button => button.onclick = async () => {
    $('speaker-test-status').textContent = await window.FrogdashAudio.speakerTest(button.dataset.speakerTest);
  });
  // Software update over Wi-Fi: asks the Pi's update helper to pull and restart.
  dialog.querySelector('[data-ops-panel="support"] .ops-columns').lastElementChild.insertAdjacentHTML('afterbegin',
    '<div class="speaker-test"><div><span>Software update</span><small id="update-status">Uses a saved Wi-Fi network (home or phone hotspot) and returns to the dash cam afterwards.</small></div>' +
    '<div class="speaker-test-buttons"><button type="button" id="update-run">Update now</button><button type="button" id="update-undo" disabled>Undo update</button><button type="button" id="update-check">Show version</button></div></div>');
  // TunerStudio is a desktop program: the kiosk opens it over the dash (hardware/frogdash/tune.py).
  dialog.querySelector('[data-ops-panel="support"]').insertAdjacentHTML('afterend',
    '<section class="driver-panel ops-panel control-section" data-ops-panel="tune" hidden><div class="ops-columns">' +
    '<div class="setting-card"><h3>Tune on this screen</h3><p id="tune-status" class="control-note" role="status"></p>' +
    '<button type="button" id="tune-open" disabled>Open TunerStudio</button>' +
    '<p class="control-note">TunerStudio opens over the dash. Exit it (File &gt; Exit), or hold OFF on the steering wheel, and the gauges come back.</p></div>' +
    '<div class="setting-card"><h3>What it needs</h3>' +
    '<p class="control-note">A keyboard and mouse plugged into the Pi.</p>' +
    '<p class="control-note">The USB serial cable from the Pi to the MicroSquirt. The dash keeps reading the engine over CAN at the same time.</p>' +
    '<p class="control-note">The car stopped: it will not open while the dash sees the car moving.</p></div></div></section>');
  let tuneNote = '', tuneNoteUntil = 0;
  const tuneStatus = () => latest.tune || {available: false, state: 'unavailable', message: 'Only on the dash screen in the car: the kiosk starts TunerStudio'};
  function renderTune() {
    const t = tuneStatus(), open = t.state === 'running' || t.state === 'starting';
    $('tune-status').textContent = Date.now() < tuneNoteUntil ? tuneNote : t.available && t.moving && !open ? 'Stop the car first: TunerStudio covers the gauges' : t.message;
    $('tune-open').textContent = open ? 'Close TunerStudio' : 'Open TunerStudio';
    $('tune-open').disabled = !t.available || (t.moving && !open);
  }
  async function tuneRequest(action) {
    try {
      const response = await fetch('/tune', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action})});
      tuneNote = response.ok ? (action === 'open' ? 'Starting TunerStudio… it takes a few seconds to appear' : 'Closing TunerStudio…') : await response.text();
    } catch { tuneNote = 'TunerStudio is not available here'; }
    tuneNoteUntil = Date.now() + 6000; renderTune();
  }
  $('tune-open').onclick = () => tuneRequest(['running', 'starting'].includes(tuneStatus().state) ? 'close' : 'open');
  window.FrogdashTune = {
    get available() { return tuneStatus().available; },
    // From the quick menu: show this page (for the status line) and start it.
    open() { if (!dialog.open) { $('drive-launch')?.click(); launch.click(); } tab('tune'); if (tuneStatus().state !== 'running') tuneRequest('open'); },
  };
  let updateTimer = null, undoArmed = false;
  async function updatePoll() {
    try {
      const s = await (await fetch('/update', {cache: 'no-store'})).json();
      $('update-status').textContent = s.pending ? 'Waiting for the update helper… (is frogdash-update.path enabled?)' : `${s.message}${s.version ? ` · version ${s.version}` : ''}`;
      const busy = s.pending || s.state === 'running';
      if (!busy) { clearInterval(updateTimer); updateTimer = null; }
      $('update-run').disabled = busy;
      // Undo is offered while the version before the last update is still saved on the Pi.
      $('update-undo').disabled = busy || !s.previous;
      $('update-undo').textContent = 'Undo update'; undoArmed = false;
    } catch { $('update-status').textContent = 'Dash restarting…'; }
  }
  async function updateRequest(action, label) {
    $('update-run').disabled = $('update-undo').disabled = true;
    $('update-status').textContent = label;
    try {
      const response = await fetch('/update', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action})});
      if (!response.ok) throw new Error();
      clearInterval(updateTimer); updateTimer = setInterval(updatePoll, 2000);
    } catch { $('update-status').textContent = 'Update is not available here'; $('update-run').disabled = false; }
  }
  $('update-check').onclick = () => updatePoll();
  $('update-run').onclick = () => updateRequest('update', 'Requesting update…');
  $('update-undo').onclick = () => {
    // Two presses, so a stray button press cannot send the dash back a version.
    if (undoArmed) return updateRequest('rollback', 'Going back to the previous version…');
    undoArmed = true; $('update-undo').textContent = 'Press again';
    $('update-status').textContent = 'Undo returns to the version before the last update. Press again to confirm.';
  };
  // Terminal (optional, --terminal): commands run as the dash's unprivileged service user.
  dialog.querySelector('[data-ops-panel="support"]').insertAdjacentHTML('afterend',
    '<section class="driver-panel ops-panel control-section" data-ops-panel="terminal" hidden><div class="terminal-line"><input id="terminal-command" type="text" maxlength="2000" autocomplete="off" spellcheck="false" placeholder="Command, for example: ip -br addr">' +
    '<button type="button" id="terminal-run">Run</button><button type="button" id="terminal-clear">Clear</button></div>' +
    '<p id="terminal-note" class="control-note">Runs as the dash service user: no sudo and not interactive. Good for checking status (ip, nmcli, ping, ls, cat). Use a keyboard; press Enter to run.</p>' +
    '<pre id="terminal-output" class="terminal-output" tabindex="0"></pre></section>');
  const terminalHistory = [];
  let terminalIndex = 0;
  async function terminalRun() {
    const command = $('terminal-command').value.trim();
    if (!command) return;
    terminalHistory.push(command); terminalIndex = terminalHistory.length;
    const out = $('terminal-output');
    out.textContent += `$ ${command}\n`;
    $('terminal-command').value = ''; $('terminal-run').disabled = true;
    try {
      const response = await fetch('/terminal', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({command})});
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      out.textContent += result.output + (result.exit ? `[exit ${result.exit}]\n` : '') + '\n';
    } catch (error) { out.textContent += `${error.message || 'Terminal unavailable'}\n\n`; }
    $('terminal-run').disabled = false;
    out.scrollTop = out.scrollHeight;
  }
  $('terminal-run').onclick = terminalRun;
  $('terminal-clear').onclick = () => { $('terminal-output').textContent = ''; };
  $('terminal-command').addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); terminalRun(); }
    else if (event.key === 'ArrowUp' && terminalIndex > 0) { $('terminal-command').value = terminalHistory[--terminalIndex]; event.preventDefault(); }
    else if (event.key === 'ArrowDown' && terminalIndex < terminalHistory.length) { $('terminal-command').value = terminalHistory[++terminalIndex] || ''; event.preventDefault(); }
  });
  fetch('/terminal').then(r => { if (!r.ok) $('terminal-note').textContent = 'Terminal is off. Add --terminal to FROGDASH_ARGS in /etc/default/frogdash and restart frogdash.service to enable it.'; }).catch(() => {});
  const launch = el('button', 'Dash management', 'close-button'); launch.id = 'operations-launch'; launch.type = 'button';
  $('drive-close').before(launch);
  function tab(key) { document.querySelectorAll('[data-ops-panel]').forEach(n => n.hidden = n.dataset.opsPanel !== key); document.querySelectorAll('[data-ops-tab]').forEach(n => n.setAttribute('aria-selected', String(n.dataset.opsTab === key))); }
  document.querySelectorAll('[data-ops-tab], [data-ops-go]').forEach(n => n.onclick = () => tab(n.dataset.opsTab || n.dataset.opsGo));
  $('operations-close').onclick = () => dialog.close();
  launch.onclick = async () => { dialog.showModal(); render(); if (!demo()) await work(async () => { const data = await api('status'); backlight = data.backlight; render(); }); };
  $('demo-park').onclick = () => window.frogdashDemo.scenario(parked() ? 'drive' : 'parked');
  function message(text) { feedback = text; $('operations-result').textContent = text; }
  async function work(fn) { if (busy) return; busy = true; try { await fn(); } catch (e) { message(e.message); } finally { busy = false; render(); } }
  async function api(action, body) { const response = await fetch('/operations/' + action, {method: body === undefined ? 'GET' : 'POST', headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(12000)}); if (!response.ok) throw new Error(await response.text()); return response.json(); }
  function preferences() { return Object.fromEntries(keys.flatMap(key => { const raw = localStorage.getItem(key); return raw ? [[key, JSON.parse(raw)]] : []; })); }
  function applyPreferences(ui) { for (const key of keys) { if (ui[key]) localStorage.setItem(key, JSON.stringify(ui[key])); else localStorage.removeItem(key); } location.reload(); }
  function download(name, data) { const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'})); const a = el('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  async function change(body) {
    if (!canConfigure()) throw new Error('Connect to the dash service to save configuration.');
    if (demo()) {
      if (body.check) simulated.checks[body.check] = Date.now();
      if (body.ui) simulated.ui = body.ui;
      const m = body.maintenance;
      if (m?.name && ![m.km, m.hours, m.days].some(n => n > 0)) throw new Error('Set at least one maintenance interval.');
      if (m?.name) simulated.maintenance.push({...m, id: crypto.randomUUID().replaceAll('-', ''), remaining: {km: m.km, hours: m.hours, days: m.days}, history: [], due: false});
      if (m?.delete) simulated.maintenance = simulated.maintenance.filter(i => i.id !== m.delete);
      if (m?.complete) { const item = simulated.maintenance.find(i => i.id === m.complete); item.history.push({timestamp_ms: Date.now()}); item.due = false; }
    } else latest.operations = await api('settings', body);
    message(demo() ? 'Simulated change applied; no hardware accessed.' : 'Saved on the Pi.');
  }
  $('maintenance-form').onsubmit = e => { e.preventDefault(); work(() => change({maintenance: {name: $('maintenance-name').value, km: $('maintenance-distance').valueAsNumber * (u.metric ? 1 : 1.609344), hours: $('maintenance-hours').valueAsNumber, days: $('maintenance-days').valueAsNumber}})); };
  $('units-system').value = u.metric ? 'metric' : 'us'; $('units-system').onchange = e => { u.set(e.target.value); render(); };
  $('backlight-form').onsubmit = e => { e.preventDefault(); work(async () => { await api('backlight', {percent: $('backlight-percent').valueAsNumber}); message('LCD brightness applied.'); }); };
  $('profile-save').onclick = () => work(() => change({ui: preferences()}));
  $('profile-load').onclick = () => work(async () => { const data = demo() ? simulated : await api('status'); if (!Object.keys(data.ui || {}).length) throw new Error('No display profile is saved on the Pi.'); applyPreferences(data.ui); });
  $('backup-download').onclick = () => work(async () => { const data = demo() ? {format: 'frogdash-preview-backup', version: 1, ui: preferences(), operations: simulated} : await api('backup', {ui: preferences()}); download('frogdash-backup.json', data); message(demo() ? 'Preview backup downloaded; production restore rejects simulated data.' : 'Backup downloaded.'); });
  $('backup-file').onchange = () => work(async () => { pending = null; const file = $('backup-file').files[0]; if (!file) return; if (file.size > 6000000) throw new Error('Backup exceeds 6 MB.'); const data = JSON.parse(await file.text()); if (data.format !== (demo() ? 'frogdash-preview-backup' : 'frogdash-backup') || ![1, 2].includes(data.version)) throw new Error('Unsupported backup.'); pending = data; $('backup-review').textContent = `${data.software || 'Preview'} · ${data.operations?.maintenance?.length || 0} service reminders. Restore will replace the configuration and reload this display.${!demo() && data.version === 1 ? ' Legacy Pi sender settings will be ignored.' : ''}`; });
  $('backup-restore').onclick = () => work(async () => { if (!pending || !canConfigure()) throw new Error('Connect to the dash service and choose a backup first.'); const result = demo() ? {ui: pending.ui} : await api('restore', pending); applyPreferences(result.ui); });
  $('diagnostic-download').onclick = () => work(async () => { download('frogdash-diagnostic.json', demo() ? {simulated: true, software: simulated} : await api('diagnostic')); message('Diagnostic report downloaded.'); });
  let feedback = '';
  let listSignature = '';
  function render() {
    const s = status(), canEdit = canConfigure() && !busy && !s.restore_pending;
    renderTune();
    $('operations-result').textContent = feedback || (demo() ? 'Preview configuration is editable while the gauges move. Changes are simulated.' : online ? 'Configuration ready. Changes save to the Pi; CAN telemetry is not required.' : 'Connecting to the dash service...');
    $('operations-summary').textContent = `${demo() ? 'SIMULATED · Preview editing enabled' : online ? 'Configuration available' : 'Connecting to the dash service'}${s.error ? ' · ' + s.error : ''}`;
    $('demo-park').hidden = !demo(); $('demo-park').textContent = parked() ? 'Drive demo' : 'Park demo';
    document.querySelectorAll('.ops-edit').forEach(n => { n.inert = !canEdit; n.classList.toggle('configuration-locked', !canEdit); });
    $('backup-restore').disabled = !pending || !canEdit;
    const rows = (id, entries) => $(id).replaceChildren(...entries.map(([label, value]) => { const row = el('p', null, 'ops-status-row'); row.append(el('span', label), el('b', value)); return row; }));
    if (dialog.open) {
      rows('setup-hardware', [['Platform', [s.model, s.os].filter(Boolean).join(' / ') || 'Waiting'], ['CAN', latest.transport?.connected ? 'Connected' : 'No live bus'], ['GPS', latest.values?.['vehicle.speed_kph']?.quality === 'live' ? 'Live speed' : 'No fresh fix'], ['Screen', `${screen.width} × ${screen.height} · viewport ${innerWidth} × ${innerHeight}`], ...Object.entries(latest.modules || {})]);
      rows('setup-calibration', [['CAN fuel level', !online ? 'Disconnected' : latest.values?.['vehicle.fuel_pct']?.quality === 'live' ? `${latest.values['vehicle.fuel_pct'].value.toFixed(1)}%` : latest.values?.['vehicle.fuel_pct']?.quality || 'unavailable'], ['Injector estimate', latest.trip?.settings?.enabled ? 'Enabled · verify calibration' : 'Needs dead-time / bank verification'], ['Tank', latest.trip?.settings?.capacity_l ? `${u.volume(latest.trip.settings.capacity_l).toFixed(2)} ${u.volumeUnit}` : demo() ? '15.4 US gal' : 'Waiting'], ['Display units', u.metric ? 'Metric' : 'US'], ['Vehicle checks', `${Object.keys(s.checks || {}).length} / ${Object.keys(checks).length} recorded`]]);
    }
    $('maintenance-distance-label').firstChild.textContent = `Distance · ${u.distanceUnit}`;
    $('support-version').textContent = `Dash ${s.version || 'connecting'} · ${s.os || ''} · Python ${s.python || '—'}`;
    $('backlight-status').textContent = demo() ? 'Hardware only: physical LCD brightness requires a connected Pi display. Use Drive > Display modes to preview software dimming.' : backlight.writable ? `Selected: ${backlight.selected}` : `Unavailable. Detected: ${(backlight.devices || []).join(', ') || 'none'}. Select a supported device in service configuration.`;
    $('backlight-apply').disabled = !backlight.writable || busy || demo();
    $('backlight-percent').disabled = !backlight.writable || busy || demo();
    $('backlight-apply').textContent = demo() ? 'Requires Pi display' : 'Apply to LCD';
    const signature = JSON.stringify([(s.maintenance || []).map(m => ({...m, remaining: Object.fromEntries(Object.entries(m.remaining || {}).map(([k,v]) => [k, Math.round(v)]))})), s.checks, s.capabilities, canEdit, u.metric]);
    if (signature !== listSignature) {
      listSignature = signature;
      $('maintenance-list').replaceChildren(el('h3', 'Upcoming service'));
      if (!s.maintenance?.length) $('maintenance-list').append(el('p', 'No reminders yet.', 'control-note'));
      for (const item of s.maintenance || []) {
        const card = el('article', null, 'service-item'); card.append(el('h4', `${item.due ? 'DUE · ' : ''}${item.name}`));
        card.append(el('p', Object.entries(item.remaining || {}).filter(([key]) => item[key] > 0).map(([key, value]) => `${(key === 'km' ? u.distance(value) : value).toFixed(0)} ${key === 'km' ? u.distanceUnit : key} remaining`).join(' · '), 'control-note'));
        const actions = el('div', null, 'control-row'); for (const [key, label] of [['complete','Record service'],['delete','Remove']]) { const b = el('button', label); b.type = 'button'; b.disabled = !canEdit; b.onclick = () => work(() => change({maintenance: {[key]: item.id}})); actions.append(b); } card.append(actions);
        if (item.history.length) {
          card.append(el('p', 'Last service: ' + new Date(item.history.at(-1).timestamp_ms).toLocaleDateString(), 'control-note'));
          const details = el('details'); details.append(el('summary', `Service history (${item.history.length})`));
          for (const h of [...item.history].reverse()) details.append(el('p', new Date(h.timestamp_ms).toLocaleString() + (Number.isFinite(h.km) ? ` \u00b7 ${u.distance(h.km).toFixed(1)} ${u.distanceUnit} tracked \u00b7 ${h.hours.toFixed(1)} h` : ''), 'control-note'));
          card.append(details);
        }
        $('maintenance-list').append(card);
      }
      $('acceptance-list').replaceChildren(...Object.entries(checks).map(([key, label]) => { const b = el('button', `${s.checks?.[key] ? '✓ ' : ''}${label}`); b.type = 'button'; b.disabled = !canEdit; b.onclick = () => work(() => change({check: key})); return b; }));
      $('controller-capabilities').replaceChildren(...(s.capabilities || []).map(c => el('p', `${c.module}: ${c.command}. ${c.readback}. ${c.persistence}.`, 'control-note')));
    }
    // Local display preferences remain editable even without the backend.
    // API-backed calibration only needs the service, not stationary CAN data.
    for (const selector of ['#fuel-settings', '#alert-settings']) {
      const node = document.querySelector(selector);
      if (node) { node.inert = !canConfigure() || s.restore_pending === true; node.classList.toggle('configuration-locked', node.inert); node.title = node.inert ? 'Waiting for the dash service to accept configuration' : ''; }
    }
    $('appearance-access').textContent = demo() ? 'Preview editing enabled \u00b7 changes save on this display' : 'Saved on this display \u00b7 live changes across the dash';
  }
  tab('setup');
  window.addEventListener('frogdash-state', e => { latest = e.detail.snapshot; online = e.detail.connected; render(); });
  const token = new URLSearchParams(location.search).get('kiosk');
  let lastBeat = 0, lastRender = 0;
  function heartbeat(now) { if (/^[0-9a-f]{32}$/.test(token) && now - lastBeat > 2000 && window.frogdashRendered !== lastRender) { lastBeat = now; lastRender = window.frogdashRendered; fetch('/ui/heartbeat/' + token, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: window.frogdashDisplayInfo ? JSON.stringify({display: window.frogdashDisplayInfo()}) : undefined, signal: AbortSignal.timeout(3000)}).catch(() => {}); } requestAnimationFrame(heartbeat); }
  requestAnimationFrame(heartbeat);
})();
