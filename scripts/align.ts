/**
 * Уточнение таймингов сцен по реальной озвучке.
 *
 *   npm run align            — паузы через ffmpeg silencedetect (+ Whisper, если он установлен)
 *   npm run align -- --no-whisper
 *
 * Что делает скрипт:
 *  1. Узнаёт длительность public/voiceover.mp3 (ffprobe) → durationInFrames.
 *  2. Запускает `ffmpeg -i public/voiceover.mp3 -af silencedetect=noise=-35dB:d=0.3 -f null -`
 *     и собирает список пауз.
 *  3. Каждую границу между сценами (из поля draft — стартовые значения) сдвигает
 *     к ближайшей паузе в пределах ±1.5 сек. Новая граница ставится чуть раньше
 *     начала следующей фразы, чтобы смена картинки совпала со вступлением голоса.
 *  4. Для каждой сцены сохраняет отрезки речи (speech) — по ним раскладываются
 *     субтитры, если нет Whisper.
 *  5. Если в системе есть `whisper` (openai-whisper) или python-модуль `faster_whisper`,
 *     получает тайминги слов и пишет их в words.json. Ничего не устанавливает.
 */
import {spawnSync} from 'node:child_process';
import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';

const ROOT = resolve(__dirname, '..');
const AUDIO = join(ROOT, 'public', 'voiceover.mp3');
const SCENES = join(ROOT, 'scenes.json');
const WORDS = join(ROOT, 'words.json');
const CACHE = join(ROOT, 'scripts', '.cache');

const SNAP_WINDOW = 1.5; // сек
const LEAD_IN = 0.12; // сцена начинается за 0.12 сек до голоса
const MIN_SCENE = 1.0; // минимальная длина сцены, сек

type Interval = {start: number; end: number};
type SceneJson = {
  id: string;
  start: number;
  end: number;
  title: string;
  text: string;
  image: string | null;
  draft?: Interval;
  speech?: Interval[];
};
type ScenesFile = {
  fps: number;
  durationInFrames: number;
  audioDuration: number;
  aligned: boolean;
  alignNote?: string;
  scenes: SceneJson[];
};

const round = (n: number) => Math.round(n * 1000) / 1000;
const args = new Set(process.argv.slice(2));

function run(cmd: string, cmdArgs: string[]) {
  const res = spawnSync(cmd, cmdArgs, {encoding: 'utf8', maxBuffer: 64 * 1024 * 1024});
  if (res.error) throw res.error;
  return res;
}

function hasCommand(cmd: string) {
  return spawnSync('sh', ['-c', `command -v ${cmd}`], {encoding: 'utf8'}).status === 0;
}

// ---------------------------------------------------------------- 1. длительность
function getDuration(): number {
  const res = run('ffprobe', [
    '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', AUDIO,
  ]);
  const d = parseFloat(res.stdout.trim());
  if (!Number.isFinite(d)) throw new Error('ffprobe не смог прочитать длительность: ' + res.stderr);
  return d;
}

// ---------------------------------------------------------------- 2. паузы
function detectSilences(duration: number): Interval[] {
  const res = run('ffmpeg', [
    '-hide_banner', '-nostats', '-i', AUDIO,
    '-af', 'silencedetect=noise=-35dB:d=0.3', '-f', 'null', '-',
  ]);
  const out = res.stderr;
  const silences: Interval[] = [];
  let open: number | null = null;
  for (const line of out.split('\n')) {
    const s = line.match(/silence_start:\s*(-?[\d.]+)/);
    const e = line.match(/silence_end:\s*([\d.]+)/);
    if (s) open = Math.max(0, parseFloat(s[1]));
    if (e && open !== null) {
      silences.push({start: open, end: parseFloat(e[1])});
      open = null;
    }
  }
  if (open !== null) silences.push({start: open, end: duration}); // тишина до конца файла
  return silences;
}

