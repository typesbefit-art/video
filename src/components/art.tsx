/**
 * Библиотека процедурных 2D-элементов (SVG): небо, солнце, горы, город,
 * облака, земля, ЛЭП. Всё детерминировано через random(seed).
 *
 * Стиль «2D реализм»: силуэты с контровым светом (rim light), градиентные
 * тени, атмосферная перспектива (дальние слои светлее и холоднее).
 */
import React, {useMemo} from 'react';
import {random} from 'remotion';
import {H, W, n1} from '../lib/math';

export type Stop = [number, string];

export const LinearGradient: React.FC<{id: string; stops: Stop[]; x2?: number; y2?: number; opacity?: number[]}> = ({
  id,
  stops,
  x2 = 0,
  y2 = 1,
  opacity,
}) => (
  <linearGradient id={id} x1={0} y1={0} x2={x2} y2={y2}>
    {stops.map(([o, c], i) => (
      <stop key={i} offset={o} stopColor={c} stopOpacity={opacity ? opacity[i] : 1} />
    ))}
  </linearGradient>
);

/** Небо — вертикальный градиент на весь кадр (с запасом под тряску). */
export const Sky: React.FC<{id: string; stops: Stop[]}> = ({id, stops}) => (
  <>
    <defs>
      <LinearGradient id={id} stops={stops} />
    </defs>
    <rect x={-300} y={-300} width={W + 600} height={H + 600} fill={`url(#${id})`} />
  </>
);

/** Светило с ореолом. */
export const Sun: React.FC<{
  id: string;
  cx: number;
  cy: number;
  r: number;
  core?: string;
  glow?: string;
  glowR?: number;
  opacity?: number;
}> = ({id, cx, cy, r, core = '#fff4d6', glow = '#ffb26b', glowR = 6, opacity = 1}) => (
  <g opacity={opacity}>
    <defs>
      <radialGradient id={`${id}-g`}>
        <stop offset="0%" stopColor={glow} stopOpacity={0.9} />
        <stop offset="25%" stopColor={glow} stopOpacity={0.35} />
        <stop offset="100%" stopColor={glow} stopOpacity={0} />
      </radialGradient>
    </defs>
    <circle cx={cx} cy={cy} r={r * glowR} fill={`url(#${id}-g)`} />
    <circle cx={cx} cy={cy} r={r} fill={core} />
  </g>
);

/** Радиальное зарево (горизонт, вспышка, свет окна). */
export const Glow: React.FC<{
  id: string;
  cx: number;
  cy: number;
  rx: number;
  ry?: number;
  color: string;
  opacity?: number;
  falloff?: number;
}> = ({id, cx, cy, rx, ry, color, opacity = 1, falloff = 0.4}) => (
  <g opacity={opacity}>
    <defs>
      <radialGradient id={id}>
        <stop offset="0%" stopColor={color} stopOpacity={1} />
        <stop offset={falloff} stopColor={color} stopOpacity={0.45} />
        <stop offset="100%" stopColor={color} stopOpacity={0} />
      </radialGradient>
    </defs>
    <ellipse cx={cx} cy={cy} rx={rx} ry={ry ?? rx} fill={`url(#${id})`} />
  </g>
);

/** Горная гряда / холмы из шума. */
export const Ridge: React.FC<{
  seed: string;
  baseY: number;
  amp: number;
  color: string;
  freq?: number;
  top?: string;
  id?: string;
}> = ({seed, baseY, amp, color, freq = 0.004, top, id}) => {
  const d = useMemo(() => {
    const pts: string[] = [];
    for (let x = -300; x <= W + 300; x += 12) {
      const y = baseY - (n1(seed, x * freq) * 0.6 + n1(seed + 'b', x * freq * 3) * 0.25 + 0.6) * amp;
      pts.push(`${x},${y.toFixed(1)}`);
    }
    return `M-300,${H + 300} L${pts.join(' L')} L${W + 300},${H + 300} Z`;
  }, [seed, baseY, amp, freq]);
  const gid = id ?? `ridge-${seed}`;
  return (
    <>
      {top && (
        <defs>
          <LinearGradient id={gid} stops={[[0, top], [0.25, color], [1, color]]} />
        </defs>
      )}
      <path d={d} fill={top ? `url(#${gid})` : color} />
    </>
  );
};

// ------------------------------------------------------------------ Город
type Building = {
  x: number;
  w: number;
  h: number;
  roof: 'flat' | 'antenna' | 'step' | 'tank' | 'spire' | 'slope';
  windows: {x: number; y: number; w: number; h: number; k: number}[];
};

