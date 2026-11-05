import * as THREE from "three";
import { rimMaterial } from "./materials";
import { rng } from "./math";

// ---------- процедурная текстура тумана ----------
function valueNoise(size: number, seed: number, cells: number) {
  const r = rng(seed);
  const g = new Float32Array(cells * cells).map(() => r());
  const out = new Float32Array(size * size);
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      const fx = (x / size) * cells;
      const fy = (y / size) * cells;
      const x0 = Math.floor(fx);
      const y0 = Math.floor(fy);
      const tx = fx - x0;
      const ty = fy - y0;
      const sx = tx * tx * (3 - 2 * tx);
      const sy = ty * ty * (3 - 2 * ty);
      const at = (i: number, j: number) => g[((j % cells) * cells + (i % cells)) | 0];
      const a = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * sx;
      const b = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * sx;
      out[y * size + x] = a + (b - a) * sy;
    }
  return out;
}

export function fogTexture(seed: number, radial = true) {
  const S = 256;
  const oct = [4, 8, 16, 32].map((c, i) => valueNoise(S, seed + i * 17, c));
  const data = new Uint8Array(S * S * 4);
  for (let i = 0; i < S * S; i++) {
    const n = oct[0][i] * 0.5 + oct[1][i] * 0.27 + oct[2][i] * 0.15 + oct[3][i] * 0.08;
    const x = (i % S) / S - 0.5;
    const y = Math.floor(i / S) / S - 0.5;
    const r = radial ? Math.max(0, 1 - Math.hypot(x, y) * 2) : 1;
    const a = Math.max(0, n - 0.38) * 1.9 * r * r;
    data[i * 4] = data[i * 4 + 1] = data[i * 4 + 2] = 255;
    data[i * 4 + 3] = Math.min(255, a * 255);
  }
  const t = new THREE.DataTexture(data, S, S, THREE.RGBAFormat);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.magFilter = THREE.LinearFilter;
  t.minFilter = THREE.LinearFilter;
  t.needsUpdate = true;
  return t;
}

export function glowTexture() {
  const S = 128;
  const data = new Uint8Array(S * S * 4);
  for (let y = 0; y < S; y++)
    for (let x = 0; x < S; x++) {
      const d = Math.hypot(x / S - 0.5, y / S - 0.5) * 2;
      const a = Math.max(0, 1 - d) ** 2.5;
      const i = (y * S + x) * 4;
      data[i] = data[i + 1] = data[i + 2] = 255;
      data[i + 3] = a * 255;
    }
  const t = new THREE.DataTexture(data, S, S, THREE.RGBAFormat);
  t.magFilter = t.minFilter = THREE.LinearFilter;
  t.needsUpdate = true;
  return t;
}

// ---------- небо ----------
export function makeSky() {
  const uniforms = {
    uZenith: { value: new THREE.Color() },
    uHorizon: { value: new THREE.Color() },
    uGlow: { value: new THREE.Color() },
    uLightDir: { value: new THREE.Vector3(1, 0.3, 0) },
    uGlowSize: { value: 8.0 },
    uDisc: { value: 0.0 },
    uDiscColor: { value: new THREE.Color(1, 1, 1) },
  };
  const mat = new THREE.ShaderMaterial({
    uniforms,
    side: THREE.BackSide,
    depthWrite: false,
    fog: false,
    vertexShader: `varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); gl_Position.z = gl_Position.w; }`,
    fragmentShader: `
      uniform vec3 uZenith, uHorizon, uGlow, uLightDir, uDiscColor; uniform float uGlowSize, uDisc;
      varying vec3 vDir;
      void main(){
        vec3 d = normalize(vDir);
        float h = clamp(d.y, -0.2, 1.0);
        vec3 col = mix(uHorizon, uZenith, pow(clamp(h, 0.0, 1.0), 0.55));
        float c = max(dot(d, normalize(uLightDir)), 0.0);
        col += uGlow * (pow(c, uGlowSize) * 0.9 + pow(c, uGlowSize * 6.0) * 1.2);
        col += uDiscColor * smoothstep(0.99935, 0.99975, c) * uDisc;
        gl_FragColor = vec4(col, 1.0);
      }`,
  });
  const sky = new THREE.Mesh(new THREE.SphereGeometry(400, 32, 16), mat);
  sky.renderOrder = -10;
  return { sky, uniforms };
}

