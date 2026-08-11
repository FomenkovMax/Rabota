/* ═══════════════════════════════════════════════════════════
   GOJO SATORU — procedural scroll scrub + cursor-tracked Six Eyes

   No image sequence: every frame of Act I and Act II is drawn from
   scratch on canvas, so the page ships with zero binary assets and
   scrubs at whatever resolution the display happens to have.
   ═══════════════════════════════════════════════════════════ */

const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const COARSE  = window.matchMedia('(hover: none)').matches;

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp  = (a, b, t) => a + (b - a) * t;
/* smooth 0→1 ramp across [a,b] */
const ramp  = (p, a, b) => { const t = clamp((p - a) / (b - a)); return t * t * (3 - 2 * t); };
/* fade in over [a,b], hold, fade out over [c,d] */
const window4 = (p, a, b, c, d) =>
  p < a || p > d ? 0 : p < b ? (p - a) / (b - a) : p > c ? 1 - (p - c) / (d - c) : 1;

/* ───────────────────────── preloader ─────────────────────────
   There are no frames to fetch, so the bar tracks the only real
   work there is — webfont loading — and refuses to finish early. */
const loaderEl   = document.getElementById('loader');
const loaderFill = document.getElementById('loaderFill');
const loaderPct  = document.getElementById('loaderPct');

(function boot() {
  const started = performance.now();
  const MIN_MS  = 1400;
  let fontsDone = false;

  const fonts = document.fonts ? document.fonts.ready : Promise.resolve();
  fonts.then(() => { fontsDone = true; });

  (function tick() {
    const elapsed = performance.now() - started;
    /* creeps to 92% on time alone; the last 8% needs the fonts */
    const byTime = clamp(elapsed / MIN_MS) * 0.92;
    const pct = fontsDone ? Math.max(byTime, clamp(elapsed / MIN_MS)) : byTime;
    loaderFill.style.width = (pct * 100).toFixed(1) + '%';
    loaderPct.textContent = String(Math.round(pct * 100)).padStart(2, '0');

    if (pct >= 1) {
      loaderEl.classList.add('done');
      document.body.classList.add('ready');
      resizeAll();
      setTimeout(() => { loaderEl.style.display = 'none'; }, 1100);
      return;
    }
    requestAnimationFrame(tick);
  })();
})();

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
/* progress of a tall section under its own sticky viewport */
function sectionProgress(el) {
  const r = el.getBoundingClientRect();
  const span = el.offsetHeight - window.innerHeight;
  return span <= 0 ? 0 : clamp(-r.top / span);
}

/* ═══════════════════════════════════════════════════════════
   THE EYE — one primitive, used by both acts
   aperture 0 = sealed, 1 = wide. gaze is normalised [-1,1].
   ═══════════════════════════════════════════════════════════ */
