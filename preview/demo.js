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
  let scenario = 'normal';
  let tick = 0, testTimer;
  // Explicit test/review hooks. The production client has no demo switch.
  window.frogdashDemo = {
    scenario(name) {
      if (!['normal', 'warning', 'offline', 'vacuum', 'night', 'parked'].includes(name)) throw new Error('Unknown demo scenario');
      scenario = name;
    }
  };
  class FrogdashDemoSocket {
    static OPEN = 1;
    readyState = 1;
    constructor() {
      this.timer = setInterval(() => this.publish(), 100);
    }
    emit(message) { this.onmessage?.({data: JSON.stringify(message)}); }
    publish() {
      tick++;
      const current = {...readings,
        'vehicle.speed_kph': scenario === 'parked' ? 0 : readings['vehicle.speed_kph'],
        'lighting.running': scenario === 'night',
        'lighting.left_state': scenario === 'night' ? 'RUNNING' : 'OFF',
        'lighting.right_state': scenario === 'night' ? 'RUNNING' : 'OFF',
        'knock.energy': scenario === 'warning' ? 75 : Math.round(23 + Math.sin(tick / 7) * 5),
        'knock.warning': scenario === 'warning',
        'engine.coolant_c': scenario === 'warning' ? 115 : readings['engine.coolant_c'],
        'engine.boost_kpa': scenario === 'vacuum' ? -55 : readings['engine.boost_kpa']
      };
      const values = Object.fromEntries(Object.entries(current).map(([key, value]) => [key,
        {value, quality: value === null ? 'unavailable' : scenario === 'offline' ? 'stale' : 'live', source: 'SIMULATED'}]));
      const test = readings['meth.state'] === 'TEST';
      const reasons = {};
      if (scenario !== 'parked') reasons['meth.test'] = 'Park before testing the pump';
      if (scenario !== 'parked') for (const key of ['meth.boost', 'knock.threshold', 'knock.multiplier']) reasons[key] = 'Park before changing calibration';
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
        case 'meth.clear_faults': readings['meth.fault_flags'] = 0; break;
        case 'knock.enable': readings['knock.enabled'] = !!value; break;
        case 'knock.threshold': readings['knock.config.threshold_offset'] = value; break;
        case 'knock.multiplier': readings['knock.config.multiplier'] = value / 10; break;
        case 'knock.clear_events': readings['knock.event_count'] = 0; break;
        case 'lighting.brightness': readings['lighting.brightness'] = value; break;
      }
      // Match the asynchronous command/state order without pretending hardware acknowledged.
      setTimeout(() => {
        this.emit({type: 'command_result', request_id, status: 'simulated', message: 'Demo change only — no vehicle connected.'});
        this.publish();
      }, 120);
    }
    close() { clearInterval(this.timer); clearTimeout(testTimer); this.readyState = 3; this.onclose?.(); }
  }
  window.FrogdashDemoSocket = FrogdashDemoSocket;
})();
