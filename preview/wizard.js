/* The setup wizard: what this car has, chosen on the dash's own screen.

   It reads the Pi's system profile, the presets and the ECU profiles from /system, walks
   through the choices one page at a time and, on Apply, posts the whole profile back. A
   root-owned helper (tools/frogdash_config.py) saves it, keeping the old one as a backup,
   and runs the Pi setup to match; this page follows its progress. It opens by itself
   while the profile says the dash has not been set up (configured: false), and from Dash
   management > Setup checklist at any time.

   The reference car's own boards (gateway, taillights, water/meth) are not offered here:
   nobody else has them. They stay as the preset has them, and the car signals page offers
   them as a source only in a car that has them.

   In the published preview there is no Pi: window.frogdashSystemDemo (made from the real
   presets and ECU profiles by tools/update_preview.py) stands in, and Apply only shows
   what would happen. Open the preview with ?wizard (or ?wizard=3 for page 3) to start here. */
(() => {
  'use strict';
  const DEMO = window.frogdashSystemDemo || null;
  const PAGES = ['start', 'screen', 'ecu', 'can', 'gps', 'cameras', 'signals', 'features', 'power', 'locale', 'review'];
  const TITLES = {start: 'Start from', screen: 'Screen', ecu: 'Engine computer', can: 'CAN board', gps: 'GPS', cameras: 'Cameras',
                  signals: 'Car signals', features: 'On the dash', power: 'Power', locale: 'Place, units and network', review: 'Review and apply'};
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
  // Car signals (hardware/frogdash/inputs.py): the dash value each stands for, and the ECU
  // reading that can give it.
  const SIGNALS = [
    ['turn_left', 'Left turn signal', 'ecu.turn_left'], ['turn_right', 'Right turn signal', 'ecu.turn_right'],
    ['brake', 'Brake', 'ecu.brake_pedal'], ['lights', 'Lights', 'ecu.headlights'], ['reverse', 'Reverse', 'ecu.reverse'],
    ['fuel', 'Fuel level', 'ecu.fuel_level_pct'],
  ];
  // Pi pins free for a car signal: not I2C (2, 3), SPI0 (7-11) or the UART (14, 15).
  const FREE_PINS = [4, 5, 6, 12, 13, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27];
  const WAVESHARE = {present: true, oscillator: 12000000, interrupt: 25};
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

  function ecuProfile(id = draft.ecu.profile) {
    if (id === 'custom') return {id, label: 'Custom ECU', bitrate: draft.ecu.bitrate, offers: data.custom?.offers || [], ...(data.custom?.missing ? {} : data.custom || {})};
    return data.ecu.profiles.find(p => p.id === id) || {id, label: id};
  }
  const offers = key => (ecuProfile().offers || []).includes(key);

  // --- Fields ---
  function toggle(path, label, help = '', disabled = false, checked = get(path)) {
    return `<label class="wizard-toggle${disabled ? ' off' : ''}"><input type="checkbox" data-wizard-path="${path}"${checked ? ' checked' : ''}${disabled ? ' disabled' : ''}>
      <span><b>${esc(label)}</b>${help ? `<small>${help}</small>` : ''}</span></label>`;
  }
  function choice(path, label, options, help = '') {
    const now = String(get(path));
    return `<label class="wizard-field"><span>${esc(label)}</span><select data-wizard-path="${path}" data-kind="${typeof get(path)}">${options.map(([v, text]) =>
      `<option value="${esc(v)}"${String(v) === now ? ' selected' : ''}>${esc(text)}</option>`).join('')}</select>${help ? `<small>${help}</small>` : ''}</label>`;
  }
  function text(path, label, help = '', placeholder = '', value = get(path)) {
    return `<label class="wizard-field"><span>${esc(label)}</span><input type="text" data-wizard-path="${path}" value="${esc(value)}" placeholder="${esc(placeholder)}" autocomplete="off" spellcheck="false">${help ? `<small>${help}</small>` : ''}</label>`;
  }
  // Big buttons for one choice of a few (data-wizard-pick="path" data-value="...").
  function cards(path, options, extraClass = '') {
    return `<div class="wizard-cards ${extraClass}">${options.map(([value, title, help]) =>
      `<button type="button" class="wizard-card" data-wizard-pick="${path}" data-value="${esc(value)}" aria-pressed="${String(get(path)) === String(value)}"><b>${esc(title)}</b><small>${help}</small></button>`).join('')}</div>`;
  }

  // --- Pages ---
  const PRESET_TEXT = {
    generic: ['A new build', 'Nothing assumed: choose your screen, ECU and parts on the next pages.'],
    foxbody: ['The reference Foxbody', 'The car Frogdash was built in, with its own boards: MicroSquirt, GPS, PiSugar 3 and a 1920 × 720 screen.'],
  };
  function startPage() {
    const names = Object.keys(data.presets);
    return `<p class="wizard-lead">Pick the closest starting point. Every choice can be changed on the pages that follow, and again later from Dash management.</p>
      <div class="wizard-cards">${names.map(name => {
        const [title, help] = PRESET_TEXT[name] || [name, 'A preset in presets/.'];
        return `<button type="button" class="wizard-card" data-wizard-preset="${esc(name)}" aria-pressed="${draft.preset === name}"><b>${esc(title)}</b><small>${esc(help)}</small></button>`;
      }).join('')}</div>`;
  }
  function screenPage() {
    const size = get('screen.size');
    const items = SCREENS.map(([key, title, help]) => {
      let picture = '<span class="wizard-screen-any">Any size</span>', fits = '';
      if (key !== 'auto') {
        const [w, h] = key.split('x').map(Number);
        const wide = w / h >= 2.4;             // Wider than the picture's frame: fit its width, else its height
        const innerW = Math.min(1, (h * 8 / 3) / w) * 100, innerH = Math.min(1, (w * 3 / 8) / h) * 100;
        picture = `<span class="wizard-screen" style="${wide ? 'width:100%' : 'height:100%'};aspect-ratio:${w}/${h}"><span class="wizard-screen-dash" style="width:${innerW}%;height:${innerH}%"></span></span>`;
        fits = `<i>${Math.round(Math.min(w / 1920, h / 720) * 100)} % of full size</i>`;
      }
      return `<button type="button" class="wizard-card screen-card" data-wizard-screen="${key}" aria-pressed="${size === key}">
        <span class="wizard-screen-frame">${picture}</span><b>${esc(title)}</b><small>${esc(help)}</small><span class="wizard-tags">${fits}</span></button>`;
    }).join('');
    const named = size === 'auto' ? 'the size' : size.replace('x', ' × ');
    return `<p class="wizard-lead">Which screen is the dash on? The picture shows how the dash fits it: green is the dash, black the bars.</p>
      <div class="wizard-cards screen-cards">${items}</div>
      ${toggle('screen.mode', `Force ${named} at boot`, size === 'auto' ? 'Pick a size above to force it.' : 'For a screen that does not describe itself properly: the Pi is told the mode before the screen answers. Tried once first; if the picture is wrong it goes back by itself.', size === 'auto', get('screen.mode') !== 'auto')}`;
  }
  // The ECU's logo when one is installed (hardware/ui/ecu-logos), else its name as a badge.
  function logo(p) {
    const name = p.id === 'custom' ? 'Custom' : (p.label || p.id).replace(/ (Infinity|EMU|Terminator.*|Sniper|Elite.*)$/i, '');
    return p.logo ? `<span class="ecu-logo"><img src="${esc(p.logo)}" alt=""></span>` : `<span class="ecu-logo ecu-logo-text${p.id === 'custom' ? ' custom' : ''}">${esc(name)}</span>`;
  }
  function ecuPage() {
    const active = ecuProfile();
    const list = [...data.ecu.profiles.filter(p => !p.error), {id: 'custom', label: 'Custom ECU', models: ['Any ECU that broadcasts on CAN: describe its frames yourself']}];
    const items = list.map(p => `<button type="button" class="wizard-card ecu-card" data-wizard-ecu="${esc(p.id)}" aria-pressed="${p.id === draft.ecu.profile}">
        ${logo(p)}<b>${esc(p.label)}</b><small>${esc((p.models || []).join(' · ') || p.manufacturer || '')}</small></button>`).join('');
    let detail;
    if (active.id === 'custom') {
      const ready = data.custom && !data.custom.missing;
      detail = `<h3>Custom ECU</h3><p>${ready ? `Your profile is in place: ${esc(data.custom.label)}, ${data.custom.signals} readings.`
        : `Describe your ECU's CAN frames in a profile and save it as <code>${esc(data.custom?.path || '/etc/frogdash/ecu/custom.json')}</code> (the format is in docs/ecu-support.md). Until then the dash reads nothing from the ECU.`}</p>
        <div class="wizard-row">${choice('ecu.bitrate', 'CAN bus speed', [[125000, '125 kbit/s'], [250000, '250 kbit/s'], [500000, '500 kbit/s'], [1000000, '1 Mbit/s']], 'The speed your ECU\'s CAN runs at.')}</div>`;
    } else {
      const base = active.base ? text('ecu.base_id', `First CAN ID (${active.base.setting || 'set in the ECU'})`, `0 uses the default, ${esc(active.base.default)}. Write it as 0x400 or as a number.`) : '';
      detail = `<h3>${esc(active.label)}</h3>${(active.setup || []).length ? `<p><b>Set in the ECU:</b></p><ul>${active.setup.map(s => `<li>${esc(s)}</li>`).join('')}</ul>` : ''}
        <p class="wizard-small">CAN bus at ${(active.bitrate || 500000) / 1000} kbit/s${active.extended ? ', 29-bit IDs' : ''}: set to match.</p>${base ? `<div class="wizard-row">${base}</div>` : ''}`;
    }
    return `<p class="wizard-lead">Which engine computer is on the CAN bus?</p>
      <div class="wizard-cards ecu-cards">${items}</div><div class="wizard-detail">${detail}</div>`;
  }
  function canPage() {
    const bus = data.bus || {};
    const live = bus.connected ? `${bus.ids_heard || 0} CAN IDs heard in the last 3 s, ${bus.ecu_ids_heard || 0} of them the ECU's.` : 'The CAN interface is not up yet.';
    const other = get('can_hat.board') === 'other';
    const usb = other && !get('can_hat.present');
    return `<p class="wizard-lead">The board that connects the Pi to the CAN bus.</p>
      ${cards('can_hat.board', [['waveshare', 'Waveshare RS485 CAN HAT', 'Sits on the Pi\'s pins: 12 MHz crystal, interrupt on GPIO 25. Set up for you.'],
                                ['other', 'Other', 'Another MCP2515 board on the pins, or a USB CAN adapter.']])}
      ${other ? `${cards('can_hat.present', [['true', 'MCP2515 board on the pins', 'Tell the Pi its crystal and interrupt pin.'], ['false', 'USB CAN adapter', 'A gs_usb or candleLight adapter: nothing to set.']])}
        ${usb ? '' : `<div class="wizard-row">${choice('can_hat.oscillator', 'Crystal on the board', [[8000000, '8 MHz'], [12000000, '12 MHz'], [16000000, '16 MHz'], [20000000, '20 MHz']], 'Printed on the silver crystal next to the MCP2515.')}
        ${choice('can_hat.interrupt', 'Interrupt pin', [25, 24, 23, 22, 6, 5].map(n => [n, `GPIO ${n}`]), 'The pin the board\'s INT is wired to.')}</div>`}` : ''}
      <div class="wizard-detail"><h3>On the bus now</h3><p id="wizard-live">${live}</p><p class="wizard-small">A change to the board needs the Pi restarted; this check then shows whether frames arrive.</p></div>`;
  }
  function gpsPage() {
    const can = get('gps.source') === 'can';
    const has = offers('ecu.gps_latitude');
    return `<p class="wizard-lead">GPS gives the map, lap timing, speed and the clock when there is no internet.</p>
      ${cards('gps.source', [['usb', 'USB GPS receiver', 'A u-blox or any receiver gpsd knows, plugged into the Pi.'],
                             ['can', 'GPS from the CAN bus', 'An ECU or another device with its own GPS sends position over CAN.'],
                             ['none', 'No GPS', 'Speed from the ECU or a sensor; no map or lap timing.']])}
      ${can ? `<div class="wizard-detail"><p>${has ? `${esc(ecuProfile().label)} sends its GPS position: the dash uses it.`
        : `The ${esc(ecuProfile().label)} profile has no GPS position. A custom ECU profile can add it (readings ecu.gps_latitude, ecu.gps_longitude, ecu.gps_heading_deg).`}</p></div>` : ''}`;
  }
  function camerasPage() {
    return `<p class="wizard-lead">Cameras are optional. The reverse camera opens by itself on the reverse signal.</p>
      ${toggle('camera.enabled', 'Reverse camera', 'A Raspberry Pi camera on the Pi camera connector (CSI); it opens when reverse is engaged.')}
      ${choice('camera.rotate', 'Reverse camera picture', [[0, 'As it comes'], [180, 'Turned upside down']])}
      ${toggle('dashcam.enabled', 'Wi-Fi dash cam', 'A dash cam whose own Wi-Fi the dash joins with its second adapter, to show and save its picture.')}`;
  }
  // Where each car signal can come from in this car.
  function sources(name, ecuKey) {
    const own = name === 'fuel' ? get('modules.gateway') : get('modules.taillights');
    return [
      own && ['module', name === 'fuel' ? 'Frogdash gateway' : 'Frogdash taillight board'],
      offers(ecuKey) && ['ecu', `From the ECU`],
      name === 'fuel' ? ['adc', 'Fuel sender (ADS1115)'] : ['gpio', 'Wired to a Pi pin'],
      ['can', 'A CAN message'],
      ['none', 'Not used'],
    ].filter(Boolean);
  }
  function signalRow([name, label, ecuKey]) {
    const spec = draft.signals[name], path = `signals.${name}`;
    const now = data.signals_now?.[name];
    const options = sources(name, ecuKey);
    if (!options.some(([v]) => v === spec.source)) spec.source = 'none';
    const pick = `<div class="signal-sources">${options.map(([v, t]) => `<button type="button" data-wizard-pick="${path}.source" data-value="${v}" aria-pressed="${spec.source === v}">${esc(t)}</button>`).join('')}</div>`;
    let fields = '';
    if (spec.source === 'gpio') {
      const taken = new Set([draft.can_hat.present ? draft.can_hat.interrupt : -1, ...SIGNALS.filter(([n]) => n !== name && draft.signals[n].source === 'gpio').map(([n]) => draft.signals[n].pin)]);
      const pins = FREE_PINS.filter(p => !taken.has(p));
      if (!pins.includes(spec.pin)) spec.pin = pins[0];
      fields = `${choice(`${path}.pin`, 'Pi pin', pins.map(p => [p, `GPIO ${p}`]))}
        ${toggle(`${path}.active_low`, 'On when pulled to ground', 'Most optocoupler boards: the signal\'s 12 V lights the opto, which pulls the pin low.')}`;
    } else if (spec.source === 'adc') {
      fields = `${choice(`${path}.adc_channel`, 'ADS1115 input', [0, 1, 2, 3].map(n => [n, `A${n}`]))}
        ${text(`${path}.empty_mv`, 'Volts when empty', '', '0.5', (spec.empty_mv / 1000).toFixed(2))}
        ${text(`${path}.full_mv`, 'Volts when full', 'Measure at the ADS1115 input with the tank empty and full.', '3.0', (spec.full_mv / 1000).toFixed(2))}`;
    } else if (spec.source === 'can') {
      fields = `${text(`${path}.can_id`, 'CAN ID', 'As 0x3A0 or a number.', '0x3A0', spec.can_id ? '0x' + spec.can_id.toString(16).toUpperCase() : '')}
        ${name === 'fuel' ? `${choice(`${path}.byte`, 'Byte', [0, 1, 2, 3, 4, 5, 6, 7].map(n => [n, `Byte ${n}`]))}${choice(`${path}.full_raw`, 'Full tank is', [[100, '100 (percent)'], [255, '255']])}`
          : choice(`${path}.bit`, 'Bit', Array.from({length: 64}, (_, n) => [n, `Byte ${n >> 3}, bit ${n & 7}`]))}`;
    } else if (spec.source === 'ecu') {
      fields = `<p class="wizard-small">${esc(ecuProfile().label)} sends it.</p>`;
    }
    const reading = now ? (now.problem ? `<i class="bad">${esc(now.problem)}</i>` : now.value === null || now.value === undefined ? '<i>No reading yet</i>'
      : `<i class="good">Now: ${name === 'fuel' ? `${esc(now.value)} %` : now.value ? 'ON' : 'off'}</i>`) : '';
    return `<div class="signal-row"><div class="signal-head"><b>${esc(label)}</b>${reading}</div>${pick}${fields ? `<div class="signal-fields">${fields}</div>` : ''}</div>`;
  }
  function signalsPage() {
    return `<p class="wizard-lead">Where the dash gets the turn signals, brake, lights, reverse and fuel level. <b>Never connect 12 V to a Pi pin:</b> use an optocoupler board (docs/car-signals.md). "Now" shows each reading as the dash is set up at the moment.</p>
      <div class="signal-grid">${SIGNALS.map(signalRow).join('')}</div>`;
  }
  function featuresPage() {
    const ecu = ecuProfile(), tuner = ecu.tuner && {...ecu.tuner, name: ecu.tuner.name.split(/[;(]/)[0].trim()};   // NSP, not its whole description
    const gps = get('gps.source') !== 'none';
    const tuning = !tuner ? `<p class="wizard-small">No tuning software is known for ${esc(ecu.label)}.</p>`
      : tuner.runs_on_dash ? toggle('tunerstudio', `Install ${tuner.name}`, `Java and ${esc(tuner.name)} on the Pi: tune from the dash screen over the ECU's USB serial cable.`)
      : toggle('windows_tuner', `Install ${tuner.name} on the dash (experimental)`, `${esc(tuner.name)} is a Windows program: on the Pi it would run through Box64 and Wine, and its USB connection may not work. <b>Not available yet:</b> choose it now and it is installed once that is ready. Until then, tune from a laptop (${esc(tuner.connection || 'USB')}); the dash keeps reading the bus while you tune.`);
    return `<p class="wizard-lead">What the dash shows and does.</p>
      <div class="wizard-row">${toggle('features.map', 'Map', gps ? 'The moving map with the offline tiles.' : 'The map needs GPS for where the car is (the GPS page).')}
      ${toggle('features.race', 'Race timer', gps ? 'Lap and drag timing from GPS, with results kept on the Pi.' : 'Timing needs GPS (the GPS page).')}</div>
      <div class="wizard-row">${toggle('recording', 'Record every drive', 'MLG logs for TunerStudio and MegaLogViewer, kept on the Pi, and the drive review.')}
      ${toggle('terminal', 'Terminal on the dash', 'A Linux shell with sudo, for someone who knows what they are doing.')}</div>
      <div class="wizard-detail"><h3>Tuning software</h3>${tuning}</div>`;
  }
  function powerPage() {
    return `<p class="wizard-lead">How the Pi gets power. Pulling 12 V with the key can damage the SD card; a power board lets the Pi shut down cleanly.</p>
      ${cards('power', [['none', 'Ignition 12 V only', 'The Pi is on while the key is. Simple; a sudden power cut can corrupt the card.'],
                        ['pisugar3', 'PiSugar 3', 'A battery board: at key-off the dash counts down and the Pi shuts down by itself. Installs its driver.']])}`;
  }
  function localePage() {
    return `<div class="wizard-row">${text('locale.timezone', 'Time zone', 'As in the tz database. Empty keeps the Pi\'s own.', 'America/Denver')}
      ${text('locale.wifi_country', 'Wi-Fi country', 'Two letters: US, GB, DE… Empty keeps the Pi\'s own.', 'US')}</div>
      <div class="wizard-row">${text('hotspot_name', 'The dash\'s own Wi-Fi name', 'The hotspot a phone joins to reach the dash.')}
      ${text('uploads.repo', 'GitHub repository for reports (optional)', 'owner/name. After each update the Pi uploads its diagnostics and the newest drive there. Empty: no uploads.', 'you/frogdash')}</div>
      ${choice('locale.units', 'Units on the gauges', [['us', 'US: mph, °F, psi, US mpg'], ['metric', 'Metric: km/h, °C, kPa, L/100 km']], 'Each screen can still pick its own under Dash management.')}`;
  }

  // --- Review ---
  const LABELS = {'screen.size': 'Screen', 'screen.mode': 'Forced at boot', 'ecu.profile': 'ECU', 'ecu.bitrate': 'CAN bus speed', 'ecu.base_id': 'ECU first ID',
    'can_hat.board': 'CAN board', 'can_hat.present': 'CAN board type', 'can_hat.oscillator': 'Board crystal', 'can_hat.interrupt': 'Board interrupt',
    'gps.source': 'GPS', 'camera.enabled': 'Reverse camera', 'camera.rotate': 'Camera picture', 'dashcam.enabled': 'Dash cam',
    ...Object.fromEntries(SIGNALS.map(([n, l]) => [`signals.${n}.source`, l])),
    'features.map': 'Map', 'features.race': 'Race timer', 'recording': 'Drive recording', 'terminal': 'Terminal', 'tunerstudio': 'TunerStudio',
    'windows_tuner': 'Windows tuner on the dash', 'power': 'Power', 'locale.timezone': 'Time zone', 'locale.wifi_country': 'Wi-Fi country', 'locale.units': 'Units',
    'hotspot_name': 'Hotspot name', 'uploads.repo': 'Reports to', 'preset': 'Preset'};
  function flat(object, prefix = '') {
    return Object.entries(object).flatMap(([k, v]) => v && typeof v === 'object' && !Array.isArray(v) ? flat(v, prefix + k + '.') : [[prefix + k, v]]);
  }
  function signalText(profile, name) {
    const s = profile.signals?.[name];
    if (!s) return '';
    return {module: name === 'fuel' ? 'Frogdash gateway' : 'Frogdash taillight board', ecu: 'From the ECU', none: 'Not used',
            gpio: `Pi pin GPIO ${s.pin}${s.active_low ? ' (on when low)' : ' (on when high)'}`,
            adc: `ADS1115 A${s.adc_channel}, ${(s.empty_mv / 1000).toFixed(2)} V empty, ${(s.full_mv / 1000).toFixed(2)} V full`,
            can: `CAN 0x${s.can_id.toString(16).toUpperCase()} ${name === 'fuel' ? `byte ${s.byte}` : `byte ${s.bit >> 3} bit ${s.bit & 7}`}`}[s.source] || s.source;
  }
  const SHOWN = {
    'ecu.profile': v => ecuProfile(v).label, 'ecu.bitrate': v => `${v / 1000} kbit/s`, 'ecu.base_id': v => v ? `0x${v.toString(16).toUpperCase()}` : "The profile's default",
    'can_hat.board': v => v === 'waveshare' ? 'Waveshare RS485 CAN HAT' : 'Other', 'can_hat.present': v => v ? 'MCP2515 on the pins' : 'USB adapter',
    'can_hat.oscillator': v => `${v / 1e6} MHz`, 'can_hat.interrupt': v => `GPIO ${v}`, 'camera.rotate': v => v ? 'Turned upside down' : 'As it comes',
    'gps.source': v => ({usb: 'USB receiver', can: 'From the CAN bus', none: 'None'}[v] || v),
    'power': v => v === 'pisugar3' ? 'PiSugar 3' : 'Ignition 12 V only', 'screen.mode': v => v === 'auto' ? 'No' : `Yes, ${v.replace('x', ' × ')}`,
    'screen.size': v => v === 'auto' ? 'Something else (fits itself)' : v.replace('x', ' × '), 'locale.units': v => v === 'metric' ? 'Metric' : 'US', 'uploads.repo': v => v || 'No uploads',
  };
  const shown = (key, value) => SHOWN[key] ? SHOWN[key](value) : typeof value === 'boolean' ? (value ? 'On' : 'Off') : value === '' ? "(the Pi's own)" : String(value);
  function reviewPage() {
    const before = new Map(flat(data.profile)), after = new Map(flat(draft));
    const signal = key => key.match(/^signals\.(\w+)\.source$/)?.[1];
    // A signal row is one change whichever of its fields changed, and shows them all.
    const changed = key => signal(key) ? signalText(data.profile, signal(key)) !== signalText(draft, signal(key)) : JSON.stringify(before.get(key)) !== JSON.stringify(after.get(key));
    const value = (profile, map, key) => signal(key) ? signalText(profile, signal(key)) : shown(key, map.get(key));
    const keys = Object.keys(LABELS).filter(k => after.has(k));
    const order = [...keys.filter(changed), ...keys.filter(k => !changed(k))];
    const rows = order.map(k => `<tr class="${changed(k) ? 'changed' : ''}"><th>${esc(LABELS[k])}</th><td>${esc(value(draft, after, k))}</td><td>${changed(k) ? `was ${esc(value(data.profile, before, k))}` : ''}</td></tr>`).join('');
    const changes = keys.filter(changed).length;
    return `<p class="wizard-lead">${changes ? `${changes} change${changes === 1 ? '' : 's'} from how this dash is set up now, listed first.` : 'The same as this dash is set up now.'} Apply saves them (the old setup is kept as a backup) and sets up the Pi to match: it may install packages and restart the dash.</p>
      <div class="wizard-review"><table>${rows}</table></div><div id="wizard-progress" class="wizard-progress"></div>`;
  }
  const RENDER = {start: startPage, screen: screenPage, ecu: ecuPage, can: canPage, gps: gpsPage, cameras: camerasPage, signals: signalsPage,
                  features: featuresPage, power: powerPage, locale: localePage, review: reviewPage};

  function render() {
    const name = PAGES[page];
    const scroll = $('wizard-body').scrollTop;
    $('wizard-title').textContent = TITLES[name];
    $('wizard-steps').innerHTML = PAGES.map((p, i) => `<li><button type="button" data-wizard-page="${i}" title="${TITLES[p]}" aria-current="${i === page ? 'step' : 'false'}">${i + 1}</button></li>`).join('');
    $('wizard-body').innerHTML = RENDER[name]();
    $('wizard-body').scrollTop = render.page === page ? scroll : 0;
    render.page = page;
    $('wizard-back').disabled = page === 0 || applying;
    $('wizard-next').textContent = name === 'review' ? (DEMO ? 'Apply (preview)' : 'Apply') : 'Next';
    $('wizard-next').disabled = applying;
    $('wizard-note').textContent = DEMO ? 'Preview: the choices are not saved anywhere.' : '';
  }

  // Typed values: numbers stay numbers, CAN IDs read as hex or decimal, volts as millivolts.
  function typed(field, path, raw) {
    if (field.type === 'checkbox') return path === 'screen.mode' ? (raw ? get('screen.size') : 'auto') : raw;
    if (field.tagName === 'SELECT' && field.dataset.kind === 'number') return Number(raw);
    if (path === 'ecu.base_id' || path.endsWith('.can_id')) {
      const t = String(raw).trim();
      return Math.max(0, /^0x[0-9a-f]+$/i.test(t) ? parseInt(t, 16) : parseInt(t, 10) || 0);
    }
    if (path.endsWith('_mv')) return Math.max(0, Math.min(5000, Math.round((parseFloat(String(raw).replace(',', '.')) || 0) * 1000)));
    if (path === 'locale.wifi_country') return String(raw).trim().toUpperCase();
    return raw;
  }
  dialog.addEventListener('change', event => {
    const field = event.target.closest('[data-wizard-path]');
    if (!field) return;
    const path = field.dataset.wizardPath;
    set(path, typed(field, path, field.type === 'checkbox' ? field.checked : field.value));
    render();
  });
  dialog.addEventListener('click', event => {
    const preset = event.target.closest('[data-wizard-preset]');
    if (preset) { draft = copy(data.presets[preset.dataset.wizardPreset]); draft.preset = preset.dataset.wizardPreset; render(); return; }
    const screen = event.target.closest('[data-wizard-screen]');
    if (screen) {
      const forced = draft.screen.mode !== 'auto';
      draft.screen.size = screen.dataset.wizardScreen;
      draft.screen.mode = forced && draft.screen.size !== 'auto' ? draft.screen.size : 'auto';
      render(); return;
    }
    const pick = event.target.closest('[data-wizard-pick]');
    if (pick) {
      const path = pick.dataset.wizardPick, raw = pick.dataset.value;
      set(path, raw === 'true' ? true : raw === 'false' ? false : raw);
      if (path === 'can_hat.board' && raw === 'waveshare') Object.assign(draft.can_hat, WAVESHARE);
      if (path === 'gps.source') { draft.gps.enabled = raw === 'usb'; if (raw !== 'usb') draft.gps.transmit_on_can = false; }
      render(); return;
    }
    const ecu = event.target.closest('[data-wizard-ecu]');
    if (ecu) {
      const chosen = ecuProfile(ecu.dataset.wizardEcu);
      draft.ecu.profile = chosen.id; draft.ecu.base_id = 0;
      if (chosen.id !== 'custom') draft.ecu.bitrate = chosen.bitrate || 500000;
      if (!chosen.tuner?.runs_on_dash) draft.tunerstudio = false;
      if (chosen.tuner?.runs_on_dash || !chosen.tuner) draft.windows_tuner = false;
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

  // A new install (or the preview opened with ?wizard, or ?wizard=3 for page 3) starts here.
  const asked = new URLSearchParams(location.search).get('wizard');
  if (asked !== null) open(Math.min(PAGES.length, Math.max(1, Number(asked) || 1)) - 1);
  else if (!DEMO) load().then(d => { if (d.profile && d.profile.configured === false) { data = d; open(); } }).catch(() => {});
})();
