import React from 'react';
import { Max } from '../characters/Max';
import { Coin } from '../characters/Coin';
import { BgType } from '../backgrounds';
import { Bill, Calendar, Chart, Clock, FallingCoin, Hand, Label, LeakyPipe, Phone, Piggy, QuestionMark, SaleTag, ShoppingBag, Sparkles, Wallet } from '../props';
import { C, INK, STROKE, hash, hop, pop, range } from '../theme';
import type { Timeline, Word } from '../types';

export type ShotCtx = {
  t: number; // seconds since shot start
  st: number; // seconds since scene start
  shotDur: number;
  sceneDur: number;
  frame: number; // global frame
  fps: number;
  k: number; // shot index within scene
  labels: Record<string, any>;
  maxMouth: number;
  coinMouth: number;
  speaker: 'max' | 'coin' | null;
  words: Word[]; // scene words, times relative to scene start
};

// Scene-local time of the first word that matches `re` (fallback: `def`).
export const at = (ctx: ShotCtx, re: RegExp, def: number) => ctx.words.find((w) => re.test(w.text.toLowerCase()))?.start ?? def;
const shotFrame = (ctx: ShotCtx) => Math.round(ctx.t * ctx.fps);
const popIn = (ctx: ShotCtx, delaySec = 0) => pop(shotFrame(ctx), ctx.fps, Math.round(delaySec * ctx.fps));
const popAtScene = (ctx: ShotCtx, sceneSec: number) => pop(Math.round((ctx.st - sceneSec) * ctx.fps), ctx.fps, 0);

// Characters with squash & stretch: hop while talking, gentle idle bounce otherwise.
const MaxC: React.FC<{ ctx: ShotCtx; x: number; y: number; scale?: number; pose?: any; mood?: any; flip?: boolean; look?: [number, number]; holding?: React.ReactNode; hopH?: number }> = ({ ctx, x, y, scale = 0.9, pose, mood, flip, look, holding, hopH }) => {
  const talking = ctx.speaker === 'max';
  const h = hop(ctx.st + 0.2, talking ? 0.62 : 1.1, hopH ?? (talking ? 34 : 10));
  const enter = popIn(ctx, 0.02);
  return <Max x={x} y={y} scale={scale * (0.6 + 0.4 * enter)} t={ctx.st} mouth={ctx.maxMouth} pose={pose} mood={mood} flip={flip} look={look} lift={h.lift} sx={h.sx} sy={h.sy} holding={holding} />;
};
const CoinC: React.FC<{ ctx: ShotCtx; x: number; y: number; scale?: number; arms?: any; mood?: any; spinAt?: number }> = ({ ctx, x, y, scale = 0.85, arms, mood, spinAt }) => {
  const talking = ctx.speaker === 'coin';
  const float = Math.sin(ctx.st * 3.1) * 16;
  const h = hop(ctx.st, talking ? 0.5 : 0.9, talking ? 26 : 8);
  const enter = popIn(ctx, 0.06);
  const spin = spinAt !== undefined ? range(ctx.t, spinAt, spinAt + 0.45) : 0;
  return <Coin x={x} y={y + float - h.lift} scale={scale * enter} t={ctx.st} mouth={ctx.coinMouth} sx={h.sx} sy={h.sy} arms={arms ?? (talking ? 'up' : 'down')} mood={mood} spin={spin} />;
};

type ShotDef = { bg: BgType; render: (ctx: ShotCtx) => React.ReactNode };

// ---------------- HOOK ----------------
const hook: ShotDef[] = [
  {
    bg: 'rays',
    render: (ctx) => {
      const L = ctx.labels;
      return (
        <g>
          <g transform={`translate(0 ${-20 + Math.sin(ctx.t * 2) * 8})`}>
            <Label text={L.salary} x={540} y={640} size={96} fill={C.green} scale={popIn(ctx, 0.1)} />
          </g>
          <Wallet x={760} y={1060} scale={0.9 * popIn(ctx, 0.15)} open={range(ctx.t, 0.3, 0.7)} />
          {Array.from({ length: 7 }).map((_, i) => {
            const p = (ctx.t * 0.55 + i / 7) % 1;
            if (ctx.t < 0.4 + i * 0.12) return null;
            const x = 760 + Math.sin(p * 6 + i) * 120 + (i % 2 ? 1 : -1) * p * 260;
            const y = 980 - p * 520;
            return <Bill key={i} x={x} y={y} rot={Math.sin(ctx.t * 5 + i) * 20} scale={0.75} wings={Math.sin(ctx.t * 18 + i)} opacity={1 - p * p} />;
          })}
          <MaxC ctx={ctx} x={380} y={1560} pose="shrug" mood="surprised" look={[0.6, -0.4]} />
        </g>
      );
    },
  },
  {
    bg: 'dots',
    render: (ctx) => {
      const L = ctx.labels;
      return (
        <g>
          <LeakyPipe y={580} t={ctx.t} holes={[260, 540, 820]} reveal={range(ctx.t, 0.2, 1.4) * 1.01} />
          <Label text={L.big} x={540} y={470} size={120} fill={C.yellow} scale={popIn(ctx, 0.3)} rotate={-4} />
          <CoinC ctx={ctx} x={300} y={1150} arms="point" spinAt={0} />
          <MaxC ctx={ctx} x={740} y={1580} scale={0.82} mood="surprised" pose="idle" look={[-0.7, -0.6]} />
        </g>
      );
    },
  },
];

