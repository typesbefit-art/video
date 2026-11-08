import React from 'react';
import { C, FONT, INK, STROKE, fitFontSize, hash } from './theme';

// Outlined cartoon text in SVG, auto-shrunk to maxWidth.
export const Label: React.FC<{
  text: string; x: number; y: number; size: number; maxWidth?: number; fill?: string; stroke?: string; sw?: number; rotate?: number; scale?: number; anchor?: 'middle' | 'start' | 'end'; weight?: number;
}> = ({ text, x, y, size, maxWidth = 840, fill = '#fff', stroke = INK, sw = 16, rotate = 0, scale = 1, anchor = 'middle', weight = 900 }) => {
  const fs = fitFontSize(text, maxWidth, size, weight);
  return (
    <g transform={`translate(${x} ${y}) rotate(${rotate}) scale(${scale})`}>
      <text x={4} y={8} textAnchor={anchor} fontFamily={FONT} fontWeight={weight} fontSize={fs} fill={INK} stroke={INK} strokeWidth={sw} strokeLinejoin="round" paintOrder="stroke">{text}</text>
      <text x={0} y={0} textAnchor={anchor} fontFamily={FONT} fontWeight={weight} fontSize={fs} fill={fill} stroke={stroke} strokeWidth={sw} strokeLinejoin="round" paintOrder="stroke">{text}</text>
    </g>
  );
};

