/* Layout is independent of telemetry, connection state and saved appearance. */
(() => {
  const root = document.documentElement;
  function resize() {
    const viewport = window.visualViewport;
    const width = viewport?.width || innerWidth;
    const height = viewport?.height || innerHeight;
    root.style.setProperty('--panel-scale', Math.min(width / 1920, height / 720));
    root.style.setProperty('--viewport-height', `${height}px`);
    root.style.setProperty('--viewport-width', `${width}px`);
    root.style.setProperty('--viewport-left', `${viewport?.offsetLeft || 0}px`);
    root.style.setProperty('--viewport-top', `${viewport?.offsetTop || 0}px`);
  }
  window.addEventListener('resize', resize);
  window.visualViewport?.addEventListener('resize', resize);
  window.visualViewport?.addEventListener('scroll', resize);
  resize();
})();
