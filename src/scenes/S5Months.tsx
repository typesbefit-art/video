import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {Clouds, CropField, Ground, Ridge, Sky, Sun} from '../components/art';
import {Layer, Parallax} from '../components/Parallax';
import {Particles} from '../components/Particles';
import {Scene, SceneProps} from '../components/Scene';
import {Chapter, Title} from '../components/Title';
import {FONT} from '../lib/fonts';
import {H, SAFE, W, mix, mixColor, prog} from '../lib/math';
import {wordFrame} from '../lib/timing';

/** 5. Первые месяцы: сажа закрывает солнце, холод, гибнущий урожай. «ЯДЕРНАЯ ЗИМА». */
export const S5Months: React.FC<SceneProps> = ({scene, index, duration}) => {
  const frame = useCurrentFrame();
  const horizon = 1080;

  const tempAt = wordFrame(index, 'температур', 4.2);
  const cropAt = wordFrame(index, 'урожа', 5.6);
  const titleAt = wordFrame(index, 'ядерн', 7.2);

  const soot = prog(frame, 0, tempAt + 20); // небо затягивает
  const cold = prog(frame, tempAt, duration);
  const wither = prog(frame, cropAt - 10, cropAt + 70);
  const zoom = mix(1.0, 1.1, frame / duration);

  const art = (
    <Parallax camera={{zoom, x: 0, y: mix(-20, 20, frame / duration)}}>
      <Layer depth={0.04}>
        <Sky
          id="s5-sky"
          stops={[
            [0, '#0e0f12'],
            [0.35, mixColor('#3a3e48', '#1e1f22', soot)],
            [0.55, mixColor('#7a7466', '#3c3a36', soot)],
            [1, '#202226'],
          ]}
        />
        {/* солнце еле видно сквозь сажу */}
        <Sun id="s5-sun" cx={W * 0.62} cy={560} r={70} core="#d9cfb4" glow="#b8a686" glowR={4} opacity={mix(0.85, 0.22, soot)} />
        <Clouds seed="s5-soot1" y={470} spread={600} count={14} size={1.4} color="#18181a" opacity={mix(0.35, 0.92, soot)} drift={0.7} blur={45} frame={frame} />
        <Clouds seed="s5-soot2" y={780} spread={300} count={10} size={1.1} color="#2e2c2a" opacity={mix(0.2, 0.75, soot)} drift={1.1} blur={35} frame={frame} />
      </Layer>
      <Layer depth={0.18}>
        <Ridge seed="s5-m" baseY={horizon} amp={110} color={mixColor('#3a3d44', '#4c5058', cold)} top={mixColor('#5c5a56', '#d6dde4', cold)} />
      </Layer>
      <Layer depth={0.5}>
        <Ground id="s5-g" y={horizon + 40} stops={[[0, mixColor('#4a4636', '#8d959d', cold)], [1, mixColor('#1a1812', '#3a4048', cold)]]} />
        {/* иней — светлые штрихи по полю */}
        <g opacity={cold * 0.6}>
          {new Array(40).fill(0).map((_, i) => (
            <rect key={i} x={(i * 137) % W} y={horizon + 60 + ((i * 89) % 700)} width={60 + (i % 5) * 30} height={3} fill="#eaf2f8" />
          ))}
        </g>
      </Layer>
      <Layer depth={0.95}>
        <CropField seed="s5-crop" y={horizon + 60} frame={frame} wither={wither} frost={cold} />
      </Layer>
    </Parallax>
  );

  return (
    <Scene
      scene={scene}
      grade={{tint: mixColor('#3a3a3a', '#2a4a6a', cold), amount: 0.45, lift: '#0c1016'}}
      art={art}
      overlay={
        <>
          <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
            <Particles kind="ash" count={80} seed="s5-ash" wind={1.2} color="#6a6460" opacity={1 - cold * 0.5} />
            <Particles kind="snow" count={90} seed="s5-snow" wind={1.8} opacity={cold} />
          </svg>
          <Chapter text="ПЕРВЫЕ МЕСЯЦЫ" index={4} />
          <Thermometer at={tempAt} />
          <Title text={scene.title} at={titleAt} variant="ice" size={124} top={SAFE.top + 520} />
        </>
      }
    />
  );
};

/** Термометр: +15 °C → −25 °C на слове «температура». */
const Thermometer: React.FC<{at: number}> = ({at}) => {
  const frame = useCurrentFrame();
  const t = prog(frame, at, at + 75);
  const appear = interpolate(frame, [at - 10, at], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const temp = Math.round(mix(15, -25, t));
  const fill = mix(0.75, 0.12, t);
  const col = mixColor('#ff7a3a', '#7cc8ff', t);
  return (
    <div style={{position: 'absolute', top: SAFE.top + 150, right: SAFE.side + 20, opacity: appear, display: 'flex', alignItems: 'center', gap: 22}}>
      <div style={{fontFamily: FONT, fontWeight: 900, fontSize: 72, color: col, textShadow: '0 4px 20px rgba(0,0,0,0.8)'}}>
        {temp > 0 ? `+${temp}` : temp}°
      </div>
      <svg width={70} height={300} viewBox="0 0 70 300">
        <rect x={22} y={10} width={26} height={240} rx={13} fill="rgba(10,14,20,0.6)" stroke="#dfe8f0" strokeWidth={4} />
        <rect x={28} y={16 + 228 * (1 - fill)} width={14} height={228 * fill + 20} rx={7} fill={col} />
        <circle cx={35} cy={262} r={28} fill={col} stroke="#dfe8f0" strokeWidth={4} />
        {[0, 1, 2, 3, 4].map((i) => (
          <rect key={i} x={50} y={40 + i * 45} width={12} height={3} fill="#dfe8f0" />
        ))}
      </svg>
    </div>
  );
};
