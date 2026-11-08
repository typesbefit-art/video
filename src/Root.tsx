import React from 'react';
import {Composition} from 'remotion';
import './fonts';
import timeline from './data/timeline.json';
import {Main} from './Main';
import {Short} from './Short';

export const Root: React.FC = () => (
  <>
    <Composition id="Main" component={Main} durationInFrames={timeline.durationInFrames} fps={60} width={1920} height={1080} />
    {timeline.shorts.map((s, i) => (
      <Composition key={i} id={`Short${i + 1}`} component={Short} defaultProps={{index: i}}
        durationInFrames={s.to - s.from} fps={60} width={1080} height={1920} />
    ))}
  </>
);
