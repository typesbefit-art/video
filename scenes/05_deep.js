// Сцена 5. Подводные вулканы, бактерии и глубоководные существа.
function bubbles(c, t, n, seed = 2, x0 = 0, x1 = W, y0 = H, rise = 200) {
  const r = rng(seed);
  for (let i = 0; i < n; i++) { const x = lerp(x0, x1, r()), sp = rise * (.6 + r() * .8), s = 8 + r() * 18, ph = r();
    const y = y0 - ((t * sp + ph * H) % H);
    circle(c, x + Math.sin(t * 3 + i) * 12, y, s, 'rgba(190,230,255,.25)', 4); }
}
function bacterium(c, x, y, s, t, col, seed) {
  withT(c, x + Math.sin(t * 2 + seed) * 20, y + Math.cos(t * 1.7 + seed) * 20, s, Math.sin(t + seed) * .4, () => {
    // жгутики
    curve(c, [[60, 0], [100, Math.sin(t * 9 + seed) * 25], [140, -Math.sin(t * 9 + seed) * 20], [175, 0]], 9, INK);
    blob(c, 0, 0, 70, t * 1.5, .1, 5, col, 9, seed);
    eye(c, -22, -12, 15, { blink: blinkAt(t, seed) }); eye(c, 18, -12, 15, { blink: blinkAt(t, seed) });
    mouth(c, -2, 22, 28, 1);
  });
}
function vent(c, x, y, s, t, seed) {
  withT(c, x, y, s, 0, () => {
    // чёрный курильщик: дым
    for (let i = 0; i < 7; i++) { const ph = (t * .45 + i / 7) % 1;
      c.globalAlpha = (1 - ph) * .9; circle(c, Math.sin(ph * 6 + seed) * 40 * ph, -260 - ph * 520, 40 + ph * 90, '#55487a', 7); }
    c.globalAlpha = 1;
    glow(c, 0, -250, 220, '#ff6a00', .7 + .2 * Math.sin(t * 5 + seed));
    poly(c, [[-130, 0], [-60, -250], [60, -250], [130, 0]], '#6a5a86');
    ellipse(c, 0, -250, 60, 20, '#ff8a1c', 8);
    line(c, -40, -150, -70, -40, 8, '#ff7a1c'); line(c, 30, -200, 55, -90, 8, '#ff7a1c');
  });
}
function tubeworm(c, x, y, h, t, i) {
  const sw = Math.sin(t * 2 + i) * 18;
  curve(c, [[x, y], [x + sw * .3, y - h * .5], [x + sw, y - h]], 30, INK);
  curve(c, [[x, y], [x + sw * .3, y - h * .5], [x + sw, y - h]], 16, '#f1ecf9');
  circle(c, x + sw, y - h - 10, 22, '#ff3b5c', 8);
}
function angler(c, x, y, s, t, o = {}) {
  withT(c, x, y, s, Math.sin(t * 2) * .05, () => {
    // удочка-фонарик
    curve(c, [[40, -110], [90, -230], [190, -240], [230, -170]], 12, INK);
    glow(c, 230, -150, 160, '#b6ff6a', .9); circle(c, 230, -150, 26, '#e8ff9a', 8);
    // хвост
    poly(c, [[-210, 0], [-330, -90 + Math.sin(t * 6) * 15], [-310, 0], [-330, 90 + Math.sin(t * 6) * 15]], '#5d3fd3');
    ellipse(c, 0, 0, 230, 170, '#7b5cff', 12);
    // плавник
    poly(c, [[-60, 60], [-20, 140], [40, 70]], '#5d3fd3', 9);
    // рот с зубами
    c.beginPath(); c.moveTo(90, 30); c.quadraticCurveTo(170, 120, 225, 10); c.closePath(); paint(c, '#2a1050', 10);
    for (let i = 0; i < 4; i++) poly(c, [[110 + i * 28, 40 + i * 6], [124 + i * 28, 68 + i * 4], [134 + i * 28, 36 + i * 4]], '#fff', 5);
    if (o.shades) { // солнечные очки — «свет мне не нужен»
      rrect(c, 40, -90, 90, 60, 20, '#111', 8); rrect(c, 140, -88, 80, 56, 20, '#111', 8); line(c, 130, -66, 140, -66, 8);
      line(c, 60, -78, 85, -78, 6, 'rgba(255,255,255,.5)');
    } else { eye(c, 110, -55, 34, { blink: blinkAt(t, 5) }); }
  });
}

