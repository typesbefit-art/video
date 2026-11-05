import * as THREE from "three";
import { rimMaterial } from "./materials";
import { DEG, V3 } from "./math";

// Локальная система бойца: +Z — вперёд, +Y — вверх, +X — его левая сторона (правая = -X).
export interface Pose {
  x: number;
  z: number;
  yaw: number; // градусы, 0 = смотрит в +Z мира
  hipY: number; // высота таза
  hipYaw: number;
  spine: V3; // наклон вперёд, поворот, крен (градусы)
  head: V3;
  fl: V3; // левая стопа (root-space)
  fr: V3; // правая стопа
  sp: V3; // точка хвата правой руки на рукояти (root-space)
  sd: V3; // направление клинка (к острию)
  se: V3; // подсказка направления режущей кромки
  rh: number; // правая рука на рукояти (0..1)
  lh: number; // левая рука на рукояти (0..1)
  rf: V3; // свободная цель правой руки
  lf: V3; // свободная цель левой руки
}

// ножны на левом бедре; меч в ножнах = та же поза
export const SAYA_MOUTH: V3 = [0.13, 0.97, 0.2];
export const SAYA_DIR: V3 = (() => {
  const d: V3 = [0.12, -0.3, -1];
  const l = Math.hypot(...d);
  return [d[0] / l, d[1] / l, d[2] / l];
})();
export const SHEATHED_GRIP: V3 = [
  SAYA_MOUTH[0] - SAYA_DIR[0] * 0.045,
  SAYA_MOUTH[1] - SAYA_DIR[1] * 0.045,
  SAYA_MOUTH[2] - SAYA_DIR[2] * 0.045,
];

const UPPER_ARM = 0.3;
const FOREARM = 0.31; // до центра хвата
const THIGH = 0.44;
const SHIN = 0.44;
const ANKLE = 0.075;
export const BLADE_LEN = 0.74;
const DOWN = new THREE.Vector3(0, -1, 0);

const tmpQ = new THREE.Quaternion();
const tmpV = new THREE.Vector3();

function setBoneDir(bone: THREE.Object3D, dirWorld: THREE.Vector3) {
  const parent = bone.parent!;
  parent.getWorldQuaternion(tmpQ).invert();
  tmpV.copy(dirWorld).applyQuaternion(tmpQ).normalize();
  bone.quaternion.setFromUnitVectors(DOWN, tmpV);
  bone.updateMatrixWorld(true);
}

/** аналитический IK на две кости; возвращает фактическую точку кисти */
function solve2(
  upper: THREE.Object3D,
  lower: THREE.Object3D,
  a: number,
  b: number,
  target: THREE.Vector3,
  pole: THREE.Vector3,
): THREE.Vector3 {
  const S = upper.getWorldPosition(new THREE.Vector3());
  const toT = target.clone().sub(S);
  const dist = toT.length();
  const d = Math.min(Math.max(dist, 0.05), a + b - 1e-3);
  const dir = toT.normalize();
  const cosA = (a * a + d * d - b * b) / (2 * a * d);
  const sinA = Math.sqrt(Math.max(0, 1 - cosA * cosA));
  const perp = pole.clone().sub(dir.clone().multiplyScalar(pole.dot(dir)));
  if (perp.lengthSq() < 1e-8) perp.set(0, -1, 0);
  perp.normalize();
  const E = S.clone()
    .add(dir.clone().multiplyScalar(a * cosA))
    .add(perp.multiplyScalar(a * sinA));
  const H = S.clone().add(dir.clone().multiplyScalar(d));
  setBoneDir(upper, E.clone().sub(S).normalize());
  setBoneDir(lower, H.clone().sub(E).normalize());
  return H;
}

function mesh(g: THREE.BufferGeometry, m: THREE.Material, p?: V3, r?: V3, s?: V3) {
  const o = new THREE.Mesh(g, m);
  if (p) o.position.set(...p);
  if (r) o.rotation.set(r[0] * DEG, r[1] * DEG, r[2] * DEG);
  if (s) o.scale.set(...s);
  return o;
}

