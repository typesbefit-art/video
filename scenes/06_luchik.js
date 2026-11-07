// Сцена 6. «Лучик» появляется и подмигивает. Призыв подписаться.
function floaty(c, i, t) { // всплывающие предметы — намёк на «исчезнет гравитация»
  if (i === 0) { circle(c, 0, 0, 55, '#ff4d4d'); line(c, 0, -55, 8, -85, 10); ellipse(c, 30, -75, 26, 12, '#4cd964', 7, -.4); }
  if (i === 1) { circle(c, 0, 0, 60, '#ffffff'); poly(c, [[0, -22], [21, -7], [13, 18], [-13, 18], [-21, -7]], INK, 0); }
  if (i === 2) { ellipse(c, 0, 0, 105, 26, null, 10, -.3); circle(c, 0, 0, 55, '#c38bff'); ctxRing(c); }
  if (i === 3) { rrect(c, -50, -50, 100, 100, 18, '#4fc3f7'); text(c, '?', 0, 4, 80, '#fff', 10); }
}
function ctxRing(c) { c.beginPath(); c.ellipse(0, 0, 105, 26, -.3, Math.PI * 1.02, Math.PI * 1.98, true); c.lineWidth = 10; c.strokeStyle = INK; c.stroke(); }
function pointer(c, x, y) { // рука-курсор
  withT(c, x, y, 1, -.35, () => {
    rrect(c, -20, -95, 40, 100, 20, '#ffd9b3', 9);
    rrect(c, -48, -10, 96, 90, 30, '#ffd9b3', 9);
    rrect(c, -40, 70, 80, 40, 10, '#4f8cff', 9);
  });
}
SCENES.luchik = {
  render(c, t, env) {
    const b = env.beat(t);
    sky(c, '#0b0720', '#1b1040');
    stars(c, t, 150, 31);
    // тёплый свет от Лучика разгоняет тьму (рисуется ДО грейда — мягкий фон)
    const appear = P(t, .05, .9, E.elastic);
    glow(c, 540, b.i === 0 ? 860 : 700, 900 * clamp(appear), '#ff9f1c', .45);
    if (b.i === 1) {
      // «гравитация»: предметы всплывают вверх
      const lt = b.lt;
      const items = [180, 880, 330, 760];
      items.forEach((x, i) => {
        const y = 1380 - ((lt * (90 + i * 25) + i * 230) % 1000);
        withT(c, x + Math.sin(t * 1.3 + i) * 30, y, 1, Math.sin(t + i) * .6, () => floaty(c, i, t));
      });
    }
  },
  top(c, t, env) {
    const b = env.beat(t);
    const appear = P(t, .05, .9, E.elastic);
    const tg = env.w('гравитация');
    const wink = t > tg + .05 && t < tg + .8;      // финальное подмигивание
    const wink2 = t > env.w('дни') && t < env.w('дни') + .35;
    if (b.i === 0) {
      const r = 230 * appear;
      if (r > 1) luchik(c, 540, 860 + Math.sin(t * 3) * 14, r, t, { look: [Math.sin(t * 1.8) * .5, 0], wink: wink2, squash: Math.sin(t * 6) * .03 });
      // сердечки / искорки при появлении
      burst(c, 540, 860, (t - .1) / .8, 380, '#ffd23f', 14);
    } else {
      const lt = b.lt;
      const y = lerp(860, 640, E.inOut(clamp(lt / .6)));
      const r = lerp(230, 190, E.inOut(clamp(lt / .6)));
      luchik(c, 540, y + Math.sin(t * 3) * 12, r, t, { wink, look: wink ? [0, 0] : [0, .7], open: !wink && lt < .4 ? .5 : 0, squash: wink ? -.06 : 0 });
      // кнопка «Подписаться» + нажимающая рука
      const pop = P(lt, .2, .45, E.back);
      const tap = (lt % 1.4) > 1.0 && lt > 1.2 ? 1 : 0;
      withT(c, 540, 1060, pop * (1 - tap * .06), 0, () => {
        rrect(c, -380, -85, 760, 170, 85, '#ff2d55', 12);
        circle(c, -290, 0, 50, '#ffffff', 8);
        poly(c, [[-306, -26], [-306, 26], [-262, 0]], '#ff2d55', 0);
        text(c, 'ПОДПИСАТЬСЯ', 45, 4, 72, '#ffffff', 0);
      });
      if (pop > .9) {
        const hx = 800 + (tap ? -20 : 0), hy = 1200 + (tap ? -25 : 0);
        pointer(c, hx, hy);
        if (tap) { c.globalAlpha = .7; circle(c, hx - 20, hy - 60, 60 + (lt % 1.4 - 1) * 120, null, 8); c.globalAlpha = 1; }
      }
      burst(c, 540, 640, (t - tg - .05) / .6, 330, '#fff3a0', 12);
    }
  },
};