const makeCity = (seed: string, x0: number, x1: number, minH: number, maxH: number, scale: number): Building[] => {
  const out: Building[] = [];
  let x = x0;
  let i = 0;
  while (x < x1) {
    const r = (s: string) => random(`${seed}-${s}-${i}`);
    const w = (50 + r('w') * 110) * scale;
    // высотки чаще в центре — естественный силуэт «сити»
    const centre = 1 - Math.min(1, Math.abs((x + w / 2 - W / 2) / (W * 0.7)));
    const h = minH + (maxH - minH) * Math.pow(r('h'), 1.4) * (0.45 + centre * 0.75);
    const roofs: Building['roof'][] = ['flat', 'flat', 'antenna', 'step', 'tank', 'spire', 'slope'];
    const roof = roofs[Math.floor(r('roof') * roofs.length)];
    const windows: Building['windows'] = [];
    const ww = 7 * scale;
    const wh = 11 * scale;
    const gx = 17 * scale;
    const gy = 24 * scale;
    const cols = Math.max(1, Math.floor((w - 10 * scale) / gx));
    const rows = Math.max(1, Math.floor((h - 20 * scale) / gy));
    const offX = (w - cols * gx) / 2 + (gx - ww) / 2;
    for (let cx = 0; cx < cols; cx++) {
      for (let ry = 0; ry < rows; ry++) {
        windows.push({
          x: x + offX + cx * gx,
          y: 14 * scale + ry * gy,
          w: ww,
          h: wh,
          k: random(`${seed}-win-${i}-${cx}-${ry}`),
        });
      }
    }
    out.push({x, w, h, roof, windows});
    x += w + (r('gap') < 0.3 ? r('g2') * 18 * scale : -2);
    i++;
  }
  return out;
};

/**
 * Силуэт города. lit — доля горящих окон (0..1): уменьшайте её во времени,
 * чтобы окна гасли. snow — шапки снега на крышах.
 */
export const Skyline: React.FC<{
  seed: string;
  baseY: number;
  minH?: number;
  maxH?: number;
  scale?: number;
  color: string;
  rim?: string;
  rimSide?: 'left' | 'right';
  rimOpacity?: number;
  windowColor?: string;
  lit?: number;
  frame?: number;
  snow?: number;
  x0?: number;
  x1?: number;
}> = ({
  seed,
  baseY,
  minH = 120,
  maxH = 520,
  scale = 1,
  color,
  rim,
  rimSide = 'right',
  rimOpacity = 0.5,
  windowColor = '#ffcf7a',
  lit = 0,
  frame = 0,
  snow = 0,
  x0 = -200,
  x1 = W + 200,
}) => {
  const city = useMemo(() => makeCity(seed, x0, x1, minH, maxH, scale), [seed, x0, x1, minH, maxH, scale]);
  return (
    <g>
      {city.map((b, i) => {
        const top = baseY - b.h;
        const roofEl = (() => {
          switch (b.roof) {
            case 'antenna':
              return <rect x={b.x + b.w * 0.6} y={top - 70 * scale} width={3 * scale} height={70 * scale} fill={color} />;
            case 'step':
              return <rect x={b.x + b.w * 0.2} y={top - 30 * scale} width={b.w * 0.6} height={31 * scale} fill={color} />;
            case 'tank':
              return (
                <g fill={color}>
                  <rect x={b.x + b.w * 0.25} y={top - 34 * scale} width={22 * scale} height={24 * scale} rx={3} />
                  <rect x={b.x + b.w * 0.25 + 4} y={top - 10 * scale} width={2} height={10 * scale} />
                  <rect x={b.x + b.w * 0.25 + 16 * scale} y={top - 10 * scale} width={2} height={10 * scale} />
                </g>
              );
            case 'spire':
              return <path d={`M${b.x + b.w * 0.35},${top} L${b.x + b.w * 0.5},${top - 120 * scale} L${b.x + b.w * 0.65},${top} Z`} fill={color} />;
            case 'slope':
              return <path d={`M${b.x},${top} L${b.x + b.w},${top - 40 * scale} L${b.x + b.w},${top} Z`} fill={color} />;
            default:
              return null;
          }
        })();
        const rimX = rimSide === 'right' ? b.x + b.w - 4 * scale : b.x;
        return (
          <g key={i}>
            {roofEl}
            <rect x={b.x} y={top} width={b.w} height={b.h + 400} fill={color} />
            {rim && (
              <rect x={rimX} y={top} width={4 * scale} height={b.h + 400} fill={rim} opacity={rimOpacity} />
            )}
            {lit > 0 &&
              b.windows.map((w, j) =>
                w.k < lit ? (
                  <rect
                    key={j}
                    x={w.x}
                    y={top + w.y}
                    width={w.w}
                    height={w.h}
                    fill={windowColor}
                    opacity={0.55 + 0.45 * (0.5 + 0.5 * Math.sin(frame * 0.05 + w.k * 40))}
                  />
                ) : null,
              )}
            {snow > 0 && (
              <rect x={b.x - 2} y={top - 6 * scale * snow} width={b.w + 4} height={8 * scale * snow} rx={4} fill="#e9eef3" opacity={0.9} />
            )}
          </g>
        );
      })}
    </g>
  );
};

