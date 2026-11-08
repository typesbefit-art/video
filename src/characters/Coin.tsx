import React from 'react';
import { C, INK, STROKE } from '../theme';
import { blinkAmount } from './Max';

type Props = {
  x: number;
  y: number; // centre
  scale?: number;
  t: number;
  mouth: number;
  spin?: number; // 0..1 → one full flip
  mood?: 'happy' | 'wink' | 'excited';
  arms?: 'down' | 'up' | 'point';
  sx?: number;
  sy?: number;
  seed?: number;
};

export const Coin: React.FC<Props> = ({ x, y, scale = 1, t, mouth, spin = 0, mood = 'happy', arms = 'down', sx = 1, sy = 1, seed = 11 }) => {
  const R = 130;
  const flip = Math.cos(spin * Math.PI * 2);
  const faceVisible = flip > 0.15;
  const blink = mood === 'wink' ? 1 : blinkAmount(t, seed);
  const m = Math.min(1, mouth);
  const shineX = ((t * 0.6) % 2.2) * 2 - 1.6; // sweeping highlight
  const armSwing = Math.sin(t * 6) * 10;
  const armPaths =
    arms === 'up'
      ? [`M -118 10 Q -190 -40 -200 ${-120 + armSwing}`, `M 118 10 Q 190 -40 200 ${-120 - armSwing}`]
      : arms === 'point'
      ? [`M -118 30 Q -170 80 -160 130`, `M 118 0 Q 200 -20 260 ${-50 + armSwing * 0.3}`]
      : [`M -118 30 Q -175 80 -165 ${130 + armSwing * 0.3}`, `M 118 30 Q 175 80 165 ${130 - armSwing * 0.3}`];
  const hands = arms === 'up' ? [[-200, -120 + armSwing], [200, -120 - armSwing]] : arms === 'point' ? [[-160, 130], [260, -50 + armSwing * 0.3]] : [[-165, 130 + armSwing * 0.3], [165, 130 - armSwing * 0.3]];

  return (
    <g transform={`translate(${x} ${y}) scale(${scale * sx} ${scale * sy})`}>
      <ellipse cx={0} cy={R + 150} rx={90} ry={16} fill="rgba(0,0,0,0.16)" />
      {/* legs */}
      <path d="M -45 110 L -55 200" stroke={INK} strokeWidth={30} strokeLinecap="round" />
      <path d="M 45 110 L 55 200" stroke={INK} strokeWidth={30} strokeLinecap="round" />
      <path d="M -45 110 L -55 200" stroke={C.goldDark} strokeWidth={14} strokeLinecap="round" />
      <path d="M 45 110 L 55 200" stroke={C.goldDark} strokeWidth={14} strokeLinecap="round" />
      <ellipse cx={-70} cy={208} rx={36} ry={18} fill={C.red} stroke={INK} strokeWidth={8} />
      <ellipse cx={70} cy={208} rx={36} ry={18} fill={C.red} stroke={INK} strokeWidth={8} />
      {/* arms */}
      {armPaths.map((d, i) => (
        <g key={i}>
          <path d={d} stroke={INK} strokeWidth={30} fill="none" strokeLinecap="round" />
          <path d={d} stroke={C.goldDark} strokeWidth={14} fill="none" strokeLinecap="round" />
          <circle cx={hands[i][0]} cy={hands[i][1]} r={22} fill="#fff" stroke={INK} strokeWidth={8} />
        </g>
      ))}
      {/* body (flips) */}
      <g transform={`scale(${Math.max(0.08, Math.abs(flip))} 1)`}>
        <circle cx={0} cy={0} r={R} fill={C.goldDark} stroke={INK} strokeWidth={STROKE} />
        <circle cx={0} cy={-6} r={R - 18} fill={C.gold} />
        <circle cx={0} cy={-6} r={R - 34} fill="none" stroke={C.goldDark} strokeWidth={6} strokeDasharray="10 12" />
        <clipPath id={`coinclip-${seed}`}>
          <circle cx={0} cy={-6} r={R - 18} />
        </clipPath>
        <g clipPath={`url(#coinclip-${seed})`}>
          <rect x={shineX * R} y={-200} width={40} height={400} fill="#fff6c8" opacity={0.7} transform={`rotate(25 0 0)`} />
        </g>
        {faceVisible ? (
          <g>
            {[-42, 42].map((ex, i) => {
              const closed = mood === 'wink' ? i === 1 : blink > 0.5;
              return closed ? (
                <path key={ex} d={`M ${ex - 22} -26 Q ${ex} -10 ${ex + 22} -26`} stroke={INK} strokeWidth={9} fill="none" strokeLinecap="round" />
              ) : (
                <g key={ex}>
                  <ellipse cx={ex} cy={-28} rx={24} ry={mood === 'excited' ? 32 : 28} fill="#fff" stroke={INK} strokeWidth={7} />
                  <circle cx={ex + 4} cy={-24} r={13} fill={INK} />
                  <circle cx={ex + 9} cy={-30} r={5} fill="#fff" />
                </g>
              );
            })}
            <path d="M -66 -70 Q -44 -82 -22 -72" stroke={INK} strokeWidth={8} fill="none" strokeLinecap="round" />
            <path d="M 22 -72 Q 44 -82 66 -70" stroke={INK} strokeWidth={8} fill="none" strokeLinecap="round" />
            <ellipse cx={-78} cy={14} rx={18} ry={11} fill={C.orange} opacity={0.6} />
            <ellipse cx={78} cy={14} rx={18} ry={11} fill={C.orange} opacity={0.6} />
            {m > 0.06 ? (
              <g transform="translate(0 34)">
                <ellipse cx={0} cy={0} rx={24 + 10 * m} ry={4 + 26 * m} fill="#7a1e2c" stroke={INK} strokeWidth={7} />
                <ellipse cx={0} cy={4 + 16 * m} rx={16} ry={10 * m} fill="#ff6b81" />
              </g>
            ) : (
              <path d="M -32 26 Q 0 58 32 26" stroke={INK} strokeWidth={9} fill="none" strokeLinecap="round" />
            )}
          </g>
        ) : (
          <text x={0} y={34} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={110} fill={C.goldDark} stroke={INK} strokeWidth={6} paintOrder="stroke">$</text>
        )}
      </g>
    </g>
  );
};
