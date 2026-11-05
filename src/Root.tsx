import '@fontsource/nunito/800.css';
import '@fontsource/nunito/900.css';
import React from 'react';
import {Composition, continueRender, delayRender} from 'remotion';
import {FPS, TOTAL_FRAMES, TalkingDogs} from './TalkingDogs';

const fontHandle = delayRender('Loading Nunito');
Promise.all([
  document.fonts.load("900 80px 'Nunito'", 'Собака говорит'),
  document.fonts.load("900 80px 'Nunito'", 'Dog'),
])
  .then(() => continueRender(fontHandle))
  .catch(() => continueRender(fontHandle));

export const RemotionRoot: React.FC = () => (
  <Composition
    id="TalkingDogs"
    component={TalkingDogs}
    durationInFrames={TOTAL_FRAMES}
    fps={FPS}
    width={1080}
    height={1920}
  />
);
