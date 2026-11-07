// Сцена 2. Город, люди идут, ничего не замечают. Свет летит 8 минут.
function cityStreet(c, t, env, o = {}) {
  const pal = PAL(env.gp(t)), dim = o.dim || 0;
  sky(c, mix(pal.skyTop, '#2a2366', dim), mix(pal.skyBot, '#4b3f8c', dim), 0, 1300);
  // солнце ещё светит (свет в пути!)
  const sunA = 1 - dim;
  if (sunA > .01) { c.globalAlpha = sunA; glow(c, 820, 330, 300, '#fff2a8', .9); circle(c, 820, 330, 110, '#ffe066', 10); c.globalAlpha = 1; }
  // облака
  const cx = (t * 30) % 1400;
  [[cx - 200, 420, 1], [cx + 400, 300, .8], [cx - 800, 560, .9]].forEach(([x, y, s]) => {
    withT(c, ((x % 1600) + 1600) % 1600 - 260, y, s, 0, () => { circle(c, 0, 0, 60, '#fff', 8); circle(c, 60, -20, 75, '#fff', 8); circle(c, 130, 0, 55, '#fff', 8); });
  });
  // дома (параллакс)
  const sc = -t * (o.speed ?? 60);
  const cols = ['#ff8c69', '#ffb347', '#7fb3ff', '#c38bff', '#ff6f91', '#5fd3a5'];
  for (let k = 0; k < 9; k++) {
    const w = 210 + (k * 37) % 90, h = 520 + (k * 131) % 420;
    let x = ((k * 230 + sc * .6) % 2070 + 2070) % 2070 - 300;
    building(c, x, 1300, w, h, grey(cols[k % 6], dim * .5), .25 + dim * .6, k + 1, t);
  }
  // тротуар и дорога
  rrect(c, -50, 1290, W + 100, 120, 0, mix('#d9c7a8', '#8a86a8', dim), 10);
  rrect(c, -50, 1400, W + 100, 600, 0, mix('#5c5470', '#2c2945', dim), 10);
  for (let i = 0; i < 7; i++) rrect(c, ((i * 260 + sc) % 1820 + 1820) % 1820 - 300, 1560, 150, 26, 13, '#f7f3e8', 0);
}

SCENES.city = {
  render(c, t, env) {
    const b = env.beat(t);
    if (b.i === 0) {
      cityStreet(c, t, env);
      const z = lerp(1.08, 1, E.out(clamp(b.lt / 1.5)));
      c.save(); c.translate(W / 2, 1300); c.scale(z, z); c.translate(-W / 2, -1300);
      const ppl = [['#4f8cff', '#ffcf9e', '#3b2314', 0], ['#ff5d8f', '#c98b5e', '#1b1b1b', 1.4], ['#2ec4b6', '#ffe0bd', '#e0a030', 2.7]];
      ppl.forEach(([shirt, skin, hair, seed], i) => {
        const x = ((i * 380 + t * 160) % 1500) - 200;
        person(c, x, 1390 + i * 8, .95, t, { shirt, skin, hair, walk: t * 7 + i, seed, look: [.6, 0] });
      });
      c.restore();
    } else if (b.i === 1) {
      // космос: луч света летит от (уже погасшего) Солнца к Земле
      const lt = b.lt, k = clamp(lt / b.bd);
      sky(c, '#1d1650', '#3a2a7a');
      stars(c, t, 120, 21);
      puff(c, 200, 330, .45 + k * .3, 120, '#ffe9a8', 8);
      line(c, 200, 330, 830, 1100, 8, 'rgba(255,240,180,.35)');
      c.setLineDash([2, 34]); line(c, 200, 330, 830, 1100, 12, '#ffe9a8'); c.setLineDash([]);
      earth(c, 850, 1130, 190, t, { shade: .2 });
      eye(c, 805, 1110, 28, { blink: blinkAt(t, 2), look: [-.6, -.6] }); eye(c, 890, 1110, 28, { blink: blinkAt(t, 2), look: [-.6, -.6] });
      mouth(c, 848, 1175, 50, 1);
      // «пакет света» с мордочкой
      const q = E.inOut(clamp(lt / (b.bd + .6)));
      const lx = lerp(200, 760, q), ly = lerp(330, 1015, q);
      for (let i = 1; i < 8; i++) glow(c, lx - i * 30 * .63, ly - i * 30 * .77, 70 - i * 7, '#ffd23f', .5);
      glow(c, lx, ly, 150, '#fff3a0', 1);
      circle(c, lx, ly, 58, '#ffe45c', 9);
      eye(c, lx - 18, ly - 8, 13, { look: [.6, .6] }); eye(c, lx + 18, ly - 8, 13, { look: [.6, .6] }); mouth(c, lx, ly + 22, 26, 1);
      // таймер 8:00 → 0:00
      const pop = P(lt, 0, .35, E.back);
      const remain = Math.max(0, 480 * (1 - clamp(lt / b.bd)));
      const mm = Math.floor(remain / 60), ss = Math.floor(remain % 60);
      withT(c, 540, 1300 - 640, pop, Math.sin(t * 3) * .03, () => {
        rrect(c, -260, -110, 520, 220, 50, '#ffffff', 12);
        circle(c, -170, 0, 62, '#ffd23f', 10);
        const a = -Math.PI / 2 + lt * 6;
        line(c, -170, 0, -170 + Math.cos(a) * 42, Math.sin(a) * 42, 10);
        line(c, -170, 0, -170, -36, 10);
        text(c, `${mm}:${String(ss).padStart(2, '0')}`, 60, 6, 130, '#ff6b35', 0);
      });
    } else {
      // снова город: прохожий беспечно насвистывает
      const k = clamp(b.lt / b.bd), dim = P(b.lt, b.bd - .9, .9, E.in);
      cityStreet(c, t, env, { dim, speed: 30 });
      const z = lerp(1.0, 1.15, E.sine(k));
      c.save(); c.translate(W / 2, 1200); c.scale(z, z); c.translate(-W / 2, -1200);
      person(c, 300, 1400, 1.15, t, { shirt: '#ff9f1c', skin: '#ffcf9e', hair: '#5a3418', walk: t * 6, seed: 4, mood: 1, look: [.3, -.3] });
      // ноты свиста
      for (let i = 0; i < 3; i++) { const ph = (t * .9 + i / 3) % 1;
        c.globalAlpha = Math.sin(ph * Math.PI); text(c, '♪', 420 + ph * 200 + Math.sin(ph * 9) * 20, 950 - ph * 260, 90, '#fff', 10); }
      c.globalAlpha = 1;
      person(c, 760, 1420, 1.0, t, { shirt: '#7b61ff', skin: '#c98b5e', hair: '#111', seed: 2, mood: 1, look: [0, .7] });
      // телефон
      rrect(c, 770, 1180, 50, 80, 10, '#333', 6); rrect(c, 778, 1190, 34, 58, 5, '#7fe0ff', 0);
      c.restore();
    }
  },
};
