import { Pose, SAYA_DIR, SHEATHED_GRIP } from "./fighter";
import { DEG, V3, clamp, easeIn, easeOut, mix, norm, smooth, smoother } from "./math";
import { sceneTime } from "./time";

// ---------- служебное ----------
type Ease = "io" | "in" | "out" | "lin" | "hold";
interface Key {
  t: number; // видео-время
  p: Pose;
  e?: Ease; // кривая перехода К этому ключу
  gait?: boolean; // шаги при перемещении в этом сегменте
}

const yawTo = (from: [number, number], to: [number, number]) =>
  Math.atan2(to[0] - from[0], to[1] - from[1]) / DEG;

/** мировая точка -> root-space позы (без высоты корня) */
function toLocal(p: Pose, w: V3): V3 {
  const c = Math.cos(p.yaw * DEG);
  const s = Math.sin(p.yaw * DEG);
  const dx = w[0] - p.x;
  const dz = w[2] - p.z;
  return [dx * c - dz * s, w[1], dx * s + dz * c];
}

/** поставить хват в мировую точку и направить клинок на мировую цель */
function gripAim(p: Pose, gripW: V3, aimW: V3, edge?: V3): Pose {
  const g = toLocal(p, gripW);
  const a = toLocal(p, aimW);
  return { ...p, sp: g, sd: norm([a[0] - g[0], a[1] - g[1], a[2] - g[2]]), se: edge ?? p.se, rh: 1, lh: 1 };
}

const P = (base: Pose, o: Partial<Pose>): Pose => ({ ...base, ...o });

// ---------- базовые позы ----------
const STAND: Pose = {
  x: 0, z: 0, yaw: 0,
  hipY: 0.97, hipYaw: 0,
  spine: [3, 0, 0], head: [2, 0, 0],
  fl: [0.12, 0, 0.06], fr: [-0.12, 0, -0.04],
  sp: SHEATHED_GRIP, sd: SAYA_DIR, se: [0, 1, 0],
  rh: 0, lh: 0,
  rf: [-0.24, 0.8, 0.04], lf: [0.17, 0.93, 0.22],
};
const HILT = P(STAND, {
  hipY: 0.93, spine: [9, 8, 0], head: [-7, -7, 0], rh: 1,
  fl: [0.14, 0, -0.12], fr: [-0.12, 0, 0.2],
});
const DRAW1 = P(HILT, {
  sp: [SHEATHED_GRIP[0] - SAYA_DIR[0] * 0.4, SHEATHED_GRIP[1] - SAYA_DIR[1] * 0.4, SHEATHED_GRIP[2] - SAYA_DIR[2] * 0.4],
  spine: [12, 22, 0], hipY: 0.9,
});
const DRAW2 = P(DRAW1, { sp: [0.0, 1.18, 0.52], sd: norm([1, 0.08, 0.3]), se: [0, 0, 1], spine: [12, 6, 0] });
const DRAW3 = P(DRAW2, { sp: [-0.2, 1.22, 0.5], sd: norm([-0.25, 0.3, 1]), se: [-1, 0, 0], spine: [10, -8, 0] });
const CHUDAN = P(STAND, {
  hipY: 0.9, spine: [10, -8, 0], head: [-8, 8, 0],
  fr: [-0.1, 0, 0.28], fl: [0.13, 0, -0.2],
  sp: [-0.03, 1.05, 0.42], sd: norm([0, 0.5, 1]), se: [0, -1, 0.3], rh: 1, lh: 1,
});
const JODAN = P(CHUDAN, { spine: [2, -5, 0], head: [-4, 5, 0], sp: [-0.03, 1.74, 0.14], sd: norm([0, 0.55, -0.85]), se: [0, 1, 0.3] });
const JODAN_R = P(JODAN, { spine: [4, -18, -4], sp: [-0.22, 1.72, 0.08], sd: norm([-0.5, 0.6, -0.6]), se: [0.3, 1, 0.4] });
const HASSO = P(CHUDAN, { spine: [6, -12, 0], sp: [-0.16, 1.42, 0.16], sd: norm([0.05, 1, -0.15]), se: [0, 0, 1] });
const LUNGE_WIND = P(CHUDAN, {
  hipY: 0.82, spine: [18, 22, 0], head: [-14, -16, 0],
  fl: [0.16, 0, 0.3], fr: [-0.14, 0, -0.32],
  sp: [0.16, 1.45, 0.28], sd: norm([0.75, 0.45, -0.5]), se: [-0.2, 0, 1],
});
const LUNGE_CUT = P(LUNGE_WIND, { spine: [20, 0, 0], head: [-16, 0, 0], sp: [-0.05, 1.28, 0.58], sd: norm([0.05, 0.05, 1]), se: [-1, 0, 0] });
const LUNGE_END = P(LUNGE_WIND, {
  hipY: 0.74, spine: [16, -24, 0], head: [-12, 20, 0],
  fl: [0.18, 0, -0.42], fr: [-0.16, 0, 0.5],
  sp: [-0.42, 1.18, 0.26], sd: norm([-0.85, -0.2, -0.5]), se: [0, 0, -1],
});

