import React, { useId, useMemo } from "react";
import { Easing, interpolate, random, useCurrentFrame, useVideoConfig } from "remotion";

export type BublikMood = "confident" | "panic" | "dead" | "proud";

export type BublikProps = {
  /** Точка опоры (низ тела) по X, px */
  x: number;
  /** Точка опоры (низ тела) по Y, px */
  y: number;
  /** Поворот тела в градусах (вокруг центра) */
  rotation?: number;
  /** Squash & stretch, масштабирование от точки опоры */
  scaleX?: number;
  scaleY?: number;
  mood?: BublikMood;
  /** Куда смотрят зрачки: x, y в диапазоне -1..1 (0,0 — в камеру) */
  lookAt?: { x: number; y: number };
  /** Y поверхности под Бубликом для тени (по умолчанию = y) */
  groundY?: number;
  /** Радиус тела, px */
  size?: number;
  /** Сид для расписания моргания */
  seed?: string;
  /** Ширина/высота слоя (по умолчанию — размер композиции) */
  layerWidth?: number;
  layerHeight?: number;
};

const BODY = "#F2C98F";
const BODY_LIGHT = "#FBE3BC";
const BODY_DARK = "#D9A464";
const INK = "#2A1A12";

const BLINK_FRAMES = 7;

/** Детерминированное расписание морганий: раз в 2–4 секунды. */
const useBlinkStarts = (fps: number, total: number, seed: string) =>
  useMemo(() => {
    const starts: number[] = [];
    let f = Math.round(fps * (0.8 + random(`${seed}-first`) * 1.2));
    let i = 0;
    // не моргаем у стыка последнего и первого кадра, чтобы цикл был бесшовным
    while (f < total - BLINK_FRAMES - fps * 0.5) {
      starts.push(f);
      f += Math.round(fps * (2 + random(`${seed}-${i++}`) * 2));
    }
    return starts;
  }, [fps, total, seed]);

const blinkOpenness = (frame: number, starts: number[]) => {
  for (const s of starts) {
    const d = frame - s;
    if (d >= 0 && d <= BLINK_FRAMES) {
      return interpolate(d, [0, 3, BLINK_FRAMES], [1, 0.05, 1], {
        easing: Easing.inOut(Easing.quad),
      });
    }
    if (s > frame) break;
  }
  return 1;
};

