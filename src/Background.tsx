import React from 'react';
import {AbsoluteFill, interpolate, random, useCurrentFrame} from 'remotion';
import {COLORS, FPS, H, W} from './theme';

/** Static-ish forest backdrop: gradient, light rays, fog, fireflies, leaves. */
export const Background: React.FC<{warmth: number}> = ({warmth}) => {
  const frame = useCurrentFrame();
  const t = frame / FPS;
  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, ${COLORS.bgTop} 0%, ${COLORS.bgBottom} 100%)`}}>
      <Warmth amount={warmth} t={t} />
      <LightRays t={t} />
      <TreeLine />
      <Fog t={t} />
      <Leaves t={t} />
      <Fireflies t={t} />
      {/* soft vignette */}
      <AbsoluteFill
        style={{background: 'radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.45) 100%)'}}
      />
    </AbsoluteFill>
  );
};

const Warmth: React.FC<{amount: number; t: number}> = ({amount, t}) => {
  if (amount <= 0.001) return null;
  const flicker = 0.92 + 0.08 * Math.sin(t * 7.3) * Math.sin(t * 3.1 + 1);
  return (
    <AbsoluteFill
      style={{
        opacity: amount * flicker,
        background:
          'radial-gradient(ellipse 85% 60% at 50% 62%, rgba(255,140,50,0.42) 0%, rgba(255,120,40,0.16) 45%, rgba(60,30,10,0) 80%), linear-gradient(180deg, rgba(40,25,10,0) 0%, rgba(90,45,15,0.35) 100%)',
      }}
    />
  );
};

const LightRays: React.FC<{t: number}> = ({t}) => {
  const rays = [
    {x: 180, w: 120, a: -14, o: 0.07, p: 0},
    {x: 420, w: 70, a: -10, o: 0.05, p: 1.7},
    {x: 600, w: 160, a: -7, o: 0.065, p: 3.1},
    {x: 860, w: 90, a: -3, o: 0.05, p: 4.4},
  ];
  return (
    <AbsoluteFill style={{mixBlendMode: 'screen'}}>
      {rays.map((r, i) => {
        const sway = Math.sin(t * 0.18 + r.p) * 2.2;
        const op = r.o * (0.65 + 0.35 * Math.sin(t * 0.35 + r.p * 2));
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: r.x,
              top: -200,
              width: r.w,
              height: 1700,
              transformOrigin: '50% 0%',
              transform: `rotate(${r.a + sway}deg)`,
              opacity: op,
              background: 'linear-gradient(180deg, rgba(255,246,214,1) 0%, rgba(255,240,200,0.5) 40%, rgba(255,240,200,0) 100%)',
              filter: 'blur(18px)',
              clipPath: 'polygon(35% 0, 65% 0, 100% 100%, 0 100%)',
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

/** Faint fir silhouettes at the bottom for depth. */
const TreeLine: React.FC = () => {
  const trees = Array.from({length: 11}, (_, i) => ({
    x: -40 + i * 110 + random(`tx${i}`) * 50,
    h: 380 + random(`th${i}`) * 300,
    w: 150 + random(`tw${i}`) * 70,
  }));
  return (
    <svg width={W} height={H} style={{position: 'absolute', inset: 0, opacity: 0.55}}>
      {trees.map((tr, i) => {
        const base = H + 10;
        const tiers = 4;
        const parts = [];
        for (let k = 0; k < tiers; k++) {
          const top = base - tr.h + (k * tr.h) / (tiers + 0.6);
          const bottom = top + tr.h / 2.2;
          const half = (tr.w / 2) * ((k + 1.4) / (tiers + 0.4));
          parts.push(`M${tr.x} ${top} L${tr.x + half} ${bottom} L${tr.x - half} ${bottom} Z`);
        }
        return <path key={i} d={parts.join(' ')} fill="#061510" />;
      })}
    </svg>
  );
};

const Fog: React.FC<{t: number}> = ({t}) => {
  const banks = [
    {y: 1250, w: 1400, h: 380, s: 9, o: 0.07, p: 0},
    {y: 1500, w: 1600, h: 420, s: -7, o: 0.09, p: 2},
    {y: 700, w: 1200, h: 300, s: 6, o: 0.045, p: 4},
    {y: 1720, w: 1800, h: 380, s: 5, o: 0.12, p: 1},
  ];
  return (
    <AbsoluteFill>
      {banks.map((b, i) => {
        const x = (W - b.w) / 2 + Math.sin(t * 0.004 * b.s + b.p) * 200;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x,
              top: b.y - b.h / 2,
              width: b.w,
              height: b.h,
              borderRadius: '50%',
              background: 'radial-gradient(ellipse at center, rgba(220,235,225,1) 0%, rgba(220,235,225,0) 70%)',
              opacity: b.o * (0.8 + 0.2 * Math.sin(t * 0.3 + b.p)),
              filter: 'blur(40px)',
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

const FIREFLIES = Array.from({length: 30}, (_, i) => ({
  x: random(`fx${i}`) * W,
  y: 150 + random(`fy${i}`) * (H - 250),
  r: 4 + random(`fr${i}`) * 5,
  ax: 30 + random(`fax${i}`) * 60,
  ay: 25 + random(`fay${i}`) * 50,
  sx: 0.12 + random(`fsx${i}`) * 0.2,
  sy: 0.1 + random(`fsy${i}`) * 0.18,
  p: random(`fp${i}`) * Math.PI * 2,
  blink: 0.6 + random(`fb${i}`) * 1.2,
}));

const Fireflies: React.FC<{t: number}> = ({t}) => (
  <AbsoluteFill style={{mixBlendMode: 'screen'}}>
    {FIREFLIES.map((f, i) => {
      const x = f.x + Math.sin(t * f.sx * 2 + f.p) * f.ax;
      const y = f.y + Math.cos(t * f.sy * 2 + f.p * 1.3) * f.ay - ((t * 6) % 40);
      const glow = 0.25 + 0.75 * Math.pow(0.5 + 0.5 * Math.sin(t * f.blink + f.p), 2);
      return (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: x - f.r * 5,
            top: y - f.r * 5,
            width: f.r * 10,
            height: f.r * 10,
            borderRadius: '50%',
            opacity: glow,
            background: `radial-gradient(circle, rgba(255,247,200,1) 0%, ${COLORS.firefly} 12%, rgba(255,200,80,0.35) 30%, rgba(255,190,70,0) 70%)`,
          }}
        />
      );
    })}
  </AbsoluteFill>
);

const LEAF_COLORS = ['#7a8b3a', '#a0702c', '#5f7a32', '#b5813a', '#6d5a28'];
const LEAVES = Array.from({length: 10}, (_, i) => ({
  x: random(`lx${i}`) * W,
  period: 14 + random(`lp${i}`) * 10,
  offset: random(`lo${i}`),
  size: 34 + random(`ls${i}`) * 26,
  sway: 50 + random(`lsw${i}`) * 80,
  spin: (random(`lsp${i}`) - 0.5) * 120,
  color: LEAF_COLORS[i % LEAF_COLORS.length],
}));

const Leaves: React.FC<{t: number}> = ({t}) => (
  <AbsoluteFill>
    {LEAVES.map((l, i) => {
      const prog = (t / l.period + l.offset) % 1;
      const y = interpolate(prog, [0, 1], [-120, H + 120]);
      const x = l.x + Math.sin(prog * Math.PI * 4 + i) * l.sway;
      const rot = l.spin * t + Math.sin(prog * Math.PI * 4 + i) * 35;
      const flip = Math.cos(t * 1.1 + i);
      return (
        <svg
          key={i}
          width={l.size}
          height={l.size}
          viewBox="0 0 40 40"
          style={{
            position: 'absolute',
            left: x,
            top: y,
            opacity: 0.55,
            transform: `rotate(${rot}deg) scaleX(${0.4 + 0.6 * Math.abs(flip)})`,
          }}
        >
          <path d="M20 2 C 34 10, 36 26, 20 38 C 4 26, 6 10, 20 2 Z" fill={l.color} />
          <path d="M20 4 L20 37" stroke="rgba(0,0,0,0.25)" strokeWidth={1.5} />
        </svg>
      );
    })}
  </AbsoluteFill>
);
