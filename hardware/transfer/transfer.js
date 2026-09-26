(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  async function request(path, options) {
    const response = await fetch(path, {...options, signal: AbortSignal.timeout(10000)});
    if (!response.ok) {
      const error = new Error(response.status === 401 ? 'Enter the current access code shown on the dash.' : response.status === 429 ? 'Too many attempts. Wait a minute.' : 'Request failed. Check the hotspot is still on.');
      error.status = response.status; throw error;
    }
    return response.json();
  }
  async function refresh() {
    $('message').textContent = '';
    try {
      const [status, listing] = await Promise.all([request('/api/status'), request('/api/logs')]);
      $('login').hidden = true; $('content').hidden = false;
      $('status').textContent = `${status.transport.connected ? 'CAN connected' : 'CAN offline'} · ${status.mode} · ${Object.entries(status.modules).map(([name, quality]) => `${name}: ${quality}`).join(' · ')}`;
      $('recording').textContent = `Recording: ${status.recording.state}${status.recording.error ? ' · ' + status.recording.error : ''}`;
      $('files').replaceChildren(...listing.files.map(file => {
        const row = document.createElement('li'), name = document.createElement(file.active ? 'span' : 'a'), detail = document.createElement('small');
        name.textContent = file.name;
        if (!file.active) { name.href = '/logs/' + encodeURIComponent(file.name); name.download = file.name; }
        detail.textContent = `${(file.bytes / 1048576).toFixed(1)} MiB${file.active ? ' · Still recording' : ''}`;
        row.append(name, detail); return row;
      }));
      if (!listing.files.length) $('files').textContent = 'No saved logs yet.';
    } catch (error) {
      $('message').textContent = error.message;
      if (error.status === 401) { $('login').hidden = false; $('content').hidden = true; }
    }
  }
  $('login-form').onsubmit = async event => {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
    try {
      await request('/session', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code: $('code').value})});
      $('code').value = ''; await refresh();
    } catch (error) { $('message').textContent = error.message; }
    finally { button.disabled = false; }
  };
  $('refresh').onclick = refresh;
})();
