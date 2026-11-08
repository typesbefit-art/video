#!/usr/bin/env node
// One-command pipeline:  npm run build
//   1. edge-tts voice-over per line (cached in tts/)
//   2. timeline from the real audio durations (auto-speeds the voice if > max)
//   3. voice + procedural SFX mix, lip-sync amplitude envelope
//   4. Remotion render (silent, high quality intermediate)
//   5. ffmpeg final encode: H.264 CRF18 yuv420p 60fps + AAC 48 kHz + faststart
//   6. verification (ffprobe + preview frames)
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildTimeline, finalizeTimeline } from './timeline.mjs';
import { SR, decode, writeWav, synthWhoosh, synthCoin, mixInto, dbToGain, softLimit, amplitudeEnvelope } from './audio.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BUILD = path.join(ROOT, 'build');
const OUT = path.join(ROOT, 'out');
const args = new Set(process.argv.slice(2));
const step = (m) => console.log(`\n\x1b[1;36m▶ ${m}\x1b[0m`);
fs.mkdirSync(BUILD, { recursive: true });
fs.mkdirSync(path.join(OUT, 'preview'), { recursive: true });

const script = JSON.parse(fs.readFileSync(path.join(ROOT, 'script.json'), 'utf8'));
const T = script.timing;
const fps = T.fps;

// ---------- 1+2. TTS and timeline ----------
const python = process.env.PYTHON || (spawnSync('python3', ['--version']).status === 0 ? 'python3' : 'python');
const runTTS = (rate) => {
  const a = [path.join(ROOT, 'scripts', 'tts.py')];
  if (rate) a.push('--rate', rate);
  const r = spawnSync(python, a, { stdio: 'inherit', cwd: ROOT });
  if (r.status !== 0) {
    console.error('\nTTS failed. Install edge-tts:  pip install edge-tts   (needs internet access to speech.platform.bing.com)');
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(path.join(ROOT, 'tts', 'manifest.json'), 'utf8'));
};
const pct = (r) => parseFloat(String(r).replace('%', '')) || 0;
const fmtRate = (p) => `${p >= 0 ? '+' : ''}${Math.round(p)}%`;

step('Voice-over (edge-tts, ' + script.voice.name + ')');
let rate = script.voice.rate;
let manifest = runTTS(null);
let tl = buildTimeline(script, manifest, ROOT);
for (let i = 0; i < 3 && T.autoAdjustRate && tl.total > T.maxDurationSec; i++) {
  const speech = tl.lines.reduce((a, l) => a + l.audioDur, 0);
  const overhead = tl.total - speech;
  const need = T.maxDurationSec - 0.25 - overhead;
  const newRate = (1 + pct(rate) / 100) * (speech / need) * 100 - 100 + 1;
  console.log(`  total ${tl.total.toFixed(2)} s > ${T.maxDurationSec} s → speeding voice ${rate} → ${fmtRate(newRate)}`);
  rate = fmtRate(newRate);
  manifest = runTTS(rate);
  tl = buildTimeline(script, manifest, ROOT);
}
if (tl.total > T.maxDurationSec) {
  console.error(`Voice-over is ${tl.total.toFixed(2)} s, longer than ${T.maxDurationSec} s. Shorten the text or raise voice.rate in script.json.`);
  process.exit(1);
}
tl = finalizeTimeline(tl, script);
console.log(`  speech fits: ${tl.total.toFixed(2)} s, ${tl.scenes.length} scenes, ${tl.shots.length} shots`);
tl.scenes.forEach((s) => console.log(`   · ${s.id.padEnd(14)} ${s.start.toFixed(2)}–${s.end.toFixed(2)} s (${(s.end - s.start).toFixed(2)} s)`));

// ---------- 3. Audio ----------
step('Audio mix (voice 100 %, SFX -18 dB)');
const totalSamples = Math.round(tl.total * SR);
const voice = new Float32Array(totalSamples);
for (const l of tl.lines) mixInto(voice, decode(path.join(ROOT, l.mp3)), l.start, 1);
const amplitude = amplitudeEnvelope(voice, fps, tl.durationInFrames);

const whoosh = synthWhoosh();
const coin = synthCoin();
fs.mkdirSync(path.join(BUILD, 'sfx'), { recursive: true });
writeWav(path.join(BUILD, 'sfx', 'whoosh.wav'), whoosh);
writeWav(path.join(BUILD, 'sfx', 'coin.wav'), coin);
const sfxGain = dbToGain(-18);
const mix = Float32Array.from(voice);
for (const c of tl.sfx) mixInto(mix, c.type === 'coin' ? coin : whoosh, c.t, sfxGain);

