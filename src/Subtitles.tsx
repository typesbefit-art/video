import React from 'react';
import type { SubChunk } from './types';
import { C, FONT, INK, fitFontSize, pop } from './theme';

// Safe zone for Shorts/Reels UI: text never below y=1480 (limit 1500) and
// never closer than 120 px to the left/right edges.
export const SUB_SAFE = { left: 120, right: 120, bottom: 1480, maxLines: 2 };
const MAX_W = 1080 - SUB_SAFE.left - SUB_SAFE.right; // 840
const BASE = 92;
const STROKE_W = 16;

export const Subtitles: React.FC<{ chunks: SubChunk[]; time: number; fps: number }> = ({ chunks, time, fps }) => {
  const chunk = chunks.find((c) => time >= c.start - 0.05 && time < c.hideAt);
  if (!chunk) return null;
  const texts = chunk.words.map((w) => w.text);
  // each word must fit on its own line; the whole chunk may wrap onto 2 lines
  const longest = Math.max(...texts.map((w) => fitFontSize(w, MAX_W - 2 * STROKE_W, BASE)));
  const full = fitFontSize(texts.join(' '), (MAX_W - 2 * STROKE_W) * SUB_SAFE.maxLines * 0.92, BASE);
  const fontSize = Math.min(longest, full);
  const enter = pop(Math.round((time - chunk.start + 0.05) * fps), fps, 0, 12);
  const color = chunk.speaker === 'coin' ? C.yellow : '#7ef0ff';

  return (
    <div
      style={{
        position: 'absolute',
        left: SUB_SAFE.left,
        right: SUB_SAFE.right,
        bottom: 1920 - SUB_SAFE.bottom,
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        alignContent: 'flex-end',
        columnGap: fontSize * 0.38,
        rowGap: 0,
        transform: `scale(${0.85 + 0.15 * enter})`,
        transformOrigin: '50% 100%',
        fontFamily: FONT,
        fontWeight: 900,
        fontSize,
        lineHeight: 1.12,
        textTransform: 'uppercase',
      }}
    >
      {chunk.words.map((w, i) => {
        const active = time >= w.start - 0.03 && time < (chunk.words[i + 1]?.start ?? chunk.hideAt);
        const spoken = time >= w.start - 0.03;
        const wp = active ? pop(Math.round((time - w.start + 0.03) * fps), fps, 0, 9) : 0;
        return (
          <span
            key={i}
            style={{
              display: 'inline-block',
              color: active ? color : '#ffffff',
              opacity: spoken ? 1 : 0.92,
              WebkitTextStroke: `${STROKE_W}px ${INK}`,
              paintOrder: 'stroke fill',
              textShadow: `0 8px 0 ${INK}`,
              transform: `scale(${1 + 0.07 * wp}) translateY(${-6 * wp}px)`,
              transformOrigin: '50% 80%',
              whiteSpace: 'nowrap',
            }}
          >
            {w.text}
          </span>
        );
      })}
    </div>
  );
};
