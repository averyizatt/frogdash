/* Trip computer UI. Real counters and estimates run in the Pi service. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), GAL = 3.785411784, MI = 1.609344;
  const fields = [
    ['capacity_l', 'Tank capacity · US gal', 0, 66, .01, GAL], ['reserve_l', 'Range reserve · US gal', 0, 13, .01, GAL],
    ['injector_cc_min', 'Injector flow · cc/min', 0, 5000, 1], ['injectors', 'Total injector count', 0, 16, 1],
    ['pw2_injectors', 'Injectors using PW2', 0, 16, 1], ['pulses_per_rev', 'Pulses / injector / rev', 0, 8, .25],
    ['dead_ms', 'Effective dead time · ms', 0, 5, .01], ['correction', 'Fuel correction multiplier', .25, 4, .01]
  ];
  let latest = {}, connected = false, loaded = false, busy = false, previous = performance.now();
  let tripMessage = '', messageUntil = 0;
  const freshBucket = () => ({km: 0, moving_s: 0, engine_s: 0, fuel_l: 0, paired_km: 0, paired_l: 0, missing_s: 0});
  const simulated = {
    settings: {enabled: true, capacity_l: 15.4 * GAL, reserve_l: 3, injector_cc_min: 440, injectors: 4, pw2_injectors: 2, pulses_per_rev: .5, dead_ms: 1, correction: 1},
    counters: {a: {...freshBucket(), km: 84.2, moving_s: 3988, engine_s: 4200, fuel_l: 7.2, paired_km: 84.2, paired_l: 7.2}, b: {...freshBucket(), km: 286.1, moving_s: 13120, engine_s: 14000, fuel_l: 24.1, paired_km: 286.1, paired_l: 24.1}, total: {...freshBucket(), km: 1284.8}},
    learned: {km: 84.2, litres: 7.2}, remaining_l: 32, fuel_source: 'Simulated fuel amount', error: ''
  };
  const demo = () => latest.mode === 'demo';
  const view = () => demo() ? simulated : latest.trip;
  const fmt = (n, digits = 1) => Number.isFinite(n) ? n.toFixed(digits) : '—';
  const duration = seconds => `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m`;
  for (const [key, title, min, max, step] of fields) {
    const label = document.createElement('label'); label.textContent = title;
    const input = document.createElement('input'); Object.assign(input, {id: `fuel-${key}`, type: 'number', min, max, step, required: true}); label.append(input); $('fuel-fields').append(label);
  }
  function fill(settings) {
    fields.forEach(([key, , , , , factor = 1]) => { $(`fuel-${key}`).value = Number((settings[key] / factor).toFixed(2)); });
    $('fuel-enabled').checked = settings.enabled;
  }
  function simulate() {
    const now = performance.now(), dt = Math.min(1, (now - previous) / 1000); previous = now;
    const speed = latest.values?.['vehicle.speed_kph'], rpm = latest.values?.['engine.rpm'];
    simulated.gps_live = connected && speed?.quality === 'live';
    simulated.fuel_live = connected && rpm?.quality === 'live' && simulated.settings.enabled;
    // Representative economy only; demo does not calibrate an engine.
    const kph = simulated.gps_live ? speed.value : null;
    const flow = simulated.fuel_live ? rpm.value > 0 ? 6.5 : 0 : null;
    simulated.flow_lph = flow;
    const km = kph !== null ? kph * dt / 3600 : 0, litres = flow !== null ? flow * dt / 3600 : 0;
    for (const b of Object.values(simulated.counters)) {
      b.km += km; b.fuel_l += litres; b.moving_s += km > 0 ? dt : 0; b.engine_s += flow > 0 ? dt : 0;
      if (kph !== null && flow !== null) { b.paired_km += km; b.paired_l += litres; }
      b.mpg = b.paired_km >= 1 && b.paired_l >= .02 ? b.paired_km / b.paired_l * GAL / MI : null;
    }
    if (kph !== null && flow !== null) { simulated.learned.km += km; simulated.learned.litres += litres; }
    const economy = simulated.learned.km >= 1 && simulated.learned.litres >= .02 ? simulated.learned.km / simulated.learned.litres : null;
    if (simulated.remaining_l !== null) simulated.remaining_l = Math.max(0, simulated.remaining_l - litres);
    simulated.average_mpg = economy ? economy * GAL / MI : null;
    simulated.range_km = economy && simulated.remaining_l !== null && simulated.fuel_live ? Math.max(0, simulated.remaining_l - simulated.settings.reserve_l) * economy : null;
    simulated.instant_mpg = kph >= 1 && flow > .01 ? kph / flow * GAL / MI : null;
    simulated.coasting = kph >= 1 && flow === 0;
    const signals = {'trip.a_km': simulated.counters.a.km, 'trip.b_km': simulated.counters.b.km, 'trip.total_km': simulated.counters.total.km, 'fuel.range_km': simulated.range_km, 'fuel.instant_mpg': simulated.instant_mpg, 'fuel.average_mpg': simulated.average_mpg};
    for (const [key, value] of Object.entries(signals)) latest.values[key] = {value, quality: value === null ? 'unavailable' : 'live', source: 'Simulated trip computer'};
  }
  function render() {
    const t = view(); if (!t) return;
    if (!loaded) { fill(t.settings); loaded = true; }
    for (const name of ['a', 'b']) {
      const b = t.counters[name];
      $(`trip-${name}-distance`).innerHTML = `${fmt(b.km / MI)} <small>mi</small>`;
      $(`trip-${name}-detail`).textContent = `${duration(b.engine_s)} engine · ${fmt(b.moving_s ? b.km / MI / (b.moving_s / 3600) : null)} MPH moving avg · ${fmt(b.mpg)} US MPG${b.missing_s > 1 ? ' · partial data' : ''}`;
    }
    $('trip-total').textContent = `${fmt(t.counters.total.km / MI)} mi tracked since installation · GPS distance, separate from the vehicle odometer.`;
    $('trip-range').innerHTML = `${fmt(connected ? t.range_km === null ? null : t.range_km / MI : null, 0)} <small>mi</small>`;
    $('trip-instant').textContent = connected && t.coasting ? 'COAST' : fmt(connected ? t.instant_mpg : null);
    $('trip-average').textContent = fmt(t.average_mpg);
    $('trip-flow').textContent = `US MPG · ${fmt(connected && t.flow_lph !== null ? t.flow_lph / GAL : null, 2)} US gal/hr`;
    $('trip-fuel-source').textContent = `${fmt(connected && t.remaining_l !== null ? t.remaining_l / GAL : null, 2)} US gal · ${t.fuel_source}`;
    $('trip-quality').textContent = `${demo() ? 'SIMULATED · ' : ''}${!connected ? 'Connection lost · live estimates unavailable' : !t.settings.enabled ? 'Fuel estimate disabled · verify settings in Fuel setup' : !t.gps_live ? 'GPS unavailable · distance paused' : !t.fuel_live ? 'Fuel telemetry unavailable · fuel estimates paused' : 'Recording distance and estimated fuel use'}${t.average_mpg === null ? ' · learning economy (minimum 0.62 mi with fuel data)' : ''}`;
    $('trip-status').textContent = performance.now() < messageUntil ? tripMessage : t.error || (demo() ? 'Preview counters are simulated and reset when this page reloads.' : 'Trip A and B save on the Pi and keep recording with this menu closed.');
    $('fuel-inventory-status').textContent = `${t.fuel_source}${t.last_manual_l != null ? ` · last tracked amount ${fmt(t.last_manual_l / GAL, 2)} US gal` : ''}${t.error ? ' · ' + t.error : ''}`;
    for (const button of document.querySelectorAll('[data-trip-reset], #fuel-settings button, #fuel-amount-form button')) button.disabled = busy || !connected;
  }
  async function command(body, status) {
    busy = true; render(); $(status).textContent = 'Saving…';
    try {
      if (demo()) {
        if (body.reset) simulated.counters[body.reset] = freshBucket();
        else if (body.settings) {
          const p = body.settings;
          if (p.enabled && (!p.injector_cc_min || !p.injectors || !p.pulses_per_rev)) throw new Error('Enter injector flow, count and pulse rate first.');
          if (p.pw2_injectors > p.injectors || p.reserve_l >= p.capacity_l) throw new Error('Check injector bank count and tank reserve.');
          simulated.settings = p; simulated.learned = {km: 0, litres: 0}; simulated.remaining_l = null;
        } else {
          if (!simulated.settings.enabled || body.remaining_l < 0 || body.remaining_l > simulated.settings.capacity_l) throw new Error('Enable fuel estimation and enter an amount within tank capacity.');
          simulated.remaining_l = body.remaining_l;
        }
      } else {
        const response = await fetch('/trip', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal: AbortSignal.timeout(5000)});
        if (!response.ok) throw new Error(await response.text());
        latest.trip = await response.json();
      }
      $(status).textContent = view().error || (demo() ? 'Simulated change applied.' : 'Saved on the Pi.');
    } catch (error) { $(status).textContent = error.message; }
    finally {
      busy = false;
      if (status === 'trip-status') { tripMessage = $(status).textContent; messageUntil = performance.now() + 8000; }
    }
  }
  for (const button of document.querySelectorAll('[data-trip-reset]')) {
    let confirmUntil = 0, timer;
    button.onclick = () => {
      const name = button.dataset.tripReset;
      if (performance.now() > confirmUntil) {
        confirmUntil = performance.now() + 5000; button.textContent = `CONFIRM RESET ${name.toUpperCase()}`;
        timer = setTimeout(() => { confirmUntil = 0; button.textContent = `RESET ${name.toUpperCase()}`; }, 5000); return;
      }
      clearTimeout(timer); confirmUntil = 0; button.textContent = `RESET ${name.toUpperCase()}`; command({reset: name}, 'trip-status');
    };
  }
  $('fuel-settings').onsubmit = event => {
    event.preventDefault(); if (!$('fuel-settings').reportValidity()) return;
    const settings = {enabled: $('fuel-enabled').checked};
    fields.forEach(([key, , , , , factor = 1]) => { settings[key] = Number($(`fuel-${key}`).value) * factor; });
    command({settings}, 'fuel-settings-status');
  };
  $('fuel-amount-form').onsubmit = event => { event.preventDefault(); if ($('fuel-amount-form').reportValidity()) command({remaining_l: Number($('fuel-amount').value) * GAL}, 'fuel-settings-status'); };
  $('fuel-full').onclick = () => { if (view()) command({remaining_l: view().settings.capacity_l}, 'fuel-settings-status'); };
  window.addEventListener('frogdash-state', event => {
    latest = event.detail.snapshot; connected = event.detail.connected;
    if (demo()) simulate();
    render();
  });
})();
