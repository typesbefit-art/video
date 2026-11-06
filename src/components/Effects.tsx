import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {H, W} from '../lib/math';

/** Плёночное зерно: шум перегенерируется каждый кадр (seed = кадр). */
export const FilmGrain: React.FC<{opacity?: number}> = ({opacity = 0.14}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{pointerEvents: 'none', mixBlendMode: 'overlay', opacity}}>
      <svg width={W} height={H}>
        <filter id="grain" x="0" y="0" width="100%" height="100%">
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={frame % 97} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
          <feComponentTransfer>
            <feFuncA type="linear" slope="1" />
          </feComponentTransfer>
        </filter>
        <rect width={W} height={H} filter="url(#grain)" />
      </svg>
    </AbsoluteFill>
  );
};

/** Виньетка. */
export const Vignette: React.FC<{strength?: number}> = ({strength = 0.75}) => (
  <AbsoluteFill
    style={{
      pointerEvents: 'none',
      background: `radial-gradient(ellipse 75% 60% at 50% 48%, rgba(0,0,0,0) 45%, rgba(0,0,0,${strength * 0.6}) 80%, rgba(0,0,0,${strength}) 100%)`,
    }}
  />
);

/**
 * Цветокоррекция: холодный серо-синий «look» — тонировка теней и лёгкая
 * усадка насыщенности. Применяется поверх всех слоёв сцены.
 */
export const ColorGrade: React.FC<{tint?: string; amount?: number; lift?: string}> = ({
  tint = '#2b4a6b',
  amount = 0.35,
  lift = '#0b1420',
}) => (
  <>
    <AbsoluteFill style={{pointerEvents: 'none', background: tint, mixBlendMode: 'soft-light', opacity: amount}} />
    <AbsoluteFill style={{pointerEvents: 'none', background: lift, mixBlendMode: 'lighten', opacity: 0.5}} />
  </>
);

/** Редкие царапины и пыль на плёнке. */
export const FilmScratches: React.FC = () => {
  const frame = useCurrentFrame();
  const lines = [0, 1, 2].map((i) => {
    const show = ((frame * 7 + i * 31) % 53) < 3;
    const x = ((frame * 131 + i * 397) % W);
    return show ? <line key={i} x1={x} y1={0} x2={x + 6} y2={H} stroke="#fff" strokeOpacity={0.08} strokeWidth={1.5} /> : null;
  });
  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <svg width={W} height={H}>{lines}</svg>
    </AbsoluteFill>
  );
};