const musicDir = path.join(ROOT, 'assets', 'music');
const music = fs.existsSync(musicDir) ? fs.readdirSync(musicDir).filter((f) => /\.(mp3|wav|m4a|aac|ogg|flac)$/i.test(f)) : [];
if (music.length) {
  console.log(`  background music: ${music[0]} at -24 dB`);
  const m = decode(path.join(musicDir, music[0]));
  const g = dbToGain(-24);
  const fade = SR * 1.5;
  for (let i = 0; i < totalSamples; i++) {
    const env = Math.min(1, i / fade, (totalSamples - i) / fade);
    mix[i] += m[i % m.length] * g * env;
  }
} else console.log('  no music in assets/music → skipped');
softLimit(mix);
const audioWav = path.join(BUILD, 'audio.wav');
writeWav(audioWav, mix);
console.log(`  ${tl.sfx.length} SFX cues, audio → build/audio.wav`);

// timeline for Remotion
const timeline = {
  fps,
  width: 1080,
  height: 1920,
  durationInFrames: tl.durationInFrames,
  total: tl.total,
  title: script.title,
  scenes: tl.scenes.map(({ lineStarts, ...s }) => s),
  lines: tl.lines.map(({ mp3, ...l }) => l),
  shots: tl.shots,
  subtitles: tl.subtitles,
  words: tl.words,
  amplitude,
};
fs.writeFileSync(path.join(ROOT, 'src', 'generated', 'timeline.json'), JSON.stringify(timeline));
fs.writeFileSync(path.join(OUT, 'timeline.json'), JSON.stringify({ ...timeline, amplitude: undefined }, null, 1));
if (args.has('--no-render')) process.exit(0);

// ---------- 4. Remotion render ----------
step('Remotion render');
const { bundle } = await import('@remotion/bundler');
const { renderMedia, selectComposition } = await import('@remotion/renderer');

function findBrowser() {
  if (process.env.REMOTION_BROWSER_EXECUTABLE) return process.env.REMOTION_BROWSER_EXECUTABLE;
  // Re-use a pre-installed Playwright headless shell if present (offline-friendly);
  // otherwise Remotion downloads its own Chrome Headless Shell.
  const base = '/opt/pw-browsers';
  if (fs.existsSync(base)) {
    for (const d of fs.readdirSync(base).filter((d) => d.startsWith('chromium_headless_shell')).sort().reverse()) {
      const p = path.join(base, d, 'chrome-headless-shell-linux64', 'chrome-headless-shell');
      if (fs.existsSync(p)) return p;
    }
  }
  return null;
}
const browserExecutable = findBrowser();
if (browserExecutable) console.log(`  browser: ${browserExecutable}`);

const serveUrl = await bundle({ entryPoint: path.join(ROOT, 'src', 'index.ts'), onProgress: () => {} });
const inputProps = {};
const composition = await selectComposition({ serveUrl, id: 'Short', inputProps, browserExecutable });
const silent = path.join(BUILD, 'video_silent.mp4');
let lastPct = -1;
const t0 = Date.now();
await renderMedia({
  composition,
  serveUrl,
  codec: 'h264',
  crf: 10,
  pixelFormat: 'yuv420p',
  imageFormat: 'jpeg',
  jpegQuality: 95,
  muted: true,
  outputLocation: silent,
  inputProps,
  browserExecutable,
  concurrency: Math.max(1, Math.min(8, os.cpus().length)),
  chromiumOptions: { gl: 'swangle' },
  onProgress: ({ progress }) => {
    const p = Math.floor(progress * 20) * 5;
    if (p !== lastPct) {
      lastPct = p;
      process.stdout.write(`  ${p}% (${((Date.now() - t0) / 1000).toFixed(0)} s)\n`);
    }
  },
});

// ---------- 5. ffmpeg final assembly ----------
step('ffmpeg final encode → out/video.mp4');
const final = path.join(OUT, 'video.mp4');
execFileSync('ffmpeg', [
  '-y', '-v', 'error', '-stats',
  '-i', silent, '-i', audioWav,
  '-map', '0:v:0', '-map', '1:a:0',
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', String(fps),
  '-profile:v', 'high', '-level', '4.2',
  '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
  '-movflags', '+faststart', '-shortest',
  final,
], { stdio: 'inherit' });

// ---------- 6. Verify ----------
step('Verification');
const v = spawnSync(process.execPath, [path.join(ROOT, 'scripts', 'verify.mjs')], { stdio: 'inherit' });
process.exit(v.status ?? 1);
