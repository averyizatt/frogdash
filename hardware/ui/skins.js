/* Photo gauge faces: a picture of a real cluster, with live needles and lamps drawn on it.
   Each face is hard-coded from its own picture (1920 x 720). A dial is its pivot and the
   pixel spots of its printed marks: the angle from the pivot to each mark is where the
   needle points for that value, and between marks it is interpolated, so a scale that is
   uneven or a little out of round in the photo still reads true. */
(() => {
  'use strict';
  const root = document.documentElement, ns = 'http://www.w3.org/2000/svg', $ = id => document.getElementById(id);
  const mph = kph => kph / 1.609344, bar = psi => psi / 14.5037738;
  const SKINS = {
    // Veglia Borletti cluster from the owner's picture. Its faces are printed in °C, bar and
    // MPH, so these needles keep those units whatever the dash's own unit setting is.
    'skin-ferrari': {
      face: 'skins/ferrari.jpg', lit: 'skins/ferrari-lamps.jpg', litAt: [890, 134],
      dials: [
        {id: 'rpm', signal: 'engine.rpm', pivot: [577.1, 363.4], length: 226, tail: 38, width: 10, hub: 22,
         marks: [[0, 415, 547.5], [1000, 350, 457.5], [2000, 332.5, 342.5], [3000, 370, 230], [4000, 457.5, 145], [5000, 577.5, 115],
                 [6000, 697.5, 145], [7000, 785, 227.5], [8000, 822.5, 342.5], [10000, 735, 545]]},
        {id: 'speed', signal: 'vehicle.speed_kph', convert: mph, pivot: [1332.5, 371], length: 228, tail: 38, width: 10, hub: 22,
         marks: [[0, 1162.5, 554], [20, 1100, 472.5], [40, 1076, 354], [60, 1115, 235], [80, 1207.5, 144], [100, 1326.5, 114],
                 [120, 1447.5, 144], [140, 1542.5, 227.5], [160, 1589, 349], [180, 1572.5, 467.5], [200, 1515, 552.5]]},
        // The small dials pivot just below their faces, as on the real cluster; the needle
        // shows only inside its face.
        {id: 'oiltemp', signal: 'engine.oil_temp_c', pivot: [158.5, 352], length: 184, width: 7, clip: [36, 140, 282, 340],
         marks: [[60, 50, 195], [100, 158.5, 161.5], [140, 267.5, 195]]},
        {id: 'oil', signal: 'engine.oil_pressure_psi', convert: bar, pivot: [158.5, 591], length: 184, width: 7, clip: [36, 378, 282, 580],
         marks: [[0, 50, 432.5], [5, 158.5, 400], [10, 267.5, 432.5]]},
        {id: 'coolant', signal: 'engine.coolant_c', pivot: [1760, 352], length: 184, width: 7, clip: [1638, 140, 1884, 340],
         marks: [[50, 1652.5, 195], [90, 1760, 161.5], [130, 1867.5, 195]]},
        {id: 'fuel', signal: 'vehicle.fuel_pct', pivot: [1760, 591], length: 184, width: 7, clip: [1638, 378, 1884, 580],
         marks: [[0, 1652.5, 432.5], [50, 1760, 400], [100, 1867.5, 432.5]]}
      ],
      // Lamps: lit from the dash's own indicators. The amber one (ABS in the photo) is CHECK:
      // an alert going off, and a tap on it opens the Alerts tab.
      lamps: [
        {id: 'brake', box: [896, 140, 1024, 196], on: () => $('icon-brake')?.classList.contains('on')},
        {id: 'check', box: [896, 218, 1024, 274], on: () => $('alerts-launch')?.dataset.warning === 'true', tap: () => $('alerts-launch')?.click()},
        {id: 'lights', box: [896, 298, 1024, 355], on: () => $('icon-running')?.classList.contains('on')},
        {id: 'left', box: [896, 379, 960, 436], on: () => $('turn-left')?.dataset.on === 'true'},
        {id: 'right', box: [960, 379, 1024, 436], on: () => $('turn-right')?.dataset.on === 'true'}
      ]
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

  let built = null;
  function build(name) {
    const skin = SKINS[name];
    built?.host.remove();
    const host = document.createElement('section'); host.className = 'skin-cluster'; host.dataset.skin = name;
    host.setAttribute('aria-label', 'Driving instruments');
    host.style.backgroundImage = `url("${skin.face}")`;
    const face = svg('svg', {viewBox: '0 0 1920 720', class: 'skin-needles', 'aria-hidden': 'true'});
    const defs = svg('defs', {}); face.append(defs);
    const dials = skin.dials.map(dial => {
      const [px, py] = dial.pivot, w = dial.width, tail = dial.tail || 0;
      const group = svg('g', {class: 'skin-dial', 'data-dial': dial.id});
      if (dial.clip) {
        const [x0, y0, x1, y1] = dial.clip, id = `skin-clip-${dial.id}`;
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
    const lamps = skin.lamps.map(lamp => {
      const [x0, y0, x1, y1] = lamp.box, node = document.createElement('div');
      node.className = 'skin-lamp'; node.dataset.lamp = lamp.id; node.dataset.on = 'false';
      Object.assign(node.style, {left: `${x0}px`, top: `${y0}px`, width: `${x1 - x0}px`, height: `${y1 - y0}px`,
        backgroundImage: `url("${skin.lit}")`, backgroundPosition: `${skin.litAt[0] - x0}px ${skin.litAt[1] - y0}px`});
      if (lamp.tap) { node.classList.add('skin-lamp-tap'); node.onclick = lamp.tap; }
      host.append(node);
      return {...lamp, node};
    });
    const warning = document.createElement('p'); warning.className = 'skin-warning'; warning.setAttribute('role', 'status'); warning.hidden = true;
    host.prepend(face); host.append(warning);
    document.querySelector('.custom-cluster').before(host);
    built = {name, host, dials, lamps, warning};
  }

  function render(snapshot, connected) {
    const name = root.dataset.gauges;
    if (!Object.hasOwn(SKINS, name)) return false;
    if (built?.name !== name) build(name);
    for (const dial of built.dials) {
      const sample = snapshot.values?.[dial.signal];
      let value = connected && sample?.quality === 'live' && Number.isFinite(sample.value) ? sample.value : null;
      if (value !== null && dial.convert) value = dial.convert(value);
      // No reading: the needle rests at its stop, dimmed, as on a car with the key off.
      const angle = value === null ? dial.angles[0][1] : angleFor(dial, value);
      const quality = value === null ? (connected ? sample?.quality || 'unavailable' : 'stale') : 'live';
      if (dial.shown !== angle) { dial.needle.style.transform = `rotate(${angle.toFixed(2)}deg)`; dial.shown = angle; }
      if (dial.group.dataset.quality !== quality) dial.group.dataset.quality = quality;
    }
    for (const lamp of built.lamps) {
      const on = String(!!lamp.on());
      if (lamp.node.dataset.on !== on) lamp.node.dataset.on = on;
    }
    const banner = $('warn-banner');
    if (built.warning.textContent !== banner.textContent) built.warning.textContent = banner.textContent;
    built.warning.hidden = banner.hidden;
    return true;
  }
  window.FrogdashSkins = {render, names: Object.keys(SKINS)};
})();