// ---------- горы: кольца силуэтов ----------
export function makeMountains() {
  const layers: { mesh: THREE.Mesh; mat: THREE.MeshBasicMaterial; depth: number }[] = [];
  const conf = [
    { R: 90, h: 16, seed: 3, depth: 0.25 },
    { R: 150, h: 30, seed: 9, depth: 0.5 },
    { R: 230, h: 48, seed: 21, depth: 0.75 },
  ];
  for (const c of conf) {
    const r = rng(c.seed);
    const N = 240;
    const ph = Array.from({ length: 6 }, () => r() * Math.PI * 2);
    const pos: number[] = [];
    const idx: number[] = [];
    for (let i = 0; i <= N; i++) {
      const a = (i / N) * Math.PI * 2;
      let hgt = 0;
      for (let k = 0; k < 6; k++) hgt += Math.abs(Math.sin(a * (2 + k * 3) + ph[k])) / (1 + k * 0.8);
      hgt = c.h * (0.25 + hgt * 0.35) + (r() - 0.5) * c.h * 0.05;
      const x = Math.cos(a) * c.R;
      const z = Math.sin(a) * c.R;
      pos.push(x, -60, z, x, hgt - 8, z);
      if (i < N) {
        const b = i * 2;
        idx.push(b, b + 2, b + 1, b + 1, b + 2, b + 3);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setIndex(idx);
    const mat = new THREE.MeshBasicMaterial({ color: 0x000000, fog: false, side: THREE.DoubleSide, depthWrite: false });
    const m = new THREE.Mesh(g, mat);
    m.renderOrder = -9 + c.depth;
    layers.push({ mesh: m, mat, depth: c.depth });
  }
  return layers;
}

// ---------- мост ----------
export function makeBridge() {
  const g = new THREE.Group();
  const wood = rimMaterial({ color: "#16120f", rim: "#4a5566", roughness: 0.9, rimPow: 4 });
  const woodDark = rimMaterial({ color: "#0d0b09", rim: "#3a4352", roughness: 0.9, rimPow: 4 });
  const L = 44;
  const r = rng(7);
  // доски поперёк моста
  const plankW = 0.26;
  const n = Math.floor(L / (plankW + 0.02));
  const planks = new THREE.InstancedMesh(new THREE.BoxGeometry(plankW, 0.06, 2.9), wood, n);
  const m4 = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  for (let i = 0; i < n; i++) {
    const x = -L / 2 + i * (plankW + 0.02);
    q.setFromEuler(new THREE.Euler((r() - 0.5) * 0.02, (r() - 0.5) * 0.03, (r() - 0.5) * 0.015));
    m4.compose(new THREE.Vector3(x, -0.03 + (r() - 0.5) * 0.012, (r() - 0.5) * 0.05), q, new THREE.Vector3(1, 1, 1));
    planks.setMatrixAt(i, m4);
  }
  g.add(planks);
  // продольные балки
  for (const z of [-1.25, 1.25]) {
    const b = new THREE.Mesh(new THREE.BoxGeometry(L, 0.22, 0.18), woodDark);
    b.position.set(0, -0.17, z);
    g.add(b);
  }
  // перила
  const posts = new THREE.InstancedMesh(new THREE.BoxGeometry(0.11, 1.1, 0.11), wood, Math.floor(L / 2.2) * 2 + 2);
  let k = 0;
  for (let x = -L / 2; x <= L / 2; x += 2.2)
    for (const z of [-1.5, 1.5]) {
      m4.compose(new THREE.Vector3(x, 0.5, z), new THREE.Quaternion(), new THREE.Vector3(1, 1, 1));
      posts.setMatrixAt(k++, m4);
    }
  posts.count = k;
  g.add(posts);
  for (const z of [-1.5, 1.5]) {
    const top = new THREE.Mesh(new THREE.BoxGeometry(L, 0.08, 0.13), wood);
    top.position.set(0, 1.06, z);
    g.add(top);
    const mid = new THREE.Mesh(new THREE.BoxGeometry(L, 0.05, 0.06), woodDark);
    mid.position.set(0, 0.55, z);
    g.add(mid);
  }
  // опоры, уходящие в пропасть
  for (const x of [-15.4, -6.6, 6.6, 15.4]) {
    for (const z of [-1.3, 1.3]) {
      const p = new THREE.Mesh(new THREE.BoxGeometry(0.3, 30, 0.3), woodDark);
      p.position.set(x, -15.3, z);
      g.add(p);
    }
    const cross = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, 3), woodDark);
    cross.position.set(x, -0.4, 0);
    g.add(cross);
  }
  // скалы по краям
  const rock = rimMaterial({ color: "#0a0b0d", rim: "#2a3240", roughness: 1, rimPow: 3 });
  for (const s of [-1, 1]) {
    for (let i = 0; i < 5; i++) {
      const c = new THREE.Mesh(new THREE.IcosahedronGeometry(4 + r() * 3, 0), rock);
      c.position.set(s * (24 + r() * 6), -3 - r() * 6, (r() - 0.5) * 10);
      c.scale.set(1.4, 2.2, 1.3);
      c.rotation.set(r() * 3, r() * 3, r() * 3);
      g.add(c);
    }
  }
  return g;
}

