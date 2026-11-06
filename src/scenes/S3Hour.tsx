import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Clouds, Glow, Ground, Plume, Ridge, Skyline, Sky} from '../components/art';
import {Layer, Parallax} from '../components/Parallax';
import {Particles} from '../components/Particles';
import {Scene, SceneProps} from '../components/Scene';
import {Chapter} from '../components/Title';
import {FONT} from '../lib/fonts';
import {H, W, mix, prog} from '../lib/math';
import {wordFrame} from '../lib/timing';

/** 3. Первый час: осадки поднимаются и дрейфуют, гаснут окна, отключаются свет/связь/интернет. */
export const S3Hour: React.FC<SceneProps> = ({scene, index, duration}) => {
  const frame = useCurrentFrame();
  const horizon = 1180;

  // точная синхронизация с голосом
  const iconsIn = wordFrame(index, 'пропада', 4.0) - 6;
  const offLight = wordFrame(index, 'свет', 4.6);
  const offComm = wordFrame(index, 'связь', 5.2);
  const offNet = wordFrame(index, 'интернет', 5.8);

  // окна гаснут: сначала медленно, на слове «свет» — разом
  const lit = interpolate(frame, [0, offLight - 4, offLight + 8, duration], [0.45, 0.3, 0.05, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const zoom = mix(1.02, 1.14, frame / duration);
  const panX = mix(30, -30, frame / duration);

  const art = (
    <Parallax camera={{zoom, x: panX, y: 0}}>
      <Layer depth={0.05}>
        <Sky id="s3-sky" stops={[[0, '#151a22'], [0.4, '#2c3440'], [0.6, '#5a5550'], [0.7, '#3a3a3e'], [1, '#121418']]} />
        <Glow id="s3-glow" cx={W * 0.3} cy={horizon - 50} rx={700} ry={200} color="#b0482a" opacity={0.45} />
        <Clouds seed="s3-c1" y={520} spread={500} count={12} color="#3a3c42" opacity={0.85} drift={0.9} frame={frame} />
      </Layer>
      <Layer depth={0.15}>
        <Ridge seed="s3-m" baseY={horizon - 20} amp={120} color="#262a32" top="#4a4a50" />
        {/* радиоактивные осадки: столбы поднимаются и уходят по ветру вправо */}
        <Plume seed="p1" x={W * 0.22} y={horizon - 40} height={1050} wind={520} frame={frame} color="#6a6460" width={70} />
        <Plume seed="p2" x={W * 0.5} y={horizon - 30} height={1150} wind={600} frame={frame} color="#57524f" width={90} speed={0.8} />
        <Plume seed="p3" x={W * 0.78} y={horizon - 30} height={900} wind={420} frame={frame} color="#6e6862" width={55} speed={1.2} />
      </Layer>
      <Layer depth={0.35}>
        <Skyline seed="s3-far" baseY={horizon + 60} minH={70} maxH={300} scale={0.6} color="#1c2028" lit={lit * 0.8} windowColor="#ffd08a" frame={frame} />
      </Layer>
      <Layer depth={0.6}>
        <Skyline seed="s3-city" baseY={horizon + 300} minH={180} maxH={760} color="#0d1015" rim="#7d8796" rimOpacity={0.35} rimSide="left" lit={lit} windowColor="#ffc670" frame={frame} />
        {/* уличные фонари гаснут на слове «свет» */}
        {new Array(12).fill(0).map((_, i) => (
          <Glow key={i} id={`s3-l${i}`} cx={i * 100 + 30} cy={horizon + 300} rx={60} ry={24} color="#ffb860" opacity={frame < offLight ? 0.8 : frame < offLight + 6 ? (frame % 2) * 0.8 : 0} />
        ))}
      </Layer>
      <Layer depth={0.9}>
        <Ground id="s3-g" y={horizon + 290} stops={[[0, '#0b0d10'], [1, '#040506']]} />
      </Layer>
    </Parallax>
  );

  return (
    <Scene
      scene={scene}
      grade={{tint: '#2a4560', amount: 0.4}}
      art={art}
      overlay={
        <>
          <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
            <Particles kind="ash" count={110} seed="s3-ash" wind={1.6} color="#a8a49a" />
            <Particles kind="ash" count={40} seed="s3-ash2" wind={2.4} speed={1.6} color="#cfcac0" opacity={0.6} />
          </svg>
          <Chapter text="ПЕРВЫЙ ЧАС" index={2} />
          <OutageIcons at={iconsIn} offs={[offLight, offComm, offNet]} />
        </>
      }
    />
  );
};

// ------------------------------------------------------------------ иконки
const Bulb: React.FC<{c: string}> = ({c}) => (
  <g fill="none" stroke={c} strokeWidth={7} strokeLinecap="round" strokeLinejoin="round">
    <path d="M60 18 C34 18 22 38 22 54 C22 70 34 78 40 88 L40 98 L80 98 L80 88 C86 78 98 70 98 54 C98 38 86 18 60 18 Z" />
    <path d="M44 110 L76 110 M48 122 L72 122" />
  </g>
);
const Signal: React.FC<{c: string}> = ({c}) => (
  <g fill={c}>
    {[0, 1, 2, 3].map((i) => (
      <rect key={i} x={20 + i * 22} y={100 - (i + 1) * 20} width={14} height={(i + 1) * 20 + 10} rx={3} />
    ))}
  </g>
);
const Wifi: React.FC<{c: string}> = ({c}) => (
  <g fill="none" stroke={c} strokeWidth={8} strokeLinecap="round">
    <path d="M14 52 A66 66 0 0 1 106 52" />
    <path d="M30 70 A42 42 0 0 1 90 70" />
    <path d="M46 88 A20 20 0 0 1 74 88" />
    <circle cx={60} cy={106} r={6} fill={c} stroke="none" />
  </g>
);

const OutageIcons: React.FC<{at: number; offs: number[]}> = ({at, offs}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const items = [
    {label: 'СВЕТ', Icon: Bulb},
    {label: 'СВЯЗЬ', Icon: Signal},
    {label: 'ИНТЕРНЕТ', Icon: Wifi},
  ];
  return (
    <div style={{position: 'absolute', top: 640, left: 0, right: 0, display: 'flex', justifyContent: 'center', gap: 40}}>
      {items.map(({label, Icon}, i) => {
        const s = spring({frame: frame - at - i * 4, fps, config: {damping: 16}});
        const off = offs[i];
        // мерцание перед отключением
        const dying = frame >= off - 2 && frame < off + 8;
        const isOff = frame >= off + 8 || (dying && frame % 3 !== 0);
        const color = isOff ? '#5b6370' : '#ffe39a';
        const slash = prog(frame, off + 6, off + 14);
        return (
          <div
            key={label}
            style={{
              width: 260,
              padding: '28px 0 22px',
              borderRadius: 28,
              background: 'rgba(10,14,20,0.62)',
              border: `2px solid ${isOff ? 'rgba(255,70,50,0.6)' : 'rgba(255,227,154,0.55)'}`,
              boxShadow: isOff ? 'none' : '0 0 40px rgba(255,210,120,0.35)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              opacity: s,
              transform: `translateY(${(1 - s) * 40}px) scale(${0.9 + s * 0.1})`,
            }}
          >
            <svg width={120} height={130} viewBox="0 0 120 130">
              <Icon c={color} />
              <line x1={10} y1={10} x2={10 + 100 * slash} y2={10 + 110 * slash} stroke="#ff4b33" strokeWidth={10} strokeLinecap="round" opacity={slash > 0 ? 1 : 0} />
            </svg>
            <div style={{fontFamily: FONT, fontWeight: 800, fontSize: 34, letterSpacing: '0.12em', color: isOff ? '#8a929e' : '#fff2cc', marginTop: 12}}>
              {label}
            </div>
            <div style={{fontFamily: FONT, fontWeight: 600, fontSize: 24, letterSpacing: '0.2em', color: isOff ? '#ff6b55' : '#9fe0a0', marginTop: 6}}>
              {isOff ? 'НЕТ' : 'ЕСТЬ'}
            </div>
          </div>
        );
      })}
    </div>
  );
};
