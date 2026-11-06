import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT} from '../lib/fonts';
import {SAFE} from '../lib/math';
import {isKeyword} from '../lib/timing';

export type TitleVariant = 'white' | 'yellow' | 'red' | 'ice';

const COLORS: Record<TitleVariant, {fill: string; glow: string}> = {
  white: {fill: '#ffffff', glow: 'rgba(255,255,255,0.35)'},
  yellow: {fill: '#FFD21F', glow: 'rgba(255,180,0,0.55)'},
  red: {fill: '#ff4a2e', glow: 'rgba(255,60,20,0.6)'},
  ice: {fill: '#dff1ff', glow: 'rgba(140,200,255,0.55)'},
};

/**
 * Заголовок на экране (верхняя часть кадра, в пределах безопасной зоны).
 * Появляется на кадре `at` (относительно сцены): «раскрытие» по буквам + разрядка.
 */
export const Title: React.FC<{
  text: string;
  at?: number;
  variant?: TitleVariant;
  size?: number;
  top?: number;
  sub?: string;
  out?: number;
  /** Подсвечивать ключевые слова жёлтым. */
  highlight?: boolean;
}> = ({text, at = 0, variant = 'white', size = 110, top = SAFE.top + 90, sub, out, highlight = true}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const f = frame - at;
  if (f < 0) return null;

  const s = spring({frame: f, fps, config: {damping: 18, stiffness: 120}});
  const fadeOut = out !== undefined ? interpolate(frame, [out - 10, out], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 1;
  const c = COLORS[variant];

  return (
    <div
      style={{
        position: 'absolute',
        left: SAFE.side,
        right: SAFE.side,
        top,
        textAlign: 'center',
        opacity: fadeOut,
        transform: `translateY(${interpolate(s, [0, 1], [-30, 0])}px)`,
      }}
    >
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: size,
          lineHeight: 1.05,
          color: c.fill,
          letterSpacing: `${interpolate(s, [0, 1], [0.25, 0.02])}em`,
          textShadow: `0 0 40px ${c.glow}, 0 8px 30px rgba(0,0,0,0.8)`,
          WebkitTextStroke: `${Math.round(size * 0.06)}px rgba(8,10,14,0.9)`,
          paintOrder: 'stroke fill',
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          columnGap: '0.28em',
        }}
      >
        {(() => {
          // разбиваем на слова, чтобы ключевые подсветить жёлтым; буквы появляются по очереди
          let n = 0;
          return text.split(' ').map((word, wi) => {
            const hl = highlight && isKeyword(word);
            const chars = [...word].map((ch) => {
              const i = n++;
              const o = interpolate(f, [i * 0.9, i * 0.9 + 6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
              return (
                <span key={i} style={{opacity: o, filter: `blur(${(1 - o) * 8}px)`}}>
                  {ch}
                </span>
              );
            });
            n++;
            return (
              <span key={wi} style={{display: 'inline-block', whiteSpace: 'nowrap', color: hl ? COLORS.yellow.fill : undefined}}>
                {chars}
              </span>
            );
          });
        })()}
      </div>
      {sub && (
        <div
          style={{
            marginTop: 24,
            fontFamily: FONT,
            fontWeight: 600,
            fontSize: size * 0.34,
            letterSpacing: '0.3em',
            color: 'rgba(230,236,245,0.85)',
            opacity: interpolate(f, [10, 25], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
            textShadow: '0 4px 16px rgba(0,0,0,0.8)',
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
};

/** Маленькая «плашка» эпизода (ПЕРВЫЕ СЕКУНДЫ / ПЕРВЫЙ ЧАС …). */
export const Chapter: React.FC<{text: string; index: number; at?: number}> = ({text, index, at = 4}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - at, fps, config: {damping: 20}});
  return (
    <div
      style={{
        position: 'absolute',
        top: SAFE.top + 20,
        left: 0,
        right: 0,
        display: 'flex',
        justifyContent: 'center',
        opacity: s,
        transform: `translateY(${(1 - s) * -20}px)`,
      }}
    >
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 38,
          letterSpacing: '0.32em',
          color: '#e9eef5',
          padding: '14px 30px 14px 38px',
          border: '2px solid rgba(233,238,245,0.55)',
          background: 'rgba(8,12,18,0.45)',
          backdropFilter: 'blur(6px)',
          textShadow: '0 2px 8px rgba(0,0,0,0.7)',
        }}
      >
        <span style={{color: '#ff6a3d', marginRight: 18}}>{String(index).padStart(2, '0')}</span>
        {text}
      </div>
    </div>
  );
};
