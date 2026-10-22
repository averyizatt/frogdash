/* Photo gauge faces: a picture of a real cluster, with live needles, lamps and readouts drawn
   on it. Each face is hard-coded from its own picture (1920 x 720). A dial is its pivot and
   the pixel spots of its printed marks: the angle from the pivot to each mark is where the
   needle points for that value, and between marks it is interpolated, so a scale that is
   uneven, curved or a little out of round in the photo still reads true. Every dial shows
   something the car has: where the picture's own label is for a sender the car lacks, the
   dial is given a reading that fits its printed scale. */
(() => {
  'use strict';
  const root = document.documentElement, ns = 'http://www.w3.org/2000/svg', $ = id => document.getElementById(id);
  const mph = kph => kph / 1.609344, bar = psi => psi / 14.5037738, fahrenheit = c => c * 1.8 + 32;
  // Readings shared by the faces: (snapshot, live) => value in the face's printed unit, or null.
  const trip = () => window.FrogdashTrip?.view?.();
  const READ = {
    // A fuel sender if the car has one, else the dash's own fuel estimate (Trips & economy).
    fuelPct(snapshot, live) {
      const sender = live('vehicle.fuel_pct');
      if (sender !== null) return sender;
      const t = snapshot.trip || trip(), litres = t?.remaining_l, tank = t?.settings?.capacity_l;
      return Number.isFinite(litres) && tank > 0 ? Math.max(0, Math.min(100, litres / tank * 100)) : null;
    },
    // Manifold pressure, kPa absolute: about 86 standing still at 5,000 ft.
    mapKpa(snapshot, live) {
      const map = live('ecu.map_kpa');
      if (map !== null) return map;
      const boost = live('engine.boost_kpa'), baro = live('ecu.baro_kpa');
      return boost === null ? null : boost + (baro ?? 86);
    },
    odometerMiles() { const km = trip()?.odometer_km; return Number.isFinite(km) ? mph(km) : null; },
    boostPsi(snapshot, live) { const kpa = live('engine.boost_kpa'); return kpa === null ? null : kpa * .145037738; }
  };
  const lit = id => () => $(id)?.classList.contains('on');
  const turn = side => () => $(`turn-${side}`)?.dataset.on === 'true';
  const boostText = (snapshot, live) => { const psi = READ.boostPsi(snapshot, live); return psi === null ? '--.- PSI' : `${psi < 0 ? '-' : ' '}${Math.abs(psi).toFixed(1).padStart(4, ' ')} PSI`; };
  const odometerText = () => { const miles = READ.odometerMiles(); return miles === null ? '------' : String(Math.floor(miles) % 1000000).padStart(6, '0'); };

  const SKINS = {
    // Veglia Borletti cluster from the owner's picture. Its faces are printed in °C, bar and
    // MPH, so these needles keep those units whatever the dash's own unit setting is.
    'skin-ferrari': {
      face: 'skins/ferrari.jpg', lit: 'skins/ferrari-lamps.jpg', litAt: [890, 134],
      needle: {body: '#ff7418', edge: '#ffd2a0', glow: '#ff6a00'},
      dials: [
        {id: 'rpm', signal: 'engine.rpm', pivot: [577.1, 363.4], length: 226, tail: 38, width: 10, hub: 22,
         marks: [[0, 415, 547.5], [1000, 350, 457.5], [2000, 332.5, 342.5], [3000, 370, 230], [4000, 457.5, 145], [5000, 577.5, 115],
                 [6000, 697.5, 145], [7000, 785, 227.5], [8000, 822.5, 342.5], [10000, 735, 545]]},
        {id: 'speed', signal: 'vehicle.speed_kph', convert: mph, pivot: [1332.5, 371], length: 228, tail: 38, width: 10, hub: 22,
         marks: [[0, 1162.5, 554], [20, 1100, 472.5], [40, 1076, 354], [60, 1115, 235], [80, 1207.5, 144], [100, 1326.5, 114],
                 [120, 1447.5, 144], [140, 1542.5, 227.5], [160, 1589, 349], [180, 1572.5, 467.5], [200, 1515, 552.5]]},
        // The small dials pivot just below their faces, as on the real cluster; the needle
        // shows only inside its face. The car has no oil temperature sender: the top-left
        // dial shows manifold pressure, its printed 60-140 read as kPa absolute
        // (about 86 at rest here, 140 at 8 psi of boost).
        {id: 'map', read: READ.mapKpa, pivot: [158.5, 352], length: 184, width: 7, clip: [36, 140, 282, 340],
         marks: [[60, 50, 195], [100, 158.5, 161.5], [140, 267.5, 195]]},
        {id: 'oil', signal: 'engine.oil_pressure_psi', convert: bar, pivot: [158.5, 591], length: 184, width: 7, clip: [36, 378, 282, 580],
         marks: [[0, 50, 432.5], [5, 158.5, 400], [10, 267.5, 432.5]]},
        {id: 'coolant', signal: 'engine.coolant_c', pivot: [1760, 352], length: 184, width: 7, clip: [1638, 140, 1884, 340],
         marks: [[50, 1652.5, 195], [90, 1760, 161.5], [130, 1867.5, 195]]},
        {id: 'fuel', read: READ.fuelPct, pivot: [1760, 591], length: 184, width: 7, clip: [1638, 378, 1884, 580],
         marks: [[0, 1652.5, 432.5], [50, 1760, 400], [100, 1867.5, 432.5]]}
      ],
      // Lamps: lit from the dash's own indicators. The amber one (ABS in the photo) is CHECK:
      // an alert going off, and a tap on it opens the Alerts tab.
      lamps: [
        {id: 'brake', box: [896, 140, 1024, 196], on: lit('icon-brake')},
        {id: 'check', box: [896, 218, 1024, 274], on: () => $('alerts-launch')?.dataset.warning === 'true', tap: () => $('alerts-launch')?.click()},
        {id: 'lights', box: [896, 298, 1024, 355], on: lit('icon-running')},
        {id: 'left', box: [896, 379, 960, 436], on: turn('left')},
        {id: 'right', box: [960, 379, 1024, 436], on: turn('right')}
      ],
      warning: [560, 596, 1360]
    },
    // Fox-style cluster with two LCD windows. Coolant in °F; the small dials sit on curved
    // faces and pivot from the outer edge of their recesses.
    'skin-fox': {
      face: 'skins/fox.jpg', needle: {body: '#ff5a1f', edge: '#ffc29a', glow: '#ff4a00'},
      dials: [
        {id: 'rpm', signal: 'engine.rpm', pivot: [599.3, 403.6], length: 262, tail: 40, width: 10, hub: 24,
         marks: [[0, 345, 522.5], [1000, 319, 370], [2000, 382.5, 224], [3000, 518.5, 134], [4000, 684, 134], [5000, 820, 224], [6000, 878, 370], [7000, 850, 522.5]]},
        {id: 'speed', signal: 'vehicle.speed_kph', convert: mph, pivot: [1283.6, 405.7], length: 270, tail: 40, width: 10, hub: 24,
         marks: [[0, 1025, 525], [20, 995, 386], [40, 1037.5, 252.5], [60, 1139, 155], [80, 1278.5, 117.5], [100, 1422.5, 151],
                 [120, 1527.5, 250], [140, 1574, 386], [160, 1547.5, 525]]},
        {id: 'coolant', signal: 'engine.coolant_c', convert: fahrenheit, pivot: [14, 246], length: 142, width: 6, clip: [56, 138, 172, 352],
         marks: [[130, 137, 333], [200, 159, 245], [270, 132, 160]]},
        {id: 'fuel', read: READ.fuelPct, pivot: [14, 499], length: 142, width: 6, clip: [56, 396, 172, 606],
         marks: [[0, 132.5, 582.5], [50, 157.5, 499], [100, 132.5, 415]]},
        {id: 'oil', signal: 'engine.oil_pressure_psi', pivot: [1906, 247], length: 142, width: 6, clip: [1748, 138, 1864, 352],
         marks: [[0, 1790, 332.5], [50, 1767.5, 247.5], [100, 1790, 160]]},
        {id: 'volts', signal: 'vehicle.battery_v', pivot: [1906, 506], length: 142, width: 6, clip: [1748, 396, 1864, 612],
         marks: [[8, 1790, 590], [13, 1780, 506.5], [18, 1790, 420]]}
      ],
      readouts: [
        {id: 'boost', box: [479, 525, 719, 589], style: 'lcd', text: boostText},
        {id: 'odometer', box: [1160, 525, 1402, 590], style: 'lcd', text: () => { const t = odometerText(); return t.includes('-') ? '------ MI' : `${t} MI`; }}
      ],
      warning: [560, 610, 1360]
    },
    // Saleen white faces. Coolant in °F; oil printed only L to H, read here as 0-80 psi.
    // The speedometer's two misprinted labels are painted out of the picture; its marks
    // follow the labels that are right (an unlabelled tick between 0 and 20 is 10, the one
    // between 180 and 200 is 190).
    'skin-saleen': {
      face: 'skins/saleen.jpg', needle: {body: '#e8341c', edge: '#5a0d04', glow: '#ff3a1a'},
      dials: [
        {id: 'rpm', signal: 'engine.rpm', pivot: [613.8, 406.1], length: 262, tail: 40, width: 10, hub: 24,
         marks: [[0, 360, 530], [1000, 327.5, 377.5], [2000, 387.5, 226], [3000, 520, 134], [4000, 701.5, 131], [5000, 835, 221], [6000, 902.5, 375], [7000, 870, 527.5]]},
        {id: 'speed', signal: 'vehicle.speed_kph', convert: mph, pivot: [1310, 400], length: 262, tail: 40, width: 10, hub: 24,
         marks: [[0, 1075, 546], [10, 1042.5, 475], [20, 1027.5, 382.5], [40, 1050, 287.5], [60, 1105, 201], [80, 1197.5, 136], [100, 1315, 120],
                 [120, 1430, 150], [140, 1517.5, 212.5], [160, 1565, 292.5], [180, 1580, 382.5], [190, 1575, 474], [200, 1542.5, 540]]},
        {id: 'coolant', signal: 'engine.coolant_c', convert: fahrenheit, pivot: [42, 233], length: 104, width: 6, clip: [30, 118, 166, 350],
         marks: [[130, 107.5, 310], [200, 147.5, 235], [270, 102.5, 150]]},
        {id: 'fuel', read: READ.fuelPct, pivot: [52, 502], length: 104, width: 6, clip: [30, 390, 166, 618],
         marks: [[0, 110, 572.5], [50, 152.5, 505], [100, 102.5, 422.5]]},
        {id: 'oil', signal: 'engine.oil_pressure_psi', pivot: [1860, 231], length: 104, width: 6, clip: [1744, 118, 1890, 350],
         marks: [[0, 1815, 307.5], [40, 1770, 232.5], [80, 1815, 152.5]]},
        {id: 'volts', signal: 'vehicle.battery_v', pivot: [1860, 509], length: 104, width: 6, clip: [1744, 390, 1890, 618],
         marks: [[8, 1815, 587.5], [13, 1775, 510], [18, 1815, 430]]}
      ],
      readouts: [
        {id: 'boost', box: [1202, 235, 1424, 274], style: 'led', text: boostText},
        {id: 'odometer', box: [1217, 507, 1406, 553], style: 'wheels', text: odometerText}
      ],
      warning: [560, 616, 1360]
    }
  };

  const svg = (tag, attrs) => { const n = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  // Clockwise from straight up, in degrees.
  const angleTo = ([px, py], x, y) => Math.atan2(x - px, py - y) * 180 / Math.PI;
  function angleFor(dial, value) {
    const marks = dial.angles;
    if (value <= marks[0][0]) return marks[0][1];
    for (let i = 1; i < marks.length; i++) {
      const [v0, a0] = marks[i - 1], [v1, a1] = marks[i];
      if (value <= v1) return a0 + (a1 - a0) * (value - v0) / (v1 - v0);
    }
    return marks.at(-1)[1];
  }
  const place = (node, [x0, y0, x1, y1]) => Object.assign(node.style, {left: `${x0}px`, top: `${y0}px`, width: `${x1 - x0}px`, height: `${y1 - y0}px`});

  let built = null;
  function build(name) {
    const skin = SKINS[name];
    built?.host.remove();
    const host = document.createElement('section'); host.className = 'skin-cluster'; host.dataset.skin = name;
    host.setAttribute('aria-label', 'Driving instruments');
    host.style.backgroundImage = `url("${skin.face}")`;
    for (const [key, value] of Object.entries(skin.needle)) host.style.setProperty(`--skin-needle-${key}`, value);
    const face = svg('svg', {viewBox: '0 0 1920 720', class: 'skin-needles', 'aria-hidden': 'true'});
    const defs = svg('defs', {}); face.append(defs);
    const dials = skin.dials.map(dial => {
      const [px, py] = dial.pivot, w = dial.width, tail = dial.tail || 0;
      const group = svg('g', {class: 'skin-dial', 'data-dial': dial.id});
      if (dial.clip) {
        const [x0, y0, x1, y1] = dial.clip, id = `skin-clip-${name}-${dial.id}`;
        const path = svg('clipPath', {id}); path.append(svg('rect', {x: x0, y: y0, width: x1 - x0, height: y1 - y0, rx: 10})); defs.append(path);
        group.setAttribute('clip-path', `url(#${id})`);
      }
      const needle = svg('g', {class: 'skin-needle'});
      needle.style.transformOrigin = `${px}px ${py}px`;
      const shape = `M${px - w / 2} ${py + tail} L${px - 1.4} ${py - dial.length} L${px + 1.4} ${py - dial.length} L${px + w / 2} ${py + tail} Z`;
      needle.append(svg('path', {d: shape, class: 'skin-needle-glow'}), svg('path', {d: shape, class: 'skin-needle-body'}));
      group.append(needle);
      if (dial.hub) group.append(svg('circle', {cx: px, cy: py, r: dial.hub, class: 'skin-hub'}), svg('circle', {cx: px, cy: py, r: dial.hub * .38, class: 'skin-hub-cap'}));
      face.append(group);
      return {...dial, needle, group, angles: dial.marks.map(([value, x, y]) => [value, angleTo(dial.pivot, x, y)]), shown: null};
    });
    const lamps = (skin.lamps || []).map(lamp => {
      const node = document.createElement('div'); place(node, lamp.box);
      node.className = 'skin-lamp'; node.dataset.lamp = lamp.id; node.dataset.on = 'false';
      Object.assign(node.style, {backgroundImage: `url("${skin.lit}")`, backgroundPosition: `${skin.litAt[0] - lamp.box[0]}px ${skin.litAt[1] - lamp.box[1]}px`});
      if (lamp.tap) { node.classList.add('skin-lamp-tap'); node.onclick = lamp.tap; }
      host.append(node);
      return {...lamp, node};
    });
    const readouts = (skin.readouts || []).map(readout => {
      const node = document.createElement('div'); place(node, readout.box);
      node.className = `skin-readout skin-${readout.style}`; node.dataset.readout = readout.id;
      host.append(node);
      return {...readout, node, shown: null};
    });
    const warning = document.createElement('p'); warning.className = 'skin-warning'; warning.setAttribute('role', 'status'); warning.hidden = true;
    const [left, top, right] = skin.warning;
    Object.assign(warning.style, {left: `${left}px`, top: `${top}px`, width: `${right - left}px`});
    host.prepend(face); host.append(warning);
    document.querySelector('.custom-cluster').before(host);
    built = {name, host, dials, lamps, readouts, warning};
  }

  function render(snapshot, connected) {
    const name = root.dataset.gauges;
    if (!Object.hasOwn(SKINS, name)) return false;
    if (built?.name !== name) build(name);
    const live = key => { const s = snapshot.values?.[key]; return connected && s?.quality === 'live' && Number.isFinite(s.value) ? s.value : null; };
    for (const dial of built.dials) {
      let value = dial.read ? (connected ? dial.read(snapshot, live) : null) : live(dial.signal);
      if (value !== null && dial.convert) value = dial.convert(value);
      // No reading: the needle rests at its stop, dimmed, as on a car with the key off.
      const angle = value === null ? dial.angles[0][1] : angleFor(dial, value);
      const quality = value !== null ? 'live' : !connected ? 'stale' : dial.signal ? snapshot.values?.[dial.signal]?.quality || 'unavailable' : 'unavailable';
      if (dial.shown !== angle) { dial.needle.style.transform = `rotate(${angle.toFixed(2)}deg)`; dial.shown = angle; }
      if (dial.group.dataset.quality !== quality) dial.group.dataset.quality = quality;
    }
    for (const lamp of built.lamps) {
      const on = String(!!lamp.on());
      if (lamp.node.dataset.on !== on) lamp.node.dataset.on = on;
    }
    for (const readout of built.readouts) {
      const text = readout.text(snapshot, live);
      if (readout.shown === text) continue;
      readout.shown = text;
      if (readout.style === 'wheels') readout.node.replaceChildren(...[...text].map(digit => Object.assign(document.createElement('span'), {textContent: digit})));
      else readout.node.textContent = text;
    }
    const banner = $('warn-banner');
    if (built.warning.textContent !== banner.textContent) built.warning.textContent = banner.textContent;
    built.warning.hidden = banner.hidden;
    return true;
  }
  window.FrogdashSkins = {render, names: Object.keys(SKINS)};
})();
