import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {Clouds, Ground, Ridge, Skyline, Sky} from '../components/art';
import {Layer, Parallax} from '../components/Parallax';
import {Particles} from '../components/Particles';
import {Scene, SceneProps} from '../components/Scene';
import {Chapter, Title} from '../components/Title';
import {H, SAFE, W, mix, prog} from '../lib/math';
import {wordFrame} from '../lib/timing';

/** 6. Через год: пустое заснеженное поле, заброшенный город под снегом. «ГЛАВНАЯ УГРОЗА — ГОЛОД». */
export const S6Year: React.FC<SceneProps> = ({scene, index, duration}) => {
  const frame = useCurrentFrame();
  const horizon = 1120;
  const titleAt = wordFrame(index, 'голод', 3.2) - 4;
  const globeAt = wordFrame(index, 'страда', 4.2);
  const zoom = mix(1.12, 1.0, frame / duration); // медленный отъезд — ощущение пустоты

  const art = (
    <Parallax camera={{zoom, x: mix(-30, 30, frame / duration), y: 0}}>
      <Layer depth={0.04}>
        <Sky id="s6-sky" stops={[[0, '#5a626c'], [0.45, '#8c949c'], [0.6, '#b4bac0'], [1, '#6e757c']]} />
        <Clouds seed="s6-c" y={520} spread={500} count={12} size={1.3} color="#9aa2aa" opacity={0.7} drift={0.4} blur={50} frame={frame} />
      </Layer>
      <Layer depth={0.15}>
        <Ridge seed="s6-m" baseY={horizon - 10} amp={100} color="#a8b0b8" top="#e4e9ee" />
      </Layer>
      <Layer depth={0.35}>
        {/* заброшенный город под снегом: ни одного горящего окна */}
        <Skyline seed="s6-city" baseY={horizon + 70} minH={90} maxH={460} scale={0.75} color="#4a525c" rim="#dfe6ec" rimSide="left" rimOpacity={0.35} snow={1} />
        <Clouds seed="s6-haze" y={horizon + 40} spread={80} count={10} color="#c8ced4" opacity={0.6} drift={0.3} blur={30} frame={frame} />
      </Layer>
      <Layer depth={0.7}>
        <Ground id="s6-g" y={horizon + 60} stops={[[0, '#d6dce2'], [0.5, '#c2c9d0'], [1, '#9aa3ac']]} />
        {/* сугробы */}
        {[0, 1, 2, 3].map((i) => (
          <ellipse key={i} cx={i * 360 - 40} cy={horizon + 260 + (i % 2) * 90} rx={420} ry={60} fill="#e8edf1" opacity={0.8} />
        ))}
      </Layer>
      <Layer depth={1}>
        {/* сухие стебли и старый забор торчат из снега */}
        <g stroke="#3a3530" strokeWidth={3} strokeLinecap="round">
          {new Array(26).fill(0).map((_, i) => {
            const x = 30 + i * 42 + ((i * 37) % 20);
            const y = H - 300 + ((i * 53) % 120);
            const h = 40 + ((i * 29) % 70);
            return <path key={i} d={`M${x},${y} q${(i % 3) * 6 - 6},${-h / 2} ${(i % 2 ? 14 : -12)},${-h}`} fill="none" />;
          })}
        </g>
        <g fill="#2c2620">
          {[0, 1, 2, 3, 4].map((i) => (
            <g key={i} transform={`rotate(${(i % 2 ? 4 : -6)} ${120 + i * 210} ${H - 180})`}>
              <rect x={110 + i * 210} y={H - 360} width={16} height={200} />
              <rect x={110 + i * 210} y={H - 330} width={220} height={10} opacity={i === 4 ? 0 : 1} />
            </g>
          ))}
        </g>
        <rect x={-200} y={H - 200} width={W + 400} height={400} fill="#eef2f5" opacity={0.9} />
      </Layer>
    </Parallax>
  );

  return (
    <Scene
      scene={scene}
      grade={{tint: '#3a5878', amount: 0.4, lift: '#141c26'}}
      vignette={0.7}
      art={art}
      overlay={
        <>
          <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
            <Particles kind="snow" count={140} seed="s6-snow" wind={2.4} />
            <Particles kind="snow" count={40} seed="s6-snow-big" wind={3} speed={1.8} opacity={0.8} />
          </svg>
          <Chapter text="ЧЕРЕЗ ГОД" index={5} />
          <Title text={scene.title} at={titleAt} size={108} top={SAFE.top + 140} />
          <Globe at={globeAt} />
        </>
      }
    />
  );
};

/** Каркасный глобус: «страдают даже страны, которые в войне не участвовали». */
const Globe: React.FC<{at: number}> = ({at}) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [at - 6, at + 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const spread = prog(frame, at, at + 80);
  const r = 170;
  const rot = frame * 1.4;
  return (
    <svg width={W} height={H} style={{position: 'absolute', inset: 0, opacity: o}}>
      <defs>
        <clipPath id="globe-clip">
          <circle cx={W / 2} cy={830} r={r} />
        </clipPath>
        <radialGradient id="globe-dark" cx="0.5" cy="0.5">
          <stop offset="0" stopColor="#2a2a2c" stopOpacity={0.85} />
          <stop offset="1" stopColor="#2a2a2c" stopOpacity={0} />
        </radialGradient>
      </defs>
      <circle cx={W / 2} cy={830} r={r} fill="rgba(20,30,44,0.55)" stroke="#e8eef4" strokeWidth={3} />
      <g clipPath="url(#globe-clip)" stroke="#e8eef4" strokeOpacity={0.55} strokeWidth={2} fill="none">
        {[-60, -30, 0, 30, 60].map((lat) => {
          const y = 830 + Math.sin((lat * Math.PI) / 180) * r;
          const rx = Math.cos((lat * Math.PI) / 180) * r;
          return <ellipse key={lat} cx={W / 2} cy={y} rx={rx} ry={rx * 0.12} />;
        })}
        {[0, 30, 60, 90, 120, 150].map((lon) => {
          const a = (((lon + rot) % 180) * Math.PI) / 180;
          return <ellipse key={lon} cx={W / 2} cy={830} rx={Math.abs(Math.cos(a)) * r} ry={r} />;
        })}
        {/* тёмное пятно «голода» расползается по всему шару */}
        <circle cx={W / 2 - 40} cy={800} r={20 + spread * r * 2} fill="url(#globe-dark)" stroke="none" />
      </g>
    </svg>
  );
};