// ---------- клочья тумана (спрайты) ----------
export function makeFogSprites(count: number, seed: number) {
  // плотнее у настила моста
  const tex = fogTexture(11);
  const r = rng(seed);
  const items: { s: THREE.Sprite; base: THREE.Vector3; speed: number; size: number; op: number; rot: number }[] = [];
  const group = new THREE.Group();
  for (let i = 0; i < count; i++) {
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, fog: true, opacity: 0.2 });
    const s = new THREE.Sprite(mat);
    const base = new THREE.Vector3((r() - 0.5) * 34, -1.8 + r() ** 1.6 * 4.5, (r() - 0.5) * 24);
    const size = 5 + r() * 9;
    s.scale.set(size * 1.6, size, 1);
    mat.rotation = r() * Math.PI * 2;
    group.add(s);
    items.push({ s, base, speed: 0.3 + r() * 0.5, size, op: 0.16 + r() * 0.22, rot: (r() - 0.5) * 0.05 });
  }
  return {
    group,
    update(sc: number, color: THREE.Color, density: number, cam: THREE.Vector3) {
      for (const it of items) {
        let x = it.base.x + sc * it.speed;
        x = ((((x + 17) % 34) + 34) % 34) - 17;
        it.s.position.set(x, it.base.y + Math.sin(sc * 0.2 + it.base.z) * 0.2, it.base.z);
        const m = it.s.material as THREE.SpriteMaterial;
        m.color.copy(color);
        // гасим у краёв петли, чтобы не было скачков
        const edge = Math.min(1, (17 - Math.abs(x)) / 3);
        const dc = it.s.position.distanceTo(cam);
        const near = Math.min(1, Math.max(0, (dc - it.size * 0.7) / (it.size * 0.8)));
        m.opacity = it.op * density * edge * near;
        m.rotation += 0;
      }
    },
  };
}

// ---------- море облаков под мостом ----------
export function makeCloudSea() {
  const tex = fogTexture(5, false);
  tex.repeat.set(3, 3);
  const layers: { m: THREE.Mesh; mat: THREE.MeshBasicMaterial; k: number }[] = [];
  const group = new THREE.Group();
  [-3.5, -6, -9].forEach((y, k) => {
    const mat = new THREE.MeshBasicMaterial({ map: tex.clone(), transparent: true, depthWrite: false, opacity: 0.5, fog: true });
    mat.map!.repeat.set(3 + k, 3 + k);
    mat.map!.needsUpdate = true;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(160, 160), mat);
    m.rotation.x = -Math.PI / 2;
    m.position.y = y;
    group.add(m);
    layers.push({ m, mat, k });
  });
  return {
    group,
    update(sc: number, color: THREE.Color) {
      for (const l of layers) {
        l.mat.map!.offset.set(sc * 0.004 * (1 + l.k * 0.5), sc * 0.0015);
        l.mat.color.copy(color);
        l.mat.opacity = 0.55 - l.k * 0.12;
      }
    },
  };
}

// ---------- морось / частицы в воздухе ----------
export function makeMotes(count: number) {
  const r = rng(99);
  const base = new Float32Array(count * 3);
  const pos = new Float32Array(count * 3);
  const sp = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    base[i * 3] = (r() - 0.5) * 24;
    base[i * 3 + 1] = -1 + r() * 6;
    base[i * 3 + 2] = (r() - 0.5) * 14;
    sp[i] = 0.6 + r() * 0.8;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({
    size: 0.018,
    map: glowTexture(),
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    color: new THREE.Color("#8fa4c4"),
    opacity: 0.55,
    fog: true,
  });
  const pts = new THREE.Points(g, mat);
  pts.frustumCulled = false;
  return {
    pts,
    mat,
    update(sc: number) {
      for (let i = 0; i < count; i++) {
        const k = i * 3;
        let x = base[k] + sc * 1.6 * sp[i];
        x = ((((x + 12) % 24) + 24) % 24) - 12;
        let y = base[k + 1] - sc * 0.5 * sp[i];
        y = ((((y + 1) % 6) + 6) % 6) - 1;
        pos[k] = x;
        pos[k + 1] = y + Math.sin(sc * 1.3 + i) * 0.05;
        pos[k + 2] = base[k + 2] + Math.sin(sc * 0.7 + i * 0.37) * 0.15;
      }
      g.attributes.position.needsUpdate = true;
    },
  };
}
