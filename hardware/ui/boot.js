/* Runs in <head> before first paint: apply the saved look so the default appearance
   never flashes, and keep the dashboard hidden until an enabled splash is showing.
   The Pi normally serves the look inside the page already; browser storage is the
   fallback (and the only source in the standalone preview). */
(() => {
  'use strict';
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
