import * as THREE from "three";
import { range, smooth } from "./math";

// Цветокоррекция и "погода" по видео-времени.
export interface Look {
  dawn: number; // 0 ночь -> 1 рассвет
  freeze: number; // стоп-время
  fogDensity: number;
  exposure: number;
  saturation: number;
  contrast: number;
  grain: number;
  vignette: number;
  fade: number; // 0 — полностью чёрный
}

export function lookAt(t: number): Look {
  const dawn = smooth(range(t, 28.35, 30));
  const freeze = smooth(range(t, 23.55, 23.9)) * (1 - smooth(range(t, 26.6, 27.1)));
  const fadeIn = smooth(range(t, 0, 1.2));
  const fadeOut = 1 - smooth(range(t, 29.55, 30));
  return {
    dawn,
    freeze,
    fogDensity: 0.072 - dawn * 0.02 + freeze * 0.008 + (1 - smooth(range(t, 0, 2.5))) * 0.03,
    exposure: 1.0 + dawn * 0.25 - freeze * 0.05,
    saturation: 0.55 - freeze * 0.32 + dawn * 0.4,
    contrast: 1.08 + freeze * 0.1,
    grain: 0.055 + freeze * 0.035 - dawn * 0.01,
    vignette: 0.42 + freeze * 0.12,
    fade: fadeIn * fadeOut,
  };
}

const C = (h: string) => new THREE.Color(h);
const NIGHT = {
  fog: C("#1a2130"),
  zenith: C("#04060a"),
  horizon: C("#243043"),
  glow: C("#6f86ad"),
  disc: C("#d4e0f2"),
  light: C("#a9bcdc"),
  rim: C("#9fb4d8"),
  hemiSky: C("#2b3752"),
  motes: C("#8ea3c4"),
};
const DAWN = {
  fog: C("#5f5250"),
  zenith: C("#26324b"),
  horizon: C("#e39a68"),
  glow: C("#ffae6a"),
  disc: C("#fff0d0"),
  light: C("#ffb27a"),
  rim: C("#ffc08a"),
  hemiSky: C("#7a6a6a"),
  motes: C("#ffd2a8"),
};

export function palette(d: number) {
  const out: Record<keyof typeof NIGHT, THREE.Color> = {} as any;
  for (const k of Object.keys(NIGHT) as (keyof typeof NIGHT)[]) out[k] = NIGHT[k].clone().lerp(DAWN[k], d);
  return out;
}

export function lightDir(d: number) {
  const moon = new THREE.Vector3(0.82, 0.36, -0.44).normalize();
  const sun = new THREE.Vector3(0.97, 0.035 + d * 0.03, -0.22).normalize();
  return moon.lerp(sun, d).normalize();
}
