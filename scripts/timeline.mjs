// Builds the timeline (scenes, shots, subtitle chunks, SFX cues) from the
// real TTS durations. Scene length follows audio length, never the other way.
import { execFileSync } from 'node:child_process';

export const probeDuration = (file) =>
  parseFloat(
    execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file])
      .toString()
      .trim(),
  );

const isSentenceEnd = (w) => /[.!?…]$/.test(w);
const isClauseEnd = (w) => /[,:;—]$/.test(w);

// Group words into short readable subtitle chunks (≤3 words / ≤20 chars).
function chunkWords(words) {
  const chunks = [];
  let cur = [];
  const flush = () => {
    if (cur.length) chunks.push(cur);
    cur = [];
  };
  for (const w of words) {
    const len = cur.reduce((a, x) => a + x.display.length + 1, 0) + w.display.length;
    if (cur.length && (cur.length >= 3 || len > 20)) flush();
    cur.push(w);
    if (isSentenceEnd(w.display) || isClauseEnd(w.display)) flush();
  }
  flush();
  return chunks;
}

// Split a scene into camera shots of 3–5 s, cutting right before a word or line.
function splitShots(scene, words, lineStarts) {
  const { start, end } = scene;
  const cands = [
    ...lineStarts.map((t) => ({ t: t - 0.06, w: 0.6 })),
    ...words.map((w, i) => ({ t: w.start - 0.04, w: i > 0 && /[.!?…:]$/.test(words[i - 1].text) ? 0.45 : 0 })),
  ].filter((c) => c.t > start && c.t < end);
  const cuts = [start];
  let s = start;
  while (end - s > 4.6) {
    const remaining = end - s;
    // aim for even-ish shots of ~4 s
    const n = Math.max(2, Math.round(remaining / 3.5));
    const target = Math.min(4.5, Math.max(3.1, remaining / n));
    let best = null;
    for (const c of cands) {
      const len = c.t - s;
      if (len < 3 || len > 5) continue;
      if (end - c.t < 3) continue;
      const score = Math.abs(len - target) - c.w;
      if (!best || score < best.score) best = { ...c, score };
    }
    if (!best) break;
    cuts.push(best.t);
    s = best.t;
  }
  cuts.push(end);
  return cuts.slice(0, -1).map((t, i) => ({ start: t, end: cuts[i + 1] }));
}

export function buildTimeline(script, manifest, rootDir) {
  const T = script.timing;
  const scenes = [];
  const lines = [];
  const words = [];
  let cursor = 0;
  manifest.scenes.forEach((ms, si) => {
    const src = script.scenes[si];
    const scene = { id: src.id, visual: src.visual || src.id, index: si, start: cursor, labels: src.labels || {} };
    let t = cursor + T.sceneLeadInSec;
    const lineStarts = [];
    ms.lines.forEach((l, li) => {
      const dur = probeDuration(`${rootDir}/${l.mp3}`);
      // trim edge-tts' leading silence so lines flow tightly
      const lead = Math.max(0, Math.min(0.08, (l.words[0]?.start ?? 0) - 0.02));
      const lineStart = t - lead;
      lines.push({ scene: si, index: li, speaker: l.speaker, mp3: l.mp3, start: lineStart, audioDur: dur, end: lineStart + dur });
      lineStarts.push(t);
      for (const w of l.words) {
        words.push({ text: w.display, start: lineStart + w.start, end: lineStart + w.end, scene: si, line: lines.length - 1, speaker: l.speaker });
      }
      const lastWordEnd = lineStart + (l.words.at(-1)?.end ?? dur);
      t = Math.min(lineStart + dur, lastWordEnd + 0.12) + (li < ms.lines.length - 1 ? T.gapBetweenLinesSec : 0);
    });
    scene.end = t + T.sceneTailSec;
    scene.lineStarts = lineStarts;
    cursor = scene.end;
    scenes.push(scene);
  });
  return { scenes, lines, words, total: cursor };
}

// Stretch scene tails so the video is at least minDurationSec, then derive
// shots, subtitle chunks and sound cues. Everything is in seconds.
export function finalizeTimeline(tl, script) {
  const T = script.timing;
  const fps = T.fps;
  let extra = Math.max(0, T.minDurationSec + 0.2 - tl.total);
  if (extra > 0) {
    // give the padding to scene tails (half of it to the last scene)
    const shift = [];
    let acc = 0;
    tl.scenes.forEach((s, i) => {
      const add = i === tl.scenes.length - 1 ? extra / 2 : extra / 2 / (tl.scenes.length - 1);
      shift.push(acc);
      s.start += acc;
      acc += add;
      s.end += acc;
    });
    for (const l of tl.lines) { l.start += shift[l.scene]; l.end += shift[l.scene]; }
    for (const w of tl.words) { w.start += shift[w.scene]; w.end += shift[w.scene]; }
    tl.scenes.forEach((s, i) => (s.lineStarts = s.lineStarts.map((t) => t + shift[i])));
    tl.total = tl.scenes.at(-1).end;
  }

  // quantise to frames
  const q = (t) => Math.round(t * fps) / fps;
  tl.scenes.forEach((s) => { s.start = q(s.start); s.end = q(s.end); });
  tl.total = tl.scenes.at(-1).end;
  tl.durationInFrames = Math.round(tl.total * fps);

  const shots = [];
  tl.scenes.forEach((s) => {
    const sw = tl.words.filter((w) => w.scene === s.index);
    splitShots(s, sw, s.lineStarts).forEach((sh, k) => {
      shots.push({ scene: s.index, visual: s.visual, k, start: q(sh.start), end: q(sh.end), global: shots.length });
    });
  });
  tl.shots = shots;

  const chunks = [];
  tl.lines.forEach((l, li) => {
    const lw = tl.words.filter((w) => w.line === li);
    for (const c of chunkWords(lw.map((w) => ({ ...w, display: w.text })))) {
      chunks.push({ words: c.map((w) => ({ text: w.text, start: w.start, end: w.end })), start: c[0].start, end: c.at(-1).end, speaker: l.speaker });
    }
  });
  chunks.forEach((c, i) => {
    const next = chunks[i + 1];
    c.hideAt = next ? Math.min(next.start, c.end + 0.6) : c.end + 0.6;
  });
  tl.subtitles = chunks;

  // SFX cues: whoosh on every cut, coin ding when the coin starts talking
  // at a scene start and on the last scene's checklist beats.
  const sfx = [];
  shots.forEach((sh, i) => { if (i > 0) sfx.push({ type: 'whoosh', t: Math.max(0, sh.start - 0.12) }); });
  tl.lines.forEach((l, i) => {
    const prev = tl.lines[i - 1];
    if (l.speaker === 'coin' && (!prev || prev.speaker !== 'coin')) sfx.push({ type: 'coin', t: l.start });
  });
  sfx.push({ type: 'coin', t: 0.05 });
  tl.sfx = sfx.sort((a, b) => a.t - b.t);
  return tl;
}
