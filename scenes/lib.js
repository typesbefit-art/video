// =====================================================================
// Общая библиотека: easing, палитра, камера, примитивы с жирным контуром,
// персонажи. Все координаты — в «логических» единицах 1080x1920.
// =====================================================================
const W = 1080, H = 1920;
const INK = '#1b1230';
const OUT = 10;            // толщина контура по умолчанию

// ---------- математика / easing ----------
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, t) => a + (b - a) * t;
const inv = (a, b, x) => clamp((x - a) / (b - a));
const E = {
  lin: t => t,
  in: t => t * t * t,
  out: t => 1 - Math.pow(1 - t, 3),
  inOut: t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2,
  sine: t => -(Math.cos(Math.PI * t) - 1) / 2,
  back: t => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
  elastic: t => t === 0 ? 0 : t === 1 ? 1 : Math.pow(2, -10 * t) * Math.sin((t * 10 - .75) * (2 * Math.PI) / 3) + 1,
  expo: t => t === 1 ? 1 : 1 - Math.pow(2, -10 * t),
};
// прогресс анимации от t0 длительностью d с easing
const P = (t, t0, d, ease = E.inOut) => ease(clamp((t - t0) / d));

function rng(seed) { // mulberry32
  let a = seed >>> 0;
  return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
// плавный «шум» для тряски
const wob = (t, s = 1) => Math.sin(t * 13.1 * s) * .5 + Math.sin(t * 27.3 * s + 1.3) * .3 + Math.sin(t * 51.7 * s + 2.1) * .2;

// ---------- цвет ----------
function hex(c) { c = c.replace('#', ''); if (c.length === 3) c = c.split('').map(x => x + x).join('');
  return [parseInt(c.slice(0, 2), 16), parseInt(c.slice(2, 4), 16), parseInt(c.slice(4, 6), 16)]; }
function mix(c1, c2, t) { const a = hex(c1), b = hex(c2);
  return '#' + a.map((v, i) => Math.round(lerp(v, b[i], clamp(t))).toString(16).padStart(2, '0')).join(''); }
function mixN(stops, t) { // stops: [[pos,color],...]
  t = clamp(t);
  for (let i = 1; i < stops.length; i++) if (t <= stops[i][0])
    return mix(stops[i - 1][1], stops[i][1], (t - stops[i - 1][0]) / (stops[i][0] - stops[i - 1][0]));
  return stops[stops.length - 1][1];
}
const grey = (c, k) => { const [r, g, b] = hex(c); const l = Math.round(r * .3 + g * .59 + b * .11);
  const gc = '#' + [l, l, l].map(v => v.toString(16).padStart(2, '0')).join(''); return mix(c, gc, k); };
function rgba(c, a) { const [r, g, b] = hex(c); return `rgba(${r},${g},${b},${a})`; }

// Глобальная палитра: p = 0 (начало видео, тепло) → 1 (конец, холод/почти чёрный)
const PAL = p => ({
  skyTop: mixN([[0, '#ffb84d'], [.22, '#ff8a3d'], [.4, '#5b7fd6'], [.62, '#27357a'], [.82, '#1a1450'], [1, '#0d0820']], p),
  skyBot: mixN([[0, '#fff1a8'], [.22, '#ffc56b'], [.4, '#9fb8f0'], [.62, '#4a5aa8'], [.82, '#2e2470'], [1, '#160d33']], p),
  ground: mixN([[0, '#7ccf5a'], [.25, '#8fbf55'], [.4, '#8aa0b8'], [.62, '#c8d6ee'], [1, '#2a2350']], p),
  accent: mixN([[0, '#ff6b35'], [.3, '#ff7f50'], [.5, '#4fc3f7'], [.75, '#7e57c2'], [1, '#5e35b1']], p),
  // цвет «грейда» поверх кадра (multiply)
  grade: mixN([[0, '#fff6e6'], [.25, '#ffe9d2'], [.45, '#e0e7ff'], [.65, '#c3c8f5'], [.85, '#aea4e6'], [1, '#a294da']], p),
});

// ---------- примитивы ----------
function paint(ctx, fill, lw = OUT, stroke = INK) {
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (lw > 0) { ctx.lineWidth = lw; ctx.strokeStyle = stroke; ctx.lineJoin = 'round'; ctx.lineCap = 'round'; ctx.stroke(); }
}
function circle(ctx, x, y, r, fill, lw = OUT) { ctx.beginPath(); ctx.arc(x, y, Math.max(0.01, r), 0, Math.PI * 2); paint(ctx, fill, lw); }
function ellipse(ctx, x, y, rx, ry, fill, lw = OUT, rot = 0) { ctx.beginPath(); ctx.ellipse(x, y, Math.max(.01, rx), Math.max(.01, ry), rot, 0, Math.PI * 2); paint(ctx, fill, lw); }
function rrect(ctx, x, y, w, h, r, fill, lw = OUT) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); paint(ctx, fill, lw); }
function poly(ctx, pts, fill, lw = OUT, close = true) {
  ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
  if (close) ctx.closePath(); paint(ctx, close ? fill : null, lw);
}
function line(ctx, x1, y1, x2, y2, lw = OUT, color = INK) {
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.lineWidth = lw; ctx.strokeStyle = color; ctx.lineCap = 'round'; ctx.stroke();
}
function curve(ctx, pts, lw = OUT, color = INK) { // сглаженная ломаная
  ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length - 1; i++) { const xc = (pts[i][0] + pts[i + 1][0]) / 2, yc = (pts[i][1] + pts[i + 1][1]) / 2; ctx.quadraticCurveTo(pts[i][0], pts[i][1], xc, yc); }
  const l = pts[pts.length - 1]; ctx.lineTo(l[0], l[1]);
  ctx.lineWidth = lw; ctx.strokeStyle = color; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke();
}
function blob(ctx, x, y, r, t, k = .08, n = 7, fill, lw = OUT, seed = 1) { // «живая» клякса
  ctx.beginPath();
  for (let i = 0; i <= 64; i++) { const a = i / 64 * Math.PI * 2;
    const rr = r * (1 + k * Math.sin(a * n + t * 3 + seed) + k * .5 * Math.sin(a * 3 - t * 2 + seed * 2));
    const px = x + Math.cos(a) * rr, py = y + Math.sin(a) * rr; i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }
  ctx.closePath(); paint(ctx, fill, lw);
}
function glow(ctx, x, y, r, color, a = 1) {
  const g = ctx.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0, rgba(color, a)); g.addColorStop(1, rgba(color, 0));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
}
function sky(ctx, top, bot, y0 = 0, y1 = H) {
  const g = ctx.createLinearGradient(0, y0, 0, y1); g.addColorStop(0, top); g.addColorStop(1, bot);
  ctx.fillStyle = g; ctx.fillRect(-W, -H, W * 3, H * 3);
}
function text(ctx, s, x, y, size, fill = '#fff', lw = 14, weight = 900, align = 'center') {
  ctx.font = `${weight} ${size}px Rubik`; ctx.textAlign = align; ctx.textBaseline = 'middle';
  ctx.lineJoin = 'round'; ctx.miterLimit = 2;
  if (lw) { ctx.lineWidth = lw; ctx.strokeStyle = INK; ctx.strokeText(s, x, y); }
  ctx.fillStyle = fill; ctx.fillText(s, x, y);
}
function withT(ctx, x, y, s, rot, fn) { // локальная трансформация
  ctx.save(); ctx.translate(x, y); if (rot) ctx.rotate(rot); if (s !== 1) ctx.scale(s, s); fn(); ctx.restore();
}
function stars(ctx, t, n = 120, seed = 7, alpha = 1) {
  const r = rng(seed);
  for (let i = 0; i < n; i++) { const x = r() * W * 1.4 - W * .2, y = r() * H * 1.4 - H * .2, s = 2 + r() * 5, ph = r() * 6;
    ctx.globalAlpha = alpha * (.4 + .6 * (0.5 + 0.5 * Math.sin(t * 2.5 + ph)));
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(x, y, s, 0, 7); ctx.fill(); }
  ctx.globalAlpha = 1;
}
// облачко-«пуф» (частицы дыма)
function puff(ctx, x, y, k, size = 160, color = '#ffffff', seed = 3) {
  if (k <= 0 || k >= 1) return;
  const r = rng(seed); ctx.save(); ctx.globalAlpha = 1 - E.in(k);
  for (let i = 0; i < 9; i++) { const a = r() * 7, d = size * (0.3 + E.out(k) * (0.8 + r() * .6));
    circle(ctx, x + Math.cos(a) * d, y + Math.sin(a) * d, size * (0.35 + 0.25 * r()) * (1 - k * .5), color, 8); }
  ctx.restore();
}
// разлетающиеся «звёздочки-искры» (хлопок)
function burst(ctx, x, y, k, size = 200, color = '#ffd23f', n = 10) {
  if (k <= 0 || k >= 1) return;
  ctx.save(); ctx.globalAlpha = 1 - E.in(k);
  for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2, d1 = size * E.out(k), d2 = d1 + size * .35 * (1 - k);
    line(ctx, x + Math.cos(a) * d1, y + Math.sin(a) * d1, x + Math.cos(a) * d2, y + Math.sin(a) * d2, 14, color); }
  ctx.restore();
}