/** изогнутый клинок: остриё по +Y, режущая кромка по +Z */
function bladeGeometry() {
  const N = 24;
  const pos: number[] = [];
  const idx: number[] = [];
  for (let i = 0; i <= N; i++) {
    const u = i / N;
    const y = 0.035 + u * BLADE_LEN;
    const sori = -0.03 * u * u; // изгиб к обуху
    const w = (0.032 - 0.008 * u) * (u > 0.93 ? Math.max(0.02, (1 - u) / 0.07) : 1);
    const th = 0.0075 * (1 - 0.4 * u);
    const tipLift = u > 0.93 ? -0.012 * ((u - 0.93) / 0.07) : 0;
    // кромка, две грани обуха
    pos.push(0, y, sori + w * 0.5 + tipLift);
    pos.push(th, y, sori - w * 0.5);
    pos.push(-th, y, sori - w * 0.5);
  }
  for (let i = 0; i < N; i++) {
    const a = i * 3;
    const b = (i + 1) * 3;
    for (let k = 0; k < 3; k++) {
      const k2 = (k + 1) % 3;
      idx.push(a + k, b + k, b + k2, a + k, b + k2, a + k2);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

export interface FighterLook {
  armor: string; // основной цвет доспеха
  rim: string; // цвет контура
  cloth: string;
  crest: "horns" | "moon";
}

export class Fighter {
  root = new THREE.Group();
  hips = new THREE.Group();
  spine = new THREE.Group();
  neck = new THREE.Group();
  armL = new THREE.Group();
  armR = new THREE.Group();
  foreL = new THREE.Group();
  foreR = new THREE.Group();
  thighL = new THREE.Group();
  thighR = new THREE.Group();
  shinL = new THREE.Group();
  shinR = new THREE.Group();
  footL = new THREE.Group();
  footR = new THREE.Group();
  sword = new THREE.Group();
  blade: THREE.Mesh;
  ribbons: THREE.Mesh[] = [];
  bladeMat: THREE.MeshStandardMaterial;
  /** внешний оверрайд мировой трансформации меча (меч выпал из руки) */
  swordOverride: { pos: THREE.Vector3; quat: THREE.Quaternion } | null = null;

  constructor(look: FighterLook) {
    const armor = rimMaterial({ color: look.armor, rim: look.rim, roughness: 0.45, metalness: 0.35 });
    const lacquer = rimMaterial({ color: "#0b0b0d", rim: look.rim, roughness: 0.35, metalness: 0.3 });
    const cloth = rimMaterial({ color: look.cloth, rim: look.rim, roughness: 0.95, rimPow: 2.2, side: THREE.DoubleSide });
    const skin = rimMaterial({ color: "#1a1412", rim: "#8a7a70", roughness: 0.8 });
    const steel = rimMaterial({ color: "#9aa3ad", rim: "#dfe8f5", roughness: 0.18, metalness: 1.0, rimPow: 2.0 });
    this.bladeMat = steel;

    const R = this.root;
    R.add(this.hips);

    // --- таз, кусадзури (юбка из пластин)
    this.hips.add(mesh(new THREE.CylinderGeometry(0.15, 0.17, 0.16, 12), cloth, [0, 0, 0]));
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2 + Math.PI / 6;
      const p = mesh(new THREE.BoxGeometry(0.17, 0.26, 0.022), armor);
      const piv = new THREE.Group();
      piv.rotation.y = a;
      p.position.set(0, -0.12, 0.17);
      p.rotation.x = 16 * DEG;
      piv.add(p);
      this.hips.add(piv);
    }

    // --- корпус
    this.spine.position.set(0, 0.06, 0);
    this.hips.add(this.spine);
    const doGeo = new THREE.CylinderGeometry(0.2, 0.165, 0.42, 14);
    this.spine.add(mesh(doGeo, armor, [0, 0.21, 0], undefined, [1, 1, 0.78]));
    // нагрудная пластина (выступ)
    this.spine.add(mesh(new THREE.BoxGeometry(0.3, 0.14, 0.06), armor, [0, 0.33, 0.12], [-12, 0, 0]));
    // воротник/плечевой пояс
    this.spine.add(mesh(new THREE.BoxGeometry(0.46, 0.06, 0.22), lacquer, [0, 0.41, 0]));

    // --- шея и голова
    this.neck.position.set(0, 0.44, 0);
    this.spine.add(this.neck);
    this.neck.add(mesh(new THREE.CylinderGeometry(0.045, 0.05, 0.08, 8), skin, [0, 0.04, 0]));
    const head = new THREE.Group();
    head.position.set(0, 0.17, 0.0);
    this.neck.add(head);
    head.add(mesh(new THREE.SphereGeometry(0.095, 14, 10), skin, [0, -0.01, 0.01]));
    // кабуто
    head.add(mesh(new THREE.SphereGeometry(0.125, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2), armor, [0, 0.015, 0]));
    // сикоро — расширяющийся назатыльник
    head.add(
      mesh(new THREE.CylinderGeometry(0.13, 0.21, 0.11, 18, 1, true, Math.PI * 0.25, Math.PI * 1.5), armor, [0, -0.03, -0.01], [0, 180, 0]),
    );
    // козырёк
    head.add(mesh(new THREE.CylinderGeometry(0.13, 0.15, 0.015, 16, 1, false, -Math.PI * 0.45, Math.PI * 0.9), lacquer, [0, 0.02, 0.01]));
    // мэмпо (маска)
    head.add(mesh(new THREE.BoxGeometry(0.12, 0.07, 0.05), lacquer, [0, -0.06, 0.085], [10, 0, 0]));
    // блики глаз в тени шлема
    const eyeMat = new THREE.MeshBasicMaterial({ color: "#aab4c2" });
    for (const sx of [-1, 1]) head.add(mesh(new THREE.SphereGeometry(0.0055, 6, 4), eyeMat, [sx * 0.034, 0.0, 0.09]));
    // навершие
    if (look.crest === "horns") {
      for (const s of [-1, 1]) {
        head.add(mesh(new THREE.BoxGeometry(0.018, 0.26, 0.008), steel, [s * 0.05, 0.16, 0.12], [-12, 0, -s * 24]));
      }
    } else {
      const moon = mesh(new THREE.TorusGeometry(0.12, 0.009, 6, 24, Math.PI), steel, [0, 0.08, 0.13]);
      head.add(moon);
    }
    // ленты, развевающиеся на ветру (вершины анимируются)
    for (const s of [-1, 1]) {
      const g = new THREE.PlaneGeometry(0.035, 0.55, 1, 10);
      g.translate(0, -0.275, 0);
      const rib = mesh(g, cloth, [s * 0.04, 0.0, -0.11]);
      rib.userData.base = (g.attributes.position.array as Float32Array).slice();
      rib.userData.seed = s;
      head.add(rib);
      this.ribbons.push(rib);
    }

    // --- руки
    for (const [arm, fore, side] of [
      [this.armL, this.foreL, 1],
      [this.armR, this.foreR, -1],
    ] as const) {
      arm.position.set(side * 0.2, 0.37, 0);
      this.spine.add(arm);
      arm.add(mesh(new THREE.CapsuleGeometry(0.052, UPPER_ARM - 0.1, 4, 8), cloth, [0, -UPPER_ARM / 2, 0]));
      // содэ — наплечник
      arm.add(mesh(new THREE.BoxGeometry(0.03, 0.22, 0.2), armor, [side * 0.07, -0.1, 0], [0, 0, side * 10]));
      fore.position.set(0, -UPPER_ARM, 0);
      arm.add(fore);
      fore.add(mesh(new THREE.CapsuleGeometry(0.043, FOREARM - 0.12, 4, 8), armor, [0, -FOREARM / 2 + 0.02, 0]));
      fore.add(mesh(new THREE.BoxGeometry(0.06, 0.08, 0.075), lacquer, [0, -FOREARM + 0.02, 0]));
    }

    // --- ноги (широкие хакама + сунэатэ)
    for (const [thigh, shin, foot, side] of [
      [this.thighL, this.shinL, this.footL, 1],
      [this.thighR, this.shinR, this.footR, -1],
    ] as const) {
      thigh.position.set(side * 0.1, -0.05, 0);
      this.hips.add(thigh);
      thigh.add(mesh(new THREE.CylinderGeometry(0.1, 0.16, THIGH + 0.04, 10), cloth, [0, -THIGH / 2, 0]));
      shin.position.set(0, -THIGH, 0);
      thigh.add(shin);
      shin.add(mesh(new THREE.CylinderGeometry(0.13, 0.08, 0.18, 10), cloth, [0, -0.05, 0]));
      shin.add(mesh(new THREE.CylinderGeometry(0.055, 0.045, SHIN - 0.06, 8), armor, [0, -SHIN / 2 - 0.02, 0]));
      R.add(foot);
      foot.add(mesh(new THREE.BoxGeometry(0.1, 0.06, 0.24), lacquer, [0, 0.03, 0.05]));
    }

    // --- ножны (в root-space)
    const saya = new THREE.Group();
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(...SAYA_DIR));
    saya.quaternion.copy(q);
    saya.position.set(...SAYA_MOUTH);
    saya.add(mesh(new THREE.BoxGeometry(0.026, 0.79, 0.042), lacquer, [0, 0.39, -0.008]));
    R.add(saya);

    // --- меч (в мировых координатах; начало — точка хвата правой руки)
    this.blade = mesh(bladeGeometry(), steel);
    this.sword.add(this.blade);
    this.sword.add(mesh(new THREE.CylinderGeometry(0.042, 0.042, 0.008, 16), lacquer, [0, 0.03, 0]));
    this.sword.add(mesh(new THREE.BoxGeometry(0.026, 0.27, 0.034), lacquer, [0, -0.1, 0]));
  }

  /** отрезок клинка в мире (от цубы до острия) */
  bladeSegment(): [THREE.Vector3, THREE.Vector3] {
    const a = this.sword.localToWorld(new THREE.Vector3(0, 0.04, 0));
    const b = this.sword.localToWorld(new THREE.Vector3(0, 0.035 + BLADE_LEN, -0.03));
    return [a, b];
  }

  headWorld(): THREE.Vector3 {
    return this.neck.localToWorld(new THREE.Vector3(0, 0.17, 0.02));
  }

  chestWorld(): THREE.Vector3 {
    return this.spine.localToWorld(new THREE.Vector3(0, 0.28, 0.05));
  }

  shoulderWorld(side: 1 | -1): THREE.Vector3 {
    return (side === 1 ? this.armL : this.armR).localToWorld(new THREE.Vector3(side * 0.06, -0.08, 0));
  }

  apply(p: Pose, s: number) {
    const R = this.root;
    R.position.set(p.x, 0, p.z);
    R.rotation.set(0, p.yaw * DEG, 0);
    const breathe = Math.sin(s * 1.9) * 0.008;
    this.hips.position.set(0, p.hipY + breathe * 0.5, 0);
    this.hips.rotation.set(0, p.hipYaw * DEG, 0);
    this.spine.rotation.set((p.spine[0] + breathe * 40) * DEG, p.spine[1] * DEG, p.spine[2] * DEG, "YXZ");
    this.neck.rotation.set(p.head[0] * DEG, p.head[1] * DEG, p.head[2] * DEG, "YXZ");
    R.updateMatrixWorld(true);

    const toW = (v: V3) => R.localToWorld(new THREE.Vector3(...v));
    const dirW = (v: V3) => new THREE.Vector3(...v).applyQuaternion(R.quaternion).normalize();

    // ноги
    for (const [thigh, shin, foot, fp, side] of [
      [this.thighL, this.shinL, this.footL, p.fl, 1],
      [this.thighR, this.shinR, this.footR, p.fr, -1],
    ] as const) {
      const ankle = toW([fp[0], fp[1] + ANKLE, fp[2]]);
      solve2(thigh, shin, THIGH, SHIN, ankle, dirW([side * 0.25, 0, 1]));
      foot.position.set(fp[0], fp[1], fp[2]);
      foot.rotation.set(0, side * 10 * DEG, 0);
    }

    // правая рука и меч
    const grip = toW(p.sp);
    const freeR = toW(p.rf);
    const rTarget = freeR.clone().lerp(grip, p.rh);
    const hR = solve2(this.armR, this.foreR, UPPER_ARM, FOREARM, rTarget, dirW([-0.6, -1, -0.5]));

    if (this.swordOverride) {
      this.sword.position.copy(this.swordOverride.pos);
      this.sword.quaternion.copy(this.swordOverride.quat);
    } else {
      const pos = grip.clone().add(hR.clone().sub(rTarget).multiplyScalar(p.rh));
      const y = dirW(p.sd);
      let z = dirW(p.se);
      z.sub(y.clone().multiplyScalar(z.dot(y)));
      if (z.lengthSq() < 1e-6) z = new THREE.Vector3(0, 1, 0).cross(y);
      z.normalize();
      const x = new THREE.Vector3().crossVectors(y, z);
      const m = new THREE.Matrix4().makeBasis(x, y, z);
      this.sword.position.copy(pos);
      this.sword.quaternion.setFromRotationMatrix(m);
    }
    this.sword.updateMatrixWorld(true);

    // левая рука — на навершие рукояти
    const lGrip = this.sword.localToWorld(new THREE.Vector3(0, -0.19, 0));
    const lTarget = toW(p.lf).lerp(lGrip, this.swordOverride ? 0 : p.lh);
    solve2(this.armL, this.foreL, UPPER_ARM, FOREARM, lTarget, dirW([0.6, -1, -0.5]));

    // ленты
    for (const rib of this.ribbons) {
      const base = rib.userData.base as Float32Array;
      const arr = rib.geometry.attributes.position.array as Float32Array;
      const sd = rib.userData.seed as number;
      for (let i = 0; i < arr.length; i += 3) {
        const u = -base[i + 1] / 0.55;
        const w = Math.sin(s * 5.3 - u * 6 + sd) * 0.06 * u + Math.sin(s * 11.7 - u * 9) * 0.015 * u;
        arr[i] = base[i] + w * 0.4 * sd;
        arr[i + 1] = base[i + 1] * (1 - 0.35 * u);
        arr[i + 2] = base[i + 2] - u * u * 0.32 + w;
      }
      rib.geometry.attributes.position.needsUpdate = true;
      rib.geometry.computeVertexNormals();
    }
  }
}
