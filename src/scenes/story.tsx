import React from 'react';
import {random} from 'remotion';
import {C, FPS, SceneProps, finance, lerp, money, pop, wobble, year} from '../lib';
import {Max} from '../components/Max';
import {Bill, Coin, Icon} from '../components/Icons';
import {Burst, Calendar, CoinRain, Pill, Pop, Stage, Strike, T, fadeIn} from '../components/ui';

const y20 = year(20);

// ---------- HOOK ----------
export const hookCounter: React.FC<SceneProps> = ({frame, dur}) => {
  const p = lerp(frame, [10, dur - 30], [0, 1]);
  const v = y20.contributed + (y20.balance - y20.contributed) * p;
  return (
    <Stage frame={frame} bg="#3a1c71" bg2="#d76d77" ground={false} clouds={false}>
      <Burst x={960} y={460} r={900} frame={frame} color="#ffaf7b" n={18} />
      <CoinRain frame={frame} n={26} seed="hk" />
      <T x={960} y={250} size={70} s={pop(frame, 0)}>{money(y20.contributed)} →</T>
      <T x={960} y={480} size={220} color={C.yellow} s={1 + 0.05 * Math.sin(frame / 6) * p}>{money(v)}</T>
      <T x={960} y={680} size={56} opacity={fadeIn(frame, 30)}>за 20 лет</T>
    </Stage>
  );
};

export const hookCrossed: React.FC<SceneProps> = ({frame, dur}) => {
  const items = [
    {icon: 'briefcase', label: 'бизнес'},
    {icon: 'bitcoin', label: 'крипта'},
    {icon: 'clover', label: 'везение'},
  ];
  const step = Math.max(14, (dur - 20) / 3);
  return (
    <Stage frame={frame} bg="#ffe8d6" bg2="#ffd6a5" ground={false} clouds={false}>
      {items.map((it, i) => {
        const x = 520 + i * 440;
        return (
          <g key={it.icon}>
            <Pop frame={frame} delay={i * 6} x={x} y={430}><Icon name={it.icon} s={1.3} /></Pop>
            <T x={x} y={650} size={64} opacity={fadeIn(frame, i * 6)}>{it.label}</T>
            <Strike x={x} y={430} size={130} p={lerp(frame, [i * step + 6, i * step + 22], [0, 1])} />
          </g>
        );
      })}
    </Stage>
  );
};

export const hookJar: React.FC<SceneProps> = ({frame}) => {
  const fall = lerp(frame, [0, 36], [-200, 470]);
  const inJar = frame > 36;
  const shake = inJar ? wobble(frame, 6 * Math.max(0, 1 - (frame - 36) / 30), 5) : 0;
  return (
    <Stage frame={frame} bg="#caffbf" bg2="#fdffb6" ground={false} clouds={false}>
      <g transform={`translate(960,${560}) rotate(${shake})`}>
        <Icon name="jar" s={2.2} />
        {inJar ? <g transform="translate(0,120) rotate(-8)"><Bill w={220} /></g> : null}
      </g>
      {!inJar ? <g transform={`translate(960,${fall}) rotate(${frame * 3})`}><Bill w={260} /></g> : null}
      <T x={960} y={150} size={96} color={C.greenDark} stroke={C.white} s={pop(frame, 30)}>$100 в месяц</T>
    </Stage>
  );
};

export const hookQuestion: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#a0c4ff" bg2="#bdb2ff">
    <Max x={560} y={900} s={0.95} frame={frame} mood="sad" armL={10} armR={10} />
    <Max x={1360} y={900} s={0.95} frame={frame} twin mood="happy" armR={130} handR={<Coin r={34} />} />
    <T x={960} y={420} size={300} color={C.yellow} s={1 + 0.06 * Math.sin(frame / 5)} r={wobble(frame, 4, 0.5)}>?</T>
    <Pill x={560} y={200} w={260} fill={C.maxShirt} color={C.white} s={pop(frame, 10)}>тратит</Pill>
    <Pill x={1360} y={200} w={400} fill={C.twinShirt} color={C.white} s={pop(frame, 18)} size={44}>откладывает</Pill>
  </Stage>
);

