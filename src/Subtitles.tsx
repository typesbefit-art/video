import { loadFont } from "@remotion/fonts";
import React from "react";
import { AbsoluteFill, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import cues from "./voice.json";

const FAMILY = "PlexSub";
loadFont({ family: FAMILY, url: staticFile("fonts/ibm-plex-sans-cyrillic-400-normal.woff2"), weight: "400" });
loadFont({ family: FAMILY, url: staticFile("fonts/ibm-plex-sans-latin-400-normal.woff2"), weight: "400" });

type Cue = { text: string; start: number; end: number };

// Безопасные зоны: верхние 10% (192px) и нижние 20% (384px) — пусто.
// Нижний край строки субтитров — на 1920 - 400 = 1520px.
export const SAFE_BOTTOM_PX = 400;

export const Subtitles: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const list = cues as Cue[];
  const i = list.findIndex((c, k) => t >= c.start - 0.08 && t < (list[k + 1]?.start ?? 31) - 0.08);
  if (i < 0) return null;
  const c = list[i];
  const hold = Math.min(c.end + 0.7, (list[i + 1]?.start ?? 31) - 0.08);
  const op =
    interpolate(t, [c.start - 0.08, c.start + 0.12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) *
    interpolate(t, [hold - 0.18, hold], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: SAFE_BOTTOM_PX }}>
      <div
        style={{
          fontFamily: `${FAMILY}, sans-serif`,
          fontSize: 40,
          lineHeight: 1.3,
          letterSpacing: "0.04em",
          color: "rgba(232,235,238,0.94)",
          textShadow: "0 0 10px rgba(0,0,0,0.85), 0 2px 3px rgba(0,0,0,0.9)",
          textAlign: "center",
          maxWidth: 860,
          opacity: op,
        }}
      >
        {c.text}
      </div>
    </AbsoluteFill>
  );
};
