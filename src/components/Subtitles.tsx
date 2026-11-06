import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT} from '../lib/fonts';
import {SAFE, W} from '../lib/math';
import {getChunks} from '../lib/timing';

const YELLOW = '#FFD21F';
const STROKE = '#0a0d12';
const MAX_WIDTH = W - SAFE.side * 2 - 40;
/** Нижняя граница блока субтитров: безопасная зона 250px + запас под подписи площадки. */
export const SUBTITLE_BOTTOM = SAFE.bottom + 190;

/**
 * Субтитры в стиле Shorts: 2–4 слова, крупно, белым с тёмной обводкой.
 * Ключевые слова (ядерная, вспышка, голод, зима, десятилетия) — жёлтым.
 * Текущее слово слегка «подпрыгивает».
 */
export const Subtitles: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const chunks = useMemo(() => getChunks(), []);
  const t = frame / fps;

  const chunk = chunks.find((c) => t >= c.start && t < c.end);
  if (!chunk) return null;

  const startFrame = Math.round(chunk.start * fps);
  const pop = spring({frame: frame - startFrame, fps, config: {damping: 14, stiffness: 220, mass: 0.6}});
  const scale = interpolate(pop, [0, 1], [0.82, 1]);
  const y = interpolate(pop, [0, 1], [24, 0]);

  const longest = Math.max(...chunk.words.flatMap((w) => w.text.split(' ').map((p) => p.length)));
  const fontSize = Math.min(98, Math.floor(MAX_WIDTH / (longest * 0.8)));

  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <div
        style={{
          position: 'absolute',
          left: SAFE.side,
          right: SAFE.side,
          bottom: SUBTITLE_BOTTOM,
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          alignContent: 'flex-end',
          columnGap: fontSize * 0.42,
          rowGap: 0,
          transform: `translateY(${y}px) scale(${scale})`,
          transformOrigin: '50% 100%',
          opacity: pop,
        }}
      >
        {chunk.words.map((w, i) => {
          const active = t >= w.start && t < w.end + 0.05;
          const wf = Math.round(w.start * fps);
          const bump = active ? spring({frame: frame - wf, fps, config: {damping: 10, stiffness: 300}}) : 0;
          return (
            <span
              key={i}
              style={{
                fontFamily: FONT,
                fontWeight: 900,
                fontSize,
                lineHeight: 1.12,
                textTransform: 'uppercase',
                letterSpacing: '-0.01em',
                color: w.keyword ? YELLOW : '#ffffff',
                WebkitTextStroke: `${Math.round(fontSize * 0.13)}px ${STROKE}`,
                paintOrder: 'stroke fill',
                textShadow: `0 6px 18px rgba(0,0,0,0.65), 0 0 2px ${STROKE}`,
                display: 'inline-block',
                transform: `scale(${1 + bump * 0.06 - (active ? 0 : 0)})`,
                filter: w.keyword ? 'drop-shadow(0 0 18px rgba(255,190,0,0.35))' : undefined,
                whiteSpace: 'nowrap',
              }}
            >
              {w.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** Отладочная рамка безопасной зоны (включается в Studio: showSafeZone). */
export const SafeZoneOverlay: React.FC = () => (
  <AbsoluteFill style={{pointerEvents: 'none'}}>
    <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: SAFE.top, background: 'rgba(255,0,80,0.25)'}} />
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: SAFE.bottom, background: 'rgba(255,0,80,0.25)'}} />
    <div
      style={{
        position: 'absolute',
        left: SAFE.side,
        right: SAFE.side,
        top: SAFE.top,
        bottom: SAFE.bottom,
        border: '3px dashed rgba(0,255,160,0.8)',
      }}
    />
  </AbsoluteFill>
);
