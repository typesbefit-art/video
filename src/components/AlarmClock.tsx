import React from "react";
import { useCurrentFrame } from "remotion";

const INK = "#2A1A12";

export const formatTime = (minutes: number) => {
  const m = ((Math.floor(minutes) % 1440) + 1440) % 1440;
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
};

/** Будильник с цифровым табло. `ringing` — трясётся и звенит. */
export const AlarmClock: React.FC<{ x: number; y: number; minutes: number; ringing?: boolean; scale?: number }> = ({
  x,
  y,
  minutes,
  ringing = false,
  scale = 1,
}) => {
  const frame = useCurrentFrame();
  const wob = ringing ? Math.sin(frame * 2.4) : 0;
  const hop = ringing ? Math.abs(Math.sin(frame * 1.2)) * 8 : 0;
  return (
    <g transform={`translate(${x} ${y - hop}) scale(${scale}) rotate(${wob * 6})`}>
      {/* звонки */}
      <g transform={`rotate(${wob * 10} -120 -120)`}>
        <path d="M -190 -95 A 70 70 0 0 1 -60 -175 Z" fill="#FFD23F" stroke={INK} strokeWidth={8} strokeLinejoin="round" />
      </g>
      <g transform={`rotate(${-wob * 10} 120 -120)`}>
        <path d="M 190 -95 A 70 70 0 0 0 60 -175 Z" fill="#FFD23F" stroke={INK} strokeWidth={8} strokeLinejoin="round" />
      </g>
      <line x1={0} y1={-150} x2={0} y2={-180} stroke={INK} strokeWidth={10} strokeLinecap="round" />
      <circle cx={0} cy={-186} r={14} fill="#FFD23F" stroke={INK} strokeWidth={6} />
      {/* ножки */}
      <path d="M -120 110 L -160 160" stroke={INK} strokeWidth={14} strokeLinecap="round" />
      <path d="M 120 110 L 160 160" stroke={INK} strokeWidth={14} strokeLinecap="round" />
      {/* корпус */}
      <rect x={-210} y={-150} width={420} height={280} rx={70} fill="#FF5A5F" stroke={INK} strokeWidth={8} />
      <rect x={-190} y={-130} width={380} height={30} rx={15} fill="#FF8A8D" opacity={0.7} />
      {/* табло */}
      <rect x={-160} y={-90} width={320} height={170} rx={28} fill="#1E2A3A" stroke={INK} strokeWidth={6} />
      <text
        x={0}
        y={32}
        textAnchor="middle"
        fontFamily="'DejaVu Sans Mono', 'Courier New', monospace"
        fontWeight={700}
        fontSize={112}
        fill="#7CFFB2"
        style={{ filter: "drop-shadow(0 0 10px rgba(124,255,178,0.8))" }}
      >
        {formatTime(minutes)}
      </text>
      {ringing && (
        <g stroke={INK} strokeWidth={8} strokeLinecap="round" opacity={0.5 + 0.5 * Math.abs(Math.sin(frame * 0.9))}>
          <path d="M -250 -170 L -290 -210" />
          <path d="M -265 -90 L -320 -95" />
          <path d="M 250 -170 L 290 -210" />
          <path d="M 265 -90 L 320 -95" />
        </g>
      )}
    </g>
  );
};