// ---------- позиции ----------
const A0 = { x: -4, z: 0, yaw: 90 };
const B0 = { x: 4, z: 0, yaw: -90 };
const at = (base: Pose, r: { x: number; z: number; yaw: number }, o: Partial<Pose> = {}) => P(base, { ...r, ...o });

// точки контакта (мир)
export const C1: V3 = [0.38, 1.7, 0]; // первый удар / блок
const C2: V3 = [0.05, 1.42, -0.3];
const C3: V3 = [0.1, 1.38, 0.3];
const C4: V3 = [0, 1.72, 0];

const A_HIT = { x: -0.75, z: 0, yaw: 90 };
const B_HIT = { x: 1.1, z: 0, yaw: -90 };
const A_EX = { x: -0.85, z: 0, yaw: 90 };
const B_EX = { x: 1.0, z: 0, yaw: -90 };
const A_CL = { x: -0.7, z: 0, yaw: 90 };
const B_CL = { x: 0.7, z: 0, yaw: -90 };

// сторона-шаг и вращение
const A_BACK: [number, number] = [-1.7, -0.1];
const B_SIDE: [number, number] = [1.2, 0.9];
export const B_SPIN_END: [number, number] = [-0.76, 0.24];
const fB = yawTo(B_SPIN_END, A_BACK); // направление B -> A
const fA = yawTo(A_BACK, B_SPIN_END);
const A_COUNTER: [number, number] = [-1.72, -0.12];
const fA2 = yawTo(A_COUNTER, B_SPIN_END);
const B_STAG: [number, number] = [0.25, 0.62];

const A_F = { x: -2.6, z: -0.35, yaw: 90 };
const B_F = { x: 2.6, z: 0.35, yaw: -90 };
const A_END = { x: 1.7, z: -0.35, yaw: 90 };
const B_END = { x: -1.7, z: 0.35, yaw: -90 };

// горизонтальный клинок с азимутом th (в локальных градусах; 0 = вперёд, +90 = влево)
const flat = (th: number, y = 0.06): V3 => norm([Math.sin(th * DEG), y, Math.cos(th * DEG)]);
const SPIN = P(CHUDAN, { hipY: 0.86, spine: [8, 0, 0], head: [-6, 0, 0], fl: [0.16, 0, 0.12], fr: [-0.16, 0, -0.1], se: [0, 0, 1] });

const spinPose = (pos: [number, number], yaw: number, th: number, o: Partial<Pose> = {}): Pose =>
  P(SPIN, {
    x: pos[0], z: pos[1], yaw,
    sp: [Math.sin((th - 8) * DEG) * 0.42, 1.5, Math.cos((th - 8) * DEG) * 0.42],
    sd: flat(th), se: norm([Math.sin((th + 90) * DEG), 0, Math.cos((th + 90) * DEG)]),
    ...o,
  });

const lerp2 = (a: [number, number], b: [number, number], u: number): [number, number] => [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u];

