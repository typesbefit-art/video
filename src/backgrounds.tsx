import React from 'react';
import { C, INK, STROKE, hash } from './theme';

export type BgType = 'rays' | 'dots' | 'stripes' | 'room' | 'city' | 'shop' | 'grid' | 'bank';
export type Palette = [string, string, string]; // base, accent, detail

export const PALETTES: Palette[] = [
  ['#ffb238', '#ffc95e', '#ff8a3d'], // orange
  ['#2ec4b6', '#5fd8cc', '#1a9e92'], // teal
  ['#8b5cf6', '#a684ff', '#6d3fe0'], // purple
  ['#ff6f91', '#ff94ad', '#e04c72'], // pink
  ['#3da5ff', '#6bbcff', '#1f7fd6'], // blue
  ['#5ccf6b', '#86e392', '#38a84a'], // green
  ['#ffd23f', '#ffe27a', '#f0b400'], // yellow
  ['#ff5e5b', '#ff8a87', '#d63f3c'], // red
];

const W = 1080;
const H = 1920;

export const Background: React.FC<{ type: BgType; palette: Palette; t: number }> = ({ type, palette, t }) => {
  const [base, accent, detail] = palette;
  switch (type) {
    case 'rays': {
      const n = 18;
      const rot = t * 8;
      return (
        <g>
          <rect x={-200} y={-200} width={W + 400} height={H + 400} fill={base} />
          <g transform={`translate(${W / 2} ${H * 0.42}) rotate(${rot})`}>
            {Array.from({ length: n }).map((_, i) => {
              const a0 = (i / n) * Math.PI * 2;
              const a1 = a0 + Math.PI / n;
              const r = 2400;
              return i % 2 === 0 ? <path key={i} d={`M0 0 L${Math.cos(a0) * r} ${Math.sin(a0) * r} L${Math.cos(a1) * r} ${Math.sin(a1) * r} Z`} fill={accent} /> : null;
            })}
          </g>
          <circle cx={W / 2} cy={H * 0.42} r={260} fill={accent} opacity={0.6} />
        </g>
      );
    }
    case 'dots': {
      const s = 120;
      const off = (t * 30) % s;
      const dots = [];
      for (let yy = -2; yy < H / s + 2; yy++)
        for (let xx = -2; xx < W / s + 2; xx++)
          dots.push(<circle key={`${xx}-${yy}`} cx={xx * s + (yy % 2 ? s / 2 : 0) + off} cy={yy * s + off} r={22} fill={accent} />);
      return (
        <g>
          <rect x={-200} y={-200} width={W + 400} height={H + 400} fill={base} />
          {dots}
        </g>
      );
    }
    case 'stripes': {
      const s = 140;
      const off = (t * 50) % (s * 2);
      return (
        <g>
          <rect x={-200} y={-200} width={W + 400} height={H + 400} fill={base} />
          <g transform={`rotate(-30 ${W / 2} ${H / 2})`}>
            {Array.from({ length: 30 }).map((_, i) => (
              <rect key={i} x={-1200 + i * s * 2 + off} y={-1000} width={s} height={H + 2000} fill={accent} />
            ))}
          </g>
        </g>
      );
    }
    case 'room':
      return (
        <g>
          <rect x={-200} y={-200} width={W + 400} height={H + 400} fill={base} />
          {/* wallpaper */}
          {Array.from({ length: 14 }).map((_, i) => (
            <rect key={i} x={-200 + i * 110} y={-200} width={40} height={1600} fill={accent} opacity={0.5} />
          ))}
          {/* window */}
          <g transform="translate(640 330)">
            <rect x={0} y={0} width={340} height={380} rx={20} fill="#bfe9ff" stroke={INK} strokeWidth={STROKE} />
            <circle cx={250} cy={100} r={50} fill={C.yellow} />
            <ellipse cx={110 + Math.sin(t * 0.5) * 30} cy={180} rx={80} ry={30} fill="#fff" />
            <path d="M170 0 V380 M0 190 H340" stroke={INK} strokeWidth={STROKE} />
          </g>
          {/* frame */}
          <g transform="translate(110 420) rotate(-4)">
            <rect x={0} y={0} width={220} height={170} fill="#fff" stroke={INK} strokeWidth={STROKE} />
            <path d="M20 150 L80 70 L120 120 L150 90 L200 150 Z" fill={detail} />
          </g>
          {/* floor */}
          <rect x={-200} y={1330} width={W + 400} height={800} fill={detail} />
          <rect x={-200} y={1330} width={W + 400} height={18} fill={INK} />
          {Array.from({ length: 10 }).map((_, i) => (
            <path key={i} d={`M ${-100 + i * 140} 1348 L ${-300 + i * 180} 2200`} stroke="rgba(0,0,0,0.12)" strokeWidth={8} />
          ))}
          {/* plant */}
          <g transform="translate(110 1330)">
            <path d="M0 -150 Q -70 -260 -40 -330 M0 -150 Q 60 -270 30 -350 M0 -150 Q 10 -260 0 -380" stroke="#2f8a3c" strokeWidth={26} fill="none" strokeLinecap="round" />
            <path d="M -60 -150 L 60 -150 L 45 0 L -45 0 Z" fill={C.orange} stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
          </g>
        </g>
      );
    case 'city': {
      const bld = [
        [0, 520], [150, 700], [280, 600], [420, 820], [560, 560], [700, 760], [840, 640], [960, 880],
      ];
      return (
        <g>
          <rect x={-200} y={-200} width={W + 400} height={H + 400} fill={base} />
          <circle cx={820} cy={330} r={110} fill={C.yellow} stroke={INK} strokeWidth={STROKE} />
          {[0, 1, 2].map((i) => (
            <ellipse key={i} cx={((i * 420 + t * 40) % 1500) - 200} cy={220 + i * 160} rx={120} ry={40} fill="#fff" opacity={0.9} />
          ))}
          {bld.map(([x, h], i) => (
            <g key={i}>
              <rect x={x - 20} y={1450 - h} width={150} height={h + 600} fill={i % 2 ? detail : accent} stroke={INK} strokeWidth={STROKE} />
              {Array.from({ length: Math.floor(h / 90) }).map((_, j) => (
                <g key={j}>
                  <rect x={x + 5} y={1450 - h + 30 + j * 90} width={36} height={46} fill={hash(i * 10 + j) > 0.4 ? '#fff4b0' : '#5b5680'} />
                  <rect x={x + 66} y={1450 - h + 30 + j * 90} width={36} height={46} fill={hash(i * 10 + j + 5) > 0.5 ? '#fff4b0' : '#5b5680'} />
                </g>
              ))}
            </g>
          ))}
          <rect x={-200} y={1400} width={W + 400} height={800} fill="#4a4566" />
          <rect x={-200} y={1400} width={W + 400} height={14} fill={INK} />
        </g>
      );
    }
    case 'shop':
      return (
        <g>
          <rect x={-200} y={-200} width={W + 400} height={H + 400} fill={base} />
          {[480, 760, 1040].map((yy, r) => (
            <g key={yy}>
              {Array.from({ length: 8 }).map((_, i) => {
                const w = 90 + hash(r * 9 + i) * 40;
                const h = 110 + hash(r * 9 + i + 3) * 70;
                const x = -60 + i * 160;
                const col = PALETTES[(r * 3 + i) % PALETTES.length][0];
                return <rect key={i} x={x} y={yy - h} width={w} height={h} rx={10} fill={col} stroke={INK} strokeWidth={8} />;
              })}
              <rect x={-200} y={yy} width={W + 400} height={30} fill={detail} stroke={INK} strokeWidth={8} />
            </g>
          ))}
          <rect x={-200} y={1330} width={W + 400} height={800} fill={accent} />
          <rect x={-200} y={1330} width={W + 400} height={16} fill={INK} />
        </g>
      );
    case 'grid': {
      const s = 90;
      const off = (t * 20) % s;
      return (
        <g>
          <rect x={-200} y={-200} width={W + 400} height={H + 400} fill={base} />
          {Array.from({ length: 30 }).map((_, i) => (
            <g key={i}>
              <line x1={-200 + i * s + off} y1={-200} x2={-200 + i * s + off} y2={H + 200} stroke={accent} strokeWidth={4} />
              <line x1={-200} y1={-200 + i * s * 1.0 + off} x2={W + 200} y2={-200 + i * s + off} stroke={accent} strokeWidth={4} />
            </g>
          ))}
        </g>
      );
    }
    case 'bank':
      return (
        <g>
          <rect x={-200} y={-200} width={W + 400} height={H + 400} fill={base} />
          <path d="M 60 560 L 540 300 L 1020 560 Z" fill={accent} stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
          {[120, 330, 540, 750, 960].map((x) => (
            <rect key={x} x={x - 45} y={580} width={90} height={760} fill="#fff" stroke={INK} strokeWidth={STROKE} />
          ))}
          <rect x={-200} y={1330} width={W + 400} height={800} fill={detail} />
          <rect x={-200} y={1330} width={W + 400} height={16} fill={INK} />
        </g>
      );
  }
};