// ---------- лица ----------
// моргание: 0 = открыт, 1 = закрыт
function blinkAt(t, seed = 0, period = 3.1) {
  const ph = ((t + seed * 1.37) % period + period) % period;
  return ph < .16 ? Math.sin(ph / .16 * Math.PI) : 0;
}
function eye(ctx, x, y, r, o = {}) {
  const close = clamp(o.blink || 0), look = o.look || [0, 0];
  if (o.wink) { // подмигивание: глаз-дужка ^
    ctx.beginPath(); ctx.arc(x, y + r * .35, r * .75, Math.PI * 1.15, Math.PI * 1.85); ctx.lineWidth = r * .32; ctx.strokeStyle = INK; ctx.lineCap = 'round'; ctx.stroke(); return;
  }
  if (close > .9) { line(ctx, x - r * .8, y, x + r * .8, y, r * .28); return; }
  ctx.save(); ctx.translate(x, y); ctx.scale(1, 1 - close);
  circle(ctx, 0, 0, r, '#fff', Math.max(5, r * .16));
  circle(ctx, look[0] * r * .35, look[1] * r * .35, r * .55, INK, 0);
  circle(ctx, look[0] * r * .35 + r * .2, look[1] * r * .35 - r * .22, r * .18, '#fff', 0);
  ctx.restore();
  if (o.sad) { line(ctx, x - r, y - r * 1.25 - (o.side || 1) * r * .25, x + r, y - r * 1.25 + (o.side || 1) * r * .25, r * .25); }
}
function mouth(ctx, x, y, w, mood = 1, open = 0) { // mood: 1 улыбка, 0 ровно, -1 грусть
  if (open > .05) { ellipse(ctx, x, y, w * .45, w * .35 * open + 4, '#7a1f2b', Math.max(5, w * .12)); return; }
  ctx.beginPath(); ctx.moveTo(x - w / 2, y); ctx.quadraticCurveTo(x, y + mood * w * .55, x + w / 2, y);
  ctx.lineWidth = Math.max(5, w * .14); ctx.strokeStyle = INK; ctx.lineCap = 'round'; ctx.stroke();
}

