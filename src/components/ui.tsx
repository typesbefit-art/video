import React from 'react';
import {random} from 'remotion';
import {C, FONT, FPS, lerp, pop} from '../lib';
import {Coin} from './Icons';

export const W = 1920;
export const H = 1080;

export const Stage: React.FC<{children: React.ReactNode; bg?: string; bg2?: string; ground?: string | false; frame: number; clouds?: boolean; night?: boolean}> = ({
  children, bg, bg2, ground = C.grass, frame, clouds = true, night,
}) => {
  const top = night ? '#2b2d6e' : bg ?? C.sky;
  const bottom = night ? '#6b5bd6' : bg2 ?? C.skyLight;
  const id = `g${top.replace('#', '')}${bottom.replace('#', '')}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" style={{position: 'absolute', inset: 0}}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={top} />
          <stop offset="1" stopColor={bottom} />
        </linearGradient>
      </defs>
      <rect width={W} height={H} fill={`url(#${id})`} />
      {night
        ? Array.from({length: 40}).map((_, i) => (
            <circle key={i} cx={random(`sx${i}`) * W} cy={random(`sy${i}`) * 600} r={2 + random(`sr${i}`) * 3}
              fill="#fff" opacity={0.4 + 0.6 * Math.abs(Math.sin(frame / 30 + i))} />
          ))
        : clouds
          ? [0, 1, 2].map((i) => {
              const x = ((random(`cx${i}`) * W + frame * (0.4 + i * 0.2)) % (W + 400)) - 200;
              return <Cloud key={i} x={x} y={90 + i * 110} s={0.7 + random(`cs${i}`) * 0.6} />;
            })
          : null}
      {ground ? <path d={`M0,${H - 210} Q${W / 2},${H - 260} ${W},${H - 210} L${W},${H} L0,${H} Z`} fill={ground} /> : null}
      {children}
    </svg>
  );
};

export const Cloud: React.FC<{x: number; y: number; s?: number}> = ({x, y, s = 1}) => (
  <g transform={`translate(${x},${y}) scale(${s})`} opacity={0.9}>
    <ellipse cx={0} cy={0} rx={90} ry={40} fill="#fff" />
    <ellipse cx={-50} cy={10} rx={60} ry={30} fill="#fff" />
    <ellipse cx={50} cy={8} rx={66} ry={32} fill="#fff" />
    <ellipse cx={10} cy={-28} rx={56} ry={40} fill="#fff" />
  </g>
);

/** Outlined cartoon text. */
export const T: React.FC<{
  x: number; y: number; size?: number; color?: string; stroke?: string; sw?: number; weight?: number;
  anchor?: 'start' | 'middle' | 'end'; children: React.ReactNode; s?: number; r?: number; opacity?: number;
}> = ({x, y, size = 80, color = C.white, stroke = C.ink, sw, weight = 800, anchor = 'middle', children, s = 1, r = 0, opacity = 1}) => (
  <g transform={`translate(${x},${y}) rotate(${r}) scale(${s})`} opacity={opacity}>
    <text x={0} y={0} textAnchor={anchor} dominantBaseline="middle" fontFamily={FONT} fontWeight={weight} fontSize={size}
      fill={color} stroke={stroke} strokeWidth={sw ?? size * 0.14} strokeLinejoin="round" paintOrder="stroke">
      {children}
    </text>
  </g>
);

/** Rounded label "pill". */
export const Pill: React.FC<{x: number; y: number; w: number; h?: number; fill?: string; children: React.ReactNode; size?: number; color?: string; s?: number}> = ({
  x, y, w, h = 90, fill = C.white, children, size = 48, color = C.ink, s = 1,
}) => (
  <g transform={`translate(${x},${y}) scale(${s})`}>
    <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={h / 2} fill={fill} stroke={C.ink} strokeWidth={6} />
    <text x={0} y={2} textAnchor="middle" dominantBaseline="middle" fontFamily={FONT} fontWeight={800} fontSize={size} fill={color}>{children}</text>
  </g>
);

