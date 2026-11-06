import React from 'react';
import {Composition} from 'remotion';
import {Video, VideoProps} from './Video';
import {DURATION_IN_FRAMES, FPS} from './lib/timing';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Main"
    component={Video}
    width={1080}
    height={1920}
    fps={FPS}
    durationInFrames={DURATION_IN_FRAMES}
    defaultProps={{showSafeZone: false} satisfies VideoProps}
  />
);
