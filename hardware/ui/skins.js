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
    odometerMiles() { const km = trip()?.odometer_km; return Number.isFinite(km) ? mph(km) : null; },
    boostPsi(snapshot, live) { const kpa = live('engine.boost_kpa'); return kpa === null ? null : kpa * .145037738; }
  };
  const lit = id => () => $(id)?.classList.contains('on');
  const turn = side => () => $(`turn-${side}`)?.dataset.on === 'true';
  const boostText = (snapshot, live) => { const psi = READ.boostPsi(snapshot, live); return psi === null ? '--.- PSI' : `${psi < 0 ? '-' : ' '}${Math.abs(psi).toFixed(1).padStart(4, ' ')} PSI`; };
  const odometerText = () => { const miles = READ.odometerMiles(); return miles === null ? '------' : String(Math.floor(miles) % 1000000).padStart(6, '0'); };

  const SKINS = {
    // Each face has a night picture, the cluster with its illumination lit: the owner's own
    // for the Ferrari (green) and the Fox; a stand-in for the Saleen.
    // Veglia Borletti cluster from the owner's day and night pictures. Its faces are printed in
    // psi, °C, bar and MPH, so these needles keep those units whatever the dash's own unit
    // setting is.
    'skin-ferrari': {
      face: 'skins/ferrari.jpg?v=f3a5132b3c', night: 'skins/ferrari-night.jpg?v=270410d90c', lit: 'skins/ferrari-lamps.jpg?v=d1ba0e2712', litAt: [890, 134],
      needle: {body: '#ff7418', edge: '#ffd2a0', glow: '#ff6a00'},
      dials: [
        // Tach 0-7 (x1000), its red band running on to 7500.
        {id: 'rpm', signal: 'engine.rpm', pivot: [583, 365], length: 222, tail: 38, width: 10, hub: 22,
         marks: [[0, 454.5, 565.7], [1000, 382.6, 492.2], [2000, 350, 379], [3000, 374.1, 261.8], [4000, 457.7, 164.1], [5000, 584.7, 128.5],
                 [6000, 717.3, 166.5], [7000, 799.5, 269.5], [7500, 817.5, 332]]},
        {id: 'speed', signal: 'vehicle.speed_kph', convert: mph, pivot: [1333, 370], length: 226, tail: 38, width: 10, hub: 22,
         marks: [[0, 1186.6, 559.6], [20, 1115, 474.5], [40, 1092.5, 362.5], [60, 1131.8, 235.7], [80, 1219.4, 156.6], [100, 1336, 126.9],
                 [120, 1454.2, 159.4], [140, 1537.2, 241], [160, 1571.6, 355.4], [180, 1553.3, 468.8], [200, 1487.2, 557]]},
        // The small dials' needles show only inside their faces, from just under the printing:
        // boost (psi) top left, oil (bar) under it, coolant (degC) top right, fuel under it.
        {id: 'boost', read: READ.boostPsi, pivot: [155.5, 270], length: 98, width: 6, clip: [36, 140, 282, 258],
         marks: [[-20, 63.5, 226.4], [0, 155.5, 167.6], [20, 247.8, 226.8]]},
        {id: 'oil', signal: 'engine.oil_pressure_psi', convert: bar, pivot: [159, 588], length: 162, width: 7, clip: [36, 378, 282, 580],
         marks: [[0, 64, 447.5], [5, 159, 417.1], [10, 255, 447.5]]},
        {id: 'coolant', signal: 'engine.coolant_c', pivot: [1758, 335], length: 160, width: 7, clip: [1638, 140, 1884, 330],
         marks: [[50, 1658.4, 202.4], [90, 1757.5, 172], [130, 1857.5, 202.6]]},
        {id: 'fuel', read: READ.fuelPct, pivot: [1757, 590], length: 168, width: 7, clip: [1638, 378, 1884, 580],
         marks: [[0, 1665, 445], [50, 1757.5, 416.6], [100, 1857.1, 447.4]]}
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
    // Fox-style cluster with two LCD windows. Coolant in °F; the small dials' needles pivot
    // just off the screen's edge, as their ticks show, and swing up and down their recesses.
    'skin-fox': {
      face: 'skins/fox.jpg?v=894d45eccd', night: 'skins/fox-night.jpg?v=cad464be8d', needle: {body: '#ff5a1f', edge: '#ffc29a', glow: '#ff4a00'},
      dials: [
        {id: 'rpm', signal: 'engine.rpm', pivot: [606.3, 381.1], length: 248, tail: 40, width: 10, hub: 24,
         marks: [[0, 377.5, 522.5], [1000, 337.5, 376.5], [2000, 376, 230], [3000, 506, 124], [3500, 607.5, 102.5], [4000, 706, 124],
                 [5000, 837.5, 225], [6000, 875, 376], [7000, 832.5, 520]]},
        {id: 'speed', signal: 'vehicle.speed_kph', convert: mph, pivot: [1282.1, 380.2], length: 254, tail: 40, width: 10, hub: 24,
         marks: [[0, 1049, 522.5], [20, 1007.5, 384], [40, 1037.5, 247.5], [60, 1132.5, 145], [80, 1276.5, 102.5], [100, 1425, 144],
                 [120, 1526, 245], [140, 1560, 384], [160, 1520, 522.5]]},
        {id: 'coolant', signal: 'engine.coolant_c', convert: fahrenheit, pivot: [-11, 236.5], length: 150, width: 6, clip: [42, 124, 176, 350],
         marks: [[130, 127.5, 330], [200, 147.5, 236.5], [270, 135, 142.5]]},
        {id: 'fuel', read: READ.fuelPct, pivot: [-11, 503], length: 150, width: 6, clip: [42, 392, 176, 616],
         marks: [[0, 128.5, 595], [50, 148.5, 503], [100, 131, 409]]},
        {id: 'oil', signal: 'engine.oil_pressure_psi', pivot: [1931, 236.5], length: 150, width: 6, clip: [1744, 124, 1878, 350],
         marks: [[0, 1792.5, 330], [50, 1772.5, 236.5], [100, 1785, 142.5]]},
        {id: 'volts', signal: 'vehicle.battery_v', pivot: [1931, 503], length: 150, width: 6, clip: [1744, 392, 1878, 616],
         marks: [[8, 1792.5, 595], [13, 1771, 503], [18, 1787.5, 409]]}
      ],
      readouts: [
        {id: 'boost', box: [485, 527, 732, 588], style: 'lcd', text: boostText},
        {id: 'odometer', box: [1157, 527, 1404, 588], style: 'lcd', text: () => { const t = odometerText(); return t.includes('-') ? '------ MI' : `${t} MI`; }}
      ],
      warning: [560, 610, 1360]
    },
    // Saleen white faces. Coolant in °F; oil printed only L to H, read here as 0-80 psi.
    // The speedometer's two misprinted labels are painted out of the picture; its marks
    // follow the labels that are right (an unlabelled tick between 0 and 20 is 10, the one
    // between 180 and 200 is 190).
    'skin-saleen': {
      face: 'skins/saleen.jpg?v=229bbbd52f', night: 'skins/saleen-night.jpg?v=0590d0e405', needle: {body: '#e8341c', edge: '#5a0d04', glow: '#ff3a1a'},
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
    },
    // Ferrari with a yellow tach and a red speedometer on carbon (the owner's picture). The
    // tach and speedometer start at the bottom and run clockwise. The speedometer's printing is
    // uneven (0 to 20 takes two steps, no 40, an unlabelled tick at the top): the marks follow
    // the numbers printed, the top tick read as 150. Small dials: coolant (degF), boost (psi,
    // its red stop is 10 psi of vacuum), fuel on the left arc only, oil 0-140 psi.
    'skin-ferrari-yellow': {
      face: 'skins/ferrari-yellow.jpg?v=f8280b01d3', needle: {body: '#f4f1ea', edge: '#1c1c1c', glow: '#ffffff'},
      dials: [
        {id: 'rpm', signal: 'engine.rpm', pivot: [965, 372.5], length: 186, tail: 34, width: 9, hub: 26, color: {body: '#d81e05', edge: '#3a0700', glow: '#ff2a0a'},
         marks: [[0, 960, 560], [1000, 845, 515], [2000, 785, 422.5], [3000, 782.5, 315], [4000, 855, 207.5], [5000, 965, 175],
                 [6000, 1082.5, 212.5], [7000, 1147.5, 322], [7500, 1152.5, 395]]},
        {id: 'speed', signal: 'vehicle.speed_kph', convert: mph, pivot: [1547.5, 377.5], length: 186, tail: 34, width: 9, hub: 26,
         marks: [[0, 1544, 572.5], [20, 1407.5, 514], [60, 1355, 445], [80, 1345, 370], [100, 1365, 290], [120, 1412.5, 227.5], [140, 1492.5, 180],
                 [150, 1549, 167.5], [160, 1602.5, 180], [180, 1685, 227.5], [200, 1730, 292.5], [220, 1747.5, 370], [240, 1735, 444]]},
        {id: 'coolant', signal: 'engine.coolant_c', convert: fahrenheit, pivot: [195, 295], length: 108, tail: 18, width: 6, hub: 17,
         marks: [[130, 112.5, 327.5], [210, 196, 175], [270, 290, 227.5]]},
        {id: 'boost', read: READ.boostPsi, pivot: [485, 295], length: 108, tail: 18, width: 6, hub: 17,
         marks: [[-10, 400, 322.5], [0, 395, 227.5], [10, 485, 175], [20, 580, 227.5]]},
        {id: 'fuel', read: READ.fuelPct, pivot: [195, 515], length: 108, tail: 18, width: 6, hub: 17,
         marks: [[0, 122.5, 570], [50, 107.5, 505], [100, 125, 445]]},
        {id: 'oil', signal: 'engine.oil_pressure_psi', pivot: [485, 515], length: 108, tail: 18, width: 6, hub: 17,
         marks: [[0, 395, 457.5], [70, 485, 415], [140, 580, 457.5]]}
      ],
      // The speedometer's own warning symbols glow when they mean something now: ABS is
      // CHECK (an alert going off; a tap opens the Alerts tab), (!) the brake lights, the oil
      // can a low oil pressure alert.
      lamps: [
        {id: 'check', box: [1672, 452, 1718, 488], glow: '#ffae1a', on: () => $('alerts-launch')?.dataset.warning === 'true', tap: () => $('alerts-launch')?.click()},
        {id: 'brake', box: [1628, 491, 1672, 527], glow: '#ff3b1a', on: lit('icon-brake')},
        {id: 'oil', box: [1594, 534, 1648, 562], glow: '#ff3b1a', on: () => !!window.FrogdashDrive?.current?.()?.alerts?.some(a => a.key === 'oil' && a.active)}
      ],
      readouts: [
        {id: 'afr', box: [922, 248, 1012, 330], style: 'amber', text: (snapshot, live) => { const afr = live('engine.afr'); return `${afr === null ? '--.-' : afr.toFixed(1)}\nAFR`; }},
        {id: 'intake', box: [984, 424, 1113, 536], style: 'amber', text: (snapshot, live) => { const c = live('engine.iat_c'); return `${c === null ? '---' : Math.round(fahrenheit(c))}°F\nINTAKE`; }},
        {id: 'odometer', box: [1484, 286, 1612, 332], style: 'amber', text: odometerText}
      ],
      warning: [560, 606, 1360]
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
    // By day the picture as taken; with the lights on, its night picture (the cluster lit).
    // The night one is fetched now so the change is instant when the lights come on.
    host.style.setProperty('--skin-face', `url("${skin.face}")`);
    host.style.setProperty('--skin-face-night', `url("${skin.night || skin.face}")`);
    if (skin.night) new Image().src = skin.night;
    for (const [key, value] of Object.entries(skin.needle)) host.style.setProperty(`--skin-needle-${key}`, value);
    const face = svg('svg', {viewBox: '0 0 1920 720', class: 'skin-needles', 'aria-hidden': 'true'});
    const defs = svg('defs', {}); face.append(defs);
    const dials = skin.dials.map(dial => {
      const [px, py] = dial.pivot, w = dial.width, tail = dial.tail || 0;
      const group = svg('g', {class: 'skin-dial', 'data-dial': dial.id});
      for (const [key, value] of Object.entries(dial.color || {})) group.style.setProperty(`--skin-needle-${key}`, value);
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
      node.className = lamp.glow ? 'skin-lamp skin-lamp-glow' : 'skin-lamp'; node.dataset.lamp = lamp.id; node.dataset.on = 'false';
      if (lamp.glow) node.style.setProperty('--lamp', lamp.glow);
      else Object.assign(node.style, {backgroundImage: `url("${skin.lit}")`, backgroundPosition: `${skin.litAt[0] - lamp.box[0]}px ${skin.litAt[1] - lamp.box[1]}px`});
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
    host.append(face, warning);   // Needles over the lamps and readouts, as on a real cluster
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
