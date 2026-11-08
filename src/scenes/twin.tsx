import React from 'react';
import {random} from 'remotion';
import {C, FPS, SceneProps, balanceAt, contributedAt, finance, lerp, money, pop, wobble, year} from '../lib';
import {Max, Mood} from '../components/Max';
import {Bill, Coin, Icon} from '../components/Icons';
import {Burst, Confetti, Pill, Pop, Stage, Strike, T, fadeIn} from '../components/ui';

// ---------- growth chart ----------
type ChartViewProps = {
  frame: number;
  p: number; // years elapsed (fractional)
  slots: number; // 20 or 30 years on the axis
  focus?: number; // year to call out
  curve?: boolean;
  showInterest?: boolean;
  mood?: Mood;
  zoomT?: number; // 0..1
  fixedMax?: number;
};

const niceMax = (v: number) => {
  const steps = [2000, 5000, 10000, 20000, 30000, 40000, 60000, 80000, 100000, 140000];
  return steps.find((s) => s >= v) ?? v;
};

export const ChartView: React.FC<ChartViewProps> = ({frame, p, slots, focus, curve, showInterest, mood = 'happy', zoomT = 0, fixedMax}) => {
  const X0 = 350, X1 = 1340, Y0 = 820, Y1 = 190;
  const bw = (X1 - X0) / slots;
  const curBal = balanceAt(p * 12);
  // y-axis follows the money smoothly (continuous, not stepped)
  const yMax = fixedMax ?? Math.max(1600, curBal * 1.3);
  const yScale = (v: number) => ((Y0 - Y1) * v) / yMax;
  const stepOpts = [250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000];
  const step = stepOpts.find((st) => yMax / st <= 4.5) ?? 50000;
  const ticks = Array.from({length: Math.floor(yMax / step)}, (_, i) => (i + 1) * step);

  const bars = [];
  const pts: string[] = [];
  const cpts: string[] = [];
  for (let k = 1; k <= slots; k++) {
    const mm = Math.min(p, k) * 12;
    const visible = p > k - 1;
    const bal = visible ? balanceAt(mm) : 0;
    const con = visible ? contributedAt(mm) : 0;
    const x = X0 + (k - 1) * bw + bw * 0.14;
    const w = bw * 0.72;
    const hc = yScale(con);
    const hi = yScale(bal - con);
    const isFocus = focus === k;
    if (visible) {
      pts.push(`${x + w / 2},${Y0 - hc - hi}`);
      cpts.push(`${x + w / 2},${Y0 - hc}`);
    }
    bars.push(
      <g key={k}>
        <rect x={x} y={Y0 - hc} width={w} height={hc} fill={C.blue} stroke={C.ink} strokeWidth={visible ? 3 : 0} />
        <rect x={x} y={Y0 - hc - hi} width={w} height={hi} fill={showInterest && isFocus ? '#3dff9a' : C.green} stroke={C.ink} strokeWidth={visible && hi > 2 ? 3 : 0} />
        {(k % (slots > 20 ? 5 : 1) === 0 || k === 1) && (slots <= 20 || k % 5 === 0) ? (
          <text x={x + w / 2} y={Y0 + 40} textAnchor="middle" fontFamily="Rubik" fontWeight={isFocus ? 900 : 700} fontSize={isFocus ? 34 : 26} fill={isFocus ? C.red : C.ink}>{k}</text>
        ) : null}
      </g>,
    );
  }

  // camera: zoom towards focus bar top
  let cam = '';
  if (focus && zoomT > 0) {
    const fx = X0 + (focus - 0.5) * bw;
    const fy = Y0 - yScale(balanceAt(focus * 12)) / 2;
    const z = 1 + 0.12 * zoomT;
    cam = `translate(${fx} ${fy}) scale(${z}) translate(${-fx} ${-fy})`;
  }
  const f = focus ? year(focus) : null;
  const cross = p * 12 >= finance.crossoverMonth;

  return (
    <g>
      <g transform={cam}>
        {/* grid */}
        {ticks.map((v, i) => (
          <g key={i}>
            <line x1={X0} x2={X1} y1={Y0 - yScale(v)} y2={Y0 - yScale(v)} stroke="#c9d6e3" strokeWidth={2} strokeDasharray="10 10" />
            <text x={X0 - 16} y={Y0 - yScale(v) + 10} textAnchor="end" fontFamily="Rubik" fontWeight={700} fontSize={26} fill="#5b6b7b">{money(v)}</text>
          </g>
        ))}
        {bars}
        <line x1={X0} x2={X1} y1={Y0} y2={Y0} stroke={C.ink} strokeWidth={6} />
        <text x={(X0 + X1) / 2} y={Y0 + 84} textAnchor="middle" fontFamily="Rubik" fontWeight={700} fontSize={28} fill="#5b6b7b">год</text>
        {curve && pts.length > 1 ? (
          <>
            <polyline points={cpts.join(' ')} fill="none" stroke={C.blueDark} strokeWidth={6} strokeDasharray="14 10" />
            <polyline points={pts.join(' ')} fill="none" stroke={C.red} strokeWidth={9} strokeLinejoin="round" strokeLinecap="round" />
          </>
        ) : null}
        {f && zoomT > 0 ? (
          <g>
          <line x1={X0 + (focus! - 0.5) * bw} y1={Y0 - yScale(f.balance) - 6} x2={800} y2={showInterest ? 430 : 380} stroke={C.ink} strokeWidth={4} strokeDasharray="8 8" opacity={zoomT} />
          <g transform={`translate(800,${showInterest ? 320 : 300}) scale(${pop(zoomT * 40, 0)})`}>
            <rect x={-230} y={-80} width={460} height={showInterest ? 190 : 140} rx={22} fill="#fff" stroke={C.ink} strokeWidth={5} />
            <text x={0} y={-30} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={34} fill={C.blueDark}>вложено {money(f.contributed)}</text>
            <text x={0} y={22} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={40} fill={C.greenDark}>на счёте {money(f.balance)}</text>
            {showInterest ? <text x={0} y={80} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={40} fill={C.green}>доход +{money(f.interest)}</text> : null}
          </g>
          </g>
        ) : null}
      </g>
      {/* side panel: live counters */}
      <g transform="translate(1530,150)">
        <rect x={-150} y={0} width={300} height={330} rx={26} fill="#fff" stroke={C.ink} strokeWidth={6} />
        <text x={0} y={52} textAnchor="middle" fontFamily="Rubik" fontWeight={700} fontSize={28} fill="#5b6b7b">Год {Math.min(slots, Math.max(1, Math.ceil(p - 1e-6)))}</text>
        <text x={0} y={102} textAnchor="middle" fontFamily="Rubik" fontWeight={700} fontSize={26} fill="#5b6b7b">на счёте</text>
        <text x={0} y={152} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={50} fill={C.greenDark}>{money(curBal)}</text>
        <text x={0} y={204} textAnchor="middle" fontFamily="Rubik" fontWeight={700} fontSize={26} fill="#5b6b7b">вложено</text>
        <text x={0} y={244} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={38} fill={C.blueDark}>{money(contributedAt(p * 12))}</text>
        <text x={0} y={296} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={30} fill={C.green}>доход +{money(curBal - contributedAt(p * 12))}</text>
      </g>
      <Max x={1530} y={890} s={0.62} frame={frame} twin mood={mood} armR={mood === 'joy' || mood === 'shock' ? 150 : 20} armL={mood === 'joy' ? 150 : 10} />
      {/* legend */}
      <g transform="translate(350,120)">
        <rect width={30} height={30} fill={C.blue} stroke={C.ink} strokeWidth={3} />
        <text x={42} y={26} fontFamily="Rubik" fontWeight={700} fontSize={28} fill={C.ink}>вложено</text>
        <rect x={200} width={30} height={30} fill={C.green} stroke={C.ink} strokeWidth={3} />
        <text x={242} y={26} fontFamily="Rubik" fontWeight={700} fontSize={28} fill={C.ink}>доход 7% годовых</text>
        {cross ? <text x={600} y={26} fontFamily="Rubik" fontWeight={900} fontSize={30} fill={C.red}>доход &gt; вложений!</text> : null}
      </g>
    </g>
  );
};

