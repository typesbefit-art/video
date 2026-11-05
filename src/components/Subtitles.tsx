import React from "react";
import { AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export type SubtitleLine = { from: number; to: number; text: string };

/**
 * Большие субтитры внизу по центру: белый текст, чёрная обводка,
 * слова появляются по одному со spring-«выпрыгиванием». Тайминги — в секундах.
 */
export const Subtitles: React.FC<{ lines: SubtitleLine[]; bottom?: number; fontSize?: number }> = ({
  lines,
  bottom = 150,
  fontSize = 78,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const line = lines.find((l) => frame >= l.from * fps && frame < l.to * fps);
  if (!line) return null;

  const start = Math.round(line.from * fps);
  const end = Math.round(line.to * fps);
  const words = line.text.split(/\s+/).filter(Boolean);
  const wordDelay = Math.max(2, Math.min(6, Math.floor(((end - start) * 0.4) / words.length)));
  const exit = interpolate(frame, [end - 7, end], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.in(Easing.quad),
  });

  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", pointerEvents: "none" }}>
      <div
        style={{
          marginBottom: bottom,
          maxWidth: 1000,
          textAlign: "center",
          lineHeight: 1.15,
          opacity: exit,
          transform: `scale(${0.9 + 0.1 * exit})`,
        }}
      >
        {words.map((w, i) => {
          const s = spring({ frame: frame - start - i * wordDelay, fps, config: { damping: 11, stiffness: 180 } });
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                margin: "0 12px",
                fontFamily: "'Arial Black', 'Montserrat', 'DejaVu Sans', 'Helvetica Neue', sans-serif",
                fontWeight: 900,
                fontSize,
                color: "#fff",
                WebkitTextStroke: "14px #000",
                paintOrder: "stroke fill",
                textShadow: "0 8px 0 rgba(0,0,0,0.35)",
                opacity: interpolate(s, [0, 0.3], [0, 1], { extrapolateRight: "clamp" }),
                transform: `translateY(${(1 - s) * 50}px) scale(${0.4 + 0.6 * s}) rotate(${(1 - s) * (i % 2 ? 8 : -8)}deg)`,
              }}
            >
              {w}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
