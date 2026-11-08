import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import timeline from './data/timeline.json';
import {SCENES} from './scenes';
import {lerp} from './lib';

const TRANS = 14; // frames of overlap for the crossfade/slide between shots
const CONTINUOUS = new Set(['chart', 'chart30', 'disclaimer']);

const ShotWrap: React.FC<{scene: string; props: any; dur: number; transition: boolean; variant: number}> = ({scene, props, dur, transition, variant}) => {
  const frame = useCurrentFrame();
  const Comp = SCENES[scene];
  if (!Comp) throw new Error(`Unknown scene ${scene}`);
  let style: React.CSSProperties = {};
  if (transition) {
    const t = lerp(frame, [0, TRANS], [0, 1]);
    const tf = [`translateX(${(1 - t) * 140}px)`, `scale(${1.1 - 0.1 * t})`, `translateY(${(1 - t) * -100}px)`][variant % 3];
    style = {opacity: t, transform: tf};
  }
  return (
    <AbsoluteFill style={style}>
      <Comp frame={frame} dur={dur} {...props} />
    </AbsoluteFill>
  );
};

export const Scenes: React.FC = () => (
  <AbsoluteFill style={{background: '#000'}}>
    {timeline.shots.map((s, i) => {
      const prev = timeline.shots[i - 1];
      const hasNext = i < timeline.shots.length - 1;
      const transition = i > 0 && !s.cont && !(prev && prev.scene === s.scene && CONTINUOUS.has(s.scene));
      return (
        <Sequence key={i} from={s.from} durationInFrames={s.dur + (hasNext ? TRANS : 0)} layout="none">
          <ShotWrap scene={s.scene} props={s.props} dur={s.dur} transition={transition} variant={i} />
        </Sequence>
      );
    })}
  </AbsoluteFill>
);