// ---------- STORY ----------
export const maxIntro: React.FC<SceneProps> = ({frame}) => {
  const wave = 120 + Math.sin(frame / 5) * 25;
  return (
    <Stage frame={frame}>
      <Max x={960} y={900} s={1.05} frame={frame} mood="joy" armR={wave} />
      <Pill x={960} y={170} w={520} h={110} size={64} s={pop(frame, 8)}>Это Макс</Pill>
    </Stage>
  );
};

export const maxJob: React.FC<SceneProps> = ({frame, dur}) => (
  <Stage frame={frame} bg="#ffd6e0" bg2="#fff1e6" ground="#e9c46a">
    {/* desk with laptop */}
    <rect x={1080} y={640} width={520} height={30} rx={10} fill="#8d5a3b" stroke={C.ink} strokeWidth={6} />
    <rect x={1110} y={670} width={30} height={220} fill="#8d5a3b" stroke={C.ink} strokeWidth={6} />
    <rect x={1540} y={670} width={30} height={220} fill="#8d5a3b" stroke={C.ink} strokeWidth={6} />
    <path d="M1240,640 L1260,500 L1460,500 L1480,640 Z" fill="#636e72" stroke={C.ink} strokeWidth={6} />
    <rect x={1290} y={530} width={140} height={80} fill="#74b9ff" />
    <Max x={760} y={900} s={0.95} frame={frame} mood="happy" armR={60} />
    <Pill x={760} y={190} w={360} s={pop(frame, 6)} fill={C.yellow}>25 лет</Pill>
    <g opacity={fadeIn(frame, dur * 0.55)}>
      <Calendar x={1360} y={300} s={0.85} day="1" />
    </g>
  </Stage>
);

export const payday: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#ffe066" bg2="#fff3b0" ground="#f4a261">
    <Burst x={960} y={500} r={800} frame={frame} color="#fff" />
    <CoinRain frame={frame} n={24} seed="pd" />
    <Max x={960} y={900} s={1} frame={frame} mood="joy" armL={150} armR={150} crown={frame > 20} />
    <Calendar x={420} y={330} s={0.9} day="1" />
    <T x={1460} y={300} size={86} color={C.yellow} s={pop(frame, 14)} r={-6}>Миллионер!</T>
  </Stage>
);

/** One small purchase: icon flies in, price tag pops, balance bar shrinks. */
export const expense: React.FC<SceneProps> = ({frame, dur, icon, icon2, label, price, balance = [1, 0.8], bg, night}) => {
  const b = lerp(frame, [18, icon2 ? dur * 0.6 : 40], balance as [number, number]);
  const barW = 520;
  return (
    <Stage frame={frame} bg={bg ?? '#ffe5ec'} bg2="#ffffff" night={night} ground={night ? '#3d348b' : '#b8e0d2'}>
      <Max x={620} y={900} s={0.95} frame={frame} mood={b < 0.45 ? 'confused' : 'happy'} armR={70}
        handR={icon === 'coffee' || icon === 'phone' ? <Icon name={icon} s={0.45} /> : undefined} />
      <Pop frame={frame} delay={2} x={icon2 ? 1150 : 1280} y={470}><Icon name={icon} s={icon2 ? 1.4 : 1.7} r={wobble(frame, 4, 0.7)} /></Pop>
      {icon2 ? <Pop frame={frame} delay={dur * 0.5} x={1440} y={430}><Icon name={icon2} s={1.2} /></Pop> : null}
      <T x={1280} y={215} size={64} opacity={fadeIn(frame, 4)}>{label}</T>
      <g transform={`translate(1460,610) rotate(10) scale(${pop(frame, 14)})`}>
        <rect x={-110} y={-56} width={220} height={112} rx={20} fill={C.red} stroke={C.ink} strokeWidth={6} />
        <text x={0} y={4} textAnchor="middle" dominantBaseline="middle" fontFamily="Rubik" fontWeight={900} fontSize={68} fill="#fff">−${price}</text>
      </g>
      {/* balance bar above Max */}
      <g transform="translate(360,160)">
        <text x={0} y={-24} fontFamily="Rubik" fontWeight={800} fontSize={36} fill={night ? '#fff' : C.ink}>Зарплата</text>
        <rect x={0} y={0} width={barW} height={50} rx={25} fill="#fff" stroke={C.ink} strokeWidth={6} />
        <rect x={6} y={6} width={(barW - 12) * b} height={38} rx={19} fill={b < 0.45 ? C.red : C.green} />
      </g>
    </Stage>
  );
};

