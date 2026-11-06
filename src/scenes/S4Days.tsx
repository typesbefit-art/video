import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {Glow} from '../components/art';
import {Layer, Parallax} from '../components/Parallax';
import {Particles} from '../components/Particles';
import {Scene, SceneProps} from '../components/Scene';
import {Chapter} from '../components/Title';
import {H, W, flicker, mix, prog} from '../lib/math';
import {wordFrame} from '../lib/timing';

/**
 * 4. Первые дни: пустой больничный коридор с мигающей лампой →
 * пустые полки магазина и капающая вода (на слове «вода»).
 */
export const S4Days: React.FC<SceneProps> = ({scene, index, duration}) => {
  const frame = useCurrentFrame();
  const cut = Math.min(Math.max(wordFrame(index, 'вода', 2.6) - 8, 40), duration - 50);
  const x = interpolate(frame, [cut - 8, cut + 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  return (
    <Scene
      scene={scene}
      grade={{tint: '#2a5060', amount: 0.45, lift: '#0a1216'}}
      art={
        <>
          <AbsoluteFill style={{opacity: 1 - x}}>
            <Corridor frame={frame} duration={cut + 10} />
          </AbsoluteFill>
          <AbsoluteFill style={{opacity: x}}>
            <Shelves frame={frame - cut} duration={duration - cut} />
          </AbsoluteFill>
        </>
      }
      overlay={
        <>
          <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
            <Particles kind="dust" count={50} seed="s4-dust" color="#cfe6e6" opacity={0.5} />
          </svg>
          <Chapter text="ПЕРВЫЕ ДНИ" index={3} />
        </>
      }
    />
  );
};

/** Больничный коридор в одноточечной перспективе. */
const Corridor: React.FC<{frame: number; duration: number}> = ({frame, duration}) => {
  const vx = W / 2;
  const vy = 1020;
  const zoom = mix(1.0, 1.2, frame / duration);
  // неисправная лампа: мигает нерегулярно
  const bad = frame % 47 < 3 || frame % 71 < 2 ? 0.15 : flicker(frame, 's4l', 0.12);
  const lamps = [0.18, 0.36, 0.56, 0.78];

  // точки «рамок» коридора: t — 0 у камеры, 1 у точки схода
  const frameAt = (t: number) => {
    const k = 1 - t;
    return {l: vx - 760 * k, r: vx + 760 * k, t: vy - 1150 * k, b: vy + 1100 * k};
  };

  return (
    <Parallax camera={{zoom, x: 0, y: 0}}>
      <Layer depth={0.3} origin={{x: vx, y: vy}}>
        <defs>
          <linearGradient id="s4-wall" x1="0" x2="1">
            <stop offset="0" stopColor="#24323a" />
            <stop offset="1" stopColor="#0e1418" />
          </linearGradient>
          <linearGradient id="s4-wallR" x1="1" x2="0">
            <stop offset="0" stopColor="#24323a" />
            <stop offset="1" stopColor="#0e1418" />
          </linearGradient>
          <linearGradient id="s4-floor" x1="0" y1="1" x2="0" y2="0">
            <stop offset="0" stopColor="#2a363a" />
            <stop offset="1" stopColor="#0c1012" />
          </linearGradient>
        </defs>
        <rect x={-200} y={-200} width={W + 400} height={H + 400} fill="#0a0e10" />
        {/* стены, пол, потолок */}
        <path d={`M-200,-300 L${vx - 60},${vy - 90} L${vx - 60},${vy + 80} L-200,${H + 300} Z`} fill="url(#s4-wall)" />
        <path d={`M${W + 200},-300 L${vx + 60},${vy - 90} L${vx + 60},${vy + 80} L${W + 200},${H + 300} Z`} fill="url(#s4-wallR)" />
        <path d={`M-200,${H + 300} L${vx - 60},${vy + 80} L${vx + 60},${vy + 80} L${W + 200},${H + 300} Z`} fill="url(#s4-floor)" />
        <path d={`M-200,-300 L${vx - 60},${vy - 90} L${vx + 60},${vy - 90} L${W + 200},-300 Z`} fill="#0b1013" />
        {/* дальний конец коридора — тусклая дверь */}
        <rect x={vx - 60} y={vy - 90} width={120} height={170} fill="#1a2428" />
        <rect x={vx - 22} y={vy - 50} width={44} height={130} fill="#2f3e40" />
        {/* двери палат по стенам */}
        {[0.12, 0.32, 0.5, 0.66].map((t, i) => {
          const a = frameAt(t);
          const b = frameAt(t + 0.08);
          const yb = (y: number, f: {t: number; b: number}) => f.t + (f.b - f.t) * y;
          return (
            <g key={i} fill="#0a1012" stroke="#3b4c50" strokeWidth={2}>
              <path d={`M${a.l + (vx - a.l) * 0.02},${yb(0.38, a)} L${b.l},${yb(0.38, b)} L${b.l},${yb(0.92, b)} L${a.l + (vx - a.l) * 0.02},${yb(0.92, a)} Z`} />
              <path d={`M${a.r - (a.r - vx) * 0.02},${yb(0.38, a)} L${b.r},${yb(0.38, b)} L${b.r},${yb(0.92, b)} L${a.r - (a.r - vx) * 0.02},${yb(0.92, a)} Z`} />
            </g>
          );
        })}
        {/* светильники на потолке и пятна света на полу */}
        {lamps.map((t, i) => {
          const f = frameAt(t);
          const w = (f.r - f.l) * 0.18;
          const y = f.t + (vy - f.t) * 0.06;
          const intensity = i === 1 ? bad : flicker(frame, `s4l${i}`, 0.06) * (i === 3 ? 0.4 : 0.8);
          return (
            <g key={i} opacity={intensity}>
              <rect x={vx - w / 2} y={y} width={w} height={Math.max(4, 22 * (1 - t))} fill="#dff5ee" />
              <Glow id={`s4-lg${i}`} cx={vx} cy={y + 40 * (1 - t)} rx={w * 1.4} ry={w * 0.6} color="#bfeee0" opacity={0.45} />
              <Glow id={`s4-fl${i}`} cx={vx} cy={f.b - (f.b - vy) * 0.08} rx={w * 1.6} ry={w * 0.3} color="#9fd8cc" opacity={0.25} />
            </g>
          );
        })}
        {/* пустая каталка у стены — силуэт */}
        <g fill="#05080a" opacity={0.95}>
          <rect x={90} y={1420} width={330} height={26} rx={6} />
          <rect x={110} y={1446} width={10} height={160} />
          <rect x={390} y={1446} width={10} height={160} />
          <circle cx={115} cy={1616} r={14} />
          <circle cx={395} cy={1616} r={14} />
        </g>
        {/* световой короб «+» */}
        <g transform={`translate(${W - 300}, 430)`} opacity={0.6 + 0.4 * bad}>
          <rect width={170} height={110} rx={10} fill="#0f2a22" stroke="#4fd1a0" strokeWidth={3} />
          <path d="M70 25 h30 v25 h25 v30 h-25 v25 h-30 v-25 h-25 v-30 h25 z" fill="#5fe0b0" transform="translate(0,-10) scale(1)" />
        </g>
      </Layer>
    </Parallax>
  );
};

/** Пустые полки магазина + капающая вода на переднем плане. */
const Shelves: React.FC<{frame: number; duration: number}> = ({frame, duration}) => {
  const f = Math.max(0, frame);
  const zoom = mix(1.08, 1.0, prog(f, 0, duration));
  const panX = mix(-40, 40, f / Math.max(1, duration));
  const drip = (f % 34) / 34; // цикл капли
  return (
    <Parallax camera={{zoom, x: panX, y: 0}}>
      <Layer depth={0.2}>
        <rect x={-200} y={-200} width={W + 400} height={H + 400} fill="#0c1215" />
        <Glow id="s4-ceil" cx={W / 2} cy={260} rx={700} ry={260} color="#8fbfc0" opacity={0.25 * flicker(f, 's4c', 0.15)} />
        {/* стеллажи */}
        {[0, 1, 2].map((col) => {
          const x = 70 + col * 330;
          return (
            <g key={col}>
              <rect x={x} y={380} width={300} height={1150} fill="#141c20" />
              <rect x={x} y={380} width={300} height={1150} fill="none" stroke="#2c3a3f" strokeWidth={6} />
              {[0, 1, 2, 3, 4, 5].map((r) => (
                <g key={r}>
                  <rect x={x} y={560 + r * 180} width={300} height={16} fill="#3a4a50" />
                  <rect x={x} y={576 + r * 180} width={300} height={10} fill="#0a0f11" opacity={0.7} />
                  {/* последние остатки товаров — пара опрокинутых коробок */}
                  {(col * 7 + r * 3) % 5 === 0 && (
                    <rect x={x + 30 + ((r * 53) % 180)} y={520 + r * 180} width={46} height={40} fill="#26343a" transform={`rotate(${(r % 2 ? 12 : -8)} ${x + 50} ${540 + r * 180})`} />
                  )}
                  {/* ценники */}
                  <rect x={x + 20} y={562 + r * 180} width={40} height={12} fill="#c9d8d0" opacity={0.35} />
                </g>
              ))}
            </g>
          );
        })}
      </Layer>
      <Layer depth={0.8}>
        <defs>
          <linearGradient id="s4-water" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#6f9a98" stopOpacity={0.6} />
            <stop offset="1" stopColor="#1a2a2c" stopOpacity={0.9} />
          </linearGradient>
        </defs>
        {/* лужа на полу, протекающая труба сверху */}
        <rect x={-200} y={1560} width={W + 400} height={600} fill="#070b0c" />
        <ellipse cx={W * 0.62} cy={1700} rx={360} ry={70} fill="url(#s4-water)" />
        {[0, 1, 2].map((i) => {
          const p = ((f + i * 11) % 34) / 34;
          return <ellipse key={i} cx={W * 0.62} cy={1700} rx={40 + p * 300} ry={8 + p * 56} fill="none" stroke="#b9e0dc" strokeWidth={3} opacity={(1 - p) * 0.6} />;
        })}
        <rect x={W * 0.62 - 30} y={-200} width={60} height={240} fill="#1d2629" />
        <circle cx={W * 0.62} cy={60 + drip * 1640} r={9} fill="#cfeeea" opacity={drip < 0.97 ? 0.85 : 0} />
      </Layer>
    </Parallax>
  );
};
