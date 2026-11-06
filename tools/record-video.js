// Запись мультфильма в видео: озвучка Piper/espeak-ng + Playwright-видео + ffmpeg-сведение
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const SP = process.argv[2], OUT = process.argv[3];
const A = `${SP}/audio`, V = `${SP}/vid`;
fs.mkdirSync(A, { recursive: true }); fs.rmSync(V, { recursive: true, force: true });
const dur = f => parseFloat(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]).toString());
(async () => {
  const b = await chromium.launch();
  // 1) тексты озвучки прямо из массива scenes
  const p0 = await b.newPage();
  await p0.goto('file:///home/user/video/index.html?mute=1');
  const sc = await p0.evaluate(() => window.__movie.scenes.map(s => ({ voice: s.voice, pitch: s.pitch || 1, duration: s.duration })));
  await p0.close();
  // Голоса: нейронный Piper. PIPER_MODEL — рассказчик, PIPER_MODEL_ALT — реплики с pitch>1 (продавщица).
  // Без PIPER_MODEL используется espeak-ng.
  const PIPER = process.env.PIPER_MODEL, ALT = process.env.PIPER_MODEL_ALT || PIPER;
  const audio = sc.map((s, i) => {
    const f = `${A}/v${i + 1}.wav`, raw = `${A}/raw${i + 1}.wav`;
    const high = s.pitch > 1;
    if (PIPER) execFileSync('python3', ['-m', 'piper', '-m', high ? ALT : PIPER, '-f', raw, '--sentence-silence', '0.2'], { input: s.voice });
    else execFileSync('espeak-ng', ['-v', high ? 'ru+f3' : 'ru+m3', '-s', '145', '-p', high ? '70' : '45', '-w', raw, s.voice]);
    const sr = parseInt(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=sample_rate', '-of', 'csv=p=0', raw]).toString(), 10);
    // продавщица: тон выше на 8% и темп быстрее на 12%
    const af = (PIPER && high ? `asetrate=${sr}*1.08,aresample=44100,atempo=${(1.12 / 1.08).toFixed(3)},` : 'aresample=44100,') +
      'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,' +
      'highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=5:release=120,loudnorm=I=-16:TP=-1.5:LRA=7';
    execFileSync('ffmpeg', ['-y', '-v', 'error', '-i', raw, '-af', af, '-ar', '44100', '-ac', '1', f]);
    return { f, ms: dur(f) * 1000 };
  });
  // длительность сцены = max(исходной, 0.35с + фраза + 0.7с)
  const durations = sc.map((s, i) => Math.max(s.duration, (350 + audio[i].ms + 700) / 1000));
  // 2) запись видео
  const ctx = await b.newContext({ viewport: { width: 1280, height: 720 }, recordVideo: { dir: V, size: { width: 1280, height: 720 } } });
  const p = await ctx.newPage();
  const vStart = Date.now();
  const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto('file:///home/user/video/index.html?mute=1');
  await p.addStyleTag({ content: '#app{padding:0!important;gap:0!important} #controls{display:none!important} #stage{width:100vw!important;height:100vh!important;border:0!important;border-radius:0!important;box-shadow:none!important}' });
  await p.evaluate(d => d.forEach((x, i) => { window.__movie.scenes[i].duration = x; }), durations);
  await p.waitForTimeout(800);
  const clickEpoch = await p.evaluate(() => { document.getElementById('bigStart').click(); return performance.timeOrigin + performance.now(); });
  await p.waitForFunction(() => window.__movie.M.finished, null, { timeout: 180000, polling: 200 });
  await p.waitForTimeout(1500);              // подержать финальный кадр
  const log = await p.evaluate(() => window.__movie.M.log.map(l => ({ ...l, epoch: performance.timeOrigin + l.at })));
  const endEpoch = Date.now();
  await ctx.close();
  const raw = fs.readdirSync(V).map(f => `${V}/${f}`)[0];
  await b.close();
  // 3) сведение: обрезаем начало до клика, каждую фразу ставим на старт её сцены + 350 мс
  const trim = (clickEpoch - vStart) / 1000;
  const starts = log.filter(l => l.scene).map(l => Math.round(l.epoch - clickEpoch + 350));
  const total = (endEpoch - clickEpoch) / 1000;
  const args = ['-y', '-v', 'error', '-ss', trim.toFixed(3), '-i', raw];
  audio.forEach(a => args.push('-i', a.f));
  const fl = audio.map((a, i) => `[${i + 1}:a]adelay=${starts[i]}|${starts[i]}[a${i}]`).join(';') +
    ';' + audio.map((_, i) => `[a${i}]`).join('') + `amix=inputs=${audio.length}:normalize=0,apad[aout]`;
  args.push('-filter_complex', fl, '-map', '0:v', '-map', '[aout]', '-t', total.toFixed(2),
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', '25', '-c:a', 'aac', '-b:a', '160k', '-ac', '2', '-movflags', '+faststart', OUT);
  execFileSync('ffmpeg', args);
  console.log('scene starts (s):', starts.map(s => (s / 1000).toFixed(1)).join(' '));
  console.log('voice lengths (s):', audio.map(a => (a.ms / 1000).toFixed(1)).join(' '));
  console.log('video:', OUT, 'length', dur(OUT).toFixed(1), 's; page errors:', errs.length ? errs : 'none');
})();
