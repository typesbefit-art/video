export type Speaker = 'max' | 'coin';
export type Word = { text: string; start: number; end: number; scene: number; line: number; speaker: Speaker };
export type Line = { scene: number; index: number; speaker: Speaker; start: number; end: number; audioDur: number };
export type Scene = { id: string; visual: string; index: number; start: number; end: number; labels: Record<string, any> };
export type Shot = { scene: number; visual: string; k: number; start: number; end: number; global: number };
export type SubChunk = { words: { text: string; start: number; end: number }[]; start: number; end: number; hideAt: number; speaker: Speaker };
export type Timeline = {
  fps: number; width: number; height: number; durationInFrames: number; total: number; title: string;
  scenes: Scene[]; lines: Line[]; shots: Shot[]; subtitles: SubChunk[]; words: Word[]; amplitude: number[];
};
