import * as THREE from "three";
import { ShotCtx, applyCamera, shotIndex, SHOTS } from "./camera";
import { A_COUNTER_KEY, B_DROP_T, choreo } from "./choreo";
import { makeBridge, makeCloudSea, makeFogSprites, makeMotes, makeMountains, makeSky } from "./env";
import { Fighter } from "./fighter";
import { SparkBurst, Sparks } from "./fx";
import { Look, lightDir, lookAt, palette } from "./grade";
import { RIM } from "./materials";
import { V3, clamp } from "./math";
import { sceneTime } from "./time";

// ближайшие точки двух отрезков
function closestSegSeg(p1: THREE.Vector3, q1: THREE.Vector3, p2: THREE.Vector3, q2: THREE.Vector3) {
  const d1 = q1.clone().sub(p1);
  const d2 = q2.clone().sub(p2);
  const r = p1.clone().sub(p2);
  const a = d1.dot(d1);
  const e = d2.dot(d2);
  const f = d2.dot(r);
  const c = d1.dot(r);
  const b = d1.dot(d2);
  const den = a * e - b * b;
  let s = den > 1e-9 ? clamp((b * f - c * e) / den) : 0;
  let t = (b * s + f) / e;
  if (t < 0) {
    t = 0;
    s = clamp(-c / a);
  } else if (t > 1) {
    t = 1;
    s = clamp((b - c) / a);
  }
  const c1 = p1.clone().addScaledVector(d1, s);
  const c2 = p2.clone().addScaledVector(d2, t);
  return { c1, c2, dist: c1.distanceTo(c2) };
}

function closestSegPoint(p: THREE.Vector3, q: THREE.Vector3, x: THREE.Vector3) {
  const d = q.clone().sub(p);
  const s = clamp(x.clone().sub(p).dot(d) / d.dot(d));
  return p.clone().addScaledVector(d, s);
}

// столкновения: [видео-время, тип, сила, искр]
const CLASHES: [number, "clash" | "hit", number, number][] = [
  [9.2, "clash", 1.0, 260],
  [10.55, "clash", 0.6, 120],
  [11.1, "clash", 0.65, 130],
  [18.75, "hit", 0.9, 200],
];

export class World {
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(40, 1080 / 1920, 0.05, 900);
  A = new Fighter({ armor: "#24070a", rim: "#ff5a48", cloth: "#0e0506", crest: "horns" });
  B = new Fighter({ armor: "#081230", rim: "#5f8dff", cloth: "#05070e", crest: "moon" });
  sky = makeSky();
  mountains = makeMountains();
  fogSprites = makeFogSprites(26, 4);
  cloudSea = makeCloudSea();
  motes = makeMotes(1400);
  sparks: Sparks;
  fog = new THREE.FogExp2(0x1a2130, 0.05);
  moon = new THREE.DirectionalLight(0xa9bcdc, 2.2);
  hemi = new THREE.HemisphereLight(0x2b3752, 0x050507, 0.35);
  fill = new THREE.DirectionalLight(0x3a4660, 0.25);
  drop: { s0: number; pos: THREE.Vector3; quat: THREE.Quaternion; landS: number; landPos: THREE.Vector3; flatQ: THREE.Quaternion } | null = null;
  look: Look = lookAt(0);
  flash = 0;
  shotLight: THREE.Vector3[] = [];

