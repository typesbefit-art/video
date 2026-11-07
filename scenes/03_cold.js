// Сцена 3. Градусник падает, деревья сереют, пар изо рта.
function snow(c, t, n, speed = 1, seed = 5, size = 1) {
  const r = rng(seed);
  for (let i = 0; i < n; i++) {
    const x0 = r() * W, sp = (120 + r() * 160) * speed, s = (6 + r() * 10) * size, ph = r() * 10;
    const y = ((r() * H + t * sp) % (H + 100)) - 50, x = x0 + Math.sin(t * 1.5 + ph) * 40;
    circle(c, x, y, s, '#ffffff', 0);
  }
}
function frost(c, k) { // иней по углам
  if (k <= 0) return;
  c.save(); c.globalAlpha = .9 * k;
  [[0, 0, 1, 1], [W, 0, -1, 1], [0, H, 1, -1], [W, H, -1, -1]].forEach(([x, y, sx, sy], j) => {
    const r = rng(40 + j);
    for (let i = 0; i < 14; i++) { const a = r() * Math.PI / 2, d = (80 + r() * 300) * k;
      circle(c, x + sx * Math.cos(a) * d, y + sy * Math.sin(a) * d, (40 + r() * 70) * k, 'rgba(225,240,255,.55)', 0); }
  });
  c.restore();
}
function breath(c, x, y, t, k = 1, dir = 1) {
  for (let i = 0; i < 3; i++) { const ph = (t * .8 + i / 3) % 1;
    c.globalAlpha = (1 - ph) * .85 * k;
    circle(c, x + dir * ph * 160, y - ph * 70, 18 + ph * 50, '#eef6ff', 6); }
  c.globalAlpha = 1;
}

SCENES.cold = {
  render(c, t, env) {
    const b = env.beat(t), pal = PAL(env.gp(t));
    if (b.i === 0) {
      // Но потом резко похолодает — деревья сереют, листья опадают
      const k = clamp(b.lt / b.bd);
      sky(c, pal.skyTop, pal.skyBot, 0, 1350);
      rrect(c, -50, 1250, W + 100, 800, 0, mix('#79c257', '#cfd9e8', E.inOut(k)), 10);
      [[160, 1290, 1.2, 0], [540, 1240, 1.5, 1], [910, 1300, 1.15, 2]].forEach(([x, y, s, i]) =>
        tree(c, x, y, s, t, { grey: E.inOut(clamp(k * 1.3 - i * .1)), leaves: 1 - E.in(clamp(k * 1.2)), autumn: k }));
      // падающие листья
      const r = rng(9);
      for (let i = 0; i < 14; i++) { const x0 = 100 + r() * 880, d = r() * .6, ph = clamp((k - d) * 2.2);
        if (ph > 0 && ph < 1) { const yy = lerp(700 + r() * 250, 1300, ph);
          ellipse(c, x0 + Math.sin(ph * 12 + i) * 50, yy, 22, 12, grey('#d9a12b', ph), 6, ph * 8); } }
      snow(c, t, Math.floor(k * 40), .8, 3);
      // дрожащая птичка на ветке не нужна — хватит ветра
    } else if (b.i === 1) {
      // За неделю температура упадёт ниже нуля — градусник
      const lt = b.lt, k = E.inOut(clamp(lt / (b.bd - .2)));
      sky(c, mix('#5f7fd0', '#3b4c9a', k), mix('#a8c4f5', '#6b7fc8', k));
      snow(c, t, 30, .7, 8, .8);
      const level = lerp(.78, .32, k);           // 0 градусов ≈ уровень .4
      const sh = (lt > b.bd * .7) ? wob(t, 2) * 6 : 0;
      thermo(c, 420 + sh, 1150, 1.25, level, { cold: k });
      const deg = Math.round(lerp(15, -12, k));
      withT(c, 790, 640, 1 + .08 * Math.sin(t * 6), .05, () =>
        text(c, (deg > 0 ? '+' : deg < 0 ? '−' : '') + Math.abs(deg) + '°', 0, 0, 170, deg > 0 ? '#ff6b35' : '#7fd4ff', 18));
      // календарь «7 дней»
      const cp = P(lt, .1, .4, E.back);
      withT(c, 800, 980, cp, -.08, () => {
        rrect(c, -130, -120, 260, 250, 30, '#fff', 12); rrect(c, -130, -120, 260, 70, [30, 30, 0, 0], '#ff5d5d', 12);
        circle(c, -70, -120, 14, '#ddd', 6); circle(c, 70, -120, 14, '#ddd', 6);
        const day = Math.min(7, 1 + Math.floor(clamp(lt / (b.bd * .8)) * 7));
        text(c, String(day), 0, 30, 120, INK, 0); text(c, 'ДЕНЬ', 0, -85, 40, '#fff', 0, 900);
      });
      frost(c, E.out(k) * .7);
    } else {
      // а через год до минус 70 — человечек мёрзнет
      const lt = b.lt, w70 = env.w("70") - env.beats[2];
      const slam = P(lt, w70 - .05, .3, E.back);
      const sh = 6 + (lt > w70 ? Math.max(0, 1 - (lt - w70) / .5) * 26 : 0);
      c.save(); c.translate(wob(t, 1.5) * sh, wob(t + 4, 1.5) * sh);
      sky(c, '#1d2a6b', '#4a62b0');
      rrect(c, -50, 1300, W + 100, 700, 0, '#e3eeff', 10);
      tree(c, 140, 1320, 1.0, t, { grey: 1, leaves: 0 }); tree(c, 960, 1330, 1.1, t, { grey: 1, leaves: 0 });
      // сугробы
      ellipse(c, 200, 1330, 260, 70, '#f4f8ff', 9); ellipse(c, 880, 1340, 280, 80, '#f4f8ff', 9);
      const z = lerp(1, 1.12, E.sine(clamp(lt / b.bd)));
      withT(c, 540, 1390, z, 0, () => {
        person(c, 0, 0, 1.25, t, { shirt: '#4fa3ff', skin: '#ffd9c9', hair: '#5a3418', cold: 1, scarf: '#ff5d5d', hat: '#ff5d5d', seed: 1, look: [0, -.2] });
        breath(c, 50, -380, t, 1, 1);
        // сосулька на носу :)
        poly(c, [[-6, -390], [6, -390], [0, -360 + 6 * Math.sin(t * 3)]], '#cfefff', 4);
      });
      snow(c, t, 70, 1.4, 12, 1.1);
      frost(c, .9);
      withT(c, 540, 560, slam, -.06, () => text(c, '−70°C', 0, 0, 230, '#8fe0ff', 22));
      c.restore();
    }
  },
};
