import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  interpolateColors,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import timeline from './timeline.json';
import {Dog, OTHER_DOG} from './Dog';
import {AlarmClock, Heart, Keys, PawPrint, Sock, Squirrel, SubscribeButton} from './Props';

export const FPS = 30;
const FONT = "'Nunito', 'Arial Rounded MT Bold', sans-serif";
const FADE = 10; // frames for colour / content transitions

type Word = {w: string; s: number; e: number};
type Line = {who: 'n' | 'd'; text: string; file: string; start: number; duration: number; words: Word[]};
type Scene = {lines: Line[]; duration: number};

const scenes = timeline.scenes as Scene[];

// Scene length = voice length + 0.4 s (rounded up to whole frames, so speech is never cut).
export const sceneFrames = scenes.map((s) => Math.ceil(s.duration * FPS));
export const sceneStarts = sceneFrames.map((_, i) => sceneFrames.slice(0, i).reduce((a, b) => a + b, 0));
export const TOTAL_FRAMES = sceneFrames.reduce((a, b) => a + b, 0);

const lineFrom = (l: Line) => Math.ceil(l.start * FPS);

// Warm backgrounds: yellow / peach / mint, one per scene.
const BG = ['#FFD84D', '#FFB894', '#9FE8CB', '#FFE36E', '#FFC7A8', '#AEEDD5', '#FFD36B', '#FFBFA3', '#B4F0DA'];

const Background: React.FC = () => {
  const f = useCurrentFrame();
  let i = 0;
  while (i < scenes.length - 1 && f >= sceneStarts[i + 1]) i++;
  const end = sceneStarts[i] + sceneFrames[i];
  let color = BG[i];
  if (i < scenes.length - 1 && f > end - FADE) {
    color = interpolateColors(f, [end - FADE, end + FADE], [BG[i], BG[i + 1]]);
  }
  if (i > 0 && f < sceneStarts[i] + FADE) {
    color = interpolateColors(f, [sceneStarts[i] - FADE, sceneStarts[i] + FADE], [BG[i - 1], BG[i]]);
  }
  // soft floating dots
  const dots = Array.from({length: 14}, (_, k) => {
    const x = (k * 263) % 1080;
    const y = ((k * 431 + f * (0.6 + (k % 3) * 0.3)) % 2100) - 100;
    const r = 30 + (k % 4) * 22;
    return <circle key={k} cx={x} cy={1920 - y} r={r} fill="#fff" opacity={0.18} />;
  });
  return (
    <AbsoluteFill style={{backgroundColor: color}}>
      <svg width={1080} height={1920}>{dots}</svg>
    </AbsoluteFill>
  );
};

/** Narrator subtitles: word by word, current word yellow. Bottom edge stays above y=1500. */
const pages = (words: Word[], max: number) => {
  const out: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    cur.push(w);
    if (cur.length >= max || /[.!?:]$/.test(w.w)) {
      out.push(cur);
      cur = [];
    }
  }
  if (cur.length) out.push(cur);
  return out;
};

const pageAt = (pg: Word[][], t: number) => {
  let idx = 0;
  for (let i = 0; i < pg.length; i++) if (t >= pg[i][0].s - 0.05) idx = i;
  return idx;
};

const currentWord = (words: Word[], t: number) => {
  let idx = -1;
  for (let i = 0; i < words.length; i++) if (t >= words[i].s) idx = i;
  return idx;
};

