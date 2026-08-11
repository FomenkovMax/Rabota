/* ═══════════════════════════════════════════════════════════
   FRAME ENGINE — one runtime, two characters

   Act I scrubs a frame sequence with the scroll; Act II picks a frame
   from the pointer's X position. Everything a character changes lives
   in window.SITE (below) and in its own theme.css — this file never
   names a character or a colour.
   ═══════════════════════════════════════════════════════════ */

const CFG = window.SITE;
const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const COARSE  = window.matchMedia('(hover: none)').matches;

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp  = (a, b, t) => a + (b - a) * t;
const window4 = (p, a, b, c, d) =>
  p < a || p > d ? 0 : p < b ? (p - a) / (b - a) : p > c ? 1 - (p - c) / (d - c) : 1;

/* palette comes from the theme stylesheet, so the engine stays neutral */
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const rgbOf = hex => {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
  return [n >> 16 & 255, n >> 8 & 255, n & 255];
};
let ACCENT = [255, 47, 74], ACCENT2 = [140, 20, 30];

/* ─────────────────── frame loading ───────────────────
   Act I gates the loader because it is what the first scroll needs;
   Act II streams in behind it, so the page opens sooner than a
   load-everything-first preloader would allow. */
const pad = n => String(n).padStart(3, '0');
const mainFrames = [];
const eyeFrames = [];

const loaderEl = document.getElementById('loader');
const loaderFill = document.getElementById('loaderFill');
const loaderPct = document.getElementById('loaderPct');

function loadFrame(src, bucket, i, onDone) {
  const img = new Image();
  img.decoding = 'async';
  img.onload = img.onerror = () => { bucket[i] = img.naturalWidth ? img : null; onDone(); };
  img.src = src;
}

(function preload() {
  const total = CFG.main.count;
  let done = 0;
  const tick = () => {
    done++;
    const pct = done / total;
    loaderFill.style.width = (pct * 100).toFixed(1) + '%';
    loaderPct.textContent = String(Math.round(pct * 100)).padStart(2, '0');
    if (done === total) ready();
  };
  for (let i = 1; i <= total; i++) loadFrame(CFG.main.dir + pad(i) + '.jpg', mainFrames, i - 1, tick);
})();

function ready() {
  loaderEl.classList.add('done');
  document.body.classList.add('ready');
  resizeAll();
  setTimeout(() => { loaderEl.style.display = 'none'; }, 1100);
  /* Act II frames, once the first screen is paid for */
  for (let i = 1; i <= CFG.eyes.count; i++) {
    loadFrame(CFG.eyes.dir + pad(i) + '.jpg', eyeFrames, i - 1, () => {});
  }
}

/* ─────────────────── canvas helpers ─────────────────── */
function fitCanvas(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.round(canvas.offsetWidth * dpr);
  const h = Math.round(canvas.offsetHeight * dpr);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  return canvas.getContext('2d');
}
function needsResize(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  return canvas.width !== Math.round(canvas.offsetWidth * dpr) ||
         canvas.height !== Math.round(canvas.offsetHeight * dpr);
}
/* Fills the canvas without cropping the sides harder than maxUp allows, so a
   tall narrow phone gets the composition rather than a zoom into one cheek. */
function drawCover(ctx, img, cw, ch, maxUp = 2.0, ox = 0, oy = 0) {
  if (!img || !img.naturalWidth) return false;
  const ir = img.naturalWidth / img.naturalHeight;
  let w = cw, h = cw / ir;
  if (h < ch) { const s = Math.min(ch / h, maxUp); w *= s; h *= s; }
  ctx.drawImage(img, (cw - w) / 2 + ox, (ch - h) / 2 + oy, w, h);
  return true;
}
function sectionProgress(el) {
  const r = el.getBoundingClientRect();
  const span = el.offsetHeight - window.innerHeight;
  return span <= 0 ? 0 : clamp(-r.top / span);
}
/* nearest loaded neighbour, so a single failed frame never blanks the scene */
function frameAt(bucket, i) {
  for (let d = 0; d < bucket.length; d++) {
    if (bucket[i + d]) return bucket[i + d];
    if (bucket[i - d]) return bucket[i - d];
  }
  return null;
}

/* ═══════════ ACT I — scroll-scrubbed frames ═══════════ */
const scrubEl = document.getElementById('scrub');
const mainCanvas = document.getElementById('mainCanvas');
const scrubGlow = document.getElementById('scrubGlow');
const titleblock = document.getElementById('titleblock');
const phaseEls = [...document.querySelectorAll('.phase')];

