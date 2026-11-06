import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Birds, Glow, PowerLines, Ridge, Skyline, Sky, Sun, Clouds, Ground} from '../components/art';
import {Layer, Parallax} from '../components/Parallax';
import {Particles} from '../components/Particles';
import {Scene, SceneProps} from '../components/Scene';
import {Title} from '../components/Title';
import {H, W, flicker, mix, mixColor, prog} from '../lib/math';

/** 1. Хук: тихий город на закате → тревожный красный свет на горизонте. */
export const S1Hook: React.FC<SceneProps> = ({scene, duration}) => {
  const frame = useCurrentFrame();
  const alarm = prog(frame, duration * 0.42, duration * 0.9); // нарастание тревоги
  const pulse = 0.75 + 0.25 * Math.sin(frame * 0.18);
  const zoom = mix(1.0, 1.12, frame / duration);
  const horizon = 1180;

  const art = (
    <Parallax camera={{zoom, x: 0, y: mix(0, -40, frame / duration)}}>
      <Layer depth={0.05}>
        <Sky
          id="s1-sky"
          stops={[
            [0, mixColor('#1d2a44', '#1a0f18', alarm)],
            [0.35, mixColor('#41506e', '#4a1c22', alarm)],
            [0.55, mixColor('#c0806a', '#a3342a', alarm)],
            [0.64, mixColor('#f2b37a', '#ff5a2e', alarm)],
            [1, '#2a1a1a'],
          ]}
        />
        <Sun id="s1-sun" cx={W * 0.68} cy={horizon - 150 + frame * 0.35} r={46} opacity={1 - alarm * 0.6} glowR={7} />
        <Clouds seed="s1-c" y={560} spread={380} count={9} color={mixColor('#c98d7a', '#7a2c2a', alarm)} opacity={0.55} drift={0.25} frame={frame} />
      </Layer>
      <Layer depth={0.15}>
        {/* тревожное красное зарево на горизонте */}
        <Glow id="s1-alarm" cx={W * 0.3} cy={horizon - 40} rx={900} ry={260} color="#ff2a12" opacity={alarm * pulse * 0.9} />
        <Ridge seed="s1-m" baseY={horizon - 30} amp={140} color={mixColor('#5d5a6e', '#4a2830', alarm)} top={mixColor('#b07a74', '#c04030', alarm)} />
      </Layer>
      <Layer depth={0.3}>
        <Skyline seed="s1-far" baseY={horizon + 40} minH={60} maxH={260} scale={0.6} color={mixColor('#3a3d4f', '#3a2228', alarm)} lit={0.25} windowColor="#ffd59a" frame={frame} />
      </Layer>
      <Layer depth={0.55}>
        <Skyline
          seed="s1-city"
          baseY={horizon + 260}
          minH={160}
          maxH={720}
          color="#141820"
          rim={mixColor('#ffb27a', '#ff4a2a', alarm)}
          rimSide="right"
          rimOpacity={0.55}
          lit={0.32}
          windowColor="#ffcf7a"
          frame={frame}
        />
        <Birds frame={frame} x={W * 0.15} y={760} />
      </Layer>
      <Layer depth={0.85}>
        <Ground id="s1-g" y={horizon + 250} stops={[[0, '#0c0e13'], [1, '#050608']]} />
        <PowerLines y={H - 280} color="#07080b" scale={1.1} />
      </Layer>
    </Parallax>
  );

  return (
    <Scene
      scene={scene}
      fadeIn={0}
      grade={{tint: mixColor('#2b4a6b', '#6b1a12', alarm), amount: 0.3}}
      art={art}
      overlay={
        <>
          <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
            <Particles kind="dust" count={40} seed="s1-dust" opacity={0.8} />
            {/* мигающий красный свет — тревога */}
            <rect width={W} height={H} fill="#ff1a0a" opacity={alarm * 0.12 * flicker(frame, 's1', 0.5)} style={{mixBlendMode: 'overlay'}} />
          </svg>
          <Title text={scene.title} at={8} size={104} variant="white" />
        </>
      }
    />
  );
};
