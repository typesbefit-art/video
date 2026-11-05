import React from "react";
import { useCurrentFrame } from "remotion";

const INK = "#2A1A12";

/** Простой SVG-кот. x, y — точка опоры (низ). mood: спит или в шоке. */
export const Cat: React.FC<{
  x: number;
  y: number;
  scaleX?: number;
  scaleY?: number;
  mood?: "sleep" | "startled";
}> = ({ x, y, scaleX = 1, scaleY = 1, mood = "sleep" }) => {
  const frame = useCurrentFrame();
  const startled = mood === "startled";
  const breathe = startled ? 1 : 1 + 0.03 * Math.sin((frame / 45) * Math.PI * 2);
  const tail = startled ? -60 : 12 * Math.sin((frame / 40) * Math.PI * 2);
  const C = "#FF9F43";
  return (
    <g transform={`translate(${x} ${y}) scale(${scaleX} ${scaleY * breathe})`}>
      <ellipse cx={0} cy={6} rx={95} ry={12} fill="rgba(40,20,30,0.25)" />
      {/* хвост */}
      <g transform={`rotate(${tail} 70 -30)`}>
        <path
          d="M 70 -30 Q 140 -40 130 -110"
          fill="none"
          stroke={INK}
          strokeWidth={30}
          strokeLinecap="round"
        />
        <path d="M 70 -30 Q 140 -40 130 -110" fill="none" stroke={C} strokeWidth={20} strokeLinecap="round" />
      </g>
      {/* тело */}
      <ellipse cx={0} cy={-48} rx={88} ry={50} fill={C} stroke={INK} strokeWidth={6} />
      <path d="M -20 -92 q 10 20 0 40 M 10 -96 q 10 22 0 44 M 40 -90 q 8 18 0 36" stroke="#E07B1E" strokeWidth={8} fill="none" strokeLinecap="round" />
      {/* голова */}
      <g transform={`translate(-70 ${startled ? -110 : -70})`}>
        <path d="M -42 -20 L -36 -70 L -8 -38 Z" fill={C} stroke={INK} strokeWidth={6} strokeLinejoin="round" />
        <path d="M 42 -20 L 36 -70 L 8 -38 Z" fill={C} stroke={INK} strokeWidth={6} strokeLinejoin="round" />
        <ellipse cx={0} cy={-10} rx={50} ry={42} fill={C} stroke={INK} strokeWidth={6} />
        {startled ? (
          <g>
            <circle cx={-18} cy={-16} r={14} fill="#fff" stroke={INK} strokeWidth={4} />
            <circle cx={18} cy={-16} r={14} fill="#fff" stroke={INK} strokeWidth={4} />
            <circle cx={-18} cy={-16} r={4} fill={INK} />
            <circle cx={18} cy={-16} r={4} fill={INK} />
            <ellipse cx={0} cy={14} rx={8} ry={10} fill={INK} />
          </g>
        ) : (
          <g stroke={INK} strokeWidth={5} fill="none" strokeLinecap="round">
            <path d="M -28 -12 q 10 8 20 0" />
            <path d="M 8 -12 q 10 8 20 0" />
            <path d="M -8 8 q 8 6 16 0" />
          </g>
        )}
        <path d="M -4 2 L 4 2 L 0 7 Z" fill="#E8546A" />
        <g stroke={INK} strokeWidth={3} strokeLinecap="round">
          <path d="M -24 6 L -62 0" />
          <path d="M -24 12 L -60 16" />
          <path d="M 24 6 L 62 0" />
          <path d="M 24 12 L 60 16" />
        </g>
      </g>
      {!startled && (
        <text x={10} y={-130} fontFamily="'DejaVu Sans', sans-serif" fontWeight={900} fontSize={36} fill="#5B6CFF" opacity={0.5 + 0.5 * Math.sin(frame * 0.08)}>
          z
        </text>
      )}
    </g>
  );
};