const NarratorCaption: React.FC<{line: Line}> = ({line}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = f / fps;
  const pg = pages(line.words, 4);
  const p = pg[pageAt(pg, t)];
  const cur = currentWord(line.words, t);
  const lastEnd = line.words[line.words.length - 1].e;
  if (t > line.duration + 0.05 && t > lastEnd + 0.3) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: 60,
        right: 60,
        top: 1260,
        height: 230,
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        alignContent: 'flex-end',
        gap: '0 36px',
        fontFamily: FONT,
        fontWeight: 900,
        fontSize: 76,
        lineHeight: 1.18,
        textAlign: 'center',
      }}
    >
      {p.map((w) => {
        const gi = line.words.indexOf(w);
        if (t < w.s) return <span key={gi} style={{opacity: 0}}>{w.w}</span>;
        const pop = spring({frame: f - Math.round(w.s * fps), fps, config: {damping: 12, stiffness: 260}});
        const active = gi === cur;
        return (
          <span
            key={gi}
            style={{
              color: active ? '#FFE14D' : '#FFFFFF',
              WebkitTextStroke: '14px #2B1A10',
              paintOrder: 'stroke fill',
              display: 'inline-block',
              transform: `scale(${interpolate(pop, [0, 1], [0.6, active ? 1.08 : 1])})`,
              textShadow: '0 6px 0 rgba(43,26,16,0.35)',
            }}
          >
            {w.w}
          </span>
        );
      })}
    </div>
  );
};

/** Dog's speech bubble: words pop in one by one with a bounce. Top stays below y=250. */
const SpeechBubble: React.FC<{line: Line; tailX: number}> = ({line, tailX}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = f / fps;
  const pg = pages(line.words, 7);
  // break dog pages only at sentence ends where possible
  const p = pg[pageAt(pg, t)];
  const cur = currentWord(line.words, t);
  const appear = spring({frame: f, fps, config: {damping: 11, stiffness: 180}});
  return (
    <div
      style={{
        position: 'absolute',
        left: 70,
        right: 70,
        top: 270,
        display: 'flex',
        justifyContent: 'center',
        transform: `scale(${appear})`,
        transformOrigin: `${tailX - 70}px 100%`,
      }}
    >
      <div
        style={{
          position: 'relative',
          background: '#FFFFFF',
          border: '9px solid #3A2414',
          borderRadius: 70,
          padding: '34px 44px',
          minHeight: 150,
          width: '100%',
          boxSizing: 'border-box',
          boxShadow: '0 14px 0 rgba(58,36,20,0.25)',
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          alignContent: 'center',
          gap: '4px 30px',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: 82,
          lineHeight: 1.15,
          color: '#3A2414',
        }}
      >
        {p.map((w) => {
          const gi = line.words.indexOf(w);
          const start = Math.round(w.s * fps);
          if (f < start) return <span key={gi} style={{opacity: 0}}>{w.w}</span>;
          const s = spring({frame: f - start, fps, config: {damping: 8, stiffness: 240, mass: 0.6}});
          const active = gi === cur && t <= w.e + 0.15;
          return (
            <span
              key={gi}
              style={{
                display: 'inline-block',
                transform: `translateY(${interpolate(s, [0, 1], [50, 0])}px) scale(${interpolate(s, [0, 1], [0.3, 1])})`,
                background: active ? '#FFE14D' : 'transparent',
                borderRadius: 18,
                padding: '0 8px',
                margin: '0 -8px',
              }}
            >
              {w.w}
            </span>
          );
        })}
        {/* tail */}
        <svg
          width={90}
          height={80}
          viewBox="0 0 90 80"
          style={{position: 'absolute', bottom: -72, left: tailX - 70 - 45 - 9}}
        >
          <path d="M8 0 L45 72 L82 0" fill="#fff" stroke="#3A2414" strokeWidth={9} strokeLinejoin="round" />
          <rect x={14} y={0} width={62} height={8} fill="#fff" />
        </svg>
      </div>
    </div>
  );
};

/** Is the dog speaking right now (inside a word)? */
const dogMouth = (lines: Line[], f: number, fps: number) => {
  for (const l of lines) {
    if (l.who !== 'd') continue;
    const t = f / fps - lineFrom(l) / fps;
    for (const w of l.words) {
      if (t >= w.s - 0.02 && t <= w.e + 0.04) {
        return 0.45 + 0.55 * Math.abs(Math.sin((t - w.s) * 14));
      }
    }
  }
  return 0;
};

const dogSpeaking = (lines: Line[], f: number, fps: number) =>
  lines.some((l) => {
    if (l.who !== 'd') return false;
    const t = (f - lineFrom(l)) / fps;
    return t >= 0 && t <= l.words[l.words.length - 1].e + 0.2;
  });