export const coinsTrickle: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#e2ece9" bg2="#fff">
    <g transform="translate(960,420)"><Icon name="wallet" s={2} /></g>
    {Array.from({length: 10}).map((_, i) => {
      const t = (frame - i * 9) / FPS;
      if (t < 0) return null;
      const x = 960 + (i % 2 ? 1 : -1) * (80 + t * 260 * (0.6 + random(`ct${i}`)));
      const y = 380 - t * 300 + t * t * 700;
      return (
        <g key={i} transform={`translate(${x},${y})`}>
          <Coin r={34} />
          <T x={0} y={-60} size={34} color={C.red}>−$3</T>
        </g>
      );
    })}
    <T x={960} y={140} size={84} color={C.ink} stroke={C.white}>Мелочь…</T>
  </Stage>
);

export const threeDollars: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#cdb4db" bg2="#ffc8dd">
    <Max x={760} y={900} s={1} frame={frame} mood="smug" armL={60} armR={120} handR={<Coin r={40} label="3" />} />
    <T x={1360} y={400} size={140} color={C.yellow} s={pop(frame, 6)} r={-8}>$3?</T>
    <T x={1360} y={560} size={56} opacity={fadeIn(frame, 16)}>ерунда же</T>
  </Stage>
);

export const bankApp: React.FC<SceneProps> = ({frame, dur}) => {
  const v = lerp(frame, [dur * 0.25, dur * 0.85], [1450, 7]);
  return (
    <Stage frame={frame} bg="#a2d2ff" bg2="#e7f6ff">
      <Calendar x={420} y={320} s={0.9} day="20" month="ДЕНЬ" />
      <Max x={700} y={900} s={0.9} frame={frame} mood={v < 100 ? 'shock' : 'neutral'} armR={70} />
      <g transform={`translate(1300,500) scale(${pop(frame, 4)})`}>
        <rect x={-190} y={-360} width={380} height={720} rx={50} fill={C.navy} stroke={C.ink} strokeWidth={8} />
        <rect x={-165} y={-325} width={330} height={650} rx={30} fill="#fff" />
        <text x={0} y={-250} textAnchor="middle" fontFamily="Rubik" fontWeight={700} fontSize={36} fill="#777">Баланс</text>
        <text x={0} y={-160} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={96} fill={v < 100 ? C.red : C.ink}>${Math.round(v)}</text>
        {['Кофе', 'Доставка', 'Бар', 'Такси', 'Покупка'].map((l, i) => (
          <g key={l} transform={`translate(-135,${-60 + i * 72})`} opacity={fadeIn(frame, 10 + i * 6)}>
            <rect width={270} height={56} rx={14} fill="#f1f2f6" />
            <text x={18} y={37} fontFamily="Rubik" fontWeight={700} fontSize={30} fill={C.ink}>{l}</text>
            <text x={252} y={37} textAnchor="end" fontFamily="Rubik" fontWeight={800} fontSize={30} fill={C.red}>−$</text>
          </g>
        ))}
      </g>
    </Stage>
  );
};

export const confused: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#e9edc9" bg2="#fefae0">
    <Max x={960} y={900} s={1.05} frame={frame} mood="confused" armR={150} armL={20} />
    {[0, 1, 2].map((i) => (
      <T key={i} x={700 + i * 260} y={260 - (i % 2) * 70 + wobble(frame + i * 20, 12)} size={130} color={C.purple} s={pop(frame, i * 6)}>?</T>
    ))}
  </Stage>
);

