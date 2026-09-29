/* Alternative vector clusters share the production values and quality rules. */
(() => {
  'use strict';
  const root = document.documentElement, host = document.querySelector('.primary-instruments');
  const ns = 'http://www.w3.org/2000/svg';
  let last = null, metric = null;
  const definitions = [
    ['coolant', 'WATER TEMP', 'engine.coolant_c'], ['fuel', 'FUEL', 'vehicle.fuel_pct'],
    ['speed', 'SPEED', 'vehicle.speed_kph'], ['rpm', 'TACHOMETER', 'engine.rpm'],
    ['oil', 'OIL PRESSURE', 'engine.oil_pressure_psi'], ['volts', 'VOLTS', 'vehicle.battery_v']
  ];
  const board = document.createElement('section'); board.className = 'custom-cluster'; board.setAttribute('aria-label', 'Custom driving instruments');
  const gauges = new Map();
  const point = (angle, radius) => { const a = angle * Math.PI / 180; return [180 + Math.sin(a) * radius, 180 - Math.cos(a) * radius]; };
  const svgNode = (tag, attrs, text) => { const n = document.createElementNS(ns, tag); for (const [k,v] of Object.entries(attrs)) n.setAttribute(k,v); if (text != null) n.textContent = text; return n; };
  for (const [id, title, signal] of definitions) {
    const card = document.createElement('article'); card.className = `cluster-gauge cluster-${id}`; card.dataset.channel = signal;
    card.innerHTML = `<svg class="cluster-dial" viewBox="0 0 360 360" aria-hidden="true"><circle class="dial-bezel" cx="180" cy="180" r="172"/><circle class="dial-face" cx="180" cy="180" r="161"/><g class="dial-scale"></g><text class="dial-title" x="180" y="116">${title}</text><text class="dial-unit" x="180" y="142"></text><g class="dial-needle"><path d="M177 205 L177 162 L180 36 L183 162 L183 205 Z"/><circle cx="180" cy="180" r="12"/></g><text class="dial-value" x="180" y="280">\u2014</text></svg><div class="terminal-face"><h3>${title}</h3><div><strong class="terminal-value">\u2014</strong><span class="terminal-unit"></span></div><div class="terminal-meter" aria-hidden="true">${'<i></i>'.repeat(28)}</div></div><div class="cyber-face"><header><span class="cyber-code">${String(definitions.findIndex(d => d[0] === id) + 1).padStart(2, '0')}</span><h3>${title}</h3><span class="cyber-unit"></span></header><strong class="cyber-value">—</strong><div class="cyber-meter" aria-hidden="true"></div>${id === 'rpm' ? `<div class="cyber-scale" aria-hidden="true">${[0,1,2,3,4,5,6,7].map(n => `<span>${n}</span>`).join('')}</div>` : ''}</div><span class="cluster-quality">NO SIGNAL</span>`;
    const segments = {rpm: 56, speed: 36}[id] || 18, meter = card.querySelector('.cyber-meter');
    for (let i = 0; i < segments; i++) {
      const bar = document.createElement('i'); bar.style.setProperty('--mix', `${Math.round(100 * i / (segments - 1))}%`);
      if (id === 'rpm' && (i + 1) / segments > 6 / 7) bar.className = 'redline';
      meter.append(bar);
    }
    if (id === 'speed' || id === 'rpm') {
      const digits = svgNode('svg',{class:'terminal-digits',viewBox:`0 0 ${id==='speed'?168:224} 94`,'aria-hidden':'true'});
      const segments = ['12,4 42,4','46,10 46,39','46,53 46,82','12,88 42,88','8,53 8,82','8,10 8,39','12,46 42,46'];
      for(let d=0;d<(id==='speed'?3:4);d++) {
        const group=svgNode('g',{transform:`translate(${d*56} 0)`});
        for(const points of segments) group.append(svgNode('polyline',{points}));
        digits.append(group);
      }
      card.querySelector('.terminal-value').after(digits);
    }
    board.append(card); gauges.set(id, {card, signal, title, needle: card.querySelector('.dial-needle'), scale: card.querySelector('.dial-scale'), meters:[[...card.querySelectorAll('.terminal-meter i')],[...card.querySelectorAll('.cyber-meter i')]]});
  }
  const track = document.createElement('div'); track.className='cluster-track'; track.hidden=true;
  track.innerHTML=`<div class="cluster-shift" aria-label="Shift lights">${'<i></i>'.repeat(8)}</div><span>LAST <b></b></span><span>BEST <b></b></span>`; board.append(track);
  const warning = document.createElement('p'); warning.className = 'cluster-warning'; warning.setAttribute('role','status'); warning.hidden = true; board.append(warning);
  const strip = document.createElement('section'); strip.className = 'cluster-telemetry'; strip.setAttribute('aria-label','Additional engine readings');
  for (const [id, name] of [['boost','MANIFOLD'],['afr','AIR / FUEL'],['iat','INTAKE AIR'],['fuelp','FUEL PRESSURE']]) {
    const cell = document.createElement('article'); cell.dataset.reading = id; cell.innerHTML = `<span>${name}</span><strong>\u2014</strong><small></small>`; strip.append(cell);
  }
  host.before(board, strip);
  const tach = document.querySelector('.tach-dial');
  if (tach) tach.insertAdjacentHTML('afterbegin', '<defs><linearGradient id="tach-gradient" x1="0" y1="0" x2="1" y2="0"><stop offset="0" class="tach-stop-start"/><stop offset="1" class="tach-stop-end"/></linearGradient></defs>');
  function configureScales() {
    const u = window.FrogdashUnits; metric = u.metric;
    const config = {rpm:[0,7000,7,'RPM \u00d7 1000'], speed:[0,u.metric ? 240 : 140,u.metric ? 12 : 7,u.speedUnit],
      coolant:u.metric ? [40,120,4,'\u00b0C'] : [100,260,4,'\u00b0F'], fuel:[0,100,4,'%'], oil:[0,u.metric ? 700 : 100,4,u.metric ? 'kPa' : 'psi'], volts:[8,18,5,'V']};
    for (const [id,g] of gauges) {
      [g.min,g.max,g.steps,g.unit] = config[id]; g.scale.replaceChildren();
      for (let i=0; i<=g.steps*5; i++) {
        const fraction = i/(g.steps*5), angle = -135 + 270*fraction, major = i%5 === 0;
        const a = point(angle, major ? 141 : 150), b = point(angle,158);
        const red = id === 'rpm' && fraction*7000 >= 6000;
        g.scale.append(svgNode('line', {x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:`dial-tick ${major ? 'major' : ''} ${red ? 'redline' : ''}`}));
        if (major) {
          const p = point(angle,120), value = g.min+(g.max-g.min)*fraction;
          const label = id === 'rpm' ? Math.round(value/1000) : id === 'fuel' ? (i===0 ? 'E' : i===g.steps*5 ? 'F' : i===10 ? '1/2' : '') : Math.round(value);
          g.scale.append(svgNode('text',{x:p[0],y:p[1],class:`dial-number ${red ? 'redline' : ''}`},label));
        }
      }
      g.card.querySelector('.dial-unit').textContent = g.unit;
      g.card.querySelector('.terminal-unit').textContent = id === 'rpm' ? 'RPM' : g.unit;
      g.card.querySelector('.cyber-unit').textContent = id === 'rpm' ? 'RPM' : g.unit;
    }
  }
  function render(snapshot, connected) {
    last = {snapshot, connected};
    if (root.dataset.gauges === 'standard' || !root.dataset.gauges) return;
    const u = window.FrogdashUnits; if (metric !== u.metric) configureScales();
    const live = key => { const s = snapshot.values?.[key]; return connected && s?.quality === 'live' && Number.isFinite(s.value) ? s.value : null; };
    const quality = key => connected ? snapshot.values?.[key]?.quality || 'unavailable' : 'stale';
    for (const [id,g] of gauges) {
      let value = live(g.signal);
      if (value !== null) { if (id==='speed') value=u.distance(value); if(id==='coolant') value=u.temperature(value); if(id==='oil') value=u.pressure(value); }
      const ratio = value === null ? 0 : Math.max(0,Math.min(1,(value-g.min)/(g.max-g.min)));
      const text = value === null ? '\u2014' : value.toFixed(id==='volts' ? 1 : 0);
      const led = g.card.querySelector('.terminal-digits');
      if(led) {
        const patterns = {'0':'abcdef','1':'bc','2':'abdeg','3':'abcdg','4':'bcfg','5':'acdfg','6':'acdefg','7':'abc','8':'abcdefg','9':'abcdfg','-':'g'};
        const number = (value===null ? '-' : Math.round(value).toString()).padStart(led.children.length,' ');
        led.style.display = number.length > led.children.length ? 'none' : '';
        g.card.querySelector('.terminal-value').style.display = number.length > led.children.length ? 'inline' : '';
        for(const [index,digit] of [...led.children].entries()) {
          for(const [segment,line] of [...digit.children].entries()) line.dataset.lit=String((patterns[number[index]]||'').includes('abcdefg'[segment]));
        }
      }
      g.card.dataset.quality = quality(g.signal);
      g.card.dataset.danger = String(id==='rpm' && value >= 6000 || id==='coolant' && live(g.signal) >= (snapshot.drive?.settings?.coolant_c ?? 112));
      g.needle.setAttribute('transform',`rotate(${-135+270*ratio} 180 180)`);
      g.needle.style.visibility = value === null ? 'hidden' : 'visible';
      for(const n of g.card.querySelectorAll('.dial-value,.terminal-value,.cyber-value')) n.textContent=text;
      g.card.querySelector('.cluster-quality').textContent = value === null ? quality(g.signal).toUpperCase().replace('UNAVAILABLE','NO SIGNAL') : '';
      g.card.setAttribute('aria-label', `${g.title}: ${text} ${id==='rpm' ? 'RPM' : g.unit}${value === null ? ', '+quality(g.signal) : ''}`);
      for(const bars of g.meters) for(const [i,bar] of bars.entries()) bar.dataset.on = String(value !== null && i < ratio*bars.length);
    }
    for(const [id,key,convert,unit,digits] of [['boost','engine.boost_kpa',u.boost,u.metric?'kPa':'psi',1],['afr','engine.afr',n=>n,'AFR',1],['iat','engine.iat_c',u.temperature,u.metric?'\u00b0C':'\u00b0F',0],['fuelp','engine.fuel_pressure_psi',u.pressure,u.metric?'kPa':'psi',1]]) {
      const cell=strip.querySelector(`[data-reading="${id}"]`), value=live(key);
      cell.querySelector('strong').textContent=value===null?'\u2014':convert(value).toFixed(digits);
      cell.querySelector('small').textContent=value===null?quality(key).toUpperCase():unit;
    }
    const shifts = document.getElementById('shift-lights');
    track.hidden=shifts.hidden;
    track.dataset.shift=shifts.dataset.shift;
    for(const [i,light] of [...track.querySelectorAll('i')].entries()) light.dataset.on=shifts.children[i].dataset.on;
    track.querySelectorAll('b')[0].textContent=document.getElementById('track-last').textContent;
    track.querySelectorAll('b')[1].textContent=document.getElementById('track-best').textContent;
    warning.textContent=document.getElementById('warn-banner').textContent;
    warning.hidden=document.getElementById('warn-banner').hidden;
  }
  window.FrogdashInstruments = {render};
  window.addEventListener('frogdash-appearance',()=>{ if(last) render(last.snapshot,last.connected); });
  window.addEventListener('frogdash-units',()=>{ if(last) render(last.snapshot,last.connected); });
})();
