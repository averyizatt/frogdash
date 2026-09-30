/* Runs in <head> before first paint: apply the saved look so the default appearance
   never flashes, and keep the dashboard hidden until an enabled splash is showing. */
(() => {
  'use strict';
  try {
    const root = document.documentElement;
    const paint = JSON.parse(localStorage.getItem('frogdash.appearance.paint.v1'));
    if (!paint || typeof paint !== 'object') return;
    if (typeof paint.style === 'string' && paint.style.length < 20000) root.setAttribute('style', paint.style);
    for (const [name, value] of Object.entries(paint.data || {})) {
      if (/^[a-zA-Z]{1,30}$/.test(name) && typeof value === 'string' && /^[\w-]{1,40}$/.test(value)) root.dataset[name] = value;
    }
    // The uploaded background image lives only in the main profile, not in the snapshot.
    if (paint.data?.finish === 'image') {
      const background = JSON.parse(localStorage.getItem('frogdash.appearance.v1'))?.background;
      if (typeof background === 'string' && /^data:image\/(jpeg|png|webp);base64,/.test(background)) root.style.setProperty('--custom-background', `url("${background}")`);
    }
    if (paint.splash === true) {
      root.dataset.splashPending = 'true';
      // Failsafe: the gauges are never kept hidden for long, whatever else happens.
      setTimeout(() => { delete root.dataset.splashPending; }, 3000);
    }
  } catch { /* No snapshot or storage: the page applies the look normally. */ }
})();
