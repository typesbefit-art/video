import React from 'react';
import {AbsoluteFill, interpolate, random, spring, useCurrentFrame, useVideoConfig, Easing} from 'remotion';
import {ACCENT, FONT, FLASH_AT, FREEZE_LEN, FREEZE_START, SCENES, WHITE} from './constants';
import {BigNumber} from './BigNumber';
import {Captions} from './Captions';

type Seg = {text: string; accent?: boolean};

const textBlock: React.CSSProperties = {
  position: 'absolute',
  top: 700,
  left: 70,
  right: 70,
  textAlign: 'center',
  fontFamily: FONT,
  fontWeight: 900,
  fontSize: 92,
  lineHeight: 1.12,
  color: WHITE,
  textShadow: '0 6px 24px rgba(0,0,0,0.6)',
};

const Accent: React.FC<{children: React.ReactNode}> = ({children}) => (
  <span style={{color: ACCENT, textShadow: `0 0 24px ${ACCENT}aa, 0 0 6px ${ACCENT}`}}>{children}</span>
);

// Плавный уход сцены в конце (fade + лёгкое уменьшение)
const useExit = (duration: number, len = 8) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [duration - len, duration], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
};

/* ---------- 1. Крючок (0–3 с) ---------- */
export const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const exit = useExit(SCENES.hook.duration);

  const s1 = spring({frame, fps, config: {damping: 9, stiffness: 160}});
  const s2 = spring({frame: frame - 14, fps, config: {damping: 6, stiffness: 180, mass: 0.9}});

  // Тряска экрана, когда «влетает» главная фраза
  const shakeT = frame - 16;
  const shakeAmp = shakeT >= 0 ? Math.max(0, 1 - shakeT / 22) * 18 : 0;
  const sx = (random(`sx${frame}`) - 0.5) * 2 * shakeAmp;
  const sy = (random(`sy${frame}`) - 0.5) * 2 * shakeAmp;
  const rot = (random(`sr${frame}`) - 0.5) * shakeAmp * 0.12;

  return (
    <AbsoluteFill style={{opacity: exit, transform: `translate(${sx}px, ${sy}px) rotate(${rot}deg) scale(${0.9 + 0.1 * exit})`}}>
      <div
        style={{
          position: 'absolute',
          top: 340,
          left: 70,
          right: 70,
          textAlign: 'center',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: 78,
          lineHeight: 1.15,
          color: WHITE,
          transform: `scale(${s1})`,
          textShadow: '0 6px 24px rgba(0,0,0,0.6)',
        }}
      >
        Ты не поверишь,
        <br />
        что в космосе
      </div>
      <div
        style={{
          position: 'absolute',
          top: 620,
          left: 40,
          right: 40,
          textAlign: 'center',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: 120,
          lineHeight: 1.02,
          letterSpacing: -2,
          color: ACCENT,
          transform: `scale(${Math.max(0, s2)})`,
          transformOrigin: '50% 50%',
          opacity: frame >= 14 ? 1 : 0,
          textShadow: `0 0 40px ${ACCENT}99, 0 0 10px ${ACCENT}, 0 8px 0 #3a0a6a`,
        }}
      >
        ПАХНЕТ
        <br />
        ЖАРЕНЫМ
        <br />
        СТЕЙКОМ
      </div>
      <Captions
        text="Так астронавты описывают запах открытого космоса"
        delay={26}
        framesPerWord={6}
        accentWords={['запах']}
      />
    </AbsoluteFill>
  );
};

/* ---------- Печать текста по буквам ---------- */
const Typewriter: React.FC<{segs: Seg[]; start: number; cps: number}> = ({segs, start, cps}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const total = segs.reduce((a, s) => a + s.text.length, 0);
  const shown = Math.max(0, Math.min(total, Math.floor(((frame - start) / fps) * cps)));
  let left = shown;
  const cursorOn = Math.floor(frame / 8) % 2 === 0 || shown < total;
  return (
    <>
      {segs.map((s, i) => {
        const take = Math.max(0, Math.min(s.text.length, left));
        left -= take;
        const visible = s.text.slice(0, take);
        const hidden = s.text.slice(take);
        const inner = (
          <>
            {visible}
            <span style={{opacity: 0}}>{hidden}</span>
          </>
        );
        return <React.Fragment key={i}>{s.accent ? <Accent>{inner}</Accent> : inner}</React.Fragment>;
      })}
      <span
        style={{
          display: 'inline-block',
          width: 0,
          overflow: 'visible',
          color: ACCENT,
          opacity: shown < total || cursorOn ? 1 : 0,
          transform: 'translateX(4px)',
        }}
      >
        |
      </span>
    </>
  );
};