/** Облака / пелена дыма: размытые эллипсы, медленный дрейф. */
export const Clouds: React.FC<{
  seed: string;
  y: number;
  spread?: number;
  count?: number;
  color: string;
  opacity?: number;
  drift?: number;
  size?: number;
  blur?: number;
  frame: number;
}> = ({seed, y, spread = 300, count = 10, color, opacity = 0.8, drift = 0.3, size = 1, blur = 30, frame}) => {
  const items = useMemo(
    () =>
      new Array(count).fill(0).map((_, i) => ({
        x: random(`${seed}-cx-${i}`) * (W + 800) - 400,
        y: y + (random(`${seed}-cy-${i}`) - 0.5) * spread,
        rx: (180 + random(`${seed}-rx-${i}`) * 320) * size,
        ry: (50 + random(`${seed}-ry-${i}`) * 90) * size,
        v: 0.5 + random(`${seed}-v-${i}`),
      })),
    [seed, y, spread, count, size],
  );
  const fid = `blur-${seed}`;
  return (
    <g opacity={opacity}>
      <defs>
        <filter id={fid} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation={blur} />
        </filter>
      </defs>
      <g filter={`url(#${fid})`}>
        {items.map((c, i) => {
          const span = W + 1400;
          const x = ((c.x + frame * drift * c.v + 700) % span + span) % span - 700;
          return <ellipse key={i} cx={x} cy={c.y} rx={c.rx} ry={c.ry} fill={color} />;
        })}
      </g>
    </g>
  );
};

/** Земля / передний план с градиентом. */
export const Ground: React.FC<{id: string; y: number; stops: Stop[]}> = ({id, y, stops}) => (
  <>
    <defs>
      <LinearGradient id={id} stops={stops} />
    </defs>
    <rect x={-300} y={y} width={W + 600} height={H - y + 400} fill={`url(#${id})`} />
  </>
);

/** Опоры ЛЭП и провода — детальный передний план. */
export const PowerLines: React.FC<{y: number; color: string; scale?: number; sag?: number}> = ({
  y,
  color,
  scale = 1,
  sag = 50,
}) => {
  const poles = [-120, 420, 960, 1500];
  const top = y - 520 * scale;
  return (
    <g fill={color} stroke={color}>
      {poles.map((px, i) => (
        <g key={i}>
          <path
            d={`M${px - 24 * scale},${y + 200} L${px - 6 * scale},${top} L${px + 6 * scale},${top} L${px + 24 * scale},${y + 200} Z`}
            strokeWidth={0}
          />
          <rect x={px - 90 * scale} y={top + 30 * scale} width={180 * scale} height={8 * scale} strokeWidth={0} />
          <rect x={px - 60 * scale} y={top + 90 * scale} width={120 * scale} height={6 * scale} strokeWidth={0} />
          {[-80, 0, 80].map((dx, j) => (
            <rect key={j} x={px + dx * scale - 3} y={top + 38 * scale} width={6} height={14 * scale} strokeWidth={0} />
          ))}
        </g>
      ))}
      {poles.slice(0, -1).flatMap((px, i) =>
        [-80, 0, 80].map((dx, j) => {
          const x1 = px + dx * scale;
          const x2 = poles[i + 1] + dx * scale;
          const yy = top + 52 * scale;
          return (
            <path
              key={`${i}-${j}`}
              d={`M${x1},${yy} Q${(x1 + x2) / 2},${yy + sag * scale} ${x2},${yy}`}
              fill="none"
              strokeWidth={2.2}
            />
          );
        }),
      )}
    </g>
  );
};

/** Стая птиц вдалеке (силуэты-«галочки»). */
export const Birds: React.FC<{frame: number; x: number; y: number; count?: number; color?: string; seed?: string}> = ({
  frame,
  x,
  y,
  count = 7,
  color = '#1c2330',
  seed = 'birds',
}) => (
  <g stroke={color} strokeWidth={3} fill="none" strokeLinecap="round">
    {new Array(count).fill(0).map((_, i) => {
      const bx = x + random(`${seed}${i}x`) * 260 + frame * 1.6;
      const by = y + random(`${seed}${i}y`) * 120 + Math.sin(frame * 0.05 + i) * 6;
      const s = 8 + random(`${seed}${i}s`) * 8;
      const flap = Math.sin(frame * 0.4 + i * 1.7) * s * 0.6;
      return <path key={i} d={`M${bx - s},${by - flap} Q${bx - s / 3},${by} ${bx},${by} Q${bx + s / 3},${by} ${bx + s},${by - flap}`} />;
    })}
  </g>
);