export const chart: React.FC<SceneProps> = ({frame, dur, from, to, zoom, curve, showInterest, mood}) => {
  const p = from === to ? to : lerp(frame, [0, Math.max(20, Math.min(dur * 0.8, dur - 10))], [from, to]);
  const zoomT = zoom ? lerp(frame, [0, 30], [0, 1]) : 0;
  return (
    <Stage frame={frame} bg="#f1f8ff" bg2="#ffffff" ground={false} clouds={false}>
      <ChartView frame={frame} p={p} slots={20} focus={zoom ?? (from === to ? undefined : undefined)} zoomT={zoomT}
        curve={curve} showInterest={showInterest} mood={mood} />
      {from !== to ? (
        <T x={820} y={470} size={150} color={C.yellow} opacity={lerp(frame, [0, 8], [0, 1]) * lerp(frame, [dur * 0.6, dur * 0.85], [1, 0])}
          s={pop(frame, 0)}>{Math.round(to) === 18 ? '19-й год' : `${to}-й год`}</T>
      ) : null}
    </Stage>
  );
};

export const chart30: React.FC<SceneProps> = ({frame, dur, phase}) => {
  const p = phase === 0 ? lerp(frame, [0, dur], [20, 22]) : lerp(frame, [0, dur * 0.75], [22, 30]);
  const y30 = year(30);
  return (
    <Stage frame={frame} bg="#f1f8ff" bg2="#ffffff" ground={false} clouds={false}>
      <ChartView frame={frame} p={p} slots={30} curve mood={phase ? 'joy' : 'happy'} />
      {phase === 1 && p >= 30 ? (
        <T x={820} y={300} size={110} color={C.green} s={pop(frame - dur * 0.75, 0)}>≈ {money(y30.balance)}</T>
      ) : null}
      {phase === 0 ? <T x={820} y={300} size={90} color={C.ink} stroke="#fff" s={pop(frame, 4)}>+10 лет?</T> : null}
    </Stage>
  );
};

