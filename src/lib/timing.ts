import scenesFile from '../../scenes.json';
import wordsFile from '../../words.json';

export type Interval = {start: number; end: number};

export type SceneData = {
  id: string;
  start: number;
  end: number;
  title: string;
  text: string;
  image: string | null;
  speech?: Interval[];
};

export type Word = {
  text: string;
  start: number; // сек, абсолютное время
  end: number;
  scene: number;
  keyword: boolean;
};

export type Chunk = {words: Word[]; start: number; end: number; scene: number};

export const FPS: number = scenesFile.fps;
export const DURATION_IN_FRAMES: number = scenesFile.durationInFrames;
export const SCENES: SceneData[] = scenesFile.scenes as SceneData[];

/** Нормализация для сравнения слов: нижний регистр, ё→е, без пунктуации. */
export const normalize = (w: string) =>
  w.toLowerCase().replace(/ё/g, 'е').replace(/[^a-zа-я0-9-]/g, '');

const KEYWORDS = /^(ядерн|вспышк|голод|зим|десятилет)/;
export const isKeyword = (w: string) => KEYWORDS.test(normalize(w));

export const secToFrame = (s: number) => Math.round(s * FPS);

export const sceneFrames = (i: number) => {
  const from = secToFrame(SCENES[i].start);
  const to = i === SCENES.length - 1 ? DURATION_IN_FRAMES : secToFrame(SCENES[i].end);
  return {from, duration: Math.max(1, to - from)};
};

// ------------------------------------------------------------------ токены
type Token = {text: string; scene: number; sentenceEnd: boolean; comma: boolean};

const tokenize = (text: string, scene: number): Token[] => {
  const raw = text.split(/\s+/).filter(Boolean);
  const tokens: Token[] = [];
  for (const r of raw) {
    // одиночное тире приклеиваем к предыдущему слову: «угроза —»
    if (/^[—–-]+$/.test(r) && tokens.length) {
      tokens[tokens.length - 1].text += ' ' + r;
      tokens[tokens.length - 1].comma = true;
      continue;
    }
    tokens.push({
      text: r,
      scene,
      sentenceEnd: /[.?!…]$/.test(r),
      comma: /[,:;]$/.test(r),
    });
  }
  return tokens;
};

const weight = (t: Token, withPauses: boolean) => {
  const letters = normalize(t.text).length || 1;
  if (!withPauses) return letters + 1; // +1 — межсловный промежуток
  return letters + 1 + (t.sentenceEnd ? 4 : t.comma ? 2 : 0);
};

/** Раскладывает токены по отрезку пропорционально длине. */
const spread = (tokens: Token[], range: Interval, withPauses: boolean): Word[] => {
  const weights = tokens.map((t) => weight(t, withPauses));
  const total = weights.reduce((a, b) => a + b, 0);
  const len = range.end - range.start;
  let acc = 0;
  return tokens.map((t, i) => {
    const start = range.start + (acc / total) * len;
    acc += weights[i];
    const end = range.start + (acc / total) * len;
    return {text: t.text, start, end, scene: t.scene, keyword: isKeyword(t.text)};
  });
};

/**
 * Запасной вариант: слова распределяются пропорционально числу символов.
 * Если align.ts нашёл отрезки речи и их столько же, сколько предложений, —
 * каждое предложение кладётся в свой отрезок. Иначе слова раскладываются
 * по «склеенной» речи сцены, паузы пропускаются.
 */
const proportionalWords = (scene: SceneData, index: number): Word[] => {
  const tokens = tokenize(scene.text, index);
  const speech = scene.speech?.length ? scene.speech : [{start: scene.start, end: scene.end}];

  const sentences: Token[][] = [];
  let cur: Token[] = [];
  for (const t of tokens) {
    cur.push(t);
    if (t.sentenceEnd) {
      sentences.push(cur);
      cur = [];
    }
  }
  if (cur.length) sentences.push(cur);

  if (scene.speech && speech.length === sentences.length) {
    return sentences.flatMap((s, i) => spread(s, speech[i], false));
  }

  // склеиваем отрезки речи в одну временную шкалу
  const total = speech.reduce((a, s) => a + (s.end - s.start), 0);
  const virtual = spread(tokens, {start: 0, end: total}, true);
  const toReal = (v: number) => {
    let left = v;
    for (const s of speech) {
      const len = s.end - s.start;
      if (left <= len + 1e-6) return s.start + left;
      left -= len;
    }
    return speech[speech.length - 1].end;
  };
  return virtual.map((w) => ({...w, start: toReal(w.start), end: toReal(w.end)}));
};

// ------------------------------------------------------------------ Whisper
type WhisperWord = {word: string; start: number; end: number};

