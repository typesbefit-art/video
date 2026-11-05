import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import script from "../script.json";
import { AlarmClock } from "../components/AlarmClock";
import { Bublik, BublikMood } from "../components/Bublik";
import { Cat } from "../components/Cat";
import { SafeAudio, SfxCue, SfxTrack } from "../components/SafeAudio";
import { Shake, ShakeHit } from "../components/Shake";
import { Subtitles } from "../components/Subtitles";
import { clockMinutes, isRinging, EpisodeScript } from "../components/script";
import {
  airStretch,
  arc,
  fall,
  Impact,
  impactSquash,
  springAt,
  track,
} from "../components/motion";
import { BEDROOM, BedroomBack, Lamp, Slipper } from "../scenes/Bedroom";

/* ------------------------------------------------------------------ */
/*  Серия 1: «Бублик встаёт с кровати». 1080x1920, 30 fps, 1200 кадров  */
/* ------------------------------------------------------------------ */

export const EP01 = { id: "Ep01", fps: 30, durationInFrames: 1200, width: 1080, height: 1920 };

const S = script as EpisodeScript;

const R = 100; // радиус Бублика
const { BED_TOP, FLOOR, PILLOW_TOP } = BEDROOM;
const REST_X = 540; // где Бублик лежит (кадр 0 == последний кадр)
const EDGE_X = 765; // край кровати
const FALL_X = 840; // куда падает в 10 с
const SLIP = { x: BEDROOM.SLIPPER.x, y: BEDROOM.SLIPPER.y - 30 };
const LAMP_SPOT = { x: 370, y: PILLOW_TOP };
const LAMP_HIT = 30; // угол лампы в момент «бонк»
const CAT_SIT_X = 905;
const CAT_TOP = { x: 885, y: FLOOR - 95 };
const PROUD = { x: 790, y: FLOOR };

const rollRot = (x0: number, x: number) => (((x - x0) / R) * 180) / Math.PI;

/* ---------- ключевые события: из них же строятся squash, shake и звуки ---------- */

const IMPACTS: Impact[] = [
  { frame: 326, strength: 0.42 }, // падение на пол
  { frame: 368, strength: 0.3 }, // обратно на кровать
  { frame: 392, strength: 0.14 },
  { frame: 588, strength: 0.3 }, // на тапок
  { frame: 636, strength: 0.36 }, // обратно на кровать
  { frame: 718, strength: 0.2 }, // на подушку
  { frame: 740, strength: 0.5 }, // лампа: бонк
  { frame: 776, strength: 0.18 },
  { frame: 815, strength: 0.35 }, // на кота
  { frame: 840, strength: 0.38 }, // встал!
  { frame: 1124, strength: 0.32 }, // обратно в кровать
  { frame: 1146, strength: 0.13 },
];

const SHAKES: ShakeHit[] = [
  { frame: 326, intensity: 34 },
  { frame: 368, intensity: 10 },
  { frame: 588, intensity: 12 },
  { frame: 636, intensity: 14 },
  { frame: 740, intensity: 26, duration: 14 },
  { frame: 815, intensity: 16 },
  { frame: 840, intensity: 28, duration: 14 },
  { frame: 1124, intensity: 10 },
];

const SFX: SfxCue[] = [
  ...S.alarm.map((a) => ({ frame: Math.round(a.from * EP01.fps), name: "ring", volume: 0.7 })),
  { frame: 300, name: "whoosh" },
  { frame: 326, name: "hit" },
  { frame: 331, name: "jump" },
  { frame: 368, name: "boing" },
  { frame: 560, name: "jump" },
  { frame: 588, name: "hit" },
  { frame: 592, name: "whoosh" },
  { frame: 636, name: "boing" },
  { frame: 641, name: "hit", volume: 0.5 }, // тапок шлёпнулся обратно
  { frame: 700, name: "jump" },
  { frame: 740, name: "bonk" },
  { frame: 750, name: "boing", volume: 0.6 },
  { frame: 815, name: "hit" },
  { frame: 815, name: "meow" },
  { frame: 818, name: "whoosh" },
  { frame: 840, name: "hit" },
  { frame: 1092, name: "jump" },
  { frame: 1124, name: "boing" },
];