// ---------- twin scenes ----------
export const twinTransfer: React.FC<SceneProps> = ({frame, dur}) => {
  const press = frame > dur * 0.35;
  const fly = lerp(frame, [dur * 0.38, dur * 0.75], [0, 1]);
  return (
    <Stage frame={frame} bg="#b9fbc0" bg2="#f1fff3">
      <Max x={430} y={900} s={0.85} frame={frame} twin mood={press ? 'joy' : 'happy'} armR={70} />
      <g transform="translate(800,470)">
        <rect x={-150} y={-280} width={300} height={560} rx={40} fill={C.navy} stroke={C.ink} strokeWidth={7} />
        <rect x={-128} y={-250} width={256} height={500} rx={24} fill="#fff" />
        <text x={0} y={-180} textAnchor="middle" fontFamily="Rubik" fontWeight={700} fontSize={30} fill="#777">Перевод</text>
        <text x={0} y={-100} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={80} fill={C.ink}>$100</text>
        <g transform={`translate(0,60) scale(${press ? 0.92 : 1})`}>
          <rect x={-100} y={-44} width={200} height={88} rx={44} fill={press ? C.greenDark : C.green} stroke={C.ink} strokeWidth={5} />
          <text x={0} y={12} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={34} fill="#fff">{press ? 'Готово ✓' : 'Отправить'}</text>
        </g>
      </g>
      <g transform={`translate(${800 + fly * 640},${470 - Math.sin(fly * Math.PI) * 260}) rotate(${fly * 360}) scale(${1 - fly * 0.4})`} opacity={fly > 0 && fly < 1 ? 1 : 0}>
        <Bill w={200} />
      </g>
      <Pop frame={frame} delay={6} x={1440} y={500}><Icon name="safe" s={1.5} /></Pop>
      <T x={1440} y={250} size={50} opacity={fadeIn(frame, 10)}>инвест-счёт</T>
      <Pill x={960} y={140} w={620} s={pop(frame, 4)} fill={C.yellow}>каждый день зарплаты</Pill>
    </Stage>
  );
};

