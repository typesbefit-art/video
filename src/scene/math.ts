import * as THREE from "three";

export type V3 = [number, number, number];

export const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a: number, b: number, u: number) => a + (b - a) * u;
export const smooth = (x: number) => {
  const u = clamp(x);
  return u * u * (3 - 2 * u);
};
export const smoother = (x: number) => {
  const u = clamp(x);
  return u * u * u * (u * (u * 6 - 15) + 10);
};
export const easeIn = (x: number) => clamp(x) ** 2.2;
export const easeOut = (x: number) => 1 - (1 - clamp(x)) ** 2.2;
export const range = (t: number, a: number, b: number) => clamp((t - a) / (b - a));
export const DEG = Math.PI / 180;

export function norm(v: V3): V3 {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
}

// детерминированный ГПСЧ
export function rng(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s ^= s << 13;
    s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    return s / 4294967296;
  };
}

// гладкий 1D-шум из суммы синусов (для ручной камеры, ветра)
export function wobble(t: number, seed: number): number {
  return (
    Math.sin(t * 1.7 + seed * 1.3) * 0.5 +
    Math.sin(t * 3.9 + seed * 2.1) * 0.3 +
    Math.sin(t * 8.3 + seed * 0.7) * 0.15 +
    Math.sin(t * 17.1 + seed * 3.3) * 0.08
  );
}

export const v3 = (a: V3) => new THREE.Vector3(a[0], a[1], a[2]);

// ключевые кадры для произвольных числовых структур
export type Num = number | Num[] | { [k: string]: Num };

export function mix<T extends Num>(a: T, b: T, u: number): T {
  if (typeof a === "number") return lerp(a, b as number, u) as T;
  if (Array.isArray(a)) return a.map((x, i) => mix(x, (b as Num[])[i], u)) as T;
  const out: Record<string, Num> = {};
  for (const k of Object.keys(a)) out[k] = mix((a as any)[k], (b as any)[k], u);
  return out as T;
}
