import {Easing, interpolate, random} from 'remotion';
import {noise2D} from '@remotion/noise';

export const W = 1080;
export const H = 1920;

/** Безопасная зона Shorts/Reels. */
export const SAFE = {top: 150, bottom: 250, side: 60};

export const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** Плавный прогресс 0→1 между кадрами a и b. */
export const prog = (frame: number, a: number, b: number, ease = Easing.inOut(Easing.cubic)) =>
  interpolate(frame, [a, b], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: ease,
  });

/** Детерминированный «шум» в диапазоне −1..1. */
export const n1 = (seed: string | number, t: number) => noise2D(seed, t, 0);

/** Мерцание света: 1 ± amount. */
export const flicker = (frame: number, seed: string, amount = 0.15, speed = 0.35) =>
  1 + n1(seed, frame * speed) * amount + (random(`${seed}-${frame}`) - 0.5) * amount * 0.6;

/** Тряска камеры: затухающий шум после кадра start. */
export const shake = (frame: number, start: number, strength = 40, decay = 25) => {
  if (frame < start) return {x: 0, y: 0, r: 0};
  const t = frame - start;
  const k = strength * Math.exp(-t / decay);
  return {
    x: n1('shake-x', t * 0.9) * k,
    y: n1('shake-y', t * 0.9) * k,
    r: n1('shake-r', t * 0.6) * k * 0.02,
  };
};

export const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/** Смешивание hex-цветов. */
export const mixColor = (a: string, b: string, t: number) => {
  const pa = parseInt(a.slice(1), 16);
  const pb = parseInt(b.slice(1), 16);
  const ch = (p: number, s: number) => (p >> s) & 255;
  const c = [16, 8, 0].map((s) => Math.round(mix(ch(pa, s), ch(pb, s), clamp01(t))));
  return `#${c.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
};
