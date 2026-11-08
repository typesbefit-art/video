import {Easing, interpolate, spring} from 'remotion';
import finance from './data/finance.json';

export const FPS = 60;

export const C = {
  sky: '#8fd8ff',
  skyLight: '#d9f3ff',
  navy: '#1d2b53',
  ink: '#22223b',
  white: '#ffffff',
  yellow: '#ffd23f',
  orange: '#ff8c42',
  red: '#ff4f5e',
  green: '#2ec27e',
  greenDark: '#1a9a5f',
  blue: '#3a86ff',
  blueDark: '#2463c9',
  purple: '#8e6cff',
  pink: '#ff7eb6',
  skin: '#ffcfa3',
  skinShade: '#f2b183',
  hair: '#3d2b1f',
  grass: '#7ed957',
  // Max spends (orange hoodie), the twin saves (green hoodie)
  maxShirt: '#ff8c42',
  twinShirt: '#2ec27e',
};

export const FONT = 'Rubik, sans-serif';

/** Balance after `months` (can be fractional: linear between month ends). */
export const balanceAt = (months: number) => {
  const m = Math.max(0, Math.min(finance.months.length - 1, months));
  const a = Math.floor(m);
  const b = Math.min(finance.months.length - 1, a + 1);
  return finance.months[a] + (finance.months[b] - finance.months[a]) * (m - a);
};
export const contributedAt = (months: number) => Math.max(0, months) * finance.monthly;
export const year = (y: number) => finance.years[y];
export {finance};

export const money = (v: number) => '$' + Math.round(v).toLocaleString('en-US').replace(/,/g, ' ');

export const ease = Easing.bezier(0.33, 1, 0.68, 1);
export const lerp = (f: number, input: [number, number], output: [number, number], e = ease) =>
  interpolate(f, input, output, {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: e});

export const pop = (frame: number, delay = 0, damping = 12) =>
  spring({frame: frame - delay, fps: FPS, config: {damping, stiffness: 160, mass: 0.7}});

export const wobble = (frame: number, amp = 1, speed = 1) => Math.sin((frame / FPS) * Math.PI * 2 * speed) * amp;

export type SceneProps = {frame: number; dur: number; [k: string]: any};
