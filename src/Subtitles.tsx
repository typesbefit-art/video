import React from 'react';
import {spring, useCurrentFrame} from 'remotion';
import timeline from './data/timeline.json';
import {C, FONT, FPS} from './lib';

type Props = {offset?: number; vertical?: boolean};

export const Subtitles: React.FC<Props> = ({offset = 0, vertical}) => {
  const frame = useCurrentFrame() + offset;
  const ph = timeline.phrases;
  let idx = -1;
  for (let i = 0; i < ph.length; i++) {
    const end = Math.min(i + 1 < ph.length ? ph[i + 1].from : Infinity, ph[i].to + 24);
    if (frame >= ph[i].from - 2 && frame < end) {
      idx = i;
      break;
    }
  }
  if (idx < 0) return null;
  const p = ph[idx];
  const appear = spring({frame: frame - p.from + 2, fps: FPS, config: {damping: 14, stiffness: 200}});
  const size = vertical ? 78 : 70;
  return (
    <div
      style={{
        position: 'absolute', left: 0, right: 0,
        ...(vertical ? {top: 1250, height: 330} : {bottom: 46}),
        display: 'flex', justifyContent: 'center', alignItems: vertical ? 'flex-start' : 'flex-end', pointerEvents: 'none',
      }}
    >
      <div
        style={{
          maxWidth: vertical ? 980 : 1640, padding: vertical ? '18px 30px' : '14px 34px', borderRadius: 28,
          background: 'rgba(20,24,48,0.72)', transform: `scale(${0.9 + 0.1 * appear})`, opacity: appear,
          display: 'flex', flexWrap: 'wrap', justifyContent: 'center', rowGap: 4,
          fontFamily: FONT, fontWeight: 800, fontSize: size, lineHeight: 1.18, textAlign: 'center',
        }}
      >
        {p.words.map((w, i) => {
          const spoken = frame >= w.from;
          const nextFrom = i + 1 < p.words.length ? p.words[i + 1].from : Infinity;
          const active = spoken && frame < nextFrom;
          const s = active ? 0.97 + 0.07 * spring({frame: frame - w.from, fps: FPS, config: {damping: 10, stiffness: 300}}) : 1;
          return (
            <span
              key={i}
              style={{
                display: 'inline-block', color: active ? C.yellow : '#fff', opacity: spoken ? 1 : 0.38,
                transform: `scale(${s})`, transformOrigin: '50% 80%', margin: `0 ${size * 0.17}px`, textShadow: '0 4px 0 rgba(0,0,0,0.35)', whiteSpace: 'nowrap',
              }}
            >
              {w.text}
            </span>
          );
        })}
      </div>
    </div>
  );
};
