// =====================================================================
// Движок таймлайна: выбирает сцену по времени, делает переходы,
// «пинки» камеры на битах, цветовой грейд и субтитры.
// Ожидает глобальные TIMELINE (из build/timeline.json) и SCENES.
// =====================================================================
const SCENES = {};
let canvas, ctx, buf, bctx, SCALE = 1;

function setup(w, h) {
  canvas = document.getElementById('c'); canvas.width = w; canvas.height = h;
  ctx = canvas.getContext('2d');
  buf = document.createElement('canvas'); buf.width = w; buf.height = h; bctx = buf.getContext('2d');
  SCALE = w / W;
}

function makeEnv(sc) {
  const toLocal = x => x - sc.start;
  const words = sc.words.map(w => ({ text: w.text, start: toLocal(w.start), end: toLocal(w.end) }));
  const beats = sc.beats.map(toLocal);
  const norm = s => s.toLowerCase().replace(/ё/g, 'е').replace(/[^a-zа-я0-9]/g, '');
  return {
    dur: sc.dur, words, beats, id: sc.id,
    // время начала слова (локальное). key: 'слово' или 'слово#2'
    w(key) { const [n, k] = key.split('#'); let c = 0;
      for (const x of words) if (norm(x.text) === norm(n) || x.text.split(' ').some(p => norm(p) === norm(n))) { c++; if (c === (+k || 1)) return x.start; }
      console.warn('no word', key); return 0; },
    beat(t) { let i = 0; while (i + 1 < beats.length && t >= beats[i + 1]) i++;
      const end = i + 1 < beats.length ? beats[i + 1] : sc.dur; return { i, lt: t - beats[i], bd: end - beats[i] }; },
    gp: t => clamp((sc.start + t) / TIMELINE.total),   // глобальный прогресс 0..1
  };
}

function drawScene(c, i, t) {
  const sc = TIMELINE.scenes[i], mod = SCENES[sc.id];
  const env = sc._env || (sc._env = makeEnv(sc));
  c.save();
  c.setTransform(SCALE, 0, 0, SCALE, 0, 0);
  // пинок камеры на каждом бите внутри сцены (кроме самого начала)
  let kick = 0, flash = 0;
  for (let b = 1; b < env.beats.length; b++) { const d = t - env.beats[b];
    if (d >= 0 && d < .45) { kick = (1 - E.out(d / .45)) * .1; flash = Math.max(flash, 1 - d / .12); } }
  if (kick) { c.translate(W / 2, H / 2); c.scale(1 + kick, 1 + kick); c.translate(-W / 2, -H / 2); }
  mod.render(c, t, env);
  // грейд палитры (multiply) + виньетка
  const p = env.gp(t), pal = PAL(p);
  c.setTransform(SCALE, 0, 0, SCALE, 0, 0);
  c.globalCompositeOperation = 'multiply'; c.fillStyle = pal.grade; c.fillRect(0, 0, W, H);
  c.globalCompositeOperation = 'source-over';
  const vg = c.createRadialGradient(W / 2, H / 2, H * .3, W / 2, H / 2, H * .75);
  vg.addColorStop(0, 'rgba(10,5,30,0)'); vg.addColorStop(1, `rgba(10,5,30,${.3 + .2 * p})`);
  c.fillStyle = vg; c.fillRect(0, 0, W, H);
  if (mod.top) mod.top(c, t, env);  // слой поверх грейда (например, яркий Лучик)
  if (flash > 0) { c.fillStyle = `rgba(255,255,255,${flash * .35})`; c.fillRect(0, 0, W, H); }
  c.restore();
}

