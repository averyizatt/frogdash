/* Windows tuning on the Tuning page (Dash management > Tuning). Experimental.

   The ECU makers' tuners are Windows programs. Two routes, per USB device
   (hardware/frogdash/wintune.py):
   - a USB serial cable or ECU: the tuner runs over the dash in Wine through Box64, with the
     port as COM1, COM2... (installed from a USB stick);
   - one that needs its maker's own Windows driver: the dash shares it with a Windows PC on
     its network (USB/IP), and the tuner runs on the PC with the real driver.
   Status comes from /tune/windows every 3 s while the page is open. */
(() => {
  'use strict';
  const panel = document.querySelector('[data-ops-panel="tune"] .ops-columns');
  if (!panel) return;
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  panel.insertAdjacentHTML('beforeend', `
    <div class="setting-card wt-card" id="wt-card"><h3>Windows tuner <small>experimental</small></h3>
      <p class="control-note" id="wt-status" role="status">Checking…</p>
      <div id="wt-programs" class="wt-list"></div>
      <h4>Install from a USB stick</h4>
      <p class="control-note">Put the maker's installer (.exe or .msi) on a USB stick and plug it into the Pi.</p>
      <div class="wt-buttons"><button type="button" data-wt="usb_scan">Look on the USB stick</button><button type="button" data-wt="usb_eject">Eject</button></div>
      <div id="wt-stick" class="wt-list"></div><div id="wt-installers" class="wt-list"></div>
    </div>
    <div class="setting-card wt-card"><h3>USB: the ECU or its tuning cable</h3>
      <p class="control-note">Plug the tuning cable into the Pi. Each device shows how its tuner can reach it.</p>
      <div id="wt-usb" class="wt-list"></div><p class="control-note" id="wt-helper" role="status"></p>
    </div>`);
  const $ = id => document.getElementById(id);
  let latest = null, timer = null;

  async function post(body) {
    const response = await fetch('/tune/windows', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (!response.ok) throw new Error(await response.text());
  }
  async function act(body, note) {
    $('wt-helper').textContent = note;
    try { await post(body); } catch (error) { $('wt-helper').textContent = error.message; }
    setTimeout(refresh, 800);
  }

  function route(device, addresses) {
    if (device.route === 'serial') {
      const port = (latest.ports || []).find(p => device.ttys.some(t => p.device.endsWith(t)));
      return `<p>USB serial (${esc(device.ttys.join(', '))}): the Windows tuner on the dash reaches it as <b>${esc(port ? port.com : 'COM1')}</b>.</p>`;
    }
    const where = (addresses || [])[0] || 'the dash';
    if (device.route === 'shared') {
      return `<p><b>Shared.</b> On the Windows PC (joined to the dash's Wi-Fi, with usbip-win2 installed): <code>usbip attach -r ${esc(where)} -b ${esc(device.busid)}</code>, then open the tuner there.</p>
        <button type="button" data-wt="unshare" data-arg="${esc(device.busid)}">Stop sharing</button>`;
    }
    return `<p>Needs its maker's own Windows driver, which Wine cannot load. Share it with a Windows PC on the dash's Wi-Fi: the tuner runs there with the real driver.</p>
      <button type="button" data-wt="share" data-arg="${esc(device.busid)}">Share with a Windows PC</button>`;
  }
  function render() {
    if (!latest) return;
    const running = latest.state === 'running';
    $('wt-status').textContent = latest.message;
    $('wt-programs').innerHTML = (latest.programs || []).map(p => `<div class="wt-row"><span>${esc(p.name)}</span>
      <button type="button" data-wt-open="${esc(p.path)}"${running || !latest.available ? ' disabled' : ''}>Open</button></div>`).join('')
      + (running ? '<div class="wt-row"><span>Running over the dash</span><button type="button" data-wt-close>Close it</button></div>' : '')
      || (latest.available ? '<p class="control-note">No tuner installed yet.</p>' : '');
    const helper = latest.helper || {};
    $('wt-stick').innerHTML = (helper.usb?.files || []).map(f => `<div class="wt-row"><span>${esc(f.name)} · ${f.mb} MB</span>
      <button type="button" data-wt="usb_copy" data-arg="${esc(f.name)}">Copy to the Pi</button></div>`).join('');
    $('wt-installers').innerHTML = (latest.installers || []).map(i => `<div class="wt-row"><span>${esc(i.name)} · on the Pi</span>
      <button type="button" data-wt-install="${esc(i.path)}"${running || !latest.available ? ' disabled' : ''}>Install</button></div>`).join('');
    $('wt-usb').innerHTML = (latest.usb || []).map(d => `<div class="wt-device"><b>${esc(d.name)}</b> <small>${esc(d.id)} · port ${esc(d.busid)}</small>${route(d, latest.addresses)}</div>`).join('')
      || '<p class="control-note">No ECU or tuning cable plugged into the Pi.</p>';
    if (latest.pending) $('wt-helper').textContent = 'Working…';
    else if (helper.message && Date.now() / 1000 - (helper.time || 0) < 60) $('wt-helper').textContent = helper.message;
  }
  async function refresh() {
    try {
      const response = await fetch('/tune/windows', {cache: 'no-store'});
      if (!response.ok) throw new Error();
      latest = await response.json();
    } catch {
      latest = {available: false, state: 'unavailable', message: 'Only on the dash in the car', programs: [], installers: [], usb: []};
    }
    render();
  }

  document.addEventListener('click', event => {
    const target = event.target.closest('#wt-card, .wt-card') && event.target.closest('button');
    if (!target) return;
    if (target.dataset.wt) act({action: target.dataset.wt, arg: target.dataset.arg || null}, 'Asking the Pi…');
    else if (target.dataset.wtOpen) act({action: 'open', target: target.dataset.wtOpen}, 'Starting it over the dash… Wine takes a while the first time');
    else if (target.dataset.wtInstall) act({action: 'install', target: target.dataset.wtInstall}, 'The installer opens over the dash: use a mouse to go through it');
    else if ('wtClose' in target.dataset) act({action: 'close'}, 'Closing…');
  });
  // Refresh while the Tuning page is showing.
  const tunePanel = document.querySelector('[data-ops-panel="tune"]');
  new MutationObserver(() => {
    clearInterval(timer); timer = null;
    if (!tunePanel.hidden && tunePanel.closest('dialog')?.open) { refresh(); timer = setInterval(refresh, 3000); }
  }).observe(tunePanel, {attributes: true, attributeFilter: ['hidden']});
})();
