import React from 'react';
import {random} from 'remotion';
import {C, FPS, SceneProps, finance, lerp, money, pop, wobble, year} from '../lib';
import {Max} from '../components/Max';
import {Bill, Coin, Icon} from '../components/Icons';
import {Burst, Calendar, Confetti, Pill, Pop, Stage, Strike, T, fadeIn} from '../components/ui';

const y20 = year(20);

export const yearsPass: React.FC<SceneProps> = ({frame, dur}) => {
  const yr = Math.round(lerp(frame, [0, dur * 0.8], [2026, 2046]));
  return (
    <Stage frame={frame} bg="#cdb4db" bg2="#ffafcc" ground={false} clouds={false}>
      <g transform={`translate(960,450) scale(1.7) rotate(${wobble(frame, 3, 2)})`}>
        <Calendar x={0} y={0} day="" month="ГОД" />
        <text x={0} y={40} textAnchor="middle" dominantBaseline="middle" fontFamily="Rubik" fontWeight={900} fontSize={70} fill={C.ink}>{yr}</text>
      </g>
      <T x={960} y={850} size={80} color={C.white} s={pop(frame, 10)}>+20 лет</T>
    </Stage>
  );
};

export const bothAged: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#ffd6a5" bg2="#fdffb6">
    <Max x={560} y={900} s={0.95} frame={frame} gray mood="neutral" />
    <Max x={1360} y={900} s={0.95} frame={frame} gray twin mood="happy" />
    <Pill x={960} y={170} w={340} fill={C.yellow} s={pop(frame, 6)} size={60}>45 лет</Pill>
  </Stage>
);

export const podiums: React.FC<SceneProps> = ({frame, reveal}) => {
  const showMax = reveal === 'max' || reveal === 'both';
  const showTwin = reveal === 'both';
  return (
    <Stage frame={frame} bg="#a0c4ff" bg2="#e0ecff" ground={false} clouds={false}>
      {showTwin ? <Burst x={1360} y={360} r={700} frame={frame} color="#fff" /> : null}
      <rect x={360} y={820} width={400} height={260} fill="#ced4da" stroke={C.ink} strokeWidth={6} />
      <rect x={1160} y={720} width={400} height={360} fill={C.yellow} stroke={C.ink} strokeWidth={6} />
      <Max x={560} y={830} s={0.8} frame={frame} gray mood={showMax ? 'sad' : 'neutral'} />
      <Max x={1360} y={730} s={0.8} frame={frame} gray twin mood={showTwin ? 'joy' : 'happy'} armL={showTwin ? 150 : 10} armR={showTwin ? 150 : 10} />
      <g>
        <T x={560} y={170} size={showMax ? 130 : 90} color={showMax ? C.red : C.white} s={showMax ? pop(frame, 4) : 1}>{showMax ? '$0' : '?'}</T>
        <T x={1360} y={110} size={showTwin ? 120 : 90} color={showTwin ? C.greenDark : C.white} stroke={showTwin ? '#fff' : C.ink} s={showTwin ? pop(frame, 4) : 1}>
          {showTwin ? money(y20.balance) : '?'}
        </T>
      </g>
      {showTwin ? <Confetti frame={frame} seed="pod" n={40} /> : null}
    </Stage>
  );
};

export const spentCounter: React.FC<SceneProps> = ({frame, dur}) => {
  const v = lerp(frame, [6, dur * 0.85], [0, y20.contributed]);
  return (
    <Stage frame={frame} bg="#ffadad" bg2="#ffd6a5" ground={false} clouds={false}>
      <Max x={460} y={900} s={0.85} frame={frame} gray mood="confused" />
      {Array.from({length: 12}).map((_, i) => {
        const t = ((frame + i * 12) % 70) / 70;
        return (
          <g key={i} transform={`translate(${620 + t * 900},${520 - Math.sin(t * Math.PI) * 300 + i * 6}) rotate(${t * 300})`} opacity={1 - t}>
            <Bill w={120} label="$" />
          </g>
        );
      })}
      <T x={1220} y={250} size={60} color={C.white}>потрачено</T>
      <T x={1220} y={400} size={150} color={C.white} stroke={C.red}>−{money(v)}</T>
    </Stage>
  );
};

export const junkPile: React.FC<SceneProps> = ({frame}) => {
  const items = ['coffee', 'box', 'delivery', 'coffee', 'box', 'phone', 'coffee', 'delivery', 'box', 'coffee', 'bar', 'box'];
  return (
    <Stage frame={frame} bg="#e9ecef" bg2="#f8f9fa" ground="#ced4da">
      {/* shelf / attic */}
      <rect x={360} y={250} width={1200} height={24} fill="#8d5a3b" stroke={C.ink} strokeWidth={5} />
      {items.map((it, i) => {
        const x = 460 + (i % 6) * 200;
        const y = i < 6 ? 180 : 760;
        return <Pop key={i} frame={frame} delay={i * 3} x={x} y={y}><Icon name={it} s={0.7} r={(random(`j${i}`) - 0.5) * 30} /></Pop>;
      })}
      {/* dust */}
      {Array.from({length: 20}).map((_, i) => (
        <circle key={i} cx={400 + random(`d${i}`) * 1100} cy={150 + ((frame * 0.5 + random(`dy${i}`) * 700) % 700)} r={4} fill="#adb5bd" />
      ))}
      <T x={960} y={480} size={84} color={C.ink} stroke="#fff" s={pop(frame, 20)}>пылится на антресолях</T>
    </Stage>
  );
};

