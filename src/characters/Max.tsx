import React from 'react';
import { C, INK, STROKE, hash } from '../theme';

export type MaxPose = 'idle' | 'wave' | 'point' | 'shrug' | 'think' | 'cheer' | 'hold';
export type MaxMood = 'happy' | 'surprised' | 'sad' | 'think';

type Props = {
  x: number;
  y: number; // feet position
  scale?: number;
  t: number; // seconds (for blink, breathing)
  mouth: number; // 0..1 open
  pose?: MaxPose;
  mood?: MaxMood;
  lift?: number;
  sx?: number;
  sy?: number;
  look?: [number, number];
  flip?: boolean;
  seed?: number;
  holding?: React.ReactNode; // drawn in right hand (local coords around hand)
};

// Blink every ~3 s with a little randomness; returns 0 (open) .. 1 (closed)
export function blinkAmount(t: number, seed = 0) {
  const period = 2.8 + hash(seed) * 1.4;
  const p = (t + hash(seed + 1) * period) % period;
  const d = 0.14;
  if (p > d) return 0;
  return Math.sin((p / d) * Math.PI);
}

const ARM_POSES: Record<MaxPose, { l: [number, number, number, number]; r: [number, number, number, number] }> = {
  // [elbowX, elbowY, handX, handY] relative to body origin (feet)
  idle: { l: [-150, -190, -150, -120], r: [150, -190, 150, -120] },
  wave: { l: [-150, -190, -150, -120], r: [210, -300, 200, -440] },
  point: { l: [-150, -190, -150, -120], r: [210, -270, 300, -320] },
  shrug: { l: [-200, -220, -250, -330], r: [200, -220, 250, -330] },
  think: { l: [-150, -190, -150, -120], r: [150, -230, 70, -300] },
  cheer: { l: [-200, -320, -230, -460], r: [200, -320, 230, -460] },
  hold: { l: [-150, -190, -150, -120], r: [180, -200, 230, -250] },
};

const Arm: React.FC<{ sx: number; sy: number; ex: number; ey: number; hx: number; hy: number; sleeve: string }> = ({ sx, sy, ex, ey, hx, hy, sleeve }) => {
  const d = `M ${sx} ${sy} Q ${ex} ${ey} ${hx} ${hy}`;
  return (
    <g>
      <path d={d} stroke={INK} strokeWidth={46} fill="none" strokeLinecap="round" />
      <path d={d} stroke={C.skin} strokeWidth={28} fill="none" strokeLinecap="round" />
      <path d={`M ${sx} ${sy} L ${sx + (ex - sx) * 0.35} ${sy + (ey - sy) * 0.35}`} stroke={sleeve} strokeWidth={30} strokeLinecap="round" />
      <circle cx={hx} cy={hy} r={28} fill={C.skin} stroke={INK} strokeWidth={STROKE} />
    </g>
  );
};

