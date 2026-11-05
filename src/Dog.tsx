import React from 'react';

export type DogColors = {
  body: string;
  ear: string;
  muzzle: string;
  patch: string;
  collar: string;
};

export const MAIN_DOG: DogColors = {
  body: '#F4B860',
  ear: '#A8622F',
  muzzle: '#FFF1DC',
  patch: '#E59A45',
  collar: '#FF4D6D',
};

export const OTHER_DOG: DogColors = {
  body: '#D9D4CF',
  ear: '#5B4A42',
  muzzle: '#FFFFFF',
  patch: '#8C7B72',
  collar: '#3A86FF',
};

type Props = {
  /** local frame, drives idle motion */
  t: number;
  /** 0..1 how open the mouth is */
  mouth?: number;
  /** head tilt, degrees */
  tilt?: number;
  /** tail wag speed multiplier */
  wag?: number;
  /** 0..1 lift of the right paw (wave) */
  wave?: number;
  colors?: DogColors;
  width?: number;
  flip?: boolean;
  /** eyes looking direction -1..1 */
  look?: number;
};

const OUTLINE = '#3A2414';

export const Dog: React.FC<Props> = ({
  t,
  mouth = 0,
  tilt = 0,
  wag = 1,
  wave = 0,
  colors = MAIN_DOG,
  width = 520,
  flip = false,
  look = 0,
}) => {
  const c = colors;
  const tailAngle = Math.sin(t * 0.55 * wag) * 22;
  const earFlop = Math.sin(t * 0.2) * 3;
  // blink every ~3.3 s for 4 frames
  const blinkPhase = (t + 37) % 100;
  const eyeScale = blinkPhase < 4 ? 0.12 : 1;
  const waveAngle = -wave * (115 + Math.sin(t * 0.6) * 20);
  const open = Math.max(0, Math.min(1, mouth));
  const sw = 7;

  return (
    <svg
      width={width}
      height={(width * 560) / 500}
      viewBox="0 0 500 560"
      style={{overflow: 'visible', transform: flip ? 'scaleX(-1)' : undefined}}
    >
      {/* tail */}
      <g transform={`rotate(${tailAngle} 345 445)`}>
        <path
          d="M345 445 C 405 430, 430 380, 420 320"
          stroke={OUTLINE}
          strokeWidth={42}
          strokeLinecap="round"
          fill="none"
        />
        <path
          d="M345 445 C 405 430, 430 380, 420 320"
          stroke={c.body}
          strokeWidth={28}
          strokeLinecap="round"
          fill="none"
        />
      </g>

      {/* body */}
      <ellipse cx={250} cy={440} rx={128} ry={112} fill={c.body} stroke={OUTLINE} strokeWidth={sw} />
      <ellipse cx={250} cy={462} rx={78} ry={78} fill={c.muzzle} />

      {/* left front leg */}
      <rect x={176} y={455} width={52} height={92} rx={26} fill={c.body} stroke={OUTLINE} strokeWidth={sw} />
      <ellipse cx={202} cy={540} rx={34} ry={20} fill={c.muzzle} stroke={OUTLINE} strokeWidth={sw} />

      {/* right front leg (waves) */}
      <g transform={`rotate(${waveAngle} 298 462)`}>
        <rect x={272} y={455} width={52} height={92} rx={26} fill={c.body} stroke={OUTLINE} strokeWidth={sw} />
        <ellipse cx={298} cy={540} rx={34} ry={20} fill={c.muzzle} stroke={OUTLINE} strokeWidth={sw} />
        <path d="M286 534 v12 M298 532 v14 M310 534 v12" stroke={OUTLINE} strokeWidth={4} strokeLinecap="round" />
      </g>

      {/* collar */}
      <path d="M160 352 Q250 400 340 352" stroke={OUTLINE} strokeWidth={30} fill="none" strokeLinecap="round" />
      <path d="M160 352 Q250 400 340 352" stroke={c.collar} strokeWidth={18} fill="none" strokeLinecap="round" />
      <circle cx={250} cy={392} r={17} fill="#FFD23F" stroke={OUTLINE} strokeWidth={5} />

      {/* head */}
      <g transform={`rotate(${tilt} 250 330)`}>
        <circle cx={250} cy={220} r={142} fill={c.body} stroke={OUTLINE} strokeWidth={sw} />
        {/* eye patch */}
        <ellipse cx={312} cy={200} rx={52} ry={46} fill={c.patch} />

        {/* ears */}
        <g transform={`rotate(${-earFlop} 140 120)`}>
          <path
            d="M150 105 C 95 95, 70 160, 78 250 C 84 310, 120 330, 140 300 C 158 270, 165 180, 150 105 Z"
            fill={c.ear}
            stroke={OUTLINE}
            strokeWidth={sw}
            strokeLinejoin="round"
          />
        </g>
        <g transform={`rotate(${earFlop} 360 120)`}>
          <path
            d="M350 105 C 405 95, 430 160, 422 250 C 416 310, 380 330, 360 300 C 342 270, 335 180, 350 105 Z"
            fill={c.ear}
            stroke={OUTLINE}
            strokeWidth={sw}
            strokeLinejoin="round"
          />
        </g>

        {/* eyes */}
        {[196, 304].map((x) => (
          <g key={x} transform={`translate(${x + look * 8} 205) scale(1 ${eyeScale})`}>
            <circle r={36} fill={OUTLINE} />
            <circle cx={11} cy={-13} r={13} fill="#fff" />
            <circle cx={-12} cy={12} r={6} fill="#fff" />
          </g>
        ))}
        {/* brows */}
        <path d="M168 158 q28 -16 56 0" stroke={OUTLINE} strokeWidth={6} fill="none" strokeLinecap="round" />
        <path d="M276 158 q28 -16 56 0" stroke={OUTLINE} strokeWidth={6} fill="none" strokeLinecap="round" />

        {/* cheeks */}
        <ellipse cx={150} cy={268} rx={22} ry={13} fill="#FF8FA3" opacity={0.6} />
        <ellipse cx={350} cy={268} rx={22} ry={13} fill="#FF8FA3" opacity={0.6} />

        {/* muzzle */}
        <ellipse cx={250} cy={292} rx={84} ry={58} fill={c.muzzle} stroke={OUTLINE} strokeWidth={5} />

        {/* mouth */}
        {open > 0.05 ? (
          <g>
            <ellipse cx={250} cy={312} rx={34} ry={10 + open * 30} fill="#6B1F2A" stroke={OUTLINE} strokeWidth={5} />
            <ellipse cx={250} cy={322 + open * 16} rx={24} ry={10 + open * 8} fill="#FF7A93" />
          </g>
        ) : null}
        <path d="M250 282 v18" stroke={OUTLINE} strokeWidth={5} strokeLinecap="round" />
        <path
          d="M208 300 q21 22 42 0 q21 22 42 0"
          stroke={OUTLINE}
          strokeWidth={5}
          fill="none"
          strokeLinecap="round"
        />
        {/* tongue hanging out */}
        {open <= 0.05 ? (
          <g transform={`rotate(${Math.sin(t * 0.3) * 4} 262 310)`}>
            <path
              d="M246 308 h34 v26 a17 17 0 0 1 -34 0 Z"
              fill="#FF7A93"
              stroke={OUTLINE}
              strokeWidth={5}
              strokeLinejoin="round"
            />
            <path d="M263 314 v18" stroke="#E0506E" strokeWidth={4} strokeLinecap="round" />
          </g>
        ) : null}

        {/* nose */}
        <ellipse cx={250} cy={266} rx={28} ry={19} fill={OUTLINE} />
        <ellipse cx={241} cy={260} rx={9} ry={5} fill="#fff" opacity={0.7} />
      </g>
    </svg>
  );
};
