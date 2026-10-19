/* Runs in <head> before first paint: apply the saved look so the default appearance
   never flashes, and keep the dashboard hidden until an enabled splash is showing.
   The Pi normally serves the look inside the page already; browser storage is the
   fallback (and the only source in the standalone preview). */
(() => {
  'use strict';
  // An error in the screen's code is sent to the dash, which records it like any other
  // fault (Support & testing > What happened, and the report): on the Pi there is no
  // console to read. Each message at most once a minute.
  const reported = new Map();
  function report(message, where) {
    const text = String(message || 'Unknown error').slice(0, 200), now = Date.now();
    if (reported.size > 50 || now - (reported.get(text) || 0) < 60000) return;
    reported.set(text, now);
    try {
      fetch('/ui/error', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text, where: String(where || '').slice(0, 120)})}).catch(() => {});
    } catch { /* The report is best effort. */ }
  }
  window.addEventListener('error', event => report(event.message, `${(event.filename || '').split('/').pop()}:${event.lineno || 0}`));
  window.addEventListener('unhandledrejection', event => report(event.reason?.message || event.reason, 'promise'));
  const root = document.documentElement;
  try {
    if (!root.hasAttribute('style')) {
      const paint = JSON.parse(localStorage.getItem('frogdash.appearance.paint.v1'));
      if (paint && typeof paint === 'object') {
        if (typeof paint.style === 'string' && paint.style.length < 20000) root.setAttribute('style', paint.style);
        for (const [name, value] of Object.entries(paint.data || {})) {
          if (/^[a-zA-Z]{1,30}$/.test(name) && typeof value === 'string' && /^[\w-]{1,40}$/.test(value)) root.dataset[name] = value;
        }
        if (paint.splash === true) root.dataset.splashPending = 'true';
      }
    }
  } catch { /* No snapshot or storage: the page applies the look normally. */ }
  try {
    // The uploaded background image lives only in the main profile, never in a snapshot.
    if (root.dataset.finish === 'image') {
      const background = JSON.parse(localStorage.getItem('frogdash.appearance.v1'))?.background;
      if (typeof background === 'string' && /^data:image\/(jpeg|png|webp);base64,/.test(background)) root.style.setProperty('--custom-background', `url("${background}")`);
    }
  } catch { /* The page loads the image itself shortly after. */ }
  // Failsafe: the gauges are never kept hidden for long, whatever else happens.
  if (root.dataset.splashPending) setTimeout(() => { delete root.dataset.splashPending; }, 3000);
})();

// Hide the mouse pointer unless a mouse is in use; it returns on movement and hides after 3 s idle.
(() => {
  const root = document.documentElement;
  let timer;
  root.classList.add('cursor-hidden');
  addEventListener('pointermove', event => {
    if (event.pointerType !== 'mouse') return;
    root.classList.remove('cursor-hidden');
    clearTimeout(timer);
    timer = setTimeout(() => root.classList.add('cursor-hidden'), 3000);
  }, {passive: true});
})();