export const notHalf: React.FC<SceneProps> = ({frame, dur}) => {
  const step = dur / 3;
  return (
    <Stage frame={frame} bg="#ffe5d9" bg2="#fff" ground={false} clouds={false}>
      {[
        {t: '50% зарплаты', x: 480, strike: true},
        {t: '40%', x: 960, strike: true},
        {t: '$100', x: 1440, strike: false},
      ].map((it, i) => (
        <g key={i}>
          <Pop frame={frame} delay={i * step * 0.7} x={it.x} y={480}>
            <rect x={-210} y={-120} width={420} height={240} rx={30} fill={it.strike ? '#fff' : C.green} stroke={C.ink} strokeWidth={7} />
            <text x={0} y={18} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={it.strike ? (it.t.length > 5 ? 44 : 90) : 110} fill={it.strike ? C.ink : '#fff'}>{it.t}</text>
          </Pop>
          {it.strike ? <Strike x={it.x} y={480} size={110} p={lerp(frame, [i * step * 0.7 + 10, i * step * 0.7 + 24], [0, 1])} /> : null}
        </g>
      ))}
      <T x={1440} y={720} size={60} color={C.greenDark} stroke="#fff" opacity={fadeIn(frame, 2 * step * 0.7 + 10)}>всего!</T>
    </Stage>
  );
};

export const perDay: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#e0fbfc" bg2="#fff" ground={false} clouds={false}>
    <T x={960} y={330} size={100} color={C.ink} stroke="#fff" opacity={fadeIn(frame, 0)}>$100 × 12 мес ÷ 365 дн</T>
    <T x={960} y={560} size={190} color={C.green} s={pop(frame, 18)}>≈ ${finance.perDay.toFixed(2).replace('.', ',')}</T>
    <T x={960} y={740} size={70} color={C.ink} stroke="#fff" opacity={fadeIn(frame, 26)}>в день</T>
  </Stage>
);

export const perDayCoffee: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#fde4cf" bg2="#fff">
    <Pop frame={frame} x={620} y={470}><g transform="scale(2.2)"><Coin r={60} label="3" /></g></Pop>
    <T x={960} y={470} size={160} color={C.ink} stroke="#fff" opacity={fadeIn(frame, 8)}>≈</T>
    <Pop frame={frame} delay={12} x={1300} y={470}><Icon name="coffee" s={2.2} r={wobble(frame, 5, 0.6)} /></Pop>
  </Stage>
);

export const indexFund: React.FC<SceneProps> = ({frame}) => {
  const cols = ['#ff595e', '#ffca3a', '#8ac926', '#1982c4', '#6a4c93', '#ff924c', '#52a675', '#4267ac'];
  return (
    <Stage frame={frame} bg="#caf0f8" bg2="#fff">
      {/* basket */}
      <path d="M560,520 L1360,520 L1260,830 L660,830 Z" fill="#d4a373" stroke={C.ink} strokeWidth={8} />
      {Array.from({length: 40}).map((_, i) => {
        const delay = i * 1.5;
        const t = Math.min(1, Math.max(0, (frame - delay) / 20));
        const tx = 640 + (i % 10) * 70;
        const ty = 470 - Math.floor(i / 10) * 64;
        const sx = tx + (random(`if${i}`) - 0.5) * 900;
        const x = sx + (tx - sx) * t;
        const y = -100 + (ty + 100) * t;
        return (
          <g key={i} transform={`translate(${x},${y})`}>
            <rect x={-30} y={-28} width={60} height={56} rx={10} fill={cols[i % cols.length]} stroke={C.ink} strokeWidth={4} />
            <text x={0} y={12} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={30} fill="#fff">{String.fromCharCode(65 + (i * 7) % 26)}</text>
          </g>
        );
      })}
      <T x={960} y={90} size={80} color={C.ink} stroke="#fff" s={pop(frame, 4)}>Индексный фонд</T>
      <T x={960} y={180} size={46} color={C.ink} stroke="#fff" opacity={fadeIn(frame, 30)}>сотни компаний в одной «корзине»</T>
    </Stage>
  );
};