export const Max: React.FC<Props> = ({
  x, y, scale = 1, t, mouth, pose = 'idle', mood = 'happy', lift = 0, sx = 1, sy = 1, look = [0, 0], flip = false, seed = 3, holding,
}) => {
  const breathe = 1 + Math.sin(t * 2.2) * 0.012;
  const blink = blinkAmount(t, seed);
  const arms = ARM_POSES[pose];
  // wave: wiggle the hand
  const wig = pose === 'wave' ? Math.sin(t * 12) * 30 : pose === 'cheer' ? Math.sin(t * 9) * 12 : 0;
  const headTilt = Math.sin(t * 1.7) * 3 + mouth * 2.5 + (mood === 'think' ? 6 : 0);
  const headBob = -mouth * 6;
  const eyeRy = mood === 'surprised' ? 64 : 54;
  const ry = Math.max(3, eyeRy * (1 - blink));
  const browLift = (mood === 'surprised' ? 22 : 0) + mouth * 8;
  const shirt = C.teal;
  const m = Math.min(1, mouth);

  return (
    <g transform={`translate(${x} ${y - lift}) scale(${(flip ? -1 : 1) * scale * sx} ${scale * sy * breathe})`}>
      {/* shadow */}
      <ellipse cx={0} cy={6 + lift / scale} rx={150 * (1 - Math.min(0.5, lift / 600))} ry={22} fill="rgba(0,0,0,0.18)" />
      {/* legs */}
      <rect x={-78} y={-120} width={58} height={110} rx={24} fill="#3546a8" stroke={INK} strokeWidth={STROKE} />
      <rect x={20} y={-120} width={58} height={110} rx={24} fill="#3546a8" stroke={INK} strokeWidth={STROKE} />
      <ellipse cx={-58} cy={-8} rx={56} ry={26} fill={INK} />
      <ellipse cx={58} cy={-8} rx={56} ry={26} fill={INK} />
      <ellipse cx={-70} cy={-16} rx={20} ry={8} fill="#5a5470" />
      <ellipse cx={46} cy={-16} rx={20} ry={8} fill="#5a5470" />
      {/* arms behind torso edges */}
      <Arm sx={-95} sy={-235} ex={arms.l[0]} ey={arms.l[1]} hx={arms.l[2]} hy={arms.l[3] + (pose === 'cheer' ? -wig : 0)} sleeve={shirt} />
      {/* torso */}
      <path d="M -110 -110 Q -120 -270 -60 -280 L 60 -280 Q 120 -270 110 -110 Z" fill={shirt} stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
      <path d="M -40 -278 Q 0 -240 40 -278" fill="none" stroke={INK} strokeWidth={8} strokeLinecap="round" />
      <circle cx={0} cy={-185} r={30} fill={C.yellow} stroke={INK} strokeWidth={8} />
      <text x={0} y={-173} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={36} fill={INK}>$</text>
      <rect x={-112} y={-130} width={224} height={26} rx={10} fill="#2a3a90" stroke={INK} strokeWidth={8} />
      <Arm sx={95} sy={-235} ex={arms.r[0]} ey={arms.r[1]} hx={arms.r[2] + wig * 0.4} hy={arms.r[3] + (pose === 'wave' ? 0 : pose === 'cheer' ? -wig : 0)} sleeve={shirt} />
      {holding ? <g transform={`translate(${arms.r[2]} ${arms.r[3]})`}>{holding}</g> : null}

      {/* head */}
      <g transform={`translate(0 ${-300 + headBob}) rotate(${headTilt}) translate(0 ${-150})`}>
        {/* ears */}
        <circle cx={-168} cy={10} r={36} fill={C.skin} stroke={INK} strokeWidth={STROKE} />
        <circle cx={168} cy={10} r={36} fill={C.skin} stroke={INK} strokeWidth={STROKE} />
        <circle cx={0} cy={0} r={172} fill={C.skin} stroke={INK} strokeWidth={STROKE} />
        {/* cheeks */}
        <ellipse cx={-105} cy={60} rx={30} ry={18} fill={C.pink} opacity={0.55} />
        <ellipse cx={105} cy={60} rx={30} ry={18} fill={C.pink} opacity={0.55} />
        {/* eyes */}
        {[-62, 62].map((ex) => (
          <g key={ex}>
            <ellipse cx={ex} cy={-10} rx={46} ry={ry} fill="#fff" stroke={INK} strokeWidth={8} />
            {ry > 12 ? (
              <g>
                <circle cx={ex + look[0] * 14} cy={-6 + look[1] * 14} r={mood === 'surprised' ? 18 : 23} fill={INK} />
                <circle cx={ex + look[0] * 14 + 8} cy={-15 + look[1] * 14} r={8} fill="#fff" />
              </g>
            ) : null}
          </g>
        ))}
        {/* brows */}
        {mood === 'sad' ? (
          <>
            <path d={`M -100 ${-82 - browLift} Q -66 ${-98 - browLift} -30 ${-76 - browLift}`} stroke={INK} strokeWidth={12} fill="none" strokeLinecap="round" transform="rotate(-10 -66 -82)" />
            <path d={`M 30 ${-76 - browLift} Q 66 ${-98 - browLift} 100 ${-82 - browLift}`} stroke={INK} strokeWidth={12} fill="none" strokeLinecap="round" transform="rotate(10 66 -82)" />
          </>
        ) : (
          <>
            <path d={`M -100 ${-80 - browLift} Q -66 ${-100 - browLift} -30 ${-84 - browLift}`} stroke={INK} strokeWidth={12} fill="none" strokeLinecap="round" />
            <path d={`M 30 ${-84 - browLift - (mood === 'think' ? 14 : 0)} Q 66 ${-100 - browLift - (mood === 'think' ? 14 : 0)} 100 ${-80 - browLift}`} stroke={INK} strokeWidth={12} fill="none" strokeLinecap="round" />
          </>
        )}
        {/* nose */}
        <path d="M -6 32 Q 8 44 -4 54" stroke={INK} strokeWidth={7} fill="none" strokeLinecap="round" />
        {/* mouth */}
        {m > 0.06 ? (
          <g transform="translate(0 92)">
            <ellipse cx={0} cy={0} rx={34 + 16 * m} ry={6 + 40 * m} fill="#7a1e2c" stroke={INK} strokeWidth={8} />
            <clipPath id={`mclip-${seed}`}>
              <ellipse cx={0} cy={0} rx={30 + 16 * m} ry={2 + 40 * m} />
            </clipPath>
            <g clipPath={`url(#mclip-${seed})`}>
              <rect x={-60} y={-60} width={120} height={50 - 40 * m + 14} fill="#fff" transform={`translate(0 ${12 - 4 * m})`} />
              <ellipse cx={0} cy={26 + 22 * m} rx={30} ry={22} fill="#ff6b81" />
            </g>
          </g>
        ) : mood === 'sad' ? (
          <path d="M -36 104 Q 0 78 36 104" stroke={INK} strokeWidth={10} fill="none" strokeLinecap="round" />
        ) : mood === 'surprised' ? (
          <ellipse cx={0} cy={96} rx={16} ry={20} fill="#7a1e2c" stroke={INK} strokeWidth={8} />
        ) : (
          <path d="M -44 82 Q 0 122 44 82" stroke={INK} strokeWidth={10} fill="none" strokeLinecap="round" />
        )}
        {/* cap */}
        <g>
          <path d="M -168 -46 Q -170 -196 0 -200 Q 170 -196 168 -46 Q 0 -78 -168 -46 Z" fill={C.red} stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
          <path d="M -60 -196 Q -40 -110 -50 -60" stroke="#d63447" strokeWidth={8} fill="none" />
          <path d="M 60 -196 Q 40 -110 50 -60" stroke="#d63447" strokeWidth={8} fill="none" />
          {/* brim */}
          <path d="M -150 -58 Q 40 -100 250 -50 Q 270 -28 230 -22 Q 40 -50 -150 -34 Z" fill="#e23347" stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
          <circle cx={0} cy={-200} r={16} fill={C.red} stroke={INK} strokeWidth={8} />
          <circle cx={0} cy={-130} r={36} fill="#fff" stroke={INK} strokeWidth={7} />
          <text x={0} y={-116} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={42} fill={C.red}>M</text>
        </g>
      </g>
    </g>
  );
};
