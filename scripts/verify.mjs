#!/usr/bin/env node
// Checks out/video.mp4 with ffprobe and extracts 3 preview frames
// (beginning / middle / end, each taken while a subtitle is on screen).
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const video = path.join(ROOT, 'out', 'video.mp4');
const prevDir = path.join(ROOT, 'out', 'preview');
fs.mkdirSync(prevDir, { recursive: true });

const probe = JSON.parse(
  execFileSync('ffprobe', ['-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', video]).toString(),
);
const v = probe.streams.find((s) => s.codec_type === 'video');
const a = probe.streams.find((s) => s.codec_type === 'audio');
const [num, den] = v.r_frame_rate.split('/').map(Number);
const fps = num / den;
const dur = parseFloat(probe.format.duration);

const checks = [
  ['Resolution 1080x1920', v.width === 1080 && v.height === 1920, `${v.width}x${v.height}`],
  ['60 fps', Math.abs(fps - 60) < 0.01, `${v.r_frame_rate} (${v.nb_frames ?? '?'} frames)`],
  ['Duration 58–60 s', dur >= 58 && dur <= 60, `${dur.toFixed(3)} s`],
  ['Video H.264 yuv420p', v.codec_name === 'h264' && v.pix_fmt === 'yuv420p', `${v.codec_name} ${v.profile} ${v.pix_fmt}`],
  ['Audio track AAC 48 kHz', !!a && a.codec_name === 'aac' && a.sample_rate === '48000', a ? `${a.codec_name} ${a.sample_rate} Hz ${a.channels}ch` : 'missing'],
];

// faststart: moov atom must precede mdat
const head = fs.readFileSync(video).subarray(0, 1 << 20);
const moov = head.indexOf('moov');
const mdat = head.indexOf('mdat');
checks.push(['+faststart (moov before mdat)', moov >= 0 && (mdat < 0 || moov < mdat), `moov@${moov} mdat@${mdat}`]);

// loudness of the final mix
const loud = String(
  spawnSync('ffmpeg', ['-hide_banner', '-nostats', '-i', video, '-af', 'ebur128=peak=true', '-f', 'null', '-'], { encoding: 'utf8' }).stderr || '',
);

// preview frames while a subtitle is visible
const tl = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', 'timeline.json'), 'utf8'));
const subs = tl.subtitles;
const midOf = (c) => (c.words.at(-1).start + c.words.at(-1).end) / 2;
const pickNear = (t) => subs.reduce((best, c) => (Math.abs(midOf(c) - t) < Math.abs(midOf(best) - t) ? c : best), subs[0]);
const picks = [
  ['01_start', midOf(subs[1] ?? subs[0])],
  ['02_middle', midOf(pickNear(dur / 2))],
  ['03_end', midOf(subs.at(-1))],
];
for (const [name, t] of picks) {
  const out = path.join(prevDir, `${name}.png`);
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-ss', t.toFixed(3), '-i', video, '-frames:v', '1', out]);
  // same frame with the Shorts/Reels safe-zone guides (y=1500, x=120/960)
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', out, '-vf',
    'drawbox=x=0:y=1500:w=1080:h=420:color=red@0.35:t=fill,drawbox=x=0:y=0:w=120:h=1920:color=red@0.35:t=fill,drawbox=x=960:y=0:w=120:h=1920:color=red@0.35:t=fill',
    path.join(prevDir, `${name}_safezone.png`)]);
}

console.log('\n=== Verification: out/video.mp4 ===');
let ok = true;
for (const [name, pass, info] of checks) {
  ok &&= pass;
  console.log(`${pass ? '✅' : '❌'} ${name.padEnd(30)} ${info}`);
}
const summary = loud.slice(loud.lastIndexOf('Summary:'));
const I = summary.match(/I:\s+(-?[\d.]+) LUFS/)?.[1];
const P = summary.match(/Peak:\s+(-?[\d.]+) dBFS/)?.[1];
if (I) console.log(`ℹ️  Loudness: ${I} LUFS integrated, true peak ${P ?? '?'} dBFS`);
console.log(`ℹ️  Size: ${(fs.statSync(video).size / 1e6).toFixed(1)} MB`);
console.log(`🖼  Previews: ${picks.map(([n, t]) => `out/preview/${n}.png @${t.toFixed(2)}s`).join(', ')} (+ *_safezone.png)`);
console.log(ok ? '\nAll checks passed.' : '\nSome checks FAILED.');
process.exit(ok ? 0 : 1);