export const assumption: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#fff3b0" bg2="#fff" ground={false} clouds={false}>
    <Burst x={960} y={430} r={700} frame={frame} color="#ffe066" />
    <T x={960} y={400} size={260} color={C.green} s={pop(frame, 0)}>7%</T>
    <T x={960} y={600} size={80} color={C.ink} stroke="#fff" opacity={fadeIn(frame, 10)}>годовых в среднем</T>
    <Pill x={960} y={760} w={980} h={80} size={38} s={pop(frame, 22)} fill="#fff">допущение · проценты каждый месяц</Pill>
  </Stage>
);

export const assumptionStamp: React.FC<SceneProps> = ({frame}) => {
  const s = lerp(frame, [8, 18], [2.5, 1]);
  return (
    <Stage frame={frame} bg="#f8edeb" bg2="#fff" ground={false} clouds={false}>
      <rect x={560} y={180} width={800} height={560} rx={20} fill="#fff" stroke={C.ink} strokeWidth={6} />
      {[0, 1, 2, 3, 4].map((i) => <rect key={i} x={640} y={260 + i * 70} width={640 - (i % 2) * 160} height={22} rx={11} fill="#dfe6e9" />)}
      <T x={960} y={640} size={60} color={C.ink} stroke="#fff">обещание</T>
      <Strike x={960} y={640} size={60} p={lerp(frame, [20, 34], [0, 1])} />
      <g transform={`translate(960,430) rotate(-12) scale(${s})`} opacity={frame > 8 ? 1 : 0}>
        <rect x={-330} y={-80} width={660} height={160} rx={20} fill="none" stroke={C.red} strokeWidth={14} />
        <text x={0} y={30} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={96} fill={C.red}>ДОПУЩЕНИЕ</text>
      </g>
    </Stage>
  );
};

export const reinvest: React.FC<SceneProps> = ({frame}) => {
  const a = (frame / FPS) * 140;
  return (
    <Stage frame={frame} bg="#d8f3dc" bg2="#fff" ground={false} clouds={false}>
      <g transform="translate(960,500)">
        <circle r={280} fill="none" stroke={C.green} strokeWidth={26} strokeDasharray="120 40" transform={`rotate(${a / 3})`} />
        <Icon name="safe" s={1.1} />
        {[0, 120, 240].map((o) => (
          <g key={o} transform={`rotate(${a + o}) translate(280,0) rotate(${-(a + o)})`}><Coin r={46} label="%" /></g>
        ))}
      </g>
      <T x={960} y={120} size={70} color={C.ink} stroke="#fff">доход → снова в работу</T>
    </Stage>
  );
};

export const magicTitle: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#3a0ca3" bg2="#7209b7" ground={false} clouds={false} night>
    {Array.from({length: 24}).map((_, i) => {
      const ang = (i / 24) * Math.PI * 2 + frame / 40;
      const r = 380 + Math.sin(frame / 10 + i) * 40;
      return <T key={i} x={960 + Math.cos(ang) * r * 1.4} y={470 + Math.sin(ang) * r * 0.8} size={44} color={C.yellow} stroke="transparent" sw={0}>✦</T>;
    })}
    <T x={960} y={400} size={110} color="#fff" s={pop(frame, 0)}>Магия</T>
    <T x={960} y={540} size={110} color={C.yellow} s={pop(frame, 8)}>сложного процента</T>
  </Stage>
);

export const snowball: React.FC<SceneProps> = ({frame, dur}) => {
  const t = lerp(frame, [0, dur], [0, 1], (x) => x);
  const x = 300 + t * 1300;
  const y = 330 + t * 470;
  const r = 40 + t * 150;
  return (
    <Stage frame={frame} bg="#caf0f8" bg2="#fff" ground={false}>
      <path d="M0,300 L1920,860 L1920,1080 L0,1080 Z" fill="#fff" stroke="#a8dadc" strokeWidth={8} />
      <g transform={`translate(${x},${y - r}) rotate(${frame * 6})`}>
        <circle r={r} fill="#f1faee" stroke={C.ink} strokeWidth={6} />
        <text x={0} y={r * 0.3} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={r * 0.9} fill={C.green}>$</text>
      </g>
      <T x={960} y={170} size={74} color={C.ink} stroke="#fff">деньги зарабатывают деньги</T>
    </Stage>
  );
};

