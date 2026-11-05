import React from "react";
import { AbsoluteFill, interpolate, interpolateColors } from "remotion";

/** Плоская спальня. Координаты в пикселях кадра 1080x1920. */
export const BEDROOM = {
  W: 1080,
  H: 1920,
  HORIZON: 1300,
  BED_TOP: 1160, // поверхность матраса
  BED_LEFT: 290,
  BED_RIGHT: 780,
  PILLOW_TOP: 1135,
  FLOOR: 1560, // линия пола для персонажей «перед» мебелью
  NIGHTSTAND_TOP: 1250,
  LAMP_BASE: { x: 135, y: 1250 },
  SLIPPER: { x: 880, y: 1560 },
  CAT: { x: 990, y: 1560 },
};

const INK = "#2A1A12";
const SW = 7;

const Svg: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <svg
    width={BEDROOM.W}
    height={BEDROOM.H}
    viewBox={`0 0 ${BEDROOM.W} ${BEDROOM.H}`}
    style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}
  >
    {children}
  </svg>
);

/** Окно: цвет неба и солнце зависят от времени на будильнике (минуты от полуночи). */
const Window: React.FC<{ minutes: number }> = ({ minutes }) => {
  const k = interpolate(minutes, [360, 480, 707], [0, 0.5, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const skyTop = interpolateColors(k, [0, 0.5, 1], ["#6C5BD4", "#7EC8FF", "#2FA8FF"]);
  const skyBottom = interpolateColors(k, [0, 0.5, 1], ["#FF9E7A", "#BFE6FF", "#8FD8FF"]);
  const sunY = interpolate(k, [0, 1], [880, 640]);
  const sunX = interpolate(k, [0, 1], [700, 860]);
  return (
    <g>
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={skyTop} />
          <stop offset="100%" stopColor={skyBottom} />
        </linearGradient>
        <clipPath id="win-clip">
          <rect x={630} y={570} width={320} height={320} rx={10} />
        </clipPath>
      </defs>
      <rect x={612} y={552} width={356} height={356} rx={20} fill="#FFFFFF" stroke={INK} strokeWidth={SW} />
      <g clipPath="url(#win-clip)">
        <rect x={630} y={570} width={320} height={320} fill="url(#sky)" />
        <circle cx={sunX} cy={sunY} r={52} fill="#FFE066" stroke={INK} strokeWidth={5} />
        <path d="M 640 860 q 40 -40 90 -10 q 40 -30 90 0 q 50 -30 130 10 L 950 900 L 630 900 Z" fill="#7BD389" stroke={INK} strokeWidth={5} />
      </g>
      <line x1={790} y1={570} x2={790} y2={890} stroke={INK} strokeWidth={SW} />
      <line x1={630} y1={730} x2={950} y2={730} stroke={INK} strokeWidth={SW} />
      {/* шторы */}
      <path d="M 590 530 Q 640 720 600 930 L 560 930 Q 580 720 550 530 Z" fill="#FF6FA3" stroke={INK} strokeWidth={SW} strokeLinejoin="round" />
      <path d="M 990 530 Q 940 720 980 930 L 1020 930 Q 1000 720 1030 530 Z" fill="#FF6FA3" stroke={INK} strokeWidth={SW} strokeLinejoin="round" />
      <rect x={530} y={515} width={520} height={24} rx={12} fill="#8B5CF6" stroke={INK} strokeWidth={SW} />
    </g>
  );
};

/** Задний план: стены, окно, картина, кровать, тумбочка, ковёр. */
export const BedroomBack: React.FC<{ minutes: number }> = ({ minutes }) => (
  <AbsoluteFill style={{ backgroundColor: "#7FD1C7" }}>
    <Svg>
      {/* стена с полосками */}
      <rect x={0} y={0} width={1080} height={BEDROOM.HORIZON} fill="#7FD1C7" />
      {Array.from({ length: 10 }).map((_, i) => (
        <rect key={i} x={i * 120 + 30} y={0} width={46} height={BEDROOM.HORIZON} fill="#93DBD2" />
      ))}
      <rect x={0} y={BEDROOM.HORIZON - 40} width={1080} height={40} fill="#FFFFFF" stroke={INK} strokeWidth={SW} />

      {/* пол */}
      <rect x={0} y={BEDROOM.HORIZON} width={1080} height={620} fill="#E9A15B" />
      {[1380, 1480, 1600, 1740, 1900].map((y) => (
        <line key={y} x1={0} y1={y} x2={1080} y2={y} stroke="#C97F3E" strokeWidth={6} />
      ))}
      {[[200, 1300, 1380], [640, 1380, 1480], [380, 1480, 1600], [860, 1600, 1740], [150, 1740, 1900]].map(
        ([x, y1, y2], i) => (
          <line key={i} x1={x} y1={y1} x2={x} y2={y2} stroke="#C97F3E" strokeWidth={6} />
        ),
      )}

      {/* ковёр */}
      <ellipse cx={850} cy={1625} rx={235} ry={66} fill="#FFD23F" stroke={INK} strokeWidth={SW} />
      <ellipse cx={850} cy={1625} rx={175} ry={44} fill="none" stroke="#FF6FA3" strokeWidth={10} strokeDasharray="22 16" />

      <Window minutes={minutes} />

      {/* картина */}
      <g transform="rotate(-3 440 690)">
        <rect x={340} y={600} width={200} height={170} rx={10} fill="#FFF3D6" stroke={INK} strokeWidth={SW} />
        <circle cx={440} cy={680} r={46} fill="#F2C98F" stroke={INK} strokeWidth={5} />
        <circle cx={425} cy={672} r={8} fill={INK} />
        <circle cx={457} cy={672} r={8} fill={INK} />
        <path d="M 420 698 q 20 14 40 0" stroke={INK} strokeWidth={5} fill="none" strokeLinecap="round" />
      </g>

      {/* тумбочка */}
      <rect x={40} y={BEDROOM.NIGHTSTAND_TOP} width={190} height={170} rx={10} fill="#B07CFF" stroke={INK} strokeWidth={SW} />
      <rect x={30} y={BEDROOM.NIGHTSTAND_TOP - 8} width={210} height={26} rx={10} fill="#C9A5FF" stroke={INK} strokeWidth={SW} />
      <rect x={62} y={1300} width={146} height={56} rx={8} fill="#C9A5FF" stroke={INK} strokeWidth={5} />
      <circle cx={135} cy={1328} r={9} fill="#FFD23F" stroke={INK} strokeWidth={4} />
      <rect x={55} y={1420} width={20} height={24} fill={INK} />
      <rect x={195} y={1420} width={20} height={24} fill={INK} />

      {/* кровать */}
      <rect x={250} y={880} width={56} height={560} rx={24} fill="#3D7BFF" stroke={INK} strokeWidth={SW} />
      <circle cx={278} cy={880} r={34} fill="#3D7BFF" stroke={INK} strokeWidth={SW} />
      <rect x={300} y={1372} width={32} height={68} fill="#2558C9" stroke={INK} strokeWidth={5} />
      <rect x={748} y={1372} width={32} height={68} fill="#2558C9" stroke={INK} strokeWidth={5} />
      <rect x={280} y={1282} width={510} height={100} rx={18} fill="#3D7BFF" stroke={INK} strokeWidth={SW} />
      <rect x={290} y={BEDROOM.BED_TOP} width={490} height={130} rx={26} fill="#FFFFFF" stroke={INK} strokeWidth={SW} />
      {/* одеяло */}
      <path
        d={`M 560 ${BEDROOM.BED_TOP + 10} L 780 ${BEDROOM.BED_TOP + 10} Q 798 1240 780 1318 L 560 1318 Q 548 1240 560 ${BEDROOM.BED_TOP + 10} Z`}
        fill="#FF6FA3"
        stroke={INK}
        strokeWidth={SW}
        strokeLinejoin="round"
      />
      {[600, 660, 720].map((x) => (
        <circle key={x} cx={x} cy={1250} r={10} fill="#FFD1E3" />
      ))}
      {/* подушка */}
      <rect x={310} y={1108} width={140} height={62} rx={30} fill="#FFF3D6" stroke={INK} strokeWidth={SW} />
    </Svg>
  </AbsoluteFill>
);

/** Лампа на тумбочке. angle — наклон вправо (градусы) вокруг основания. */
export const Lamp: React.FC<{ angle: number; on?: boolean }> = ({ angle, on = true }) => {
  const { x, y } = BEDROOM.LAMP_BASE;
  return (
    <Svg>
      <g transform={`rotate(${angle} ${x} ${y})`}>
        <ellipse cx={x} cy={y - 8} rx={52} ry={16} fill="#FFD23F" stroke={INK} strokeWidth={SW} />
        <rect x={x - 9} y={y - 200} width={18} height={190} fill="#FFD23F" stroke={INK} strokeWidth={5} />
        {on && <ellipse cx={x} cy={y - 175} rx={60} ry={30} fill="#FFF7A8" opacity={0.7} />}
        <path
          d={`M ${x - 52} ${y - 300} L ${x + 52} ${y - 300} L ${x + 95} ${y - 190} L ${x - 95} ${y - 190} Z`}
          fill="#FF8A3D"
          stroke={INK}
          strokeWidth={SW}
          strokeLinejoin="round"
        />
        <path d={`M ${x - 74} ${y - 245} L ${x + 74} ${y - 245}`} stroke="#FFB27A" strokeWidth={10} />
      </g>
    </Svg>
  );
};

/** Тапок. Смещение/вращение относительно его места на полу. */
export const Slipper: React.FC<{ dx?: number; dy?: number; rotation?: number; scaleY?: number }> = ({
  dx = 0,
  dy = 0,
  rotation = 0,
  scaleY = 1,
}) => {
  const { x, y } = BEDROOM.SLIPPER;
  const lift = Math.max(0, -dy);
  const sk = interpolate(lift, [0, 500], [1, 0.4], { extrapolateRight: "clamp" });
  return (
    <Svg>
      <ellipse cx={x + dx} cy={y + 2} rx={70 * sk} ry={10 * sk} fill="rgba(40,20,30,0.25)" />
      <g transform={`translate(${x + dx} ${y + dy}) scale(1 ${scaleY}) rotate(${rotation} 0 -16)`}>
        <path d="M -70 0 Q -78 -30 -40 -32 L 50 -32 Q 76 -30 72 0 Z" fill="#5B6CFF" stroke={INK} strokeWidth={SW} strokeLinejoin="round" />
        <path d="M -10 -32 Q 30 -70 66 -24" fill="#FF6FA3" stroke={INK} strokeWidth={SW} strokeLinejoin="round" />
        <circle cx={34} cy={-46} r={12} fill="#FFFFFF" stroke={INK} strokeWidth={4} />
      </g>
    </Svg>
  );
};
