import React from 'react';
import {C, FONT} from '../lib';

const S = {stroke: C.ink, strokeWidth: 6, strokeLinejoin: 'round' as const, strokeLinecap: 'round' as const};

export const Coin: React.FC<{r?: number; label?: string}> = ({r = 40, label = '$'}) => (
  <g>
    <circle r={r} fill={C.yellow} {...S} />
    <circle r={r * 0.72} fill="none" stroke="#e0a800" strokeWidth={r * 0.1} />
    <text y={r * 0.32} textAnchor="middle" fontFamily={FONT} fontWeight={800} fontSize={r * 0.95} fill="#b07d00">{label}</text>
  </g>
);

export const Bill: React.FC<{w?: number; label?: string}> = ({w = 180, label = '$100'}) => {
  const h = w * 0.5;
  return (
    <g>
      <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={10} fill="#7fd99a" {...S} />
      <rect x={-w / 2 + 12} y={-h / 2 + 12} width={w - 24} height={h - 24} rx={6} fill="none" stroke={C.greenDark} strokeWidth={4} />
      <circle r={h * 0.28} fill="#b9f0c8" stroke={C.greenDark} strokeWidth={4} />
      <text y={h * 0.13} textAnchor="middle" fontFamily={FONT} fontWeight={800} fontSize={h * 0.36} fill={C.greenDark}>{label}</text>
    </g>
  );
};

