import React from 'react';
import {random, useCurrentFrame} from 'remotion';
import {Clouds, Glow, Ground, Ridge, Sky, Sun} from '../components/art';
import {Layer, Parallax} from '../components/Parallax';
import {Particles} from '../components/Particles';
import {Scene, SceneProps} from '../components/Scene';
import {Title} from '../components/Title';
import {H, SAFE, W, mix, prog} from '../lib/math';
import {wordFrame} from '../lib/timing';

/** 7. Восстановление: рассвет, ростки пробиваются сквозь пепел. «ДЕСЯТИЛЕТИЯ». */
export const S7Recovery: React.FC<SceneProps> = ({scene, index, duration}) => {
  const frame = useCurrentFrame();
  const horizon = 1150;
  const dawn = prog(frame, 0, duration);
  const titleAt = wordFrame(index, 'десятил', 1.2) - 3;
  const zoom = mix(1.0, 1.08, dawn);

  const art = (
    <Parallax camera={{zoom, x: 0, y: mix(20, -10, dawn)}}>
      <Layer depth={0.04}>
        <Sky id="s7-sky" stops={[[0, '#1c2a44'], [0.4, '#4a5a7a'], [0.56, '#d08a6a'], [0.62, '#ffc88a'], [1, '#3a3430']]} />
        {/* лучи рассвета */}
        <g opacity={0.25 + dawn * 0.2}>
          {new Array(9).fill(0).map((_, i) => {
            const a = -80 + i * 20;
            const rad = (a * Math.PI) / 180;
            const x2 = W * 0.5 + Math.sin(rad) * 1800;
            const y2 = horizon - Math.cos(rad) * 1800;
            return <path key={i} d={`M${W * 0.5},${horizon} L${x2 - 60},${y2} L${x2 + 60},${y2} Z`} fill="#ffe2b0" opacity={0.18} />;
          })}
        </g>
        <Sun id="s7-sun" cx={W * 0.5} cy={horizon + 40 - dawn * 120} r={80} core="#fff1c8" glow="#ffb070" glowR={6} />
        <Clouds seed="s7-c" y={620} spread={350} count={8} color="#e4a080" opacity={0.45} drift={0.3} frame={frame} />
      </Layer>
      <Layer depth={0.2}>
        <Ridge seed="s7-m" baseY={horizon + 10} amp={90} color="#3a3434" top="#c0806a" />
      </Layer>
      <Layer depth={0.6}>
        <Ground id="s7-g" y={horizon + 40} stops={[[0, '#6a625c'], [0.4, '#4a4440'], [1, '#221e1c']]} />
        <Glow id="s7-gl" cx={W * 0.5} cy={horizon + 60} rx={800} ry={140} color="#ffb070" opacity={0.4} />
      </Layer>
      <Layer depth={1}>
        <Sprouts frame={frame} y={horizon + 200} />
      </Layer>
    </Parallax>
  );

  return (
    <Scene
      scene={scene}
      grade={{tint: '#6a4a3a', amount: 0.25, lift: '#140f0c'}}
      art={art}
      overlay={
        <>
          <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
            <Particles kind="dust" count={60} seed="s7-dust" color="#ffe0b0" />
          </svg>
          <Title text={scene.title} at={titleAt} variant="yellow" size={128} top={SAFE.top + 260} sub="ВОССТАНОВЛЕНИЕ" />
        </>
      }
    />
  );
};

/** Ростки, пробивающиеся сквозь пепел. */
const Sprouts: React.FC<{frame: number; y: number}> = ({frame, y}) => (
  <g>
    {new Array(22).fill(0).map((_, i) => {
      const depth = random(`sp-d${i}`);
      const s = 0.5 + depth * 1.4;
      const x = random(`sp-x${i}`) * W;
      const yy = y + depth * (H - y - 150);
      const g = prog(frame, i * 2, i * 2 + 40);
      const h = 90 * s * g;
      const leaf = 26 * s * prog(frame, i * 2 + 20, i * 2 + 55);
      const sw = Math.sin(frame * 0.06 + i) * 4 * s;
      return (
        <g key={i}>
          <ellipse cx={x} cy={yy} rx={30 * s} ry={6 * s} fill="#2a2522" opacity={0.7} />
          <path d={`M${x},${yy} q${sw},${-h / 2} ${sw * 1.5},${-h}`} stroke="#7fbf5a" strokeWidth={4 * s} fill="none" strokeLinecap="round" />
          <path d={`M${x + sw * 1.5},${yy - h} q${-leaf},${-leaf * 0.2} ${-leaf * 1.3},${-leaf * 0.9} q${leaf * 0.8},${-leaf * 0.1} ${leaf * 1.3},${leaf * 0.9}`} fill="#8fd066" />
          <path d={`M${x + sw * 1.5},${yy - h} q${leaf},${-leaf * 0.2} ${leaf * 1.3},${-leaf * 0.9} q${-leaf * 0.8},${-leaf * 0.1} ${-leaf * 1.3},${leaf * 0.9}`} fill="#a4e07a" />
        </g>
      );
    })}
  </g>
);
