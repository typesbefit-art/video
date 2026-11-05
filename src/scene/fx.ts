import * as THREE from "three";
import { glowTexture } from "./env";
import { rng } from "./math";

export interface SparkBurst {
  s: number; // время сцены
  origin: THREE.Vector3;
  normal: THREE.Vector3; // основное направление разлёта
  count: number;
  power: number; // 0..1
  seed: number;
}

interface Spark {
  s0: number;
  p0: THREE.Vector3;
  v0: THREE.Vector3;
  life: number;
  w: number;
}

const G = -9.8;
const DRAG = 1.6;

// позиция с линейным сопротивлением воздуха: p = p0 + v0*(1-e^{-kt})/k + g*(t/k - (1-e^{-kt})/k^2)
function sparkPos(sp: Spark, dt: number, out: THREE.Vector3) {
  const e = Math.exp(-DRAG * dt);
  const a = (1 - e) / DRAG;
  out.copy(sp.p0).addScaledVector(sp.v0, a);
  out.y += G * (dt / DRAG - (1 - e) / (DRAG * DRAG));
  return out;
}

export class Sparks {
  sparks: Spark[] = [];
  bursts: SparkBurst[] = [];
  mesh: THREE.Mesh;
  geo: THREE.BufferGeometry;
  max: number;
  flash: THREE.Sprite;
  light: THREE.PointLight;

  constructor(bursts: SparkBurst[]) {
    this.bursts = bursts;
    for (const b of bursts) {
      const r = rng(b.seed);
      for (let i = 0; i < b.count; i++) {
        // разлёт: конус вокруг нормали + случайная сфера
        const rnd = new THREE.Vector3(r() - 0.5, r() - 0.5, r() - 0.5).normalize();
        const dir = b.normal.clone().multiplyScalar(r() < 0.5 ? 1 : -1).multiplyScalar(0.8).add(rnd).normalize();
        dir.y += 0.35;
        const speed = (1.5 + r() ** 1.5 * 7) * (0.5 + b.power * 0.7);
        this.sparks.push({
          s0: b.s + r() * 0.012,
          p0: b.origin.clone().add(rnd.clone().multiplyScalar(0.02)),
          v0: dir.normalize().multiplyScalar(speed),
          life: 0.18 + r() ** 2 * 0.75 * (0.6 + b.power * 0.5),
          w: 0.0035 + r() * 0.006,
        });
      }
    }
    this.max = this.sparks.length;
    this.geo = new THREE.BufferGeometry();
    this.geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(this.max * 4 * 3), 3));
    this.geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(this.max * 4 * 3), 3));
    this.geo.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(this.max * 4 * 2), 2));
    const idx: number[] = [];
    for (let i = 0; i < this.max; i++) {
      const b = i * 4;
      idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
    }
    this.geo.setIndex(idx);
    const mat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      vertexColors: true,
      vertexShader: `varying vec3 vC; varying vec2 vUv;
        void main(){ vC = color; vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
      fragmentShader: `varying vec3 vC; varying vec2 vUv;
        void main(){ float a = (1.0 - abs(vUv.y*2.0-1.0)); a = a*a; a *= smoothstep(0.0, 0.25, vUv.x); gl_FragColor = vec4(vC * a, 1.0); }`,
    });
    this.mesh = new THREE.Mesh(this.geo, mat);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 5;

    this.flash = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: glowTexture(), color: 0xffd9a0, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false }),
    );
    this.flash.renderOrder = 6;
    this.light = new THREE.PointLight(0xffc27a, 0, 7, 2);
  }

  /** возвращает силу текущей вспышки (0..1) для грейдинга */
  update(s: number, camera: THREE.Camera): number {
    const pos = this.geo.attributes.position.array as Float32Array;
    const col = this.geo.attributes.color.array as Float32Array;
    const uv = this.geo.attributes.uv.array as Float32Array;
    const camPos = camera.position;
    const head = new THREE.Vector3();
    const tail = new THREE.Vector3();
    const side = new THREE.Vector3();
    const toCam = new THREE.Vector3();
    let n = 0;
    for (const sp of this.sparks) {
      const dt = s - sp.s0;
      if (dt < 0 || dt > sp.life) continue;
      sparkPos(sp, dt, head);
      sparkPos(sp, Math.max(0, dt - 0.022), tail);
      if (head.distanceToSquared(tail) < 1e-8) tail.y -= 0.002;
      toCam.copy(camPos).sub(head);
      side.copy(head).sub(tail).cross(toCam).normalize();
      const age = dt / sp.life;
      const w = sp.w * (1 - age * 0.6);
      // белый -> жёлтый -> оранжевый -> тёмно-красный
      const heat = 1 - age;
      const r = 2.6 * heat + 0.4;
      const g = 2.2 * heat * heat + 0.12;
      const b = 1.6 * heat ** 4;
      const k = n * 12;
      const verts = [
        [tail, -1, 0],
        [head, -1, 1],
        [head, 1, 1],
        [tail, 1, 0],
      ] as const;
      verts.forEach(([p, sd, u], j) => {
        pos[k + j * 3] = p.x + side.x * w * sd;
        pos[k + j * 3 + 1] = p.y + side.y * w * sd;
        pos[k + j * 3 + 2] = p.z + side.z * w * sd;
        col[k + j * 3] = r;
        col[k + j * 3 + 1] = g;
        col[k + j * 3 + 2] = b;
        uv[n * 8 + j * 2] = u;
        uv[n * 8 + j * 2 + 1] = sd < 0 ? 0 : 1;
      });
      n++;
    }
    this.geo.setDrawRange(0, n * 6);
    this.geo.attributes.position.needsUpdate = true;
    this.geo.attributes.color.needsUpdate = true;
    this.geo.attributes.uv.needsUpdate = true;

    // вспышка — от ближайшего прошедшего удара
    let flash = 0;
    let at: THREE.Vector3 | null = null;
    for (const b of this.bursts) {
      const dt = s - b.s;
      if (dt < 0 || dt > 0.6) continue;
      const f = Math.exp(-dt / (0.035 + b.power * 0.04)) * b.power;
      if (f > flash) {
        flash = f;
        at = b.origin;
      }
    }
    if (at && flash > 0.002) {
      this.flash.visible = true;
      this.flash.position.copy(at);
      const sc = 0.12 + flash * 0.55;
      this.flash.scale.set(sc, sc, 1);
      (this.flash.material as THREE.SpriteMaterial).opacity = Math.min(1, flash * 0.9);
      this.light.position.copy(at);
      this.light.intensity = flash * 10;
    } else {
      this.flash.visible = false;
      this.light.intensity = 0;
    }
    return flash;
  }
}