export const coinsBreed: React.FC<SceneProps> = ({frame, dur}) => {
  const levels = 4;
  const step = Math.max(12, (dur - 20) / levels);
  const nodes: React.ReactNode[] = [];
  const draw = (x: number, y: number, lvl: number, key: string) => {
    const appear = lvl * step;
    if (frame < appear) return;
    const s = pop(frame, appear) * (1 - lvl * 0.16);
    nodes.push(<g key={key} transform={`translate(${x},${y}) scale(${s})`}><Coin r={54} label={lvl ? '%' : '$'} /></g>);
    if (lvl < levels - 1) {
      const spread = 420 / (lvl + 1) ** 1.1;
      for (const d of [-1, 1]) {
        if (frame >= appear + step) nodes.push(<line key={key + d + 'l'} x1={x} y1={y + 40} x2={x + d * spread} y2={y + 170} stroke={C.ink} strokeWidth={4} opacity={0.3} />);
        draw(x + d * spread, y + 180, lvl + 1, key + d);
      }
    }
  };
  draw(960, 200, 0, 'n');
  return (
    <Stage frame={frame} bg="#fff8e1" bg2="#fff" ground={false} clouds={false}>
      {nodes}
    </Stage>
  );
};

export const plusTiny: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#f1f8ff" bg2="#fff" ground={false} clouds={false}>
    <T x={960} y={480} size={60} color={C.green} stroke="#fff">+{money(year(1).interest)}</T>
    <g transform={`translate(${960 + wobble(frame, 30, 0.4)},480) scale(${pop(frame, 4)})`}>
      <circle r={210} fill="rgba(255,255,255,0.4)" stroke={C.ink} strokeWidth={18} />
      <line x1={150} y1={150} x2={320} y2={320} stroke={C.ink} strokeWidth={40} strokeLinecap="round" />
      <T x={0} y={0} size={150} color={C.green}>+{money(year(1).interest)}</T>
    </g>
  </Stage>
);

export const twinYawn: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#e0e1dd" bg2="#fff">
    <Max x={960} y={900} s={1} frame={frame} twin mood="sleepy" armR={150} />
    {[0, 1, 2].map((i) => (
      <T key={i} x={1180 + i * 70} y={360 - i * 80 - ((frame / 2) % 40)} size={60 + i * 20} color={C.purple} opacity={fadeIn(frame, i * 8)}>Z</T>
    ))}
  </Stage>
);

export const quitters: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#dee2e6" bg2="#f8f9fa" ground="#adb5bd">
    {[0, 1, 2, 3].map((i) => (
      <Max key={i} x={300 + i * 260 - (frame / FPS) * 90} y={900} s={0.55} frame={frame + i * 13} shirt="#adb5bd" mood="sad" flip bob />
    ))}
    <Max x={1450} y={900} s={0.85} frame={frame} twin mood="smug" armR={20} />
    <Pill x={640} y={200} w={560} fill="#fff" s={pop(frame, 6)}>«не работает…»</Pill>
    <Pill x={1450} y={250} w={420} fill={C.green} color="#fff" s={pop(frame, 18)}>продолжаю</Pill>
  </Stage>
);

export const yearCompare: React.FC<SceneProps> = ({frame, year: y = 15}) => {
  const r = year(y);
  const g = lerp(frame, [10, 50], [0, 1]);
  const max = 2400;
  const h = (v: number) => (480 * v * g) / max;
  return (
    <Stage frame={frame} bg="#f1f8ff" bg2="#fff" ground={false} clouds={false}>
      <T x={960} y={110} size={64} color={C.ink} stroke="#fff">за {y}-й год</T>
      {[
        {x: 700, v: 12 * finance.monthly, c: C.blue, l: 'вложил сам'},
        {x: 1220, v: r.interestThisYear, c: C.green, l: 'принесли проценты'},
      ].map((b) => (
        <g key={b.x}>
          <rect x={b.x - 130} y={820 - h(b.v)} width={260} height={h(b.v)} rx={16} fill={b.c} stroke={C.ink} strokeWidth={6} />
          <T x={b.x} y={790 - h(b.v) - 40} size={70} color={b.c === C.green ? C.greenDark : C.blueDark} stroke="#fff">{money(b.v * g)}</T>
          <T x={b.x} y={880} size={46} color={C.ink} stroke="#fff">{b.l}</T>
        </g>
      ))}
    </Stage>
  );
};