/* ---------- Орбита Венеры (декор) ---------- */
const VenusOrbit: React.FC = () => {
  const frame = useCurrentFrame();
  const a = frame / 20;
  return (
    <svg width={1080} height={420} style={{position: 'absolute', top: 250, left: 0}}>
      <ellipse cx={540} cy={210} rx={300} ry={110} fill="none" stroke="rgba(0,229,255,0.35)" strokeWidth={3} strokeDasharray="10 14" />
      <circle cx={540 + Math.cos(a) * 300} cy={210 + Math.sin(a) * 110} r={26} fill="url(#venus)" />
      <defs>
        <radialGradient id="venus" cx="35%" cy="35%">
          <stop offset="0%" stopColor="#FFE9B0" />
          <stop offset="100%" stopColor="#D08A2E" />
        </radialGradient>
      </defs>
    </svg>
  );
};

/* ---------- 2. Факт 1 (3–10 с) ---------- */
export const Fact1: React.FC = () => {
  const frame = useCurrentFrame();
  const d = SCENES.fact1.duration;
  // Уезжает влево, уступая место факту 2
  const out = interpolate(frame, [d - 14, d], [0, -1080], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.cubic),
  });
  return (
    <AbsoluteFill style={{transform: `translateX(${out}px)`}}>
      <VenusOrbit />
      <BigNumber n={1} />
      <div style={textBlock}>
        <Typewriter
          start={10}
          cps={22}
          segs={[
            {text: 'Один день на '},
            {text: 'Венере', accent: true},
            {text: ' длиннее её '},
            {text: 'года', accent: true},
          ]}
        />
      </div>
      <Captions
        text="Сутки там длятся 243 земных дня, а год — всего 225"
        delay={70}
        framesPerWord={7}
        accentWords={['243', '225']}
      />
    </AbsoluteFill>
  );
};

