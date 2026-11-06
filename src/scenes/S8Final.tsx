import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Birds, Clouds, Ground, Ridge, Skyline, Sky, Sun} from '../components/art';
import {Layer, Parallax} from '../components/Parallax';
import {Particles} from '../components/Particles';
import {Scene, SceneProps} from '../components/Scene';
import {FONT} from '../lib/fonts';
import {H, W, mix} from '../lib/math';
import {wordFrame} from '../lib/timing';

/** 8. Финал: чистое небо, мирный город. В конце — кнопка «ПОДПИШИСЬ». */
export const S8Final: React.FC<SceneProps> = ({scene, index, duration}) => {
  const frame = useCurrentFrame();
  const horizon = 1150;
  const ctaAt = Math.min(wordFrame(index, 'подпиш', 4.6) - 6, duration - 45);
  const zoom = mix(1.12, 1.0, frame / duration);

  const art = (
    <Parallax camera={{zoom, x: 0, y: mix(-30, 0, frame / duration)}}>
      <Layer depth={0.04}>
        <Sky id="s8-sky" stops={[[0, '#2f6fae'], [0.45, '#79aee0'], [0.62, '#cfe4f2'], [1, '#8fb0c8']]} />
        <Sun id="s8-sun" cx={W * 0.76} cy={380} r={60} core="#fffbe8" glow="#fff0c0" glowR={5} />
        <Clouds seed="s8-c" y={560} spread={420} count={8} color="#ffffff" opacity={0.6} drift={0.4} blur={28} frame={frame} />
      </Layer>
      <Layer depth={0.15}>
        <Ridge seed="s8-m" baseY={horizon} amp={140} color="#6a8aa4" top="#a8c4d8" />
      </Layer>
      <Layer depth={0.3}>
        <Ridge seed="s8-h" baseY={horizon + 60} amp={70} color="#4f7a5a" top="#7aa870" freq={0.006} />
        <Skyline seed="s8-far" baseY={horizon + 90} minH={60} maxH={260} scale={0.6} color="#7b8fa3" rim="#e8f0f6" rimOpacity={0.4} />
      </Layer>
      <Layer depth={0.55}>
        <Skyline seed="s8-city" baseY={horizon + 330} minH={160} maxH={640} color="#3c4e62" rim="#fff2d4" rimSide="right" rimOpacity={0.55} lit={0.25} windowColor="#ffe6a8" frame={frame} />
        <Birds frame={frame} x={W * 0.1} y={720} count={9} color="#2a3646" />
      </Layer>
      <Layer depth={0.85}>
        <Ground id="s8-g" y={horizon + 320} stops={[[0, '#3f6a3e'], [1, '#1c3220']]} />
        {/* деревья на переднем плане */}
        {[60, 210, 860, 1010].map((x, i) => (
          <g key={i} fill={i % 2 ? '#20402a' : '#26492f'}>
            <rect x={x - 8} y={H - 360} width={16} height={140} fill="#2a2018" />
            <ellipse cx={x} cy={H - 400} rx={90} ry={120} />
            <ellipse cx={x - 40} cy={H - 360} rx={60} ry={70} />
            <ellipse cx={x + 45} cy={H - 350} rx={60} ry={70} />
          </g>
        ))}
      </Layer>
    </Parallax>
  );

  return (
    <Scene
      scene={scene}
      grade={{tint: '#3a6a9a', amount: 0.15, lift: '#0a1018'}}
      vignette={0.55}
      art={art}
      overlay={
        <>
          <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
            <Particles kind="dust" count={40} seed="s8-dust" color="#ffffff" opacity={0.6} />
          </svg>
          <SubscribeButton at={ctaAt} />
        </>
      }
    />
  );
};

/** Кнопка-призыв «ПОДПИШИСЬ» с колокольчиком и «нажатием». */
const SubscribeButton: React.FC<{at: number}> = ({at}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const f = frame - at;
  if (f < 0) return null;
  const s = spring({frame: f, fps, config: {damping: 11, stiffness: 160}});
  const press = interpolate(f, [26, 30, 36], [1, 0.92, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const pulse = 1 + Math.max(0, Math.sin((f - 36) * 0.18)) * 0.04 * (f > 36 ? 1 : 0);
  const bell = Math.sin(f * 0.9) * 18 * Math.exp(-Math.max(0, f - 30) / 20) * (f > 30 ? 1 : 0);
  const ring = interpolate(f, [30, 60], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  return (
    <div style={{position: 'absolute', top: 760, left: 0, right: 0, display: 'flex', justifyContent: 'center'}}>
      <div style={{position: 'relative', transform: `scale(${s * press * pulse})`}}>
        {/* расходящееся кольцо после нажатия */}
        <div
          style={{
            position: 'absolute',
            inset: -20,
            borderRadius: 999,
            border: '4px solid rgba(255,255,255,0.8)',
            opacity: ring > 0 ? 1 - ring : 0,
            transform: `scale(${1 + ring * 0.35})`,
          }}
        />
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 26,
            padding: '34px 64px',
            borderRadius: 999,
            background: 'linear-gradient(180deg, #ff3b30 0%, #d61f1f 100%)',
            boxShadow: '0 20px 60px rgba(160,0,0,0.45), inset 0 2px 0 rgba(255,255,255,0.35)',
          }}
        >
          <svg width={78} height={78} viewBox="0 0 24 24" style={{transform: `rotate(${bell}deg)`, transformOrigin: '50% 10%'}}>
            <path
              fill="#fff"
              d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5.5-6.84V3.5a1.5 1.5 0 0 0-3 0v.66A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2Z"
            />
          </svg>
          <span style={{fontFamily: FONT, fontWeight: 900, fontSize: 82, color: '#fff', letterSpacing: '0.03em', textShadow: '0 3px 10px rgba(0,0,0,0.3)'}}>
            ПОДПИШИСЬ
          </span>
        </div>
      </div>
    </div>
  );
};
