/* Camera pictures that fill the screen. The cameras are fixed (4:3 or 16:9) and the screen
   is 1920 x 720, so the picture used to sit in a box with black beside it. Three ways to
   show it, chosen beside the picture and remembered per view:
   - Whole: the picture as it comes, nothing cut off.
   - Fill: cropped to fill, more from the top than the bottom (the ground behind the
     bumper matters more than the sky).
   - Wide: a little cropped, then widened with a curve, like a TV's panorama mode: the
     middle stays close to its true shape and the edges take the stretch. Fills the space.
   Drawn with WebGL from the live <img> (or the preview's demo canvas). */
(() => {
  'use strict';
  const KEY = 'frogdash.cameraview.v1';
  const MODES = [['whole', 'Whole'], ['fill', 'Fill'], ['wide', 'Wide']];
  const MIN_KEEP = .82;      // Wide: at most 18% of the height is cut off
  const TOP_SHARE = .65;     // ...two thirds of it from the top
  const MAX_CENTRE = 1.45;   // Wide: the curve's limit (the edges stay readable)
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY)) || {}; } catch { saved = {}; }

  const VERTEX = 'attribute vec2 p; varying vec2 v; void main(){ v = vec2(p.x * .5 + .5, .5 - p.y * .5); gl_Position = vec4(p, 0., 1.); }';
  const FRAGMENT = `precision mediump float; varying vec2 v; uniform sampler2D t; uniform float a; uniform vec2 h; uniform vec2 w;
    void main(){ float x = v.x * 2. - 1.; float u = (a * x + (1. - a) * x * x * x) * .5 + .5;
      gl_FragColor = texture2D(t, vec2(h.x + u * h.y, w.x + v.y * w.y)); }`;

  // Where the picture is taken from, for a stage of aspect `stage` and a source of `source`:
  // {a: centre slope of the curve (1 = straight), h: [start, width] across, w: [start, height] down}.
  function plan(mode, stage, source) {
    if (mode === 'wide') {
      const keep = Math.max(MIN_KEEP, Math.min(1, source / stage));
      const k = stage / (source / keep);
      if (k > 1) return {a: Math.min(k, MAX_CENTRE), h: [0, 1], w: [(1 - keep) * TOP_SHARE, keep]};
      mode = 'fill';
    }
    if (source > stage) { const keep = stage / source; return {a: 1, h: [(1 - keep) / 2, keep], w: [0, 1]}; }
    const keep = source / stage;
    return {a: 1, h: [0, 1], w: [(1 - keep) * TOP_SHARE, keep]};
  }

  function attach({name, dialog, img, demo, after}) {
    const stage = img.closest('.camera-stage');
    const canvas = document.createElement('canvas');
    canvas.className = 'camera-view'; canvas.setAttribute('aria-hidden', 'true');
    img.after(canvas);
    let mode = MODES.some(([m]) => m === saved[name]) ? saved[name] : 'wide';
    const buttons = document.createElement('div');
    buttons.className = 'camera-toggles camera-view-modes'; buttons.setAttribute('role', 'group'); buttons.setAttribute('aria-label', 'Picture');
    for (const [key, label] of MODES) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = label; button.dataset.view = key;
      button.onclick = () => { mode = key; saved[name] = key; try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch { /* Session only. */ } show(); };
      buttons.append(button);
    }
    after.after(buttons);

    const gl = canvas.getContext('webgl', {alpha: false, antialias: false, preserveDrawingBuffer: true});
    let ready = false, uniforms = {};
    if (gl) {
      const shader = (kind, source) => { const s = gl.createShader(kind); gl.shaderSource(s, source); gl.compileShader(s); return s; };
      const program = gl.createProgram();
      gl.attachShader(program, shader(gl.VERTEX_SHADER, VERTEX));
      gl.attachShader(program, shader(gl.FRAGMENT_SHADER, FRAGMENT));
      gl.linkProgram(program);
      if (gl.getProgramParameter(program, gl.LINK_STATUS)) {
        gl.useProgram(program);
        gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        const at = gl.getAttribLocation(program, 'p');
        gl.enableVertexAttribArray(at);
        gl.vertexAttribPointer(at, 2, gl.FLOAT, false, 0, 0);
        gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
        for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
        uniforms = {a: gl.getUniformLocation(program, 'a'), h: gl.getUniformLocation(program, 'h'), w: gl.getUniformLocation(program, 'w')};
        ready = true;
      }
    }
    stage.dataset.gl = ready ? 'yes' : 'no';

    function show() {
      stage.dataset.view = mode;
      for (const b of buttons.children) b.setAttribute('aria-pressed', String(b.dataset.view === mode));
      if (mode !== 'whole' && ready && dialog.open) loop();
    }
    const source = () => demo && !demo.hidden ? demo : img;
    let frame = 0, last = 0;
    function draw() {
      const from = source();
      const width = from.naturalWidth ?? from.width, height = from.naturalHeight ?? from.height;
      canvas.hidden = from.hidden || !width;
      if (canvas.hidden) return;
      const w = Math.round(canvas.clientWidth * devicePixelRatio), h = Math.round(canvas.clientHeight * devicePixelRatio);
      if (!w || !h) return;
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);
      try {
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, from);
      } catch { return; }   // No frame yet.
      const p = plan(mode, w / h, width / height);
      gl.uniform1f(uniforms.a, p.a);
      gl.uniform2f(uniforms.h, ...p.h);
      gl.uniform2f(uniforms.w, ...p.w);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    function loop() {
      if (frame) return;
      const step = now => {
        frame = 0;
        if (!dialog.open || mode === 'whole') return;
        if (now - last >= 30) { last = now; draw(); }   // About 30 pictures a second
        frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    }
    new MutationObserver(show).observe(dialog, {attributes: true, attributeFilter: ['open']});
    show();
    return {get mode() { return mode; }, plan};
  }

  window.FrogdashCameraView = {attach, plan};
  const $ = id => document.getElementById(id);
  if ($('camera-feed')) attach({name: 'camera', dialog: $('camera-dialog'), img: $('camera-feed'), demo: $('camera-demo'), after: document.querySelector('#camera-dialog .camera-toggles')});
  if ($('dashcam-feed')) attach({name: 'dashcam', dialog: $('dashcam-dialog'), img: $('dashcam-feed'), after: document.querySelector('#dashcam-dialog .camera-toggles')});
})();