type SceneLook = {
  dogX: number;
  dogY: number;
  dogW: number;
  tilt?: (t: number) => number;
  look?: number;
  props?: (t: number) => React.ReactNode;
};

const floatHearts = (t: number, n: number, x0: number, spread: number) =>
  Array.from({length: n}, (_, k) => {
    const cycle = 80;
    const ph = (t + k * (cycle / n)) % cycle;
    const y = 1220 - ph * 6;
    const x = x0 + Math.sin((t + k * 20) * 0.06) * 40 + ((k * 137) % spread) - spread / 2;
    const op = interpolate(ph, [0, 10, cycle - 20, cycle], [0, 1, 1, 0]);
    return (
      <div key={k} style={{position: 'absolute', left: x, top: y, opacity: op, transform: `scale(${0.7 + (k % 3) * 0.2})`}}>
        <Heart size={90} color={k % 2 ? '#FF4D6D' : '#FF8FA3'} />
      </div>
    );
  });

const pawTrail = (t: number) =>
  [
    [70, 330, -20],
    [210, 250, 10],
    [800, 300, 20],
    [930, 400, -10],
    [90, 1190, 15],
    [900, 1180, -15],
  ].map(([x, y, r], k) => (
    <div
      key={k}
      style={{
        position: 'absolute',
        left: x,
        top: y,
        transform: `rotate(${r}deg) scale(${interpolate(Math.sin(t * 0.12 + k), [-1, 1], [0.85, 1.05])})`,
        opacity: 0.35,
      }}
    >
      <PawPrint size={110} />
    </div>
  ));

const LOOKS: SceneLook[] = [
  // 0 intro
  {dogX: 540, dogY: 520, dogW: 600, tilt: (t) => Math.sin(t * 0.07) * 10, props: pawTrail},
  // 1 alarm clock
  {
    dogX: 600,
    dogY: 760,
    dogW: 520,
    look: -0.6,
    props: (t) => (
      <div style={{position: 'absolute', left: 50, top: 820}}>
        <AlarmClock t={t} size={250} />
      </div>
    ),
  },
  // 2 keys
  {
    dogX: 470,
    dogY: 760,
    dogW: 520,
    look: 0.8,
    tilt: (t) => 8 + Math.sin(t * 0.1) * 6,
    props: (t) => (
      <div style={{position: 'absolute', left: 790, top: 790}}>
        <Keys t={t} size={210} />
      </div>
    ),
  },
  // 3 came back — hearts
  {dogX: 540, dogY: 760, dogW: 540, props: (t) => floatHearts(t, 6, 520, 760)},
  // 4 squirrel
  {
    dogX: 420,
    dogY: 760,
    dogW: 500,
    look: 1,
    tilt: (t) => 12 + Math.sin(t * 0.3) * 4,
    props: (t) => {
      const peek = interpolate(Math.sin(t * 0.18), [-1, 1], [0, 1]);
      return (
        <div style={{position: 'absolute', left: 790, top: 900 - peek * 40, transform: `scaleX(-1) rotate(${Math.sin(t * 0.5) * 4}deg)`}}>
          <Squirrel t={t} size={240} />
        </div>
      );
    },
  },
  // 5 other dog
  {
    dogX: 330,
    dogY: 800,
    dogW: 440,
    look: 1,
    tilt: (t) => -6 + Math.sin(t * 0.12) * 5,
    props: (t) => (
      <>
        <div style={{position: 'absolute', left: 600, top: 920}}>
          <Dog t={t + 50} colors={OTHER_DOG} width={380} flip look={1} tilt={Math.sin(t * 0.09) * 6} wag={0.6} />
        </div>
        {floatHearts(t, 3, 540, 200)}
      </>
    ),
  },
  // 6 vet + sock
  {
    dogX: 600,
    dogY: 760,
    dogW: 520,
    look: -0.4,
    tilt: (t) => -10 + Math.sin(t * 0.08) * 4,
    props: (t) => (
      <div style={{position: 'absolute', left: 60, top: 1080}}>
        <Sock t={t} size={200} />
      </div>
    ),
  },
  // 7 evening chill — slow hearts
  {dogX: 540, dogY: 760, dogW: 540, tilt: (t) => Math.sin(t * 0.05) * 7, props: (t) => floatHearts(t / 2, 4, 520, 820)},
  // 8 finale
  {dogX: 540, dogY: 330, dogW: 560, props: pawTrail},
];