export const emptyWallet: React.FC<SceneProps> = ({frame}) => {
  const fly = frame / FPS;
  return (
    <Stage frame={frame} bg="#d8e2dc" bg2="#fff">
      <g transform="translate(960,560)">
        <Icon name="wallet" s={2.3} />
      </g>
      {/* moth flying out */}
      <g transform={`translate(${960 + fly * 160},${430 - fly * 120 + Math.sin(frame / 4) * 20})`}>
        <ellipse cx={-22} cy={0} rx={26} ry={16 * Math.abs(Math.sin(frame / 3))} fill="#c9b79c" stroke={C.ink} strokeWidth={4} />
        <ellipse cx={22} cy={0} rx={26} ry={16 * Math.abs(Math.sin(frame / 3))} fill="#c9b79c" stroke={C.ink} strokeWidth={4} />
        <ellipse cx={0} cy={0} rx={8} ry={20} fill="#6d597a" />
      </g>
      <T x={960} y={190} size={96} color={C.ink} stroke={C.white} s={pop(frame, 8)}>Пусто</T>
    </Stage>
  );
};

export const moneyFlyAway: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#bde0fe" bg2="#fff">
    <Max x={560} y={900} s={0.95} frame={frame} mood="sad" armR={40} />
    {Array.from({length: 8}).map((_, i) => {
      const t = Math.max(0, frame - i * 8) / FPS;
      return (
        <g key={i} transform={`translate(${700 + t * 420 + i * 30},${520 - t * 160 + Math.sin(frame / 8 + i) * 30}) rotate(${Math.sin(frame / 10 + i) * 30})`}
          opacity={t > 0 ? 1 : 0}>
          <Bill w={150} label="$" />
        </g>
      );
    })}
  </Stage>
);

export const iceCream: React.FC<SceneProps> = ({frame, dur}) => {
  const m = lerp(frame, [8, dur - 10], [0, 1]);
  return (
    <Stage frame={frame} bg="#ffd166" bg2="#fff4cc" ground="#f4a261">
      <g transform="translate(1500,230)"><Icon name="sun" s={1.1 + 0.05 * Math.sin(frame / 8)} r={frame / 2} /></g>
      <g transform={`translate(860,${520 + m * 60}) scale(${1.8 * (1 - m * 0.2)},${1.8 * (1 - m * 0.5)})`}>
        <Icon name="iceCream" />
      </g>
      {/* puddle */}
      <ellipse cx={860} cy={820} rx={60 + m * 260} ry={14 + m * 30} fill="#7fd99a" stroke={C.ink} strokeWidth={5} opacity={m > 0.05 ? 1 : 0} />
      {[0, 1, 2].map((i) => (
        <ellipse key={i} cx={760 + i * 100} cy={560 + ((frame * 3 + i * 60) % 240)} rx={10} ry={16} fill="#7fd99a" opacity={m > 0.1 ? 1 : 0} />
      ))}
    </Stage>
  );
};

export const calendarFlip: React.FC<SceneProps> = ({frame, mode}) => {
  const months = ['ЯНВ', 'ФЕВ', 'МАР', 'АПР', 'МАЙ', 'ИЮН', 'ИЮЛ', 'АВГ', 'СЕН', 'ОКТ', 'НОЯ', 'ДЕК'];
  const speed = mode === 'years' ? 9 : 7;
  const k = Math.floor(frame / speed);
  const label = mode === 'years' ? String(2026 + k) : months[k % 12];
  const flipT = (frame % speed) / speed;
  return (
    <Stage frame={frame} bg="#c8b6ff" bg2="#e7c6ff">
      <g transform={`translate(960,470) scale(1.6) rotate(${wobble(frame, 2, 1)})`}>
        <Calendar x={0} y={0} day="" month={label} />
        {mode !== 'years' ? <text x={0} y={40} textAnchor="middle" dominantBaseline="middle" fontFamily="Rubik" fontWeight={900} fontSize={56} fill={C.red}>−$$$</text> : null}
        {mode === 'years' ? <text x={0} y={40} textAnchor="middle" dominantBaseline="middle" fontFamily="Rubik" fontWeight={900} fontSize={72} fill={C.ink}>{label}</text> : null}
        <rect x={-110} y={-100} width={220} height={210} rx={20} fill="#fff" opacity={0.6 * (1 - flipT)} transform={`skewY(${-20 * flipT})`} />
      </g>
      <g transform="translate(960,860)">
        {Array.from({length: 6}).map((_, i) => (
          <g key={i} transform={`translate(${(i - 2.5) * 140},0) scale(${0.4})`}><Coin r={60} label="−" /></g>
        ))}
      </g>
    </Stage>
  );
};

