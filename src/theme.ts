import timelineJson from './timeline.json';

export const W = 1080;
export const H = 1920;
export const FPS = 30;

export const COLORS = {
  bgTop: '#0b1f17',
  bgBottom: '#1d3b2a',
  cream: '#F6EEDC',
  accent: '#FFB347',
  ember: '#FF7A2A',
  firefly: '#FFD66B',
};

export const FONT = "'Montserrat', 'Arial Black', sans-serif";

// TikTok safe zone for text: between y=250 and y=1500.
export const SAFE_TOP = 250;
export const SAFE_BOTTOM = 1500;

export type Word = {text: string; start: number; end: number};
export type SceneData = {
  id: string;
  text: string;
  audio: string;
  audioDuration: number;
  durationInFrames: number;
  words: Word[];
};

export const SCENES: (SceneData & {from: number})[] = (() => {
  let from = 0;
  return (timelineJson.scenes as SceneData[]).map((s) => {
    const out = {...s, from};
    from += s.durationInFrames;
    return out;
  });
})();

export const TOTAL_FRAMES = SCENES.reduce((a, s) => a + s.durationInFrames, 0);
