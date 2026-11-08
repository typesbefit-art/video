import React from 'react';
import {AbsoluteFill, Audio, interpolate, staticFile} from 'remotion';
import timeline from './data/timeline.json';
import {Scenes} from './Scenes';
import {Subtitles} from './Subtitles';

export const MUSIC_VOLUME = 0.09;

export const Soundtrack: React.FC<{total: number}> = ({total}) => (
  <>
    <Audio src={staticFile('voice.wav')} volume={1} />
    <Audio
      src={staticFile('music.wav')}
      volume={(f) => MUSIC_VOLUME * interpolate(f, [0, 30, total - 120, total], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}
    />
  </>
);

export const Main: React.FC = () => (
  <AbsoluteFill>
    <Scenes />
    <Subtitles />
    <Soundtrack total={timeline.durationInFrames} />
  </AbsoluteFill>
);