  constructor() {
    const S = this.scene;
    S.fog = this.fog;
    S.add(this.sky.sky);
    for (const m of this.mountains) S.add(m.mesh);
    S.add(makeBridge());
    S.add(this.cloudSea.group, this.fogSprites.group, this.motes.pts);
    S.add(this.A.root, this.A.sword, this.B.root, this.B.sword);
    S.add(this.moon, this.moon.target, this.hemi, this.fill);
    this.moon.target.position.set(0, 0, 0);

    // контровой свет: для каждого плана источник — за героями, напротив камеры
    SHOTS.forEach((sh, i) => {
      const tm = (sh.t0 + sh.t1) / 2;
      this.poseAt(tm, false);
      applyCamera(this.camera, tm, this.ctx(), tm);
      const f = new THREE.Vector3();
      this.camera.getWorldDirection(f);
      f.y = 0;
      f.normalize().applyAxisAngle(new THREE.Vector3(0, 1, 0), (i % 2 ? -1 : 1) * 0.42);
      f.y = 0.42;
      this.shotLight[i] = f.normalize();
    });

    // контратака A точно в левое плечо B
    this.poseAt(18.75, false);
    const sh = this.B.shoulderWorld(1);
    const k = choreo.aKeys[A_COUNTER_KEY];
    const yaw = (k.p.yaw * Math.PI) / 180;
    const f = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw));
    const rgt = new THREE.Vector3(-Math.cos(yaw), 0, Math.sin(yaw));
    const grip = new THREE.Vector3(k.p.x, 1.48, k.p.z).addScaledVector(f, 0.44).addScaledVector(rgt, 0.12);
    const aim = sh.clone().addScaledVector(sh.clone().sub(grip).normalize(), 0.06);
    k.p = choreo.gripAim(k.p, grip.toArray() as V3, aim.toArray() as V3);

    // искры: считаем точку контакта по реальной геометрии клинков
    const bursts: SparkBurst[] = [];
    CLASHES.forEach(([t, type, power, count], i) => {
      this.poseAt(t, false);
      const [a0, a1] = this.A.bladeSegment();
      const [b0, b1] = this.B.bladeSegment();
      let origin: THREE.Vector3;
      if (type === "clash") origin = closestSegSeg(a0, a1, b0, b1).c1.lerp(closestSegSeg(a0, a1, b0, b1).c2, 0.5);
      else origin = closestSegPoint(a0, a1, this.B.shoulderWorld(1));
      const normal = new THREE.Vector3().crossVectors(a1.clone().sub(a0), b1.clone().sub(b0)).normalize();
      if (normal.lengthSq() < 0.1) normal.set(0, 0, 1);
      bursts.push({ s: sceneTime(t), origin, normal, count, power, seed: 100 + i * 31 });
    });
    // скрежет в клинче
    for (let t = 11.62, i = 0; t < 12.95; t += 0.065, i++) {
      this.poseAt(t, false);
      const [a0, a1] = this.A.bladeSegment();
      const [b0, b1] = this.B.bladeSegment();
      const c = closestSegSeg(a0, a1, b0, b1);
      bursts.push({ s: sceneTime(t), origin: c.c1.lerp(c.c2, 0.5), normal: new THREE.Vector3(0, 0.3, 1).normalize(), count: 7, power: 0.12, seed: 500 + i });
    }

    // падение меча B
    this.poseAt(B_DROP_T, false);
    const pos = this.B.sword.position.clone();
    const quat = this.B.sword.quaternion.clone();
    const h = pos.y - 0.025;
    const fall = Math.sqrt((2 * h) / 9.8);
    const s0 = sceneTime(B_DROP_T);
    const landPos = pos.clone().add(new THREE.Vector3(-0.15, 0, -0.25));
    landPos.y = 0.018;
    const flatQ = new THREE.Quaternion().setFromEuler(new THREE.Euler(Math.PI / 2, 0.6, Math.PI / 2 - 0.1));
    this.drop = { s0, pos, quat, landS: s0 + fall, landPos, flatQ };
    bursts.push({ s: s0 + fall, origin: landPos.clone().add(new THREE.Vector3(0, 0.02, 0)), normal: new THREE.Vector3(0, 1, 0), count: 18, power: 0.25, seed: 900 });

    this.sparks = new Sparks(bursts);
    S.add(this.sparks.mesh, this.sparks.flash, this.sparks.light);
  }

  /** только позы бойцов (без камеры/эффектов) */
  poseAt(t: number, withDrop = true) {
    const s = sceneTime(t);
    this.A.apply(choreo.A(t), s);
    this.B.swordOverride = null;
    if (withDrop && this.drop && t >= B_DROP_T) {
      const d = this.drop;
      const dt = s - d.s0;
      const fallT = d.landS - d.s0;
      const pos = new THREE.Vector3();
      const q = new THREE.Quaternion();
      if (s < d.landS) {
        const u = dt / fallT;
        pos.copy(d.pos).lerp(d.landPos, u);
        pos.y = d.pos.y - 0.5 * 9.8 * dt * dt;
        pos.y = Math.max(pos.y, d.landPos.y);
        q.copy(d.quat).slerp(d.flatQ, u * u);
      } else {
        const a = s - d.landS;
        pos.copy(d.landPos);
        pos.y += Math.abs(Math.sin(a * 22)) * 0.03 * Math.exp(-a * 9);
        q.copy(d.flatQ);
        q.multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, Math.sin(a * 30) * 0.05 * Math.exp(-a * 8))));
      }
      this.B.swordOverride = { pos, quat: q };
    }
    this.B.apply(choreo.B(t), s);
  }

  ctx(): ShotCtx {
    const yawOf = (f: Fighter) => (f.root.rotation.y * 180) / Math.PI;
    return {
      aRoot: this.A.root.position.clone(),
      bRoot: this.B.root.position.clone(),
      aYaw: yawOf(this.A),
      bYaw: yawOf(this.B),
      aHead: this.A.headWorld(),
      bHead: this.B.headWorld(),
      aChest: this.A.chestWorld(),
      bChest: this.B.chestWorld(),
    };
  }

  /** полное обновление мира на видео-время t; shotT — время, по которому выбирается план (для подкадров motion blur) */
  update(t: number, shotT = t) {
    const s = sceneTime(t);
    this.poseAt(t);
    applyCamera(this.camera, t, this.ctx(), shotT);

    const look = (this.look = lookAt(t));
    const pal = palette(look.dawn);
    const ld = this.shotLight[shotIndex(shotT)].clone().lerp(lightDir(1), look.dawn).normalize();

    this.fog.color.copy(pal.fog);
    this.fog.density = look.fogDensity;
    const su = this.sky.uniforms;
    su.uZenith.value.copy(pal.zenith);
    su.uHorizon.value.copy(pal.horizon);
    su.uGlow.value.copy(pal.glow).multiplyScalar(0.55 + look.dawn * 0.9);
    su.uLightDir.value.copy(ld);
    su.uGlowSize.value = 9 - look.dawn * 5.5;
    su.uDisc.value = 1.2 + look.dawn * 1.8;
    su.uDiscColor.value.copy(pal.disc);
    this.sky.sky.position.copy(this.camera.position);

    this.mountains.forEach((m) => {
      m.mat.color.copy(pal.horizon).lerp(pal.zenith, 0.55 - m.depth * 0.45).multiplyScalar(0.55 + m.depth * 0.35);
      m.mesh.position.set(this.camera.position.x, 0, this.camera.position.z);
    });

    this.moon.position.copy(ld).multiplyScalar(40);
    this.moon.color.copy(pal.light);
    this.moon.intensity = 0.9 + look.dawn * 1.6;
    this.hemi.color.copy(pal.hemiSky);
    this.hemi.intensity = 0.22 + look.dawn * 0.45;
    this.fill.position.copy(this.camera.position).add(new THREE.Vector3(0, 2, 0));

    // rim: цвет и направление на источник в координатах камеры
    RIM.uRimLight.value.copy(pal.rim).multiplyScalar(1.5 + look.dawn * 0.9);
    RIM.uLightDirV.value.copy(ld).transformDirection(this.camera.matrixWorldInverse);

    const fogCol = pal.fog.clone().lerp(pal.horizon, 0.45).multiplyScalar(1.25);
    this.fogSprites.update(s, fogCol, 1 + look.freeze * 0.3, this.camera.position);
    this.cloudSea.update(s, pal.fog.clone().lerp(pal.horizon, 0.5).multiplyScalar(1.4));
    this.motes.update(s);
    this.motes.mat.color.copy(pal.motes);

    // блеск клинков: сильнее в момент обнажения
    this.flash = this.sparks.update(s, this.camera);
    return look;
  }

  static shotOf(t: number) {
    const i = shotIndex(t);
    return SHOTS[i];
  }
}