// ---------------- SUBSCRIPTIONS ----------------
const subscriptions: ShotDef[] = [
  {
    bg: 'stripes',
    render: (ctx) => (
      <g>
        <Phone x={690} y={930} scale={0.9 * popIn(ctx, 0.05)} t={ctx.t} reveal={range(ctx.t, 0.2, 2.2)} priceLabel={ctx.labels.price} />
        <CoinC ctx={ctx} x={250} y={1180} arms="point" />
      </g>
    ),
  },
  {
    bg: 'rays',
    render: (ctx) => {
      const L = ctx.labels;
      const tYear = at(ctx, /шестьсот/, ctx.st + 1.6) - (ctx.st - ctx.t);
      const showYear = popIn(ctx, Math.max(0.3, tYear - 0.1));
      return (
        <g>
          <Label text={L.math} x={540} y={640} size={130} fill="#fff" scale={popIn(ctx, 0.1)} />
          <g transform={`translate(540 860) scale(${showYear}) rotate(${Math.sin(ctx.t * 6) * 3})`}>
            <Label text={L.yearly} x={0} y={0} size={220} fill={C.yellow} sw={20} />
            <Label text={L.perYear} x={0} y={110} size={80} fill="#fff" />
          </g>
          {Array.from({ length: 9 }).map((_, i) => {
            const p = Math.max(0, (ctx.t - 0.4 - i * 0.18) / 0.5);
            if (p <= 0) return null;
            const y = Math.min(1, p) * (1380 - i * 34) + (1 - Math.min(1, p)) * 200;
            return <FallingCoin key={i} x={860 + (i % 2) * 8} y={y} r={46} />;
          })}
          <MaxC ctx={ctx} x={380} y={1580} scale={0.86} pose="shrug" mood="surprised" look={[0.5, -0.5]} />
        </g>
      );
    },
  },
  {
    bg: 'room',
    render: (ctx) => {
      const L = ctx.labels;
      return (
        <g>
          <Phone x={720} y={900} scale={0.82} t={ctx.t} reveal={1} crossed={range(ctx.t, 0.3, 1.8)} priceLabel={ctx.labels.price} />
          <Label text={L.unused} x={540} y={560} size={104} fill={C.red} scale={popIn(ctx, 0.2)} rotate={-3} />
          <MaxC ctx={ctx} x={300} y={1590} scale={0.86} pose="point" mood="think" look={[0.8, -0.3]} />
        </g>
      );
    },
  },
  {
    bg: 'city',
    render: (ctx) => {
      const L = ctx.labels;
      const tap = Math.max(0, Math.sin(Math.max(0, ctx.t - 0.8) * 6)) * (ctx.t > 0.8 ? 1 : 0);
      return (
        <g>
          <Phone x={640} y={940} scale={0.9} t={ctx.t} screen="cancel" tap={tap} cancelLabel={L.cancel} priceLabel={L.price} />
          <Hand x={700 + 40 * (1 - range(ctx.t, 0, 0.7))} y={1170 + 200 * (1 - range(ctx.t, 0, 0.7)) + tap * 20} scale={1.1} rot={-15} />
          <Label text={L.now} x={540} y={540} size={100} fill={C.yellow} scale={popIn(ctx, 0.5)} rotate={3} />
          <CoinC ctx={ctx} x={230} y={1200} scale={0.75} arms="up" mood="excited" />
          {tap > 0.5 ? <Sparkles t={ctx.t} cx={640} cy={1150} spread={200} color={C.yellow} /> : null}
        </g>
      );
    },
  },
];

