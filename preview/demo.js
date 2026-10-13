/* Design preview only. No network, GPS, or hardware access. */
(() => {
  'use strict';
  const readings = {
    'engine.rpm': 3450, 'vehicle.speed_kph': 76, 'gps.satellites': 9,
    'engine.coolant_c': 96, 'engine.iat_c': 40, 'vehicle.battery_v': 14.2,
    'engine.boost_kpa': 85, 'engine.afr': 12.4, 'ecu.afr_target': 12.5,
    'engine.ego_correction_pct': 100, 'engine.oil_pressure_psi': 62,
    'engine.fuel_pressure_psi': 39, 'vehicle.fuel_pct': null,
    'meth.state': 'OFF', 'meth.duty_pct': 0, 'meth.tank_pct': 85,
    'meth.flow': 'OK', 'meth.fault_flags': 0,
    'lighting.turn_left': false, 'lighting.turn_right': false,
    'lighting.brake': false, 'lighting.running': false, 'lighting.reverse': false,
    'lighting.brightness': 180, 'lighting.left_state': 'RUNNING', 'lighting.right_state': 'RUNNING',
    'knock.energy': 23, 'knock.baseline': 18, 'knock.threshold': 50,
    'knock.enabled': true, 'knock.learned': true, 'knock.warning': false,
    'knock.critical': false, 'knock.event_count': 0, 'knock.last_rpm': 0,
    'knock.last_boost_kpa': 0, 'knock.config.threshold_offset': 20,
    'knock.config.multiplier': 2, 'knock.config.center_hz': 6000,
    'knock.config.flags': 3, 'knock.config.min_rpm': 0, 'knock.config.min_map_kpa': 120,
    'knock.config.debounce_ms': 300, 'knock.config.gain': 1, 'knock.config.bandwidth_hz': 1500, 'knock.config.bore_mm': 96,
    'knock.band_share_pct': 14, 'knock.hook.bias_adc': 512, 'knock.hook.envelope': 22,
    'interior.upper.color': '#ffb46b', 'interior.upper.brightness': 0,
    'interior.lower.color': '#ffb46b', 'interior.lower.brightness': 0
  };
  let scenario = 'drive', paused = false, elapsed = 3, previous = performance.now();
  let tick = 0, testTimer, lightingMode = 0;
  // Simulated water/meth tuning (can_protocol.h extension 5); rules come from meth-tune.js.
  // The relay board is simulated unless the address ends in ?meth=pwm (the ESP32 board).
  const mt = () => window.FrogdashMethTune;
  let mtLive = null, mtSaved = null, mtRevision = 1, mtAck = null;
  let mtDrive = new URLSearchParams(location.search).get('meth') === 'pwm' ? 'pwm' : 'relay';
  // Simulated knock controller. The ESP32 board (can_protocol.h extension 6: spectrum, the
  // knock frequency it finds, amplifier gain) unless the address ends in ?knock=nano.
  const knockSim = {esp32: new URLSearchParams(location.search).get('knock') !== 'nano', ringsAt: 6250, learnedFrom: 0, fixedStep: -1, top: 30, boreMm: 96};
  const KNOCK_ESP32_ONLY = ['knock.amp_gain', 'knock.bore', 'knock.relearn'];
  const KNOCK_SETTINGS = ['knock.threshold', 'knock.multiplier', 'knock.min_rpm', 'knock.min_map', 'knock.hold', 'knock.level_gain',
    'knock.center', 'knock.bandwidth', 'knock.auto_frequency', ...KNOCK_ESP32_ONLY];
  // Simulated taillight extras: show/demo/override/custom, parked-only and cleared when moving.
  const TL_STATES = ['OFF', 'RUNNING', 'BRAKE', 'TURN', 'REVERSE', 'BRAKE_TURN', 'HAZARD'];
  const TL_PARKED = ['lighting.show', 'lighting.demo', 'lighting.override', 'lighting.custom'];
  let tl = {show: null, override: null, customUntil: 0}, tlResult = null;
  // Simulated taillight settings (can_protocol.h extension 3), with a saved copy for revert.
  const TL_KEYS = {1: 'brightness', 2: 'brightness_dim', 3: 'turn_blink_ms', 4: 'turn_custom', 5: 'turn_sweep_ms', 6: 'turn_hold_ms',
    7: 'turn_off_ms', 8: 'brake_speed', 9: 'reverse_speed', 10: 'run_speed', 11: 'frame_ms', 12: 'brake_anim', 13: 'turn_anim',
    14: 'reverse_anim', 15: 'run_anim', 16: 'lens_preset', 17: 'startup_anim', 18: 'rest_mode', 19: 'show_speed', 20: 'show_anim', 21: 'show_mode'};
  const TL_DEFAULTS = {settings: {brightness: 255, brightness_dim: 15, turn_blink_ms: 700, turn_custom: 0, turn_sweep_ms: 350, turn_hold_ms: 200,
    turn_off_ms: 300, brake_speed: 100, reverse_speed: 100, run_speed: 100, frame_ms: 20, brake_anim: 0, turn_anim: 0, reverse_anim: 0,
    run_anim: 0, lens_preset: 1, startup_anim: 1, rest_mode: 0, show_speed: 100, show_anim: 0, show_mode: 0},
    colors: {brake: '#ff0000', turn: '#ff7a00', reverse: '#ffffff', running: '#ff0000'}, text: 'FOX BODY'};
  const tlCopy = value => JSON.parse(JSON.stringify(value));
  let tlSaved = tlCopy(TL_DEFAULTS), tlLive = tlCopy(TL_DEFAULTS), tlProfiles = [tlCopy(TL_DEFAULTS), null, null, null, null, null], tlRevision = 1, tlAck = null;
  // Keyframes model acceleration, brief gear changes, cruise, braking and idle.
  const cycle = [
    [0,0,900,-60], [2,5,1600,-30], [6,42,5200,70], [6.4,46,3300,0],
    [10,85,6000,100], [10.4,88,4100,5], [15,128,6100,100],
    [15.4,129,4500,10], [19,130,4400,-15], [23,78,3100,-65],
    [28,10,1150,-60], [30,0,900,-60], [34,0,900,-60]
  ];
  function drivingValues(seconds) {
    const t = seconds % 34;
    const index = cycle.findIndex((point, i) => i > 0 && point[0] >= t);
    const a = cycle[index - 1], b = cycle[index];
    const fraction = (t - a[0]) / (b[0] - a[0]);
    const [speed, rpm, boost] = [1,2,3].map(i => a[i] + (b[i] - a[i]) * fraction);
    const target = boost > 15 ? 12.3 : 14.7;
    return {
      'vehicle.speed_kph': speed, 'engine.rpm': Math.round(rpm),
      'engine.boost_kpa': boost, 'engine.afr': target + .12 * Math.sin(seconds * 2.2),
      'ecu.afr_target': target, 'engine.ego_correction_pct': 100 + 2 * Math.sin(seconds * .7),
      'engine.oil_pressure_psi': 23 + rpm * .007,
      'engine.fuel_pressure_psi': 39 + Math.max(0, boost) * .145,
      'engine.coolant_c': 93 + 2.5 * Math.sin(seconds / 15),
      'engine.iat_c': 34 + Math.max(0, boost) * .08,
      'vehicle.battery_v': 14.1 + .12 * Math.sin(seconds * .6),
      'vehicle.fuel_pct': Math.max(5, 72 - seconds / 240),
      'lighting.brake': t >= 19 && t < 30,
      'lighting.turn_left': t < 5 && Math.floor(seconds * 2) % 2 === 0,
      'lighting.turn_right': t >= 26 && t < 32 && Math.floor(seconds * 2) % 2 === 0,
      'knock.energy': Math.round(12 + rpm / 450 + 2 * Math.sin(seconds * 3))
    };
  }
  const motion = document.createElement('button');
  motion.id = 'demo-motion'; motion.type = 'button'; motion.className = 'demo-control';
  const park = document.createElement('button');
  park.id = 'demo-driving'; park.type = 'button'; park.className = 'demo-control';
  const controls = document.createElement('div'); controls.className = 'demo-playback';
  controls.setAttribute('role', 'group'); controls.setAttribute('aria-label', 'Simulated drive playback');
  controls.append(motion, park);
  document.getElementById('recording-badge').hidden = true;
  document.getElementById('recording-badge').before(controls);
  function playbackLabels() {
    motion.textContent = scenario === 'drive' && !paused ? 'Pause' : 'Play';
    motion.setAttribute('aria-label', scenario === 'drive' && !paused ? 'Pause simulated drive' : 'Play simulated drive');
    motion.setAttribute('aria-pressed', String(scenario === 'drive' && !paused));
    park.textContent = scenario === 'parked' ? 'Drive' : 'Park';
    park.setAttribute('aria-label', scenario === 'parked' ? 'Resume simulated driving' : 'Switch to simulated idle');
  }
  function setScenario(name) {
    if (!['drive', 'normal', 'warning', 'offline', 'vacuum', 'night', 'parked', 'reverse'].includes(name)) throw new Error('Unknown demo scenario');
    scenario = name; paused = false; previous = performance.now(); playbackLabels();
  }
  motion.onclick = () => {
    if (scenario !== 'drive') setScenario('drive');
    else { paused = !paused; previous = performance.now(); playbackLabels(); }
  };
  park.onclick = () => setScenario(scenario === 'parked' ? 'drive' : 'parked');
  playbackLabels();
  // Static scenarios remain available for repeatable design checks.
  // This entire transport is loaded only by the standalone preview.
  window.frogdashDemo = {scenario: setScenario, methPreset(values) { mtLive = {...mtLive, ...values}; mtRevision++; },
    knockController(kind) { knockSim.esp32 = kind !== 'nano'; },
    methDrive(drive) { mtDrive = drive === 'pwm' ? 'pwm' : 'relay'; mtRevision++; }};
  class FrogdashDemoSocket {
    static OPEN = 1;
    readyState = 1;
    constructor() {
      this.timer = setInterval(() => this.publish(), 100);
    }
    emit(message) { this.onmessage?.({data: JSON.stringify(message)}); }
    publish() {
      tick++;
      const now = performance.now();
      if (scenario === 'drive' && !paused && !document.hidden) elapsed += Math.min(.25, Math.max(0, (now - previous) / 1000));
      previous = now;
      const dynamic = scenario === 'drive' ? drivingValues(elapsed) : {};

      const current = {...readings,
        'vehicle.speed_kph': scenario === 'parked' ? 0 : scenario === 'reverse' ? 4 : readings['vehicle.speed_kph'],
        'lighting.reverse': scenario === 'reverse',
        'lighting.running': scenario === 'night',
        'lighting.left_state': scenario === 'night' ? 'RUNNING' : 'OFF',
        'lighting.right_state': scenario === 'night' ? 'RUNNING' : 'OFF',
        'knock.energy': scenario === 'warning' ? 75 : Math.round(23 + Math.sin(tick / 7) * 5),
        'knock.band_share_pct': scenario === 'warning' ? 71 : Math.round(14 + Math.sin(tick / 5) * 4),
        'knock.hook.envelope': scenario === 'warning' ? 96 : Math.round(22 + Math.sin(tick / 9) * 4),
        'knock.warning': scenario === 'warning',
        'engine.coolant_c': scenario === 'warning' ? 115 : readings['engine.coolant_c'],
        'engine.boost_kpa': scenario === 'vacuum' ? -55 : readings['engine.boost_kpa'],
        ...dynamic
      };
      if (scenario === 'reverse') Object.assign(current, {'engine.rpm': 950, 'engine.boost_kpa': -58});
      if (scenario === 'parked') Object.assign(current, {'engine.rpm': 900, 'engine.boost_kpa': -60, 'engine.afr': 14.7, 'ecu.afr_target': 14.7, 'vehicle.fuel_pct': drivingValues(elapsed)['vehicle.fuel_pct']});
      if (scenario === 'drive') for (const side of ['left', 'right']) current[`lighting.${side}_state`] = current[`lighting.turn_${side}`] ? 'TURN' : current['lighting.brake'] ? 'BRAKE' : 'OFF';
      const speed = current['vehicle.speed_kph'];
      const tlActive = tl.show !== null || tl.override || tl.customUntil > Date.now();
      if (tlActive && speed > 5) {
        tl = {show: null, override: null, customUntil: 0};
        tlResult = {action: 'lighting.clear', status: 'sent', message: 'Vehicle moving: taillight show/override cleared so turn signals work'};
      }
      if (!current['lighting.brake'] && !current['lighting.reverse']) {
        if (tl.customUntil > Date.now()) current['lighting.left_state'] = current['lighting.right_state'] = 'CUSTOM';
        else if (tl.show !== null) current['lighting.left_state'] = current['lighting.right_state'] = 'SHOW';
        else if (tl.override) [current['lighting.left_state'], current['lighting.right_state']] = tl.override.map(n => TL_STATES[n]);
      }
      // Stand-in controller: run time from boost, the dose limit, and the minimum RPM.
      if (!mtLive) { mtLive = {...mt().DEFAULTS}; mtSaved = {...mtLive}; }
      const boostPsi = current['engine.boost_kpa'] * .145037738, armed = readings['meth.state'] === 'ARMED';
      const mapKpa = 85 + current['engine.boost_kpa'], fuel = mt().fuelGPerMin(current['engine.rpm'], mapKpa);
      const belowBoost = boostPsi < mtLive.start_psi_x10 / 10;
      const early = armed && belowBoost && mtLive.early_rpm > 0 && current['engine.rpm'] >= mtLive.early_rpm && boostPsi >= -1.5;
      let hold = !armed ? 'DISARMED' : belowBoost && !early ? 'BELOW_BOOST' : current['engine.rpm'] < mtLive.min_rpm ? 'RPM_LOW' : 'NONE';
      const ramp = Math.min(1, Math.max(0, (boostPsi * 10 - mtLive.start_psi_x10) / (mtLive.full_psi_x10 - mtLive.start_psi_x10)));
      // Relay: on-time in each cycle. PWM: pump duty, reported as on-time out of 1000.
      const pwm = mtDrive === 'pwm', low = pwm ? mtLive.min_duty_pct * 10 : mtLive.min_on_ms, high = pwm ? mtLive.max_duty_pct * 10 : mtLive.max_on_ms;
      const period = pwm ? 1000 : mtLive.period_ms;
      let wanted = Math.round(low + (high - low) * ramp);
      const airC = 38 + Math.max(0, boostPsi) * 5;
      const heat = mtLive.hot_start_c > 0 && airC > mtLive.hot_start_c ?
        Math.round(low + (high - low) * Math.min(1, (airC - mtLive.hot_start_c) / (mtLive.hot_full_c - mtLive.hot_start_c))) : 0;
      const hotAir = heat > wanted;
      if (hotAir) wanted = heat;
      const share = Math.min(1, fuel * mtLive.max_dose_pct / 100 / mtLive.nozzle_ml_min);
      if (mtLive.max_dose_pct) wanted = Math.min(wanted, Math.floor(period * (pwm ? share * share : share)));
      const onMs = hold !== 'NONE' ? 0 : pwm ? (wanted >= low ? wanted : 0) : mt().relayOn(wanted, period);
      if (hold === 'NONE' && !onMs) hold = 'DOSE_LIMIT';
      if (onMs) { current['meth.state'] = 'SPRAYING'; current['meth.duty_pct'] = Math.round(onMs * 100 / period); }
      const flow = mtLive.nozzle_ml_min * (pwm ? mt().pwmFlow(onMs / 10) : onMs / period);
      const preC = airC, dropC = flow / 60 * 22;
      Object.assign(current, {'meth.pre_temp_c': Math.round(preC * 10) / 10, 'meth.post_temp_c': Math.round((preC - dropC) * 10) / 10,
        'meth.temp_drop_c': Math.round(dropC * 10) / 10, 'meth.hold': hold, 'meth.on_ms': onMs, 'meth.period_ms': period,
        'meth.flow_ml_min': Math.round(flow * 10) / 10, 'meth.dose_pct': fuel > 0 ? Math.round(flow / fuel * 1000) / 10 : null});
      // Stand-in knock controller: where it listens, its amplifier, and two spectra.
      const knockDetail = {supported: knockSim.esp32 && scenario !== 'offline', start_hz: 2000, step_hz: 300, normal: null, burst: null};
      {
        const boreHz = Math.round(1800000 / (Math.PI * knockSim.boreMm));
        const byHand = !(readings['knock.config.flags'] & 2), loud = scenario === 'warning';
        const learned = knockSim.esp32 && !byHand && performance.now() >= knockSim.learnedFrom;
        const filterHz = byHand ? readings['knock.config.center_hz'] : learned ? knockSim.ringsAt : boreHz;
        current['knock.config.center_hz'] = filterHz;
        current['knock.config.sample_rate_hz'] = knockSim.esp32 ? 38400 : 19200;
        const step = knockSim.fixedStep >= 0 ? knockSim.fixedStep : Math.min(knockSim.top, Math.max(0, Math.round(34 - current['engine.rpm'] / 240)));
        const bell = (hz, centre, width) => Math.exp(-(((hz - centre) / width) ** 2));
        const esp32 = knockSim.esp32 ? {
          'knock.amp.automatic': knockSim.fixedStep < 0, 'knock.amp.fixed': knockSim.fixedStep >= 0, 'knock.amp.ineffective': false,
          'knock.amp.overloaded': false, 'knock.amp.silent': false, 'knock.amp.gain': Math.round((1 + 10 * step / knockSim.top) * 10) / 10,
          'knock.amp.step': step, 'knock.amp.top_step': knockSim.top, 'knock.amp.rest_mv': 816,
          'knock.amp.swing_mv': Math.round((150 + 18 * Math.sin(tick / 11)) / 8) * 8, 'knock.amp.room_mv': 800,
          'knock.freq.learning': !byHand, 'knock.freq.learned': learned, 'knock.freq.second_active': true, 'knock.freq.filter_hz': filterHz,
          'knock.freq.found_hz': learned ? knockSim.ringsAt + 12 : null, 'knock.freq.agreement_pct': learned ? 84 : 0,
          'knock.freq.votes': learned ? 120 : byHand ? 0 : Math.min(39, Math.floor((4000 - (knockSim.learnedFrom - performance.now())) / 100)),
          'knock.freq.bore_hz': boreHz, 'knock.freq.tone_hz': 0, 'knock.freq.sample_rate_hz': 38460,
          'knock.listen.notable': loud, 'knock.listen.confirmed': loud, 'knock.listen.second': loud ? 44 : Math.round(9 + 2 * Math.sin(tick / 6)),
          'knock.listen.second_normal': 9, 'knock.listen.background': 14, 'knock.listen.crest': loud ? 3.1 : Math.round((1.3 + .1 * Math.sin(tick / 4)) * 10) / 10,
        } : Object.fromEntries(['amp.automatic', 'amp.fixed', 'amp.ineffective', 'amp.overloaded', 'amp.silent', 'amp.gain', 'amp.step', 'amp.top_step',
          'amp.rest_mv', 'amp.swing_mv', 'amp.room_mv', 'freq.learning', 'freq.learned', 'freq.second_active', 'freq.filter_hz', 'freq.found_hz',
          'freq.agreement_pct', 'freq.votes', 'freq.bore_hz', 'freq.tone_hz', 'freq.sample_rate_hz', 'listen.notable', 'listen.confirmed',
          'listen.second', 'listen.second_normal', 'listen.background', 'listen.crest'].map(name => [`knock.${name}`, null]));
        Object.assign(current, esp32);
        if (knockDetail.supported) {
          // The engine's own spectrum: falling with frequency, a hump where the cylinder
          // rings and a smaller one at its second resonance. Bursts lift both.
          const lift = loud ? 17 : 4 + 2 * Math.sin(tick / 5);
          knockDetail.normal = []; knockDetail.burst = [];
          for (let point = 0; point < 36; point++) {
            const hz = 2000 + 300 * point;
            const normal = 25 - (hz - 2000) / 1000 * 1.1 + 6 * bell(hz, knockSim.ringsAt, 520) + 3 * bell(hz, knockSim.ringsAt * 1.659, 620) + .5 * Math.sin(tick / 9 + point);
            knockDetail.normal.push(Math.round(normal * 3) / 3);
            knockDetail.burst.push(Math.round((normal + 2 + lift * bell(hz, knockSim.ringsAt, 430) + lift * .5 * bell(hz, knockSim.ringsAt * 1.659, 520) + 1.4 * Math.abs(Math.sin(point * 1.7 + tick / 3))) * 3) / 3);
          }
        }
      }
      const values = Object.fromEntries(Object.entries(current).map(([key, value]) => [key,
        {value, quality: value === null ? 'unavailable' : scenario === 'offline' ? 'stale' : 'live', source: 'SIMULATED'}]));
      const test = readings['meth.state'] === 'TEST';
      const reasons = {};
      // Simulated motion does not lock preview configuration. Keep meaningful
      // controller states (disarm before test, active test, offline) observable.
      if (test) reasons['meth.arm'] = reasons['meth.test'] = reasons['meth.boost'] = 'Stop the pump test first';
      if (readings['meth.state'] === 'ARMED') reasons['meth.test'] = reasons['meth.boost'] = 'Disarm before adjusting or testing';
      if (!(speed < 1)) for (const action of TL_PARKED) reasons[action] = 'Park first: shows and overrides replace the turn signals';
      if (!knockSim.esp32) for (const action of KNOCK_ESP32_ONLY) reasons[action] = 'This setting needs the ESP32 water/meth controller';
      if (scenario === 'offline') {
        for (const button of document.querySelectorAll('[data-action]')) reasons[button.dataset.action] = 'Simulated controller offline';
        reasons['meth.disarm'] = 'Simulated controller offline';
        for (const action of KNOCK_SETTINGS) reasons[action] = 'Simulated controller offline';
      }
      this.emit({type: 'state', mode: 'demo', values, events: [], knock_detail: knockDetail,
        modules: Object.fromEntries(['taillights', 'comfort', 'watermeth', 'knock'].map(name => [name, scenario === 'offline' ? 'stale' : 'live'])),
        transport: {connected: scenario !== 'offline', status: 'Design preview — simulated data', received: tick, malformed: 0},
        meth_tune: {supported: scenario !== 'offline', complete: true, revision: mtRevision, unsaved: JSON.stringify(mtLive) !== JSON.stringify(mtSaved),
          rpm_ok: current['engine.rpm'] >= mtLive.min_rpm, pre_valid: true, post_valid: true, pump_on: onMs > 0 && (pwm || (tick * 100) % period < onMs),
          early_start: early && onMs > 0, hot_air: hotAir && onMs > 0,
          hold, on_ms: onMs, period_ms: period, drive: mtDrive, duty_pct: pwm ? onMs / 10 : null, settings: mtLive, last_ack: mtAck},
        taillight: {supported: scenario !== 'offline', complete: true, revision: tlRevision, unsaved: JSON.stringify(tlLive) !== JSON.stringify(tlSaved),
          show: false, demo: false, custom: false, override: false, show_anim: tlLive.settings.show_anim, phase_ms: 0,
          profiles: tlProfiles.map(Boolean), settings: tlLive.settings, colors: tlLive.colors, text: tlLive.text, last_ack: tlAck},
        controls: {reasons, test_active: test, lighting_active: tl.show !== null || !!tl.override, ...(tlResult ? {last_result: tlResult} : {})}});
    }
    send(data) {
      const {request_id, action, value} = JSON.parse(data);
      let detail = 'Demo change only — no vehicle connected.';
      if (scenario === 'offline') {
        this.emit({type: 'command_result', request_id, status: 'rejected', message: 'Demo controller offline'});
        return;
      }
      switch (action) {
        case 'meth.arm':
          clearTimeout(testTimer); readings['meth.state'] = value ? 'ARMED' : 'OFF'; readings['meth.duty_pct'] = 0; break;
        case 'meth.test':
          readings['meth.state'] = 'TEST'; readings['meth.duty_pct'] = value;
          clearTimeout(testTimer);
          testTimer = setTimeout(() => { readings['meth.state'] = 'OFF'; readings['meth.duty_pct'] = 0; this.publish(); }, 3000);
          break;
        case 'meth.stop':
          clearTimeout(testTimer); readings['meth.state'] = 'OFF'; readings['meth.duty_pct'] = 0; break;
        case 'meth.boost': mt().applySetting(mtLive, 'start_psi_x10', Math.round(value * 1.45037738)); mtRevision++; detail = `Simulated boost start set to ${value} kPa.`; break;
        case 'meth.setting': {
          const name = mt().keyName(Math.floor(value / 65536)), requested = value % 65536;
          const applied = mt().applySetting(mtLive, name, requested);
          mtAck = {command: 16, status: applied === requested ? 0 : 3, subject: Math.floor(value / 65536), value: applied, revision: ++mtRevision};
          detail = applied === requested ? 'Simulated water/meth setting applied.' : `Simulated controller limited the value to ${applied}.`; break;
        }
        case 'meth.tune_action':
          if (value === 0) mtSaved = {...mtLive};
          else if (value === 1) mtLive = {...mtSaved};
          else if (value === 2) mtLive = {...mt().DEFAULTS};
          mtAck = {command: 17, status: 0, subject: value, value: 0, revision: ++mtRevision};
          detail = ['Simulated settings saved.', 'Simulated settings reverted.', 'Simulated conservative defaults applied.'][value] || 'Simulated settings reported.'; break;
        case 'meth.clear_faults': readings['meth.fault_flags'] = 0; break;
        case 'knock.enable': readings['knock.enabled'] = !!value; break;
        case 'knock.threshold': readings['knock.config.threshold_offset'] = value; break;
        case 'knock.multiplier': readings['knock.config.multiplier'] = value / 10; break;
        case 'knock.refresh': detail = 'Simulated knock settings refreshed.'; break;
        case 'knock.clear_events': readings['knock.event_count'] = 0; break;
        case 'knock.min_rpm': readings['knock.config.min_rpm'] = value * 100; break;
        case 'knock.min_map': readings['knock.config.min_map_kpa'] = value; break;
        case 'knock.hold': readings['knock.config.debounce_ms'] = value * 10; break;
        case 'knock.level_gain': readings['knock.config.gain'] = value / 10; break;
        case 'knock.center': readings['knock.config.center_hz'] = value * 100; readings['knock.config.flags'] &= ~2; detail = 'Simulated: the knock frequency is set by hand.'; break;
        case 'knock.bandwidth': readings['knock.config.bandwidth_hz'] = value * 100; break;
        case 'knock.auto_frequency':
          readings['knock.config.flags'] = value ? readings['knock.config.flags'] | 2 : readings['knock.config.flags'] & ~2;
          detail = value ? 'Simulated: the knock frequency is found from the engine.' : detail; break;
        case 'knock.amp_gain': case 'knock.bore': case 'knock.relearn':
          if (!knockSim.esp32) { this.emit({type: 'command_result', request_id, status: 'rejected', message: 'This setting needs the ESP32 water/meth controller'}); return; }
          if (action === 'knock.amp_gain') { knockSim.fixedStep = value ? Math.min(value - 1, knockSim.top) : -1; detail = value ? `Simulated: gain held at position ${knockSim.fixedStep}.` : 'Simulated: the controller sets the gain.'; }
          else {
            // A new bore, or learning again: the bore's figure for a few seconds, then the engine's.
            if (action === 'knock.bore') { knockSim.boreMm = value; readings['knock.config.bore_mm'] = value; }
            knockSim.learnedFrom = performance.now() + 4000; detail = 'Simulated: learning the knock frequency again.';
          }
          break;
        case 'lighting.brightness': readings['lighting.brightness'] = value; break;
        case 'lighting.mode': lightingMode = value; tl = {show: null, override: null, customUntil: 0}; detail = `Simulated lighting mode: ${lightingMode ? 'Sequential' : 'Stock'}.`; break;
        case 'lighting.show': tl = {show: value, override: null, customUntil: 0}; detail = `Simulated show ${value}.`; break;
        case 'lighting.demo': tl = {show: 0, override: null, customUntil: 0}; detail = 'Simulated demo cycling every 5 seconds.'; break;
        case 'lighting.override': tl = {show: null, override: [value >> 4, value & 15], customUntil: 0}; detail = 'Simulated per-side test.'; break;
        case 'lighting.clear': tl = {show: null, override: null, customUntil: 0}; detail = 'Simulated normal lights.'; break;
        case 'lighting.custom': tl.customUntil = Date.now() + (value === 1 ? 6000 : 1500); detail = 'Simulated one-shot effect.'; break;
        case 'interior.light': {
          const zone = Math.floor(value / 2 ** 32), rgb = Math.floor(value / 256) % 2 ** 24, level = value % 256;
          for (const [channel, key] of [[1, 'upper'], [2, 'lower']]) if (!zone || zone === channel) {
            readings[`interior.${key}.color`] = '#' + rgb.toString(16).padStart(6, '0'); readings[`interior.${key}.brightness`] = level;
          }
          detail = level ? 'Simulated interior lights on.' : 'Simulated interior lights off.'; break;
        }
        case 'lighting.setting': tlLive.settings[TL_KEYS[Math.floor(value / 65536)]] = value % 65536; tlRevision++; detail = 'Simulated taillight setting applied.'; break;
        case 'lighting.color': tlLive.colors[['brake', 'turn', 'reverse', 'running'][Math.floor(value / 2 ** 24)]] = '#' + (value % 2 ** 24).toString(16).padStart(6, '0'); tlRevision++; detail = 'Simulated taillight color applied.'; break;
        case 'lighting.text': tlLive.text = String(value); tlRevision++; detail = 'Simulated show text applied.'; break;
        case 'lighting.action': {
          const kind = Math.floor(value / 256), slot = value % 256;
          let status = 0;
          if (kind === 0) tlSaved = tlCopy(tlLive);
          else if (kind === 1) tlLive = tlCopy(tlSaved);
          else if (kind === 2) tlLive = tlCopy(TL_DEFAULTS);
          else if (kind === 4) { if (tlProfiles[slot]) tlLive = tlCopy(tlProfiles[slot]); else status = 5; }
          else if (kind === 5) tlProfiles[slot] = tlCopy(tlLive);
          else if (kind === 6) tlProfiles[slot] = null;
          tlAck = {command: 9, status, subject: kind, value: slot, revision: ++tlRevision};
          detail = status ? 'That profile slot is empty.' : 'Simulated taillight action done.'; break;
        }
        default: this.emit({type: 'command_result', request_id, status: 'rejected', message: 'This command is not supported in the preview.'}); return;
      }
      // Match the asynchronous command/state order without pretending hardware acknowledged.
      setTimeout(() => {
        this.emit({type: 'command_result', request_id, status: 'simulated', message: detail});
        this.publish();
      }, 120);
    }
    close() { clearInterval(this.timer); clearTimeout(testTimer); this.readyState = 3; this.onclose?.(); }
  }
  window.FrogdashDemoSocket = FrogdashDemoSocket;
})();