const MOODS: [number, BublikMood][] = [
  [0, "confident"],
  [172, "panic"],
  [368, "dead"],
  [470, "confident"],
  [592, "panic"],
  [636, "dead"],
  [672, "confident"],
  [726, "panic"],
  [740, "dead"],
  [782, "confident"],
  [800, "panic"],
  [848, "proud"],
  [1062, "panic"],
  [1150, "confident"],
];

const moodAt = (f: number): BublikMood => {
  let m: BublikMood = MOODS[0][1];
  for (const [start, mood] of MOODS) if (f >= start) m = mood;
  return m;
};

const LOOK_X: [number, number][] = [
  [0, -0.15], [45, -0.15], [65, 0], [100, 0.8], [180, 0.5], [300, 0.6], [380, 0], [500, 0.3],
  [530, 0.7], [600, 0], [672, 0], [685, -0.8], [740, -0.8], [782, 0.7], [804, 0.4], [848, 0],
  [1040, 0], [1056, -0.5], [1124, -0.3], [1150, 0], [1170, 0], [1190, -0.15],
];
const LOOK_Y: [number, number][] = [
  [0, -0.8], [45, -0.8], [65, 0], [100, 0.2], [180, 0.9], [300, 1], [380, 0], [500, -0.4],
  [530, 0.7], [600, 0], [672, 0], [685, -0.6], [740, -0.6], [782, 0.6], [804, 1], [848, 0],
  [1040, 0], [1056, -1], [1124, -0.5], [1150, 0], [1170, 0], [1190, -0.8],
];

/* ---------- позиция Бублика по кадрам ---------- */

type Pose = { x: number; y: number; rot: number; sx: number; sy: number; ground?: number };