// ---------------- IMPULSE ----------------
const impulse: ShotDef[] = [
  {
    bg: 'shop',
    render: (ctx) => {
      const L = ctx.labels;
      return (
        <g>
          <SaleTag x={760} y={760} text={L.sale} swing={Math.sin(ctx.t * 3) * 10} scale={popIn(ctx, 0.15)} />
          <CoinC ctx={ctx} x={260} y={1150} arms="point" spinAt={0.1} />
          <ShoppingBag x={640} y={1460} color={C.purple} scale={0.8 * popIn(ctx, 0.4)} rot={-6} label={L.bag} />
          <ShoppingBag x={860} y={1480} color={C.orange} scale={0.75 * popIn(ctx, 0.55)} rot={8} />
        </g>
      );
    },
  },
  {
    bg: 'dots',
    render: (ctx) => {
      const L = ctx.labels;
      const tQ = at(ctx, /нужно/, ctx.st + 1.5) - (ctx.st - ctx.t);
      const q = popIn(ctx, Math.max(0.2, tQ - 0.15));
      return (
        <g>
          <QuestionMark x={800} y={900} scale={q} rot={Math.sin(ctx.t * 4) * 8} />
          <Label text={L.question} x={540} y={560} size={120} fill={C.yellow} scale={q} />
          <ShoppingBag x={250} y={1060} color={C.pink} scale={0.7} rot={Math.sin(ctx.t * 5) * 8} label={L.sale} />
          <MaxC ctx={ctx} x={520} y={1600} scale={0.9} pose={q > 0.5 ? 'think' : 'cheer'} mood={q > 0.5 ? 'think' : 'happy'} look={[0.6, -0.6]} hopH={q > 0.5 ? 6 : 40} />
        </g>
      );
    },
  },
  {
    bg: 'rays',
    render: (ctx) => {
      const L = ctx.labels;
      return (
        <g>
          <Label text={L.rule} x={540} y={560} size={96} fill="#fff" scale={popIn(ctx, 0.1)} />
          <Clock x={640} y={930} r={210} t={ctx.t} speed={3} label={L.hours} />
          <CoinC ctx={ctx} x={240} y={1220} scale={0.8} arms="up" />
        </g>
      );
    },
  },
  {
    bg: 'stripes',
    render: (ctx) => {
      const L = ctx.labels;
      const okAt = at(ctx, /хочешь/, ctx.st + 1) - (ctx.st - ctx.t);
      const ok = popIn(ctx, Math.max(0.3, okAt - 0.2));
      return (
        <g>
          <Calendar x={760} y={900} scale={0.95 * popIn(ctx, 0.05)} page={range(ctx.t, 0.2, 0.8)} label={L.hours} />
          <Label text={ok > 0.3 ? L.ok : L.wait} x={540} y={560} size={86} fill={ok > 0.3 ? C.green : '#fff'} scale={ok > 0.3 ? ok : popIn(ctx, 0.1)} />
          <MaxC ctx={ctx} x={330} y={1590} scale={0.88} pose={ok > 0.3 ? 'cheer' : 'idle'} mood="happy" holding={ok > 0.3 ? <ShoppingBag x={0} y={60} color={C.teal} scale={0.45} /> : undefined} />
        </g>
      );
    },
  },
];