export const Bill: React.FC<{ x: number; y: number; rot?: number; scale?: number; wings?: number; opacity?: number }> = ({ x, y, rot = 0, scale = 1, wings, opacity = 1 }) => (
  <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${scale})`} opacity={opacity}>
    {wings !== undefined ? (
      <>
        <path d={`M -40 -10 Q -120 ${-80 - wings * 40} -150 ${-20 - wings * 30} Q -100 0 -40 10 Z`} fill="#fff" stroke={INK} strokeWidth={8} strokeLinejoin="round" />
        <path d={`M 40 -10 Q 120 ${-80 - wings * 40} 150 ${-20 - wings * 30} Q 100 0 40 10 Z`} fill="#fff" stroke={INK} strokeWidth={8} strokeLinejoin="round" />
      </>
    ) : null}
    <rect x={-90} y={-48} width={180} height={96} rx={10} fill="#7ed957" stroke={INK} strokeWidth={8} />
    <rect x={-72} y={-32} width={144} height={64} rx={6} fill="none" stroke="#3e9a2a" strokeWidth={5} />
    <circle cx={0} cy={0} r={24} fill="#a8ec88" stroke="#3e9a2a" strokeWidth={5} />
    <text x={0} y={12} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={34} fill="#2d7a1d">$</text>
  </g>
);

export const Wallet: React.FC<{ x: number; y: number; scale?: number; open?: number }> = ({ x, y, scale = 1, open = 1 }) => (
  <g transform={`translate(${x} ${y}) scale(${scale})`}>
    <rect x={-150} y={-100 - 40 * open} width={300} height={90} rx={18} fill="#a0522d" stroke={INK} strokeWidth={STROKE} transform={`rotate(${-12 * open} -150 -60)`} />
    <rect x={-160} y={-80} width={320} height={190} rx={26} fill="#8b4513" stroke={INK} strokeWidth={STROKE} />
    <rect x={60} y={-10} width={120} height={70} rx={18} fill="#a0522d" stroke={INK} strokeWidth={STROKE} />
    <circle cx={110} cy={25} r={12} fill={C.gold} stroke={INK} strokeWidth={6} />
    <path d="M -130 -50 Q -60 -20 0 -50" stroke="#6b3410" strokeWidth={6} fill="none" strokeDasharray="12 10" />
  </g>
);

// Leaky pipe with drips (coins) falling from holes.
export const LeakyPipe: React.FC<{ y: number; t: number; holes: number[]; reveal?: number }> = ({ y, t, holes, reveal = 1 }) => (
  <g>
    <rect x={-100} y={y - 50} width={1280} height={100} fill="#9aa5b8" stroke={INK} strokeWidth={STROKE} />
    <rect x={-100} y={y - 30} width={1280} height={18} fill="#c3ccdb" />
    {[160, 540, 920].map((x) => (
      <rect key={x} x={x - 40} y={y - 66} width={80} height={132} rx={10} fill="#7c879b" stroke={INK} strokeWidth={STROKE} />
    ))}
    {holes.map((hx, i) => {
      if (i / holes.length >= reveal) return null;
      return (
        <g key={hx}>
          <ellipse cx={hx} cy={y + 46} rx={22} ry={10} fill={INK} />
          {[0, 1, 2].map((k) => {
            const p = (t * 0.9 + k / 3 + i * 0.21) % 1;
            const cy = y + 60 + p * 700;
            return (
              <g key={k} transform={`translate(${hx} ${cy}) scale(${1 - p * 0.3})`} opacity={1 - p * p}>
                <circle r={28} fill={C.gold} stroke={INK} strokeWidth={7} />
                <text y={11} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={32} fill={C.goldDark}>$</text>
              </g>
            );
          })}
        </g>
      );
    })}
  </g>
);

const APP_COLORS = ['#ff4d5e', '#3da5ff', '#ffd23f', '#8b5cf6', '#2ec4b6', '#ff8a3d', '#ff7eb6', '#4cd964', '#5b6cff', '#ff5e5b'];
const AppGlyph: React.FC<{ i: number }> = ({ i }) => {
  const g = i % 10;
  const s = { fill: '#fff', stroke: INK, strokeWidth: 6, strokeLinejoin: 'round' as const };
  switch (g) {
    case 0: return <path d="M -18 -26 L 26 0 L -18 26 Z" {...s} />;
    case 1: return <g><circle cx={-12} cy={18} r={12} {...s} /><path d="M 0 18 V -26 L 24 -18" {...s} fill="none" strokeWidth={8} /></g>;
    case 2: return <path d="M -30 14 Q -30 -6 -12 -6 Q -6 -26 12 -20 Q 30 -20 28 0 Q 36 14 22 18 L -24 18 Z" {...s} />;
    case 3: return <g><rect x={-32} y={-16} width={64} height={34} rx={16} {...s} /><circle cx={14} cy={0} r={5} fill={INK} /><path d="M -18 -8 V 8 M -26 0 H -10" stroke={INK} strokeWidth={5} /></g>;
    case 4: return <g><rect x={-28} y={-22} width={56} height={44} rx={6} {...s} /><path d="M -28 -8 H 28" stroke={INK} strokeWidth={5} /></g>;
    case 5: return <path d="M 0 -28 L 8 -8 L 30 -8 L 12 6 L 18 28 L 0 14 L -18 28 L -12 6 L -30 -8 L -8 -8 Z" {...s} />;
    case 6: return <path d="M 0 24 L -26 -2 Q -34 -22 -16 -26 Q -4 -28 0 -14 Q 4 -28 16 -26 Q 34 -22 26 -2 Z" {...s} />;
    case 7: return <g><rect x={-30} y={-8} width={60} height={16} rx={6} {...s} /><rect x={-36} y={-18} width={14} height={36} rx={4} {...s} /><rect x={22} y={-18} width={14} height={36} rx={4} {...s} /></g>;
    case 8: return <g><rect x={-24} y={-28} width={48} height={56} rx={6} {...s} /><path d="M -14 -14 H 14 M -14 0 H 14 M -14 14 H 4" stroke={INK} strokeWidth={5} /></g>;
    default: return <g><circle r={26} {...s} /><path d="M 0 -14 V 0 L 12 8" stroke={INK} strokeWidth={6} fill="none" strokeLinecap="round" /></g>;
  }
};

// Phone with a grid of subscription apps; `crossed` marks indices X-ed out, `gone` fades them.
export const Phone: React.FC<{ x: number; y: number; scale?: number; t: number; reveal?: number; crossed?: number; gone?: number; screen?: 'apps' | 'cancel'; tap?: number; cancelLabel?: string; priceLabel?: string }> = ({
  x, y, scale = 1, t, reveal = 1, crossed = 0, gone = 0, screen = 'apps', tap = 0, cancelLabel = 'ОТМЕНИТЬ', priceLabel = '$5',
}) => (
  <g transform={`translate(${x} ${y}) scale(${scale})`}>
    <rect x={-200} y={-380} width={400} height={760} rx={56} fill={INK} />
    <rect x={-176} y={-340} width={352} height={680} rx={30} fill="#f4f1ff" />
    <rect x={-50} y={-366} width={100} height={14} rx={7} fill="#4a4566" />
    {screen === 'apps'
      ? Array.from({ length: 10 }).map((_, i) => {
          const col = i % 3;
          const row = Math.floor(i / 3);
          const cx = -110 + col * 110 + (i === 9 ? 110 : 0);
          const cy = -250 + row * 140;
          const appear = Math.max(0, Math.min(1, reveal * 10 - i));
          const isCrossed = i % 2 === 1 && Math.floor(i / 2) < crossed * 5;
          const fade = isCrossed ? 1 - gone : 1;
          const wob = Math.sin(t * 4 + i) * 3;
          return (
            <g key={i} transform={`translate(${cx} ${cy + wob}) scale(${appear * (isCrossed ? 0.6 + 0.4 * fade : 1)})`} opacity={fade}>
              <rect x={-44} y={-44} width={88} height={88} rx={22} fill={isCrossed ? '#b9b4c9' : APP_COLORS[i]} stroke={INK} strokeWidth={7} />
              <AppGlyph i={i} />
              <text x={30} y={-30} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={24} fill="#fff" stroke={INK} strokeWidth={6} paintOrder="stroke">{priceLabel}</text>
              {isCrossed ? (
                <g stroke={C.red} strokeWidth={14} strokeLinecap="round">
                  <path d="M -38 -38 L 38 38" />
                  <path d="M 38 -38 L -38 38" />
                </g>
              ) : null}
            </g>
          );
        })
      : (
        <g>
          <rect x={-140} y={-300} width={280} height={60} rx={14} fill="#dcd6f5" />
          <rect x={-140} y={-220} width={200} height={30} rx={10} fill="#dcd6f5" />
          {[0, 1, 2].map((r) => (
            <g key={r} transform={`translate(0 ${-130 + r * 100})`}>
              <rect x={-140} y={-36} width={280} height={72} rx={16} fill="#fff" stroke={INK} strokeWidth={6} />
              <rect x={-124} y={-22} width={44} height={44} rx={12} fill={APP_COLORS[r * 3 + 1]} />
              <rect x={-66} y={-10} width={110} height={20} rx={8} fill="#dcd6f5" />
              <text x={110} y={10} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={26} fill={C.red}>{priceLabel}</text>
            </g>
          ))}
          <g transform={`translate(0 210) scale(${1 - 0.08 * tap})`}>
            <rect x={-140} y={-50} width={280} height={100} rx={50} fill={C.red} stroke={INK} strokeWidth={8} />
            <Label text={cancelLabel} x={0} y={14} size={40} maxWidth={240} sw={8} />
          </g>
        </g>
      )}
  </g>
);

// Pointing hand cursor
export const Hand: React.FC<{ x: number; y: number; scale?: number; rot?: number }> = ({ x, y, scale = 1, rot = 0 }) => (
  <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${scale})`}>
    <path d="M -14 0 L -14 -90 Q -14 -110 6 -110 Q 26 -110 26 -90 L 26 -30 Q 50 -40 60 -20 Q 82 -26 88 -4 Q 112 -8 112 20 L 106 80 Q 100 120 60 120 L 10 120 Q -20 120 -36 90 L -70 30 Q -80 6 -56 0 Q -36 -4 -14 30 Z" fill="#fff" stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
  </g>
);

