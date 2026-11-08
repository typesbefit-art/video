// Audio helpers: decode with ffmpeg, procedural SFX, mixing, WAV writing,
// and per-frame amplitude extraction for lip-sync.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';

export const SR = 48000;

export function decode(file) {
  const buf = execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-f', 'f32le', '-ac', '1', '-ar', String(SR), '-'], {
    maxBuffer: 1 << 30,
  });
  return new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4).slice();
}

export function writeWav(file, samples, channels = 1) {
  const n = samples.length;
  const buf = Buffer.alloc(44 + n * 2);
  buf.write('RIFF', 0);
  buf.writeUInt32LE(36 + n * 2, 4);
  buf.write('WAVE', 8);
  buf.write('fmt ', 12);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(channels, 22);
  buf.writeUInt32LE(SR, 24);
  buf.writeUInt32LE(SR * channels * 2, 28);
  buf.writeUInt16LE(channels * 2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write('data', 36);
  buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    buf.writeInt16LE(Math.round(v * 32767), 44 + i * 2);
  }
  fs.writeFileSync(file, buf);
}

const normalize = (a) => {
  let p = 0;
  for (const v of a) p = Math.max(p, Math.abs(v));
  if (p > 0) for (let i = 0; i < a.length; i++) a[i] /= p;
  return a;
};

// Deterministic PRNG so builds are reproducible.
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296) * 2 - 1;
}

// Whoosh: noise through a resonant band-pass whose centre sweeps up then down.
export function synthWhoosh(dur = 0.55) {
  const n = Math.floor(dur * SR);
  const out = new Float32Array(n);
  const rand = rng(7);
  let low = 0, band = 0;
  for (let i = 0; i < n; i++) {
    const x = i / n;
    const fc = 250 + 2600 * Math.sin(Math.PI * Math.pow(x, 0.8));
    const f = 2 * Math.sin((Math.PI * fc) / SR);
    const q = 0.35;
    const input = rand();
    low += f * band;
    const high = input - low - q * band;
    band += f * high;
    const env = Math.pow(Math.sin(Math.PI * Math.min(1, x * 1.15)), 1.6);
    out[i] = band * env;
  }
  return normalize(out);
}

// Coin "cha-ching": two bright metallic hits made of inharmonic partials.
export function synthCoin() {
  const dur = 0.9;
  const n = Math.floor(dur * SR);
  const out = new Float32Array(n);
  const partials = [
    [2093, 1.0, 9],
    [2637, 0.7, 11],
    [3520, 0.5, 14],
    [5274, 0.35, 18],
    [7040, 0.2, 24],
  ];
  const hit = (t0, amp) => {
    const s0 = Math.floor(t0 * SR);
    for (let i = s0; i < n; i++) {
      const t = (i - s0) / SR;
      let v = 0;
      for (const [f, a, d] of partials) v += a * Math.sin(2 * Math.PI * f * t) * Math.exp(-d * t);
      const attack = Math.min(1, t / 0.002);
      out[i] += amp * v * attack;
    }
  };
  hit(0, 0.8);
  hit(0.09, 1.0);
  return normalize(out);
}

export const dbToGain = (db) => Math.pow(10, db / 20);

export function mixInto(dst, src, atSec, gain = 1) {
  const off = Math.round(atSec * SR);
  for (let i = 0; i < src.length; i++) {
    const j = off + i;
    if (j < 0 || j >= dst.length) continue;
    dst[j] += src[i] * gain;
  }
}

// Soft limiter: transparent below -1 dBFS, tanh-style above.
export function softLimit(a, ceiling = dbToGain(-1)) {
  for (let i = 0; i < a.length; i++) {
    const v = a[i], av = Math.abs(v);
    if (av > ceiling) {
      const over = av - ceiling;
      a[i] = Math.sign(v) * (ceiling + (1 - ceiling) * Math.tanh(over / (1 - ceiling)));
    }
  }
  return a;
}

// Per-video-frame RMS envelope, normalised to ~0..1 for lip-sync.
export function amplitudeEnvelope(samples, fps, frames) {
  const hop = SR / fps;
  const win = Math.round(SR * 0.035);
  const env = new Array(frames).fill(0);
  for (let f = 0; f < frames; f++) {
    const c = Math.round(f * hop + hop / 2);
    let sum = 0, cnt = 0;
    for (let i = c - win; i < c + win; i++) {
      if (i < 0 || i >= samples.length) continue;
      sum += samples[i] * samples[i];
      cnt++;
    }
    env[f] = cnt ? Math.sqrt(sum / cnt) : 0;
  }
  const sorted = [...env].filter((v) => v > 0.005).sort((a, b) => a - b);
  const ref = sorted[Math.floor(sorted.length * 0.9)] || 1;
  return env.map((v) => {
    const x = Math.max(0, v / ref - 0.08);
    return Math.round(Math.min(1, x) * 100) / 100;
  });
}
