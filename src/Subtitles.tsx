import React from 'react';
import {interpolate} from 'remotion';
import {COLORS, FONT, Word} from './theme';

const MAX_WORDS = 6;

/** Split words into short pages: break on sentence/colon ends, long chunks, or commas in mid-length chunks. */
export const paginate = (words: Word[]): Word[][] => {
  const pages: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    cur.push(w);
    const end = /[.?!:]$/.test(w.text);
    const comma = /,$/.test(w.text) && cur.length >= 3;
    if (end || comma || cur.length >= MAX_WORDS) {
      pages.push(cur);
      cur = [];
    }
  }
  if (cur.length) pages.push(cur);
  return pages;
};

type Props = {
  words: Word[];
  t: number; // seconds since scene start
  fontSize: number;
  top: number;
  height: number;
};

/** Big centered karaoke subtitles: words appear one by one, the spoken word glows orange. */
export const Subtitles: React.FC<Props> = ({words, t, fontSize, top, height}) => {
  const pages = paginate(words);
  let pageIdx = 0;
  for (let i = 0; i < pages.length; i++) if (t >= pages[i][0].start - 0.05) pageIdx = i;
  const page = pages[pageIdx];
  const nextPageStart = pages[pageIdx + 1]?.[0].start ?? Infinity;

  return (
    <div
      style={{
        position: 'absolute',
        left: 70,
        right: 70,
        top,
        height,
        display: 'flex',
        flexWrap: 'wrap',
        alignContent: 'center',
        justifyContent: 'center',
        columnGap: fontSize * 0.28,
        rowGap: fontSize * 0.12,
        fontFamily: FONT,
        fontWeight: 800,
        fontSize,
        lineHeight: 1.18,
        textAlign: 'center',
      }}
    >
      {page.map((w, i) => {
        const next = page[i + 1]?.start ?? nextPageStart;
        const shown = t >= w.start - 0.05;
        if (!shown) return null; // only spoken words take space, so the line stays centered
        const current = t < Math.max(next, w.end) - 0.02;
        const appear = interpolate(t, [w.start - 0.05, w.start + 0.12], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        return (
          <span
            key={`${pageIdx}-${i}`}
            style={{
              display: 'inline-block',
              opacity: appear,
              transform: `translateY(${(1 - appear) * 18}px) scale(${current ? 1.06 : 1})`,
              color: current ? COLORS.accent : COLORS.cream,
              textShadow: current
                ? '0 0 28px rgba(255,179,71,0.55), 0 4px 14px rgba(0,0,0,0.6)'
                : '0 4px 14px rgba(0,0,0,0.6)',
            }}
          >
            {w.text}
          </span>
        );
      })}
    </div>
  );
};