// ---------------------------------------------------------------- 3. границы
function snapBoundaries(scenes: SceneJson[], silences: Interval[], duration: number) {
  const used = new Set<number>();
  const boundaries: number[] = [0];
  const report: string[] = [];

  for (let i = 1; i < scenes.length; i++) {
    const draft = scenes[i].draft!.start;
    const prev = boundaries[i - 1];
    let best: {idx: number; dist: number; len: number} | null = null;

    silences.forEach((sil, idx) => {
      if (used.has(idx)) return;
      const dist = draft < sil.start ? sil.start - draft : draft > sil.end ? draft - sil.end : 0;
      if (dist > SNAP_WINDOW) return;
      const candidate = Math.max(sil.start, sil.end - LEAD_IN);
      if (candidate < prev + MIN_SCENE) return;
      const len = sil.end - sil.start;
      if (!best || dist < best.dist - 0.05 || (Math.abs(dist - best.dist) <= 0.05 && len > best.len)) {
        best = {idx, dist, len};
      }
    });

    let b = draft;
    if (best) {
      const sil = silences[(best as {idx: number}).idx];
      used.add((best as {idx: number}).idx);
      b = Math.max(sil.start, sil.end - LEAD_IN);
      report.push(
        `  ${scenes[i - 1].id} → ${scenes[i].id}: ${draft.toFixed(2)} → ${b.toFixed(2)} сек ` +
          `(пауза ${sil.start.toFixed(2)}–${sil.end.toFixed(2)})`,
      );
    } else {
      report.push(`  ${scenes[i - 1].id} → ${scenes[i].id}: ${draft.toFixed(2)} сек — пауза в ±${SNAP_WINDOW} сек не найдена, оставлено как есть`);
    }
    boundaries.push(Math.max(b, prev + MIN_SCENE));
  }
  boundaries.push(duration);
  return {boundaries, report};
}

// ---------------------------------------------------------------- 4. отрезки речи
function speechSegments(range: Interval, silences: Interval[]): Interval[] {
  const segs: Interval[] = [];
  let cursor = range.start;
  for (const sil of silences) {
    if (sil.end <= range.start || sil.start >= range.end) continue;
    const s = Math.max(sil.start, range.start);
    if (s - cursor > 0.05) segs.push({start: round(cursor), end: round(s)});
    cursor = Math.max(cursor, Math.min(sil.end, range.end));
  }
  if (range.end - cursor > 0.05) segs.push({start: round(cursor), end: round(range.end)});
  return segs.length ? segs : [{start: round(range.start), end: round(range.end)}];
}

// ---------------------------------------------------------------- 5. Whisper (опционально)
type Word = {word: string; start: number; end: number};

function tryWhisper(): {source: string; words: Word[]} | null {
  if (args.has('--no-whisper')) return null;
  mkdirSync(CACHE, {recursive: true});

  // faster-whisper (python)
  const py = hasCommand('python3') ? 'python3' : hasCommand('python') ? 'python' : null;
  if (py && spawnSync(py, ['-c', 'import faster_whisper'], {encoding: 'utf8'}).status === 0) {
    console.log('• Найден faster-whisper — получаю тайминги слов…');
    const code = [
      'import json, sys',
      'from faster_whisper import WhisperModel',
      'm = WhisperModel(sys.argv[2], device="auto", compute_type="auto")',
      'segs, _ = m.transcribe(sys.argv[1], language="ru", word_timestamps=True, vad_filter=False)',
      'out = [{"word": w.word, "start": w.start, "end": w.end} for s in segs for w in (s.words or [])]',
      'print(json.dumps(out, ensure_ascii=False))',
    ].join('\n');
    const res = spawnSync(py, ['-c', code, AUDIO, process.env.WHISPER_MODEL ?? 'small'], {
      encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
    });
    if (res.status === 0) {
      const lines = res.stdout.trim().split('\n');
      return {source: 'faster-whisper', words: JSON.parse(lines[lines.length - 1])};
    }
    console.warn('  faster-whisper завершился с ошибкой, использую запасной вариант.\n' + res.stderr.slice(-600));
  }

  // openai-whisper (CLI)
  if (hasCommand('whisper')) {
    console.log('• Найден whisper CLI — получаю тайминги слов…');
    const res = spawnSync('whisper', [
      AUDIO, '--model', process.env.WHISPER_MODEL ?? 'small', '--language', 'ru',
      '--word_timestamps', 'True', '--output_format', 'json', '--output_dir', CACHE,
    ], {encoding: 'utf8', maxBuffer: 64 * 1024 * 1024});
    const json = join(CACHE, 'voiceover.json');
    if (res.status === 0 && existsSync(json)) {
      const data = JSON.parse(readFileSync(json, 'utf8')) as {
        segments: {words?: Word[]}[];
      };
      return {source: 'whisper', words: data.segments.flatMap((s) => s.words ?? [])};
    }
    console.warn('  whisper завершился с ошибкой, использую запасной вариант.\n' + (res.stderr ?? '').slice(-600));
  }
  return null;
}

