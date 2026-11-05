import React from 'react';
import {spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT, WHITE} from './constants';

type Props = {
  text: string;
  delay?: number; // кадр (внутри Sequence), когда появляется первое слово
  framesPerWord?: number;
  accentWords?: string[];
  accent?: string;
};

// Субтитры «слово за словом»: каждое слово выпрыгивает и чуть подпрыгивает.
// Блок стоит в зоне 1280..1480 px — внутри безопасной зоны TikTok.
export const Captions: React.FC<Props> = ({text, delay = 0, framesPerWord = 6, accentWords = [], accent = '#00E5FF'}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const words = text.split(' ');
  return (
    <div
      style={{
        position: 'absolute',
        top: 1280,
        left: 70,
        right: 70,
        height: 220,
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        alignContent: 'flex-start',
        gap: '6px 18px',
        fontFamily: FONT,
        fontWeight: 800,
        fontSize: 52,
        lineHeight: 1.2,
      }}
    >
      {words.map((w, i) => {
        const start = delay + i * framesPerWord;
        const local = frame - start;
        if (local < 0) return <span key={i} style={{opacity: 0}}>{w}</span>;
        const pop = spring({frame: local, fps, config: {damping: 7, stiffness: 220, mass: 0.6}});
        const y = (1 - pop) * 40;
        const isCurrent = local < framesPerWord + 2;
        const clean = w.replace(/[.,!?—:]/g, '').toLowerCase();
        const isAccent = accentWords.includes(clean);
        return (
          <span
            key={i}
            style={{
              display: 'inline-block',
              transform: `translateY(${y}px) scale(${0.6 + 0.4 * pop + (isCurrent ? 0.06 : 0)})`,
              opacity: Math.min(1, local / 3),
              color: isAccent ? accent : WHITE,
              textShadow: '0 4px 0 rgba(0,0,0,0.55), 0 0 18px rgba(0,0,0,0.6)',
              WebkitTextStroke: '2px rgba(0,0,0,0.6)',
            }}
          >
            {w}
          </span>
        );
      })}
    </div>
  );
};