// ---------- персонажи ----------
// Маскот «Лучик»
function luchik(ctx, x, y, r, t, o = {}) {
  const rays = o.rays ?? 1, sq = o.squash ?? 0;
  if (o.glow !== 0) glow(ctx, x, y, r * 3.2, '#ffd23f', .55 * (o.glow ?? 1));
  ctx.save(); ctx.translate(x, y); ctx.scale(1 + sq, 1 - sq);
  // лучи
  const n = 10;
  for (let i = 0; i < n; i++) { const a = i / n * Math.PI * 2 + t * .6;
    const l = r * (1.32 + .1 * Math.sin(t * 5 + i)) * rays;
    ctx.save(); ctx.rotate(a);
    poly(ctx, [[r * .82, -r * .2], [l + r * .1, 0], [r * .82, r * .2]], '#ff9f1c', 8);
    ctx.restore(); }
  circle(ctx, 0, 0, r, '#ffd23f', 12);
  // блик
  ctx.beginPath(); ctx.arc(-r * .35, -r * .4, r * .22, 0, 7); ctx.fillStyle = 'rgba(255,255,255,.55)'; ctx.fill();
  // щёчки
  circle(ctx, -r * .55, r * .25, r * .14, '#ff8fa3', 0); circle(ctx, r * .55, r * .25, r * .14, '#ff8fa3', 0);
  const bl = blinkAt(t, 2, 2.7);
  eye(ctx, -r * .32, -r * .1, r * .24, { blink: bl, look: o.look });
  eye(ctx, r * .32, -r * .1, r * .24, { blink: o.wink ? 0 : bl, wink: o.wink, look: o.look });
  mouth(ctx, 0, r * .35, r * .45, o.mood ?? 1, o.open ?? 0);
  ctx.restore();
}