export const Bublik: React.FC<BublikProps> = ({
  x,
  y,
  rotation = 0,
  scaleX = 1,
  scaleY = 1,
  mood = "confident",
  lookAt = { x: 0, y: 0 },
  groundY,
  size = 100,
  seed = "bublik",
  layerWidth,
  layerHeight,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const blinkStarts = useBlinkStarts(fps, durationInFrames, seed);
  const open = mood === "dead" ? 1 : blinkOpenness(frame, blinkStarts);

  const R = size;
  const ground = groundY ?? y;
  const lift = Math.max(0, ground - y);
  const shadowK = interpolate(lift, [0, 600], [1, 0.35], { extrapolateRight: "clamp" });

  // Паника — мелкая дрожь зрачков
  const jitter = mood === "panic" ? 2.2 : 0;
  const jx = jitter * Math.sin(frame * 2.3);
  const jy = jitter * Math.cos(frame * 3.1);

  const eyeScale = mood === "panic" ? 1.18 : 1;
  const pupilR = mood === "panic" ? 7 : mood === "proud" ? 13 : 12;
  const lx = Math.max(-1, Math.min(1, lookAt.x));
  const ly = Math.max(-1, Math.min(1, lookAt.y));

  const eye = (cx: number, side: -1 | 1) => {
    if (mood === "dead") {
      const s = 16;
      return (
        <g key={side} stroke={INK} strokeWidth={8} strokeLinecap="round">
          <line x1={cx - s} y1={-22 - s} x2={cx + s} y2={-22 + s} />
          <line x1={cx + s} y1={-22 - s} x2={cx - s} y2={-22 + s} />
        </g>
      );
    }
    const rx = 25 * eyeScale;
    const ry = 31 * eyeScale;
    // Веко: confident — полуприкрыто, proud — чуть прикрыто
    const lid = mood === "confident" ? 0.38 : mood === "proud" ? 0.22 : 0;
    const lidTilt = side * (mood === "confident" ? 6 : 3);
    return (
      <g key={side} transform={`translate(${cx} -22) scale(1 ${open}) translate(${-cx} 22)`}>
        <ellipse cx={cx} cy={-22} rx={rx} ry={ry} fill="#fff" stroke={INK} strokeWidth={4} />
        <circle
          cx={cx + lx * (rx - pupilR - 4) + jx}
          cy={-22 + ly * (ry - pupilR - 4) + jy}
          r={pupilR}
          fill={INK}
        />
        <circle
          cx={cx + lx * (rx - pupilR - 4) + jx + pupilR * 0.35}
          cy={-22 + ly * (ry - pupilR - 4) + jy - pupilR * 0.35}
          r={pupilR * 0.3}
          fill="#fff"
        />
        {lid > 0 && (
          <path
            d={`M ${cx - rx - 3} ${-22 - ry - 3} L ${cx + rx + 3} ${-22 - ry - 3}
                L ${cx + rx + 3} ${-22 - ry + ry * 2 * lid - lidTilt}
                L ${cx - rx - 3} ${-22 - ry + ry * 2 * lid + lidTilt} Z`}
            fill={BODY}
            stroke={INK}
            strokeWidth={4}
            strokeLinejoin="round"
          />
        )}
      </g>
    );
  };

  const mouth = () => {
    switch (mood) {
      case "confident":
        return (
          <path d="M -26 32 Q 2 48 30 26" fill="none" stroke={INK} strokeWidth={6} strokeLinecap="round" />
        );
      case "panic":
        return (
          <ellipse cx={0} cy={40} rx={14 + 2 * Math.sin(frame * 1.7)} ry={18} fill={INK} />
        );
      case "dead":
        return (
          <g>
            <path
              d="M -30 36 Q -20 28 -10 36 Q 0 44 10 36 Q 20 28 30 36"
              fill="none"
              stroke={INK}
              strokeWidth={6}
              strokeLinecap="round"
            />
            <path d="M 8 38 Q 12 58 22 54 Q 28 46 22 36" fill="#E8546A" stroke={INK} strokeWidth={4} />
          </g>
        );
      case "proud":
        return (
          <g>
            <path d="M -36 24 Q 0 70 36 24 Z" fill={INK} stroke={INK} strokeWidth={5} strokeLinejoin="round" />
            <path d="M -30 27 Q 0 36 30 27 L 28 33 Q 0 41 -28 33 Z" fill="#fff" />
          </g>
        );
    }
  };

  const brows = () => {
    if (mood === "panic") {
      return (
        <g stroke={INK} strokeWidth={7} strokeLinecap="round" fill="none">
          <path d="M -58 -78 Q -40 -92 -18 -76" />
          <path d="M 18 -76 Q 40 -92 58 -78" />
        </g>
      );
    }
    if (mood === "proud") {
      return (
        <g stroke={INK} strokeWidth={7} strokeLinecap="round" fill="none">
          <path d="M -56 -64 Q -36 -76 -14 -66" />
          <path d="M 14 -66 Q 36 -76 56 -64" />
        </g>
      );
    }
    return null;
  };

  const sparkle = mood === "proud" ? 0.6 + 0.4 * Math.sin(frame * 0.4) : 0;

  return (
    <svg
      width={layerWidth ?? width}
      height={layerHeight ?? height}
      viewBox={`0 0 ${layerWidth ?? width} ${layerHeight ?? height}`}
      style={{ position: "absolute", left: 0, top: 0, overflow: "visible", pointerEvents: "none" }}
    >
      <defs>
        <radialGradient id={`body-${uid}`} cx="38%" cy="32%" r="75%">
          <stop offset="0%" stopColor={BODY_LIGHT} />
          <stop offset="55%" stopColor={BODY} />
          <stop offset="100%" stopColor={BODY_DARK} />
        </radialGradient>
      </defs>

      {/* Тень на поверхности */}
      <ellipse
        cx={x}
        cy={ground + 4}
        rx={R * 0.85 * shadowK * scaleX}
        ry={R * 0.16 * shadowK}
        fill="rgba(40,20,30,0.28)"
      />

      <g transform={`translate(${x} ${y}) scale(${scaleX} ${scaleY})`}>
        <g transform={`translate(0 ${-R}) rotate(${rotation})`}>
          <circle cx={0} cy={0} r={R} fill={`url(#body-${uid})`} stroke={INK} strokeWidth={6} />
          {/* кунжут — чтобы было видно вращение */}
          <g fill="#FFF6E0" stroke={BODY_DARK} strokeWidth={2}>
            <ellipse cx={-52} cy={52} rx={7} ry={4} transform="rotate(-30 -52 52)" />
            <ellipse cx={58} cy={46} rx={7} ry={4} transform="rotate(25 58 46)" />
            <ellipse cx={4} cy={78} rx={7} ry={4} />
            <ellipse cx={-70} cy={-18} rx={6} ry={3.5} transform="rotate(70 -70 -18)" />
          </g>
          {/* румянец */}
          <ellipse cx={-62} cy={18} rx={14} ry={8} fill="#F29B85" opacity={0.55} />
          <ellipse cx={62} cy={18} rx={14} ry={8} fill="#F29B85" opacity={0.55} />
          {brows()}
          {eye(-34, -1)}
          {eye(34, 1)}
          {mouth()}
          {mood === "panic" && (
            <path
              d={`M 84 ${-58 + 4 * Math.sin(frame * 0.5)} q 10 18 0 26 q -10 -8 0 -26 Z`}
              fill="#8FD3FF"
              stroke={INK}
              strokeWidth={3}
            />
          )}
          {sparkle > 0 && (
            <path
              transform={`translate(${R * 0.72} ${-R * 0.72}) scale(${sparkle})`}
              d="M 0 -22 L 6 -6 L 22 0 L 6 6 L 0 22 L -6 6 L -22 0 L -6 -6 Z"
              fill="#FFF7A8"
              stroke={INK}
              strokeWidth={3}
            />
          )}
        </g>
      </g>
    </svg>
  );
};