// ---------------------------------------------------------------- main
function main() {
  const file = JSON.parse(readFileSync(SCENES, 'utf8')) as ScenesFile;
  const fps = file.fps;

  // стартовые значения сохраняем один раз — повторный запуск всегда считает от них
  for (const s of file.scenes) if (!s.draft) s.draft = {start: s.start, end: s.end};

  const duration = getDuration();
  console.log(`• Длительность озвучки: ${duration.toFixed(3)} сек (${Math.round(duration * fps)} кадров @ ${fps} fps)`);

  const silences = detectSilences(duration);
  console.log(`• Найдено пауз: ${silences.length}`);
  for (const s of silences) console.log(`    ${s.start.toFixed(2)} – ${s.end.toFixed(2)}  (${(s.end - s.start).toFixed(2)} сек)`);

  const {boundaries, report} = snapBoundaries(file.scenes, silences, duration);
  console.log('• Границы сцен:');
  report.forEach((r) => console.log(r));

  file.scenes.forEach((s, i) => {
    s.start = round(boundaries[i]);
    s.end = round(boundaries[i + 1]);
    s.speech = speechSegments({start: s.start, end: s.end}, silences);
  });

  file.audioDuration = round(duration);
  file.durationInFrames = Math.round(duration * fps);
  file.aligned = true;
  file.alignNote = `Выровнено scripts/align.ts по паузам озвучки (${new Date().toISOString()}). Стартовые значения — в поле draft.`;
  writeFileSync(SCENES, JSON.stringify(file, null, 2) + '\n');
  console.log('✓ scenes.json обновлён');

  const whisper = tryWhisper();
  if (whisper && whisper.words.length) {
    writeFileSync(WORDS, JSON.stringify({source: whisper.source, words: whisper.words.map((w) => ({
      word: w.word.trim(), start: round(w.start), end: round(w.end),
    }))}, null, 2) + '\n');
    console.log(`✓ words.json: ${whisper.words.length} слов от ${whisper.source}`);
  } else {
    writeFileSync(WORDS, JSON.stringify({
      source: 'none',
      note: 'Whisper не найден — субтитры распределяются пропорционально длине слов внутри отрезков речи сцены.',
      words: [],
    }, null, 2) + '\n');
    console.log('• Whisper/faster-whisper не найден — субтитры: пропорционально длине слов (запасной вариант)');
  }

  console.log('\nИтог:');
  for (const s of file.scenes) {
    console.log(`  ${s.id.padEnd(9)} ${s.start.toFixed(2).padStart(6)} – ${s.end.toFixed(2).padStart(6)}  речь: ${s.speech!.map((x) => `${x.start.toFixed(2)}–${x.end.toFixed(2)}`).join(', ')}`);
  }
}

main();
