import React, {useMemo} from 'react';
import {AbsoluteFill, random, useCurrentFrame} from 'remotion';
import {FREEZE_LEN, FREEZE_START, HEIGHT, WIDTH} from './constants';

const STAR_COUNT = 260;

// «Время звёзд»: во время заморозки стоит на месте, потом продолжает без скачка
const starTime = (frame: number) => {
  if (frame < FREEZE_START) return frame;
  if (frame < FREEZE_START + FREEZE_LEN) return FREEZE_START;
  return frame - FREEZE_LEN;
};

export const Starfield: React.FC = () => {
  const frame = useCurrentFrame();
  const t = starTime(frame);

  const stars = useMemo(
    () =>
      new Array(STAR_COUNT).fill(0).map((_, i) => {
        const depth = random(`d${i}`); // 0 — далеко, 1 — близко
        return {
          x: random(`x${i}`) * WIDTH,
          y: random(`y${i}`) * HEIGHT,
          size: 1.2 + depth * depth * 4.2,
          speed: 0.6 + depth * 2.6, // px за кадр — медленно вниз
          phase: random(`p${i}`) * Math.PI * 2,
          twinkle: 0.06 + random(`t${i}`) * 0.16,
          base: 0.35 + depth * 0.55,
          tint: random(`c${i}`) > 0.85 ? '#9FF6FF' : random(`c2${i}`) > 0.8 ? '#E6CCFF' : '#FFFFFF',
        };
      }),
    []
  );

  return (
    <AbsoluteFill>
      <svg width={WIDTH} height={HEIGHT} style={{position: 'absolute'}}>
        {stars.map((s, i) => {
          const y = (s.y + t * s.speed) % (HEIGHT + 20);
          const tw = 0.5 + 0.5 * Math.sin(t * s.twinkle + s.phase);
          const opacity = s.base * (0.35 + 0.65 * tw);
          return (
            <g key={i}>
              {s.size > 3.5 ? (
                <circle cx={s.x} cy={y} r={s.size * 2.6} fill={s.tint} opacity={opacity * 0.15} />
              ) : null}
              <circle cx={s.x} cy={y} r={s.size / 2} fill={s.tint} opacity={opacity} />
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
};
