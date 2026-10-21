/* The screens that are not the gauges, loaded after them.

   The page starts with what driving needs: the gauges and their look, the warning
   alerts, and the reverse camera and dash cam (they open on the reverse signal). The rest
   (menus, wheel navigation, taillights, knock, water/meth tuning, map, graphs,
   management, drive summary) waits until the gauges have drawn their first frame, then
   DELAY_MS more, and is loaded one file at a time between frames, so the gauges never
   stutter. They are all in place well before anyone opens them. The list is in
   index.html (#later-files), in the order the files depend on each other.

   A press on one of their buttons before that loads them at once, then repeats the press.
   window.frogdashLater resolves when everything is loaded. */
(() => {
  'use strict';
  // Tests that drive the screen from its first second set window.frogdashLaterDelay = 0.
  const DELAY_MS = Number.isFinite(window.frogdashLaterDelay) ? window.frogdashLaterDelay : 4000;
  // Buttons of screens that are loaded first: never held back.
  const FIRST = new Set(['drive-launch', 'alerts-launch', 'bookmark-launch', 'camera-launch', 'dashcam-launch', 'race-launch', 'appearance-launch']);
  let files = [];
  try { files = JSON.parse(document.getElementById('later-files')?.textContent || '[]'); } catch { files = []; }
  let started = false, finish;
  const done = new Promise(resolve => { finish = resolve; });
  window.frogdashLater = done;
  window.frogdashLaterLoaded = false;

  const frame = () => new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 0)));
  function add(name) {
    return new Promise(resolve => {
      const css = /\.css(\?|$)/.test(name);
      const node = document.createElement(css ? 'link' : 'script');
      if (css) { node.rel = 'stylesheet'; node.href = name; } else { node.src = name; node.async = false; }
      // A file that fails to load is skipped: the others and the gauges carry on.
      node.onload = node.onerror = () => resolve();
      (css ? document.head : document.body).append(node);
    });
  }
  async function load() {
    if (started) return done;
    started = true;
    clearTimeout(timer);
    for (const name of files) {
      await add(name);
      await frame();          // One file per frame: the gauges keep drawing in between
    }
    window.frogdashLaterLoaded = true;
    window.frogdashLaterMs = performance.now();   // For the reports (viewport.js)
    window.dispatchEvent(new Event('frogdash-later'));   // For the first screens that add to later ones
    finish();
    return done;
  }
  window.frogdashLoadLater = load;

  // After the first frame of the gauges (app.js counts them), then the delay.
  let timer = null;
  (function wait() {
    if (window.frogdashRendered) timer = setTimeout(load, DELAY_MS);
    else setTimeout(wait, 100);
  })();
  // Whatever happens, never leave them unloaded: the dash may stay disconnected.
  setTimeout(load, DELAY_MS + 8000);

  // A press on one of their buttons before they are here: load now, then press again.
  document.addEventListener('click', event => {
    if (window.frogdashLaterLoaded) return;
    const button = event.target.closest?.('[id$="-launch"], [data-later]');
    if (!button || FIRST.has(button.id)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    load().then(() => button.click());
  }, true);
})();
