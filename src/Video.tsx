import React from 'react';
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from 'remotion';
import timelineJson from './generated/timeline.json';
import type { Timeline } from './types';
import { Background, BgType, PALETTES } from './backgrounds';
import { getShotDef, ShotCtx } from './scenes';
import { Subtitles } from './Subtitles';
import { Headline } from './Headline';
import { pop } from './theme';

const tl = timelineJson as unknown as Timeline;
const ALT_BG: BgType[] = ['dots', 'stripes', 'rays', 'grid'];

// Resolve which shot variant + background each shot uses (stable for the whole render).
const shotPlan = tl.shots.map((sh) => {
  const scene = tl.scenes[sh.scene];
  const words = tl.words.filter((w) => w.scene === sh.scene).map((w) => ({ ...w, start: w.start - scene.start, end: w.end - scene.start }));
  const { def, index } = getShotDef(sh.visual, sh.start - scene.start, words);
  return { sh, def, index, words };
});
shotPlan.forEach((p, i) => {
  let bg = p.def.bg;
  const prev = i > 0 ? (shotPlan[i - 1] as any).bg : null;
  if (bg === prev) bg = ALT_BG.find((b) => b !== prev && b !== p.def.bg)!;
  (p as any).bg = bg;
});

function mouthAt(frame: number) {
  const a = tl.amplitude;
  const v = (a[frame - 1] ?? 0) * 0.25 + (a[frame] ?? 0) * 0.5 + (a[frame + 1] ?? 0) * 0.25;
  return Math.min(1, v * 1.15);
}

export const Video: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const time = frame / fps;

  let si = shotPlan.findIndex((p) => time >= p.sh.start && time < p.sh.end);
  if (si < 0) si = shotPlan.length - 1;
  const plan = shotPlan[si];
  const { sh, def, words } = plan;
  const scene = tl.scenes[sh.scene];
  const line = tl.lines.find((l) => time >= l.start && time <= l.end - 0.05);
  const speaker = line?.speaker ?? null;
  const mouth = mouthAt(frame);
  const palette = PALETTES[(sh.global * 3 + 1) % PALETTES.length];

  const t = time - sh.start;
  const shotDur = sh.end - sh.start;
  const ctx: ShotCtx = {
    t,
    st: time - scene.start,
    shotDur,
    sceneDur: scene.end - scene.start,
    frame,
    fps,
    k: sh.k,
    labels: scene.labels,
    maxMouth: speaker === 'max' ? mouth : 0,
    coinMouth: speaker === 'coin' ? mouth : 0,
    speaker,
    words,
  };

  // Camera: slow zoom in/out + pan + sway, with a punch-in on every cut.
  const p = t / shotDur;
  const g = sh.global;
  const zoomIn = g % 2 === 0;
  const zoom = 1.03 + 0.07 * (zoomIn ? p : 1 - p);
  const punch = 0.12 * (1 - pop(Math.round(t * fps), fps, 0, 14));
  const panX = ((g % 3) - 1) * 50 * (p - 0.5);
  const panY = (g % 2 ? 1 : -1) * 24 * (p - 0.5);
  const rot = Math.sin(time * 0.9 + g) * 0.7;
  const s = zoom + punch;
  const camera = `translate(540 960) rotate(${rot}) scale(${s}) translate(${-540 + panX} ${-960 + panY})`;

  return (
    <AbsoluteFill style={{ backgroundColor: palette[0] }}>
      <svg width={1080} height={1920} viewBox="0 0 1080 1920" style={{ position: 'absolute', inset: 0 }}>
        <g transform={camera}>
          <Background type={(plan as any).bg} palette={palette} t={time} />
          {def.render(ctx)}
        </g>
        <Wipe time={time} />
      </svg>
      <Headline scene={scene} time={time} fps={fps} titleUntil={tl.shots.find((x) => x.scene === sh.scene)!.end} />
      <Subtitles chunks={tl.subtitles} time={time} fps={fps} />
    </AbsoluteFill>
  );
};

// Diagonal colour band sweeping across the screen on every cut.
const Wipe: React.FC<{ time: number }> = ({ time }) => {
  const half = 0.13;
  const cut = tl.shots.find((s, i) => i > 0 && Math.abs(time - s.start) < half);
  if (!cut) return null;
  const p = (time - (cut.start - half)) / (2 * half); // 0..1
  const pal = PALETTES[(cut.global * 3 + 5) % PALETTES.length];
  const x = -2400 + p * 4800;
  return (
    <g transform={`translate(${540 + x} 960) rotate(18)`}>
      <rect x={-1250} y={-1800} width={2500} height={3600} fill={pal[0]} stroke="#1d1830" strokeWidth={24} />
      <rect x={-1100} y={-1800} width={120} height={3600} fill={pal[1]} />
      <rect x={980} y={-1800} width={120} height={3600} fill={pal[1]} />
    </g>
  );
};