// Человечек. o: {shirt, skin, hair, walk (фаза), cold 0..1, mood, scarf, look}
function person(ctx, x, y, s, t, o = {}) {
  const shirt = o.shirt || '#4f8cff', skin = o.skin || '#ffcf9e', pants = o.pants || '#3b3355';
  const ph = o.walk ?? null, shiver = (o.cold || 0) * wob(t * 2.2, 2.5) * 4;
  const bob = ph === null ? 0 : Math.abs(Math.sin(ph)) * -10;
  ctx.save(); ctx.translate(x + shiver, y + bob); ctx.scale(s, s);
  // ноги
  const lA = ph === null ? 0 : Math.sin(ph) * .5, lB = -lA;
  [[lA, -20], [lB, 20]].forEach(([a, dx]) => {
    ctx.save(); ctx.translate(dx, -90); ctx.rotate(a); line(ctx, 0, 0, 0, 85, 26, INK); line(ctx, 0, 0, 0, 82, 14, pants);
    ellipse(ctx, 8, 88, 18, 10, INK, 0); ctx.restore(); });
  // руки
  const aA = ph === null ? (o.cold ? -.9 : .15) : -Math.sin(ph) * .6;
  [[aA, -48, 1], [ph === null ? -aA : -aA, 48, -1]].forEach(([a, dx, sd]) => {
    ctx.save(); ctx.translate(dx, -220); ctx.rotate(a * sd); line(ctx, 0, 0, 0, 90, 24, INK); line(ctx, 0, 0, 0, 88, 12, shirt);
    circle(ctx, 0, 92, 13, skin, 6); ctx.restore(); });
  // туловище
  rrect(ctx, -55, -250, 110, 170, 45, shirt);
  if (o.scarf) { rrect(ctx, -50, -258, 100, 30, 14, o.scarf, 7); rrect(ctx, 10, -240, 26, 70, 10, o.scarf, 7); }
  // голова
  circle(ctx, 0, -320, 66, skin);
  // волосы
  ctx.beginPath(); ctx.arc(0, -330, 66, Math.PI * 1.05, Math.PI * 1.95); ctx.quadraticCurveTo(10, -350, -60, -335);
  paint(ctx, o.hair || '#4a2c1a', 8);
  if (o.hat) { ctx.beginPath(); ctx.arc(0, -340, 64, Math.PI, 0); ctx.closePath(); paint(ctx, o.hat, 8); circle(ctx, 0, -408, 16, '#fff', 6); }
  const look = o.look || [0, 0];
  eye(ctx, -22, -325, 15, { blink: blinkAt(t, o.seed || 0), look, sad: o.mood < 0, side: 1 });
  eye(ctx, 22, -325, 15, { blink: blinkAt(t, o.seed || 0), look, sad: o.mood < 0, side: -1 });
  if (o.cold > .3) { // зубы стучат
    rrect(ctx, -18, -292 + Math.sin(t * 40) * 2, 36, 14, 4, '#fff', 5);
  } else mouth(ctx, 0, -288, 30, o.mood ?? 1, o.open || 0);
  circle(ctx, -40, -298, 9, rgba('#ff7b8a', .6), 0); circle(ctx, 40, -298, 9, rgba('#ff7b8a', .6), 0);
  ctx.restore();
}