/** Сопоставляет слова сценария со словами Whisper (текст берём из сценария). */
const whisperWords = (whisper: WhisperWord[]): Word[] | null => {
  const tokens = SCENES.flatMap((s, i) => tokenize(s.text, i));
  const ww = whisper.filter((w) => normalize(w.word).length > 0);
  if (!ww.length) return null;

  const times: (Interval | null)[] = tokens.map(() => null);
  let j = 0;
  for (let i = 0; i < tokens.length && j < ww.length; i++) {
    const n = normalize(tokens[i].text.split(' ')[0]);
    for (let k = j; k < Math.min(ww.length, j + 6); k++) {
      const m = normalize(ww[k].word);
      if (m === n || (n.length > 4 && m.slice(0, 5) === n.slice(0, 5))) {
        times[i] = {start: ww[k].start, end: ww[k].end};
        j = k + 1;
        break;
      }
    }
  }
  const matched = times.filter(Boolean).length;
  if (matched < tokens.length * 0.6) return null; // слишком плохое совпадение

  // интерполяция несопоставленных слов между соседями
  for (let i = 0; i < tokens.length; i++) {
    if (times[i]) continue;
    let a = i - 1;
    while (a >= 0 && !times[a]) a--;
    let b = i + 1;
    while (b < tokens.length && !times[b]) b++;
    const from = a >= 0 ? times[a]!.end : SCENES[tokens[i].scene].start;
    const to = b < tokens.length ? times[b]!.start : SCENES[tokens[i].scene].end;
    const span = b - a - 1;
    const pos = i - a - 1;
    const step = (to - from) / span;
    times[i] = {start: from + step * pos, end: from + step * (pos + 1)};
  }
  return tokens.map((t, i) => ({
    text: t.text,
    start: times[i]!.start,
    end: times[i]!.end,
    scene: t.scene,
    keyword: isKeyword(t.text),
  }));
};

// ------------------------------------------------------------------ публичное API
let cachedWords: Word[] | null = null;

export const getWords = (): Word[] => {
  if (cachedWords) return cachedWords;
  const fromWhisper =
    wordsFile.words.length > 0 ? whisperWords(wordsFile.words as WhisperWord[]) : null;
  cachedWords = fromWhisper ?? SCENES.flatMap((s, i) => proportionalWords(s, i));
  return cachedWords;
};

export const subtitleSource = () =>
  wordsFile.words.length > 0 && whisperWords(wordsFile.words as WhisperWord[])
    ? wordsFile.source
    : 'proportional';

/** Группы по 2–4 слова в стиле Shorts. Группа не пересекает границу сцены. */
export const getChunks = (): Chunk[] => {
  const words = getWords();
  const chunks: Chunk[] = [];
  let cur: Word[] = [];
  const chars = (ws: Word[]) => ws.reduce((a, w) => a + w.text.length + 1, 0);

  const flush = () => {
    if (!cur.length) return;
    chunks.push({words: cur, start: cur[0].start, end: cur[cur.length - 1].end, scene: cur[0].scene});
    cur = [];
  };

  words.forEach((w, i) => {
    if (cur.length && cur[0].scene !== w.scene) flush();
    cur.push(w);
    const next = words[i + 1];
    const endSentence = /[.?!…]$/.test(w.text);
    const pause = /[,:;—]$/.test(w.text);
    if (
      cur.length >= 4 ||
      (cur.length >= 2 && chars(cur) >= 17) ||
      endSentence ||
      (pause && cur.length >= 2) ||
      !next ||
      next.scene !== w.scene
    ) {
      flush();
    }
  });

  // не оставляем одиночное слово, если его можно приклеить к предыдущей группе
  for (let i = chunks.length - 1; i > 0; i--) {
    const c = chunks[i];
    const p = chunks[i - 1];
    if (
      c.words.length === 1 &&
      p.scene === c.scene &&
      p.words.length < 4 &&
      !/[.?!…]$/.test(p.words[p.words.length - 1].text) &&
      chars([...p.words, ...c.words]) <= 24
    ) {
      p.words.push(...c.words);
      p.end = c.end;
      chunks.splice(i, 1);
    }
  }

  // показываем группу до начала следующей (но не дольше 0.5 сек после последнего слова)
  chunks.forEach((c, i) => {
    const next = chunks[i + 1];
    c.end = next ? Math.min(next.start, c.end + 0.5) : c.end + 0.5;
  });
  return chunks;
};

/**
 * Кадр (относительно начала сцены), на котором звучит слово, начинающееся с prefix.
 * Используется для синхронизации анимаций с голосом: иконки «свет/связь/интернет»,
 * надписи «ЯДЕРНАЯ ЗИМА», «ГОЛОД», кнопка «ПОДПИШИСЬ».
 */
export const wordFrame = (sceneIndex: number, prefix: string, fallbackSec = 0): number => {
  const p = normalize(prefix);
  const w = getWords().find((x) => x.scene === sceneIndex && normalize(x.text).startsWith(p));
  const sceneStart = SCENES[sceneIndex].start;
  return secToFrame((w ? w.start : sceneStart + fallbackSec) - sceneStart);
};