const SceneView: React.FC<{scene: Scene; index: number}> = ({scene, index}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const dur = sceneFrames[index];
  const look = LOOKS[index];
  const speaking = dogSpeaking(scene.lines, f, fps);
  const mouth = dogMouth(scene.lines, f, fps);

  const fadeIn = interpolate(f, [0, FADE], [0, 1], {extrapolateRight: 'clamp'});
  const fadeOut = index === scenes.length - 1 ? 1 : interpolate(f, [dur - FADE, dur], [1, 0], {extrapolateLeft: 'clamp'});
  const enter = spring({frame: f, fps, config: {damping: 12, stiffness: 120}});

  // hop: excited bouncing while talking, gentle bob otherwise
  const hop = speaking ? Math.abs(Math.sin(f * 0.32)) * 55 : Math.abs(Math.sin(f * 0.12)) * 12;
  const squash = speaking ? 1 + Math.max(0, 0.06 - Math.abs(Math.sin(f * 0.32)) * 0.2) : 1;
  const tilt = (look.tilt ? look.tilt(f) : Math.sin(f * 0.1) * 6) + (speaking ? Math.sin(f * 0.21) * 7 : 0);
  const wave = index === scenes.length - 1 ? interpolate(f, [10, 25], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 0;
  const dogH = (look.dogW * 560) / 500;

  const narr = scene.lines.find((l) => l.who === 'n');
  const dog = scene.lines.find((l) => l.who === 'd');

  return (
    <AbsoluteFill style={{opacity: fadeIn * fadeOut}}>
      {look.props ? look.props(f) : null}
      {/* shadow */}
      <div
        style={{
          position: 'absolute',
          left: look.dogX - look.dogW * 0.32,
          top: look.dogY + dogH - 30,
          width: look.dogW * 0.64,
          height: 50,
          borderRadius: '50%',
          background: 'rgba(58,36,20,0.18)',
          transform: `scale(${1 - hop / 200})`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: look.dogX - look.dogW / 2,
          top: look.dogY - hop,
          transform: `scale(${interpolate(enter, [0, 1], [0.6, 1]) * squash}, ${interpolate(enter, [0, 1], [0.6, 1]) / squash})`,
          transformOrigin: '50% 100%',
        }}
      >
        <Dog t={f} mouth={mouth} tilt={tilt} wag={speaking ? 1.8 : 1} wave={wave} width={look.dogW} look={look.look ?? 0} />
      </div>

      {index === scenes.length - 1 ? (
        <div style={{position: 'absolute', left: 0, right: 0, top: 1030, transform: `scale(${enter})`}}>
          <SubscribeButton t={f} />
        </div>
      ) : null}

      {narr ? (
        <Sequence from={lineFrom(narr)} layout="none">
          <NarratorCaption line={narr} />
        </Sequence>
      ) : null}
      {dog ? (
        <Sequence from={lineFrom(dog)} layout="none">
          <SpeechBubble line={dog} tailX={look.dogX} />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};

export const TalkingDogs: React.FC = () => {
  return (
    <AbsoluteFill style={{fontFamily: FONT}}>
      <Background />
      {scenes.map((scene, i) => (
        <Sequence key={i} from={sceneStarts[i]} durationInFrames={sceneFrames[i]}>
          <SceneView scene={scene} index={i} />
          {scene.lines.map((l) => (
            <Sequence key={l.file} from={lineFrom(l)}>
              <Audio src={staticFile(l.file)} />
            </Sequence>
          ))}
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