/** 3–10 с: катится к краю и застревает, раскачиваясь. */
const teeter = (f: number, fps: number): Pose => {
  const p = springAt(f, 95, fps, { damping: 15, stiffness: 40, mass: 1.2 });
  let x = REST_X + (EDGE_X - REST_X) * p;
  let rot = rollRot(REST_X, x);
  const env = interpolate(f, [150, 185, 270, 300], [0, 1, 1, 1.8], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const wob = Math.sin((f - 150) * 0.33) * env;
  x += 9 * wob;
  rot += 16 * wob;
  return { x, y: BED_TOP + 5 * Math.abs(wob), rot, sx: 1, sy: 1 };
};

const anticipation = (f: number, start: number, release: number, amount: number) =>
  track(f, [
    [start, 0],
    [release - 4, amount],
    [release, 0],
  ]);

const pose = (f: number, fps: number): Pose => {
  const rest: Pose = { x: REST_X, y: BED_TOP, rot: 0, sx: 1, sy: 1 };

  // 0–3 с: лежит
  if (f < 95) return rest;

  // 3–10 с: катится и застревает
  if (f < 300) return teeter(f, fps);

  // 10–18 с: падает, отскакивает на кровать
  const T = teeter(300, fps);
  if (f < 326) {
    const p = fall(f, 300, 326, T, { x: FALL_X, y: FLOOR });
    return { x: p.x, y: p.y, rot: T.rot + 100 * p.t * p.t, ...airStretch(p.t, 0.22) };
  }
  if (f < 331) return { x: FALL_X, y: FLOOR, rot: T.rot + 100, sx: 1, sy: 1 };
  if (f < 368) {
    const a = arc(f, 331, 368, { x: FALL_X, y: FLOOR }, { x: REST_X, y: BED_TOP }, 480);
    const rot = interpolate(a.t, [0, 1], [T.rot + 100, -360], { easing: Easing.inOut(Easing.quad) });
    return { x: a.x, y: a.y, rot, ...airStretch(a.speed) };
  }
  if (f < 374) return rest;
  if (f < 392) {
    const a = arc(f, 374, 392, rest, rest, 70);
    return { ...rest, y: a.y, ...airStretch(a.speed, 0.1) };
  }
  if (f < 540) return rest;

  // 18–23 с: попытка 1 — тапок
  if (f < 560) {
    const k = anticipation(f, 540, 560, 0.24);
    return { ...rest, sx: 1 + 0.8 * k, sy: 1 - k };
  }
  if (f < 588) {
    const a = arc(f, 560, 588, rest, SLIP, 260);
    return { x: a.x, y: a.y, rot: track(f, [[560, 0], [588, 25]]), ...airStretch(a.speed), ground: FLOOR };
  }
  if (f < 592) return { x: SLIP.x, y: SLIP.y, rot: 25, sx: 1, sy: 1, ground: FLOOR };
  if (f < 636) {
    const a = arc(f, 592, 636, SLIP, rest, 620);
    const rot = interpolate(a.t, [0, 1], [25, -720], { easing: Easing.inOut(Easing.cubic) });
    return { x: a.x, y: a.y, rot, ...airStretch(a.speed) };
  }
  if (f < 690) return rest;

  // 23–26.3 с: попытка 2 — лампа
  if (f < 700) {
    const k = anticipation(f, 690, 700, 0.2);
    return { ...rest, sx: 1 + 0.8 * k, sy: 1 - k };
  }
  if (f < 718) {
    const a = arc(f, 700, 718, rest, LAMP_SPOT, 160);
    return { x: a.x, y: a.y, rot: track(f, [[700, 0], [718, -10]]), ...airStretch(a.speed), ground: BED_TOP };
  }
  if (f < 750) return { ...LAMP_SPOT, rot: -10, sx: 1, sy: 1, ground: PILLOW_TOP };
  if (f < 776) {
    const a = arc(f, 750, 776, LAMP_SPOT, rest, 110);
    return { x: a.x, y: a.y, rot: -10 + 10 * a.t - 18 * Math.sin(Math.PI * a.t), ...airStretch(a.speed, 0.12) };
  }
  if (f < 790) return rest;

  // 26.3–28 с: попытка 3 — кот (самая быстрая)
  if (f < 804) {
    const x = track(f, [[790, REST_X], [804, EDGE_X]], Easing.in(Easing.quad));
    return { x, y: BED_TOP, rot: rollRot(REST_X, x), sx: 1, sy: 1 };
  }
  const r0 = rollRot(REST_X, EDGE_X);
  if (f < 815) {
    const p = fall(f, 804, 815, { x: EDGE_X, y: BED_TOP }, CAT_TOP);
    return { x: p.x, y: p.y, rot: r0 + 80 * p.t, ...airStretch(p.t, 0.2), ground: FLOOR };
  }
  if (f < 818) return { ...CAT_TOP, rot: r0 + 80, sx: 1, sy: 1, ground: FLOOR };
  if (f < 840) {
    const a = arc(f, 818, 840, CAT_TOP, PROUD, 420);
    const rot = interpolate(a.t, [0, 1], [r0 + 80, -360], { easing: Easing.inOut(Easing.cubic) });
    return { x: a.x, y: a.y, rot, ...airStretch(a.speed), ground: FLOOR };
  }

  // 28–36 с: стоит и гордится
  if (f < 1080) {
    const puff = springAt(f, 862, fps, { damping: 9, stiffness: 90 });
    const fade = interpolate(f, [1050, 1078], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    return {
      ...PROUD,
      rot: 4 * Math.sin((f - 862) / 14) * puff * fade,
      sx: 1 + 0.06 * puff * fade,
      sy: 1 + 0.09 * puff * fade,
    };
  }

  // 36–40 с: падает обратно в кровать → кадр совпадает с кадром 0
  if (f < 1092) {
    const k = anticipation(f, 1080, 1092, 0.22);
    return { ...PROUD, rot: 0, sx: 1 + 0.8 * k, sy: 1 - k };
  }
  if (f < 1124) {
    const a = arc(f, 1092, 1124, PROUD, rest, 380);
    const rot = interpolate(a.t, [0, 1], [0, -360], { easing: Easing.inOut(Easing.cubic) });
    return { x: a.x, y: a.y, rot, ...airStretch(a.speed) };
  }
  if (f < 1130) return rest;
  if (f < 1146) {
    const a = arc(f, 1130, 1146, rest, rest, 55);
    return { ...rest, y: a.y, ...airStretch(a.speed, 0.08) };
  }
  return rest;
};

/** Дыхание во сне — период 60 кадров, чтобы кадр 0 и 1199 совпадали. */
const breathing = (f: number) => {
  const env =
    f < 95
      ? interpolate(f, [80, 95], [1, 0], { extrapolateLeft: "clamp" })
      : interpolate(f, [1146, 1170], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return 1 + 0.015 * env * Math.sin((f / 60) * Math.PI * 2);
};

const groundFor = (x: number, y: number) =>
  x > BEDROOM.BED_LEFT && x < BEDROOM.BED_RIGHT && y <= BED_TOP + 1 ? BED_TOP : FLOOR;

/* ---------- реквизит ---------- */

const lampAngle = (f: number, fps: number) => {
  if (f < 718) return 0;
  if (f < 728) return 5 * Math.sin((f - 718) * 1.1) * interpolate(f, [718, 722, 728], [0, 1, 0.6]);
  if (f < 740) {
    const t = (f - 728) / 12;
    return 3 + (LAMP_HIT - 3) * t * t; // падает с ускорением
  }
  return LAMP_HIT * (1 - springAt(f, 742, fps, { damping: 6, stiffness: 120 }));
};

const slipperState = (f: number, fps: number) => {
  const squash = impactSquash(f, [{ frame: 588, strength: 0.4 }, { frame: 641, strength: 0.25 }], fps);
  if (f >= 592 && f < 641) {
    const t = (f - 592) / (641 - 592);
    return {
      dy: -4 * 560 * t * (1 - t),
      rotation: interpolate(t, [0, 1], [0, -720], { easing: Easing.inOut(Easing.cubic) }),
      scaleY: 1,
    };
  }
  return { dy: 0, rotation: 0, scaleY: squash.sy };
};

const catState = (f: number, fps: number) => {
  if (f < 770 || f > 852) return null;
  if (f < 815) {
    const x = track(f, [[770, 1260], [798, CAT_SIT_X]], Easing.out(Easing.cubic));
    const walking = f < 798 ? Math.abs(Math.sin(f * 0.7)) * 10 : 0;
    return { x, y: FLOOR - walking, sx: 1, sy: 1, mood: "sleep" as const };
  }
  const sq = impactSquash(f, [{ frame: 815, strength: 0.45 }], fps);
  if (f < 820) return { x: CAT_SIT_X, y: FLOOR, sx: sq.sx, sy: sq.sy, mood: "startled" as const };
  const a = arc(f, 820, 852, { x: CAT_SIT_X, y: FLOOR }, { x: 1320, y: FLOOR }, 320);
  return { x: a.x, y: a.y, ...airStretchToScale(a.speed), mood: "startled" as const };
};
const airStretchToScale = (speed: number) => {
  const s = airStretch(speed, 0.25);
  return { sx: s.sx, sy: s.sy };
};

/* ---------- сцена ---------- */

export const Ep01: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const p = pose(frame, fps);
  const sq = impactSquash(frame, IMPACTS, fps);
  const breath = breathing(frame);
  const minutes = clockMinutes(S.clock, frame, fps);
  const cat = catState(frame, fps);
  const slipper = slipperState(frame, fps);

  return (
    <AbsoluteFill style={{ backgroundColor: "#7FD1C7" }}>
      <Shake hits={SHAKES}>
        <BedroomBack minutes={minutes} />
        <Slipper {...slipper} />
        {cat && (
          <svg width={1080} height={1920} style={{ position: "absolute", overflow: "visible" }}>
            <Cat x={cat.x} y={cat.y} scaleX={cat.sx} scaleY={cat.sy} mood={cat.mood} />
          </svg>
        )}
        <Bublik
          x={p.x}
          y={p.y}
          rotation={p.rot}
          scaleX={p.sx * sq.sx * (2 - breath)}
          scaleY={p.sy * sq.sy * breath}
          mood={moodAt(frame)}
          lookAt={{ x: track(frame, LOOK_X), y: track(frame, LOOK_Y) }}
          groundY={p.ground ?? groundFor(p.x, p.y)}
          size={R}
        />
        <Lamp angle={lampAngle(frame, fps)} />
        <svg width={1080} height={1920} style={{ position: "absolute", overflow: "visible" }}>
          <AlarmClock x={540} y={300} minutes={minutes} ringing={isRinging(S.alarm, frame, fps)} />
        </svg>
      </Shake>

      <Subtitles lines={S.subtitles} />

      <SafeAudio file={S.audio.voice} volume={S.audio.voiceVolume ?? 1} />
      <SafeAudio file={S.audio.music} volume={S.audio.musicVolume ?? 0.15} loop />
      <SfxTrack cues={SFX} />
    </AbsoluteFill>
  );
};