// ---------- ключи A (красный) ----------
const A_KEYS: Key[] = [
  { t: 0, p: at(STAND, A0) },
  { t: 3.9, p: at(STAND, A0) },
  { t: 4.8, p: at(HILT, A0), e: "io" },
  { t: 6.05, p: at(HILT, A0), e: "hold" },
  { t: 6.45, p: at(DRAW1, A0), e: "in" },
  { t: 6.62, p: at(DRAW2, A0), e: "lin" },
  { t: 6.85, p: at(DRAW3, A0), e: "out" },
  { t: 7.35, p: at(CHUDAN, A0), e: "io" },
  { t: 7.55, p: at(CHUDAN, A0) },
  { t: 8.35, p: at(JODAN, { x: -1.1, z: 0, yaw: 90 }, { spine: [14, -4, 0] }), e: "io", gait: true },
  { t: 8.62, p: at(JODAN, A_HIT, { spine: [6, -4, 0] }), e: "out" },
  { t: 9.2, p: gripAim(at(CHUDAN, A_HIT, { spine: [18, -6, 0], head: [-4, 4, 0], fr: [-0.1, 0, 0.42] }), [-0.25, 1.55, 0.02], C1), e: "in" },
  { t: 9.85, p: gripAim(at(CHUDAN, A_HIT, { spine: [15, -6, 0], fr: [-0.1, 0, 0.42] }), [-0.3, 1.5, 0.02], [0.3, 1.82, 0.0]), e: "out" },
  { t: 10.15, p: at(CHUDAN, A_EX), e: "io" },
  // блок атаки B
  { t: 10.55, p: gripAim(at(CHUDAN, A_EX, { spine: [8, 14, 0] }), [-0.28, 1.05, -0.22], C2), e: "out" },
  { t: 10.8, p: at(JODAN_R, A_EX), e: "io" },
  { t: 11.1, p: gripAim(at(CHUDAN, A_EX, { spine: [16, -14, 0], fr: [-0.1, 0, 0.4] }), [-0.33, 1.45, 0.18], C3), e: "in" },
  // клинч
  { t: 11.6, p: gripAim(at(CHUDAN, A_CL, { spine: [16, -4, 0] }), [-0.34, 1.33, 0.05], C4), e: "io" },
  { t: 12.2, p: gripAim(at(CHUDAN, { ...A_CL, x: -0.66 }, { spine: [18, -4, 0] }), [-0.3, 1.36, 0.05], [0.04, 1.73, 0]), e: "io" },
  { t: 12.9, p: gripAim(at(CHUDAN, { ...A_CL, x: -0.74 }, { spine: [15, -4, 0] }), [-0.38, 1.31, 0.05], [-0.03, 1.71, 0]), e: "io" },
  // отброшен назад
  { t: 13.55, p: at(CHUDAN, { x: A_BACK[0], z: A_BACK[1], yaw: 86 }, { spine: [2, -8, 0] }), e: "out" },
  { t: 14.4, p: at(CHUDAN, { x: A_BACK[0], z: A_BACK[1], yaw: fA }), e: "io" },
  { t: 15.9, p: at(CHUDAN, { x: A_BACK[0], z: A_BACK[1], yaw: fA }, { spine: [4, -6, 0] }), e: "io" },
  // отклоняется от клинка
  { t: 16.9, p: at(CHUDAN, { x: A_BACK[0], z: A_BACK[1], yaw: fA }, { hipY: 0.86, spine: [-16, -4, -4], head: [-22, 6, 0], sp: [-0.08, 0.98, 0.36] }), e: "io" },
  { t: 17.7, p: at(CHUDAN, { x: A_BACK[0], z: A_BACK[1], yaw: fA }, { hipY: 0.87, spine: [-10, -4, 0], head: [-12, 6, 0] }), e: "io" },
  // контратака по плечу B
  { t: 18.3, p: at(JODAN_R, { x: A_COUNTER[0] - 0.12, z: A_COUNTER[1], yaw: fA2 }), e: "io" },
  { t: 18.75, p: P(at(CHUDAN, { x: A_COUNTER[0], z: A_COUNTER[1], yaw: fA2 }, { spine: [18, -12, 0], fr: [-0.1, 0, 0.42] }), {}), e: "in" },
  { t: 19.3, p: at(CHUDAN, { x: A_COUNTER[0], z: A_COUNTER[1], yaw: fA2 }, { spine: [20, 6, 0], sp: [0.1, 0.92, 0.45], sd: norm([0.5, -0.3, 1]) }), e: "out" },
  { t: 20.99, p: at(CHUDAN, { x: A_COUNTER[0], z: A_COUNTER[1], yaw: fA2 }), e: "io" },
  // финальная дистанция
  { t: 21.0, p: at(HASSO, A_F), e: "lin" },
  { t: 22.55, p: at(HASSO, A_F, { spine: [8, -12, 0] }), e: "io" },
  { t: 22.92, p: at(LUNGE_WIND, { ...A_F, x: lerp2([A_F.x, 0], [A_END.x, 0], 0.18)[0] }), e: "in", gait: true },
  { t: 23.22, p: at(LUNGE_CUT, { ...A_F, x: lerp2([A_F.x, 0], [A_END.x, 0], 0.62)[0] }), e: "lin", gait: true },
  { t: 23.62, p: at(LUNGE_END, A_END), e: "out", gait: true },
  { t: 27.1, p: at(LUNGE_END, A_END, { spine: [15, -24, 0] }), e: "io" },
  // выпрямляется, стряхивает кровь (тибури)
  { t: 28.1, p: at(CHUDAN, A_END, { hipY: 0.94, spine: [4, -10, 0], head: [-2, 0, 0], sp: [-0.32, 1.12, 0.38], sd: norm([-0.25, 0.25, 1]) }), e: "io" },
  { t: 28.32, p: at(CHUDAN, A_END, { hipY: 0.94, spine: [4, -10, 0], sp: [-0.3, 1.2, 0.34], sd: norm([-0.3, 0.6, 0.8]) }), e: "io" },
  { t: 28.48, p: at(CHUDAN, A_END, { hipY: 0.92, spine: [6, -12, 0], sp: [-0.38, 0.95, 0.36], sd: norm([-0.35, -0.55, 1]) }), e: "in" },
  { t: 30, p: at(CHUDAN, A_END, { hipY: 0.95, spine: [3, -10, 0], head: [-6, 0, 0], sp: [-0.38, 0.96, 0.32], sd: norm([-0.35, -0.6, 1]) }), e: "io" },
];

