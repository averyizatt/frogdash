/* Display conversions only. CAN, logs and calibration retain explicit engineering units. */
(() => {
  let system = 'us';
  try { if (JSON.parse(localStorage.getItem('frogdash.units.v1'))?.system === 'metric') system = 'metric'; } catch {}
  const u = window.FrogdashUnits = {
    get metric() { return system === 'metric'; },
    set(value) { system = value === 'metric' ? 'metric' : 'us'; localStorage.setItem('frogdash.units.v1', JSON.stringify({system})); window.dispatchEvent(new Event('frogdash-units')); },
    distance: n => n == null ? null : u.metric ? n : n / 1.609344,
    temperature: n => u.metric ? n : n * 1.8 + 32,
    pressure: n => u.metric ? n * 6.894757293 : n,
    boost: n => u.metric ? n : n * .145037738,
    volume: n => n == null ? null : u.metric ? n : n / 3.785411784,
    economy: n => n == null || n <= 0 ? null : u.metric ? 235.214583 / n : n,
    get distanceUnit() { return u.metric ? 'km' : 'mi'; },
    get speedUnit() { return u.metric ? 'km/h' : 'MPH'; },
    get volumeUnit() { return u.metric ? 'L' : 'US gal'; },
    get economyUnit() { return u.metric ? 'L/100 km' : 'US MPG'; },
    definition(def) {
      if (!u.metric) return def;
      const [name, signal, unit, min, max, digits] = def;
      if (unit === '°F') return [name, signal, '°C', Math.round((min - 32) / 1.8), Math.round((max - 32) / 1.8), digits];
      if (unit === 'psi') return [name, signal, 'kPa', Math.round(min * 6.894757293), Math.round(max * 6.894757293), 0, signal.endsWith('_kpa') ? n => n : u.pressure];
      if (unit === 'mi') return [name, signal, 'km', 0, Math.round(max * 1.609344), digits];
      if (unit === 'US MPG') return [name, signal, 'L/100 km', 0, 30, digits, u.economy];
      return def;
    }
  };
})();
