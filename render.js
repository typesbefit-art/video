#!/usr/bin/env node
// Deterministic frame-by-frame render of avatar.svg -> avatar.mp4 + avatar.png
// Usage: node render.js [--crf 22] [--png-time 1.0]
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : def; };

const DIR = __dirname;
const SVG = path.join(DIR, 'avatar.svg');
const FRAMES = path.join(DIR, 'frames');
const SIZE = 800, FPS = 30, DURATION = 6;
const N = FPS * DURATION;                 // 180 frames; frame 180 == frame 0, so it is not rendered
const CRF = opt('--crf', '22');
const PNG_TIME = parseFloat(opt('--png-time', '1.0')); // seconds, still frame for avatar.png
const MAX_BYTES = 2 * 1024 * 1024;

(async () => {
  fs.rmSync(FRAMES, { recursive: true, force: true });
  fs.mkdirSync(FRAMES);

  const svg = fs.readFileSync(SVG, 'utf8')
    .replace(/<svg([^>]*?)\swidth="[^"]*"/, '<svg$1')
    .replace(/<svg([^>]*?)\sheight="[^"]*"/, '<svg$1')
    .replace('<svg', `<svg width="${SIZE}" height="${SIZE}"`);
  const html = `<!doctype html><html><head><style>
    html,body{margin:0;padding:0;background:#0A1224;overflow:hidden}
    svg{display:block}</style></head><body>${svg}</body></html>`;

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: SIZE, height: SIZE }, deviceScaleFactor: 1 });
  await page.setContent(html, { waitUntil: 'load' });

  const count = await page.evaluate(() => {
    const a = document.getAnimations();
    a.forEach(x => x.pause());
    return a.length;
  });
  console.log(`animations found: ${count}`);

  const seek = (ms) => page.evaluate((t) => {
    document.getAnimations().forEach(a => { a.currentTime = t; });
  }, ms);

  for (let f = 0; f < N; f++) {
    await seek(f / FPS * 1000);
    await page.screenshot({ path: path.join(FRAMES, `f${String(f).padStart(4, '0')}.png`) });
    if (f % 30 === 0) process.stdout.write(`frame ${f}/${N}\n`);
  }

  // Static PNG 640x640
  await page.setViewportSize({ width: 640, height: 640 });
  await page.evaluate(() => {
    const s = document.querySelector('svg'); s.setAttribute('width', 640); s.setAttribute('height', 640);
  });
  await seek(PNG_TIME * 1000);
  await page.screenshot({ path: path.join(DIR, 'avatar.png') });
  await browser.close();

  const out = path.join(DIR, 'avatar.mp4');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error',
    '-framerate', String(FPS), '-i', path.join(FRAMES, 'f%04d.png'),
    '-c:v', 'libx264', '-preset', 'slow', '-crf', CRF, '-pix_fmt', 'yuv420p',
    '-an', '-movflags', '+faststart', out], { stdio: 'inherit' });

  const size = fs.statSync(out).size;
  console.log(`avatar.mp4: ${(size / 1024).toFixed(1)} KB (CRF ${CRF})`);
  if (size > MAX_BYTES) console.warn('WARNING: >2 MB, rerun with a higher --crf');
  fs.rmSync(FRAMES, { recursive: true, force: true });
})().catch(e => { console.error(e); process.exit(1); });
