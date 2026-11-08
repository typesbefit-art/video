import React from 'react';
import { Composition } from 'remotion';
import { Video } from './Video';
import timeline from './generated/timeline.json';
import type { Timeline } from './types';

const tl = timeline as unknown as Timeline;

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Short"
    component={Video}
    durationInFrames={tl.durationInFrames}
    fps={tl.fps}
    width={tl.width}
    height={tl.height}
  />
);
