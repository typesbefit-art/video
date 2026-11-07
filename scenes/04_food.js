// Сцена 4. Растения вянут, цепочка питания рушится, пустой холодильник.
function cross(c, x, y, s, k) { // красный крест «зачёркнуто»
  if (k <= 0) return;
  const a = E.out(clamp(k * 2)), b2 = E.out(clamp(k * 2 - 1));
  line(c, x - s, y - s, x - s + 2 * s * a, y - s + 2 * s * a, 34, INK);
  line(c, x - s, y - s, x - s + 2 * s * a, y - s + 2 * s * a, 18, '#ff3b4f');
  if (b2 > 0) { line(c, x + s, y - s, x + s - 2 * s * b2, y - s + 2 * s * b2, 34, INK); line(c, x + s, y - s, x + s - 2 * s * b2, y - s + 2 * s * b2, 18, '#ff3b4f'); }
}

SCENES.food = {
  render(c, t, env) {
    const b = env.beat(t), pal = PAL(env.gp(t));
    if (b.i === 0) {
      // Без света растения не смогут питаться — цветы вянут
      const k = E.inOut(clamp(b.lt / (b.bd - .2)));
      sky(c, '#2c3b86', '#6f6fb8', 0, 1350);
      // «нет солнца»: пустое место с пунктиром
      c.setLineDash([24, 22]); circle(c, 820, 330, 110, null, 8); c.setLineDash([]);
      text(c, '?', 820, 335, 120, '#ffffff', 12);
      rrect(c, -50, 1250, W + 100, 800, 0, mix('#6aa84f', '#7b7f8c', k), 10);
      const z = lerp(1, 1.1, k);
      withT(c, 540, 1250, z, 0, () => {
        [[-370, .95, '#ff5d8f'], [-190, 1.15, '#ffb703'], [0, 1.35, '#9b5de5'], [190, 1.1, '#ff5d8f'], [370, .95, '#00bbf9']].forEach(([x, s, col], i) =>
          flower(c, x, 0, s, t, { color: col, wilt: clamp(k * 1.25 - i * .06) }));
      });
      // листок-грустяшка с «батарейкой» энергии
      const e = 1 - k;
      withT(c, 260, 520, 1, 0, () => {
        rrect(c, -120, -60, 220, 120, 24, '#fff', 10); rrect(c, 100, -25, 26, 50, 8, '#fff', 8);
        rrect(c, -104, -44, 188 * e + 1, 88, 14, mix('#ff4d4d', '#4cd964', e), 0);
      });
    } else if (b.i === 1) {
      // Цепочка: растения → травоядные → хищники
      const lt = b.lt, t1 = env.w('растения#2') - env.beats[1], t2 = env.w('травоядные') - env.beats[1], t3 = env.w('хищники') - env.beats[1];
      sky(c, '#2a2a6e', '#4b3f8c');
      const items = [[540, 470, t1], [540, 830, t2], [540, 1190, t3]];
      // стрелки
      [[0, 1], [1, 2]].forEach(([a, bb]) => { const ya = items[a][1] + 120, yb = items[bb][1] - 130;
        line(c, 540, ya, 540, yb, 16, '#ffffff'); poly(c, [[510, yb - 20], [570, yb - 20], [540, yb + 15]], '#fff', 8); });
      items.forEach(([x, y, tt], i) => {
        const appear = P(lt, i * .12, .35, E.back), gone = clamp((lt - tt) / .6);
        const g = E.out(gone);
        withT(c, x + (i % 2 ? 1 : -1) * 0, y, appear * (1 - .15 * g), (i - 1) * .05, () => {
          rrect(c, -200, -140, 400, 280, 50, mix('#ffffff', '#9a96b8', g), 12);
          c.save(); c.globalAlpha = 1 - .5 * g;
          if (i === 0) { flower(c, -60, 110, .8, t, { color: '#ff5d8f', wilt: g * .8 }); flower(c, 70, 110, .7, t, { color: '#ffb703', wilt: g }); }
          if (i === 1) bunny(c, 0, 125, .9, t, { mood: gone > 0 ? -1 : 1, grey: g });
          if (i === 2) fox(c, -20, 125, .88, t, { mood: gone > 0 ? -1 : 1, grey: g });
          c.restore();
          cross(c, 0, 0, 120, gone * 1.5);
        });
        puff(c, x, y, (lt - tt) / .7, 150, '#d8d4ee', i + 2);
      });
    } else {
      // И мы. — пустой холодильник в тёмной кухне
      const lt = b.lt, k = clamp(lt / b.bd);
      const z = lerp(1, 1.18, E.inOut(k));
      sky(c, '#241c55', '#3a2f78');
      c.save(); c.translate(540, 1100); c.scale(z, z); c.translate(-540, -1100);
      rrect(c, -50, 1320, W + 100, 700, 0, '#544a88', 10);
      // окно с тёмным небом
      rrect(c, 90, 360, 300, 360, 20, '#0b0820', 12); line(c, 240, 360, 240, 720, 10); line(c, 90, 540, 390, 540, 10);
      stars(c, t, 0);
      const open = P(lt, .15, .6, E.out);
      fridge(c, 700, 1340, 1.25, t, open, { inside: '#2d2a45', cobweb: true });
      // одинокий огрызок яблока на полке
      if (open > .3) { withT(c, 700, 1080, 1, 0, () => { ellipse(c, 0, 0, 22, 34, '#f5e6c8', 6); line(c, 0, -34, 4, -50, 6); }); }
      person(c, 330, 1420, 1.25, t, { shirt: '#6c63ff', skin: '#e8c4a8', hair: '#3b2314', mood: -1, seed: 3, look: [.9, .1] });
      // слеза
      const tear = (lt * 1.4) % 1;
      ellipse(c, 330 - 35, 1420 - 395 + tear * 90, 10, 15, '#8fd8ff', 4);
      c.restore();
    }
  },
};