// Дерево. grey 0..1 — обесцвечивание, leaves 0..1 — сколько листвы осталось
function tree(ctx, x, y, s, t, o = {}) {
  const g = o.grey || 0, lv = o.leaves ?? 1, sway = Math.sin(t * 1.6 + x * .01) * .03;
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s); ctx.rotate(sway);
  poly(ctx, [[-22, 0], [-14, -200], [14, -200], [22, 0]], grey('#8b5a2b', g));
  line(ctx, 0, -150, -60, -230, 16); line(ctx, 0, -150, -60, -230, 6, grey('#8b5a2b', g));
  line(ctx, 0, -170, 55, -250, 16); line(ctx, 0, -170, 55, -250, 6, grey('#8b5a2b', g));
  if (lv > .02) {
    const c = grey(mix('#3fbf4a', '#c9a227', o.autumn || 0), g);
    ctx.save(); ctx.globalAlpha = clamp(lv * 1.5);
    const k = .6 + .4 * lv;
    circle(ctx, -55, -250, 70 * k, c); circle(ctx, 55, -260, 75 * k, c); circle(ctx, 0, -320, 95 * k, c);
    ctx.restore();
  }
  ctx.restore();
}
// Цветок / растение. wilt 0..1 — увядание
function flower(ctx, x, y, s, t, o = {}) {
  const w = o.wilt || 0, g = o.grey ?? w, c = o.color || '#ff5d8f';
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  const bend = w * 1.4 + Math.sin(t * 2 + x) * .05;
  const hx = Math.sin(bend) * 120, hy = -Math.cos(bend) * 120 - 40 * (1 - w);
  curve(ctx, [[0, 0], [0, -70], [hx * .7, hy * .8], [hx, hy]], 18); curve(ctx, [[0, 0], [0, -70], [hx * .7, hy * .8], [hx, hy]], 8, grey('#3fae49', g));
  ellipse(ctx, -30, -50, 30, 14, grey('#4cc35a', g), 7, -.5 + w); ellipse(ctx, 30, -60, 30, 14, grey('#4cc35a', g), 7, .5 - w * .5);
  for (let i = 0; i < 6; i++) { const a = i / 6 * Math.PI * 2 + bend; circle(ctx, hx + Math.cos(a) * 30, hy + Math.sin(a) * 30, 22 * (1 - w * .4), grey(c, g), 7); }
  circle(ctx, hx, hy, 20, grey('#ffd23f', g), 7);
  ctx.restore();
}
// Зайчик (травоядное)
function bunny(ctx, x, y, s, t, o = {}) {
  const c = o.color || '#f2efe9', g = o.grey || 0;
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  const ear = o.mood < 0 ? .9 : .15 * Math.sin(t * 3);
  [[-25, -ear], [25, ear]].forEach(([dx, a]) => { ctx.save(); ctx.translate(dx, -150); ctx.rotate(a + (dx < 0 ? -.15 : .15)); ellipse(ctx, 0, -60, 22, 62, grey(c, g)); ellipse(ctx, 0, -55, 10, 42, grey('#ffb3c1', g), 0); ctx.restore(); });
  ellipse(ctx, 0, -60, 80, 70, grey(c, g)); circle(ctx, 0, -150, 60, grey(c, g));
  eye(ctx, -22, -158, 13, { blink: blinkAt(t, 1.1), sad: o.mood < 0, side: 1 }); eye(ctx, 22, -158, 13, { blink: blinkAt(t, 1.1), sad: o.mood < 0, side: -1 });
  circle(ctx, 0, -135, 8, '#ff7b8a', 4); mouth(ctx, 0, -118, 24, o.mood ?? 1);
  ctx.restore();
}
// Лиса (хищник)
function fox(ctx, x, y, s, t, o = {}) {
  const c = o.color || '#ff7a2f', g = o.grey || 0;
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  ctx.save(); ctx.translate(60, -40); ctx.rotate(-.6 + Math.sin(t * 3) * .15 * (o.mood < 0 ? .2 : 1));
  ellipse(ctx, 50, 0, 70, 30, grey(c, g)); ellipse(ctx, 100, 0, 22, 18, '#fff', 0); ctx.restore();
  ellipse(ctx, 0, -60, 75, 65, grey(c, g));
  poly(ctx, [[-60, -160], [-45, -250], [-5, -185]], grey(c, g)); poly(ctx, [[60, -160], [45, -250], [5, -185]], grey(c, g));
  circle(ctx, 0, -155, 62, grey(c, g));
  poly(ctx, [[-50, -140], [0, -95], [50, -140], [0, -125]], '#fff', 6);
  eye(ctx, -24, -165, 12, { blink: blinkAt(t, 2.3), sad: o.mood < 0, side: 1 }); eye(ctx, 24, -165, 12, { blink: blinkAt(t, 2.3), sad: o.mood < 0, side: -1 });
  circle(ctx, 0, -110, 9, INK, 0); mouth(ctx, 0, -98, 22, o.mood ?? 1);
  ctx.restore();
}
// Холодильник
function fridge(ctx, x, y, s, t, open, o = {}) {
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  rrect(ctx, -150, -520, 300, 520, 30, '#e8eef7');
  rrect(ctx, -130, -500, 260, 480, 18, o.inside || '#cfd8e6', 8);
  line(ctx, -130, -340, 130, -340, 8); line(ctx, -130, -190, 130, -190, 8);
  if (o.cobweb) { ctx.globalAlpha = .8; curve(ctx, [[-130, -500], [-90, -470], [-130, -430]], 4, '#fff'); curve(ctx, [[-130, -470], [-110, -480]], 4, '#fff'); line(ctx, -130, -500, -70, -440, 4, '#fff'); ctx.globalAlpha = 1; }
  // дверь (сжимается по ширине при открытии)
  const dw = 300 * (1 - open * 1.15);
  if (Math.abs(dw) > 3) { rrect(ctx, dw > 0 ? -150 : -150 + dw, -520, Math.abs(dw), 520, 30, dw > 0 ? '#f5f8fc' : '#c4cede');
    if (dw > 0) rrect(ctx, -150 + dw - 50, -360, 20, 120, 10, '#9aa6b8', 6); }
  ctx.restore();
}
// Градусник
function thermo(ctx, x, y, s, level, o = {}) { // level 0..1
  ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
  rrect(ctx, -60, -700, 120, 760, 60, '#f4f8ff', 14);
  for (let i = 0; i <= 10; i++) { const yy = -620 + i * 56; line(ctx, 22, yy, i % 5 ? 45 : 55, yy, 7); }
  const col = mix('#ff3b30', '#3fa9ff', o.cold ?? (1 - level));
  const top = lerp(-40, -640, clamp(level));
  rrect(ctx, -22, top, 44, -top + 20, 22, col, 0);
  circle(ctx, 0, 60, 95, col, 14);
  ctx.beginPath(); ctx.arc(-30, 30, 22, 0, 7); ctx.fillStyle = 'rgba(255,255,255,.5)'; ctx.fill();
  ctx.restore();
}
// Земля
function earth(ctx, x, y, r, t, o = {}) {
  const g = o.grey || 0;
  ctx.save(); ctx.translate(x, y);
  circle(ctx, 0, 0, r, grey('#3a8ee6', g), 14);
  ctx.save(); ctx.beginPath(); ctx.arc(0, 0, r - 6, 0, 7); ctx.clip();
  const sh = (t * 40) % (r * 4);
  [[-.5, -.3, .45, .3], [.3, .1, .35, .45], [-.1, .6, .4, .22], [.75, -.55, .3, .2], [-.9, .3, .3, .35]].forEach(([cx, cy, rx, ry], i) => {
    const xx = ((cx * r + sh + r * 2) % (r * 4)) - r * 2;
    blob(ctx, xx, cy * r, rx * r, i, .12, 5, grey('#57c75b', g), 9, i * 3); });
  ellipse(ctx, 0, -r * .92, r * .5, r * .14, '#fff', 0); ellipse(ctx, 0, r * .95, r * .45, r * .12, '#fff', 0);
  // тень ночной стороны
  const sh2 = o.shade ?? .25;
  ctx.fillStyle = `rgba(10,5,40,${sh2})`; ctx.beginPath(); ctx.arc(r * .55, r * .35, r * 1.15, 0, 7); ctx.fill();
  ctx.restore();
  circle(ctx, 0, 0, r, null, 14);
  ctx.restore();
}
// Здание
function building(ctx, x, y, w, h, color, lit, seed = 1, t = 0) {
  rrect(ctx, x, y - h, w, h, 12, color);
  const r = rng(seed); const cols = Math.max(2, Math.floor(w / 70)), rows = Math.max(2, Math.floor(h / 90));
  const ww = w / cols;
  for (let i = 0; i < cols; i++) for (let j = 0; j < rows - 1; j++) {
    const on = r() < lit;
    rrect(ctx, x + i * ww + ww * .22, y - h + 40 + j * 90, ww * .56, 52, 8, on ? '#ffe27a' : rgba('#1b1230', .35), 5);
  }
}
