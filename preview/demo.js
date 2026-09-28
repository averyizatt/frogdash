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
    'knock.config.multiplier': 2
  };
  let scenario = 'drive', paused = false, elapsed = 3, previous = performance.now();
  let tick = 0, testTimer, boostStart = 25, lightingMode = 0;
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
    if (!['drive', 'normal', 'warning', 'offline', 'vacuum', 'night', 'parked'].includes(name)) throw new Error('Unknown demo scenario');
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
  window.frogdashDemo = {scenario: setScenario};
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
        'vehicle.speed_kph': scenario === 'parked' ? 0 : readings['vehicle.speed_kph'],
        'lighting.running': scenario === 'night',
        'lighting.left_state': scenario === 'night' ? 'RUNNING' : 'OFF',
        'lighting.right_state': scenario === 'night' ? 'RUNNING' : 'OFF',
        'knock.energy': scenario === 'warning' ? 75 : Math.round(23 + Math.sin(tick / 7) * 5),
        'knock.warning': scenario === 'warning',
        'engine.coolant_c': scenario === 'warning' ? 115 : readings['engine.coolant_c'],
        'engine.boost_kpa': scenario === 'vacuum' ? -55 : readings['engine.boost_kpa'],
        ...dynamic
      };
      if (scenario === 'parked') Object.assign(current, {'engine.rpm': 900, 'engine.boost_kpa': -60, 'engine.afr': 14.7, 'ecu.afr_target': 14.7, 'vehicle.fuel_pct': drivingValues(elapsed)['vehicle.fuel_pct']});
      if (scenario === 'drive') for (const side of ['left', 'right']) current[`lighting.${side}_state`] = current[`lighting.turn_${side}`] ? 'TURN' : current['lighting.brake'] ? 'BRAKE' : 'OFF';
      if (scenario === 'drive' && readings['meth.state'] === 'ARMED' && current['engine.boost_kpa'] > boostStart) {
        current['meth.state'] = 'SPRAYING';
        current['meth.duty_pct'] = Math.round(Math.min(85, 20 + current['engine.boost_kpa'] * .6));
      }
      const values = Object.fromEntries(Object.entries(current).map(([key, value]) => [key,
        {value, quality: value === null ? 'unavailable' : scenario === 'offline' ? 'stale' : 'live', source: 'SIMULATED'}]));
      const test = readings['meth.state'] === 'TEST';
      const reasons = {};
      // Simulated motion does not lock preview configuration. Keep meaningful
      // controller states (disarm before test, active test, offline) observable.
      if (test) reasons['meth.arm'] = reasons['meth.test'] = reasons['meth.boost'] = 'Stop the pump test first';
      if (readings['meth.state'] === 'ARMED') reasons['meth.test'] = reasons['meth.boost'] = 'Disarm before adjusting or testing';
      if (scenario === 'offline') {
        for (const button of document.querySelectorAll('[data-action]')) reasons[button.dataset.action] = 'Simulated controller offline';
        reasons['meth.disarm'] = 'Simulated controller offline';
      }
      this.emit({type: 'state', mode: 'demo', values, events: [],
        modules: Object.fromEntries(['taillights', 'comfort', 'watermeth', 'knock'].map(name => [name, scenario === 'offline' ? 'stale' : 'live'])),
        transport: {connected: scenario !== 'offline', status: 'Design preview — simulated data', received: tick, malformed: 0},
        controls: {reasons, test_active: test}});
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
        case 'meth.boost': boostStart = value; detail = `Simulated boost start set to ${value} kPa.`; break;
        case 'meth.clear_faults': readings['meth.fault_flags'] = 0; break;
        case 'knock.enable': readings['knock.enabled'] = !!value; break;
        case 'knock.threshold': readings['knock.config.threshold_offset'] = value; break;
        case 'knock.multiplier': readings['knock.config.multiplier'] = value / 10; break;
        case 'knock.refresh': detail = 'Simulated knock settings refreshed.'; break;
        case 'knock.clear_events': readings['knock.event_count'] = 0; break;
        case 'lighting.brightness': readings['lighting.brightness'] = value; break;
        case 'lighting.mode': lightingMode = value; detail = `Simulated lighting mode: ${lightingMode ? 'Sequential' : 'Stock'}.`; break;
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