export const ShoppingBag: React.FC<{ x: number; y: number; color: string; scale?: number; rot?: number; label?: string }> = ({ x, y, color, scale = 1, rot = 0, label }) => (
  <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${scale})`}>
    <path d="M -50 -110 Q -50 -170 0 -170 Q 50 -170 50 -110" stroke={INK} strokeWidth={14} fill="none" />
    <path d="M -100 -120 L 100 -120 L 120 100 L -120 100 Z" fill={color} stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
    {label ? <Label text={label} x={0} y={10} size={56} maxWidth={190} sw={10} /> : <circle cx={0} cy={-10} r={30} fill="#fff" opacity={0.6} />}
  </g>
);

export const SaleTag: React.FC<{ x: number; y: number; text: string; swing: number; scale?: number }> = ({ x, y, text, swing, scale = 1 }) => (
  <g transform={`translate(${x} ${y}) rotate(${swing}) scale(${scale})`}>
    <line x1={0} y1={-140} x2={0} y2={-60} stroke={INK} strokeWidth={8} />
    <path d="M -130 -60 L 130 -60 L 130 100 L -130 100 Z" fill={C.red} stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
    <circle cx={0} cy={-34} r={12} fill="#fff" stroke={INK} strokeWidth={6} />
    <Label text={text} x={0} y={70} size={88} maxWidth={230} fill={C.yellow} sw={12} />
  </g>
);

export const Clock: React.FC<{ x: number; y: number; r?: number; t: number; speed?: number; label?: string }> = ({ x, y, r = 200, t, speed = 1, label }) => (
  <g transform={`translate(${x} ${y})`}>
    <circle r={r + 24} fill={C.red} stroke={INK} strokeWidth={STROKE} />
    <circle r={r} fill="#fff" stroke={INK} strokeWidth={STROKE} />
    {Array.from({ length: 12 }).map((_, i) => {
      const a = (i / 12) * Math.PI * 2;
      return <line key={i} x1={Math.sin(a) * (r - 20)} y1={-Math.cos(a) * (r - 20)} x2={Math.sin(a) * (r - 44)} y2={-Math.cos(a) * (r - 44)} stroke={INK} strokeWidth={i % 3 === 0 ? 12 : 6} strokeLinecap="round" />;
    })}
        <line x1={0} y1={0} x2={Math.sin(t * speed * 0.5) * r * 0.5} y2={-Math.cos(t * speed * 0.5) * r * 0.5} stroke={INK} strokeWidth={18} strokeLinecap="round" />
    <line x1={0} y1={0} x2={Math.sin(t * speed * 6) * r * 0.78} y2={-Math.cos(t * speed * 6) * r * 0.78} stroke={C.red} strokeWidth={10} strokeLinecap="round" />
    <circle r={18} fill={INK} />
    {label ? <Label text={label} x={0} y={r * 0.72} size={r * 0.34} maxWidth={r * 0.9} fill={C.red} sw={10} /> : null}
    {/* bells */}
    <circle cx={-r * 0.75} cy={-r * 0.95} r={r * 0.22} fill={C.red} stroke={INK} strokeWidth={STROKE} />
    <circle cx={r * 0.75} cy={-r * 0.95} r={r * 0.22} fill={C.red} stroke={INK} strokeWidth={STROKE} />
  </g>
);

export const Piggy: React.FC<{ x: number; y: number; scale?: number; t: number; fill?: number; sad?: boolean }> = ({ x, y, scale = 1, t, fill = 0, sad = false }) => {
  const s = scale * (1 + fill * 0.25);
  const wob = Math.sin(t * 5) * 2;
  return (
    <g transform={`translate(${x} ${y}) scale(${s}) rotate(${wob})`}>
      <ellipse cx={0} cy={150} rx={170} ry={20} fill="rgba(0,0,0,0.16)" />
      {[-110, -40, 40, 110].map((lx) => (
        <rect key={lx} x={lx - 24} y={60} width={48} height={90} rx={16} fill="#ff8fb3" stroke={INK} strokeWidth={STROKE} />
      ))}
      <ellipse cx={0} cy={0} rx={200} ry={150} fill={C.pink} stroke={INK} strokeWidth={STROKE} />
      <path d="M -120 -110 L -150 -190 L -60 -140 Z" fill="#ff8fb3" stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
      <path d="M 60 -140 L 140 -190 L 120 -110 Z" fill="#ff8fb3" stroke={INK} strokeWidth={STROKE} strokeLinejoin="round" />
      <rect x={-50} y={-150} width={100} height={16} rx={8} fill={INK} />
      <ellipse cx={175} cy={20} rx={52} ry={44} fill="#ff8fb3" stroke={INK} strokeWidth={STROKE} />
      <circle cx={162} cy={20} r={8} fill={INK} />
      <circle cx={190} cy={20} r={8} fill={INK} />
      <circle cx={80} cy={-40} r={14} fill={INK} />
      {sad ? <path d="M 50 50 Q 80 30 110 50" stroke={INK} strokeWidth={9} fill="none" strokeLinecap="round" /> : <path d="M 50 40 Q 80 70 110 40" stroke={INK} strokeWidth={9} fill="none" strokeLinecap="round" />}
      <path d="M -200 0 Q -250 -30 -230 -60 Q -210 -80 -240 -100" stroke={INK} strokeWidth={10} fill="none" strokeLinecap="round" />
    </g>
  );
};

export const FallingCoin: React.FC<{ x: number; y: number; r?: number; rot?: number }> = ({ x, y, r = 40, rot = 0 }) => (
  <g transform={`translate(${x} ${y}) rotate(${rot})`}>
    <circle r={r} fill={C.gold} stroke={INK} strokeWidth={8} />
    <circle r={r * 0.72} fill="none" stroke={C.goldDark} strokeWidth={5} />
    <text y={r * 0.38} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={r * 1.05} fill={C.goldDark}>$</text>
  </g>
);

export const Sparkles: React.FC<{ t: number; cx: number; cy: number; spread?: number; n?: number; color?: string }> = ({ t, cx, cy, spread = 300, n = 8, color = '#fff' }) => (
  <g>
    {Array.from({ length: n }).map((_, i) => {
      const a = hash(i) * Math.PI * 2;
      const d = spread * (0.5 + hash(i + 9) * 0.5);
      const p = (t * 0.8 + hash(i + 3)) % 1;
      const s = Math.sin(p * Math.PI) * (14 + hash(i + 5) * 14);
      return <path key={i} transform={`translate(${cx + Math.cos(a) * d} ${cy + Math.sin(a) * d}) scale(${s / 10})`} d="M0 -10 L3 -3 L10 0 L3 3 L0 10 L-3 3 L-10 0 L-3 -3 Z" fill={color} stroke={INK} strokeWidth={1.5} />;
    })}
  </g>
);

export const QuestionMark: React.FC<{ x: number; y: number; scale?: number; rot?: number }> = ({ x, y, scale = 1, rot = 0 }) => (
  <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${scale})`}>
    <text x={8} y={10} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={360} fill={INK}>?</text>
    <text x={0} y={0} textAnchor="middle" fontFamily={FONT} fontWeight={900} fontSize={360} fill={C.yellow} stroke={INK} strokeWidth={14} paintOrder="stroke">?</text>
  </g>
);

