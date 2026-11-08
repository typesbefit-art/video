import React from 'react';
import {C, FPS} from '../lib';

export type Mood = 'happy' | 'sad' | 'shock' | 'smug' | 'neutral' | 'confused' | 'sleepy' | 'joy';

type Props = {
  x: number;
  y: number;
  s?: number;
  frame: number;
  shirt?: string;
  mood?: Mood;
  armL?: number; // degrees, 0 = hanging down, positive = raised outward
  armR?: number;
  gray?: boolean;
  crown?: boolean;
  flip?: boolean;
  bob?: boolean;
  twin?: boolean;
  handR?: React.ReactNode; // drawn in right hand (local coords around 0,0)
  handL?: React.ReactNode;
  opacity?: number;
};

/** Flat cartoon guy. Origin = point between the feet; ~600px tall at s=1. */
export const Max: React.FC<Props> = ({
  x, y, s = 1, frame, shirt, mood = 'happy', armL = 8, armR = 8, gray, crown, flip, bob = true, twin, handR, handL, opacity = 1,
}) => {
  const color = shirt ?? (twin ? C.twinShirt : C.maxShirt);
  const t = frame / FPS;
  const by = bob ? Math.sin(t * Math.PI * 2 * 0.8) * 5 : 0;
  // blink every ~3.2s for 7 frames
  const blinkPhase = (frame + (twin ? 40 : 0)) % 190;
  const blink = blinkPhase < 7 ? 0.1 : 1;
  const hair = gray ? '#9aa0a6' : C.hair;
  const eyeScale = mood === 'shock' ? 1.35 : mood === 'sleepy' ? 0.35 : 1;

  const mouth = {
    happy: <path d="M-30,-392 Q0,-362 30,-392" stroke={C.ink} strokeWidth={8} fill="none" strokeLinecap="round" />,
    joy: <path d="M-36,-396 Q0,-340 36,-396 Z" fill="#7a2232" stroke={C.ink} strokeWidth={6} strokeLinejoin="round" />,
    sad: <path d="M-28,-372 Q0,-396 28,-372" stroke={C.ink} strokeWidth={8} fill="none" strokeLinecap="round" />,
    shock: <ellipse cx={0} cy={-380} rx={18} ry={24} fill="#7a2232" stroke={C.ink} strokeWidth={6} />,
    smug: <path d="M-24,-388 Q10,-370 34,-396" stroke={C.ink} strokeWidth={8} fill="none" strokeLinecap="round" />,
    neutral: <line x1={-24} y1={-384} x2={24} y2={-384} stroke={C.ink} strokeWidth={8} strokeLinecap="round" />,
    confused: <path d="M-28,-380 Q-14,-392 0,-382 Q14,-372 28,-386" stroke={C.ink} strokeWidth={8} fill="none" strokeLinecap="round" />,
    sleepy: <ellipse cx={0} cy={-382} rx={12} ry={8} fill="#7a2232" stroke={C.ink} strokeWidth={5} />,
  }[mood];

  const brows = {
    happy: [-8, 8], joy: [-12, 12], neutral: [0, 0], smug: [6, -14], sad: [16, -16], shock: [-14, 14], confused: [14, -10], sleepy: [4, -4],
  }[mood];

  const arm = (side: -1 | 1, angle: number, hand?: React.ReactNode) => (
    <g transform={`translate(${side * 74},-312) rotate(${side * -angle})`}>
      <rect x={-20} y={-6} width={40} height={150} rx={20} fill={color} stroke={C.ink} strokeWidth={6} />
      <circle cx={0} cy={150} r={24} fill={C.skin} stroke={C.ink} strokeWidth={6} />
      {hand ? <g transform={`translate(0,160) rotate(${side * angle})`}>{hand}</g> : null}
    </g>
  );

  return (
    <g transform={`translate(${x},${y + by * s}) scale(${flip ? -s : s},${s})`} opacity={opacity}>
      {/* shadow */}
      <ellipse cx={0} cy={6} rx={110} ry={18} fill="rgba(0,0,0,0.15)" />
      {/* legs */}
      <rect x={-62} y={-160} width={52} height={150} rx={18} fill="#34495e" stroke={C.ink} strokeWidth={6} />
      <rect x={10} y={-160} width={52} height={150} rx={18} fill="#34495e" stroke={C.ink} strokeWidth={6} />
      <rect x={-74} y={-22} width={70} height={30} rx={14} fill={C.ink} />
      <rect x={4} y={-22} width={70} height={30} rx={14} fill={C.ink} />
      {/* arms behind body for natural look */}
      {arm(-1, armL, handL)}
      {/* body */}
      <rect x={-92} y={-340} width={184} height={200} rx={56} fill={color} stroke={C.ink} strokeWidth={6} />
      <path d="M-40,-200 h80 v30 a40,20 0 0 1 -80,0 Z" fill="rgba(0,0,0,0.12)" />
      {twin ? (
        <g transform="translate(0,-262)">
          <ellipse cx={0} cy={0} rx={30} ry={22} fill="#ffb3c7" stroke={C.ink} strokeWidth={4} />
          <rect x={-8} y={-26} width={16} height={6} rx={3} fill={C.ink} />
          <circle cx={10} cy={-4} r={3} fill={C.ink} />
        </g>
      ) : (
        <text x={0} y={-244} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={48} fill="rgba(255,255,255,0.9)">$</text>
      )}
      {arm(1, armR, handR)}
      {/* neck + head */}
      <rect x={-22} y={-358} width={44} height={30} fill={C.skinShade} />
      <circle cx={-92} cy={-430} r={20} fill={C.skin} stroke={C.ink} strokeWidth={6} />
      <circle cx={92} cy={-430} r={20} fill={C.skin} stroke={C.ink} strokeWidth={6} />
      <circle cx={0} cy={-430} r={95} fill={C.skin} stroke={C.ink} strokeWidth={6} />
      {/* hair */}
      <path
        d="M-94,-440 C-104,-520 -40,-548 10,-540 C60,-536 104,-512 94,-440 C80,-480 50,-486 30,-476 C10,-500 -30,-500 -40,-478 C-60,-488 -84,-476 -94,-440 Z"
        fill={hair} stroke={C.ink} strokeWidth={6} strokeLinejoin="round"
      />
      {gray ? <path d="M-94,-440 q-6,-30 6,-52 M94,-440 q6,-30 -6,-52" stroke="#e0e0e0" strokeWidth={10} fill="none" /> : null}
      {/* eyes */}
      {[-34, 34].map((ex, i) => (
        <g key={ex} transform={`translate(${ex},-440) scale(${eyeScale},${blink * eyeScale})`}>
          <ellipse cx={0} cy={0} rx={15} ry={19} fill={C.white} stroke={C.ink} strokeWidth={4} />
          <circle cx={mood === 'confused' ? (i ? 4 : -4) : 2} cy={mood === 'sad' ? 5 : 2} r={8} fill={C.ink} />
          <circle cx={5} cy={-3} r={3} fill={C.white} />
        </g>
      ))}
      {/* brows */}
      <line x1={-50} y1={-474 + brows[0]} x2={-18} y2={-474 - brows[0] * 0.3} stroke={C.ink} strokeWidth={7} strokeLinecap="round" />
      <line x1={18} y1={-474 - brows[1] * 0.3} x2={50} y2={-474 + brows[1]} stroke={C.ink} strokeWidth={7} strokeLinecap="round" />
      {/* cheeks */}
      <circle cx={-56} cy={-400} r={13} fill={C.pink} opacity={0.45} />
      <circle cx={56} cy={-400} r={13} fill={C.pink} opacity={0.45} />
      {mouth}
      {crown ? (
        <g transform={`translate(0,-540) rotate(${Math.sin(t * 4) * 4})`}>
          <path d="M-60,0 L-60,-60 L-30,-28 L0,-74 L30,-28 L60,-60 L60,0 Z" fill={C.yellow} stroke={C.ink} strokeWidth={6} strokeLinejoin="round" />
          <circle cx={0} cy={-20} r={8} fill={C.red} />
        </g>
      ) : null}
    </g>
  );
};
