import React from 'react';
import {interpolate, random} from 'remotion';
import {COLORS, FONT} from './theme';

type P = {t: number}; // seconds since scene start

const SIZE = 400;
const C = COLORS.cream;
const A = COLORS.accent;

const Svg: React.FC<{children: React.ReactNode; w?: number; h?: number}> = ({children, w = SIZE, h = SIZE}) => (
  <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{overflow: 'visible'}}>
    {children}
  </svg>
);

const draw = (t: number, delay: number, dur: number) =>
  interpolate(t, [delay, delay + dur], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

/** 1 — pause: ring + two bars, gently breathing. */
export const PauseIcon: React.FC<P> = ({t}) => {
  const breathe = 1 + 0.035 * Math.sin(t * 1.4);
  const ring = 2 * Math.PI * 150;
  return (
    <Svg>
      <g transform={`translate(200 200) scale(${breathe})`}>
        <circle r={175} fill="rgba(255,179,71,0.07)" />
        <circle
          r={150}
          fill="none"
          stroke={C}
          strokeWidth={14}
          strokeLinecap="round"
          strokeDasharray={ring}
          strokeDashoffset={ring * draw(t, 0.1, 1.1)}
          transform="rotate(-90)"
        />
        <rect x={-62} y={-72} width={40} height={144} rx={14} fill={A} />
        <rect x={22} y={-72} width={40} height={144} rx={14} fill={A} />
      </g>
    </Svg>
  );
};

/** 2 — lean-to shelter (шалаш) silhouette drawn stick by stick. */
export const ShelterIcon: React.FC<P> = ({t}) => {
  const sticks = [
    [200, 70, 60, 330],
    [200, 70, 340, 330],
    [175, 50, 95, 330],
    [225, 50, 305, 330],
    [200, 70, 130, 330],
    [200, 70, 270, 330],
    [185, 45, 200, 70],
    [215, 45, 200, 70],
  ];
  const fillIn = interpolate(t, [0.9, 1.6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <Svg>
      <path d="M200 72 L64 330 L336 330 Z" fill="#0f2a1e" opacity={fillIn} />
      {/* leaf covering laid along both slopes */}
      {[0.3, 0.48, 0.66, 0.84].flatMap((k, i) =>
        [-1, 1].map((side) => {
          const x = 200 + side * 136 * k - side * 14;
          const y = 72 + 258 * k;
          return (
            <ellipse
              key={`${i}${side}`}
              cx={x}
              cy={y}
              rx={30}
              ry={11}
              fill={(i + (side > 0 ? 1 : 0)) % 2 ? '#6f8a3a' : '#a07a35'}
              opacity={0.85 * fillIn}
              transform={`rotate(${side * 62} ${x} ${y})`}
            />
          );
        })
      )}
      <path d="M200 200 L168 330 L232 330 Z" fill="#06120c" opacity={fillIn} />
      {sticks.map(([x1, y1, x2, y2], i) => {
        const len = Math.hypot(x2 - x1, y2 - y1);
        return (
          <line
            key={i}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            stroke={i < 2 ? C : '#d9cbb0'}
            strokeWidth={i < 2 ? 14 : 9}
            strokeLinecap="round"
            strokeDasharray={len}
            strokeDashoffset={len * draw(t, 0.1 + i * 0.1, 0.5)}
          />
        );
      })}
      <line x1={30} y1={336} x2={370} y2={336} stroke={A} strokeWidth={8} strokeLinecap="round" opacity={0.9} />
    </Svg>
  );
};

/** 3 — water drop with ripples. */
export const DropIcon: React.FC<P> = ({t}) => {
  const bob = Math.sin(t * 1.6) * 8;
  return (
    <Svg>
      <defs>
        <linearGradient id="dropG" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#d8f0f5" />
          <stop offset="100%" stopColor="#6fb6cc" />
        </linearGradient>
      </defs>
      {[0, 1, 2].map((k) => {
        const p = ((t * 0.5 + k / 3) % 1);
        return (
          <ellipse
            key={k}
            cx={200}
            cy={350}
            rx={60 + p * 140}
            ry={14 + p * 26}
            fill="none"
            stroke={C}
            strokeWidth={4}
            opacity={(1 - p) * 0.55}
          />
        );
      })}
      <g transform={`translate(0 ${bob})`}>
        <path
          d="M200 30 C 200 30, 95 165, 95 230 A 105 105 0 0 0 305 230 C 305 165, 200 30, 200 30 Z"
          fill="url(#dropG)"
          stroke={C}
          strokeWidth={10}
          strokeLinejoin="round"
        />
        <path d="M150 215 Q 150 265 190 285" fill="none" stroke="#ffffff" strokeWidth={12} strokeLinecap="round" opacity={0.7} />
      </g>
    </Svg>
  );
};

/** 4 — animated campfire with flickering flames and rising sparks. */
export const FireIcon: React.FC<P> = ({t}) => {
  const f1 = 1 + 0.08 * Math.sin(t * 9) + 0.05 * Math.sin(t * 13.7 + 1);
  const f2 = 1 + 0.1 * Math.sin(t * 11 + 2) + 0.04 * Math.sin(t * 17 + 3);
  const f3 = 1 + 0.12 * Math.sin(t * 14 + 4);
  const sk = 4 * Math.sin(t * 5.3);
  const flame = (scale: number, skew: number, color: string, w: number, h: number) => (
    <path
      d={`M200 ${330 - h} C ${200 + w * 0.35} ${330 - h * 0.62}, ${200 + w} ${330 - h * 0.4}, ${200 + w * 0.8} ${300} C ${200 + w * 0.6} ${330}, ${200 - w * 0.6} ${330}, ${200 - w * 0.8} ${300} C ${200 - w} ${330 - h * 0.4}, ${200 - w * 0.2} ${330 - h * 0.55}, 200 ${330 - h} Z`}
      fill={color}
      transform={`translate(200 320) scale(${1 + (1 - scale) * 0.5} ${scale}) skewX(${skew}) translate(-200 -320)`}
    />
  );
  return (
    <Svg>
      <circle cx={200} cy={250} r={190} fill="url(#fireGlow)" />
      <defs>
        <radialGradient id="fireGlow">
          <stop offset="0%" stopColor="rgba(255,160,60,0.55)" />
          <stop offset="100%" stopColor="rgba(255,120,40,0)" />
        </radialGradient>
      </defs>
      {flame(f1, sk, COLORS.ember, 105, 270)}
      {flame(f2, -sk * 0.8, A, 75, 205)}
      {flame(f3, sk * 0.6, '#FFE6A3', 42, 130)}
      {/* logs */}
      <rect x={70} y={318} width={260} height={36} rx={18} fill="#6b4226" transform="rotate(14 200 336)" />
      <rect x={70} y={318} width={260} height={36} rx={18} fill="#7d5030" transform="rotate(-14 200 336)" />
      <circle cx={78} cy={305} r={14} fill="#c79b6a" />
      <circle cx={322} cy={305} r={14} fill="#c79b6a" />
      {/* sparks */}
      {Array.from({length: 8}, (_, i) => {
        const period = 1.6 + random(`sp${i}`) * 1.2;
        const p = ((t + random(`so${i}`) * period) % period) / period;
        const x = 200 + (random(`sx${i}`) - 0.5) * 140 + Math.sin(p * 6 + i) * 20;
        const y = 220 - p * 230;
        return <circle key={i} cx={x} cy={y} r={4 + (1 - p) * 3} fill="#FFE29A" opacity={1 - p} />;
      })}
    </Svg>
  );
};

/** 5 — three flashes lighting up in sequence. */
export const FlashesIcon: React.FC<P> = ({t}) => {
  const cycle = 2.4;
  return (
    <Svg w={600} h={400}>
      {[0, 1, 2].map((k) => {
        const local = ((t % cycle) - k * 0.45) / 0.45;
        const on = local >= 0 && local < 1 ? Math.sin(local * Math.PI) : 0;
        const cx = 120 + k * 180;
        return (
          <g key={k} transform={`translate(${cx} 200)`}>
            <circle r={95} fill={A} opacity={on * 0.25} />
            {Array.from({length: 8}, (_, r) => (
              <line
                key={r}
                x1={0}
                y1={-58 - on * 6}
                x2={0}
                y2={-78 - on * 22}
                stroke={A}
                strokeWidth={9}
                strokeLinecap="round"
                opacity={0.25 + on * 0.75}
                transform={`rotate(${r * 45})`}
              />
            ))}
            <circle r={38 + on * 8} fill={on > 0.05 ? '#FFF3D6' : 'none'} opacity={0.35 + 0.65 * on} stroke={C} strokeWidth={8} />
          </g>
        );
      })}
    </Svg>
  );
};

/** 6 — warning sign. */
export const WarningIcon: React.FC<P> = ({t}) => {
  const pulse = 1 + 0.03 * Math.sin(t * 2.4);
  return (
    <Svg>
      <g transform={`translate(200 210) scale(${pulse}) translate(-200 -210)`}>
        <path
          d="M200 45 L360 330 L40 330 Z"
          fill="rgba(255,179,71,0.14)"
          stroke={A}
          strokeWidth={22}
          strokeLinejoin="round"
        />
        <rect x={186} y={135} width={28} height={120} rx={14} fill={C} />
        <circle cx={200} cy={292} r={17} fill={C} />
      </g>
    </Svg>
  );
};

/** 7 — subscribe button with soft pulse. */
export const SubscribeButton: React.FC<P> = ({t}) => {
  const pulse = 1 + 0.04 * Math.sin(t * Math.PI * 1.2);
  const ringP = (t * 0.6) % 1;
  return (
    <div style={{position: 'relative', width: 760, height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
      <div
        style={{
          position: 'absolute',
          width: 640,
          height: 150,
          borderRadius: 75,
          border: `5px solid ${A}`,
          opacity: (1 - ringP) * 0.6,
          transform: `scale(${1 + ringP * 0.18})`,
        }}
      />
      <div
        style={{
          transform: `scale(${pulse})`,
          width: 640,
          height: 150,
          borderRadius: 75,
          background: `linear-gradient(180deg, #FFC46B 0%, ${A} 55%, #F29A2E 100%)`,
          boxShadow: `0 0 ${50 + 30 * Math.sin(t * Math.PI * 1.2)}px rgba(255,179,71,0.55)`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 26,
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 58,
          color: '#13291d',
          letterSpacing: 1,
        }}
      >
        <svg width={60} height={60} viewBox="0 0 60 60">
          <rect x={25} y={6} width={10} height={48} rx={5} fill="#13291d" />
          <rect x={6} y={25} width={48} height={10} rx={5} fill="#13291d" />
        </svg>
        ПОДПИСАТЬСЯ
      </div>
    </div>
  );
};