// ---------------- PAY YOURSELF ----------------
const Bars: React.FC<{ ctx: ShotCtx; flip: number; appear: number[] }> = ({ ctx, flip, appear }) => {
  const L = ctx.labels;
  const items = [
    { text: L.bills, col: C.red, w: 760 },
    { text: L.spend, col: C.orange, w: 680 },
    { text: L.save, col: C.green, w: 520 },
  ];
  // flip: 0 → bills on top; 1 → savings on top
  return (
    <g>
      {items.map((it, i) => {
        const pos0 = i;
        const pos1 = 2 - i;
        const pos = pos0 + (pos1 - pos0) * flip;
        const y = 560 + pos * 170;
        const s = appear[i];
        const isSave = i === 2;
        const shrink = isSave ? 0.75 + 0.25 * flip : 1;
        const w = it.w * shrink + (isSave ? 260 * flip : 0);
        const arc = Math.sin(flip * Math.PI) * (i === 1 ? 0 : i === 0 ? 180 : -180);
        return (
          <g key={i} transform={`translate(${540 + arc} ${y}) scale(${s})`} opacity={isSave ? 0.55 + 0.45 * flip : 1}>
            <rect x={-w / 2} y={-62} width={w} height={124} rx={30} fill={it.col} stroke={INK} strokeWidth={STROKE} />
            <Label text={`${i === 2 ? (flip > 0.5 ? 1 : 3) : flip > 0.5 ? 3 - i : i + 1}. ${it.text}`} x={0} y={24} size={66} maxWidth={w - 50} sw={12} />
          </g>
        );
      })}
    </g>
  );
};
const payyourself: ShotDef[] = [
  {
    bg: 'room',
    render: (ctx) => (
      <g>
        <Piggy x={760} y={1130} scale={0.85 * popIn(ctx, 0.1)} t={ctx.t} sad />
        <Wallet x={760} y={760} scale={0.6} open={range(ctx.t, 0.3, 0.8)} />
        <CoinC ctx={ctx} x={260} y={1130} arms="point" spinAt={0} />
      </g>
    ),
  },
  {
    bg: 'grid',
    render: (ctx) => {
      const base = ctx.st - ctx.t;
      const a = [at(ctx, /счета/, base + 0.3), at(ctx, /траты/, base + 1.2), at(ctx, /накоплен/, base + 2.2)].map((s) => popIn(ctx, Math.max(0.05, s - base - 0.1)));
      return (
        <g>
          <Bars ctx={ctx} flip={0} appear={a} />
          <MaxC ctx={ctx} x={540} y={1610} scale={0.84} pose="shrug" mood={a[2] > 0.5 ? 'sad' : 'happy'} look={[0, -0.8]} />
        </g>
      );
    },
  },
  {
    bg: 'rays',
    render: (ctx) => {
      const L = ctx.labels;
      const f = range(ctx.t, 0.5, 1.4);
      // second beat inside this shot: "…отложи десять процентов" → piggy bank scene
      const tSave = at(ctx, /^отложи|^десять/, 1e9) - 0.1;
      if (ctx.st >= tSave && ctx.st - tSave < ctx.t) {
        const dt = ctx.st - tSave;
        return payyourself[3].render({ ...ctx, t: dt, shotDur: Math.max(1, ctx.shotDur - (ctx.t - dt)) });
      }
      return (
        <g>
          <Bars ctx={ctx} flip={f} appear={[1, 1, 1]} />
          <Label text={L.flip} x={540} y={1110} size={110} fill={C.yellow} scale={popIn(ctx, 0.05)} rotate={Math.sin(ctx.t * 5) * 4} />
          <CoinC ctx={ctx} x={830} y={1290} scale={0.7} arms="up" mood="excited" />
        </g>
      );
    },
  },
  {
    bg: 'city',
    render: (ctx) => {
      const L = ctx.labels;
      const fill = range(ctx.t, 0.3, ctx.shotDur - 0.3);
      return (
        <g>
          <Label text={L.payday} x={540} y={560} size={84} fill="#fff" scale={popIn(ctx, 0.05)} />
          <Label text={L.percent} x={540} y={760} size={200} fill={C.yellow} sw={20} scale={popIn(ctx, 0.3)} rotate={-4} />
          <Piggy x={700} y={1180} scale={0.7} t={ctx.t} fill={fill} />
          {Array.from({ length: 6 }).map((_, i) => {
            const p = ((ctx.t - 0.4) * 1.3 + i / 6) % 1;
            if (ctx.t < 0.4 + i * 0.12) return null;
            return <FallingCoin key={i} x={700 + Math.sin(i) * 20} y={860 + p * 160} r={30} rot={p * 360} />;
          })}
          <CoinC ctx={ctx} x={250} y={1200} scale={0.75} arms="up" mood="excited" />
        </g>
      );
    },
  },
];