export const Calendar: React.FC<{x: number; y: number; s?: number; day: React.ReactNode; month?: string}> = ({x, y, s = 1, day, month = 'ЗАРПЛАТА'}) => (
  <g transform={`translate(${x},${y}) scale(${s})`}>
    <rect x={-110} y={-100} width={220} height={210} rx={20} fill={C.white} stroke={C.ink} strokeWidth={6} />
    <rect x={-110} y={-100} width={220} height={62} rx={20} fill={C.red} stroke={C.ink} strokeWidth={6} />
    <text x={0} y={-66} textAnchor="middle" dominantBaseline="middle" fontFamily={FONT} fontWeight={800} fontSize={30} fill={C.white}>{month}</text>
    <text x={0} y={40} textAnchor="middle" dominantBaseline="middle" fontFamily={FONT} fontWeight={900} fontSize={110} fill={C.ink}>{day}</text>
    <circle cx={-60} cy={-104} r={10} fill={C.ink} />
    <circle cx={60} cy={-104} r={10} fill={C.ink} />
  </g>
);

/** Big red X drawn over something. */
export const Strike: React.FC<{x: number; y: number; size?: number; p: number}> = ({x, y, size = 120, p}) => {
  const len = size * 2 * Math.SQRT2;
  const a = Math.min(1, p * 2);
  const b = Math.max(0, p * 2 - 1);
  return (
    <g transform={`translate(${x},${y})`} strokeLinecap="round" stroke={C.red} strokeWidth={size * 0.22}>
      <line x1={-size} y1={-size} x2={size} y2={size} strokeDasharray={len} strokeDashoffset={len * (1 - a)} />
      <line x1={size} y1={-size} x2={-size} y2={size} strokeDasharray={len} strokeDashoffset={len * (1 - b)} />
    </g>
  );
};

export const Burst: React.FC<{x: number; y: number; r?: number; frame: number; color?: string; n?: number}> = ({x, y, r = 200, frame, color = C.yellow, n = 14}) => {
  const rot = frame * 0.4;
  return (
    <g transform={`translate(${x},${y}) rotate(${rot})`} opacity={0.55}>
      {Array.from({length: n}).map((_, i) => (
        <path key={i} d={`M0,0 L${-r * 0.12},${-r} L${r * 0.12},${-r} Z`} fill={color} transform={`rotate(${(360 / n) * i})`} />
      ))}
    </g>
  );
};

export const Confetti: React.FC<{frame: number; n?: number; seed?: string}> = ({frame, n = 60, seed = 'c'}) => (
  <g>
    {Array.from({length: n}).map((_, i) => {
      const x0 = random(`${seed}x${i}`) * W;
      const sp = 4 + random(`${seed}s${i}`) * 6;
      const y = -40 + ((frame * sp + random(`${seed}y${i}`) * 400) % (H + 80)) - 300 * random(`${seed}d${i}`);
      const col = [C.yellow, C.red, C.blue, C.green, C.pink, C.purple][i % 6];
      return <rect key={i} x={x0 + Math.sin(frame / 20 + i) * 30} y={y} width={18} height={10} fill={col}
        transform={`rotate(${frame * 5 + i * 37},${x0},${y})`} />;
    })}
  </g>
);

export const CoinRain: React.FC<{frame: number; n?: number; seed?: string; x0?: number; x1?: number; speed?: number}> = ({frame, n = 20, seed = 'r', x0 = 0, x1 = W, speed = 1}) => (
  <g>
    {Array.from({length: n}).map((_, i) => {
      const x = x0 + random(`${seed}${i}`) * (x1 - x0);
      const y = ((frame * (6 + random(`${seed}v${i}`) * 6) * speed + random(`${seed}o${i}`) * H) % (H + 200)) - 100;
      return <g key={i} transform={`translate(${x},${y}) scale(${Math.cos(frame / 10 + i) * 0.5 + 0.7},1)`}><Coin r={30} /></g>;
    })}
  </g>
);

/** Spring pop-in scale helper for a group. */
export const Pop: React.FC<{frame: number; delay?: number; x: number; y: number; children: React.ReactNode; damping?: number}> = ({frame, delay = 0, x, y, children, damping}) => {
  const s = pop(frame, delay, damping);
  return <g transform={`translate(${x},${y}) scale(${s})`} opacity={frame >= delay ? 1 : 0}>{children}</g>;
};

export const fadeIn = (frame: number, delay = 0, len = 12) => lerp(frame, [delay, delay + len], [0, 1]);
export const seconds = (s: number) => s * FPS;