export const crossover: React.FC<SceneProps> = ({frame}) => {
  const m = finance.crossoverMonth;
  const con = contributedAt(m);
  const inter = balanceAt(m) - con;
  const g = lerp(frame, [6, 40], [0, 1]);
  const h = (v: number) => (520 * v * g) / 23000;
  return (
    <Stage frame={frame} bg="#fff0f3" bg2="#fff" ground={false} clouds={false}>
      {frame > 40 ? <Burst x={1220} y={420} r={500} frame={frame} color="#b7efc5" /> : null}
      {[
        {x: 700, v: con, c: C.blue, l: 'все вложения'},
        {x: 1220, v: inter, c: C.green, l: 'весь доход'},
      ].map((b) => (
        <g key={b.x}>
          <rect x={b.x - 140} y={820 - h(b.v)} width={280} height={h(b.v)} rx={16} fill={b.c} stroke={C.ink} strokeWidth={6} />
          <T x={b.x} y={780 - h(b.v) - 30} size={64} color={b.c === C.green ? C.greenDark : C.blueDark} stroke="#fff">{money(b.v * g)}</T>
          <T x={b.x} y={880} size={46} color={C.ink} stroke="#fff">{b.l}</T>
        </g>
      ))}
      <T x={960} y={110} size={60} color={C.ink} stroke="#fff">{m}-й месяц (начало {Math.floor(m / 12) + 1}-го года)</T>
      {frame > 40 ? <T x={960} y={560} size={120} color={C.red} s={pop(frame, 40)} r={-6}>&gt;</T> : null}
    </Stage>
  );
};

export const scales: React.FC<SceneProps> = ({frame}) => {
  const tilt = lerp(frame, [10, 50], [-10, 8]);
  return (
    <Stage frame={frame} bg="#e9f5db" bg2="#fff" ground={false} clouds={false}>
      <rect x={940} y={360} width={40} height={460} fill="#8d5a3b" stroke={C.ink} strokeWidth={6} />
      <rect x={800} y={800} width={320} height={40} rx={12} fill="#8d5a3b" stroke={C.ink} strokeWidth={6} />
      <g transform={`translate(960,360) rotate(${tilt})`}>
        <rect x={-420} y={-12} width={840} height={24} rx={12} fill={C.ink} />
        {[-1, 1].map((d) => (
          <g key={d} transform={`translate(${d * 400},0) rotate(${-tilt})`}>
            <line x1={-120} y1={180} x2={0} y2={0} stroke={C.ink} strokeWidth={5} />
            <line x1={120} y1={180} x2={0} y2={0} stroke={C.ink} strokeWidth={5} />
            <path d="M-150,180 L150,180 Q120,250 0,250 Q-120,250 -150,180 Z" fill="#ffd166" stroke={C.ink} strokeWidth={6} />
            {d < 0
              ? <><g transform="translate(0,140)"><Bill w={170} label="сам" /></g><T x={0} y={320} size={44} color={C.blueDark} stroke="#fff">отложил</T></>
              : <><g transform="translate(0,140)"><Coin r={60} label="%" /></g><T x={0} y={320} size={44} color={C.greenDark} stroke="#fff">заработали деньги</T></>}
          </g>
        ))}
      </g>
    </Stage>
  );
};

