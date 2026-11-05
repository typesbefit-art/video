import React from 'react';
import {Composition, continueRender, delayRender, staticFile} from 'remotion';
import {ForestSurvival} from './ForestSurvival';
import {FPS, H, TOTAL_FRAMES, W} from './theme';

const fontHandle = delayRender('Loading Montserrat');
Promise.all(
  ['montserrat-cyrillic-800-normal.woff2', 'montserrat-latin-800-normal.woff2'].map((f) => {
    const face = new FontFace('Montserrat', `url(${staticFile(`fonts/${f}`)}) format('woff2')`, {
      weight: '800',
    });
    return face.load().then((loaded) => document.fonts.add(loaded));
  })
)
  .then(() => continueRender(fontHandle))
  .catch((e) => {
    console.error(e);
    continueRender(fontHandle);
  });

export const RemotionRoot: React.FC = () => (
  <Composition
    id="ForestSurvival"
    component={ForestSurvival}
    durationInFrames={TOTAL_FRAMES}
    fps={FPS}
    width={W}
    height={H}
  />
);
