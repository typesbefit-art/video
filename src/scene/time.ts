// Видео-время t (секунды ролика) -> время сцены s (время "внутри мира").
// Скорость сцены задаётся ключами; s(t) = ∫ speed. Слоумо = speed < 1.
// Озвучка и субтитры живут в видео-времени и от рампа не зависят.

export const DURATION = 30;

// [видео-время, скорость]; между ключами — плавная (smoothstep) интерполяция
const SPEED_KEYS: [number, number][] = [
  [0, 1],
  // первый удар и блок
  [8.85, 1], [9.1, 0.14], [9.75, 0.14], [10.1, 1],
  // сталь у самого лица
  [16.05, 1], [16.35, 0.1], [17.35, 0.1], [17.75, 1],
  // пропущенный удар
  [18.62, 1], [18.74, 0.3], [19.0, 0.3], [19.3, 1],
  // последний выпад -> почти стоп-кадр
  [23.3, 1], [23.72, 0.03], [26.55, 0.03], [27.0, 1],
  [30, 1],
];

const smooth = (x: number) => x * x * (3 - 2 * x);

export function speedAt(t: number): number {
  if (t <= SPEED_KEYS[0][0]) return SPEED_KEYS[0][1];
  for (let i = 0; i < SPEED_KEYS.length - 1; i++) {
    const [t0, v0] = SPEED_KEYS[i];
    const [t1, v1] = SPEED_KEYS[i + 1];
    if (t <= t1) {
      const u = t1 > t0 ? (t - t0) / (t1 - t0) : 1;
      return v0 + (v1 - v0) * smooth(u);
    }
  }
  return SPEED_KEYS[SPEED_KEYS.length - 1][1];
}

// таблица интеграла с шагом 1/4800 с
const STEP = 1 / 4800;
const N = Math.ceil((DURATION + 1) / STEP) + 2;
const TABLE = new Float64Array(N);
for (let i = 1; i < N; i++) {
  const ta = (i - 1) * STEP;
  TABLE[i] = TABLE[i - 1] + ((speedAt(ta) + speedAt(ta + STEP)) / 2) * STEP;
}

/** время сцены для видео-времени t */
export function sceneTime(t: number): number {
  if (t <= 0) return t;
  const x = t / STEP;
  const i = Math.min(N - 2, Math.floor(x));
  const f = x - i;
  return TABLE[i] + (TABLE[i + 1] - TABLE[i]) * f;
}