export const payYourself: React.FC<SceneProps> = ({frame, dur}) => (
  <Stage frame={frame} bg="#b9fbc0" bg2="#f1fff3">
    <Max x={420} y={900} s={0.85} frame={frame} gray twin mood="smug" armR={130} />
    <g transform="translate(1180,0)">
      <Pop frame={frame} delay={8} x={0} y={330}>
        <rect x={-380} y={-80} width={760} height={160} rx={30} fill={C.green} stroke={C.ink} strokeWidth={6} />
        <text x={0} y={18} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={64} fill="#fff">1. Сначала себе $100</text>
      </Pop>
      <Pop frame={frame} delay={dur * 0.55} x={0} y={560}>
        <rect x={-380} y={-80} width={760} height={160} rx={30} fill="#fff" stroke={C.ink} strokeWidth={6} />
        <text x={0} y={18} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={64} fill={C.ink}>2. Потом траты</text>
      </Pop>
    </g>
  </Stage>
);

export const useCase: React.FC<SceneProps> = ({frame, icon, label, bg}) => (
  <Stage frame={frame} bg={bg} bg2="#fff">
    <Burst x={960} y={460} r={600} frame={frame} color="#fff" />
    <Pop frame={frame} x={960} y={470}><Icon name={icon} s={2.3} r={wobble(frame, 3, 0.5)} /></Pop>
    <T x={960} y={150} size={84} color={C.ink} stroke="#fff" s={pop(frame, 8)}>{label}</T>
    <Pill x={960} y={800} w={420} fill={C.green} color="#fff" s={pop(frame, 16)}>{money(y20.balance)}</Pill>
  </Stage>
);

export const crossedWords: React.FC<SceneProps> = ({frame, dur}) => {
  const words = ['зарплата', 'талант', 'везение'];
  const step = (dur - 20) / 3;
  return (
    <Stage frame={frame} bg="#f8edeb" bg2="#fff" ground={false} clouds={false}>
      {words.map((w, i) => (
        <g key={w}>
          <T x={960} y={260 + i * 220} size={110} color={C.ink} stroke="#fff" opacity={fadeIn(frame, i * step * 0.6)}>{w}</T>
          <line x1={680} x2={680 + 560 * lerp(frame, [i * step + 10, i * step + 22], [0, 1])} y1={260 + i * 220} y2={260 + i * 220}
            stroke={C.red} strokeWidth={22} strokeLinecap="round" />
        </g>
      ))}
    </Stage>
  );
};

export const oneDecision: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#2b2d42" bg2="#8d99ae" ground={false} clouds={false}>
    <path d="M760,0 L1160,0 L1360,1080 L560,1080 Z" fill="#fff8c4" opacity={0.18} />
    <g transform={`translate(960,470) scale(${pop(frame, 4)})`}>
      <circle r={190} fill={C.green} stroke={C.ink} strokeWidth={10} />
      <circle r={150} fill="#3dff9a" stroke={C.ink} strokeWidth={6} />
      <text x={0} y={30} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={80} fill="#fff">$100</text>
    </g>
    <T x={960} y={140} size={84} color={C.yellow}>одно решение</T>
    <T x={960} y={800} size={56} color="#fff" opacity={fadeIn(frame, 20)}>20 лет назад</T>
  </Stage>
);

// ---------- OUTRO ----------
export const hourglass: React.FC<SceneProps> = ({frame, dur}) => {
  const p = lerp(frame, [0, dur], [0, 1], (x) => x);
  return (
    <Stage frame={frame} bg="#ffd166" bg2="#fff4cc" ground={false} clouds={false}>
      <g transform="translate(960,490) scale(2.6)">
        <Icon name="hourglass" />
        <path d={`M${-50 * (1 - p)},${-90 + 80 * p} L${50 * (1 - p)},${-90 + 80 * p} L0,-6 Z`} fill={C.yellow} />
        <path d={`M-52,96 L52,96 L${30 * (1 - p) + 6},${96 - 70 * p} L${-30 * (1 - p) - 6},${96 - 70 * p} Z`} fill={C.yellow} />
        <line x1={0} y1={-6} x2={0} y2={94} stroke="#e0a800" strokeWidth={3} strokeDasharray="4 6" strokeDashoffset={-frame} />
      </g>
      <T x={960} y={120} size={90} color={C.ink} stroke="#fff" s={pop(frame, 6)}>главное — время</T>
    </Stage>
  );
};

