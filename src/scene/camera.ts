import * as THREE from "three";
import { DEG, V3, clamp, lerp, smooth, smoother, wobble } from "./math";

export interface ShotCtx {
  aRoot: THREE.Vector3;
  bRoot: THREE.Vector3;
  aYaw: number;
  bYaw: number;
  aHead: THREE.Vector3;
  bHead: THREE.Vector3;
  aChest: THREE.Vector3;
  bChest: THREE.Vector3;
}

export interface CamState {
  pos: THREE.Vector3;
  look: THREE.Vector3;
  fov: number;
  roll: number;
  hand: number; // амплитуда ручной камеры
  up?: THREE.Vector3;
}

type Shot = { t0: number; t1: number; f: (u: number, t: number, c: ShotCtx) => CamState };

const V = (a: V3) => new THREE.Vector3(...a);
const L = (a: V3, b: V3, u: number) => V(a).lerp(V(b), u);
const fwd = (yaw: number) => new THREE.Vector3(Math.sin(yaw * DEG), 0, Math.cos(yaw * DEG));
const left = (yaw: number) => new THREE.Vector3(Math.cos(yaw * DEG), 0, -Math.sin(yaw * DEG));
const cs = (pos: THREE.Vector3, look: THREE.Vector3, fov: number, hand = 0.15, roll = 0): CamState => ({ pos, look, fov, roll, hand });

const orbit = (c: THREE.Vector3, r: number, th: number, h: number) =>
  new THREE.Vector3(c.x + Math.cos(th * DEG) * r, h, c.z + Math.sin(th * DEG) * r);

export const SHOTS: Shot[] = [
  // 1. кран над мостом, проявление из тумана
  { t0: 0, t1: 2, f: (u) => cs(L([-13, 7.5, 3.5], [-9.0, 2.4, 0.9], smooth(u)), L([1, 0.2, 0], [2, 1.15, 0], smooth(u)), 44, 0.08) },
  // 2. общий план из-за спины A
  { t0: 2, t1: 4, f: (u) => cs(L([-6.0, 1.8, 0.42], [-5.6, 1.76, 0.38], u), V([2.5, 1.35, 0]), 38, 0.1) },
  // 3. рука A на рукояти
  {
    t0: 4, t1: 5,
    f: (u, t, c) => {
      const f = fwd(c.aYaw), l = left(c.aYaw);
      const p = c.aRoot.clone().addScaledVector(f, lerp(1.9, 1.6, smooth(u))).addScaledVector(l, 0.85).add(V([0, 1.2, 0]));
      return cs(p, c.aRoot.clone().addScaledVector(f, 0.15).addScaledVector(l, 0.1).add(V([0, 1.12, 0])), 34, 0.12);
    },
  },
  // 4. глаза B
  {
    t0: 5, t1: 6,
    f: (u, t, c) => {
      const f = fwd(c.bYaw), l = left(c.bYaw);
      const p = c.bHead.clone().addScaledVector(f, lerp(1.75, 1.5, u)).addScaledVector(l, 0.2).add(V([0, -0.12, 0]));
      return cs(p, c.bHead.clone().add(V([0, -0.1, 0])), 30, 0.06);
    },
  },
  // 5. обнажение — облёт A на 90°
  {
    t0: 6, t1: 7.5,
    f: (u, t, c) => {
      const th = lerp(-48, 42, smoother(u));
      const p = orbit(c.aRoot, 2.5, th, 1.35);
      return cs(p, c.aChest.clone().add(V([0.15, 0.05, 0])), 40, 0.25);
    },
  },
  // 6. рывок A, низкая камера внутри моста
  { t0: 7.5, t1: 8.5, f: (u, t, c) => cs(V([c.aRoot.x + 2.0, 0.45, 0.55]), V([c.aRoot.x, 1.15, 0]), 46, 0.7) },
  // 7. первый удар — сбоку, медленный наезд
  { t0: 8.5, t1: 10.0, f: (u) => cs(L([0.15, 1.55, 3.1], [0.25, 1.62, 2.35], smooth(u)), V([0.12, 1.55, 0]), 44, 0.3) },
  // 8. из-за плеча B
  { t0: 10.0, t1: 11.5, f: (u, t, c) => cs(V([c.bRoot.x + 1.05, 1.9, c.bRoot.z + 0.55]), c.aChest.clone().add(V([0, 0.1, 0])), 44, 0.55) },
  // 9. клинч — облёт 140°
  { t0: 11.5, t1: 13, f: (u) => cs(orbit(V([0, 0, 0]), 2.4, lerp(112, 248, smooth(u)), lerp(1.3, 1.75, u)), V([0, 1.55, 0]), 44, 0.3) },
  // 10. шаг в сторону — вдоль моста из-за A
  {
    t0: 13, t1: 14.5,
    f: (u, t, c) => {
      const mid = c.aRoot.clone().lerp(c.bRoot, 0.5);
      return cs(V([c.aRoot.x - lerp(2.0, 1.6, u), 1.65, -0.9]), V([mid.x + 0.6, 1.25, mid.z]), 46, 0.45);
    },
  },
  // 11. разворот — облёт навстречу вращению
  { t0: 14.5, t1: 16.05, f: (u, t, c) => cs(orbit(c.bRoot, 2.3, lerp(150, -40, smooth(u)), 1.55), c.bChest.clone(), 46, 0.4) },
  // 12. сталь у самого лица
  {
    t0: 16.05, t1: 18.0,
    f: (u, t, c) => {
      const f = fwd(c.aYaw);
      const l = left(c.aYaw);
      const p = c.aHead.clone().addScaledVector(f, 0.12).addScaledVector(l, lerp(1.3, 1.15, u)).add(V([0, 0.02, 0]));
      return cs(p, c.aHead.clone().addScaledVector(f, 0.1).add(V([0, 0.02, 0])), 38, 0.12);
    },
  },
  // 13. контратака, удар по плечу — по диагонали вдоль моста
  {
    t0: 18.0, t1: 19.5,
    f: (u, t, c) => {
      const mid = c.aRoot.clone().lerp(c.bRoot, 0.5);
      return cs(V([mid.x - 2.6, 1.5, -1.15]), V([mid.x + 0.3, 1.25, mid.z]), 44, 0.45);
    },
  },
  // 14. B поднимается — низкий ракурс
  {
    t0: 19.5, t1: 21,
    f: (u, t, c) => {
      const toA = c.aRoot.clone().sub(c.bRoot).setY(0).normalize();
      const side = new THREE.Vector3(-toA.z, 0, toA.x);
      const p = c.bRoot.clone().addScaledVector(toA, 1.35).addScaledVector(side, 0.85);
      p.y = lerp(0.3, 0.38, u);
      return cs(p, c.bChest.clone().add(V([0, 0.3, 0])), 42, 0.15);
    },
  },
  // 15. общий план перед выпадом — вдоль моста из-за A
  { t0: 21, t1: 22.5, f: (u) => cs(L([-6.4, 1.95, -1.0], [-5.8, 1.9, -0.9], u), V([1.5, 1.1, 0.1]), 40, 0.1) },
  // 16. выпад — сверху, мост вертикально в кадре, наезд
  { t0: 22.5, t1: 23.5, f: (u) => ({ ...cs(L([-0.55, 8.4, 0.9], [-0.3, 5.0, 0.7], smoother(u)), L([-0.55, 0.6, 0], [-0.3, 0.6, 0], smoother(u)), 60, 0.4), up: V([1, 0, 0]) }) },
  // 17. стоп-время — медленное вращение сверху
  {
    t0: 23.5, t1: 27,
    f: (u) => cs(L([7.6, 1.45, 1.15], [7.0, 1.5, 0.9], smooth(u)), V([-0.2, 1.0, 0.0]), lerp(30, 27, u), 0.05),
  },
  // 18. клинок падает
  { t0: 27, t1: 28.5, f: (u, t, c) => cs(L([-3.75, 0.95, 1.25], [-3.6, 0.88, 1.2], u), V([-2.0, 0.45, -0.1]), 44, 0.12) },
  // 19. рассвет — кран вверх и назад
  {
    t0: 28.5, t1: 30.01,
    f: (u) => cs(L([-3.8, 1.3, 1.1], [-7.0, 4.3, 1.3], smooth(u)), L([0.5, 1.1, 0], [6, 2.4, -1], smooth(u)), lerp(44, 48, u), 0.08),
  },
];

