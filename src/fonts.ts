import {continueRender, delayRender, staticFile} from 'remotion';

const load = (family: string, file: string, weight: string) => {
  if (typeof FontFace === 'undefined') return;
  const handle = delayRender(`Loading font ${file}`);
  const face = new FontFace(family, `url('${staticFile(file)}') format('opentype')`, {weight});
  face
    .load()
    .then(() => {
      (document.fonts as unknown as {add: (f: FontFace) => void}).add(face);
      continueRender(handle);
    })
    .catch((err) => {
      console.error('Font load failed', err);
      continueRender(handle);
    });
};

load('InterBlack', 'fonts/Inter-Black.otf', '900');
load('InterBlack', 'fonts/Inter-ExtraBold.otf', '800');
