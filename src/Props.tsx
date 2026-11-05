import React from 'react';

const O = '#3A2414';

export const Heart: React.FC<{size?: number; color?: string}> = ({size = 90, color = '#FF4D6D'}) => (
  <svg width={size} height={size} viewBox="0 0 100 100" style={{overflow: 'visible'}}>
    <path
      d="M50 88 C 18 66, 4 46, 12 28 C 20 10, 42 10, 50 28 C 58 10, 80 10, 88 28 C 96 46, 82 66, 50 88 Z"
      fill={color}
      stroke={O}
      strokeWidth={6}
      strokeLinejoin="round"
    />
    <ellipse cx={30} cy={32} rx={8} ry={5} fill="#fff" opacity={0.7} transform="rotate(-30 30 32)" />
  </svg>
);

export const PawPrint: React.FC<{size?: number; color?: string}> = ({size = 90, color = '#A8622F'}) => (
  <svg width={size} height={size} viewBox="0 0 100 100">
    <ellipse cx={50} cy={64} rx={24} ry={20} fill={color} />
    <ellipse cx={22} cy={40} rx={10} ry={13} fill={color} />
    <ellipse cx={40} cy={24} rx={10} ry={13} fill={color} />
    <ellipse cx={60} cy={24} rx={10} ry={13} fill={color} />
    <ellipse cx={78} cy={40} rx={10} ry={13} fill={color} />
  </svg>
);

export const AlarmClock: React.FC<{t: number; size?: number}> = ({t, size = 260}) => {
  const shake = Math.sin(t * 2.2) * 9;
  const ringOn = Math.floor(t / 4) % 2 === 0;
  return (
    <svg width={size} height={size} viewBox="0 0 200 200" style={{overflow: 'visible'}}>
      <g transform={`rotate(${shake} 100 110)`}>
        {/* bells */}
        <circle cx={52} cy={42} r={26} fill="#FFD23F" stroke={O} strokeWidth={6} />
        <circle cx={148} cy={42} r={26} fill="#FFD23F" stroke={O} strokeWidth={6} />
        <path d="M100 30 v-14 M88 16 h24" stroke={O} strokeWidth={7} strokeLinecap="round" />
        {/* legs */}
        <path d="M60 165 l-16 22 M140 165 l16 22" stroke={O} strokeWidth={9} strokeLinecap="round" />
        {/* body */}
        <circle cx={100} cy={110} r={72} fill="#FF5A5F" stroke={O} strokeWidth={7} />
        <circle cx={100} cy={110} r={54} fill="#fff" stroke={O} strokeWidth={5} />
        {[0, 90, 180, 270].map((a) => (
          <rect key={a} x={97} y={62} width={6} height={12} rx={3} fill={O} transform={`rotate(${a} 100 110)`} />
        ))}
        {/* hands: 6:00 */}
        <path d="M100 110 V 76" stroke={O} strokeWidth={6} strokeLinecap="round" />
        <path d="M100 110 V 146" stroke={O} strokeWidth={8} strokeLinecap="round" />
        <circle cx={100} cy={110} r={7} fill={O} />
      </g>
      {ringOn ? (
        <g stroke={O} strokeWidth={7} strokeLinecap="round" fill="none">
          <path d="M14 20 q-12 18 0 36" />
          <path d="M-6 10 q-18 28 0 56" />
          <path d="M186 20 q12 18 0 36" />
          <path d="M206 10 q18 28 0 56" />
        </g>
      ) : null}
    </svg>
  );
};

export const Keys: React.FC<{t: number; size?: number}> = ({t, size = 220}) => {
  const swing = Math.sin(t * 0.25) * 18;
  const key = (rot: number, color: string) => (
    <g transform={`rotate(${rot} 100 60)`}>
      <path
        d="M100 70 V 170 M100 140 h18 M100 160 h12"
        stroke={O}
        strokeWidth={16}
        strokeLinecap="round"
        fill="none"
      />
      <path d="M100 70 V 170 M100 140 h18 M100 160 h12" stroke={color} strokeWidth={8} strokeLinecap="round" fill="none" />
      <circle cx={100} cy={76} r={22} fill={color} stroke={O} strokeWidth={6} />
      <circle cx={100} cy={76} r={8} fill="#fff" stroke={O} strokeWidth={4} />
    </g>
  );
  return (
    <svg width={size} height={size * 1.1} viewBox="0 0 200 220" style={{overflow: 'visible'}}>
      <g transform={`rotate(${swing} 100 20)`}>
        <circle cx={100} cy={40} r={24} fill="none" stroke={O} strokeWidth={12} />
        <circle cx={100} cy={40} r={24} fill="none" stroke="#C9CED6" strokeWidth={6} />
        {key(-22, '#FFD23F')}
        {key(18, '#9AA5B1')}
      </g>
    </svg>
  );
};

