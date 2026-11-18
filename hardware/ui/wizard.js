/* The setup wizard: what this car has, chosen on the dash's own screen.

   It reads the Pi's system profile, the presets and the ECU profiles from /system, walks
   through the choices one page at a time and, on Apply, posts the whole profile back. A
   root-owned helper (tools/frogdash_config.py) saves it, keeping the old one as a backup,
   and runs the Pi setup to match; this page follows its progress. It opens by itself
   while the profile says the dash has not been set up (configured: false), and from Dash
   management > Setup checklist at any time.

   In the published preview there is no Pi: window.frogdashSystemDemo (made from the real
   presets and ECU profiles by tools/update_preview.py) stands in, and Apply only shows
   what would happen. Open the preview with ?wizard to start here. */
(() => {
  'use strict';
  const DEMO = window.frogdashSystemDemo || null;
  const STATUS = {car: ['Running in a car', 'good'], simulated: ['Tested with simulated frames', 'warn'], documented: ['From the documents only', 'warn']};
  const MODULES = [
    ['gateway', 'Sensor gateway', 'The DIY comfort/gateway module: speed sensor, fuel sender, analog sensors and the steering-wheel buttons over CAN.'],
    ['taillights', 'Taillight controller', 'The CustomTaillights board: turn, brake and reverse signals reach the dash from it, and its light shows are set from here.'],
    ['watermeth', 'Water/methanol injection', 'The ESP32 water/meth board: its tank, pump and safety readings, tuning and black box. It reads MAP from a MegaSquirt broadcast.'],
  ];
  const PAGES = ['start', 'screen', 'ecu', 'can', 'gps', 'cameras', 'modules', 'features', 'power', 'locale', 'review'];
  const TITLES = {start: 'Start from', screen: 'Screen', ecu: 'Engine computer', can: 'CAN board', gps: 'GPS', cameras: 'Cameras',
                  modules: 'Frogdash modules', features: 'On the dash', power: 'Power', locale: 'Place, units and network', review: 'Review and apply'};
  // Screens people use for a dash, and how the 1920 x 720 layout fits each (scaled, with
  // bars where the shape differs). 'auto': any other; the dash fits itself to it.
  const SCREENS = [
    ['1920x720', 'Bar screen, 1920 × 720', '8.8" to 12.3" stretched panels. The layout is made for this: it fills the screen exactly.'],
    ['1280x480', 'Bar screen, 1280 × 480', 'Smaller stretched panels. The same shape: the dash fills it, scaled down.'],
    ['1280x400', 'Bar screen, 1280 × 400', 'Long thin panels. Thin bars at the sides.'],
    ['800x480', '7" screen, 800 × 480', 'The official Raspberry Pi 7" and many HDMI 7" screens. Bars above and below.'],
    ['1024x600', '7" screen, 1024 × 600', 'Common HDMI 7" panels. Bars above and below.'],
    ['1280x800', '10.1" screen, 1280 × 800', 'Tablet-shaped panels. Bars above and below.'],
    ['1920x1080', 'Full HD, 1920 × 1080', 'A monitor or TV. Bars above and below.'],
    ['auto', 'Something else', 'The dash measures the screen and fits itself to it.'],
  ];
  let data = null, draft = null, page = 0, applying = false, poll = null;

  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const copy = value => JSON.parse(JSON.stringify(value));
  const get = path => path.split('.').reduce((o, k) => o?.[k], draft);
  function set(path, value) {
    const keys = path.split('.'); const last = keys.pop();
    keys.reduce((o, k) => o[k], draft)[last] = value;
  }

  const dialog = document.createElement('dialog');
  dialog.id = 'setup-wizard'; dialog.className = 'workspace-dialog wizard'; dialog.setAttribute('aria-labelledby', 'wizard-title');
  dialog.innerHTML = `<header class="wizard-head"><div><span class="eyebrow">SET UP THIS DASH</span><h2 id="wizard-title">Setup</h2></div>
      <ol class="wizard-steps" id="wizard-steps"></ol><button type="button" class="close-button" id="wizard-close">Close ×</button></header>
    <section class="wizard-body" id="wizard-body" aria-live="polite"></section>
    <footer class="wizard-foot"><p id="wizard-note" role="status"></p>
      <div class="wizard-nav"><button type="button" id="wizard-back">Back</button><button type="button" id="wizard-next" class="wizard-primary">Next</button></div></footer>`;
  document.body.append(dialog);
  const $ = id => dialog.querySelector('#' + id);

  async function load() {
    if (DEMO) return copy(DEMO);
    const response = await fetch('/system', {cache: 'no-store'});
    if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`);
    return response.json();
  }

  function ecuProfile(id = draft.ecu.profile) { return data.ecu.profiles.find(p => p.id === id) || {id, label: id}; }

  // --- Fields ---
  function toggle(path, label, help = '', disabled = false) {
    return `<label class="wizard-toggle${disabled ? ' off' : ''}"><input type="checkbox" data-wizard-path="${path}"${(path === 'screen.mode' ? get(path) !== 'auto' : get(path)) ? ' checked' : ''}${disabled ? ' disabled' : ''}>
      <span><b>${esc(label)}</b>${help ? `<small>${help}</small>` : ''}</span></label>`;
  }
  function choice(path, label, options, help = '') {
    const now = String(get(path));
    return `<label class="wizard-field"><span>${esc(label)}</span><select data-wizard-path="${path}" data-kind="${typeof get(path)}">${options.map(([v, text]) =>
      `<option value="${esc(v)}"${String(v) === now ? ' selected' : ''}>${esc(text)}</option>`).join('')}</select>${help ? `<small>${help}</small>` : ''}</label>`;
  }
  function text(path, label, help = '', placeholder = '') {
    return `<label class="wizard-field"><span>${esc(label)}</span><input type="text" data-wizard-path="${path}" value="${esc(get(path))}" placeholder="${esc(placeholder)}" autocomplete="off" spellcheck="false">${help ? `<small>${help}</small>` : ''}</label>`;
  }

  // --- Pages ---
  const PRESET_TEXT = {
    generic: ['A new build', 'Nothing assumed: choose your ECU and the parts your car has on the next pages.'],
    foxbody: ['The reference Foxbody', 'The car Frogdash was built in: MicroSquirt, GPS, the three Frogdash modules, PiSugar 3 and a 1920 × 720 screen.'],
  };
  function startPage() {
    const names = Object.keys(data.presets);
    return `<p class="wizard-lead">Pick the closest starting point. Every choice can be changed on the pages that follow, and again later from Dash management.</p>
      <div class="wizard-cards">${names.map(name => {
        const [title, help] = PRESET_TEXT[name] || [name, 'A preset in presets/.'];
        return `<button type="button" class="wizard-card" data-wizard-preset="${esc(name)}" aria-pressed="${draft.preset === name}"><b>${esc(title)}</b><small>${esc(help)}</small><code>${esc(name)}</code></button>`;
      }).join('')}</div>`;
  }
  function ecuPage() {
    const active = ecuProfile();
    const heard = data.bus?.ids_heard ? ` Heard on the bus now: ${data.bus.ids_heard} IDs.` : '';
    const cards = data.ecu.profiles.filter(p => !p.error).map(p => {
      const [label, tone] = STATUS[p.status] || [p.status, 'warn'];
      return `<button type="button" class="wizard-card ecu-card" data-wizard-ecu="${esc(p.id)}" aria-pressed="${p.id === draft.ecu.profile}">
        <b>${esc(p.label)}</b><small>${esc((p.models || []).join(' · ') || p.manufacturer || '')}</small>
        <span class="wizard-tags"><i class="${tone}">${esc(label)}</i><i>${(p.bitrate || 500000) / 1000} kbit/s${p.extended ? ', 29-bit' : ''}</i>${p.matches ? `<i class="good">${p.matches} of its frames heard now</i>` : ''}</span></button>`;
    }).join('');
    const tuner = active.tuner ? `<p><b>Tuning:</b> ${esc(active.tuner.name)}${active.tuner.runs_on_dash ? ' runs on the dash (Tune tab).' : ` runs on a separate computer (${esc(active.tuner.connection || '')}); the dash keeps reading the CAN bus while you tune.`}</p>` : '';
    const base = active.base ? text('ecu.base_id', `First CAN ID (${active.base.setting || 'set in the ECU'})`, `0 uses the profile's default, ${esc(active.base.default)}. Write it as a number, e.g. 1024 for 0x400.`) : '';
    return `<p class="wizard-lead">Which engine computer is on the CAN bus? Only what its maker has published is read; status says how far each has been checked.${heard}</p>
      <div class="wizard-cards ecu-cards">${cards}</div>
      <div class="wizard-detail"><h3>${esc(active.label)}</h3>${(active.setup || []).length ? `<p><b>In the ECU:</b></p><ul>${active.setup.map(s => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}
        ${tuner}${active.notes ? `<p class="wizard-small">${esc(active.notes)}</p>` : ''}
        ${active.source ? `<p class="wizard-small">Source: ${esc(active.source.title)} (${esc(active.source.version || '')})</p>` : ''}
        <div class="wizard-row">${choice('ecu.bitrate', 'CAN bus speed', [[125000, '125 kbit/s'], [250000, '250 kbit/s'], [500000, '500 kbit/s'], [1000000, '1 Mbit/s']],
          active.bitrate && active.bitrate !== get('ecu.bitrate') ? `${esc(active.label)} sends at ${active.bitrate / 1000} kbit/s.` : '')}${base}</div></div>`;
  }
  function canPage() {
    const bus = data.bus || {};
    const live = bus.connected ? `${bus.ids_heard || 0} CAN IDs heard in the last 3 s, ${bus.ecu_ids_heard || 0} of them the ECU's (${esc(data.ecu.active?.label || '')}).` : 'The CAN interface is not up yet.';
    return `<p class="wizard-lead">The board that connects the Pi to the CAN bus. An MCP2515 HAT is set up with a boot overlay; a USB CAN adapter needs none.</p>
      ${toggle('can_hat.present', 'An MCP2515 CAN HAT on the Pi', 'For example the Waveshare RS485 CAN HAT. Off for a USB adapter (gs_usb, slcan).')}
      <div class="wizard-row">${choice('can_hat.oscillator', 'Crystal on the board', [[8000000, '8 MHz'], [12000000, '12 MHz'], [16000000, '16 MHz'], [20000000, '20 MHz']], 'Printed on the silver crystal next to the MCP2515.')}
      ${choice('can_hat.interrupt', 'Interrupt pin (GPIO)', [[25, 'GPIO 25'], [24, 'GPIO 24'], [22, 'GPIO 22'], [23, 'GPIO 23'], [6, 'GPIO 6'], [5, 'GPIO 5']])}</div>
      <div class="wizard-detail"><h3>On the bus now</h3><p id="wizard-live">${live}</p><p class="wizard-small">A change to the board needs the Pi restarted; the check above then shows whether frames arrive.</p></div>`;
  }
  function gpsPage() {
    return `<p class="wizard-lead">A USB GPS (u-blox or any gpsd receiver) gives speed, the map, lap timing and the clock when there is no internet.</p>
      ${toggle('gps.enabled', 'A GPS receiver is connected', 'Installs gpsd, and chrony to set the clock from it.')}
      ${toggle('gps.transmit_on_can', 'Share GPS speed on the CAN bus (ID 0x203)', 'For modules that use vehicle speed (the water/meth board). Leave off on a bus where 0x203 is taken.', !get('gps.enabled'))}`;
  }
  function camerasPage() {
    return `<p class="wizard-lead">Cameras are optional. The reverse camera opens by itself on the reverse signal.</p>
      ${toggle('camera.enabled', 'Reverse camera', 'A Raspberry Pi camera on the Pi camera connector (CSI); it opens when reverse is engaged.')}
      ${choice('camera.rotate', 'Reverse camera picture', [[0, 'As it comes'], [180, 'Turned upside down']])}
      ${toggle('dashcam.enabled', 'Wi-Fi dash cam', 'A dash cam whose own Wi-Fi the dash joins with its second adapter, to show and save its picture.')}`;
  }
  function modulesPage() {
    const ms = draft.ecu.profile === 'megasquirt';
    return `<p class="wizard-lead">Frogdash's own boards on the CAN bus. Switch on only the ones in this car: the dash then expects them, checks them and updates their firmware.</p>
      ${MODULES.map(([key, label, help]) => toggle(`modules.${key}`, label, help + (key === 'watermeth' && !ms ? ' <b>Needs a MegaSquirt for now.</b>' : ''), key === 'watermeth' && !ms && !get('modules.watermeth'))).join('')}
      <p class="wizard-small">Turn signals, brake, reverse and fuel level come from the taillight board and the gateway in the reference car. Pi inputs and other CAN sources for them are coming (docs/presets.md).</p>`;
  }
  function screenPage() {
    const size = get('screen.size');
    const cards = SCREENS.map(([key, title, help]) => {
      let picture = '<span class="wizard-screen-any">Any size</span>', fits = '';
      if (key !== 'auto') {
        const [w, h] = key.split('x').map(Number);
        const scale = Math.min(w / 1920, h / 720);
        const wide = w / h >= 2.4;             // Wider than the picture's frame: fit its width, else its height
        const innerW = Math.min(1, (h * 8 / 3) / w) * 100, innerH = Math.min(1, (w * 3 / 8) / h) * 100;
        picture = `<span class="wizard-screen" style="${wide ? 'width:100%' : 'height:100%'};aspect-ratio:${w}/${h}"><span class="wizard-screen-dash" style="width:${innerW}%;height:${innerH}%"></span></span>`;
        fits = `<i>${Math.round(scale * 100)} % of full size</i>`;
      }
      return `<button type="button" class="wizard-card screen-card" data-wizard-screen="${key}" aria-pressed="${size === key}">
        <span class="wizard-screen-frame">${picture}</span><b>${esc(title)}</b><small>${esc(help)}</small><span class="wizard-tags">${fits}</span></button>`;
    }).join('');
    return `<p class="wizard-lead">Which screen is the dash on? The picture shows how the dash fits it: green is the dash, black the bars.</p>
      <div class="wizard-cards screen-cards">${cards}</div>
      ${toggle('screen.mode', 'Force 1920 × 720 at boot', 'For a bar panel that does not describe itself properly (the reference car\'s): the Pi is told the mode before the screen answers. Needs a restart.', size !== '1920x720')}`;
  }
  function featuresPage() {
    const tuner = ecuProfile().tuner;
    const tunes = tuner?.runs_on_dash;
    const gps = get('gps.enabled');
    const owned = [['Knock monitor and the water/meth panel', get('modules.watermeth'), 'water/meth board'],
                   ['Taillight controls and light shows', get('modules.taillights'), 'taillight board']];
    return `<p class="wizard-lead">What the dash shows and does. Screens that belong to a Frogdash module come and go with it (the Modules page).</p>
      <div class="wizard-row">${toggle('features.map', 'Map', gps ? 'The moving map with the offline tiles.' : 'The map needs GPS for where the car is (the GPS page).')}
      ${toggle('features.race', 'Race timer', gps ? 'Lap and drag timing from GPS, with results kept on the Pi.' : 'Timing needs GPS (the GPS page).')}</div>
      <div class="wizard-row">${toggle('recording', 'Record every drive', 'MLG logs for TunerStudio and MegaLogViewer, kept on the Pi, and the drive review.')}
      ${toggle('terminal', 'Terminal on the dash', 'A Linux shell with sudo, for someone who knows what they are doing.')}</div>
      ${toggle('tunerstudio', tunes ? `${tuner.name} on the dash` : 'Tuning software on the dash', tunes ? 'Installs Java and the tuner; tune from the dash screen over USB serial.' : `${esc(ecuProfile().label)} is tuned with ${esc(tuner?.name || 'its own software')} on a separate computer; the dash keeps reading the bus while you tune.`, !tunes && !get('tunerstudio'))}
      <div class="wizard-detail"><h3>With the modules</h3><ul>${owned.map(([what, on, board]) => `<li>${esc(what)}: <b>${on ? 'shown' : 'hidden'}</b> (${on ? 'the' : 'no'} ${board})</li>`).join('')}</ul>
        <p class="wizard-small">Gauges, alerts, the drive summary, trip and fuel, sensors and the CAN tools are always there. Gauge faces, colours and layouts are chosen on the dash under Appearance.</p></div>`;
  }
  function powerPage() {
    return `<p class="wizard-lead">How the Pi gets power. Pulling 12 V with the key can damage the SD card; a power board lets the Pi shut down cleanly.</p>
      <div class="wizard-cards">${[['none', 'Ignition 12 V only', 'The Pi is on while the key is. Simple; a sudden power cut can corrupt the card.'],
                                 ['pisugar3', 'PiSugar 3', 'A battery board: at key-off the dash counts down and the Pi shuts down by itself. Installs its driver.']].map(([key, title, help]) =>
        `<button type="button" class="wizard-card" data-wizard-power="${key}" aria-pressed="${get('power') === key}"><b>${esc(title)}</b><small>${esc(help)}</small></button>`).join('')}</div>`;
  }
  function localePage() {
    return `<div class="wizard-row">${text('locale.timezone', 'Time zone', 'As in the tz database. Empty keeps the Pi\'s own.', 'America/Denver')}
      ${text('locale.wifi_country', 'Wi-Fi country', 'Two letters: US, GB, DE… Empty keeps the Pi\'s own.', 'US')}</div>
      <div class="wizard-row">${text('hotspot_name', 'The dash\'s own Wi-Fi name', 'The hotspot a phone joins to reach the dash.')}
      ${text('uploads.repo', 'GitHub repository for reports (optional)', 'owner/name. After each update the Pi uploads its diagnostics and the newest drive there. Empty: no uploads.', 'you/frogdash')}</div>
      ${choice('locale.units', 'Units on the gauges', [['us', 'US: mph, °F, psi, US mpg'], ['metric', 'Metric: km/h, °C, kPa, L/100 km']], 'Each screen can still pick its own under Dash management.')}`;
  }
  const LABELS = {'ecu.profile': 'ECU', 'ecu.bitrate': 'CAN bus speed', 'ecu.base_id': 'ECU first ID', 'can_hat.present': 'CAN HAT', 'can_hat.oscillator': 'HAT crystal',
    'can_hat.interrupt': 'HAT interrupt', 'gps.enabled': 'GPS', 'gps.transmit_on_can': 'GPS on CAN', 'camera.enabled': 'Reverse camera', 'camera.rotate': 'Camera picture',
    'dashcam.enabled': 'Dash cam', 'modules.gateway': 'Sensor gateway', 'modules.taillights': 'Taillights', 'modules.watermeth': 'Water/meth', 'power': 'Power board',
    'recording': 'Drive recording', 'tunerstudio': 'TunerStudio', 'terminal': 'Terminal', 'locale.timezone': 'Time zone', 'locale.wifi_country': 'Wi-Fi country',
    'hotspot_name': 'Hotspot name', 'uploads.repo': 'Reports to', 'screen.size': 'Screen', 'screen.mode': 'Force 1920 × 720', 'features.map': 'Map',
    'features.race': 'Race timer', 'locale.units': 'Units', 'preset': 'Preset'};
  function flat(object, prefix = '') {
    return Object.entries(object).flatMap(([k, v]) => v && typeof v === 'object' && !Array.isArray(v) ? flat(v, prefix + k + '.') : [[prefix + k, v]]);
  }
  const SHOWN = {
    'ecu.profile': v => ecuProfile(v).label, 'ecu.bitrate': v => `${v / 1000} kbit/s`, 'ecu.base_id': v => v ? `0x${v.toString(16).toUpperCase()}` : "The profile's default",
    'can_hat.oscillator': v => `${v / 1e6} MHz`, 'can_hat.interrupt': v => `GPIO ${v}`, 'camera.rotate': v => v ? 'Turned upside down' : 'As it comes',
    'power': v => v === 'pisugar3' ? 'PiSugar 3' : 'Ignition 12 V only', 'screen.mode': v => v === 'auto' ? 'Off' : 'On',
    'screen.size': v => v === 'auto' ? 'Something else (fits itself)' : v.replace('x', ' × '), 'locale.units': v => v === 'metric' ? 'Metric' : 'US', 'uploads.repo': v => v || 'No uploads',
  };
  const shown = (key, value) => SHOWN[key] ? SHOWN[key](value) : typeof value === 'boolean' ? (value ? 'On' : 'Off') : value === '' ? "(the Pi's own)" : String(value);
  function reviewPage() {
    const before = new Map(flat(data.profile)), after = new Map(flat(draft));
    const changed = key => JSON.stringify(before.get(key)) !== JSON.stringify(after.get(key));
    const keys = Object.keys(LABELS).filter(k => after.has(k));
    const order = [...keys.filter(changed), ...keys.filter(k => !changed(k))];
    const rows = order.map(k => `<tr class="${changed(k) ? 'changed' : ''}"><th>${esc(LABELS[k])}</th><td>${esc(shown(k, after.get(k)))}</td><td>${changed(k) ? `was ${esc(shown(k, before.get(k)))}` : ''}</td></tr>`).join('');
    const changes = keys.filter(changed).length;
    return `<p class="wizard-lead">${changes ? `${changes} change${changes === 1 ? '' : 's'} from how this dash is set up now, listed first.` : 'The same as this dash is set up now.'} Apply saves them (the old setup is kept as a backup) and sets up the Pi to match: it may install packages and restart the dash.</p>
      <div class="wizard-review"><table>${rows}</table></div><div id="wizard-progress" class="wizard-progress"></div>`;
  }
  const RENDER = {start: startPage, ecu: ecuPage, can: canPage, gps: gpsPage, cameras: camerasPage, modules: modulesPage, screen: screenPage, features: featuresPage, power: powerPage, locale: localePage, review: reviewPage};

  function render() {
    const name = PAGES[page];
    $('wizard-title').textContent = TITLES[name];
    $('wizard-steps').innerHTML = PAGES.map((p, i) => `<li><button type="button" data-wizard-page="${i}" aria-current="${i === page ? 'step' : 'false'}"${i > page && !draft.preset ? ' disabled' : ''}>${i + 1}</button></li>`).join('');
    $('wizard-body').innerHTML = RENDER[name]();
    $('wizard-back').disabled = page === 0 || applying;
    $('wizard-next').textContent = name === 'review' ? (DEMO ? 'Apply (preview)' : 'Apply') : 'Next';
    $('wizard-next').disabled = applying;
    $('wizard-note').textContent = DEMO ? 'Preview: the choices are not saved anywhere.' : '';
  }

  dialog.addEventListener('change', event => {
    const field = event.target.closest('[data-wizard-path]');
    if (!field) return;
    const path = field.dataset.wizardPath;
    let value = field.type === 'checkbox' ? field.checked : field.value;
    if (path === 'screen.mode') value = value ? '1920x720' : 'auto';
    if (field.tagName === 'SELECT' && field.dataset.kind === 'number') value = Number(value);
    if (path === 'ecu.base_id') value = /^0x[0-9a-f]+$/i.test(value.trim()) ? parseInt(value, 16) : Math.max(0, parseInt(value, 10) || 0);
    if (path === 'locale.wifi_country') value = value.trim().toUpperCase();
    set(path, value);
    if (path === 'gps.enabled' && !value) set('gps.transmit_on_can', false);
    render();
  });
  dialog.addEventListener('click', event => {
    const preset = event.target.closest('[data-wizard-preset]');
    if (preset) { draft = copy(data.presets[preset.dataset.wizardPreset]); draft.preset = preset.dataset.wizardPreset; render(); return; }
    const screen = event.target.closest('[data-wizard-screen]');
    if (screen) {
      draft.screen.size = screen.dataset.wizardScreen;
      if (draft.screen.size !== '1920x720') draft.screen.mode = 'auto';
      render(); return;
    }
    const power = event.target.closest('[data-wizard-power]');
    if (power) { draft.power = power.dataset.wizardPower; render(); return; }
    const ecu = event.target.closest('[data-wizard-ecu]');
    if (ecu) {
      const chosen = ecuProfile(ecu.dataset.wizardEcu);
      draft.ecu.profile = chosen.id; draft.ecu.bitrate = chosen.bitrate || 500000; draft.ecu.base_id = 0;
      if (chosen.id !== 'megasquirt') draft.modules.watermeth = false;
      if (!chosen.tuner?.runs_on_dash) draft.tunerstudio = false;
      render(); return;
    }
    const step = event.target.closest('[data-wizard-page]');
    if (step && !applying) { page = Number(step.dataset.wizardPage); render(); }
  });
  $('wizard-back').onclick = () => { if (page > 0) { page--; render(); } };
  $('wizard-next').onclick = () => { if (PAGES[page] === 'review') apply(); else { page++; render(); } };
  $('wizard-close').onclick = () => { clearInterval(poll); poll = null; dialog.close(); };

  function progress(html) { const box = $('wizard-progress'); if (box) box.innerHTML = html; }
  function steps(setup) {
    return (setup?.steps || []).map(s => `<li data-result="${esc(s.result)}"><b>${esc(s.name)}</b> ${esc(s.result)}${s.detail ? ` · ${esc(s.detail)}` : ''}</li>`).join('');
  }
  async function apply() {
    applying = true; render();
    if (DEMO) {
      const parts = ['System profile', 'CAN board', 'CAN bus speed', 'GPS', 'Dash options'];
      for (let i = 1; i <= parts.length; i++) {
        progress(`<p>Setting up the Pi… (preview)</p><ol>${parts.slice(0, i).map(p => `<li data-result="done"><b>${p}</b> done</li>`).join('')}</ol>`);
        await new Promise(r => setTimeout(r, 450));
      }
      progress('<p class="good">On a real dash the choices would now be saved and the Pi set up to match. Nothing was saved in the preview.</p>');
      applying = false; $('wizard-next').disabled = true; $('wizard-back').disabled = false; return;
    }
    try {
      const response = await fetch('/system', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({profile: draft})});
      if (!response.ok) throw new Error(await response.text());
    } catch (error) {
      applying = false; render(); progress(`<p class="bad">Not applied: ${esc(error.message || error)}</p>`); return;
    }
    const started = Date.now() / 1000 - 5;
    clearInterval(poll);
    poll = setInterval(async () => {
      try {
        const now = await load();
        const status = now.status && now.status.time >= started ? now.status : null;
        if (!status || now.pending) { progress('<p>Waiting for the Pi to pick up the request…</p>'); return; }
        progress(`<p class="${status.state === 'failed' ? 'bad' : status.state === 'done' ? 'good' : ''}">${esc(status.message)}</p><ol>${steps(now.setup)}</ol>`);
        if (status.state !== 'applying') {
          clearInterval(poll); poll = null; applying = false; data = now; $('wizard-back').disabled = false;
          $('wizard-next').disabled = status.state === 'done';
        }
      } catch { progress('<p>The dash is restarting with the new setup…</p>'); }
    }, 2000);
  }

  async function open(at = 0) {
    try {
      data = await load();
    } catch (error) {
      window.alert?.(`The setup could not be read: ${error.message || error}`); return;
    }
    draft = copy(data.profile); page = at; applying = false;
    render();
    if (!dialog.open) dialog.showModal();
    $('wizard-next').focus();
  }
  window.frogdashWizard = {open};
  document.addEventListener('click', event => { if (event.target.closest('[data-wizard-open]')) open(); });

  // A new install (or the preview opened with ?wizard, or ?wizard=2 for its second page) starts here.
  const asked = new URLSearchParams(location.search).get('wizard');
  if (asked !== null) open(Math.min(PAGES.length, Math.max(1, Number(asked) || 1)) - 1);
  else if (!DEMO) load().then(d => { if (d.profile && d.profile.configured === false) { data = d; open(); } }).catch(() => {});
})();