/** Столб дыма/осадков, поднимающийся и сносимый ветром. */
export const Plume: React.FC<{
  seed: string;
  x: number;
  y: number;
  height: number;
  wind: number;
  frame: number;
  color: string;
  width?: number;
  count?: number;
  speed?: number;
  opacity?: number;
}> = ({seed, x, y, height, wind, frame, color, width = 60, count = 26, speed = 1, opacity = 1}) => {
  const gid = `plume-${seed}`;
  return (
    <g opacity={opacity}>
      <defs>
        <radialGradient id={gid}>
          <stop offset="0" stopColor={color} stopOpacity={0.6} />
          <stop offset="0.6" stopColor={color} stopOpacity={0.25} />
          <stop offset="1" stopColor={color} stopOpacity={0} />
        </radialGradient>
      </defs>
      {new Array(count).fill(0).map((_, i) => {
        const L = 260 / speed;
        const ph = (((frame + random(`${seed}${i}`) * L) % L) + L) % L / L;
        const py = y - ph * height;
        const px = x + ph * ph * wind + n1(`${seed}w`, ph * 3 + i) * 20 * ph;
        const r = width * (0.5 + ph * 2.4);
        const o = Math.min(1, ph * 8) * (1 - ph);
        return <circle key={i} cx={px} cy={py} r={r} fill={`url(#${gid})`} opacity={o} />;
      })}
    </g>
  );
};

/**
 * Поле колосьев в перспективе. wither 0..1 — урожай гибнет (стебли никнут, цвет
 * уходит в серо-бурый), frost 0..1 — иней, sway — ветер.
 */
export const CropField: React.FC<{
  seed: string;
  y: number;
  frame: number;
  wither?: number;
  frost?: number;
  rows?: number;
  perRow?: number;
  green?: string;
  dead?: string;
}> = ({seed, y, frame, wither = 0, frost = 0, rows = 7, perRow = 34, green = '#9a9a46', dead = '#5e5446'}) => {
  const stalks = useMemo(() => {
    const out: {x: number; y: number; h: number; k: number; s: number}[] = [];
    for (let r = 0; r < rows; r++) {
      const depth = r / (rows - 1); // 0 — дальний ряд, 1 — ближний
      const s = 0.35 + depth * 1.3;
      const yy = y + Math.pow(depth, 1.6) * (H - y + 80);
      for (let i = 0; i < perRow; i++) {
        out.push({
          x: -60 + (i + random(`${seed}-${r}-${i}`) * 0.8) * ((W + 120) / perRow),
          y: yy + random(`${seed}-y${r}-${i}`) * 20 * s,
          h: (110 + random(`${seed}-h${r}-${i}`) * 60) * s,
          k: random(`${seed}-k${r}-${i}`),
          s,
        });
      }
    }
    return out;
  }, [seed, y, rows, perRow]);

  const lerp = (a: string, b: string, t: number) => {
    const pa = parseInt(a.slice(1), 16);
    const pb = parseInt(b.slice(1), 16);
    const c = [16, 8, 0].map((sh) => Math.round(((pa >> sh) & 255) * (1 - t) + ((pb >> sh) & 255) * t));
    return `rgb(${c.join(',')})`;
  };

  return (
    <g strokeLinecap="round">
      {stalks.map((st, i) => {
        const w = Math.min(1, Math.max(0, wither * 1.4 - st.k * 0.4));
        const sway = Math.sin(frame * 0.04 + st.x * 0.01) * 10 * st.s * (1 - w * 0.7);
        const bend = sway + w * (st.k > 0.5 ? 1 : -1) * st.h * 0.55;
        const tipX = st.x + bend;
        const tipY = st.y - st.h * (1 - w * 0.45);
        const col = lerp(lerp(green, dead, w), '#dfe8ee', frost * 0.55);
        return (
          <g key={i}>
            <path d={`M${st.x},${st.y} Q${st.x + bend * 0.2},${st.y - st.h * 0.6} ${tipX},${tipY}`} stroke={col} strokeWidth={2.4 * st.s} fill="none" />
            <ellipse
              cx={tipX}
              cy={tipY}
              rx={4 * st.s}
              ry={14 * st.s}
              fill={col}
              transform={`rotate(${(bend / st.h) * 70} ${tipX} ${tipY})`}
            />
          </g>
        );
      })}
    </g>
  );
};
