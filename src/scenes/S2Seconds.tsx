import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {Clouds, Glow, Ground, Ridge, Skyline, Sky} from '../components/art';
import {Layer, Parallax} from '../components/Parallax';
import {Particles} from '../components/Particles';
import {Scene, SceneProps} from '../components/Scene';
import {Chapter} from '../components/Title';
import {H, W, flicker, mix, mixColor, prog, shake} from '../lib/math';
import {wordFrame} from '../lib/timing';

/** 2. Первые секунды: белая вспышка, огненный шар, ударная волна, тряска. */
export const S2Seconds: React.FC<SceneProps> = ({scene, index, duration}) => {
  const frame = useCurrentFrame();
  const horizon = 1200;
  const cx = W * 0.5;
  const cy = horizon - 220;

  // синхронизация с голосом: вспышка — на «Ослепительная», волна — на «ударная»
  const t0 = Math.max(6, Math.min(wordFrame(index, 'ослепит', 1.2), duration - 90));
  const waveAt = Math.max(t0 + 30, Math.min(wordFrame(index, 'ударн', 3.0), duration - 40));
  const f = frame - t0; // кадры от момента вспышки
  const pre = f < 0; // «затишье» до вспышки: ночной город, тлеющий горизонт

  const flash = interpolate(f, [-2, 0, 3, 24], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const heat = pre ? 0 : prog(f, 0, 40); // огненный шар
  const cool = prog(f, 60, duration - t0); // шар остывает → дымовое облако
  const ballR = pre ? 0 : mix(30, 230, prog(f, 0, 50)) + mix(0, 80, cool);
  const rise = mix(0, 560, prog(f, 20, duration - t0, (t) => t));
  const wave = prog(frame, waveAt - 22, waveAt + 18, (t) => t); // 0..1 — кольцо расходится
  const sh = shake(frame, waveAt, 46, 22);
  const dust = prog(frame, waveAt, waveAt + 90); // пылевая стена накрывает центр
  const zoom = mix(1.06, 1.18, frame / duration);
  const glowI = pre ? 0.25 + 0.15 * (frame / t0) : (1 - cool * 0.55) * flicker(frame, 's2g', 0.08);

  const ballCore = mixColor('#fffbe8', '#ff7a1e', prog(f, 10, 90));
  const ballEdge = mixColor('#ffd36b', '#7a2a12', prog(f, 10, 120));

  const art = (
    <Parallax camera={{zoom, x: 0, y: mix(0, 30, frame / duration)}} shake={sh} focus={{x: cx, y: cy}}>
      <Layer depth={0.05}>
        <Sky id="s2-sky" stops={[[0, '#0d1018'], [0.45, mixColor('#1e2638', mixColor('#5a2a1c', '#2a1d1d', cool), heat)], [0.62, mixColor('#5a3036', mixColor('#ff8a3a', '#7a3a22', cool), heat)], [1, '#140b08']]} />
        <Glow id="s2-skyglow" cx={cx} cy={cy - rise * 0.5} rx={1100} ry={900} color="#ff6a1e" opacity={0.55 * glowI} falloff={0.3} />
      </Layer>

      <Layer depth={0.15}>
        <Ridge seed="s2-m" baseY={horizon - 10} amp={110} color="#2a1a18" top={mixColor('#6a3030', mixColor('#ff9a4a', '#5a2a1e', cool), heat)} />
        {/* «ножка» облака */}
        <defs>
          <linearGradient id="s2-stem" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={ballEdge} stopOpacity={0.9} />
            <stop offset="1" stopColor="#3a2420" stopOpacity={0.95} />
          </linearGradient>
          <radialGradient id="s2-ball">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset="0.35" stopColor={ballCore} />
            <stop offset="0.8" stopColor={ballEdge} />
            <stop offset="1" stopColor={ballEdge} stopOpacity={0} />
          </radialGradient>
        </defs>
        <path
          d={`M${cx - 70 - cool * 30},${horizon} C${cx - 40},${cy - rise * 0.5} ${cx - 50},${cy - rise * 0.8} ${cx - 40},${cy - rise} L${cx + 40},${cy - rise} C${cx + 50},${cy - rise * 0.8} ${cx + 40},${cy - rise * 0.5} ${cx + 70 + cool * 30},${horizon} Z`}
          fill="url(#s2-stem)"
          opacity={prog(f, 25, 70)}
        />
        {/* шапка облака из клубов */}
        <Clouds seed="s2-cap" y={cy - rise} spread={ballR * 0.6} count={12} size={0.35 + cool * 0.6} color={mixColor('#ff7a2a', '#4a2c26', cool)} opacity={prog(f, 30, 80) * 0.95} drift={0.05} blur={22} frame={frame} />
        <circle cx={cx} cy={cy - rise} r={ballR} fill="url(#s2-ball)" opacity={1 - cool * 0.6} />
        <Glow id="s2-ballglow" cx={cx} cy={cy - rise} rx={ballR * 3.2} color="#ffb35a" opacity={heat * glowI * 0.75} />
      </Layer>

      <Layer depth={0.35}>
        {/* ударная волна: кольцо по земле + купол в воздухе */}
        <ellipse cx={cx} cy={horizon + 10} rx={wave * 1700} ry={wave * 340} fill="none" stroke="#fff3dc" strokeWidth={mix(18, 4, wave)} opacity={(1 - wave) * (wave > 0 ? 0.9 : 0)} />
        <ellipse cx={cx} cy={horizon + 10} rx={wave * 1500} ry={wave * 1100} fill="none" stroke="#ffd9a8" strokeWidth={mix(10, 2, wave)} opacity={(1 - wave) * (wave > 0 ? 0.45 : 0)} />
        <Skyline seed="s2-far" baseY={horizon + 60} minH={50} maxH={200} scale={0.6} color="#1a0f0d" rim="#ffb060" rimSide="left" rimOpacity={0.7 * glowI} />
      </Layer>

      <Layer depth={0.55}>
        <g transform={`translate(0 ${dust * 40})`}>
          <Skyline seed="s2-city" baseY={horizon + 300} minH={120} maxH={430} color="#07070a" rim="#ff9a4a" rimSide="left" rimOpacity={0.6 * glowI} />
        </g>
        {/* пылевая стена после прохода волны */}
        <Clouds seed="s2-dust" y={horizon + 120 - dust * 260} spread={260} count={14} size={1.3} color="#3b2a22" opacity={dust * 0.92} drift={1.5} blur={40} frame={frame} />
      </Layer>

      <Layer depth={0.85}>
        <Ground id="s2-g" y={horizon + 270} stops={[[0, '#160c08'], [1, '#050404']]} />
        <Particles kind="debris" count={70} seed="s2-deb" startFrame={waveAt} area={{x: -200, y: horizon - 300, w: W, h: 700}} />
      </Layer>
    </Parallax>
  );

  return (
    <Scene
      scene={scene}
      fadeIn={0}
      grade={{tint: '#7a2a10', amount: 0.25, lift: '#140806'}}
      art={art}
      overlay={
        <>
          <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
            <Particles kind="embers" count={70} seed="s2-emb" wind={1.2} speed={1.2} area={{x: 0, y: 300, w: W, h: 1500}} opacity={heat} />
            <Particles kind="ash" count={60} seed="s2-ash" wind={2} opacity={dust} color="#8a7a70" />
          </svg>
          <Chapter text="ПЕРВЫЕ СЕКУНДЫ" index={1} at={18} />
          {/* белая вспышка */}
          <AbsoluteFill style={{background: '#fff', opacity: flash}} />
          <AbsoluteFill style={{background: '#ffe2b0', opacity: interpolate(frame, [waveAt, waveAt + 4, waveAt + 14], [0, 0.35, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}), mixBlendMode: 'screen'}} />
        </>
      }
    />
  );
};
