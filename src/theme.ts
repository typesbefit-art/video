import { continueRender, delayRender, interpolate, spring } from 'remotion';
import { measureText } from '@remotion/layout-utils';
import rubik900cy from '@fontsource/rubik/files/rubik-cyrillic-900-normal.woff2';
import rubik900la from '@fontsource/rubik/files/rubik-latin-900-normal.woff2';
import rubik700cy from '@fontsource/rubik/files/rubik-cyrillic-700-normal.woff2';
import rubik700la from '@fontsource/rubik/files/rubik-latin-700-normal.woff2';

export const FONT = 'Rubik';
export const INK = '#1d1830';
export const STROKE = 10;

export const C = {
  ink: INK,
  white: '#ffffff',
  cream: '#fff6e0',
  yellow: '#ffd23f',
  gold: '#ffc233',
  goldDark: '#e89a10',
  orange: '#ff8a3d',
  red: '#ff4d5e',
  pink: '#ff7eb6',
  purple: '#8b5cf6',
  blue: '#3da5ff',
  teal: '#2ec4b6',
  green: '#4cd964',
  skin: '#ffd1a6',
  skinShade: '#f5b78a',
};

// ---- font loading (blocks rendering until Rubik is ready) ----
let fontsReady = false;
if (typeof document !== 'undefined') {
  const handle = delayRender('Loading Rubik');
  const faces = [
    new FontFace(FONT, `url(${rubik900la})`, { weight: '900', unicodeRange: 'U+0000-00FF, U+2000-206F, U+20AC, U+2212' }),
    new FontFace(FONT, `url(${rubik900cy})`, { weight: '900', unicodeRange: 'U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116' }),
    new FontFace(FONT, `url(${rubik700la})`, { weight: '700', unicodeRange: 'U+0000-00FF, U+2000-206F, U+20AC, U+2212' }),
    new FontFace(FONT, `url(${rubik700cy})`, { weight: '700', unicodeRange: 'U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116' }),
  ];
  Promise.all(faces.map((f) => f.load()))
    .then((loaded) => {
      loaded.forEach((f) => document.fonts.add(f));
      fontsReady = true;
      continueRender(handle);
    })
    .catch((e) => {
      console.error(e);
      continueRender(handle);
    });
}

// Largest font size (≤ base) at which `text` fits into maxWidth on one line.
export function fitFontSize(text: string, maxWidth: number, base: number, weight = 900, letterSpacing = 0): number {
  if (!fontsReady && typeof document === 'undefined') return base;
  const { width } = measureText({ text, fontFamily: FONT, fontSize: base, fontWeight: String(weight), letterSpacing: `${letterSpacing}px` });
  return width > maxWidth ? Math.floor((base * maxWidth) / width) : base;
}

// ---- animation helpers ----
export const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
export const ease = (t: number) => t * t * (3 - 2 * t);
export const pop = (frame: number, fps: number, delay = 0, damping = 11) =>
  spring({ frame: frame - delay, fps, config: { damping, stiffness: 180, mass: 0.7 } });
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const range = (t: number, a: number, b: number) => interpolate(t, [a, b], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

// deterministic noise
export const hash = (n: number) => {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};

// Hop with squash & stretch. Returns lift (px) and scale factors anchored at the feet.
export function hop(t: number, period: number, height: number) {
  const p = (t / period) % 1;
  const air = Math.sin(Math.PI * p); // 0 on ground, 1 at apex
  const lift = air * height;
  // squash on contact, stretch while rising/falling fast
  const contact = Math.max(0, 1 - Math.min(p, 1 - p) / 0.12);
  const speed = Math.abs(Math.cos(Math.PI * p));
  const sy = 1 - 0.14 * contact + 0.08 * speed * (1 - contact);
  const sx = 1 / sy;
  return { lift, sx, sy };
}
