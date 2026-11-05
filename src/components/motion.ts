import { Easing, interpolate, spring, SpringConfig } from "remotion";

/** Общие помощники анимации: никаких линейных движений, только easing и spring. */

export type Vec = { x: number; y: number };

const clamp01 = (t: number) => Math.min(1, Math.max(0, t));
export const progress = (frame: number, start: number, end: number) =>
  clamp01((frame - start) / (end - start));

/**
 * Кусочная дорожка ключей: [кадр, значение][]. Между ключами — easing (по умолчанию inOut cubic).
 * До первого ключа держит первое значение, после последнего — последнее.
 */
export const track = (
  frame: number,
  keys: [number, number][],
  easing: (t: number) => number = Easing.inOut(Easing.cubic),
): number => {
  if (frame <= keys[0][0]) return keys[0][1];
  for (let i = 0; i < keys.length - 1; i++) {
    const [f0, v0] = keys[i];
    const [f1, v1] = keys[i + 1];
    if (frame <= f1) {
      return interpolate(frame, [f0, f1], [v0, v1], {
        easing,
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
    }
  }
  return keys[keys.length - 1][1];
};

/** spring, стартующий с кадра `start` (до него 0). */
export const springAt = (
  frame: number,
  start: number,
  fps: number,
  config: Partial<SpringConfig> = {},
) => (frame < start ? 0 : spring({ frame: frame - start, fps, config }));

/**
 * Прыжок по дуге: горизонталь с easing, вертикаль — парабола (гравитация).
 * Возвращает позицию и «растяжение» по скорости для squash & stretch.
 */
export const arc = (
  frame: number,
  start: number,
  end: number,
  from: Vec,
  to: Vec,
  height: number,
) => {
  const t = progress(frame, start, end);
  const tx = Easing.inOut(Easing.sin)(t);
  const x = from.x + (to.x - from.x) * tx;
  const y = from.y + (to.y - from.y) * t - 4 * height * t * (1 - t);
  // |скорость| максимальна на взлёте и при приземлении, 0 в апогее
  const speed = Math.abs(1 - 2 * t);
  return { x, y, t, speed };
};

/** Свободное падение: ускорение по вертикали (t²), горизонталь замедляется. */
export const fall = (frame: number, start: number, end: number, from: Vec, to: Vec) => {
  const t = progress(frame, start, end);
  return {
    x: from.x + (to.x - from.x) * Easing.out(Easing.quad)(t),
    y: from.y + (to.y - from.y) * t * t,
    t,
  };
};

export type Impact = { frame: number; strength: number };

/**
 * Squash & stretch после ударов: недодемпфированный spring даёт сплющивание,
 * затем вытягивание и затухающее покачивание. Объём примерно сохраняется.
 */
export const impactSquash = (frame: number, impacts: Impact[], fps: number) => {
  let sx = 1;
  let sy = 1;
  for (const imp of impacts) {
    const f = frame - imp.frame;
    if (f < 0 || f > 75) continue;
    const s = spring({ frame: f, fps, config: { damping: 7, stiffness: 220, mass: 0.6 } });
    const k = imp.strength * (1 - s);
    sy *= 1 - k;
    sx *= 1 + k * 0.85;
  }
  return { sx, sy };
};

/** Вытягивание в полёте пропорционально скорости. */
export const airStretch = (speed: number, amount = 0.18) => ({
  sx: 1 - amount * 0.6 * speed,
  sy: 1 + amount * speed,
});

/** Округление угла к ближайшему «ровному» положению (кратному 360). */
export const nearestUpright = (deg: number) => Math.round(deg / 360) * 360;