// ---------------- OUTRO ----------------
const Checklist: React.FC<{ ctx: ShotCtx; checks: number[] }> = ({ ctx, checks }) => {
  const steps: string[] = ctx.labels.steps ?? [];
  return (
    <g>
      {steps.map((s, i) => {
        const appear = popAtScene(ctx, Math.max(0, checks[i] - 0.25));
        const chk = popAtScene(ctx, checks[i] + 0.25);
        return (
          <g key={i} transform={`translate(540 ${590 + i * 170}) scale(${appear})`}>
            <rect x={-440} y={-66} width={880} height={132} rx={30} fill="#fff" stroke={INK} strokeWidth={STROKE} />
            <rect x={-410} y={-42} width={84} height={84} rx={18} fill={chk > 0.1 ? C.green : '#eee'} stroke={INK} strokeWidth={8} />
            <path d="M -394 0 L -372 24 L -338 -22" stroke="#fff" strokeWidth={16} fill="none" strokeLinecap="round" strokeLinejoin="round" transform={`translate(-368 0) scale(${chk}) translate(368 0)`} />
            <Label text={s} x={-300} y={22} size={64} maxWidth={710} anchor="start" fill={INK} stroke="#fff" sw={0} weight={700} shadow={false} />
          </g>
        );
      })}
    </g>
  );
};
const outroChecks = (ctx: ShotCtx) => {
  // check items when the voice reaches each step: after the colon, then after each comma
  const firstLine = ctx.words.filter((w) => w.line === ctx.words[0]?.line);
  const idx: number[] = [];
  firstLine.forEach((w, i) => {
    if (/[:,]$/.test(w.text) && i + 1 < firstLine.length) idx.push(firstLine[i + 1].start);
  });
  while (idx.length < 3) idx.push((idx.at(-1) ?? 0.5) + 1.5);
  return idx.slice(0, 3);
};
const outro: ShotDef[] = [
  {
    bg: 'stripes',
    render: (ctx) => (
      <g>
        <Checklist ctx={ctx} checks={outroChecks(ctx)} />
        <MaxC ctx={ctx} x={330} y={1600} scale={0.8} pose="point" mood="happy" look={[0.6, -0.6]} />
        <CoinC ctx={ctx} x={820} y={1270} scale={0.62} />
      </g>
    ),
  },
  {
    bg: 'dots',
    render: (ctx) => (
      <g>
        <Checklist ctx={ctx} checks={outroChecks(ctx)} />
        <MaxC ctx={ctx} x={760} y={1600} scale={0.8} pose="cheer" mood="happy" />
        <CoinC ctx={ctx} x={260} y={1270} scale={0.62} arms="up" />
      </g>
    ),
  },
  {
    bg: 'grid',
    render: (ctx) => {
      const L = ctx.labels;
      const press = ctx.t > 0.9 ? Math.max(0, Math.sin((ctx.t - 0.9) * 7)) : 0;
      const pressed = ctx.t > 1.1;
      const capAt = at(ctx, /капитал/, ctx.st + 2.5) - (ctx.st - ctx.t);
      return (
        <g>
          <g transform={`translate(540 560) scale(${popIn(ctx, 0.05) * (1 - 0.06 * press)})`}>
            <rect x={-380} y={-80} width={760} height={160} rx={80} fill={pressed ? '#9a97a8' : C.red} stroke={INK} strokeWidth={STROKE} />
            <Label text={L.subscribe} x={40} y={26} size={76} maxWidth={560} sw={12} />
            <g transform="translate(-300 0)">
              <path d="M -30 20 Q -30 -40 0 -40 Q 30 -40 30 20 L 40 30 L -40 30 Z" fill={C.yellow} stroke={INK} strokeWidth={7} strokeLinejoin="round" transform={`rotate(${pressed ? Math.sin(ctx.t * 20) * 15 : 0})`} />
            </g>
          </g>
          <Hand x={600 + 160 * (1 - range(ctx.t, 0.2, 0.9))} y={650 + 300 * (1 - range(ctx.t, 0.2, 0.9)) + press * 16} scale={0.9} rot={-20} />
          {pressed ? <Sparkles t={ctx.t} cx={540} cy={560} spread={420} n={10} color={C.yellow} /> : null}
          <g transform={`scale(1)`}>
            <Chart x={560} y={820} w={420} h={330} progress={range(ctx.t, 0.05, Math.min(0.9, Math.max(0.5, capAt)))} />
            <Label text={L.capital} x={770} y={1250} size={78} fill={C.yellow} scale={popIn(ctx, Math.max(0.4, capAt - 0.1))} maxWidth={440} />
          </g>
          <CoinC ctx={ctx} x={260} y={880} scale={0.62} arms="up" mood={pressed ? 'wink' : 'happy'} />
          <MaxC ctx={ctx} x={300} y={1640} scale={0.66} pose="wave" mood="happy" />
        </g>
      );
    },
  },
];

const VISUALS: Record<string, ShotDef[]> = { hook, subscriptions, impulse, payyourself, outro };

// Each shot variant is tied to a cue word of the voice-over: a shot shows the
// last variant whose cue has been spoken by (shot start + 0.5 s).
const CUES: Record<string, (RegExp | null)[]> = {
  hook: [null, /^дело/],
  subscriptions: [null, /^десять/, /^половин/, /^открой/],
  impulse: [null, /^увидел/, /^правило/, /^если/],
  payyourself: [null, /^сначала/, /^переверни/, /^зарплаты|^сразу/],
  outro: [null, /^жди/, /^подпишись/],
};

export function getShotDef(visual: string, shotStartInScene: number, words: Word[]): { def: ShotDef; index: number } {
  const defs = VISUALS[visual] ?? hook;
  const cues = CUES[visual] ?? [];
  let index = 0;
  defs.forEach((_, i) => {
    const re = cues[i];
    if (!re) return;
    const w = words.find((x) => re.test(x.text.toLowerCase()));
    if (w && w.start <= shotStartInScene + 0.5) index = i;
  });
  return { def: defs[index], index };
}
