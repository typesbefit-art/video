#!/usr/bin/env python3
"""
Генератор вертикального хоррор-ролика «страшная история с озвучкой и субтитрами».

    python generate.py story.txt                  -> output.mp4
    python generate.py story.txt --fps 60
    python generate.py story.txt --duration 15 -o output_preview.mp4   (пробная версия)

Текст истории — в story.txt (первая строка — заголовок).
Части серии: python generate.py story2.txt part2  -> output_part2.mp4 (настройки в parts/part2.toml)
Голоса, цвета, шрифты, события по ключевым словам — в config.toml.
"""
import argparse
import asyncio
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent


# ───────────────────────────── зависимости ─────────────────────────────

def _pip(*pkgs):
    print(f"[setup] устанавливаю: {' '.join(pkgs)}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *pkgs])


def ensure_python_deps():
    need = []
    for mod, pkg in (("numpy", "numpy"), ("PIL", "pillow"), ("edge_tts", "edge-tts")):
        try:
            __import__(mod)
        except ImportError:
            need.append(pkg)
    if sys.version_info < (3, 11):
        try:
            __import__("tomli")
        except ImportError:
            need.append("tomli")
    if need:
        _pip(*need)


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    # Пытаемся поставить системный ffmpeg, иначе берём статический из pip.
    if shutil.which("apt-get") and hasattr(os, "geteuid") and os.geteuid() == 0:
        subprocess.call(["apt-get", "install", "-y", "-qq", "ffmpeg"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif shutil.which("brew"):
        subprocess.call(["brew", "install", "ffmpeg"])
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # noqa
    except ImportError:
        _pip("imageio-ffmpeg")
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


ensure_python_deps()

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402
import edge_tts  # noqa: E402

try:
    import tomllib  # noqa: E402
except ImportError:  # Python < 3.11
    import tomli as tomllib  # noqa: E402

FFMPEG = None
G = {}  # состояние для рендера кадров (наследуется воркерами через fork)


# ───────────────────────────── утилиты ─────────────────────────────

def db(x):
    return 10.0 ** (x / 20.0)


def to_db(x):
    return 20.0 * math.log10(max(float(x), 1e-12))


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def norm_word(s):
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[^\w\s-]", "", s)
    return s.strip()


def smoothstep(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def active_rms(x, sr, floor_db=-35.0):
    """RMS только по звучащим участкам (окна 50 мс выше порога от пика)."""
    win = int(sr * 0.05)
    n = len(x) // win
    if n == 0:
        return rms(x)
    frames = x[:n * win].reshape(n, win)
    r = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    thr = r.max() * db(floor_db)
    r = r[r > thr]
    return float(np.sqrt(np.mean(r ** 2))) if len(r) else 0.0


def fft_filter(x, sr, lo=None, hi=None, order=2):
    """Мягкий полосовой фильтр в частотной области (без scipy)."""
    n = len(x)
    if n == 0:
        return x
    nfft = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, nfft)
    f = np.fft.rfftfreq(nfft, 1.0 / sr)
    m = np.ones_like(f)
    if lo:
        with np.errstate(divide="ignore"):
            m *= 1.0 / np.sqrt(1.0 + (lo / np.maximum(f, 1e-6)) ** (2 * order))
    if hi:
        m *= 1.0 / np.sqrt(1.0 + (f / hi) ** (2 * order))
    return np.fft.irfft(X * m, nfft)[:n].astype(np.float32)


def fft_convolve(x, ir):
    n = len(x) + len(ir) - 1
    nfft = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(ir, nfft), nfft)[:n]
    return y.astype(np.float32)


def simple_reverb(x, sr, decay=0.8, mix=0.25, seed=1):
    rng = np.random.default_rng(seed)
    n = int(sr * decay * 1.5)
    t = np.arange(n) / sr
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-t / (decay / 6.9)).astype(np.float32)
    ir = fft_filter(ir, sr, hi=5000)
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    wet = fft_convolve(x, ir)[:len(x)]
    return (1 - mix) * x + mix * wet * (rms(x) / (rms(wet) + 1e-9))


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def decode_audio(path, sr, af=None):
    out = run([FFMPEG, "-v", "error", "-i", str(path)] + (["-af", af] if af else []) +
              ["-f", "f32le", "-ac", "1", "-ar", str(sr), "-"], capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def write_wav(path, x, sr):
    y = np.clip(x, -1, 1)
    pcm = (y * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def load_font(candidates, size):
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    if shutil.which("fc-match"):
        for fam in ("Inter:style=ExtraBold", "DejaVu Sans:style=Bold"):
            p = subprocess.run(["fc-match", "-f", "%{file}", fam], capture_output=True, text=True).stdout
            if p and os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


# ───────────────────────────── история ─────────────────────────────

def parse_story(path, vcfg=None):
    vcfg = vcfg or {}
    text = Path(path).read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    title = lines[0].strip()
    body = " ".join(l.strip() for l in lines[1:] if l.strip())
    # «Кавычки», которые читает рассказчик (надписи на экране, имена, свои реплики)
    narr = {norm_word(q) for q in vcfg.get("narrator_quotes", [])}
    body = re.sub(r"«([^»]+)»", lambda m: m.group(1) if norm_word(m.group(1)) in narr else m.group(0), body)
    segments = []  # {"text", "quote", "qstart", "dash"}
    pos = 0
    for m in re.finditer(r"«([^»]+)»", body):
        _split_sentences(body[pos:m.start()], segments, False)
        # «Реплика, — сказала она. — Продолжение» : слова автора внутри — рассказчику
        pieces = re.split(r"\s+[—–]\s+", m.group(1).strip())
        for k, p in enumerate(pieces):
            _split_sentences(p, segments, quote=(k % 2 == 0), first_of_quote=(k == 0))
        pos = m.end()
    _split_sentences(body[pos:], segments, False)
    return title, segments


def _split_sentences(chunk, out, quote=False, first_of_quote=False):
    chunk = chunk.strip()
    if not chunk:
        return
    j = 0
    for s in re.split(r"(?<=[.!?…])\s+", chunk):
        s = s.strip()
        dash = bool(re.match(r"^[—–-]", s))
        s = s.lstrip("—–- ").strip()
        if s and re.search(r"\w", s):
            out.append({"text": s, "quote": quote, "qstart": quote and first_of_quote and j == 0, "dash": dash})
            j += 1


# ───────────────────────────── озвучка ─────────────────────────────

def patch_edge_tts_ssl():
    """edge-tts использует certifi; за корпоративным/прокси-шлюзом нужен свой CA."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.isfile(ca):
        import ssl
        import edge_tts.communicate as ec
        ec._SSL_CTX = ssl.create_default_context(cafile=ca)


async def _tts_one(text, voice, rate, pitch, cache, sem):
    key = hashlib.sha1(json.dumps([text, voice, rate, pitch]).encode()).hexdigest()[:20]
    mp3, js = cache / f"{key}.mp3", cache / f"{key}.json"
    if mp3.exists() and js.exists():
        return mp3, json.loads(js.read_text())
    async with sem:
        last_err = None
        tries = int(os.environ.get("TTS_RETRIES", "8"))
        for attempt in range(tries):
            # сервис иногда «залипает» на конкретной строке — пробуем равнозвучные варианты
            noyo = text.replace("ё", "е").replace("Ё", "Е")
            variants = [text, text.rstrip(".!?…") or text, noyo, noyo.rstrip(".!?…") or noyo, text + ".."]
            say = variants[attempt % len(variants)]
            try:
                words, audio = [], bytearray()
                com = edge_tts.Communicate(say, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
                async for ch in com.stream():
                    if ch["type"] == "audio":
                        audio.extend(ch["data"])
                    elif ch["type"] == "WordBoundary":
                        st = ch["offset"] / 1e7
                        words.append([ch["text"], st, st + ch["duration"] / 1e7])
                if not audio:
                    raise RuntimeError("пустой ответ edge-tts")
                mp3.write_bytes(bytes(audio))
                js.write_text(json.dumps(words, ensure_ascii=False))
                return mp3, words
            except Exception as e:  # сеть может моргать
                last_err = e
                await asyncio.sleep(min(30.0, 2.0 * 1.6 ** attempt))
        raise RuntimeError(f"edge-tts не ответил для «{text[:40]}…»: {last_err}")


AUDIO_EXT = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus")
VOWELS = set("аеёиоуыэюяaeiouy")


def find_recordings(name):
    """voice/<name>/01.wav … или один файл voice/<name>.wav"""
    d = ROOT / "voice" / name
    if d.is_dir():
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in AUDIO_EXT)
        if files:
            return {"files": files}
    roles = {}
    vd = ROOT / "voice"
    for role in ("narrator", "female"):
        # part2_narrator.mp3 или несколько кусков part2_narrator_1.mp3, part2_narrator_2.mp3 …
        fs = [p for p in (vd.glob(f"{name}_{role}*") if vd.is_dir() else [])
              if p.suffix.lower() in AUDIO_EXT and re.fullmatch(rf"{re.escape(name)}_{role}(_?\d+)?", p.stem)]
        if fs:
            roles[role] = sorted(fs, key=lambda p: int(re.sub(r"\D", "", p.stem[len(name) + len(role) + 1:]) or 0))
    if "narrator" in roles:
        return {"roles": roles}
    for ext in AUDIO_EXT:
        f = ROOT / "voice" / f"{name}{ext}"
        if f.exists():
            return {"single": f}
    return None


def _frame_energy(x, sr, ms=10):
    fr = max(1, int(sr * ms / 1000))
    n = max(1, len(x) // fr)
    e = np.sqrt(np.mean(x[: n * fr].reshape(n, fr).astype(np.float64) ** 2, axis=1) + 1e-12)
    e = np.convolve(e, np.ones(3) / 3, mode="same")
    thr = max(np.percentile(e, 10) * 2.5, e.max() * db(-38))
    return e, thr, fr


def split_by_silence(x, sr, n):
    """Режет одну запись на n фраз по n-1 самым длинным паузам."""
    if n <= 1:
        return [x]
    e, thr, fr = _frame_energy(x, sr)
    quiet = e < thr
    runs, i = [], 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if i > 0 and j < len(quiet):
                runs.append((j - i, i, j))
            i = j
        else:
            i += 1
    runs = [r for r in runs if r[0] * fr / sr >= 0.3]
    if len(runs) < n - 1:
        raise SystemExit(f"[voice] в записи нашлось только {len(runs) + 1} фраз(ы) вместо {n}: "
                         f"сделай паузы между фразами не короче 1 секунды или пришли по файлу на фразу")
    cuts = sorted(((a + b) // 2) * fr for _, a, b in sorted(runs, reverse=True)[: n - 1])
    bounds = [0] + cuts + [len(x)]
    return [x[bounds[k]:bounds[k + 1]] for k in range(n)]


def split_aligned(x, sr, texts):
    """Режет запись на фразы с учётом текста: разрезы — по паузам, длина кусков ≈ числу слогов.
    Нужна, когда паузы между фразами не длиннее пауз внутри фраз (ElevenLabs игнорирует <break>)."""
    n = len(texts)
    if n <= 1:
        return [x]
    e, thr, fr = _frame_energy(x, sr)
    voiced = e > thr
    cum = np.concatenate([[0], np.cumsum(voiced)])
    cands = []  # (середина паузы в кадрах, длина паузы в секундах)
    i = 0
    while i < len(voiced):
        if not voiced[i]:
            j = i
            while j < len(voiced) and not voiced[j]:
                j += 1
            if i > 0 and j < len(voiced) and (j - i) * fr / sr >= 0.08:
                cands.append(((i + j) // 2, (j - i) * fr / sr))
            i = j
        else:
            i += 1
    if len(cands) < n - 1:
        raise SystemExit(f"[voice] в записи слишком мало пауз ({len(cands)}) для {n} фраз")
    syl = np.array([sum(ch in VOWELS for ch in t.lower()) + 0.6 for t in texts], dtype=np.float64)
    exp = syl / syl.sum() * cum[-1]                    # ожидаемая «звучащая» длина каждой фразы (кадры)
    pos = [0] + [c[0] for c in cands] + [len(voiced)]
    gap = [0.0] + [c[1] for c in cands] + [0.0]
    M = len(pos)
    NEG = -1e18
    # dp[k][j]: лучший счёт, если k-я фраза заканчивается на позиции j
    dp = np.full((n + 1, M), NEG)
    back = np.zeros((n + 1, M), dtype=np.int64)
    dp[0][0] = 0.0
    for k in range(1, n + 1):
        for j in range(1, M):
            if k < n and j == M - 1:
                continue
            if k == n and j != M - 1:
                continue
            best, arg = NEG, -1
            for i0 in range(k - 1, j):
                if dp[k - 1][i0] <= NEG / 2:
                    continue
                v = cum[pos[j]] - cum[pos[i0]]
                dev = (v - exp[k - 1]) / max(exp[k - 1], 25.0)
                sc = dp[k - 1][i0] - 4.0 * dev * dev + (3.0 * gap[j] if k < n else 0.0)
                if sc > best:
                    best, arg = sc, i0
            dp[k][j], back[k][j] = best, arg
    cuts, j = [], M - 1
    for k in range(n, 0, -1):
        cuts.append(pos[j])
        j = back[k][j]
    bounds = [0] + sorted(cuts)
    return [x[bounds[k] * fr:bounds[k + 1] * fr] for k in range(n)]


def trim_silence(x, sr):
    e, thr, fr = _frame_energy(x, sr)
    idx = np.nonzero(e > thr)[0]
    if not len(idx):
        return x
    a = max(0, idx[0] * fr - int(0.04 * sr))
    b = min(len(x), (idx[-1] + 1) * fr + int(0.10 * sr))
    y = x[a:b].copy()
    f = min(len(y), int(0.02 * sr))
    if f:
        y[:f] *= np.linspace(0, 1, f, dtype=np.float32)
        y[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
    return y


def estimate_words(x, sr, text):
    """Тайминги слов без распознавания: паузы по громкости + слоги внутри речи."""
    toks = re.findall(r"\w[\w-]*", text)
    if not toks:
        return []
    e, thr, fr = _frame_energy(x, sr)
    voiced = e > thr
    cum = np.cumsum(voiced)
    total = max(int(cum[-1]), 1)
    wts = [sum(ch in VOWELS for ch in t.lower()) + 0.35 for t in toks]
    edges = np.cumsum([0.0] + wts) / sum(wts) * total
    idx = np.searchsorted(cum, np.maximum(edges, 1), side="left")
    idx[0] = np.argmax(voiced) if voiced.any() else 0
    out = []
    for k, t in enumerate(toks):
        st, en = idx[k] * fr / sr, max(idx[k + 1], idx[k] + 1) * fr / sr
        out.append([t, float(st), float(en)])
    return out


def load_recorded(segments, cfg, rate_shift, sr):
    rec = cfg["_recorded"]
    v = cfg["voice"]
    tempo = min(1.08, max(0.94, 1 + rate_shift / 100.0))
    af = f"highpass=f=70,atempo={tempo:.3f}" if abs(tempo - 1) > 1e-3 else "highpass=f=70"
    n = len(segments)
    if "files" in rec:
        files = rec["files"]
        by_num = {}
        for f in files:
            m = re.match(r"0*(\d+)", f.stem)
            if m:
                by_num.setdefault(int(m.group(1)), f)
        missing = [k for k in range(1, n + 1) if k not in by_num]
        if missing:
            raise SystemExit(f"[voice] нет файлов для фраз: {missing} (ожидаю {n} файлов 01…{n:02d})")
        raws = [decode_audio(by_num[k], sr, af) for k in range(1, n + 1)]
    elif "roles" in rec:
        # два файла: все фразы рассказчика подряд и все женские реплики подряд
        nq = sum(1 for sg in segments if sg["quote"])
        def load_role(files):
            gap = np.zeros(int(1.5 * sr), dtype=np.float32)
            parts = []
            for f in files:
                parts += [decode_audio(f, sr, af), gap]
            return np.concatenate(parts)
        narr = split_aligned(load_role(rec["roles"]["narrator"]), sr, [sg["text"] for sg in segments if not sg["quote"]])
        fem = []
        if nq:
            if "female" not in rec["roles"]:
                raise SystemExit(f"[voice] нужен файл с женскими репликами ({nq} шт.): voice/<часть>_female.mp3")
            fem = split_aligned(load_role(rec["roles"]["female"]), sr, [sg["text"] for sg in segments if sg["quote"]])
        it_n, it_f = iter(narr), iter(fem)
        raws = [next(it_f) if sg["quote"] else next(it_n) for sg in segments]
    else:
        raws = split_aligned(decode_audio(rec["single"], sr, af), sr, [sg["text"] for sg in segments])
    out = []
    for s, x in zip(segments, raws):
        x = trim_silence(x, sr)
        words = estimate_words(x, sr, s["text"])
        out.append({**s, "audio": x, "words": words, "dur": len(x) / sr,
                    "whisper": v.get("recorded_quote_whisper", 0.25)})
    return out


def synthesize(segments, cfg, rate_shift, sr):
    v = cfg["voice"]
    if cfg.get("_recorded"):
        return load_recorded(segments, cfg, rate_shift, sr)
    cache = ROOT / ".cache" / "tts"
    cache.mkdir(parents=True, exist_ok=True)

    def shift(rate):
        return f"{int(rate.rstrip('%')) + rate_shift:+d}%"

    async def main():
        sem = asyncio.Semaphore(2)
        jobs = []
        for s in segments:
            if s["quote"]:
                jobs.append(_tts_one(s["text"], v["quote_voice"], shift(v["quote_rate"]), v["quote_pitch"], cache, sem))
            else:
                jobs.append(_tts_one(s["text"], v["narrator"], shift(v["narrator_rate"]), v["narrator_pitch"], cache, sem))
        return await asyncio.gather(*jobs)

    results = asyncio.run(main())
    out = []
    for s, (mp3, words) in zip(segments, results):
        x = decode_audio(mp3, sr)
        x, words = trim_segment(x, words, sr)
        out.append({**s, "audio": x, "words": words, "dur": len(x) / sr})
    return out


def trim_segment(x, words, sr):
    win = max(1, int(sr * 0.01))
    env = np.convolve(np.abs(x), np.ones(win) / win, mode="same")
    thr = max(env.max() * db(-42), 1e-5)
    idx = np.nonzero(env > thr)[0]
    first_audio = idx[0] / sr if len(idx) else 0.0
    last_audio = idx[-1] / sr if len(idx) else len(x) / sr
    first = min(words[0][1], first_audio) if words else first_audio
    a = max(0.0, first - 0.04)
    b = min(len(x) / sr, last_audio + 0.10)
    y = x[int(a * sr):int(b * sr)].copy()
    f = min(len(y), int(0.02 * sr))
    if f:
        y[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
    dur = len(y) / sr
    w2 = [[w, max(0.0, s - a), min(dur, e - a)] for w, s, e in words]
    return y, w2


def whisperize(x, sr, amount, seed=7):
    """Шёпот: тоньше голос + дыхательный шум по огибающей голоса."""
    if amount <= 0 or len(x) == 0:
        return x
    rng = np.random.default_rng(seed)
    thin = fft_filter(x, sr, lo=320, hi=7000)
    win = int(sr * 0.012)
    env = np.convolve(np.abs(x), np.ones(win) / win, mode="same").astype(np.float32)
    breath = fft_filter(rng.standard_normal(len(x)).astype(np.float32), sr, lo=1600, hi=7500)
    breath *= env / (rms(env) + 1e-9)
    breath *= rms(thin) / (rms(breath) + 1e-9) * 0.55
    y = thin * (1 - 0.45 * amount) + breath * amount
    return simple_reverb(y, sr, decay=0.35, mix=0.12, seed=seed)


# ───────────────────────────── сопоставление фраз ─────────────────────────────

def build_tokens(words):
    toks = []
    for wi, w in enumerate(words):
        for p in norm_word(w["text"]).replace("-", " ").split():
            toks.append((p, wi))
    return toks


def find_phrase(words, phrase, toks=None):
    """Возвращает список (индекс_первого_слова, индекс_последнего_слова)."""
    toks = toks if toks is not None else build_tokens(words)
    pt = norm_word(phrase).replace("-", " ").split()
    if not pt:
        return []
    res = []
    for i in range(len(toks) - len(pt) + 1):
        if all(toks[i + k][0].startswith(pt[k]) for k in range(len(pt))):
            res.append((toks[i][1], toks[i + len(pt) - 1][1]))
    return res


# ───────────────────────────── таймлайн ─────────────────────────────

def plan_timeline(segs, cfg, pause):
    v, vid = cfg["voice"], cfg["video"]
    n = len(segs)
    gaps = [0.0] * n  # пауза перед сегментом i
    flex = [False] * n
    keyp = [(norm_word(p["phrase"]).replace("-", " "), p["pause"]) for p in v.get("pause_before", [])]
    for i in range(1, n):
        seg, prev = segs[i], segs[i - 1]
        nt = norm_word(seg["text"]).replace("-", " ")
        g = None
        for kp, kpause in keyp:
            if nt.startswith(kp):
                g = kpause
        if i == n - 1:
            g = max(g or 0.0, v["pause_before_last"])
        if g is None:
            if seg.get("qstart"):
                g = v["pause_before_quote"]
            elif prev["text"].rstrip().endswith(",") or seg.get("dash"):
                g = v.get("pause_short", 0.25)
            else:
                g = pause
                flex[i] = True
        gaps[i] = g
    # Тишина вокруг фразы: удлиняем нужную паузу
    for ev in cfg.get("events", []):
        if ev.get("type") != "silence" or not isinstance(ev.get("duration"), (int, float)):
            continue
        at = ev.get("at", "after")
        if at == "after":
            for si, s in enumerate(segs[:-1]):
                sw = [{"text": w[0]} for w in s["words"]]
                hits = find_phrase(sw, ev["phrase"])
                if hits:
                    tail = s["dur"] - s["words"][hits[0][1]][2]
                    need = ev["duration"] + 0.05 - tail
                    if gaps[si + 1] < need:
                        gaps[si + 1], flex[si + 1] = need, False
                    break
        elif at == "before":
            pt = norm_word(ev["phrase"]).replace("-", " ")
            for si, s in enumerate(segs):
                if si and norm_word(s["text"]).replace("-", " ").startswith(pt):
                    need = ev["duration"] + 0.08
                    if gaps[si] < need:
                        gaps[si], flex[si] = need, False
                    break
    t = vid["title_duration"]
    starts = []
    for i, s in enumerate(segs):
        t += gaps[i]
        starts.append(t)
        t += s["dur"]
    voice_end = t
    total = voice_end + vid["outro_gap"] + vid["outro_duration"]
    return starts, voice_end, total, sum(flex)


def fit_duration(segments, cfg, sr):
    vid, v = cfg["video"], cfg["voice"]
    lo, hi = vid["min_duration"], vid["max_duration"]
    rate_shift, pause = 0, v["pause"]
    for attempt in range(6):
        segs = synthesize(segments, cfg, rate_shift, sr)
        starts, vend, total, nflex = plan_timeline(segs, cfg, pause)
        if lo <= total <= hi:
            return segs, starts, vend, total, pause, rate_shift
        base_total = total - nflex * pause
        if total > hi:
            p = (hi - 0.4 - base_total) / max(nflex, 1)
            if p >= 0.3:
                pause = p
            else:
                rate_shift += 6
                continue
        else:
            p = (lo + 0.6 - base_total) / max(nflex, 1)
            if p <= 1.1:
                pause = p
            else:
                rate_shift -= 6
                continue
        starts, vend, total, _ = plan_timeline(segs, cfg, pause)
        return segs, starts, vend, total, pause, rate_shift
    return segs, starts, vend, total, pause, rate_shift


# ───────────────────────────── звук ─────────────────────────────

def synth_music_box(sr, length, seed, clean=False):
    """Расстроенная шкатулка: 4 ноты по кругу, металлические обертоны."""
    rng = np.random.default_rng(seed)
    n = int(length * sr)
    out = np.zeros(n + sr * 3, dtype=np.float32)
    notes = [659.25, 523.25, 587.33, 493.88]          # E5 C5 D5 B4 — минорный мотив
    detune = [-27.0, 14.0, -9.0, 33.0]                # каждая нота «своя», расстроенная
    partials = [(1.0, 1.0, 1.0), (2.0, 0.22, 0.6), (5.43, 0.10, 0.25), (8.97, 0.05, 0.12)]
    t, k, step = 0.15, 0, 0.62
    while t < length:
        f0 = notes[k % 4] * 2 ** ((detune[k % 4] - 22) / 1200)
        L = int(2.2 * sr)
        tt = np.arange(L) / sr
        wow = 9.0 * np.sin(2 * np.pi * 0.45 * (t + tt)) / 1200
        y = np.zeros(L, dtype=np.float32)
        for ratio, amp, tau in partials:
            ph = 2 * np.pi * np.cumsum(f0 * ratio * 2 ** wow) / sr
            y += (amp * np.sin(ph) * np.exp(-tt / (1.3 * tau))).astype(np.float32)
        y *= (1 - np.exp(-tt / 0.002)).astype(np.float32)
        vel = 0.75 + 0.25 * rng.random()
        i0 = max(int((t + rng.normal(0, 0.02)) * sr), 0)
        out[i0:i0 + L] += y * vel
        k += 1
        t += step * (1.0 + 0.04 * (k // 4))            # чуть замедляется, «заводка» кончается
        if k % 4 == 0:
            t += 0.55
    if clean:                                          # чистая запись: без динамика видеоняни
        out = fft_filter(out, sr, lo=150)
        out = simple_reverb(out, sr, decay=1.6, mix=0.28, seed=seed + 1)
    else:
        out = fft_filter(out, sr, lo=380, hi=4200)      # из динамика видеоняни
        out = np.tanh(out * 1.6) / 1.6
        out = simple_reverb(out, sr, decay=1.1, mix=0.3, seed=seed + 1)
    return out[:n]


def synth_hum(sr, length, seed):
    """Низкий гул 35–50 Гц, нарастает (в дБ линейно) от -30 до 0 к концу."""
    rng = np.random.default_rng(seed)
    n = int(length * sr)
    t = np.arange(n) / sr
    y = (np.sin(2 * np.pi * 38 * t) + 0.8 * np.sin(2 * np.pi * 46.5 * t + 1.0)
         + 0.35 * np.sin(2 * np.pi * 76 * t) + 0.22 * np.sin(2 * np.pi * 93 * t + 0.5)
         + 0.10 * np.sin(2 * np.pi * 141 * t))           # гармоники — чтобы было слышно на телефоне
    rumble = fft_filter(rng.standard_normal(n).astype(np.float32), sr, lo=25, hi=90)
    y = y + rumble * (0.6 / (rms(rumble) + 1e-9))
    y *= 1 + 0.25 * np.sin(2 * np.pi * 0.17 * t)
    x = t / max(length, 1e-3)
    y *= 10 ** (-30 * (1 - x) / 20) * np.minimum(1, t / 1.0)
    return y.astype(np.float32)


def _place(dst, x, t, sr):
    i = int(t * sr)
    if i < 0:
        x, i = x[-i:], 0
    if i >= len(dst):
        return
    dst[i:i + len(x)] += x[: len(dst) - i]


def synth_hit(sr):
    L = int(3.2 * sr)
    t = np.arange(L) / sr
    f = 31 + 30 * np.exp(-t / 0.10)
    ph = 2 * np.pi * np.cumsum(f) / sr
    env = (1 - np.exp(-t / 0.003)) * np.exp(-t / 0.95)
    y = np.sin(ph) * env + 0.25 * np.sin(2 * ph) * env * np.exp(-t / 0.4)
    rng = np.random.default_rng(3)
    thump = fft_filter(rng.standard_normal(L).astype(np.float32), sr, hi=260) * np.exp(-t / 0.035)
    y = y + thump * 3.0
    y = np.tanh(2.2 * y) / np.tanh(2.2)                 # гармоники — слышно и на телефоне
    y = simple_reverb(y.astype(np.float32), sr, decay=1.8, mix=0.25, seed=5)
    return (y / np.max(np.abs(y)) * db(-3)).astype(np.float32)


def synth_click(sr, rng):
    L = int(0.08 * sr)
    t = np.arange(L) / sr
    y = np.zeros(L, dtype=np.float32)
    for off in (0.0, 0.012 + rng.random() * 0.006):
        i = int(off * sr)
        tt = t[: L - i]
        y[i:] += (rng.standard_normal(L - i) * np.exp(-tt / 0.004)).astype(np.float32)
    return fft_filter(y, sr, lo=1500, hi=6000)


def synth_static_burst(sr, dur, rng):
    L = int(dur * sr)
    y = fft_filter(rng.standard_normal(L).astype(np.float32), sr, lo=900, hi=6500)
    blk = int(sr * 0.006)
    gate = np.repeat((rng.random(L // blk + 1) > 0.35).astype(np.float32), blk)[:L]
    gate = np.convolve(gate, np.ones(48) / 48, mode="same")
    env = np.minimum(1, np.arange(L) / (0.01 * sr)) * np.minimum(1, (L - np.arange(L)) / (0.03 * sr))
    return (y * gate * env).astype(np.float32)


def compress_voice(x, sr, target_rms_db, peak_db):
    """Мягкий компрессор голоса (блоки 5 мс, атака ~5 мс, восстановление ~80 мс) + выход на целевую громкость."""
    blk = int(sr * 0.005)
    nb = len(x) // blk
    if nb < 4:
        return x
    r = np.sqrt(np.mean(x[: nb * blk].reshape(nb, blk).astype(np.float64) ** 2, axis=1) + 1e-12)
    lvl = 20 * np.log10(r)
    act = active_rms(x, sr)
    thr = to_db(act) + 1.0                       # порог чуть выше средней громкости речи
    gr = np.minimum(0.0, (thr - lvl) * (1 - 1 / 3.0))   # 3:1
    rel = math.exp(-0.005 / 0.08)
    g = np.empty_like(gr)
    cur = 0.0
    for k in range(nb):                          # атака мгновенная по блоку, плавное восстановление
        cur = gr[k] if gr[k] < cur else gr[k] + (cur - gr[k]) * rel
        g[k] = cur
    gain = np.repeat(10 ** (g / 20), blk)
    gain = np.concatenate([gain, np.full(len(x) - len(gain), gain[-1])]).astype(np.float32)
    y = x * gain
    y *= db(target_rms_db) / (active_rms(y, sr) + 1e-9)
    lim = db(peak_db)
    over = np.abs(y) > lim * 0.8
    k0 = lim * 0.8
    y[over] = np.sign(y[over]) * (k0 + (lim - k0) * np.tanh((np.abs(y[over]) - k0) / (lim - k0)))
    return y.astype(np.float32)


def build_audio(segs, starts, total, ev, cfg, sr, seed):
    a = cfg["audio"]
    v = cfg["voice"]
    rng = np.random.default_rng(seed)
    N = int(round(total * sr))
    sfx_below = a.get("sfx_below_voice_db", 12)

    # Голос
    narr_peak = max((np.max(np.abs(s["audio"])) for s in segs if not s["quote"]), default=1.0)
    narr_act = np.mean([active_rms(s["audio"], sr) for s in segs if not s["quote"]] or [0.1])
    g_narr = min(db(a["voice_peak_db"]) / narr_peak, db(a.get("voice_rms_db", -16.5)) / (narr_act + 1e-9))
    narr_rms = np.mean([active_rms(s["audio"] * g_narr, sr) for s in segs if not s["quote"]] or [0.1])
    voice = np.zeros(N, dtype=np.float32)
    for s, st in zip(segs, starts):
        x = s["audio"] * g_narr
        if s["quote"]:
            x = whisperize(s["audio"], sr, s.get("whisper", v["quote_whisper"]))
            x = x * (narr_rms * db(v["quote_level_db"]) / (active_rms(x, sr) + 1e-9))
        _place(voice, x, st, sr)
    voice = compress_voice(voice, sr, a.get("voice_rms_db", -16.5), a["voice_peak_db"])
    voice_rms = active_rms(voice, sr)
    vdb = to_db(voice_rms)
    stats = [("голос", vdb)]

    def rel(x, below):  # громкость относительно голоса
        return x * (voice_rms * db(-below) / (active_rms(x, sr) + 1e-9))

    # Шум эфира видеоняни
    noise = rng.standard_normal(N).astype(np.float32)
    noise = fft_filter(noise, sr, lo=60, hi=11000, order=1)
    noise *= db(a["noise_db"]) / rms(noise)
    stats.append(("шум эфира", to_db(rms(noise))))

    # Редкие помехи
    crackles = np.zeros(N, dtype=np.float32)
    crackle_times = []
    t = 0.3
    lo_i, hi_i = a["crackle_every"]
    loudest = -120.0
    while t < total - 1.0:
        if rng.random() < 0.6:
            c = synth_click(sr, rng)
            c *= db(-22 - 6 * rng.random()) / (np.max(np.abs(c)) + 1e-9)
            dur = 0.05
        else:
            dur = 0.08 + 0.2 * rng.random()
            c = rel(synth_static_burst(sr, dur, rng), sfx_below + 2 + 4 * rng.random())
        loudest = max(loudest, to_db(active_rms(c, sr)))
        _place(crackles, c, t, sr)
        crackle_times.append((t, dur))
        t += lo_i + (hi_i - lo_i) * rng.random()
    stats.append(("треск (громчайший)", loudest))

    # Шкатулки
    music = np.zeros(N, dtype=np.float32)
    for mi, m in enumerate(ev.get("music", [])):
        mb = synth_music_box(sr, m["t1"] - m["t0"], seed + 11 + mi, clean=m["clean"])
        mb = rel(mb, max(m["below"], 12.0))
        f = int(0.008 * sr)
        mb[-f:] *= np.linspace(1, 0, f, dtype=np.float32)   # резкий обрыв
        _place(music, mb, m["t0"], sr)
        stats.append(("шкатулка" + (" (чистая)" if m["clean"] else ""), to_db(active_rms(mb, sr))))

    # Гул
    hum = np.zeros(N, dtype=np.float32)
    if ev.get("hum"):
        h0, h1, below = ev["hum"]
        hm = synth_hum(sr, h1 - h0, seed + 21)
        tail = hm[-int(1.5 * sr):]
        hm *= voice_rms * db(-max(below, 12.0)) / (rms(tail) + 1e-9)
        f = int(0.005 * sr)
        hm[-f:] *= np.linspace(1, 0, f, dtype=np.float32)   # обрыв
        _place(hum, hm, h0, sr)
        stats.append(("гул (в конце)", to_db(rms(hm[-int(1.5 * sr):]))))

    # Звуковые эффекты
    sfx = np.zeros(N, dtype=np.float32)
    for ft in ev.get("flash", []) + ev.get("switch", []) + ev.get("white", []):
        _place(sfx, rel(synth_static_burst(sr, 0.4, rng), sfx_below + 2), ft - 0.05, sr)
    for lt in ev.get("light", []):
        _place(sfx, rel(synth_click(sr, rng), sfx_below), lt - 0.05, sr)
    if ev.get("hit") is not None:
        h = rel(synth_hit(sr), sfx_below)
        _place(sfx, h, ev["hit"], sr)
        stats.append(("удар", to_db(active_rms(h, sr))))

    # Резкая тишина: глушим всё, кроме голоса и эффектов
    gate = np.ones(N, dtype=np.float32)
    for s0, s1, hold in ev.get("silence", []):
        i0, i1 = int(s0 * sr), int(s1 * sr)
        f = int(0.004 * sr)
        gate[i0:i0 + f] = np.minimum(gate[i0:i0 + f], np.linspace(1, 0, len(gate[i0:i0 + f])))
        if hold:
            gate[i0 + f:] = 0
        else:
            gate[i0 + f:i1] = 0
            r = int(0.9 * sr)
            gate[i1:i1 + r] = np.linspace(0, 1, len(gate[i1:i1 + r]))
    if ev.get("outro"):
        o0 = int(ev["outro"] * sr)
        fade = np.ones(N, dtype=np.float32)
        fade[o0:] = np.linspace(1, 0.15, N - o0)
        gate *= fade

    mix = voice + (noise + crackles + music + hum) * gate + sfx
    peak = np.max(np.abs(mix))
    th = 0.9
    over = np.abs(mix) > th
    mix[over] = np.sign(mix[over]) * (th + (1 - th) * np.tanh((np.abs(mix[over]) - th) / (1 - th)))
    stats.append(("пик микса", to_db(peak)))
    return mix.astype(np.float32), crackle_times, stats


# ───────────────────────────── графика: подготовка ─────────────────────────────

def figure_mask(h, blur):
    """Силуэт женщины в длинном платье (маска L)."""
    w = int(h * 0.42)
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    cx = w / 2
    hr = h * 0.055
    d.ellipse([cx - hr * 0.85, h * 0.03, cx + hr * 0.85, h * 0.03 + hr * 2.2], fill=255)      # голова
    d.polygon([(cx - hr * 0.9, h * 0.07), (cx + hr * 0.9, h * 0.07),                        # волосы
               (cx + hr * 1.25, h * 0.26), (cx - hr * 1.25, h * 0.26)], fill=255)
    d.rectangle([cx - hr * 0.35, h * 0.13, cx + hr * 0.35, h * 0.18], fill=255)              # шея
    d.polygon([(cx - w * 0.22, h * 0.19), (cx + w * 0.22, h * 0.19),                         # плечи/корпус
               (cx + w * 0.17, h * 0.42), (cx - w * 0.17, h * 0.42)], fill=255)
    d.polygon([(cx - w * 0.17, h * 0.40), (cx + w * 0.17, h * 0.40),                         # платье до пола
               (cx + w * 0.40, h * 0.99), (cx - w * 0.40, h * 0.99)], fill=255)
    for sgn in (-1, 1):                                                                      # руки вдоль тела
        d.polygon([(cx + sgn * w * 0.21, h * 0.20), (cx + sgn * w * 0.27, h * 0.22),
                   (cx + sgn * w * 0.28, h * 0.60), (cx + sgn * w * 0.23, h * 0.61)], fill=255)
    return im.filter(ImageFilter.GaussianBlur(blur))


def tall_mask(h, blur):
    """Высокая худая фигура: маленькая голова, длинные руки ниже колен."""
    w = int(h * 0.30)
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    cx = w / 2
    hr = h * 0.038
    d.ellipse([cx - hr * 0.8, h * 0.01, cx + hr * 0.8, h * 0.01 + hr * 2.3], fill=255)
    d.rectangle([cx - hr * 0.3, h * 0.08, cx + hr * 0.3, h * 0.11], fill=255)
    d.polygon([(cx - w * 0.26, h * 0.11), (cx + w * 0.26, h * 0.11),
               (cx + w * 0.17, h * 0.55), (cx - w * 0.17, h * 0.55)], fill=255)
    for sgn in (-1, 1):
        d.polygon([(cx + sgn * w * 0.10, h * 0.55), (cx + sgn * w * 0.18, h * 0.55),
                   (cx + sgn * w * 0.15, h * 0.99), (cx + sgn * w * 0.07, h * 0.99)], fill=255)
        d.polygon([(cx + sgn * w * 0.24, h * 0.12), (cx + sgn * w * 0.32, h * 0.14),
                   (cx + sgn * w * 0.30, h * 0.68), (cx + sgn * w * 0.24, h * 0.69)], fill=255)
    return im.filter(ImageFilter.GaussianBlur(blur))


def make_night_base(W, H, seed, day=False):
    """Детская: стены, пол, окно, смутная кроватка. day=True — дневная камера."""
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(0, 1, W)[None, :]
    floor_y = 0.70
    if day:
        lum = 0.46 + 0.04 * y - 0.10 * x
        lum = np.where(y > floor_y, 0.56 + 0.08 * (y - floor_y) - 0.08 * x, lum)
        lum = lum + 0.03 * (np.abs(x - 0.5) < 0.003) * (y < floor_y)
        r = np.sqrt(((x - 0.2) / 0.9) ** 2 + ((y - 0.35) / 0.7) ** 2)
        lum = lum * (0.85 + 0.25 * np.exp(-r ** 2 * 2.0))
        win, frame_c, curt, col, blanket, head, shadow = 250, 200, 180, 222, 190, 200, 150
    else:
        lum = 0.13 + 0.05 * y + 0 * x
        lum = np.where(y > floor_y, 0.20 + 0.10 * (y - floor_y), lum)
        lum = lum + 0.025 * (np.abs(x - 0.5) < 0.003) * (y < floor_y)
        r = np.sqrt(((x - 0.5) / 0.75) ** 2 + ((y - 0.58) / 0.55) ** 2)
        lum = lum * (0.55 + 0.75 * np.exp(-r ** 2 * 1.6))
        win, frame_c, curt, col, blanket, head, shadow = 62, 34, 44, 118, 96, 104, 50
    im = Image.fromarray(np.clip(lum * 255, 0, 255).astype(np.uint8), "L")
    d = ImageDraw.Draw(im)
    wx0, wy0, wx1, wy1 = int(W * 0.08), int(H * 0.22), int(W * 0.34), int(H * 0.44)
    d.rectangle([wx0, wy0, wx1, wy1], fill=win)
    d.line([(wx0 + wx1) // 2, wy0, (wx0 + wx1) // 2, wy1], fill=frame_c, width=10)
    d.line([wx0, (wy0 + wy1) // 2, wx1, (wy0 + wy1) // 2], fill=frame_c, width=10)
    d.rectangle([wx0 - 30, wy0 - 20, wx0 + 40, wy1 + 60], fill=curt)
    cx0, cx1 = int(W * 0.24), int(W * 0.76)
    top, bot = int(H * 0.53), int(H * 0.70)
    d.rectangle([cx0 - 18, top - 70, cx0 + 6, bot + 70], fill=col)
    d.rectangle([cx1 - 6, top - 70, cx1 + 18, bot + 70], fill=col)
    d.rectangle([cx0, top - 14, cx1, top + 10], fill=min(255, col + 10))
    d.rectangle([cx0, bot - 30, cx1, bot - 6], fill=col)
    for bx in range(cx0 + 30, cx1 - 10, 38):
        d.rectangle([bx, top, bx + 9, bot - 20], fill=col - 15)
    d.ellipse([cx0 + 70, bot - 120, cx0 + 330, bot - 34], fill=blanket)
    d.ellipse([cx0 + 300, bot - 110, cx0 + 380, bot - 44], fill=head)
    d.rectangle([cx0 - 10, bot + 70, cx1 + 10, bot + 110], fill=shadow)
    im = im.filter(ImageFilter.GaussianBlur(7))
    im = im.resize((W // 3, H // 3), Image.BILINEAR).resize((W, H), Image.BILINEAR)
    base = np.asarray(im).astype(np.float32) / 255.0
    base += rng.normal(0, 0.006, base.shape).astype(np.float32)
    return base


def make_cam2_base(W, H, seed):
    """CAM 02: детская сверху из угла, кроватка сверху, внизу слева — тёмный угол."""
    rng = np.random.default_rng(seed + 5)
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(0, 1, W)[None, :]
    wall_line = 0.30 - 0.08 * x                          # стык стены и пола под углом
    lum = np.where(y < wall_line, 0.11 + 0.04 * y, 0.19 + 0.06 * (y - 0.3))
    r = np.sqrt(((x - 0.64) / 0.6) ** 2 + ((y - 0.52) / 0.45) ** 2)
    lum = lum * (0.45 + 0.85 * np.exp(-r ** 2 * 1.5))    # ИК-пятно на кроватке
    # тёмный угол комнаты внизу слева
    cr = np.sqrt((x / 0.42) ** 2 + ((1 - y) / 0.48) ** 2)
    lum = lum * (0.35 + 0.65 * np.clip((cr - 0.55) / 0.6, 0, 1))
    im = Image.fromarray(np.clip(lum * 255, 0, 255).astype(np.uint8), "L")
    d = ImageDraw.Draw(im)
    # шов между стенами в углу
    d.line([(int(W * 0.30), int(H * 0.56)), (int(W * 0.24), H)], fill=12, width=8)
    d.line([(0, int(H * 0.50)), (int(W * 0.30), int(H * 0.56))], fill=14, width=6)
    # ковёр
    d.ellipse([int(W * 0.34), int(H * 0.70), int(W * 0.92), int(H * 0.86)], fill=58)
    # кроватка сверху (перспектива): бортики с прутьями, матрас, одеяльце
    tl, tr = (int(W * 0.46), int(H * 0.39)), (int(W * 0.90), int(H * 0.37))
    br, bl = (int(W * 0.94), int(H * 0.60)), (int(W * 0.50), int(H * 0.635))
    ins = 34

    def lerp(p, q, k):
        return (p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k)
    itl, itr = (tl[0] + ins, tl[1] + ins), (tr[0] - ins, tr[1] + ins)
    ibr, ibl = (br[0] - ins, br[1] - ins), (bl[0] + ins, bl[1] - ins)
    d.polygon([bl, br, (br[0] - 4, br[1] + 70), (bl[0] - 4, bl[1] + 70)], fill=40)      # тень под кроваткой
    d.polygon([itl, itr, ibr, ibl], fill=92)                                              # матрас
    for (o0, o1, i0, i1) in ((tl, tr, itl, itr), (tr, br, itr, ibr), (br, bl, ibr, ibl), (bl, tl, ibl, itl)):
        L = math.hypot(o1[0] - o0[0], o1[1] - o0[1])
        n = max(4, int(L / 30))
        for k in range(n + 1):
            d.line([lerp(o0, o1, k / n), lerp(i0, i1, k / n)], fill=150, width=6)       # прутья
    d.line([tl, tr, br, bl, tl], fill=176, width=12)                                      # верхний бортик
    d.line([itl, itr, ibr, ibl, itl], fill=128, width=6)
    for c in (tl, tr, br, bl):
        d.ellipse([c[0] - 14, c[1] - 14, c[0] + 14, c[1] + 14], fill=180)                # стойки
    d.ellipse([int(W * 0.58), int(H * 0.455), int(W * 0.82), int(H * 0.565)], fill=132)   # одеяльце
    d.ellipse([int(W * 0.78), int(H * 0.44), int(W * 0.855), int(H * 0.49)], fill=142)    # голова малыша
    im = im.filter(ImageFilter.GaussianBlur(7))
    im = im.resize((W // 3, H // 3), Image.BILINEAR).resize((W, H), Image.BILINEAR)
    base = np.asarray(im).astype(np.float32) / 255.0
    base += rng.normal(0, 0.006, base.shape).astype(np.float32)
    return base


def make_vignette(W, H, strength):
    y = np.linspace(-1, 1, H)[:, None]
    x = np.linspace(-1, 1, W)[None, :] * (W / H) * 1.25
    r = np.sqrt(x ** 2 + y ** 2)
    v = 1 - strength * np.clip((r - 0.45) / 0.85, 0, 1) ** 1.5
    return v.astype(np.float32)


def layout_text_lines(words, font, max_w, grow=0.0):
    space = font.getlength(" ")
    lines, cur, cur_w = [], [], 0.0
    for w in words:
        wl = font.getlength(w) * (1 + grow)
        add = wl if not cur else cur_w + space + wl
        if cur and add > max_w:
            lines.append(cur)
            cur, cur_w = [w], wl
        else:
            cur.append(w)
            cur_w = add
    if cur:
        lines.append(cur)
    if len(lines) == 2:  # балансируем две строки, чтобы не висело одно слово
        allw = lines[0] + lines[1]
        wl = [font.getlength(w) * (1 + grow) for w in allw]
        best = None
        for k in range(1, len(allw)):
            a = sum(wl[:k]) + space * (k - 1)
            b = sum(wl[k:]) + space * (len(allw) - k - 1)
            if max(a, b) <= max_w and (best is None or max(a, b) < best[0]):
                best = (max(a, b), k)
        if best:
            lines = [allw[:best[1]], allw[best[1]:]]
    return lines, space


def build_sub_chunks(words, cfg, font, W, H):
    sc = cfg["subtitles"]
    wmax = sc["words_max"]
    chunks = []
    seg_ids = sorted(set(w["seg"] for w in words))
    for sid in seg_ids:
        ws = [w for w in words if w["seg"] == sid]
        n = len(ws)
        k = math.ceil(n / wmax)
        sizes = [n // k + (1 if i < n % k else 0) for i in range(k)]
        p = 0
        for sz in sizes:
            chunks.append({"words": ws[p:p + sz]})
            p += sz
        # короткий предлог/союз в конце группы переносим в следующую группу
        cs = chunks[-k:]
        for a, b in zip(cs, cs[1:]):
            if len(a["words"]) > 1 and len(norm_word(a["words"][-1]["text"])) <= 2:
                b["words"].insert(0, a["words"].pop())
    for i, c in enumerate(chunks):
        first, last = c["words"][0], c["words"][-1]
        c["t0"] = first["start"] - 0.06
        nxt = chunks[i + 1]["words"][0]["start"] - 0.06 if i + 1 < len(chunks) else None
        end = last["end"] + 0.35
        c["t1"] = nxt if (nxt is not None and nxt - last["end"] < 0.6) else (min(end, nxt) if nxt else end)
    # раскладка
    max_w = W - 2 * 80
    lh = sc["size"] * 1.18
    for c in chunks:
        texts = [w["disp"] for w in c["words"]]
        grow = sc["pulse"] * 1.3  # запас места, чтобы пульсирующее слово не налезало на соседей
        lines, space = layout_text_lines(texts, font, max_w, grow)
        cy0 = H * sc["y"] - (len(lines) - 1) * lh / 2
        items, wi = [], 0
        for li, line in enumerate(lines):
            widths = [font.getlength(t) * (1 + grow) for t in line]
            tot = sum(widths) + space * (len(line) - 1)
            x = W / 2 - tot / 2
            for t, wl in zip(line, widths):
                w = c["words"][wi]
                items.append({"text": t, "cx": x + wl / 2, "cy": cy0 + li * lh,
                              "start": w["start"], "quote": w["quote"]})
                x += wl + space
                wi += 1
        c["items"] = items
    return chunks


def make_title_overlay(title, cfg, W):
    c = cfg["colors"]
    sc = cfg["subtitles"]
    size = 118
    while True:
        font = load_font(sc["fonts"], size)
        lines, _ = layout_text_lines(title.upper().split(), font, W - 160)
        if len(lines) <= 3 or size < 60:
            break
        size -= 8
    lh = size * 1.15
    hgt = int(lh * len(lines) + 120)
    im = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, line in enumerate(lines):
        d.text((W / 2, 60 + lh * (i + 0.5)), " ".join(line), font=font, anchor="mm",
               fill=hex_rgb(c["title"]), stroke_width=10, stroke_fill=hex_rgb(c["stroke"]))
    d.rectangle([W / 2 - 70, hgt - 26, W / 2 + 70, hgt - 18], fill=hex_rgb(c["subtitle_active"]))
    return im


def make_outro_overlay(cfg):
    c, vid, sc = cfg["colors"], cfg["video"], cfg["subtitles"]
    bw, bh = 860, 400
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([4, 4, bw - 5, bh - 5], radius=36, fill=hex_rgb(c["outro_box"]) + (235,),
                        outline=hex_rgb(c["outro_accent"]), width=7)
    f1 = load_font(sc["fonts"], 132)
    f2 = load_font(sc["fonts"], 76)
    d.text((bw / 2, bh * 0.36), vid["outro_text"], font=f1, anchor="mm",
           fill=hex_rgb(c["outro_accent"]), stroke_width=4, stroke_fill=(0, 0, 0))
    d.text((bw / 2, bh * 0.72), vid["outro_subtext"], font=f2, anchor="mm",
           fill=hex_rgb(c["outro_text"]), stroke_width=4, stroke_fill=(0, 0, 0))
    return im


def paste_alpha(img, overlay, xy, alpha):
    if alpha <= 0.01:
        return
    a = overlay.getchannel("A")
    if alpha < 0.999:
        a = a.point(lambda v: int(v * alpha))
    img.paste(overlay.convert("RGB"), xy, a)


def current_cam(t):
    cam, label = G["cams"][0][1], G["cams"][0][2]
    for ct, c, lab in G["cams"]:
        if t >= ct:
            cam, label = c, lab
    return cam, label


def ghost_state(gh, t):
    """Возвращает (прозрачность, масштаб, импульс мерцания)."""
    if t < gh["t0"]:
        return 0.0, 1.0, 0.0
    up = smoothstep((t - gh["t0"]) / gh["fin"]) if gh["fin"] > 0 else 1.0
    down = 1.0 if gh["t1"] is None else 1 - smoothstep((t - gh["t1"]) / max(gh["fout"], 1e-3))
    a = up * down
    scale, pulse = 1.0, 0.0
    if gh["grow_t"] is not None and gh["grow_t"] > gh["t0"]:
        gf = smoothstep((t - gh["t0"]) / (gh["grow_t"] - gh["t0"]))
        a *= 0.55 + 0.45 * gf
        scale = 1 + (gh["grow_to"] - 1) * gf
    if gh["flicker"]:
        ph = (t - gh["t0"]) % gh["flicker"]
        pulse = math.exp(-ph / 0.07)
    return a, scale, pulse


def ghost_masks(gh, scale):
    key = (id(gh), round(scale, 3))
    cache = G.setdefault("_gcache", {})
    if key not in cache:
        h = int(gh["h"] * G["H"] * scale)
        fn = tall_mask if gh["kind"] == "tall" else figure_mask
        inner = np.asarray(fn(h, gh["blur"])).astype(np.float32) / 255
        outer = np.asarray(fn(h, gh["blur"] * 2.6)).astype(np.float32) / 255 if gh["dark"] else None
        if len(cache) > 400:
            cache.clear()
        cache[key] = (inner, outer)
    return cache[key]


def apply_ghost(lum, gh, a, scale, pulse):
    W, H = G["W"], G["H"]
    inner, outer = ghost_masks(gh, scale)
    h, w = inner.shape
    x0 = int(gh["x"] * W - w / 2)
    y1 = int(gh["y"] * H)
    y0 = y1 - h
    sx0, sy0 = max(0, -x0), max(0, -y0)
    X0, Y0 = max(0, x0), max(0, y0)
    X1, Y1 = min(W, x0 + w), min(H, y1)
    if X1 <= X0 or Y1 <= Y0:
        return
    m = inner[sy0:sy0 + (Y1 - Y0), sx0:sx0 + (X1 - X0)]
    reg = lum[Y0:Y1, X0:X1]
    if gh["dark"]:
        o = outer[sy0:sy0 + (Y1 - Y0), sx0:sx0 + (X1 - X0)]
        contour = np.clip(o - m * 0.85, 0, 1)
        reg *= 1 - gh["strength"] * m * a
        reg += contour * (0.05 + 0.10 * pulse) * a
    else:
        reg += m * (gh["strength"] * a * (1 + 0.5 * pulse))


def day_factor(t):
    d = 0.0
    for t0, t1, fin, fout in G["days"]:
        if t >= t0:
            up = smoothstep((t - t0) / fin)
            down = 1.0 if t1 is None else 1 - smoothstep((t - t1) / fout)
            d = max(d, up * down)
    return d


def zoom_f(arr, z):
    W, H = G["W"], G["H"]
    if z <= 1.001:
        return arr
    bw, bh = W / z, H / z
    im = Image.fromarray(arr, "F")
    return np.asarray(im.resize((W, H), Image.BILINEAR, box=((W - bw) / 2, (H - bh) / 2, (W + bw) / 2, (H + bh) / 2)))


# ───────────────────────────── рендер кадра ─────────────────────────────

def glitch(arr, g, rng):
    H, W = arr.shape[:2]
    nb = int(2 + g * 14)
    for _ in range(nb):
        if rng.random() > 0.25 + 0.75 * g:
            continue
        y = int(rng.integers(0, H - 8))
        h = int(rng.integers(4, 16 + int(140 * g)))
        s = int(rng.integers(-int(170 * g) - 6, int(170 * g) + 7))
        arr[y:y + h] = np.roll(arr[y:y + h], s, axis=1)
    sh = int(16 * g * rng.random())
    if sh:
        arr[:, :, 0] = np.roll(arr[:, :, 0], sh, axis=1)
        arr[:, :, 2] = np.roll(arr[:, :, 2], -sh, axis=1)
    for _ in range(int(g * 7)):
        y = int(rng.integers(0, H - 3))
        arr[y:y + int(rng.integers(1, 4))] = rng.integers(90, 255, (1, W, 1), dtype=np.uint8)


def render_frame(i, bg_bytes=None):
    W, H, fps = G["W"], G["H"], G["fps"]
    t = i / fps
    if i in G["white"]:
        return b"\xff" * (W * H * 3)
    rng = np.random.default_rng(G["seed"] * 1_000_003 + i)
    tint = G["tint"]
    cam, label = current_cam(t)

    # 1. Фон (+ зум)
    z = 1.0
    if G["zoom"]:
        z0, amt = G["zoom"]
        z = 1 + amt * smoothstep((t - z0) / 1.6)
    d = day_factor(t) if cam == 1 else 0.0
    if bg_bytes is None:
        lum = G["bases"][cam]
        copied = False
        if d < 0.999:
            for gh in G["ghosts"]:
                if gh["cam"] != cam:
                    continue
                a, sc, pulse = ghost_state(gh, t)
                if a <= 0.003:
                    continue
                if not copied:
                    lum, copied = lum.copy(), True
                apply_ghost(lum, gh, a, sc, pulse)
        breathe = 0.96 + 0.04 * math.sin(2 * math.pi * 0.21 * t) + 0.015 * rng.standard_normal()
        band_y = ((t * 0.09) % 1.3 - 0.15) * H
        band = (0.035 * np.exp(-((G["yy"] - band_y) / 55.0) ** 2)).astype(np.float32)
        if d < 0.999:
            ln = zoom_f(lum * breathe, z) + band
            rgb = ln[:, :, None] * tint[None, None, :]
            if d > 0.001:
                rgb = rgb * (1 - d)
        if d > 0.001:
            ld = zoom_f(G["day_base"] * (0.98 + 0.02 * breathe), z)
            dr = ld[:, :, None] * (G["day_tint"] * d)[None, None, :]
            rgb = dr if d >= 0.999 else rgb + dr
        grain = G["gen_grain"] * (1 - 0.6 * d)
    else:
        src = np.frombuffer(bg_bytes, dtype=np.uint8).reshape(H, W, 3)
        if z > 1.001:
            im = Image.frombuffer("RGB", (W, H), bg_bytes, "raw", "RGB", 0, 1)
            bw, bh = W / z, H / z
            im = im.resize((W, H), Image.BILINEAR, box=((W - bw) / 2, (H - bh) / 2, (W + bw) / 2, (H + bh) / 2))
            src = np.asarray(im)
        rgb = src.astype(np.float32)
        grain = G["vid_grain"]

    # 2. Мерцание + белый силуэт
    bright = 1.0
    for ft in G["flash"]:
        if ft - 0.12 <= t <= ft + G["flash_dur"] + 0.35:
            bright *= 0.45 + 1.0 * rng.random()
        if ft <= t <= ft + G["flash_dur"]:
            if rng.random() > 0.2:
                rgb = rgb + G["flash_img"][:, :, None] * (255 * (0.75 + 0.25 * rng.random()))
    for lt in G["light"]:
        if lt - 0.02 <= t <= lt + 1.2:
            k = 2.2 * math.exp(-max(0.0, t - lt) / 0.22)
            rgb = rgb * (1 + k) + 90 * k
    shake = 0
    if G["hit"] is not None and G["hit"] <= t <= G["hit"] + 0.35:
        shake = int(rng.integers(-14, 15) * (1 - (t - G["hit"]) / 0.35))
        bright *= 0.75

    rgb = rgb * (G["vignette"][:, :, None] * bright)
    gi = int(rng.integers(0, len(G["noise"])))
    nz = G["noise"][gi]
    if rng.random() < 0.5:
        nz = nz[::-1]
    rgb = rgb + (nz.astype(np.float32) * (grain / 40.0))[:, :, None]
    frame = np.clip(rgb, 0, 255).astype(np.uint8)
    if shake:
        frame = np.roll(frame, shake, axis=0)

    img = Image.fromarray(frame, "RGB")

    # 3. Интерфейс камеры и приложения
    if G["hud"]:
        draw_hud(img, t, label)
    if G["card"]:
        draw_card(img, t)

    # 4. Помехи, дрожание, затемнение
    g = 0.0
    for ct, cd in G["crackles"]:
        if ct <= t <= ct + cd + 0.05:
            g = max(g, 0.22)
    for st in G["switch"]:
        if st - 0.08 <= t <= st + 0.22:
            g = max(g, 0.85)
    e0, e1 = G["ending"]
    if t >= e0:
        p = smoothstep((t - e0) / max(e1 - e0, 0.1))
        g = max(g, 0.12 + 0.5 * p ** 1.4 + (0.35 if rng.random() < 0.08 + 0.2 * p else 0))
    if G["hit"] is not None and G["hit"] <= t <= G["hit"] + 0.25:
        g = max(g, 0.8)
    dark = 1.0
    if t >= G["dark_from"]:
        dark = 1 - 0.93 * smoothstep((t - G["dark_from"]) / max(G["outro_t"] - G["dark_from"], 0.1))
    if t >= G["outro_t"]:
        g = 0.1 if rng.random() < 0.7 else 0.0
        dark = 0.07
    sx = sy = 0
    for s0, s1, amp in G["shake"]:
        if s0 <= t <= s1:
            k = amp * (0.5 + 0.5 * smoothstep((t - s0) / 0.6))
            sx, sy = int(rng.integers(-k, k + 1)), int(rng.integers(-k, k + 1))
    if g > 0 or dark < 1 or sx or sy:
        arr = np.array(img)
        if sx or sy:
            arr = np.roll(arr, (sy, sx), axis=(0, 1))
        if g > 0:
            glitch(arr, g, rng)
        if dark < 1:
            arr = (arr.astype(np.float32) * dark).astype(np.uint8)
        img = Image.fromarray(arr, "RGB")

    # 5. Заголовок, субтитры, плашка
    td = G["title_dur"]
    if t < td:
        a = 1.0 if t < td - 0.4 else max(0.0, (td - t) / 0.4)
        if t < 0.25:
            a *= 0.5 + 0.5 * (rng.random() > 0.3)
        ov = G["title_img"]
        paste_alpha(img, ov, (0, int(H * 0.42 - ov.height / 2)), a)
    draw_subs(img, t)
    if t >= G["outro_t"]:
        a = smoothstep((t - G["outro_t"]) / 0.25)
        ov = G["outro_img"]
        jitter = int(rng.integers(-6, 7)) if t - G["outro_t"] < 0.2 else 0
        paste_alpha(img, ov, ((W - ov.width) // 2 + jitter, int(H * 0.45 - ov.height / 2)), a)
    return img.tobytes()


def draw_hud(img, t, label):
    W, H = G["W"], G["H"]
    d = ImageDraw.Draw(img)
    col = G["hud_col"]
    m, L, lw = 64, 96, 6
    for (x, y, sx, sy) in ((m, m + 40, 1, 1), (W - m, m + 40, -1, 1), (m, H - m - 260, 1, -1), (W - m, H - m - 260, -1, -1)):
        d.line([(x, y), (x + sx * L, y)], fill=col, width=lw)
        d.line([(x, y), (x, y + sy * L)], fill=col, width=lw)
    f = G["hud_font"]
    if (t % 1.0) < 0.6:
        d.ellipse([m + 34, m + 84, m + 70, m + 120], fill=G["rec_col"])
    d.text((m + 86, m + 102), "REC", font=f, fill=col, anchor="lm")
    d.text((W - m - 34, m + 102), timecode_at(t), font=f, fill=col, anchor="rm")
    d.text((m + 34, H - m - 300), label, font=G["hud_small"], fill=col, anchor="lm")
    bx, by = W - m - 34 - 92, H - m - 322
    d.rectangle([bx, by, bx + 80, by + 40], outline=col, width=4)
    d.rectangle([bx + 80, by + 12, bx + 88, by + 28], fill=col)
    d.rectangle([bx + 8, by + 8, bx + 30, by + 32], fill=col)


def timecode_at(t):
    secs = G["tcs"][0][1]
    base_t = 0.0
    for tt, s in G["tcs"]:
        if t >= tt:
            secs, base_t = s, tt
    v = int(secs + (t - base_t)) % 86400
    return f"{v // 3600:02d}:{v // 60 % 60:02d}:{v % 60:02d}"


def _mixc(c, bg, k):
    return tuple(int(bg[j] + (c[j] - bg[j]) * k) for j in range(3))


def draw_card(img, t):
    """Карточка приложения няни: список подключённых устройств."""
    C = G["card"]
    if t < C["t0"]:
        return
    a = smoothstep((t - C["t0"]) / 0.3)
    if t >= G["outro_t"]:
        return
    W, H = G["W"], G["H"]
    cw = 900
    pad = 40
    row_h, gap = 128, 20
    n = len(C["rows"])
    ch = 150 + n * (row_h + gap) + 150
    panel = C["panel"]
    ov = Image.new("RGB", (cw, ch), (0, 0, 0))
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=44, fill=255)
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=44, fill=panel, outline=C["line"], width=3)
    d.text((pad + 8, 78), C["title"], font=C["f_title"], fill=C["text"], anchor="lm")
    d.line([(pad, 140), (cw - pad, 140)], fill=C["line"], width=3)
    y = 165
    for r in C["rows"]:
        k = smoothstep((t - r["t"]) / 0.3)
        if k > 0:
            alert = r["style"] == "alert"
            rowbg = C["row"]
            tc = C["alert_text"] if alert else C["muted"]
            d.rounded_rectangle([pad - 4, y, cw - pad + 4, y + row_h], radius=28, fill=_mixc(rowbg, panel, k),
                                outline=_mixc(C["alert"], panel, k) if alert else None, width=6 if alert else 0)
            ic = _mixc(C["alert"] if alert else C["muted"], rowbg, k)
            ix, iy = pad + 36, y + row_h / 2
            d.rounded_rectangle([ix, iy - 34, ix + 42, iy + 34], radius=8, outline=ic, width=5)
            d.ellipse([ix + 16, iy + 20, ix + 26, iy + 30], fill=ic)
            d.text((ix + 82, iy), r["name"], font=C["f_row"], fill=_mixc(tc, rowbg, k), anchor="lm")
        y += row_h + gap
    k = smoothstep((t - C["note_t"]) / 0.3) if C["note_t"] is not None else 0
    if k > 0 and C["note"]:
        d.text((pad + 8, y + 22), C["note"], font=C["f_small"], fill=_mixc(C["muted"], panel, k), anchor="lm")
    k = smoothstep((t - C["status_t"]) / 0.25) if C["status_t"] is not None else 0
    if k > 0 and C["status"]:
        sy = y + 92
        if ((t - C["status_t"]) % 1.0) < 0.6:
            d.ellipse([pad + 8, sy - 14, pad + 36, sy + 14], fill=_mixc(C["green"], panel, k))
        d.text((pad + 56, sy), C["status"], font=C["f_status"], fill=_mixc(C["text"], panel, k), anchor="lm")
    x0 = (W - cw) // 2
    y0 = int(H * 0.15 + 18 * (1 - a))
    if a < 0.999:
        mask = mask.point(lambda v: int(v * a))
    img.paste(ov, (x0, y0), mask)


def draw_subs(img, t):
    chunks = G["chunks"]
    c = None
    for ch in chunks:
        if ch["t0"] <= t < ch["t1"]:
            c = ch
            break
    if c is None:
        return
    d = ImageDraw.Draw(img)
    items = c["items"]
    rise = int(14 * (1 - smoothstep((t - c["t0"]) / 0.12)))
    active = -1
    for k, it in enumerate(items):
        if t >= it["start"]:
            active = k
    for k, it in enumerate(items):
        if k == active:
            dt = t - it["start"]
            s = 1 + G["pulse"] * math.exp(-dt * 7) + G["pulse"] * 0.25 * math.sin(dt * 2 * math.pi * 2.2) * math.exp(-dt * 1.2)
            size = int(round(G["sub_size"] * s / 2) * 2)
            font = G["fonts"].get(size)
            if font is None:
                font = load_font(G["font_list"], size)
                G["fonts"][size] = font
            fill = G["col_active"]
        else:
            font = G["fonts"][G["sub_size"]]
            fill = G["col_quote"] if it["quote"] else G["col_sub"]
        d.text((it["cx"], it["cy"] + rise), it["text"], font=font, anchor="mm", fill=fill,
               stroke_width=G["stroke"], stroke_fill=G["col_stroke"])


def _init_worker():
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _render_star(args):
    return render_frame(*args)


def deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v  # списки (events) заменяются целиком
    return out


def parse_tc(s):
    h, m, sec = (int(p) for p in s.split(":"))
    return h * 3600 + m * 60 + sec


def resolve_events(cfg, words, voice_end, outro_t):
    toks = build_tokens(words)
    vid = cfg["video"]

    def hit(phrase, last=False, after=-1.0, edge="start"):
        if phrase in (None, ""):
            return None
        if phrase == "@start":
            return 0.0
        if phrase == "@end":
            return voice_end
        for a, b in find_phrase(words, phrase, toks):
            w = words[b] if last else words[a]
            if words[a]["start"] >= after:
                return w["end"] if edge == "end" else w["start"]
        return None

    ev = {"flash": [], "light": [], "silence": [], "ghosts": [], "zoom": None, "hit": None,
          "music": [], "hum": None, "ending": None, "outro": outro_t, "cams": [], "switch": [],
          "tcs": [(0.0, parse_tc(vid.get("timecode_start", "03:00:07")))], "days": [], "card": None,
          "shake": [], "white": [], "flash_dur": 0.3}
    for e in cfg.get("events", []):
        typ = e.get("type")
        if typ == "music_box":
            t0 = hit(e["start"])
            if t0 is None:
                continue
            t1 = hit(e.get("stop"), after=t0)
            ev["music"].append({"t0": t0, "t1": t1 if t1 and t1 > t0 else voice_end,
                                "clean": e.get("clean", False),
                                "below": e.get("below_voice_db", cfg["audio"]["music_below_voice_db"])})
        elif typ == "flash":
            hits = find_phrase(words, e["word"], toks)
            occ = e.get("occurrence", "all")
            if occ != "all":
                hits = hits[int(occ) - 1:int(occ)]
            ev["flash"] += [words[h[0]]["start"] for h in hits]
            ev["flash_dur"] = e.get("duration", 0.3)
        elif typ == "ghost":
            t0 = hit(e["show"])
            if t0 is None:
                continue
            ev["ghosts"].append({
                "t0": t0, "t1": hit(e.get("hide"), after=t0),
                "fin": e.get("fade_in", 0.8), "fout": e.get("fade_out", 0.15),
                "cam": e.get("camera", 1), "kind": e.get("kind", "woman"),
                "x": e.get("x", 0.75), "y": e.get("y", 0.735),
                "h": e.get("height", 0.40), "blur": e.get("blur", 14),
                "dark": e.get("dark", False), "strength": e.get("strength", 0.16),
                "flicker": e.get("flicker", 0), "grow_to": e.get("grow_to", 1.0),
                "grow_t": hit(e.get("grow_until"), after=t0),
            })
        elif typ == "light":
            t = hit(e["phrase"], last=True)
            if t is not None:
                ev["light"].append(t)
        elif typ == "zoom":
            t = hit(e["phrase"])
            if t is not None:
                ev["zoom"] = (t, e.get("amount", 0.08))
        elif typ == "silence":
            at = e.get("at", "after")
            dur = e.get("duration", 1.5)
            hold = e.get("hold", False) or dur == "end"
            if at == "after":
                t = hit(e["phrase"], last=True, edge="end")
                s = (t, t + (dur if not isinstance(dur, str) else 0)) if t is not None else None
            elif at == "before":
                t = hit(e["phrase"])
                s = (t - dur, t) if t is not None else None
            else:
                t = hit(e["phrase"])
                s = (t, t + (dur if not isinstance(dur, str) else 0)) if t is not None else None
            if s:
                ev["silence"].append((s[0], s[1], hold))
        elif typ == "hit":
            t = hit(e["word"])
            if t is not None:
                ev["hit"] = t
        elif typ == "ending":
            t = hit(e["phrase"])
            if t is not None:
                ev["ending"] = t
        elif typ == "hum":
            t0 = hit(e["start"])
            if t0 is None:
                continue
            t1 = hit(e.get("stop"), after=t0) or voice_end
            for s0, s1, _ in ev["silence"]:
                if t0 < s0 <= t1:
                    t1 = s0
            ev["hum"] = (t0, t1, e.get("below_voice_db", 12.5))
        elif typ == "camera":
            t = hit(e["phrase"], last=True, edge=e.get("at", "end"))
            if t is not None:
                ev["cams"].append((t, e.get("camera", 2), e.get("label", "CAM 02  ·  IR")))
                ev["switch"].append(t)
        elif typ == "timecode":
            t = hit(e["phrase"], last=e.get("at") == "end", edge=e.get("at", "start"))
            if t is None:
                continue
            val = parse_tc(e["value"])
            anchor = hit(e.get("anchor"), after=t)
            if anchor is not None:
                val -= anchor - t
            ev["tcs"].append((t, val))
        elif typ == "day":
            t0 = hit(e["start"])
            if t0 is None:
                continue
            t1 = hit(e.get("stop"), after=t0)
            ev["days"].append((t0, t1, e.get("fade_in", 0.35), e.get("fade_out", 1.2)))
            ev["switch"].append(t0)
        elif typ == "card":
            t0 = hit(e["phrase"])
            if t0 is None:
                continue
            rows = []
            for r in e.get("rows", []):
                rt = hit(r.get("reveal"), after=t0)
                rows.append({"name": r["name"], "style": r.get("style", "muted"),
                             "t": rt if rt is not None else t0})
            ev["card"] = {"t0": t0, "title": e.get("title", ""), "rows": rows,
                          "note": e.get("note", ""), "note_t": hit(e.get("note_reveal"), after=t0) if e.get("note_reveal") else t0,
                          "status": e.get("status", ""), "status_t": hit(e.get("status_reveal"), after=t0) if e.get("status_reveal") else t0}
        elif typ == "shake":
            t0 = hit(e["phrase"])
            if t0 is not None:
                ev["shake"].append((t0, outro_t, e.get("amount", 26)))
        elif typ == "white_frame":
            t = hit(e["word"], last=True)
            if t is not None:
                ev["white"].append(t)
    if ev["ending"] is None:
        ev["ending"] = max(vid["title_duration"], voice_end - 5)
    ev["cams"].sort()
    ev["tcs"].sort()
    return ev


# ───────────────────────────── main ─────────────────────────────

def main():
    global FFMPEG
    ap = argparse.ArgumentParser(description="Генератор вертикальных хоррор-шортсов")
    ap.add_argument("story", nargs="?", default="story.txt")
    ap.add_argument("part", nargs="?", default=None,
                    help="имя части (part2, part3…): берёт parts/<имя>.toml и пишет output_<имя>.mp4")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--fps", type=int, default=None, help="30 (по умолчанию) или 60")
    ap.add_argument("--duration", type=float, default=None, help="отрендерить только первые N секунд (пробная версия)")
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--voice", default=None,
                    help="имя записи в папке voice/ (по умолчанию = имя части, для части 1 — part1)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    args = ap.parse_args()

    t_start = time.time()
    cfg = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.part:
        pf = ROOT / "parts" / f"{args.part}.toml"
        if pf.exists():
            cfg = deep_merge(cfg, tomllib.loads(pf.read_text(encoding="utf-8")))
            print(f"[part] настройки части: {pf.relative_to(ROOT)}")
        else:
            print(f"[part] {pf.relative_to(ROOT)} не найден — беру config.toml как есть")
    output = args.output or (f"output_{args.part}.mp4" if args.part else "output.mp4")
    vid, colors, sc, bgc, acfg = cfg["video"], cfg["colors"], cfg["subtitles"], cfg["background"], cfg["audio"]
    W, H = vid["width"], vid["height"]
    fps = args.fps or vid["fps"]
    sr = acfg["sample_rate"]
    seed = args.seed if args.seed is not None else random.randint(0, 99999)
    FFMPEG = find_ffmpeg()
    patch_edge_tts_ssl()

    title, segments = parse_story(args.story, cfg["voice"])
    print(f"[story] «{title}»: {len(segments)} фраз(ы)")
    for s in segments:
        if s["quote"]:
            print(f"        2-й голос: {s['text']}")

    rec_name = args.voice or (args.part or "part1")
    rec = find_recordings(rec_name)
    if rec:
        cfg["_recorded"] = rec
        src = rec.get("single") or (rec["roles"]["narrator"][0] if "roles" in rec else rec["files"][0].parent)
        print(f"[voice] беру свою озвучку: {Path(src).relative_to(ROOT) if str(src).startswith(str(ROOT)) else src}")
    else:
        print("[voice] озвучка через edge-tts…")
    segs, starts, voice_end, total, pause, rate_shift = fit_duration(segments, cfg, sr)
    if rate_shift or abs(pause - cfg["voice"]["pause"]) > 1e-3:
        what = "ускорение записи" if cfg.get("_recorded") else "темп"
        print(f"[voice] подогнал длину: пауза {pause:.2f} с, {what} {rate_shift:+d}%")

    words = []
    for si, (s, st) in enumerate(zip(segs, starts)):
        for w, a, b in s["words"]:
            disp = w.upper() if sc["uppercase"] else w
            words.append({"text": w, "disp": disp, "start": st + a, "end": st + b, "seg": si, "quote": s["quote"]})

    outro_t = voice_end + vid["outro_gap"]
    ev = resolve_events(cfg, words, voice_end, outro_t)

    T = total if args.duration is None else min(total, args.duration)
    nframes = int(round(T * fps))
    T = nframes / fps

    print(f"[timeline] полная длина {total:.2f} с, рендер {T:.2f} с @ {fps} fps")
    r2 = lambda v: round(v, 2) if isinstance(v, float) else v  # noqa: E731
    for k in ("music", "flash", "light", "zoom", "silence", "hit", "hum", "cams", "days", "tcs", "shake", "white", "ending"):
        val = ev[k]
        if val is None or (isinstance(val, list) and not val):
            continue
        if isinstance(val, list):
            val = [({kk: r2(vv) for kk, vv in x.items()} if isinstance(x, dict) else
                    tuple(r2(y) for y in x) if isinstance(x, tuple) else r2(x)) for x in val]
        elif isinstance(val, tuple):
            val = tuple(r2(y) for y in val)
        print(f"           {k:8s}: {val}")
    if ev["card"]:
        print(f"           card    : {ev['card']['t0']:.2f}, строки {[round(r['t'], 2) for r in ev['card']['rows']]}")
    for gh in ev["ghosts"]:
        print(f"           ghost   : CAM{gh['cam']} {gh['kind']} {gh['t0']:.2f}→{gh['t1']}")

    # Звук
    print("[audio] сведение…")
    mix, crackle_times, stats = build_audio(segs, starts, total, ev, cfg, sr, seed)
    mix = mix[: int(round(T * sr))]
    work = ROOT / ".cache" / "work"
    work.mkdir(parents=True, exist_ok=True)
    wav = work / f"mix_{args.part or 'main'}.wav"
    write_wav(wav, mix, sr)
    vdb = stats[0][1]
    for name, val in stats:
        extra = "" if name in ("голос", "пик микса") else f"  (голос громче на {vdb - val:.1f} dB)"
        print(f"[audio] {name:20s} {val:6.1f} dBFS{extra}")

    # Фон
    bg_dir = ROOT / bgc["folder"] if not os.path.isabs(bgc["folder"]) else Path(bgc["folder"])
    vids = sorted([p for p in bg_dir.glob("*") if p.suffix.lower() in (".mp4", ".mov")]) if bg_dir.is_dir() else []
    bg_file = random.Random(seed).choice(vids) if vids else None
    print(f"[bg] {'видео: ' + bg_file.name if bg_file else 'генерирую ночную камеру'}")

    font_list = sc["fonts"]
    sub_font = load_font(font_list, sc["size"])
    tint = np.array(hex_rgb(colors["night_tint"]), dtype=np.float32)
    nrng = np.random.default_rng(seed + 99)
    mono = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Bold.ttf"] + font_list
    bases = {}
    if bg_file is None:
        bases[1] = make_night_base(W, H, seed)
        if any(c == 2 for _, c, _ in ev["cams"]) or any(g["cam"] == 2 for g in ev["ghosts"]):
            bases[2] = make_cam2_base(W, H, seed)
    G.update({
        "W": W, "H": H, "fps": fps, "seed": seed, "tint": tint,
        "day_tint": np.array(hex_rgb(colors.get("day_tint", "#EEEAE4")), dtype=np.float32),
        "bases": bases,
        "day_base": make_night_base(W, H, seed, day=True) if (bg_file is None and ev["days"]) else None,
        "days": ev["days"] if bg_file is None else [],
        "cams": [(0.0, 1, vid.get("cam_label", "CAM 01  ·  IR"))] + ev["cams"],
        "tcs": ev["tcs"], "switch": ev["switch"], "shake": ev["shake"],
        "white": {int(round(t * fps)) for t in ev["white"]},
        "yy": np.arange(H, dtype=np.float32)[:, None],
        "vignette": make_vignette(W, H, bgc["vignette"]),
        "noise": [np.clip(nrng.normal(0, 40, (H, W)), -127, 127).astype(np.int8) for _ in range(10)],
        "gen_grain": bgc["generated_grain"], "vid_grain": bgc["grain"],
        "zoom": ev["zoom"], "flash": ev["flash"], "flash_dur": ev["flash_dur"], "light": ev["light"],
        "hit": ev["hit"],
        "ghosts": ev["ghosts"] if bg_file is None else [],
        "crackles": crackle_times,
        "ending": (ev["ending"], voice_end), "dark_from": ev["hit"] if ev["hit"] else ev["ending"],
        "outro_t": outro_t, "title_dur": vid["title_duration"],
        "hud": bg_file is None or bgc["hud_on_video"],
        "hud_col": hex_rgb(colors["hud"]), "rec_col": hex_rgb(colors["rec"]),
        "hud_font": load_font(mono, 52), "hud_small": load_font(mono, 38),
        "title_img": make_title_overlay(title, cfg, W),
        "outro_img": make_outro_overlay(cfg),
        "chunks": build_sub_chunks(words, cfg, sub_font, W, H),
        "fonts": {sc["size"]: sub_font}, "font_list": font_list, "sub_size": sc["size"],
        "stroke": sc["stroke"], "pulse": sc["pulse"],
        "col_sub": hex_rgb(colors["subtitle"]), "col_active": hex_rgb(colors["subtitle_active"]),
        "col_quote": hex_rgb(colors["subtitle_quote"]), "col_stroke": hex_rgb(colors["stroke"]),
        "card": None,
    })
    # ночью до кадра с днём таймкод «дневной» не нужен — всё задаётся событиями timecode
    if ev["card"]:
        cc = cfg.get("card", {})
        cfonts = cc.get("fonts", ["/usr/share/fonts/opentype/inter/Inter-Bold.otf"]) + font_list
        G["card"] = {**ev["card"],
                     "f_title": load_font(cfonts, 50), "f_row": load_font(cfonts, 54),
                     "f_small": load_font(cfonts, 38), "f_status": load_font(cfonts, 44),
                     "panel": hex_rgb(cc.get("panel", "#101412")), "row": hex_rgb(cc.get("row", "#1A201D")),
                     "line": hex_rgb(cc.get("line", "#2A322E")), "text": hex_rgb(cc.get("text", "#EEF2EF")),
                     "muted": hex_rgb(cc.get("muted", "#878F8A")), "alert": hex_rgb(cc.get("alert", "#E3242B")),
                     "alert_text": hex_rgb(cc.get("alert_text", "#FFFFFF")),
                     "green": hex_rgb(cc.get("green", "#3DDC72"))}
    # белый силуэт для вспышки (экранные координаты)
    fh = int(H * 0.56)
    core = np.asarray(figure_mask(fh, 4)).astype(np.float32) / 255
    glow = np.asarray(figure_mask(fh, 28)).astype(np.float32) / 255
    fm = np.zeros((H, W), dtype=np.float32)
    fw = core.shape[1]
    y0, x0 = int(H * 0.47 - fh / 2), (W - fw) // 2
    fm[y0:y0 + fh, x0:x0 + fw] = np.clip(core * 0.95 + glow * 0.6, 0, 1)
    G["flash_img"] = fm
    # прогреваем кэш масок фигур до fork, чтобы воркеры не считали одно и то же
    for gh in G["ghosts"]:
        ghost_masks(gh, 1.0)

    # Кодирование
    enc = subprocess.Popen([
        FFMPEG, "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
        "-i", str(wav),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(vid["crf"]), "-pix_fmt", "yuv420p",
        "-maxrate", "12M", "-bufsize", "24M",
        "-profile:v", "high", "-g", str(fps * 2), "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000",
        "-movflags", "+faststart", "-shortest", output,
    ], stdin=subprocess.PIPE)

    dec = None
    if bg_file is not None:
        b = bgc["brightness"]
        tr, tg, tb = (tint / 255.0 * b)
        vf = (f"crop='min(iw,ih*{W}/{H})':'min(ih,iw*{H}/{W})',scale={W}:{H}:flags=lanczos,fps={fps},"
              f"eq=contrast=1.12:saturation=0,"
              f"colorchannelmixer=rr={tr:.3f}:rg=0:rb=0:gr=0:gg={tg:.3f}:gb=0:br=0:bg=0:bb={tb:.3f},format=rgb24")
        dec = subprocess.Popen([FFMPEG, "-v", "error", "-stream_loop", "-1", "-i", str(bg_file),
                                "-t", f"{T + 1:.3f}", "-vf", vf, "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                               stdout=subprocess.PIPE)
    fsize = W * H * 3
    ctx = mp.get_context("fork")
    batch = args.workers * 6
    print(f"[render] {nframes} кадров, {args.workers} процесс(а)…")
    t_r = time.time()
    last_frame = None
    with ctx.Pool(args.workers, initializer=_init_worker) as pool:
        for b0 in range(0, nframes, batch):
            idx = list(range(b0, min(nframes, b0 + batch)))
            if dec is not None:
                jobs = []
                for i in idx:
                    buf = dec.stdout.read(fsize)
                    if len(buf) < fsize:
                        buf = last_frame
                    last_frame = buf
                    jobs.append((i, buf))
            else:
                jobs = [(i, None) for i in idx]
            for fr in pool.imap(_render_star, jobs, chunksize=2):
                enc.stdin.write(fr)
            done = idx[-1] + 1
            el = time.time() - t_r
            print(f"\r[render] {done}/{nframes}  {done / el:.1f} к/с", end="", flush=True)
    print()
    enc.stdin.close()
    enc.wait()
    if dec is not None:
        dec.kill()
    if enc.returncode != 0:
        sys.exit("ffmpeg завершился с ошибкой")
    print(f"[done] {output}  ({T:.2f} с, {os.path.getsize(output) / 1e6:.1f} МБ, "
          f"за {time.time() - t_start:.0f} с)")
    if bg_file is None:
        print(f"[tip] Положи свои .mp4/.mov в папку {bg_dir}/ — фон возьмётся оттуда.")




if __name__ == "__main__":
    main()