/* ---------- Ветер (декор для Нептуна) ---------- */
const WindStreaks: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      {new Array(22).fill(0).map((_, i) => {
        const y = 260 + random(`wy${i}`) * 1200;
        const len = 120 + random(`wl${i}`) * 260;
        const speed = 28 + random(`ws${i}`) * 30;
        const x = ((random(`wx${i}`) * 1600 + frame * speed) % 1700) - 300;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              top: y,
              left: x,
              width: len,
              height: 3,
              borderRadius: 3,
              background: `linear-gradient(90deg, rgba(0,229,255,0), rgba(0,229,255,${0.25 + random(`wo${i}`) * 0.4}))`,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

/* ---------- 3. Факт 2 (10–17 с) — въезжает слайдом ---------- */
export const Fact2: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const inS = spring({frame, fps, config: {damping: 16, stiffness: 110}});
  const x = (1 - inS) * 1080;
  const exit = useExit(SCENES.fact2.duration);
  const t = spring({frame: frame - 10, fps, config: {damping: 14}});
  return (
    <AbsoluteFill style={{transform: `translateX(${x}px)`, opacity: exit}}>
      <WindStreaks />
      <BigNumber n={2} delay={4} />
      <div style={{...textBlock, opacity: t, transform: `translateY(${(1 - t) * 60}px)`}}>
        На <Accent>Нептуне</Accent> ветер <Accent>быстрее звука</Accent>
      </div>
      <Captions
        text="Ураганы там разгоняются до 2100 км/ч — в 1,7 раза быстрее звука на Земле"
        delay={36}
        framesPerWord={7}
        accentWords={['2100', 'км/ч']}
      />
    </AbsoluteFill>
  );
};

/* ---------- Звуковая волна, которая затихает ---------- */
const SoundWave: React.FC = () => {
  const frame = useCurrentFrame();
  const abs = frame + SCENES.fact3.from;
  // До заморозки — живая волна, после — тишина (ровная линия)
  const amp = interpolate(abs, [FREEZE_START - 6, FREEZE_START], [1, 0.0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const bars = 27;
  return (
    <div
      style={{
        position: 'absolute',
        top: 1090,
        left: 0,
        right: 0,
        height: 160,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
      }}
    >
      {new Array(bars).fill(0).map((_, i) => {
        const h = 8 + amp * (20 + 110 * Math.abs(Math.sin(frame / 4 + i * 0.7)) * (1 - Math.abs(i - bars / 2) / (bars / 1.6)));
        return <div key={i} style={{width: 14, height: h, borderRadius: 7, background: ACCENT, boxShadow: `0 0 12px ${ACCENT}`, opacity: 0.85}} />;
      })}
    </div>
  );
};

/* ---------- 4. Факт 3 (17–23 с) — звёзды замирают, вспышка ---------- */
export const Fact3: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const abs = frame + SCENES.fact3.from;
  const inS = spring({frame, fps, config: {damping: 13}});
  const exit = useExit(SCENES.fact3.duration);
  const frozen = abs >= FREEZE_START && abs < FREEZE_START + FREEZE_LEN;
  const afterFlash = spring({frame: abs - FLASH_AT, fps, config: {damping: 8, stiffness: 200}});
  return (
    <AbsoluteFill style={{opacity: Math.min(inS * 1.4, 1) * exit}}>
      <BigNumber n={3} />
      <div
        style={{
          ...textBlock,
          transform: `scale(${0.8 + 0.2 * inS + (abs >= FLASH_AT ? 0.06 * (1 - afterFlash) : 0)})`,
        }}
      >
        Космос <Accent>полностью беззвучен</Accent>
      </div>
      <SoundWave />
      {frozen ? (
        <div
          style={{
            position: 'absolute',
            top: 1010,
            left: 0,
            right: 0,
            textAlign: 'center',
            fontFamily: FONT,
            fontWeight: 800,
            fontSize: 40,
            letterSpacing: 10,
            color: 'rgba(255,255,255,0.75)',
          }}
        >
          ТСС…
        </div>
      ) : null}
      <Captions
        text="Звуку нужен воздух, а в вакууме его просто нет"
        delay={FLASH_AT - SCENES.fact3.from + 4}
        framesPerWord={6}
        accentWords={['вакууме']}
      />
    </AbsoluteFill>
  );
};

/* ---------- Вспышка света (поверх всего) ---------- */
export const Flash: React.FC = () => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [FLASH_AT - 2, FLASH_AT, FLASH_AT + 16], [0, 0.95, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  if (o <= 0) return null;
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 50% 45%, rgba(255,255,255,1) 0%, rgba(180,250,255,0.9) 35%, rgba(0,229,255,0.5) 100%)`,
        opacity: o,
        mixBlendMode: 'screen',
      }}
    />
  );
};

/* ---------- 5. Финал (23–25 с) ---------- */
export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame, fps, config: {damping: 9, stiffness: 160}});
  const s2 = spring({frame: frame - 8, fps, config: {damping: 9, stiffness: 160}});
  const pulse = 1 + 0.08 * Math.sin((frame / fps) * Math.PI * 4);
  const ring = (frame % 20) / 20;
  const arrowY = Math.sin((frame / fps) * Math.PI * 4) * 10;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          top: 470,
          left: 50,
          right: 50,
          textAlign: 'center',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: 126,
          lineHeight: 1.05,
          color: WHITE,
          transform: `scale(${s})`,
          textShadow: '0 8px 30px rgba(0,0,0,0.6)',
        }}
      >
        Подпишись
      </div>
      <div
        style={{
          position: 'absolute',
          top: 640,
          left: 60,
          right: 60,
          textAlign: 'center',
          fontFamily: FONT,
          fontWeight: 900,
          fontSize: 80,
          lineHeight: 1.15,
          color: WHITE,
          transform: `scale(${s2})`,
        }}
      >
        завтра ещё <Accent>3 факта</Accent>
      </div>
      {/* Пульсирующая кнопка со стрелкой вниз */}
      <div
        style={{
          position: 'absolute',
          top: 960,
          left: 540 - 130,
          width: 260,
          height: 260,
          transform: `scale(${s2})`,
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: '50%',
            border: `6px solid ${ACCENT}`,
            transform: `scale(${1 + ring * 0.6})`,
            opacity: 1 - ring,
          }}
        />
        <div
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: '50%',
            background: ACCENT,
            transform: `scale(${pulse})`,
            boxShadow: `0 0 ${50 * pulse}px ${ACCENT}, 0 0 120px rgba(0,229,255,0.4)`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <svg width={120} height={120} viewBox="0 0 24 24" style={{transform: `translateY(${arrowY}px)`}}>
            <path d="M12 4v14M5 12l7 7 7-7" stroke="#14002E" strokeWidth={3.2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </div>
    </AbsoluteFill>
  );
};