export const finalCounter: React.FC<SceneProps> = ({frame, dur}) => {
  const v = lerp(frame, [0, dur * 0.7], [year(19).balance, year(20).balance]);
  const done = frame > dur * 0.7;
  return (
    <Stage frame={frame} bg="#ffcb69" bg2="#fff3c4" ground={false} clouds={false}>
      <Burst x={960} y={500} r={900} frame={frame} color="#fff" n={20} />
      <g transform={`translate(960,500) scale(${done ? 1 + 0.03 * Math.sin(frame / 5) : 1})`}>
        <rect x={-640} y={-170} width={1280} height={340} rx={40} fill="#fff" stroke="#d4a017" strokeWidth={22} />
        <text x={0} y={60} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={210} fill={C.greenDark}>{money(v)}</text>
      </g>
      <T x={960} y={170} size={70} color={C.ink} stroke="#fff">на счёте через 20 лет</T>
      {done ? <Confetti frame={frame - dur * 0.7} seed="fc" /> : null}
    </Stage>
  );
};

export const splitStack: React.FC<SceneProps> = ({frame}) => {
  const r = year(20);
  const g1 = lerp(frame, [0, 26], [0, 1]);
  const g2 = lerp(frame, [26, 60], [0, 1]);
  const k = 620 / r.balance;
  const hc = r.contributed * k * g1;
  const hi = r.interest * k * g2;
  return (
    <Stage frame={frame} bg="#f1f8ff" bg2="#fff" ground={false} clouds={false}>
      <rect x={760} y={840 - hc} width={400} height={hc} fill={C.blue} stroke={C.ink} strokeWidth={6} />
      <rect x={760} y={840 - hc - hi} width={400} height={hi} fill={C.green} stroke={C.ink} strokeWidth={6} />
      <T x={730} y={840 - hc / 2} size={52} anchor="end" color={C.blueDark} stroke="#fff" opacity={g1}>вложил {money(r.contributed)}</T>
      <T x={1190} y={840 - hc - hi / 2} size={56} anchor="start" color={C.greenDark} stroke="#fff" opacity={g2}>+{money(r.interest)}</T>
      <T x={1190} y={840 - hc - hi / 2 + 70} size={44} anchor="start" color={C.ink} stroke="#fff" opacity={g2}>сложный %</T>
    </Stage>
  );
};

export const twinRelax: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#90e0ef" bg2="#caf0f8" ground="#ffe08a">
    <g transform="translate(470,870)"><Icon name="palm" s={2.2} /></g>
    <g transform="translate(1450,870) scale(-1,1)"><Icon name="palm" s={2.2} /></g>
    <path d={`M520,560 Q960,${760 + Math.sin(frame / 20) * 15} 1400,560`} fill="none" stroke="#e76f51" strokeWidth={14} />
    <g transform={`translate(960,${700 + Math.sin(frame / 20) * 12}) rotate(-88)`}>
      <Max x={0} y={180} s={0.7} frame={frame} twin mood="sleepy" armR={160} bob={false} />
    </g>
    <T x={960} y={160} size={80} color={C.ink} stroke="#fff" s={pop(frame, 6)}>не работал больше</T>
  </Stage>
);

export const moneyWorkers: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#ffe8d6" bg2="#fff" ground="#ddbea9">
    {Array.from({length: 6}).map((_, i) => {
      const x = ((frame * 3 + i * 330) % 2200) - 140;
      const step = Math.sin(frame / 5 + i) * 18;
      return (
        <g key={i} transform={`translate(${x},${780 + Math.abs(step) * -0.5})`}>
          <line x1={-14} y1={40} x2={-14 + step} y2={90} stroke={C.ink} strokeWidth={8} strokeLinecap="round" />
          <line x1={14} y1={40} x2={14 - step} y2={90} stroke={C.ink} strokeWidth={8} strokeLinecap="round" />
          <Coin r={56} />
          <path d="M-50,-46 Q0,-100 50,-46 Z" fill={C.orange} stroke={C.ink} strokeWidth={5} />
          <rect x={30} y={-20} width={60} height={40} rx={4} fill="#e76f51" stroke={C.ink} strokeWidth={4} />
        </g>
      );
    })}
    <T x={960} y={250} size={100} color={C.ink} stroke="#fff" s={pop(frame, 4)}>работают деньги</T>
  </Stage>
);