function drawEye(ctx, cx, cy, ew, aperture, gx, gy, glow, t) {
  const a = clamp(aperture);
  if (a <= 0.001) return;
  const eh = ew * 0.34 * a;          // lid opening scale
  const hw = ew / 2;

  /* Upper lid carries more curve than the lower one — that asymmetry is
     the whole difference between an eye and a lens flare. */
  const lidPath = () => {
    ctx.beginPath();
    ctx.moveTo(cx - hw, cy);
    ctx.bezierCurveTo(cx - hw * 0.45, cy - eh * 1.9, cx + hw * 0.45, cy - eh * 1.9, cx + hw, cy);
    ctx.bezierCurveTo(cx + hw * 0.45, cy + eh * 1.25, cx - hw * 0.45, cy + eh * 1.25, cx - hw, cy);
    ctx.closePath();
  };

  ctx.save();
  lidPath();

  /* glow spilling past the lids */
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  const spill = ctx.createRadialGradient(cx, cy, 0, cx, cy, ew * 1.5);
  spill.addColorStop(0, `rgba(127,212,255,${0.4 * glow})`);
  spill.addColorStop(0.35, `rgba(31,111,255,${0.18 * glow})`);
  spill.addColorStop(1, 'rgba(31,111,255,0)');
  ctx.fillStyle = spill;
  ctx.fillRect(cx - ew * 1.5, cy - ew * 1.5, ew * 3, ew * 3);
  ctx.restore();

  ctx.clip();

  /* sclera — never white; Gojo's eyes read as lit glass */
  const sclera = ctx.createLinearGradient(cx, cy - eh, cx, cy + eh);
  sclera.addColorStop(0, '#0c1830');
  sclera.addColorStop(0.5, '#16294d');
  sclera.addColorStop(1, '#070d1c');
  ctx.fillStyle = sclera;
  ctx.fillRect(cx - hw, cy - eh * 2.2, ew, eh * 4.4);

  /* iris follows the gaze, but only inside the lid box */
  const ir = ew * 0.29;
  const ix = cx + gx * hw * 0.30;
  const iy = cy + gy * eh * 0.55;

  const iris = ctx.createRadialGradient(ix - ir * 0.25, iy - ir * 0.3, ir * 0.05, ix, iy, ir);
  iris.addColorStop(0, '#dff3ff');
  iris.addColorStop(0.28, '#7fd4ff');
  iris.addColorStop(0.62, '#1f6fff');
  iris.addColorStop(1, '#061638');
  ctx.fillStyle = iris;
  ctx.beginPath(); ctx.arc(ix, iy, ir, 0, Math.PI * 2); ctx.fill();

  /* iris striations */
  ctx.save();
  ctx.beginPath(); ctx.arc(ix, iy, ir, 0, Math.PI * 2); ctx.clip();
  ctx.strokeStyle = 'rgba(8,26,70,.4)';
  ctx.lineWidth = Math.max(1, ir * 0.03);
  for (let i = 0; i < 34; i++) {
    const ang = (i / 34) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(ix + Math.cos(ang) * ir * 0.36, iy + Math.sin(ang) * ir * 0.36);
    ctx.lineTo(ix + Math.cos(ang) * ir, iy + Math.sin(ang) * ir);
    ctx.stroke();
  }
  ctx.restore();

  /* six marks around the ring — the Six Eyes, turning slowly */
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  for (let i = 0; i < 6; i++) {
    const ang = t * 0.00022 + (i / 6) * Math.PI * 2;
    const mx = ix + Math.cos(ang) * ir * 0.7;
    const my = iy + Math.sin(ang) * ir * 0.7;
    const g = ctx.createRadialGradient(mx, my, 0, mx, my, ir * 0.13);
    g.addColorStop(0, `rgba(223,243,255,${0.6 * glow})`);
    g.addColorStop(1, 'rgba(223,243,255,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(mx, my, ir * 0.13, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();

  /* pupil + rim */
  ctx.fillStyle = 'rgba(3,6,16,.94)';
  ctx.beginPath(); ctx.arc(ix, iy, ir * 0.34, 0, Math.PI * 2); ctx.fill();

  ctx.strokeStyle = `rgba(127,212,255,${0.55 + 0.4 * glow})`;
  ctx.lineWidth = Math.max(1, ew * 0.008);
  ctx.beginPath(); ctx.arc(ix, iy, ir, 0, Math.PI * 2); ctx.stroke();

  /* specular */
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  const sx = ix - ir * 0.42, sy = iy - ir * 0.46;
  const spec = ctx.createRadialGradient(sx, sy, 0, sx, sy, ir * 0.26);
  spec.addColorStop(0, 'rgba(255,255,255,.8)');
  spec.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = spec;
  ctx.beginPath(); ctx.arc(sx, sy, ir * 0.26, 0, Math.PI * 2); ctx.fill();
  ctx.restore();

  /* upper lid shadow so the eye sits in a face, not on a plate */
  const lidShade = ctx.createLinearGradient(cx, cy - eh * 2.1, cx, cy);
  lidShade.addColorStop(0, 'rgba(2,3,8,.9)');
  lidShade.addColorStop(1, 'rgba(2,3,8,0)');
  ctx.fillStyle = lidShade;
  ctx.fillRect(cx - hw, cy - eh * 2.2, ew, eh * 2.2);

  ctx.restore();

  /* lash line */
  ctx.save();
  ctx.strokeStyle = `rgba(150,190,240,${0.18 + 0.3 * glow})`;
  ctx.lineWidth = Math.max(1, ew * 0.012);
  ctx.beginPath();
  ctx.moveTo(cx - hw, cy);
  ctx.bezierCurveTo(cx - hw * 0.45, cy - eh * 1.9, cx + hw * 0.45, cy - eh * 1.9, cx + hw, cy);
  ctx.stroke();
  ctx.restore();
}

/* ═══════════════════════════════════════════════════════════
   ACT I — scroll-scrubbed unsealing
   0.00 blindfold   0.30 unwrapping   0.55 six eyes   0.80 limitless
   ═══════════════════════════════════════════════════════════ */
const scrubEl   = document.getElementById('scrub');
const mainCanvas = document.getElementById('mainCanvas');
const scrubGlow = document.getElementById('scrubGlow');
const titleblock = document.getElementById('titleblock');
const phaseEls  = [...document.querySelectorAll('.phase')];

/* the void field is generated once and reused, so the stars do not
   reshuffle on every resize */
const FIELD = Array.from({ length: 170 }, () => ({
  x: Math.random(), y: Math.random(),
  r: Math.random() * 1.6 + 0.3,
  s: Math.random() * 0.6 + 0.2,
  hue: Math.random()
}));

/* nine bandage ribbons, each with its own unwrap offset */
const RIBBONS = Array.from({ length: 9 }, (_, i) => ({
  off: i / 9,
  tilt: (Math.random() - 0.5) * 0.06,
  delay: (i % 3) * 0.045 + Math.random() * 0.02,
  dir: i % 2 ? 1 : -1
}));

function renderScrub(p, t) {
  const ctx = fitCanvas(mainCanvas);
  const W = mainCanvas.width, H = mainCanvas.height;
  const cx = W / 2, cy = H * 0.46;

  ctx.clearRect(0, 0, W, H);

  /* ── void backdrop ── */
  const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(W, H) * 0.8);
  bg.addColorStop(0, `rgba(${10 + 14 * p | 0},${12 + 20 * p | 0},${30 + 46 * p | 0},1)`);
  bg.addColorStop(1, '#030408');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  /* ── cursed energy field ── */
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  for (const s of FIELD) {
    const drift = REDUCED ? 0 : Math.sin(t * 0.0004 * s.s + s.hue * 9) * H * 0.012;
    const x = s.x * W, y = s.y * H + drift;
    const a = (0.1 + 0.5 * p) * (0.4 + 0.6 * s.s);
    ctx.fillStyle = s.hue > 0.7
      ? `rgba(207,139,255,${a})`
      : `rgba(127,212,255,${a})`;
    ctx.beginPath(); ctx.arc(x, y, s.r * (H / 900) * 2, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();

  /* ── the eyes underneath ── */
  /* narrow viewports get a proportionally larger pair, or the eyes read as
     two pinpricks in an ocean of void */
  const ew = Math.min(W * (mainCanvas.offsetWidth < 700 ? 0.33 : 0.20), H * 0.30);
  const gap = ew * 1.34;
  const aperture = ramp(p, 0.30, 0.60);
  const glow = ramp(p, 0.34, 0.72);
  const drift = REDUCED ? 0 : Math.sin(t * 0.0006) * 0.25;

  drawEye(ctx, cx - gap / 2, cy, ew, aperture, drift, Math.sin(t * 0.0004) * 0.12, glow, t);
  drawEye(ctx, cx + gap / 2, cy, ew, aperture, drift, Math.sin(t * 0.0004) * 0.12, glow, t);

  /* ── blindfold: ribbons peel off, staggered ── */
  const bandH = ew * 1.15;
  for (const rb of RIBBONS) {
    const local = clamp((p - 0.06 - rb.delay) / 0.20);
    if (local >= 1) continue;
    const slide = local * local * W * 0.85 * rb.dir;
    const y = cy - bandH / 2 + rb.off * bandH;
    const h = bandH / 9 + 1;

    ctx.save();
    ctx.globalAlpha = 1 - local * 0.85;
    ctx.translate(slide, 0);
    ctx.rotate(rb.tilt * local);

    const band = ctx.createLinearGradient(0, y, 0, y + h);
    band.addColorStop(0, '#1b1f2c');
    band.addColorStop(0.5, '#0d1018');
    band.addColorStop(1, '#05070c');
    ctx.fillStyle = band;
    ctx.fillRect(-W * 0.3, y, W * 1.6, h);

    ctx.strokeStyle = 'rgba(160,180,215,.14)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(-W * 0.3, y + 0.5); ctx.lineTo(W * 1.3, y + 0.5); ctx.stroke();
    ctx.restore();
  }

  /* ── LIMITLESS: rings that converge and never arrive ── */
  const inf = ramp(p, 0.70, 0.92);
  if (inf > 0.01) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const base = Math.min(W, H) * 0.42;
    for (let i = 0; i < 14; i++) {
      /* each ring is half the distance of the last — a geometric series
         collapsing on the centre */
      const k = Math.pow(0.82, i);
      const phase = REDUCED ? 0 : (t * 0.00012) % 1;
      const r = base * k * (1 - phase * 0.18);
      ctx.strokeStyle = `rgba(127,212,255,${0.30 * inf * k})`;
      ctx.lineWidth = Math.max(1, (W / 1400) * (1 + 3 * k));
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.restore();
  }

  /* ── HOLLOW PURPLE: blue and red close, then annihilate ── */
  const hp = ramp(p, 0.84, 1.0);
  if (hp > 0.01) {
    const sep = lerp(Math.min(W, H) * 0.26, 0, ramp(p, 0.84, 0.965));
    const orbR = Math.min(W, H) * 0.075 * (0.7 + 0.5 * hp);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';

    const orb = (x, col) => {
      const g = ctx.createRadialGradient(x, cy, 0, x, cy, orbR);
      g.addColorStop(0, 'rgba(255,255,255,.95)');
      g.addColorStop(0.3, col);
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(x, cy, orbR, 0, Math.PI * 2); ctx.fill();
    };
    orb(cx - sep, 'rgba(31,111,255,.95)');
    orb(cx + sep, 'rgba(255,47,74,.95)');

    /* the collision writes a purple line through everything */
    const merge = ramp(p, 0.94, 1.0);
    if (merge > 0.01) {
      const beamH = orbR * (0.35 + 1.5 * merge);
      const beam = ctx.createLinearGradient(0, cy - beamH, 0, cy + beamH);
      beam.addColorStop(0, 'rgba(139,61,255,0)');
      beam.addColorStop(0.42, `rgba(139,61,255,${0.5 * merge})`);
      beam.addColorStop(0.5, `rgba(238,225,255,${0.8 * merge})`);
      beam.addColorStop(0.58, `rgba(139,61,255,${0.5 * merge})`);
      beam.addColorStop(1, 'rgba(139,61,255,0)');
      ctx.fillStyle = beam;
      ctx.fillRect(0, cy - beamH, W, beamH * 2);

      /* the halo stays a halo — it must not eat the caption under it */
      const halo = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.min(W, H) * 0.42);
      halo.addColorStop(0, `rgba(139,61,255,${0.26 * merge})`);
      halo.addColorStop(0.55, `rgba(139,61,255,${0.08 * merge})`);
      halo.addColorStop(1, 'rgba(139,61,255,0)');
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, W, H);
    }
    ctx.restore();
  }

  /* ── captions ── */
  scrubGlow.style.opacity = (glow * 0.8).toFixed(3);
  titleblock.style.opacity = window4(p, -1, 0, 0.05, 0.16).toFixed(3);

  phaseEls[0].style.opacity = window4(p, -1, 0.02, 0.14, 0.22).toFixed(3);
  phaseEls[1].style.opacity = window4(p, 0.22, 0.28, 0.40, 0.47).toFixed(3);
  phaseEls[2].style.opacity = window4(p, 0.49, 0.55, 0.66, 0.73).toFixed(3);
  phaseEls[3].style.opacity = window4(p, 0.75, 0.81, 0.95, 1.01).toFixed(3);
}

/* ─────────── cursed energy motes over Act I ─────────── */
const moteCanvas = document.getElementById('moteCanvas');
const MOTES = Array.from({ length: 60 }, () => ({
  x: Math.random(), y: Math.random(),
  vx: (Math.random() - 0.5) * 0.00012,
  vy: -Math.random() * 0.00018 - 0.00004,
  r: Math.random() * 2.4 + 0.6,
  a: Math.random() * 0.5 + 0.2,
  hot: Math.random() > 0.72
}));

function renderMotes(p, dt) {
  const ctx = fitCanvas(moteCanvas);
  const W = moteCanvas.width, H = moteCanvas.height;
  ctx.clearRect(0, 0, W, H);
  if (REDUCED) return;

  ctx.globalCompositeOperation = 'lighter';
  for (const m of MOTES) {
    m.x += m.vx * dt; m.y += m.vy * dt;
    if (m.y < -0.05) { m.y = 1.05; m.x = Math.random(); }
    if (m.x < -0.05) m.x = 1.05; else if (m.x > 1.05) m.x = -0.05;

    const x = m.x * W, y = m.y * H;
    const rad = m.r * (H / 900) * 6;
    const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
    const alpha = m.a * (0.25 + 0.75 * p);
    g.addColorStop(0, m.hot ? `rgba(207,139,255,${alpha})` : `rgba(127,212,255,${alpha})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
  }
}

/* ═══════════════════════════════════════════════════════════
   ACT II — the Six Eyes track the pointer
   ═══════════════════════════════════════════════════════════ */
const eyesEl    = document.getElementById('eyes');
const eyeCanvas = document.getElementById('eyeCanvas');
const eyeFlare  = document.getElementById('eyeFlare');
const eyeReadout = document.getElementById('eyeReadout');

const pointer = { x: 0.5, y: 0.5, sx: 0.5, sy: 0.5 };

function renderEyes(p, t) {
  const ctx = fitCanvas(eyeCanvas);
  const W = eyeCanvas.width, H = eyeCanvas.height;
  const cx = W / 2, cy = H * 0.42;

  ctx.clearRect(0, 0, W, H);
  const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(W, H) * 0.75);
  bg.addColorStop(0, '#0a1226');
  bg.addColorStop(1, '#000');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  /* the eyes open as the section takes the viewport, and never close */
  const aperture = ramp(p, 0.02, 0.26);

  /* gaze: the pointer, eased. On touch the eyes sweep on their own. */
  let gx, gy;
  if (COARSE) {
    gx = Math.sin(t * 0.0005) * 0.9;
    gy = Math.sin(t * 0.00031) * 0.5;
  } else {
    pointer.sx = lerp(pointer.sx, pointer.x, 0.12);
    pointer.sy = lerp(pointer.sy, pointer.y, 0.12);
    gx = clamp((pointer.sx - 0.5) * 2.4, -1, 1);
    gy = clamp((pointer.sy - 0.45) * 2.4, -1, 1);
  }

  const ew = Math.min(W * 0.28, H * 0.46);
  const gap = ew * 1.3;
  drawEye(ctx, cx - gap / 2, cy, ew, aperture, gx, gy, aperture, t);
  drawEye(ctx, cx + gap / 2, cy, ew, aperture, gx, gy, aperture, t);

  eyeFlare.style.opacity = (aperture * (0.5 + 0.5 * Math.abs(gx))).toFixed(3);

  const fmt = v => (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1).padStart(4, '0');
  eyeReadout.textContent =
    `視線 ${fmt(gx)} / ${fmt(gy)} · 呪力 ${String(Math.round(320 + 180 * Math.abs(gx))).padStart(3, '0')}`;
}

if (!COARSE) {
  window.addEventListener('pointermove', e => {
    pointer.x = e.clientX / window.innerWidth;
    pointer.y = e.clientY / window.innerHeight;
  }, { passive: true });
}

/* ═══════════════════════════════════════════════════════════
   CURSED ENERGY HEM — 呪力 licking the bottom of the viewport
   ═══════════════════════════════════════════════════════════ */
const hemCanvas = document.getElementById('hemCanvas');
const HEM = Array.from({ length: REDUCED ? 0 : 48 }, () => ({
  x: Math.random(), y: Math.random(),
  vy: -(Math.random() * 0.0006 + 0.0003),
  r: Math.random() * 0.5 + 0.35,
  seed: Math.random() * 100,
  hot: Math.random() > 0.6
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
    const wob = Math.sin(t * 0.002 + f.seed) * 0.012;
    const x = (f.x + wob) * W, y = f.y * H;
    const rad = f.r * H * 0.9;
    const fade = clamp(1 - Math.abs(f.y - 0.6) * 1.1);
    const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
    g.addColorStop(0, f.hot ? `rgba(139,61,255,${0.32 * fade})` : `rgba(31,111,255,${0.26 * fade})`);
    g.addColorStop(0.5, `rgba(80,40,180,${0.12 * fade})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
  }
}

/* ═══════════════════════════════════════════════════════════
   DISCHARGE — the air around him does not behave
   ═══════════════════════════════════════════════════════════ */
const stormFlash = document.getElementById('stormFlash');
const boltPath   = document.getElementById('boltPath');
const boltGlow   = document.getElementById('boltGlow');
const boltSvg    = document.getElementById('stormBolt');

function boltD() {
  const x0 = 150 + Math.random() * 700;
  let x = x0, y = 0;
  let d = `M${x.toFixed(1)} 0`;
  while (y < 1000) {
    y += 60 + Math.random() * 90;
    x += (Math.random() - 0.5) * 190;
    d += ` L${clamp(x, 20, 980).toFixed(1)} ${Math.min(y, 1000).toFixed(1)}`;
    /* a fork, sometimes */
    if (Math.random() > 0.72 && y < 700) {
      const fx = x + (Math.random() - 0.5) * 300;
      const fy = y + 120 + Math.random() * 160;
      d += ` M${clamp(x, 20, 980).toFixed(1)} ${y.toFixed(1)} L${clamp(fx, 20, 980).toFixed(1)} ${fy.toFixed(1)} M${clamp(x, 20, 980).toFixed(1)} ${y.toFixed(1)}`;
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

/* ═══════════════════════════════════════════════════════════
   INFINITY CURSOR — converges on the pointer, never lands
   ═══════════════════════════════════════════════════════════ */
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
  const dist = Math.hypot(dx, dy);
  /* the gain falls off as the gap closes — halve the distance, halve the
     speed, forever. It arrives only in the limit. */
  const gain = 0.02 + 0.14 * clamp(dist / 260);
  cur.x += dx * gain;
  cur.y += dy * gain;
  cursorEl.style.transform = `translate(${cur.x.toFixed(1)}px, ${cur.y.toFixed(1)}px)`;
}

/* ═══════════════════════════════════════════════════════════
   GHOST TRAIL — cursed energy smeared across Act III
   ═══════════════════════════════════════════════════════════ */
const ghostCanvas = document.getElementById('ghostCanvas');
const jutsuEl     = document.getElementById('jutsu');
const TRAIL = [];
const TRAIL_MAX = 34;

if (!COARSE && !REDUCED) {
  jutsuEl.addEventListener('pointermove', e => {
    const r = ghostCanvas.getBoundingClientRect();
    TRAIL.push({ x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, born: performance.now() });
    if (TRAIL.length > TRAIL_MAX) TRAIL.shift();
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
    const life = 1 - age;
    const rad = W * (0.035 + 0.09 * age);
    const x = pt.x * W, y = pt.y * H;
    const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
    const head = i / TRAIL.length;
    g.addColorStop(0, `rgba(207,139,255,${0.16 * life * (0.35 + head)})`);
    g.addColorStop(0.4, `rgba(80,110,255,${0.09 * life * (0.35 + head)})`);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
  }
  while (TRAIL.length && now - TRAIL[0].born > 1500) TRAIL.shift();
}

/* ═══════════════════════════════════════════════════════════
   AUDIO — synthesised, so the page still ships no binaries
   ═══════════════════════════════════════════════════════════ */
const audio = {
  on: false, ctx: null, gain: null, nodes: [],

  init() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    this.ctx = new AC();
    this.gain = this.ctx.createGain();
    this.gain.gain.value = 0;
    this.gain.connect(this.ctx.destination);

    const filter = this.ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = 320;
    filter.Q.value = 6;
    filter.connect(this.gain);

    /* two detuned saws under a low-pass — a room that is about to be
       a domain expansion */
    [55, 82.5].forEach((f, i) => {
      const o = this.ctx.createOscillator();
      o.type = i ? 'triangle' : 'sawtooth';
      o.frequency.value = f;
      const g = this.ctx.createGain();
      g.gain.value = i ? 0.18 : 0.1;
      o.connect(g); g.connect(filter);
      o.start();
      this.nodes.push(o);
    });

    /* slow wobble on the cutoff */
    const lfo = this.ctx.createOscillator();
    lfo.frequency.value = 0.07;
    const lfoGain = this.ctx.createGain();
    lfoGain.gain.value = 140;
    lfo.connect(lfoGain); lfoGain.connect(filter.frequency);
    lfo.start();
    this.nodes.push(lfo);
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
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    const bp = this.ctx.createBiquadFilter();
    bp.type = 'bandpass'; bp.frequency.value = 420; bp.Q.value = 0.8;
    const g = this.ctx.createGain(); g.gain.value = 0.22;
    src.connect(bp); bp.connect(g); g.connect(this.gain);
    src.start();
  }
};

const soundToggle = document.getElementById('soundToggle');
const soundState  = document.getElementById('soundState');
soundToggle.addEventListener('click', () => {
  const on = audio.toggle();
  soundToggle.setAttribute('aria-pressed', String(!!on));
  soundState.textContent = on ? 'ON' : 'OFF';
});

/* ═══════════════════════════════════════════════════════════
   CHROME — rail readout, hint, sticky badge, section lighting
   ═══════════════════════════════════════════════════════════ */
const railScroll  = document.getElementById('railScroll');
const hintEl      = document.getElementById('hint');
const stickyBadge = document.getElementById('stickyBadge');

const io = new IntersectionObserver(entries => {
  for (const e of entries) if (e.isIntersecting) {
    e.target.classList.add('in');
    io.unobserve(e.target);
  }
}, { threshold: 0.18 });
document.querySelectorAll('[data-px], .card').forEach(el => io.observe(el));

const litIo = new IntersectionObserver(entries => {
  for (const e of entries) jutsuEl.classList.toggle('lit', e.isIntersecting);
}, { threshold: 0.12 });
litIo.observe(jutsuEl);

/* ═══════════════════════════════════════════════════════════
   MAIN LOOP
   ═══════════════════════════════════════════════════════════ */
let last = performance.now();

function resizeAll() {
  [mainCanvas, moteCanvas, eyeCanvas, hemCanvas, ghostCanvas].forEach(c => { if (needsResize(c)) fitCanvas(c); });
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

  /* only paint a canvas whose section is anywhere near the viewport */
  const nearScrub = scrubEl.getBoundingClientRect().bottom > -200 &&
                    scrubEl.getBoundingClientRect().top < window.innerHeight + 200;
  if (nearScrub) {
    const p = sectionProgress(scrubEl);
    renderScrub(p, now);
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
requestAnimationFrame(frame);
