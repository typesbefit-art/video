// Сцена 1. Земля из космоса, Солнце гаснет с «пуф».
SCENES.space = {
  render(c, t, env) {
    const b = env.beat(t), tp = env.w('исчезнет'), pal = PAL(env.gp(t));
    const off = P(t, tp, .45, E.in);             // 0 → 1: Солнце погасло
    const shake = Math.max(0, 1 - Math.abs(t - tp - .2) / .5) * 22;
    sky(c, mix('#2b1f6b', '#0e0a2a', off), mix('#5a2d82', '#1a1240', off));
    c.save();
    c.translate(wob(t) * shake, wob(t + 9) * shake);

    if (b.i === 0) {
      const z = lerp(1, 1.08, E.sine(clamp(t / env.dur)));
      c.translate(W / 2, H / 2); c.scale(z, z); c.translate(-W / 2, -H / 2);
      stars(c, t, 110, 3, .5 + .5 * off);
      // Солнце
      const sx = 540, sy = 470, sr = 210 * (1 - off) * (1 + .04 * Math.sin(t * 4));
      if (off < 1) {
        glow(c, sx, sy, sr * 2.6, '#ffcf3f', .8);
        withT(c, sx, sy, 1, t * .3, () => {
          for (let i = 0; i < 12; i++) { c.save(); c.rotate(i / 12 * Math.PI * 2);
            poly(c, [[sr * .85, -sr * .18], [sr * 1.45 + 15 * Math.sin(t * 6 + i), 0], [sr * .85, sr * .18]], '#ff9f1c', 9); c.restore(); }
        });
        circle(c, sx, sy, sr, '#ffd23f', 12);
        const scared = P(t, tp - .5, .25, E.out);
        eye(c, sx - sr * .33, sy - sr * .12, sr * (.2 + .06 * scared), { blink: blinkAt(t, 1), look: [0, .6 * scared] });
        eye(c, sx + sr * .33, sy - sr * .12, sr * (.2 + .06 * scared), { blink: blinkAt(t, 1), look: [0, .6 * scared] });
        mouth(c, sx, sy + sr * .35, sr * .4, 1 - scared, scared);
      }
      puff(c, sx, sy, (t - tp - .25) / 1.1, 170, '#ffe9a8', 5);
      // Земля
      const ey = 1250 + Math.sin(t * 1.5) * 8;
      earth(c, 540, ey, 330, t, { shade: lerp(.15, .6, off) });
      const look = [0, -.7 + off * .4];
      eye(c, 470, ey - 30, 46, { blink: blinkAt(t, 3), look });
      eye(c, 610, ey - 30, 46, { blink: blinkAt(t, 3), look });
      mouth(c, 540, ey + 70, 70, 1 - 2 * off, off > .5 ? .6 : 0);
    } else {
      // Досмотри до конца! — наезд на испуганную Землю
      const lt = b.lt, z = lerp(1.0, 1.25, E.inOut(clamp(lt / b.bd)));
      stars(c, t, 140, 11, 1);
      c.translate(540, 900); c.scale(z, z); c.translate(-540, -900);
      const ey = 900 + Math.sin(t * 7) * 6;
      earth(c, 540, ey, 400, t, { shade: .62 });
      const lk = [Math.sin(t * 3) * .8, 0];
      eye(c, 455, ey - 40, 62, { blink: blinkAt(t, 4), look: lk });
      eye(c, 625, ey - 40, 62, { blink: blinkAt(t, 4), look: lk });
      mouth(c, 540, ey + 95, 90, -1, .7 + .2 * Math.sin(t * 9));
      // «?!» выпрыгивают
      const q = P(lt, .05, .35, E.back);
      withT(c, 845, 470, q, -.15 + Math.sin(t * 5) * .05, () => text(c, '?!', 0, 0, 220, '#ffd23f', 18));
      // капли пота
      ellipse(c, 870, 760 + (lt * 200) % 120, 18, 28, '#9fe3ff', 6);
    }
    c.restore();
  },
};