const icons: Record<string, React.ReactNode> = {
  coffee: (
    <g>
      <path d="M-55,-60 L55,-60 L42,80 L-42,80 Z" fill={C.white} {...S} />
      <rect x={-64} y={-84} width={128} height={30} rx={10} fill="#8d5a3b" {...S} />
      <rect x={-50} y={-10} width={100} height={44} fill="#c98b5b" stroke="none" />
      <path d="M-20,-110 q10,-20 0,-40 M20,-110 q10,-20 0,-40" stroke="#bbb" strokeWidth={6} fill="none" strokeLinecap="round" />
    </g>
  ),
  delivery: (
    <g>
      <path d="M-80,-40 L80,-40 L70,90 L-70,90 Z" fill="#ffb347" {...S} />
      <path d="M-40,-40 Q-40,-100 0,-100 Q40,-100 40,-40" fill="none" {...S} />
      <circle cx={0} cy={25} r={26} fill={C.white} {...S} />
      <path d="M-12,25 l8,10 l16,-20" fill="none" stroke={C.green} strokeWidth={7} strokeLinecap="round" />
    </g>
  ),
  phone: (
    <g>
      <rect x={-60} y={-110} width={120} height={220} rx={20} fill={C.navy} {...S} />
      <rect x={-48} y={-92} width={96} height={170} rx={8} fill="#6c5ce7" />
      <polygon points="-16,-36 -16,24 30,-6" fill={C.white} />
      <circle cx={0} cy={94} r={8} fill="#556" />
    </g>
  ),
  bar: (
    <g>
      <path d="M-70,-80 L-10,-80 L-16,70 L-64,70 Z" fill="#ffd166" {...S} />
      <rect x={-70} y={-100} width={60} height={28} rx={12} fill={C.white} {...S} />
      <path d="M10,-60 L80,-60 L46,0 Z" fill="#ff6b9a" {...S} />
      <line x1={46} y1={0} x2={46} y2={60} {...S} />
      <line x1={22} y1={64} x2={70} y2={64} {...S} />
    </g>
  ),
  taxi: (
    <g>
      <path d="M-110,30 L-90,-20 Q-80,-50 -50,-50 L50,-50 Q80,-50 90,-20 L110,30 L110,60 L-110,60 Z" fill={C.yellow} {...S} />
      <path d="M-70,-20 L-56,-42 L56,-42 L70,-20 Z" fill="#bde4ff" {...S} />
      <rect x={-24} y={-78} width={48} height={24} rx={6} fill={C.white} {...S} />
      <circle cx={-62} cy={64} r={24} fill={C.ink} />
      <circle cx={62} cy={64} r={24} fill={C.ink} />
    </g>
  ),
  box: (
    <g>
      <path d="M-90,-30 L0,-70 L90,-30 L0,10 Z" fill="#e9b872" {...S} />
      <path d="M-90,-30 L0,10 L0,100 L-90,60 Z" fill="#d49a52" {...S} />
      <path d="M90,-30 L0,10 L0,100 L90,60 Z" fill="#c4883f" {...S} />
      <rect x={-60} y={-110} width={120} height={46} rx={12} fill={C.red} {...S} transform="rotate(-10)" />
      <text x={0} y={-76} textAnchor="middle" fontFamily={FONT} fontWeight={800} fontSize={30} fill={C.white} transform="rotate(-10)">SALE</text>
    </g>
  ),
  jar: (
    <g>
      <path d="M-70,-70 L70,-70 L80,90 Q80,110 60,110 L-60,110 Q-80,110 -80,90 Z" fill="rgba(200,240,255,0.6)" {...S} />
      <rect x={-60} y={-100} width={120} height={34} rx={8} fill="#c0c0c0" {...S} />
    </g>
  ),
  piggy: (
    <g>
      <ellipse cx={0} cy={10} rx={100} ry={76} fill="#ff9ab8" {...S} />
      <circle cx={-70} cy={-50} r={22} fill="#ff9ab8" {...S} />
      <ellipse cx={96} cy={10} rx={22} ry={28} fill="#ffb3c9" {...S} />
      <circle cx={92} cy={4} r={4} fill={C.ink} />
      <circle cx={100} cy={16} r={4} fill={C.ink} />
      <circle cx={50} cy={-20} r={8} fill={C.ink} />
      <rect x={-30} y={-70} width={60} height={12} rx={6} fill={C.ink} />
      <rect x={-60} y={70} width={26} height={30} rx={8} fill="#ff9ab8" {...S} />
      <rect x={30} y={70} width={26} height={30} rx={8} fill="#ff9ab8" {...S} />
    </g>
  ),
  wallet: (
    <g>
      <rect x={-100} y={-60} width={200} height={130} rx={20} fill="#8d5a3b" {...S} />
      <rect x={30} y={-20} width={80} height={50} rx={12} fill="#a86f4b" {...S} />
      <circle cx={60} cy={5} r={8} fill={C.yellow} />
    </g>
  ),
  house: (
    <g>
      <path d="M-100,-10 L0,-100 L100,-10" fill={C.red} {...S} />
      <rect x={-80} y={-20} width={160} height={120} fill="#fff3d6" {...S} />
      <rect x={-20} y={30} width={40} height={70} fill="#8d5a3b" {...S} />
      <rect x={-64} y={4} width={34} height={34} fill="#bde4ff" {...S} />
      <rect x={30} y={4} width={34} height={34} fill="#bde4ff" {...S} />
    </g>
  ),
  car: (
    <g>
      <path d="M-130,30 L-110,-10 Q-90,-60 -40,-60 L40,-60 Q90,-60 110,-10 L130,30 L130,60 L-130,60 Z" fill={C.blue} {...S} />
      <path d="M-80,-10 L-60,-46 L60,-46 L80,-10 Z" fill="#bde4ff" {...S} />
      <circle cx={-72} cy={64} r={28} fill={C.ink} />
      <circle cx={72} cy={64} r={28} fill={C.ink} />
      <circle cx={-72} cy={64} r={10} fill="#ccc" />
      <circle cx={72} cy={64} r={10} fill="#ccc" />
    </g>
  ),
  palm: (
    <g>
      <ellipse cx={0} cy={100} rx={120} ry={22} fill="#ffe08a" {...S} />
      <path d="M-6,100 Q-20,20 10,-60 L26,-56 Q0,20 14,100 Z" fill="#a0703f" {...S} />
      {[-150, -110, -60, -20, 30].map((a, i) => (
        <path key={i} d="M18,-60 Q60,-110 120,-80 Q70,-80 18,-60 Z" fill={C.green} {...S} transform={`rotate(${a + 90},18,-60)`} />
      ))}
      <circle cx={70} cy={-90} r={30} fill={C.yellow} opacity={0} />
    </g>
  ),
  hourglass: (
    <g>
      <rect x={-80} y={-120} width={160} height={20} rx={8} fill="#8d5a3b" {...S} />
      <rect x={-80} y={100} width={160} height={20} rx={8} fill="#8d5a3b" {...S} />
      <path d="M-60,-100 L60,-100 Q60,-30 8,0 Q60,30 60,100 L-60,100 Q-60,30 -8,0 Q-60,-30 -60,-100 Z" fill="rgba(200,240,255,0.7)" {...S} />
    </g>
  ),
  bitcoin: (
    <g>
      <circle r={80} fill="#f7931a" {...S} />
      <text y={38} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={110} fill={C.white}>B</text>
      <line x1={-12} y1={-58} x2={-12} y2={58} stroke={C.white} strokeWidth={10} />
      <line x1={14} y1={-58} x2={14} y2={58} stroke={C.white} strokeWidth={10} />
    </g>
  ),
  briefcase: (
    <g>
      <rect x={-100} y={-50} width={200} height={130} rx={16} fill="#8d5a3b" {...S} />
      <path d="M-36,-50 L-36,-80 L36,-80 L36,-50" fill="none" {...S} />
      <line x1={-100} y1={0} x2={100} y2={0} {...S} />
    </g>
  ),
  clover: (
    <g>
      {[0, 90, 180, 270].map((a) => (
        <g key={a} transform={`rotate(${a})`}>
          <circle cx={-24} cy={-40} r={30} fill={C.green} {...S} />
          <circle cx={24} cy={-40} r={30} fill={C.green} {...S} />
        </g>
      ))}
      <path d="M0,0 Q20,60 50,100" fill="none" stroke={C.greenDark} strokeWidth={12} strokeLinecap="round" />
    </g>
  ),
  bell: (
    <g>
      <path d="M-60,40 Q-60,-70 0,-70 Q60,-70 60,40 L76,60 L-76,60 Z" fill={C.yellow} {...S} />
      <circle cx={0} cy={74} r={16} fill={C.yellow} {...S} />
    </g>
  ),
  thumb: (
    <g>
      <rect x={-80} y={-10} width={40} height={100} rx={8} fill={C.blue} {...S} />
      <path d="M-30,-10 L0,-80 Q20,-100 30,-70 L20,-20 L70,-20 Q90,-18 86,6 L70,80 Q66,90 54,90 L-30,90 Z" fill={C.skin} {...S} />
    </g>
  ),
  iceCream: (
    <g>
      <path d="M-50,0 L0,130 L50,0 Z" fill="#e9b872" {...S} />
      <circle cx={0} cy={-30} r={62} fill="#7fd99a" {...S} />
      <text y={-12} textAnchor="middle" fontFamily={FONT} fontWeight={800} fontSize={56} fill={C.greenDark}>$</text>
    </g>
  ),
  sun: (
    <g>
      {Array.from({length: 12}).map((_, i) => (
        <rect key={i} x={-8} y={-130} width={16} height={40} rx={8} fill="#ffb703" transform={`rotate(${i * 30})`} />
      ))}
      <circle r={80} fill={C.yellow} {...S} />
    </g>
  ),
  safe: (
    <g>
      <rect x={-100} y={-100} width={200} height={190} rx={18} fill="#5d6d7e" {...S} />
      <rect x={-80} y={-80} width={160} height={150} rx={10} fill="#85929e" {...S} />
      <circle r={36} fill="#d5d8dc" {...S} />
      <line x1={0} y1={0} x2={0} y2={-28} {...S} />
      <rect x={-80} y={92} width={30} height={16} fill={C.ink} />
      <rect x={50} y={92} width={30} height={16} fill={C.ink} />
    </g>
  ),
  bank: (
    <g>
      <path d="M-110,-40 L0,-110 L110,-40 Z" fill="#dfe6e9" {...S} />
      {[-80, -30, 20, 70].map((x) => <rect key={x} x={x} y={-30} width={22} height={110} fill="#dfe6e9" {...S} />)}
      <rect x={-120} y={80} width={240} height={24} fill="#b2bec3" {...S} />
    </g>
  ),
  calendar: (
    <g>
      <rect x={-90} y={-80} width={180} height={170} rx={16} fill={C.white} {...S} />
      <rect x={-90} y={-80} width={180} height={50} rx={16} fill={C.red} {...S} />
    </g>
  ),
};

export const Icon: React.FC<{name: string; x?: number; y?: number; s?: number; r?: number}> = ({name, x = 0, y = 0, s = 1, r = 0}) => (
  <g transform={`translate(${x},${y}) rotate(${r}) scale(${s})`}>{icons[name] ?? <Coin />}</g>
);