const TR = .32; // длительность перехода между сценами
function renderFrame(T) {
  const S = TIMELINE.scenes;
  let i = S.length - 1; while (i > 0 && T < S[i].start) i--;
  const t = T - S[i].start;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, canvas.width, canvas.height);
  // новая сцена «въезжает» с лёгким зумом
  const k = i > 0 ? P(t, 0, TR + .25, E.out) : 1;
  ctx.save();
  if (k < 1) { const s = lerp(1.18, 1, k); ctx.translate(canvas.width / 2, canvas.height / 2); ctx.rotate((1 - k) * .04); ctx.scale(s, s); ctx.translate(-canvas.width / 2, -canvas.height / 2); }
  drawScene(ctx, i, t);
  ctx.restore();
  // старая сцена улетает в зум и растворяется
  if (i > 0 && t < TR) {
    const kk = E.inOut(t / TR);
    bctx.setTransform(1, 0, 0, 1, 0, 0); bctx.clearRect(0, 0, buf.width, buf.height);
    drawScene(bctx, i - 1, S[i - 1].dur + t);
    ctx.save(); ctx.globalAlpha = 1 - kk;
    const s = 1 + kk * .5; ctx.translate(canvas.width / 2, canvas.height / 2); ctx.scale(s, s); ctx.rotate(-kk * .06);
    ctx.drawImage(buf, -canvas.width / 2, -canvas.height / 2); ctx.restore();
  }
  ctx.save(); ctx.setTransform(SCALE, 0, 0, SCALE, 0, 0); subtitles(ctx, T); ctx.restore();
}

// ---------- субтитры: 2-4 слова, текущее подсвечено ----------
const SUB_Y = 1470, SUB_SIZE = 92, SUB_MAXW = 940;
function subtitles(c, T) {
  const g = TIMELINE.subtitles.find(g => T >= g.start && T < g.end);
  if (!g) return;
  const ws = g.words.map(w => ({ ...w, s: w.text.toUpperCase() }));
  let size = SUB_SIZE;
  c.font = `900 ${size}px Rubik`;
  const space = size * .42;
  const width = arr => arr.reduce((a, w) => a + c.measureText(w.s).width, 0) + space * (arr.length - 1);
  // разбиваем на 1-2 строки
  let lines = [ws];
  if (width(ws) > SUB_MAXW && ws.length > 1) {
    let best = 1, bestD = 1e9;
    for (let k = 1; k < ws.length; k++) { const d = Math.abs(width(ws.slice(0, k)) - width(ws.slice(k))); if (d < bestD) { bestD = d; best = k; } }
    lines = [ws.slice(0, best), ws.slice(best)];
  }
  const maxw = Math.max(...lines.map(width));
  if (maxw > SUB_MAXW) size *= SUB_MAXW / maxw;
  const pop = E.back(clamp((T - g.start) / .18));
  c.save(); c.translate(W / 2, SUB_Y); c.scale(lerp(.6, 1, pop), lerp(.6, 1, pop)); c.globalAlpha = clamp(pop * 1.5);
  c.font = `900 ${size}px Rubik`; c.textBaseline = 'middle'; c.textAlign = 'left'; c.lineJoin = 'round';
  const lh = size * 1.18, sp = size * .42;
  lines.forEach((ln, li) => {
    const lw = ln.reduce((a, w) => a + c.measureText(w.s).width, 0) + sp * (ln.length - 1);
    let x = -lw / 2; const y = (li - (lines.length - 1) / 2) * lh;
    ln.forEach(w => {
      const ww = c.measureText(w.s).width;
      const active = T >= w.start - .03 && T < w.end + .05;
      const ka = active ? E.back(clamp((T - w.start + .03) / .14)) : 0;
      c.save(); c.translate(x + ww / 2, y); const s = 1 + .08 * ka; c.scale(s, s); c.rotate(active ? -.03 : 0);
      c.lineWidth = size * .2; c.strokeStyle = INK;
      c.fillStyle = 'rgba(15,8,35,.55)'; c.fillText(w.s, -ww / 2 + 5, 8);   // мягкая тень
      c.strokeText(w.s, -ww / 2, 0);
      c.fillStyle = active ? '#ffd23f' : (T > w.end ? '#ffffff' : '#f3eefe');
      c.fillText(w.s, -ww / 2, 0);
      c.restore();
      x += ww + sp;
    });
  });
  c.restore();
}