SCENES.deep = {
  render(c, t, env) {
    const b = env.beat(t);
    if (b.i === 0) {
      // Выживут только бактерии — весёлые бактерии крупным планом
      const lt = b.lt;
      sky(c, '#15287a', '#24145a');
      bubbles(c, t, 26, 3);
      const z = lerp(1.2, 1, E.out(clamp(lt / 1.2)));
      withT(c, 540, 900, z, 0, () => {
        glow(c, 0, 0, 600, '#2fd3c8', .25);
        bacterium(c, -220, -330, 1.3, t, '#5ef38c', 1);
        bacterium(c, 210, -170, 1.6, t, '#ff7ad9', 2);
        bacterium(c, -150, 160, 1.2, t, '#ffd23f', 3);
        bacterium(c, 230, 330, 1.1, t, '#6ec6ff', 4);
        bacterium(c, -330, 470, .9, t, '#ff9f43', 5);
      });
    } else if (b.i === 1) {
      // и жители глубин возле вулканов — камера опускается к курильщикам
      const lt = b.lt, k = E.inOut(clamp(lt / b.bd));
      sky(c, '#1a2a70', '#2a1a5a');
      c.save(); c.translate(0, lerp(-260, 0, k));
      bubbles(c, t, 30, 7, 0, W, 2200, 260);
      rrect(c, -50, 1420, W + 100, 900, 0, '#4a3a6a', 10);
      vent(c, 300, 1440, 1.05, t, 1); vent(c, 800, 1460, .8, t, 2);
      for (let i = 0; i < 6; i++) tubeworm(c, 470 + i * 34, 1440, 140 + (i % 3) * 50, t, i);
      for (let i = 0; i < 4; i++) tubeworm(c, 60 + i * 30, 1440, 100 + (i % 2) * 60, t, i + 7);
      // креветка-краб
      withT(c, 640 + Math.sin(t * 2) * 30, 1415, .8, 0, () => {
        ellipse(c, 0, 0, 80, 50, '#ff6b6b', 9); line(c, -40, -40, -70, -100, 8); line(c, 40, -40, 70, -100, 8);
        circle(c, -70, -100, 16, '#fff', 6); circle(c, 70, -100, 16, '#fff', 6); circle(c, -70, -100, 7, INK, 0); circle(c, 70, -100, 7, INK, 0);
        mouth(c, 0, 10, 40, 1);
      });
      // мелкие светящиеся бактерии над жерлами
      const r = rng(4);
      for (let i = 0; i < 18; i++) { const x = 220 + r() * 680, y = 1000 + r() * 380; glow(c, x + Math.sin(t * 2 + i) * 15, y + Math.cos(t * 2 + i) * 15, 30, '#7dffb2', .8); }
      c.restore();
    } else {
      // Им свет вообще не нужен! — удильщик в очках
      const lt = b.lt;
      sky(c, '#141c55', '#120a35');
      bubbles(c, t, 22, 11);
      const sw = lerp(-300, 0, E.out(clamp(lt / .9)));
      angler(c, 480 + sw + Math.sin(t * 1.5) * 20, 900 + Math.sin(t * 2.2) * 25, 1.35, t, { shades: lt > .5 });
      // искорки «крутой»
      burst(c, 650, 760, (lt - .5) / .6, 180, '#e8ff9a', 8);
      bacterium(c, 220, 1250, .8, t, '#5ef38c', 6); bacterium(c, 850, 1220, .7, t, '#ff7ad9', 7);
    }
  },
};
