import { Easing, interpolate } from "remotion";
import type { SubtitleLine } from "./Subtitles";

/** Формат script.json серии. Все тайминги — в секундах. */
export type EpisodeScript = {
  title: string;
  audio: { voice: string; voiceVolume?: number; music: string; musicVolume?: number };
  subtitles: SubtitleLine[];
  clock: { at: number; time: string }[];
  alarm: { from: number; to: number }[];
};

export const parseTime = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
};

/** Время на будильнике (минуты от полуночи) по ключам из script.json. */
export const clockMinutes = (keys: EpisodeScript["clock"], frame: number, fps: number) => {
  const sec = frame / fps;
  if (sec <= keys[0].at) return parseTime(keys[0].time);
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (sec < b.at) {
      // Ключи ближе 0.25 с — мгновенная смена, иначе плавная «перемотка» с easing
      if (b.at - a.at < 0.25) return parseTime(a.time);
      return Math.floor(
        interpolate(sec, [a.at, b.at], [parseTime(a.time), parseTime(b.time)], {
          easing: Easing.inOut(Easing.cubic),
        }),
      );
    }
  }
  return parseTime(keys[keys.length - 1].time);
};

export const isRinging = (alarm: EpisodeScript["alarm"], frame: number, fps: number) =>
  alarm.some((a) => frame >= a.from * fps && frame < a.to * fps);
