/* Drive summary (hardware/frogdash/summary.py). When the key goes off the PiSugar counts down
   to shutdown; this drive's figures fill the screen for those seconds, with the countdown.
   The key back on closes it. Software & power > Last drive shows it again. */
(() => {
  'use strict';
  const u = window.FrogdashUnits;
  const dialog = document.createElement('dialog');
  dialog.id = 'summary-dialog'; dialog.className = 'workspace-dialog summary-dialog'; dialog.setAttribute('aria-labelledby', 'summary-title');
  dialog.innerHTML = '<header class="summary-head"><div><span class="eyebrow">DRIVE SUMMARY</span><h2 id="summary-title">This drive</h2><p id="summary-when"></p></div>' +
    '<div class="summary-countdown" id="summary-countdown" hidden><strong id="summary-seconds"></strong><span>Shutting down · key on to keep going</span><i><b id="summary-bar"></b></i></div>' +
    '<button type="button" class="close-button" id="summary-close">Close ×</button></header><ul class="summary-grid" id="summary-grid"></ul>';
  document.body.append(dialog);
  let countdown = false, longest = 0, latest = null;

  const one = (value, digits = 0) => value == null ? '—' : Number(value).toFixed(digits);
  function rows(d) {
    const minutes = Math.round((d.duration_s || 0) / 60);
    const meth = d.meth_spray_s || 0;
    return [
      ['Distance', one(u.distance(d.distance_km), 1), u.distanceUnit],
      ['Time', minutes >= 60 ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}` : String(minutes), minutes >= 60 ? 'h:mm' : 'min'],
      ['Top speed', one(d.top_speed_kph == null ? null : u.distance(d.top_speed_kph)), u.speedUnit],
      ['Average speed', one(d.duration_s >= 60 ? u.distance(d.distance_km / (d.duration_s / 3600)) : null), u.speedUnit],
      ['Peak boost', one(d.peak_boost_kpa == null ? null : u.boost(d.peak_boost_kpa), u.metric ? 0 : 1), u.metric ? 'kPa' : 'psi'],
      ['Highest RPM', one(d.max_rpm), 'RPM'],
      ['Hottest coolant', one(d.max_coolant_c == null ? null : u.temperature(d.max_coolant_c)), u.metric ? '°C' : '°F'],
      ['Lowest oil (1500+ RPM)', one(d.min_oil_psi == null ? null : u.pressure(d.min_oil_psi), u.metric ? 0 : 1), u.metric ? 'kPa' : 'psi'],
      ['Water / meth sprayed', meth >= 60 ? `${Math.floor(meth / 60)}:${String(Math.round(meth % 60)).padStart(2, '0')}` : one(meth), meth >= 60 ? 'm:ss' : 's'],
      ['Knock events', String(d.knock_events || 0), '', d.knock_events ? 'warn' : 'good'],
      ['Alerts', String(d.alerts || 0), '', d.alerts ? 'warn' : 'good'],
      ['Problems noted', String(d.problems || 0), '', d.problems ? 'warn' : 'good'],
    ];
  }
  function render(d, ongoing) {
    $('summary-title').textContent = ongoing ? 'This drive so far' : 'This drive';
    const started = new Date(d.started * 1000);
    $('summary-when').textContent = `${started.toLocaleDateString([], {weekday: 'short', month: 'short', day: 'numeric'})} · ${started.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}` +
      (d.ended ? ` – ${new Date(d.ended * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}` : '');
    $('summary-grid').replaceChildren(...rows(d).map(([label, value, unit, tone]) => {
      const item = document.createElement('li');
      if (tone) item.dataset.tone = tone;
      item.innerHTML = '<span></span><strong></strong><small></small>';
      item.children[0].textContent = label; item.children[1].textContent = value; item.children[2].textContent = unit;
      return item;
    }));
  }
  function $(id) { return document.getElementById(id); }
  function show(d, ongoing) {
    render(d, ongoing);
    if (!dialog.open) dialog.showModal();
  }
  function open() {
    const s = latest?.summary;
    const d = s?.current || s?.last;
    if (d) show(d, !!s.current);
  }
  function tick(snapshot, connected) {
    latest = snapshot;
    const s = snapshot.summary;
    if (!s || !connected) return;
    const ending = s.shutting_down && s.last && !s.current;
    if (ending) {
      if (!countdown) { countdown = true; longest = 0; }
      $('summary-countdown').hidden = false;
      const left = s.remaining_s;
      longest = Math.max(longest, left || 0);
      $('summary-seconds').textContent = left == null ? 'Off' : `${Math.ceil(left)} s`;
      $('summary-bar').style.width = `${left == null || !longest ? 0 : Math.max(0, Math.min(100, left / longest * 100))}%`;
      show(s.last, false);
    } else if (countdown) {
      countdown = false;   // The key came back on: back to the gauges.
      $('summary-countdown').hidden = true;
      if (dialog.open) dialog.close();
    }
  }
  $('summary-close').onclick = () => dialog.close();
  window.addEventListener('frogdash-state', ({detail}) => tick(detail.snapshot, detail.connected));
  window.FrogdashSummary = {open, get open_() { return dialog.open; }};
})();
