import React from 'react';
import {Composition} from 'remotion';
import {SpaceFacts} from './SpaceFacts';
import {DURATION, FPS, HEIGHT, WIDTH} from './constants';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="SpaceFacts"
    component={SpaceFacts}
    durationInFrames={DURATION}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
  />
);