export const Calendar: React.FC<{ x: number; y: number; scale?: number; page: number; label: string }> = ({ x, y, scale = 1, page, label }) => (
  <g transform={`translate(${x} ${y}) scale(${scale})`}>
    <rect x={-150} y={-160} width={300} height={320} rx={24} fill="#fff" stroke={INK} strokeWidth={STROKE} />
    <rect x={-150} y={-160} width={300} height={90} rx={24} fill={C.red} stroke={INK} strokeWidth={STROKE} />
    <circle cx={-80} cy={-170} r={14} fill={INK} />
    <circle cx={80} cy={-170} r={14} fill={INK} />
    <g transform={`translate(0 -70) scale(1 ${Math.abs(Math.cos(page * Math.PI))}) translate(0 70)`}>
      <Label text={label} x={0} y={70} size={150} maxWidth={250} fill={INK} stroke="#fff" sw={0} />
    </g>
  </g>
);

export const Chart: React.FC<{ x: number; y: number; w: number; h: number; progress: number }> = ({ x, y, w, h, progress }) => {
  const pts = Array.from({ length: 9 }).map((_, i) => {
    const px = (i / 8) * w;
    const py = h - Math.pow(i / 8, 1.8) * h * 0.95 - Math.sin(i * 1.7) * 18;
    return [px, py];
  });
  const n = Math.max(1, Math.floor(progress * 8));
  const visible = pts.slice(0, n + 1);
  const d = visible.map((p, i) => `${i ? 'L' : 'M'} ${p[0]} ${p[1]}`).join(' ');
  const last = visible[visible.length - 1];
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect x={-30} y={-30} width={w + 60} height={h + 60} rx={24} fill="#fff" stroke={INK} strokeWidth={STROKE} />
      {Array.from({ length: 8 }).map((_, i) => (
        <rect key={i} x={(i / 8) * w + 8} y={h - Math.pow((i + 1) / 8, 1.8) * h * 0.95 * Math.min(1, progress * 8 - i)} width={w / 8 - 16} height={Math.max(0, Math.pow((i + 1) / 8, 1.8) * h * 0.95 * Math.min(1, progress * 8 - i))} fill={C.green} opacity={0.35} />
      ))}
      <path d={d} stroke={C.green} strokeWidth={18} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d={d} stroke={INK} strokeWidth={4} fill="none" strokeLinecap="round" strokeLinejoin="round" opacity={0.25} />
      <FallingCoin x={last[0]} y={last[1]} r={34} />
    </g>
  );
};
