// Рендер контрольных кадров: node scripts/stills.mjs out_dir t1 t2 ...  (секунды, композиция Samurai60)
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import path from "node:path";

const [outDir, ...times] = process.argv.slice(2);
const browserExecutable = process.env.REMOTION_BROWSER ?? "/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell";
const serveUrl = await bundle({ entryPoint: path.resolve("src/index.ts") });
const comp = await selectComposition({ serveUrl, id: "Samurai60", chromiumOptions: { gl: process.env.REMOTION_GL ?? "swangle" }, browserExecutable });
for (const t of times) {
  const frame = Math.round(parseFloat(t) * 60);
  const t0 = Date.now();
  await renderStill({
    serveUrl, composition: comp, frame, output: path.join(outDir, `f_${t}.jpg`), imageFormat: "jpeg", jpegQuality: 90,
    chromiumOptions: { gl: process.env.REMOTION_GL ?? "swangle" }, scale: 0.5, browserExecutable,
  });
  console.log(t, "s", ((Date.now() - t0) / 1000).toFixed(1) + "s");
}
