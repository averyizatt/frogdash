(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let showPassed = false, updating = false, armed = null, armTimer = 0;
  async function request(path, options) {
    const response = await fetch(path, {...options, signal: AbortSignal.timeout(10000)});
    if (!response.ok) {
      const error = new Error(response.status === 401 ? 'Enter the current access code shown on the dash.' : response.status === 429 ? 'Too many attempts. Wait a minute.' : 'Request failed. Check the hotspot is still on.');
      error.status = response.status; throw error;
    }
    return response.json();
  }
  const post = (path, body) => request(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  function needLogin(error) {
    if (error.status === 401) { $('login').hidden = false; $('content').hidden = true; }
  }

  // Faults first: everything that failed or needs attention, with what to do about it.
  function renderCheck(report) {
    const order = {fail: 0, warn: 1, ok: 2, skip: 3}, words = {fail: 'FAULT', warn: 'CHECK', ok: 'OK', skip: 'NOT USED'};
    const counts = report.counts, problems = counts.fail + counts.warn;
    $('check-summary').textContent = problems ? `${counts.fail} fault${counts.fail === 1 ? '' : 's'}, ${counts.warn} to check, ${counts.ok} OK` : `No faults: ${counts.ok} checks OK`;
    $('check-summary').dataset.state = counts.fail ? 'fail' : counts.warn ? 'warn' : 'ok';
    const lines = report.lines.filter(line => showPassed || line.status === 'fail' || line.status === 'warn').sort((a, b) => order[a.status] - order[b.status]);
    $('check-lines').replaceChildren(...lines.map(line => {
      const row = document.createElement('li'), head = document.createElement('strong'), detail = document.createElement('span');
      row.dataset.state = line.status;
      head.textContent = `${words[line.status]} · ${line.group} · ${line.name}`;
      detail.textContent = line.detail;
      row.append(head, detail);
      if (line.fix) { const fix = document.createElement('small'); fix.textContent = line.fix; row.append(fix); }
      return row;
    }));
    $('check-all').hidden = false;
    $('check-all').textContent = showPassed ? 'Show faults only' : 'Show everything that passed';
  }
  function renderUpdate(update) {
    const busy = update.pending || update.state === 'running';
    $('update-status').textContent = update.pending ? 'Waiting for the dash to start…' : `${update.message}${update.version ? ` · version ${update.version}` : ''}`;
    $('update-status').dataset.state = update.state === 'failed' ? 'fail' : update.state === 'rolledback' || update.state === 'held' ? 'warn' : '';
    $('update-run').disabled = busy;
    $('update-undo').disabled = busy || !update.previous;
    if (!armed) { $('update-run').textContent = 'Update now'; $('update-undo').textContent = 'Undo last update'; }
    if (busy && !updating) watchUpdate();
  }
  // The dash restarts during an update and the hotspot stays up for it: keep asking until it answers again.
  async function watchUpdate() {
    updating = true;
    for (let quiet = 0; updating;) {
      await new Promise(resolve => setTimeout(resolve, 3000));
      try {
        const update = await request('/api/update');
        quiet = 0; renderUpdate(update);
        if (!update.pending && update.state !== 'running') { updating = false; refresh(); }
      } catch (error) {
        if (error.status === 401) { updating = false; needLogin(error); $('message').textContent = error.message; }
        else if (++quiet > 100) { updating = false; $('update-status').textContent = 'No answer from the dash. Check the hotspot under Controls → Wi-Fi.'; }
        else $('update-status').textContent = 'The dash is restarting…';
      }
    }
  }
  // Two presses, as on the dash: the first arms the button for a few seconds.
  function twoPress(button, label, action) {
    button.onclick = async () => {
      if (armed !== button) {
        armed = button; button.textContent = `Press again to ${label}`;
        clearTimeout(armTimer); armTimer = setTimeout(() => { armed = null; refresh(); }, 5000);
        return;
      }
      armed = null; clearTimeout(armTimer); button.disabled = true;
      try { renderUpdate(await post('/api/update', {action})); }
      catch (error) { $('message').textContent = error.message; needLogin(error); }
    };
  }
  // Module firmware goes over the CAN bus from the dash; this only presses its button.
  let installing = false, firmwareNote = null;   // {name, text, until}: a prompt or refusal kept readable
  function renderFirmware(firmware) {
    const modules = Object.values(firmware || {}), busy = modules.some(module => module.job.state === 'running');
    $('firmware').replaceChildren(...modules.map(module => {
      const row = document.createElement('li'), text = document.createElement('span'), job = module.job, running = job.state === 'running';
      const held = firmwareNote && firmwareNote.name === module.name && Date.now() < firmwareNote.until && !running;
      text.textContent = held ? firmwareNote.text : running ? `${module.title}: ${job.message} (${Math.round(job.progress * 100)}%)` :
        job.state === 'failed' ? `${module.title}: ${job.message}` : job.state === 'done' ? job.message :
        `${module.title}: ${module.installed ? `build ${module.installed}. ` : ''}${module.note}`;
      row.dataset.state = job.state === 'failed' ? 'fail' : module.new ? 'warn' : '';
      row.append(text);
      if (module.new || running) {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'quiet'; button.dataset.firmware = module.name;
        button.disabled = busy || !module.can_install;
        button.textContent = running ? 'Installing…' : armed === module.name ? 'Press again to install' : `Install ${module.title.toLowerCase()}`;
        button.onclick = () => installFirmware(module);
        row.append(button);
      }
      return row;
    }));
    if (busy && !installing) watchFirmware();
  }
  async function watchFirmware() {
    installing = true;
    while (installing) {
      await new Promise(resolve => setTimeout(resolve, 1500));
      try {
        const firmware = await request('/api/firmware');
        if (!Object.values(firmware).some(module => module.job.state === 'running')) installing = false;
        renderFirmware(firmware);
      } catch (error) { installing = false; needLogin(error); }
    }
  }
  async function showFirmware() {
    try { renderFirmware(await request('/api/firmware')); } catch (error) { needLogin(error); }
  }
  async function installFirmware(module) {
    if (armed !== module.name) {
      armed = module.name;
      firmwareNote = {name: module.name, text: `Stop the car first. ${module.warning}`, until: Date.now() + 6000};
      clearTimeout(armTimer); armTimer = setTimeout(() => { armed = null; firmwareNote = null; showFirmware(); }, 6000);
      return showFirmware();
    }
    armed = null; firmwareNote = null; clearTimeout(armTimer);
    try {
      const response = await fetch('/api/firmware', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: module.name, action: 'install'}), signal: AbortSignal.timeout(10000)});
      if (response.ok) return renderFirmware(await response.json());
      firmwareNote = {name: module.name, text: `${module.title}: ${(await response.text()).slice(0, 200)}`, until: Date.now() + 8000};
    } catch { firmwareNote = {name: module.name, text: `${module.title}: the dash did not answer`, until: Date.now() + 8000}; }
    showFirmware();
  }
  twoPress($('update-run'), 'update', 'update');
  twoPress($('update-undo'), 'go back', 'rollback');

  async function refresh() {
    $('message').textContent = '';
    try {
      const [status, listing, check] = await Promise.all([request('/api/status'), request('/api/logs'), request('/api/check')]);
      $('login').hidden = true; $('content').hidden = false;
      $('status').textContent = `${status.transport.connected ? 'CAN connected' : 'CAN offline'} · ${status.mode} · ${Object.entries(status.modules).map(([name, quality]) => `${name}: ${quality}`).join(' · ')}`;
      $('recording').textContent = `Recording: ${status.recording.state}${status.recording.error ? ' · ' + status.recording.error : ''}`;
      const system = status.system;
      $('system-status').textContent = system ? `System: ${system.cpu_c == null ? 'temperature unavailable' : system.cpu_c.toFixed(1) + ' °C'} · ${system.disk ? (system.disk.free_bytes / 1073741824).toFixed(1) + ' GiB free' : 'storage unavailable'} · CAN ${system.can?.state || 'diagnostics unavailable'}` : 'System diagnostics unavailable';
      renderCheck(check.report); renderUpdate(check.update); renderFirmware(check.firmware);
      $('finish-log').disabled = !listing.files.some(file => file.active);
      $('files').replaceChildren(...listing.files.map(file => {
        const row = document.createElement('li'), name = document.createElement(file.active ? 'span' : 'a'), detail = document.createElement('small');
        name.textContent = file.name;
        if (!file.active) { name.href = '/logs/' + encodeURIComponent(file.name); name.download = file.name; }
        detail.textContent = `${(file.bytes / 1048576).toFixed(1)} MiB${file.active ? ' · Still recording' : ''}`;
        row.append(name, detail); return row;
      }));
      if (!listing.files.length) $('files').textContent = 'No saved logs yet.';
      await review.load();
    } catch (error) {
      $('message').textContent = error.message;
      needLogin(error);
    }
  }
  $('login-form').onsubmit = async event => {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
    try {
      await post('/session', {code: $('code').value});
      $('code').value = ''; await refresh();
    } catch (error) { $('message').textContent = error.message; }
    finally { button.disabled = false; }
  };
  $('refresh').onclick = refresh;
  $('check-all').onclick = () => { showPassed = !showPassed; refresh(); };
  $('finish-log').onclick = async () => {
    $('finish-log').disabled = true;
    try {
      await post('/api/logs/finish');
      $('message').textContent = 'Finished. The log is ready to download.';
      setTimeout(refresh, 1200);   // The recorder closes the file on its own turn.
    } catch (error) { $('message').textContent = error.status === 401 ? error.message : 'Could not finish the log. Try again.'; needLogin(error); }
  };
  const review = new FrogdashReview($('phone-review'), {
    list: () => reviewRequest('/api/drives'), read: name => reviewRequest('/api/drives/' + encodeURIComponent(name))
  });
  async function reviewRequest(path) {
    try { return await request(path); }
    catch (error) { needLogin(error); throw error; }
  }
  // Coming back to the page after an update restart (or reopening it): the login is still good.
  request('/api/update').then(() => refresh()).catch(() => {});
})();
