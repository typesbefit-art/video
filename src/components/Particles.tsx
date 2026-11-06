import React, {useMemo} from 'react';
import {random, useCurrentFrame} from 'remotion';
import {H, W, n1} from '../lib/math';

export type ParticleKind = 'ash' | 'snow' | 'embers' | 'smoke' | 'dust' | 'debris';

type Props = {
  kind: ParticleKind;
  count?: number;
  seed?: string;
  /** Горизонтальный ветер, px/кадр. */
  wind?: number;
  /** Множитель скорости. */
  speed?: number;
  color?: string;
  opacity?: number;
  /** Область появления (по умолчанию весь кадр). */
  area?: {x: number; y: number; w: number; h: number};
  /** Кадр, с которого частицы начинают «жить» (для взрывных выбросов). */
  startFrame?: number;
};

type P = {x: number; y: number; size: number; v: number; phase: number; life: number};

const PRESETS: Record<ParticleKind, {size: [number, number]; v: [number, number]; color: string; dir: 1 | -1}> = {
  ash: {size: [2, 6], v: [0.6, 1.8], color: '#b9b4ad', dir: 1},
  snow: {size: [3, 9], v: [1.2, 3.2], color: '#eef3f8', dir: 1},
  embers: {size: [2, 6], v: [1.5, 4.5], color: '#ff8a2a', dir: -1},
  smoke: {size: [120, 320], v: [0.6, 1.6], color: '#3d4148', dir: -1},
  dust: {size: [1.5, 3.5], v: [0.15, 0.5], color: '#ffe2b8', dir: -1},
  debris: {size: [3, 10], v: [10, 26], color: '#1a1410', dir: 1},
};

/**
 * Частицы пепла, снега, искр, дыма и пыли. Полностью детерминированы
 * (random(seed)), поэтому рендер одинаков на любом кадре и машине.
 */
export const Particles: React.FC<Props> = ({
  kind,
  count = 60,
  seed = kind,
  wind = 0,
  speed = 1,
  color,
  opacity = 1,
  area = {x: -100, y: -100, w: W + 200, h: H + 200},
  startFrame = 0,
}) => {
  const frame = useCurrentFrame();
  const preset = PRESETS[kind];
  const fill = color ?? preset.color;

  const particles = useMemo<P[]>(
    () =>
      new Array(count).fill(0).map((_, i) => ({
        x: random(`${seed}-x-${i}`),
        y: random(`${seed}-y-${i}`),
        size: preset.size[0] + random(`${seed}-s-${i}`) * (preset.size[1] - preset.size[0]),
        v: preset.v[0] + random(`${seed}-v-${i}`) * (preset.v[1] - preset.v[0]),
        phase: random(`${seed}-p-${i}`) * Math.PI * 2,
        life: random(`${seed}-l-${i}`),
      })),
    [count, seed, preset],
  );

  const t = Math.max(0, frame - startFrame);
  const gradId = `pg-${seed}`;

  return (
    <g opacity={opacity}>
      <defs>
        <radialGradient id={gradId}>
          <stop offset="0%" stopColor={fill} stopOpacity={kind === 'smoke' ? 0.55 : 1} />
          <stop offset="60%" stopColor={fill} stopOpacity={kind === 'smoke' ? 0.25 : 0.6} />
          <stop offset="100%" stopColor={fill} stopOpacity={0} />
        </radialGradient>
      </defs>
      {particles.map((p, i) => {
        const travel = p.v * speed * t;
        let x: number;
        let y: number;
        let o = 1;
        let r = p.size;

        if (kind === 'debris') {
          // разлёт обломков от ударной волны — слева направо, с гравитацией
          x = area.x + p.x * area.w * 0.3 + travel * 1.6;
          y = area.y + p.y * area.h + 0.018 * t * t * (0.5 + p.life) - travel * 0.25;
          o = Math.max(0, 1 - t / (40 + p.life * 40));
        } else {
          const h = area.h;
          const baseY = area.y + p.y * h;
          y = preset.dir === 1
            ? area.y + ((baseY - area.y + travel) % h + h) % h
            : area.y + ((baseY - area.y - travel) % h + h) % h;
          const sway = kind === 'smoke' ? 40 : kind === 'snow' ? 18 : 10;
          x = area.x + ((p.x * area.w + wind * t + n1(`${seed}-w${i}`, t * 0.02 + p.phase) * sway) % area.w + area.w) % area.w;

          if (kind === 'embers') o = 0.5 + 0.5 * Math.sin(t * 0.3 + p.phase);
          if (kind === 'dust') o = 0.3 + 0.4 * (0.5 + 0.5 * Math.sin(t * 0.05 + p.phase));
          if (kind === 'smoke') {
            // клубы растут по мере подъёма
            const k = 1 - (y - area.y) / h;
            r = p.size * (0.6 + k * 0.9);
            o = Math.min(1, k * 3) * Math.min(1, (1 - k) * 4);
          }
          if (kind === 'ash' || kind === 'snow') {
            o = 0.55 + 0.45 * p.life;
          }
        }

        if (kind === 'smoke' || kind === 'embers' || kind === 'dust') {
          return <circle key={i} cx={x} cy={y} r={kind === 'smoke' ? r : r * 2.2} fill={`url(#${gradId})`} opacity={o} />;
        }
        if (kind === 'ash' || kind === 'debris') {
          const rot = (t * (p.phase - 3) * 2) % 360;
          return (
            <rect
              key={i}
              x={x - r / 2}
              y={y - r / 3}
              width={r}
              height={r * 0.6}
              fill={fill}
              opacity={o}
              transform={`rotate(${rot} ${x} ${y})`}
            />
          );
        }
        return <circle key={i} cx={x} cy={y} r={r / 2} fill={fill} opacity={o} />;
      })}
    </g>
  );
};