export const Squirrel: React.FC<{t: number; size?: number}> = ({t, size = 260}) => {
  const tail = Math.sin(t * 0.4) * 8;
  return (
    <svg width={size} height={size} viewBox="0 0 200 200" style={{overflow: 'visible'}}>
      {/* tail */}
      <g transform={`rotate(${tail} 120 150)`}>
        <path
          d="M118 160 C 190 160, 200 60, 150 30 C 120 12, 100 50, 130 62 C 160 76, 150 120, 118 130 Z"
          fill="#E2763A"
          stroke={O}
          strokeWidth={6}
          strokeLinejoin="round"
        />
        <path d="M140 50 C 170 70, 168 120, 135 140" stroke="#F4A261" strokeWidth={10} fill="none" strokeLinecap="round" />
      </g>
      {/* body */}
      <ellipse cx={92} cy={140} rx={40} ry={48} fill="#E2763A" stroke={O} strokeWidth={6} />
      <ellipse cx={86} cy={150} rx={22} ry={30} fill="#FFE0C2" />
      {/* head */}
      <circle cx={80} cy={82} r={34} fill="#E2763A" stroke={O} strokeWidth={6} />
      <path d="M62 56 l-4 -26 l20 18 Z" fill="#E2763A" stroke={O} strokeWidth={5} strokeLinejoin="round" />
      <path d="M92 52 l8 -24 l10 24 Z" fill="#E2763A" stroke={O} strokeWidth={5} strokeLinejoin="round" />
      <circle cx={70} cy={80} r={8} fill={O} />
      <circle cx={73} cy={77} r={3} fill="#fff" />
      <circle cx={52} cy={92} r={6} fill={O} />
      <ellipse cx={66} cy={98} rx={10} ry={6} fill="#FF8FA3" opacity={0.6} />
      {/* acorn */}
      <g transform="translate(46 128)">
        <ellipse cx={0} cy={8} rx={13} ry={15} fill="#C68642" stroke={O} strokeWidth={4} />
        <path d="M-15 0 q15 -14 30 0 Z" fill="#7A4A21" stroke={O} strokeWidth={4} strokeLinejoin="round" />
      </g>
      {/* feet */}
      <ellipse cx={74} cy={186} rx={16} ry={8} fill="#E2763A" stroke={O} strokeWidth={5} />
      <ellipse cx={110} cy={186} rx={16} ry={8} fill="#E2763A" stroke={O} strokeWidth={5} />
    </svg>
  );
};

export const Sock: React.FC<{t: number; size?: number}> = ({t, size = 200}) => (
  <svg width={size} height={size} viewBox="0 0 200 200" style={{overflow: 'visible'}}>
    <g transform={`rotate(${-20 + Math.sin(t * 0.15) * 4} 100 100)`}>
      <path
        d="M70 20 h60 v100 c0 30 -10 50 -45 60 c-30 8 -60 -4 -64 -28 c-4 -22 14 -34 34 -40 c10 -4 15 -10 15 -20 Z"
        fill="#fff"
        stroke={O}
        strokeWidth={7}
        strokeLinejoin="round"
      />
      <path d="M70 20 h60 v24 h-60 Z" fill="#3A86FF" stroke={O} strokeWidth={6} />
      <path d="M70 62 h60" stroke="#FF4D6D" strokeWidth={12} />
      <path d="M70 88 h60" stroke="#FF4D6D" strokeWidth={12} />
      {/* holes from chewing */}
      <circle cx={45} cy={160} r={7} fill={O} opacity={0.8} />
      <circle cx={88} cy={150} r={5} fill={O} opacity={0.8} />
    </g>
  </svg>
);

export const SubscribeButton: React.FC<{t: number}> = ({t}) => {
  const pulse = 1 + Math.sin(t * 0.25) * 0.06;
  const ring = (t % 40) / 40;
  return (
    <div style={{position: 'relative', display: 'flex', justifyContent: 'center', alignItems: 'center'}}>
      <div
        style={{
          position: 'absolute',
          width: 640,
          height: 150,
          borderRadius: 75,
          border: '8px solid #FF3B5C',
          opacity: 1 - ring,
          transform: `scale(${1 + ring * 0.25})`,
        }}
      />
      <div
        style={{
          transform: `scale(${pulse})`,
          background: '#FF3B5C',
          color: '#fff',
          fontSize: 76,
          fontWeight: 900,
          padding: '22px 64px',
          borderRadius: 80,
          border: '8px solid #3A2414',
          boxShadow: '0 12px 0 #3A2414',
          display: 'flex',
          alignItems: 'center',
          gap: 22,
          whiteSpace: 'nowrap',
        }}
      >
        <span
          style={{
            width: 70,
            height: 70,
            borderRadius: 35,
            background: '#fff',
            color: '#FF3B5C',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 70,
            lineHeight: 1,
          }}
        >
          +
        </span>
        Подписаться
      </div>
    </div>
  );
};