function renderScrub(p) {
  const ctx = fitCanvas(mainCanvas);
  const W = mainCanvas.width, H = mainCanvas.height;
  const idx = Math.round(p * (CFG.main.count - 1));

  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);
  drawCover(ctx, frameAt(mainFrames, idx), W, H, CFG.main.maxUp ?? 2.0);

  scrubGlow.style.opacity = (window4(p, 0.3, 0.62, 0.9, 1.02) * 0.85).toFixed(3);
  titleblock.style.opacity = window4(p, ...CFG.titleWindow).toFixed(3);
  phaseEls.forEach((el, i) => { el.style.opacity = window4(p, ...CFG.phases[i]).toFixed(3); });
}

/* ─────────── ambient motes over Act I ─────────── */
const moteCanvas = document.getElementById('moteCanvas');
const MOTES = Array.from({ length: REDUCED ? 0 : 56 }, () => ({
  x: Math.random(), y: Math.random(),
  vx: (Math.random() - 0.5) * 0.00012,
  vy: -Math.random() * 0.00018 - 0.00004,
  r: Math.random() * 2.4 + 0.6,
  a: Math.random() * 0.5 + 0.2,
  hot: Math.random() > 0.7
}));

function renderMotes(p, dt) {
  const ctx = fitCanvas(moteCanvas);
  const W = moteCanvas.width, H = moteCanvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!MOTES.length) return;
  ctx.globalCompositeOperation = 'lighter';
  for (const m of MOTES) {
    m.x += m.vx * dt; m.y += m.vy * dt;
    if (m.y < -0.05) { m.y = 1.05; m.x = Math.random(); }
    if (m.x < -0.05) m.x = 1.05; else if (m.x > 1.05) m.x = -0.05;
    const x = m.x * W, y = m.y * H, rad = m.r * (H / 900) * 6;
    const c = m.hot ? ACCENT : ACCENT2;
    const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
    g.addColorStop(0, `rgba(${c[0]},${c[1]},${c[2]},${m.a * (0.25 + 0.75 * p)})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
  }
}

/* ═══════════ ACT II — the pointer picks the frame ═══════════ */
const eyesEl = document.getElementById('eyes');
const eyeCanvas = document.getElementById('eyeCanvas');
const eyeFlare = document.getElementById('eyeFlare');
const eyeReadout = document.getElementById('eyeReadout');

const pointer = { x: 0.5, y: 0.5, sx: 0.5, sy: 0.5 };
if (!COARSE) {
  window.addEventListener('pointermove', e => {
    pointer.x = e.clientX / window.innerWidth;
    pointer.y = e.clientY / window.innerHeight;
  }, { passive: true });
}

function renderEyes(p, t) {
  const ctx = fitCanvas(eyeCanvas);
  const W = eyeCanvas.width, H = eyeCanvas.height;

  let gx, gy;
  if (COARSE) {
    gx = 0.5 + Math.sin(t * 0.0005) * 0.45;
    gy = 0.5 + Math.sin(t * 0.00031) * 0.2;
  } else {
    pointer.sx = lerp(pointer.sx, pointer.x, 0.12);
    pointer.sy = lerp(pointer.sy, pointer.y, 0.12);
    gx = pointer.sx; gy = pointer.sy;
  }

  const idx = Math.round(clamp(gx) * (CFG.eyes.count - 1));
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);
  /* a few pixels of vertical parallax sell the tracking the frames can't do */
  drawCover(ctx, frameAt(eyeFrames, idx), W, H, CFG.eyes.maxUp ?? 2.4,
            0, (gy - 0.5) * H * 0.05);

  eyeFlare.style.opacity = (0.35 + 0.5 * Math.abs(gx - 0.5) * 2).toFixed(3);

  const fmt = v => (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1).padStart(4, '0');
  eyeReadout.textContent = CFG.readout(fmt((gx - 0.5) * 2), fmt((gy - 0.5) * 2), idx + 1);
}

/* ═══════════ AMBIENT — hem, discharge, cursor, trail ═══════════ */
const hemCanvas = document.getElementById('hemCanvas');
const HEM = Array.from({ length: REDUCED ? 0 : 44 }, () => ({
  x: Math.random(), y: Math.random(),
  vy: -(Math.random() * 0.0006 + 0.0003),
  r: Math.random() * 0.5 + 0.35,
  seed: Math.random() * 100,
  hot: Math.random() > 0.55
}));

function renderHem(t, dt) {
  const ctx = fitCanvas(hemCanvas);
  const W = hemCanvas.width, H = hemCanvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!HEM.length) return;
  ctx.globalCompositeOperation = 'lighter';
  for (const f of HEM) {
    f.y += f.vy * dt;
    if (f.y < -0.2) { f.y = 1.1; f.x = Math.random(); }
    const x = (f.x + Math.sin(t * 0.002 + f.seed) * 0.012) * W, y = f.y * H;
    const rad = f.r * H * 0.9;
    const fade = clamp(1 - Math.abs(f.y - 0.6) * 1.1);
    const c = f.hot ? ACCENT : ACCENT2;
    const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
    g.addColorStop(0, `rgba(${c[0]},${c[1]},${c[2]},${0.3 * fade})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
  }
}