export const thought: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#ffcad4" bg2="#fff0f3">
    <Max x={560} y={900} s={0.95} frame={frame} mood="smug" armR={150} armL={10} />
    <circle cx={760} cy={430} r={20} fill="#fff" stroke={C.ink} strokeWidth={5} opacity={fadeIn(frame, 4)} />
    <circle cx={830} cy={360} r={32} fill="#fff" stroke={C.ink} strokeWidth={5} opacity={fadeIn(frame, 8)} />
    <g transform={`translate(1260,260) scale(${pop(frame, 12)})`}>
      <ellipse rx={420} ry={170} fill="#fff" stroke={C.ink} strokeWidth={6} />
      <text x={0} y={-30} textAnchor="middle" fontFamily="Rubik" fontWeight={800} fontSize={60} fill={C.ink}>«Начну откладывать</text>
      <text x={0} y={50} textAnchor="middle" fontFamily="Rubik" fontWeight={900} fontSize={84} fill={C.red}>ПОТОМ…»</text>
    </g>
  </Stage>
);

export const familiar: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#ffadad" bg2="#ffd6a5" ground={false} clouds={false}>
    <g transform={`translate(960,${1350}) scale(${1.9 + frame * 0.002})`}>
      <Max x={0} y={0} frame={frame} mood="smug" bob={false} />
    </g>
    <T x={960} y={190} size={130} color={C.yellow} s={pop(frame, 4)} r={-4}>Знакомо?</T>
  </Stage>
);

export const portal: React.FC<SceneProps> = ({frame, dur}) => {
  const open = lerp(frame, [0, 30], [0, 1]);
  const twinIn = lerp(frame, [dur * 0.4, dur * 0.8], [0, 1]);
  return (
    <Stage frame={frame} bg="#240046" bg2="#7b2cbf" ground="#3c096c" clouds={false} night>
      <Max x={560} y={900} s={0.9} frame={frame} mood="shock" />
      <g transform={`translate(1340,560) rotate(${frame * 2})`}>
        <ellipse rx={260 * open} ry={330 * open} fill="none" stroke="#c77dff" strokeWidth={30} strokeDasharray="60 30" />
        <ellipse rx={220 * open} ry={290 * open} fill="#e0aaff" opacity={0.5} />
      </g>
      <Max x={1340} y={900} s={0.9 * twinIn} frame={frame} twin mood="happy" armR={110} opacity={twinIn} />
    </Stage>
  );
};

export const twinsMirror: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame}>
    <line x1={960} y1={60} x2={960} y2={870} stroke="#fff" strokeWidth={10} strokeDasharray="30 20" />
    <Max x={560} y={900} s={0.95} frame={frame} mood="happy" armR={70} handR={<Icon name="coffee" s={0.45} />} />
    <Max x={1360} y={900} s={0.95} frame={frame} twin mood="happy" armL={70} flip handL={<Icon name="coffee" s={0.45} />} />
    <Pill x={960} y={150} w={540} s={pop(frame, 6)} fill={C.yellow}>одна зарплата</Pill>
  </Stage>
);

export const oneDifference: React.FC<SceneProps> = ({frame}) => (
  <Stage frame={frame} bg="#10002b" bg2="#3c096c" ground="#240046" clouds={false}>
    <path d="M1260,0 L1460,0 L1660,880 L1060,880 Z" fill="#fff8c4" opacity={0.25 * fadeIn(frame, 0, 10)} />
    <Max x={560} y={900} s={0.9} frame={frame} mood="neutral" opacity={0.5} />
    <Max x={1360} y={900} s={0.95} frame={frame} twin mood="smug" armR={140} handR={<Icon name="piggy" s={0.55} />} />
    <T x={960} y={170} size={90} color={C.yellow} s={pop(frame, 10)}>одно отличие</T>
  </Stage>
);
