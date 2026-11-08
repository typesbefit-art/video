// Dev helper: render individual frames.  node scripts/stills.mjs <outDir> <sec> [sec...]
import path from 'node:path';
import fs from 'node:fs';
import { bundle } from '@remotion/bundler';
import { renderStill, selectComposition } from '@remotion/renderer';
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const [outDir, ...secs] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const be = process.env.REMOTION_BROWSER_EXECUTABLE || fs.readdirSync('/opt/pw-browsers').filter(d=>d.startsWith('chromium_headless_shell')).map(d=>`/opt/pw-browsers/${d}/chrome-headless-shell-linux64/chrome-headless-shell`)[0];
const serveUrl = await bundle({ entryPoint: path.join(ROOT, 'src/index.ts') });
const composition = await selectComposition({ serveUrl, id: 'Short', browserExecutable: be });
for (const s of secs) {
  const frame = Math.min(composition.durationInFrames - 1, Math.round(parseFloat(s) * composition.fps));
  await renderStill({ composition, serveUrl, frame, output: path.join(outDir, `f_${s}.png`), browserExecutable: be, scale: 0.5 });
  console.log('rendered', s);
}
