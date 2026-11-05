// Рендер: node scripts/render.mjs  →  output/space.mp4
import {execSync} from 'node:child_process';
import {existsSync} from 'node:fs';

execSync('node scripts/prepare.mjs', {stdio: 'inherit'});
const music = existsSync('public/music.mp3');
const browser = process.env.REMOTION_CHROME ?? (existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : '');
const args = [
  'npx remotion render src/index.ts SpaceFacts output/space.mp4',
  '--codec=h264 --crf=18 --pixel-format=yuv420p',
  music ? '' : '--muted',
  browser ? `--browser-executable=${browser}` : '',
].join(' ');
console.log('▶', args);
execSync(args, {stdio: 'inherit'});