// контратака A: целимся в левое плечо B — точку уточняет world (после расчёта позы B)
export const A_COUNTER_KEY = A_KEYS.findIndex((k) => k.t === 18.75);

// ---------- ключи B (синий) ----------
const B_KEYS: Key[] = [
  { t: 0, p: at(STAND, B0) },
  { t: 4.4, p: at(STAND, B0) },
  { t: 5.3, p: at(HILT, B0), e: "io" },
  { t: 6.1, p: at(HILT, B0), e: "hold" },
  { t: 6.52, p: at(DRAW1, B0), e: "in" },
  { t: 6.7, p: at(DRAW2, B0), e: "lin" },
  { t: 6.95, p: at(DRAW3, B0), e: "out" },
  { t: 7.45, p: at(CHUDAN, B0), e: "io" },
  { t: 7.8, p: at(CHUDAN, B0) },
  { t: 8.6, p: at(CHUDAN, B_HIT, { spine: [12, -8, 0] }), e: "io", gait: true },
  { t: 9.05, p: gripAim(at(CHUDAN, B_HIT, { spine: [4, 6, 0], head: [-10, 0, 0] }), [0.55, 1.55, -0.3], [0.1, 1.95, 0.5]), e: "out" },
  { t: 9.2, p: gripAim(at(CHUDAN, B_HIT, { spine: [2, 6, 0], head: [-10, 0, 0] }), [0.55, 1.55, -0.3], [0.1, 1.95, 0.5]), e: "lin" },
  { t: 9.85, p: gripAim(at(CHUDAN, B_HIT, { spine: [-2, 6, 0], head: [-10, 0, 0] }), [0.58, 1.5, -0.3], [0.12, 1.88, 0.5]), e: "out" },
  { t: 10.25, p: at(JODAN_R, B_EX), e: "io" },
  { t: 10.55, p: gripAim(at(CHUDAN, B_EX, { spine: [16, -16, 0], fr: [-0.1, 0, 0.4] }), [0.5, 1.5, -0.2], C2), e: "in" },
  { t: 10.85, p: at(CHUDAN, B_EX, { spine: [8, 12, 0] }), e: "io" },
  { t: 11.1, p: gripAim(at(CHUDAN, B_EX, { spine: [8, 14, 0] }), [0.45, 1.05, 0.25], C3), e: "out" },
  { t: 11.6, p: gripAim(at(CHUDAN, B_CL, { spine: [16, -4, 0] }), [0.34, 1.33, -0.05], C4), e: "io" },
  { t: 12.2, p: gripAim(at(CHUDAN, { ...B_CL, x: 0.74 }, { spine: [14, -4, 0] }), [0.38, 1.31, -0.05], [0.04, 1.73, 0]), e: "io" },
  { t: 12.9, p: gripAim(at(CHUDAN, { ...B_CL, x: 0.66 }, { spine: [19, -4, 0] }), [0.3, 1.36, -0.05], [-0.03, 1.71, 0]), e: "io" },
  // отталкивает и уходит в сторону
  { t: 13.4, p: at(CHUDAN, { x: 0.95, z: 0.1, yaw: -90 }, { spine: [14, 10, 0] }), e: "out" },
  { t: 14.35, p: at(CHUDAN, { x: B_SIDE[0], z: B_SIDE[1], yaw: yawTo(B_SIDE, A_BACK) }), e: "io", gait: true },
  // разворот на 360°
  { t: 14.6, p: spinPose(B_SIDE, fB, -100, { spine: [12, -30, 0] }), e: "io" },
  { t: 15.2, p: spinPose(lerp2(B_SIDE, B_SPIN_END, 0.45), fB + 110, -90), e: "in", gait: true },
  { t: 15.85, p: spinPose(lerp2(B_SIDE, B_SPIN_END, 0.92), fB + 300, -90), e: "lin", gait: true },
  { t: 16.3, p: spinPose(B_SPIN_END, fB + 345, -20, { spine: [8, 6, 0] }), e: "lin" },
  { t: 17.6, p: spinPose(B_SPIN_END, fB + 365, 40, { spine: [10, 28, 0] }), e: "lin" },
  { t: 18.05, p: spinPose(B_SPIN_END, fB + 365, 50, { spine: [6, 24, 0] }), e: "out" },
  // пропускает удар в плечо
  { t: 18.6, p: at(CHUDAN, { x: B_SPIN_END[0], z: B_SPIN_END[1], yaw: fB }, { spine: [6, 10, 0] }), e: "io" },
  { t: 18.75, p: at(CHUDAN, { x: B_SPIN_END[0], z: B_SPIN_END[1], yaw: fB }, { spine: [8, 12, 0] }), e: "lin" },
  { t: 19.35, p: at(CHUDAN, { x: B_STAG[0], z: B_STAG[1], yaw: fB - 18 }, { hipY: 0.78, spine: [22, 28, 18], head: [24, 10, 0], sp: [-0.25, 0.75, 0.32], sd: norm([-0.2, -0.75, 0.6]), lh: 0, lf: [0.2, 1.25, 0.12] }), e: "out", gait: true },
  { t: 19.9, p: at(CHUDAN, { x: B_STAG[0], z: B_STAG[1], yaw: fB - 18 }, { hipY: 0.8, spine: [20, 22, 14], head: [16, 8, 0], sp: [-0.25, 0.72, 0.32], sd: norm([-0.2, -0.8, 0.5]), lh: 0, lf: [0.2, 1.25, 0.12] }), e: "io" },
  { t: 20.99, p: at(CHUDAN, { x: B_STAG[0], z: B_STAG[1], yaw: fB - 6 }, { hipY: 0.9, spine: [6, 4, 2], head: [-12, 0, 0], lh: 1 }), e: "io" },
  // финальная дистанция
  { t: 21.0, p: at(CHUDAN, B_F), e: "lin" },
  { t: 22.55, p: at(CHUDAN, B_F, { spine: [12, -8, 0] }), e: "io" },
  { t: 22.92, p: at(LUNGE_WIND, { ...B_F, x: B_F.x + (B_END.x - B_F.x) * 0.18 }), e: "in", gait: true },
  { t: 23.22, p: at(LUNGE_CUT, { ...B_F, x: B_F.x + (B_END.x - B_F.x) * 0.62 }), e: "lin", gait: true },
  { t: 23.62, p: at(LUNGE_END, B_END), e: "out", gait: true },
  { t: 27.05, p: at(LUNGE_END, B_END, { spine: [17, -22, 0] }), e: "io" },
  // клинок падает, колено
  { t: 27.3, p: at(LUNGE_END, B_END, { spine: [24, -18, 6], head: [10, 10, 0], rh: 0, lh: 0, rf: [-0.3, 0.9, 0.3], lf: [0.25, 1.0, 0.2] }), e: "io" },
  {
    t: 28.2,
    p: at(LUNGE_END, B_END, {
      hipY: 0.5, spine: [32, -6, 4], head: [30, 4, 0], fl: [0.16, 0, -0.42], fr: [-0.16, 0, 0.34],
      rh: 0, lh: 0, rf: [-0.24, 0.62, 0.32], lf: [0.2, 0.72, 0.38],
    }),
    e: "io",
  },
  {
    t: 30,
    p: at(LUNGE_END, B_END, {
      hipY: 0.49, spine: [36, -6, 4], head: [34, 4, 0], fl: [0.16, 0, -0.42], fr: [-0.16, 0, 0.34],
      rh: 0, lh: 0, rf: [-0.24, 0.6, 0.33], lf: [0.2, 0.7, 0.38],
    }),
    e: "io",
  },
];

