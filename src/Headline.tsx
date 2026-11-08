import React from 'react';
import type { Scene } from './types';
import { C, FONT, INK, fitFontSize, pop } from './theme';

// Scene title at the top (inside the 120 px side margins, below the status area).
// The big title is shown only during the scene's first shot; afterwards only the badge stays.
export const Headline: React.FC<{ scene: Scene; time: number; fps: number; titleUntil: number }> = ({ scene, time, fps, titleUntil }) => {
  const L = scene.labels || {};
  const st = time - scene.start;
  const f = Math.round(st * fps);
  const a = pop(f, fps, 2, 10);
  const out = Math.max(0, Math.min(1, (titleUntil - time) / 0.18));
  const b = pop(f, fps, 10, 10) * out;
  const maxW = 840;
  const titleSize = fitFontSize(String(L.title ?? ''), maxW - 30, 104);
  const badgeSize = fitFontSize(String(L.badge ?? ''), maxW - 120, 50);
  const wob = Math.sin(time * 2.4) * 1.5;
  return (
    <div style={{ position: 'absolute', left: 120, right: 120, top: 210, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18, fontFamily: FONT, fontWeight: 900 }}>
      {L.badge ? (
        <div
          style={{
            transform: `scale(${a}) rotate(${-2 + wob * 0.5}deg)`,
            background: C.red,
            color: '#fff',
            border: `8px solid ${INK}`,
            borderRadius: 999,
            padding: '8px 40px 12px',
            fontSize: badgeSize,
            boxShadow: `0 8px 0 ${INK}`,
            whiteSpace: 'nowrap',
          }}
        >
          {L.badge}
        </div>
      ) : null}
      {L.title && b > 0.01 ? (
        <div
          style={{
            transform: `scale(${b}) rotate(${wob * 0.6}deg)`,
            color: C.yellow,
            fontSize: titleSize,
            lineHeight: 1.05,
            WebkitTextStroke: `16px ${INK}`,
            paintOrder: 'stroke fill',
            textShadow: `0 10px 0 ${INK}`,
            whiteSpace: 'nowrap',
            textAlign: 'center',
          }}
        >
          {L.title}
        </div>
      ) : null}
    </div>
  );
};