export const earlyVsLate: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#e0fbfc" bg2="#fff" ground={false} clouds={false}>
    <T x={960} y={120} size={60} color={C.ink} stroke="#fff">чтобы получить {money(y20.balance)}</T>
    <Pop frame={frame} delay={6} x={560} y={500}>
      <rect x={-330} y={-220} width={660} height={440} rx={30} fill={C.green} stroke={C.ink} strokeWidth={7} />
      <text x={0} y={-110} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={56} fill="#fff">за 20 лет</text>
      <text x={0} y={40} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={130} fill="#fff">${finance.monthly}</text>
      <text x={0} y={140} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={50} fill="#fff">в месяц</text>
    </Pop>
    <Pop frame={frame} delay={24} x={1360} y={500}>
      <rect x={-330} y={-220} width={660} height={440} rx={30} fill="#fff" stroke={C.ink} strokeWidth={7} />
      <text x={0} y={-110} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={56} fill={C.ink}>за 10 лет</text>
      <text x={0} y={40} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={130} fill={C.red}>${Math.round(finance.needMonthlyFor10y)}</text>
      <text x={0} y={140} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={50} fill={C.ink}>в месяц</text>
    </Pop>
  </Stage>
);

export const handshake: React.FC<SceneProps> = ({frame, dur}) => {
  const drop = lerp(frame, [dur * 0.4, dur * 0.7], [0, 1]);
  return (
    <Stage frame={frame}>
      <Max x={520} y={900} s={0.9} frame={frame} mood="happy" armR={70} />
      <Max x={1400} y={900} s={0.9} frame={frame} twin mood="joy" armL={70} flip />
      <g transform="translate(960,700)"><Icon name="piggy" s={1.4} /></g>
      <g transform={`translate(960,${300 + drop * 300}) rotate(${drop * 20})`} opacity={drop < 1 ? 1 : 0}><Bill w={160} label="$" /></g>
      <Pill x={960} y={150} w={760} fill={C.yellow} s={pop(frame, 6)}>начни с малого — сегодня</Pill>
    </Stage>
  );
};

export const subscribe: React.FC<SceneProps> = ({frame, dur}) => {
  const click = frame > dur * 0.45;
  const cx = lerp(frame, [0, dur * 0.42], [1500, 1010]);
  const cy = lerp(frame, [0, dur * 0.42], [900, 520]);
  return (
    <Stage frame={frame} bg="#ff595e" bg2="#ff924c" ground={false} clouds={false}>
      <Burst x={960} y={500} r={900} frame={frame} color="#ffca3a" />
      <g transform={`translate(860,500) scale(${pop(frame, 0) * (click && frame < dur * 0.45 + 8 ? 0.94 : 1)})`}>
        <rect x={-340} y={-90} width={680} height={180} rx={90} fill={click ? '#adb5bd' : '#e00000'} stroke={C.ink} strokeWidth={8} />
        <text x={0} y={22} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={70} fill="#fff">{click ? 'Вы подписаны' : 'ПОДПИСАТЬСЯ'}</text>
      </g>
      <Pop frame={frame} delay={dur * 0.5} x={1360} y={500}><g transform={`rotate(${click ? wobble(frame, 18, 3) : 0})`}><Icon name="bell" s={1.1} /></g></Pop>
      <Pop frame={frame} delay={dur * 0.65} x={960} y={780}><Icon name="thumb" s={1.1} /></Pop>
      {/* cursor */}
      <g transform={`translate(${cx},${cy})`}>
        <path d="M0,0 L0,80 L22,60 L38,96 L52,90 L36,54 L66,54 Z" fill="#fff" stroke={C.ink} strokeWidth={5} strokeLinejoin="round" />
      </g>
    </Stage>
  );
};

export const disclaimer: React.FC<SceneProps> = ({frame, full}) => (
  <Stage frame={frame} bg="#1d2b53" bg2="#3a4a7a" ground={false} clouds={false}>
    <T x={960} y={full ? 230 : 400} size={full ? 72 : 96} color={C.yellow} s={full ? 1 : pop(frame, 0)}>Не финансовая рекомендация</T>
    {full ? (
      <g opacity={fadeIn(frame, 6, 20)}>
        {[
          'Расчёт учебный: $100 в конце каждого месяца,',
          '7% годовых — допущение, капитализация ежемесячно,',
          'без учёта налогов, комиссий и инфляции.',
          'Реальная доходность может отличаться.',
          'Инвестиции всегда связаны с риском.',
        ].map((l, i) => (
          <text key={i} x={960} y={390 + i * 76} textAnchor="middle" fontFamily="Rubik" fontWeight={700} fontSize={46} fill="#fff">{l}</text>
        ))}
      </g>
    ) : (
      <T x={960} y={560} size={56} color="#fff" opacity={fadeIn(frame, 10)}>только образовательный пример</T>
    )}
  </Stage>
);