const stormFlash = document.getElementById('stormFlash');
const boltPath = document.getElementById('boltPath');
const boltGlow = document.getElementById('boltGlow');
const boltSvg = document.getElementById('stormBolt');

function boltD() {
  const x0 = 150 + Math.random() * 700;
  let x = x0, y = 0, d = `M${x.toFixed(1)} 0`;
  while (y < 1000) {
    y += 60 + Math.random() * 90;
    x += (Math.random() - 0.5) * 190;
    const cx = clamp(x, 20, 980).toFixed(1);
    d += ` L${cx} ${Math.min(y, 1000).toFixed(1)}`;
    if (Math.random() > 0.72 && y < 700) {
      const fx = clamp(x + (Math.random() - 0.5) * 300, 20, 980).toFixed(1);
      const fy = (y + 120 + Math.random() * 160).toFixed(1);
      d += ` M${cx} ${y.toFixed(1)} L${fx} ${fy} M${cx} ${y.toFixed(1)}`;
    }
  }
  return { d, x0 };
}

function strike() {
  const { d, x0 } = boltD();
  boltPath.setAttribute('d', d);
  boltGlow.setAttribute('d', d);
  stormFlash.style.setProperty('--bx', (x0 / 10).toFixed(1) + '%');
  const seq = [[1, 40], [0.15, 60], [0.9, 50], [0, 260]];
  let i = 0;
  (function step() {
    if (i >= seq.length) return;
    const [v, ms] = seq[i++];
    boltSvg.style.opacity = v;
    stormFlash.style.opacity = v * 0.7;
    setTimeout(step, ms);
  })();
  if (audio.on) audio.crack();
}

if (!REDUCED) {
  (function schedule() {
    setTimeout(() => { if (!document.hidden) strike(); schedule(); },
      7000 + Math.random() * 13000);
  })();
}

const cursorEl = document.getElementById('cursor');
const cur = { x: innerWidth / 2, y: innerHeight / 2, tx: innerWidth / 2, ty: innerHeight / 2 };
if (!COARSE && !REDUCED) {
  window.addEventListener('pointermove', e => { cur.tx = e.clientX; cur.ty = e.clientY; }, { passive: true });
  document.querySelectorAll('a, button, .card').forEach(el => {
    el.addEventListener('pointerenter', () => cursorEl.classList.add('hot'));
    el.addEventListener('pointerleave', () => cursorEl.classList.remove('hot'));
  });
}
function stepCursor() {
  const dx = cur.tx - cur.x, dy = cur.ty - cur.y;
  const gain = 0.06 + 0.16 * clamp(Math.hypot(dx, dy) / 260);
  cur.x += dx * gain; cur.y += dy * gain;
  cursorEl.style.transform = `translate(${cur.x.toFixed(1)}px, ${cur.y.toFixed(1)}px)`;
}

