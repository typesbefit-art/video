import React from "react";
import { AbsoluteFill, random, useCurrentFrame } from "remotion";

export type ShakeHit = { frame: number; intensity: number; duration?: number };

/** Смещение камеры от набора ударов: затухающие колебания, без линейных движений. */
export const shakeOffset = (frame: number, hits: ShakeHit[]) => {
  let x = 0;
  let y = 0;
  let r = 0;
  for (const h of hits) {
    const d = h.duration ?? 12;
    const f = frame - h.frame;
    if (f < 0 || f > d) continue;
    const decay = Math.pow(1 - f / d, 2);
    const ph = random(`shake-${h.frame}`) * Math.PI * 2;
    x += h.intensity * decay * Math.sin(f * 2.1 + ph);
    y += h.intensity * decay * Math.cos(f * 2.7 + ph);
    r += h.intensity * 0.04 * decay * Math.sin(f * 1.7 + ph);
  }
  return { x, y, r };
};

/** Короткий screen shake на ударах. Оборачивает всё, что должно трястись. */
export const Shake: React.FC<{ hits: ShakeHit[]; children: React.ReactNode }> = ({ hits, children }) => {
  const frame = useCurrentFrame();
  const { x, y, r } = shakeOffset(frame, hits);
  return (
    <AbsoluteFill style={{ transform: `translate(${x}px, ${y}px) rotate(${r}deg) scale(1.03)` }}>
      {children}
    </AbsoluteFill>
  );
};
