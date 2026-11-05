import React from 'react';
import {AbsoluteFill, Audio, getStaticFiles, interpolate, Sequence, staticFile, useVideoConfig} from 'remotion';
import './fonts';
import {Background} from './Background';
import {Starfield} from './Starfield';
import {ProgressBar} from './ProgressBar';
import {SCENES} from './constants';
import {Fact1, Fact2, Fact3, Flash, Hook, Outro} from './scenes';

// Музыка подключается, только если scripts/prepare.mjs скопировал assets/music.mp3 в public/
const hasMusic = () => getStaticFiles().some((f) => f.name === 'music.mp3');

export const SpaceFacts: React.FC = () => {
  const {durationInFrames} = useVideoConfig();
  return (
    <AbsoluteFill style={{backgroundColor: '#07011A'}}>
      <Background />
      <Starfield />

      <Sequence from={SCENES.hook.from} durationInFrames={SCENES.hook.duration} name="1. Крючок">
        <Hook />
      </Sequence>
      <Sequence from={SCENES.fact1.from} durationInFrames={SCENES.fact1.duration} name="2. Факт 1 — Венера">
        <Fact1 />
      </Sequence>
      <Sequence from={SCENES.fact2.from} durationInFrames={SCENES.fact2.duration} name="3. Факт 2 — Нептун">
        <Fact2 />
      </Sequence>
      <Sequence from={SCENES.fact3.from} durationInFrames={SCENES.fact3.duration} name="4. Факт 3 — тишина">
        <Fact3 />
      </Sequence>
      <Sequence from={SCENES.outro.from} durationInFrames={SCENES.outro.duration} name="5. Финал">
        <Outro />
      </Sequence>

      <Flash />
      <ProgressBar />

      {hasMusic() ? (
        <Audio
          src={staticFile('music.mp3')}
          volume={(f) =>
            0.15 *
            interpolate(f, [0, 20, durationInFrames - 30, durationInFrames], [0, 1, 1, 0], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            })
          }
        />
      ) : null}
    </AbsoluteFill>
  );
};