export const B_DROP_T = 27.3; // видео-время, когда меч B выскальзывает

const EASE: Record<Ease, (u: number) => number> = {
  io: smooth,
  in: easeIn,
  out: easeOut,
  lin: (u) => u,
  hold: () => 0,
};

function evalKeys(keys: Key[], t: number): Pose {
  if (t <= keys[0].t) return keys[0].p;
  for (let i = 0; i < keys.length - 1; i++) {
    const k0 = keys[i];
    const k1 = keys[i + 1];
    if (t <= k1.t) {
      const s0 = sceneTime(k0.t);
      const s1 = sceneTime(k1.t);
      const u = clamp((sceneTime(t) - s0) / Math.max(1e-6, s1 - s0));
      const e = EASE[k1.e ?? "io"](u);
      const p = mix(k0.p as any, k1.p as any, e) as Pose;
      p.sd = norm(p.sd);
      if (k1.gait) applyGait(p, k0.p, k1.p, e);
      return p;
    }
  }
  return keys[keys.length - 1].p;
}

// простая походка: стопы попеременно выносятся вперёд и поднимаются
function applyGait(p: Pose, a: Pose, b: Pose, u: number) {
  const dist = Math.hypot(b.x - a.x, b.z - a.z);
  if (dist < 0.25) return;
  const steps = Math.max(1, Math.round(dist / 0.6));
  const ph = u * steps * Math.PI;
  const lift = Math.abs(Math.sin(ph)) * 0.1 * Math.min(1, dist);
  const swing = Math.cos(ph) * 0.22;
  const leftLeads = Math.floor(u * steps) % 2 === 0;
  const fl: V3 = [...p.fl];
  const fr: V3 = [...p.fr];
  if (leftLeads) {
    fl[1] += lift;
    fl[2] += -swing;
  } else {
    fr[1] += lift;
    fr[2] += -swing;
  }
  p.fl = fl;
  p.fr = fr;
  p.hipY -= lift * 0.3;
}

export const choreo = {
  A: (t: number) => evalKeys(A_KEYS, t),
  B: (t: number) => evalKeys(B_KEYS, t),
  aKeys: A_KEYS,
  bKeys: B_KEYS,
  gripAim,
};

export { smoother };