export function shotIndex(t: number) {
  for (let i = 0; i < SHOTS.length; i++) if (t < SHOTS[i].t1) return i;
  return SHOTS.length - 1;
}

/** события тряски (видео-время, сила) */
export const SHAKES: [number, number][] = [
  [9.2, 1.0],
  [10.55, 0.55],
  [11.1, 0.55],
  [11.6, 0.4],
  [18.75, 1.0],
  [23.2, 0.35],
  [27.9, 0.25],
];

export function applyCamera(cam: THREE.PerspectiveCamera, t: number, ctx: ShotCtx, shotT?: number) {
  const i = shotIndex(shotT ?? t);
  const sh = SHOTS[i];
  const u = clamp((t - sh.t0) / (sh.t1 - sh.t0));
  const st = sh.f(u, t, ctx);
  cam.position.copy(st.pos);
  cam.fov = st.fov;
  cam.updateProjectionMatrix();
  // низкая камера не должна оказываться за перилами (z = ±1.5)
  if (st.pos.y < 1.3) st.pos.z = clamp(st.pos.z, -1.3, 1.3);
  cam.position.copy(st.pos);
  if (st.up) cam.up.copy(st.up);
  else cam.up.set(0, 1, 0);
  cam.lookAt(st.look);
  // ручная камера + удары
  let kick = 0;
  for (const [te, a] of SHAKES) if (t >= te) kick += a * Math.exp(-(t - te) / 0.22);
  const amp = st.hand * 0.006 + kick * 0.018;
  const hf = kick * 0.012;
  cam.rotateX(wobble(t * 1.3, 1) * amp + Math.sin(t * 71) * hf);
  cam.rotateY(wobble(t * 1.1, 2) * amp + Math.sin(t * 63 + 1) * hf);
  cam.rotateZ(wobble(t * 0.9, 3) * amp * 0.6 + st.roll * DEG);
  cam.position.y += wobble(t * 1.7, 4) * amp * 0.25;
  cam.updateMatrixWorld(true);
  return i;
}
