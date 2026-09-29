/* Layout is independent of telemetry, connection state and saved appearance. */
(() => {
  const root = document.documentElement;
  window.frogdashDisplayInfo = () => {
    const node = document.getElementById('display'), rect = node.getBoundingClientRect();
    const css = getComputedStyle(node), viewport = window.visualViewport;
    const round = n => Math.round(n * 100) / 100;
    return {
      screen: [screen.width, screen.height], viewport: [innerWidth, innerHeight],
      visual: viewport ? [viewport.width, viewport.height, viewport.scale, viewport.offsetLeft, viewport.offsetTop].map(round) : [],
      pixel_ratio: devicePixelRatio, responsive: matchMedia('(max-aspect-ratio: 11/5)').matches,
      dashboard: [rect.left, rect.top, rect.width, rect.height].map(round),
      position: css.position, transform: css.transform, margin: css.margin,
      body_overflow: getComputedStyle(document.body).overflow,
      scroll: [scrollX, scrollY], browser: navigator.userAgent.slice(0, 200),
      responsive_css: [...document.styleSheets].some(sheet => sheet.href && new URL(sheet.href).pathname.endsWith('/responsive.css'))
    };
  };
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