const ghostCanvas = document.getElementById('ghostCanvas');
const jutsuEl = document.getElementById('jutsu');
const TRAIL = [];
if (!COARSE && !REDUCED) {
  jutsuEl.addEventListener('pointermove', e => {
    const r = ghostCanvas.getBoundingClientRect();
    TRAIL.push({ x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, born: performance.now() });
    if (TRAIL.length > 34) TRAIL.shift();
  }, { passive: true });
}
function renderGhost(now) {
  const ctx = fitCanvas(ghostCanvas);
  const W = ghostCanvas.width, H = ghostCanvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!TRAIL.length) return;
  ctx.globalCompositeOperation = 'lighter';
  for (let i = 0; i < TRAIL.length; i++) {
    const pt = TRAIL[i];
    const age = (now - pt.born) / 1500;
    if (age >= 1) continue;
    const life = 1 - age, head = i / TRAIL.length;
    const rad = W * (0.035 + 0.09 * age);
    const x = pt.x * W, y = pt.y * H;
    const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
    g.addColorStop(0, `rgba(${ACCENT[0]},${ACCENT[1]},${ACCENT[2]},${0.15 * life * (0.35 + head)})`);
    g.addColorStop(0.4, `rgba(${ACCENT2[0]},${ACCENT2[1]},${ACCENT2[2]},${0.09 * life * (0.35 + head)})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
  }
  while (TRAIL.length && now - TRAIL[0].born > 1500) TRAIL.shift();
}

/* ═══════════ AUDIO — synthesised, no files ═══════════ */
const audio = {
  on: false, ctx: null, gain: null,
  init() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    this.ctx = new AC();
    this.gain = this.ctx.createGain();
    this.gain.gain.value = 0;
    this.gain.connect(this.ctx.destination);
    const filter = this.ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = CFG.audio.cutoff;
    filter.Q.value = 6;
    filter.connect(this.gain);
    CFG.audio.voices.forEach(v => {
      const o = this.ctx.createOscillator();
      o.type = v.type; o.frequency.value = v.freq;
      const g = this.ctx.createGain(); g.gain.value = v.gain;
      o.connect(g); g.connect(filter); o.start();
    });
    const lfo = this.ctx.createOscillator();
    lfo.frequency.value = 0.07;
    const lg = this.ctx.createGain(); lg.gain.value = CFG.audio.cutoff * 0.45;
    lfo.connect(lg); lg.connect(filter.frequency); lfo.start();
    return true;
  },
  toggle() {
    if (!this.ctx && !this.init()) return false;
    if (this.ctx.state === 'suspended') this.ctx.resume();
    this.on = !this.on;
    const now = this.ctx.currentTime;
    this.gain.gain.cancelScheduledValues(now);
    this.gain.gain.setTargetAtTime(this.on ? 0.16 : 0, now, 0.6);
    return this.on;
  },
  crack() {
    if (!this.on || !this.ctx) return;
    const dur = 1.2;
    const buf = this.ctx.createBuffer(1, this.ctx.sampleRate * dur, this.ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / data.length, 3);
    }
    const src = this.ctx.createBufferSource(); src.buffer = buf;
    const bp = this.ctx.createBiquadFilter();
    bp.type = 'bandpass'; bp.frequency.value = 420; bp.Q.value = 0.8;
    const g = this.ctx.createGain(); g.gain.value = 0.22;
    src.connect(bp); bp.connect(g); g.connect(this.gain);
    src.start();
  }
};

const soundToggle = document.getElementById('soundToggle');
const soundState = document.getElementById('soundState');
soundToggle.addEventListener('click', () => {
  const on = audio.toggle();
  soundToggle.setAttribute('aria-pressed', String(!!on));
  soundState.textContent = on ? 'ON' : 'OFF';
});

/* ═══════════ CHROME + REVEALS ═══════════ */
const railScroll = document.getElementById('railScroll');
const hintEl = document.getElementById('hint');
const stickyBadge = document.getElementById('stickyBadge');

const io = new IntersectionObserver(es => {
  for (const e of es) if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
}, { threshold: 0.18 });
document.querySelectorAll('[data-px], .card').forEach(el => io.observe(el));

const litIo = new IntersectionObserver(es => {
  for (const e of es) jutsuEl.classList.toggle('lit', e.isIntersecting);
}, { threshold: 0.12 });
litIo.observe(jutsuEl);

/* ═══════════ MAIN LOOP ═══════════ */
let last = performance.now();
function resizeAll() {
  [mainCanvas, moteCanvas, eyeCanvas, hemCanvas, ghostCanvas]
    .forEach(c => { if (needsResize(c)) fitCanvas(c); });
}
window.addEventListener('resize', resizeAll, { passive: true });
window.addEventListener('orientationchange', resizeAll, { passive: true });

function frame(now) {
  const dt = Math.min(now - last, 64);
  last = now;

  /* scrollingElement, not documentElement: in quirks mode the scroller is
     <body>, and a host that wraps this page can put it there */
  const doc = document.scrollingElement || document.documentElement;
  const scrolled = doc.scrollTop / Math.max(1, doc.scrollHeight - doc.clientHeight);
  railScroll.textContent = 'SCROLL ' + String(Math.round(scrolled * 100)).padStart(3, '0') + '%';
  hintEl.classList.toggle('hide', doc.scrollTop > window.innerHeight * 0.35);
  stickyBadge.classList.toggle('show', doc.scrollTop > window.innerHeight * 0.8);

  const sRect = scrubEl.getBoundingClientRect();
  if (sRect.bottom > -200 && sRect.top < window.innerHeight + 200) {
    const p = sectionProgress(scrubEl);
    renderScrub(p);
    renderMotes(p, dt);
  }
  const eRect = eyesEl.getBoundingClientRect();
  if (eRect.bottom > -200 && eRect.top < window.innerHeight + 200) {
    renderEyes(sectionProgress(eyesEl), now);
  }
  const jRect = jutsuEl.getBoundingClientRect();
  if (jRect.bottom > 0 && jRect.top < window.innerHeight) renderGhost(now);

  renderHem(now, dt);
  if (!COARSE && !REDUCED) stepCursor();

  requestAnimationFrame(frame);
}

/* the theme stylesheet may still be parsing when this file runs */
requestAnimationFrame(() => {
  ACCENT = rgbOf(css('--accent-hot') || '#ff2f4a');
  ACCENT2 = rgbOf(css('--accent-deep') || '#8c141e');
  requestAnimationFrame(frame);
});
