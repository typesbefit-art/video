#!/usr/bin/env python3
"""
Генератор вертикального хоррор-ролика «страшная история с озвучкой и субтитрами».

    python generate.py story.txt                  -> output.mp4
    python generate.py story.txt --fps 60
    python generate.py story.txt --duration 15 -o output_preview.mp4   (пробная версия)

Текст истории — в story.txt (первая строка — заголовок).
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


def decode_audio(path, sr):
    out = run([FFMPEG, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1",
               "-ar", str(sr), "-"], capture_output=True).stdout
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

def parse_story(path):
    text = Path(path).read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    title = lines[0].strip()
    body = " ".join(l.strip() for l in lines[1:] if l.strip())
    segments = []  # {"text", "quote"}
    pos = 0
    for m in re.finditer(r"«([^»]+)»", body):
        _split_sentences(body[pos:m.start()], segments)
        q = m.group(1).strip()
        if q:
            segments.append({"text": q, "quote": True})
        pos = m.end()
    _split_sentences(body[pos:], segments)
    return title, segments


def _split_sentences(chunk, out):
    chunk = chunk.strip()
    if not chunk:
        return
    for s in re.split(r"(?<=[.!?…])\s+", chunk):
        s = s.strip()
        if s and re.search(r"\w", s):
            out.append({"text": s, "quote": False})


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
        for attempt in range(5):
            try:
                words, audio = [], bytearray()
                com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
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
                await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"edge-tts не ответил для «{text[:40]}…»: {last_err}")


def synthesize(segments, cfg, rate_shift, sr):
    v = cfg["voice"]
    cache = ROOT / ".cache" / "tts"
    cache.mkdir(parents=True, exist_ok=True)

    def shift(rate):
        return f"{int(rate.rstrip('%')) + rate_shift:+d}%"

    async def main():
        sem = asyncio.Semaphore(4)
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
    for i in range(1, n):
        if segs[i]["quote"]:
            gaps[i] = v["pause_before_quote"]
        elif i == n - 1:
            gaps[i] = v["pause_before_last"]
        else:
            gaps[i] = pause
            flex[i] = True
    # Тишина после фразы: удлиняем паузу после сегмента, где фраза заканчивается
    for ev in cfg.get("events", []):
        if ev.get("type") != "silence":
            continue
        for si, s in enumerate(segs[:-1]):
            sw = [{"text": w[0]} for w in s["words"]]
            hits = find_phrase(sw, ev["phrase"])
            if hits:
                last = hits[0][1]
                tail = s["dur"] - s["words"][last][2]
                need = ev["duration"] + 0.05 - tail
                if gaps[si + 1] < need:
                    gaps[si + 1] = need
                    flex[si + 1] = False
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

def synth_music_box(sr, length, seed):
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
        i0 = int((t + rng.normal(0, 0.02)) * sr)
        i0 = max(i0, 0)
        out[i0:i0 + L] += y * vel
        k += 1
        t += step * (1.0 + 0.04 * (k // 4))            # чуть замедляется, «заводка» кончается
        if k % 4 == 0:
            t += 0.55
    out = fft_filter(out, sr, lo=380, hi=4200)          # из динамика видеоняни
    out = np.tanh(out * 1.6) / 1.6
    out = simple_reverb(out, sr, decay=1.1, mix=0.3, seed=seed + 1)
    return out[:n]


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


def build_audio(segs, starts, total, ev, cfg, sr, seed):
    a = cfg["audio"]
    v = cfg["voice"]
    rng = np.random.default_rng(seed)
    N = int(round(total * sr))

    # Голос
    narr_peak = max((np.max(np.abs(s["audio"])) for s in segs if not s["quote"]), default=1.0)
    g_narr = db(a["voice_peak_db"]) / narr_peak
    narr_rms = np.mean([active_rms(s["audio"] * g_narr, sr) for s in segs if not s["quote"]] or [0.1])
    voice = np.zeros(N, dtype=np.float32)
    for s, st in zip(segs, starts):
        x = s["audio"] * g_narr
        if s["quote"]:
            x = whisperize(s["audio"], sr, v["quote_whisper"])
            x = x * (narr_rms * db(v["quote_level_db"]) / (active_rms(x, sr) + 1e-9))
        i = int(st * sr)
        voice[i:i + len(x)] += x[: max(0, N - i)]
    voice_rms = active_rms(voice, sr)

    # Шум эфира видеоняни: белый шум -34 dBFS
    noise = rng.standard_normal(N).astype(np.float32)
    noise = fft_filter(noise, sr, lo=60, hi=11000, order=1)
    noise *= db(a["noise_db"]) / rms(noise)

    # Редкие помехи
    crackles = np.zeros(N, dtype=np.float32)
    crackle_times = []
    t = 0.3
    lo_i, hi_i = a["crackle_every"]
    while t < total - 1.0:
        if rng.random() < 0.6:
            c = synth_click(sr, rng)
            c *= db(-20 - 6 * rng.random()) / (np.max(np.abs(c)) + 1e-9)
            dur = 0.05
        else:
            dur = 0.08 + 0.2 * rng.random()
            c = synth_static_burst(sr, dur, rng)
            c *= db(-27 - 4 * rng.random()) / (rms(c) + 1e-9)
        i = int(t * sr)
        crackles[i:i + len(c)] += c[: max(0, N - i)]
        crackle_times.append((t, dur))
        t += lo_i + (hi_i - lo_i) * rng.random()

    # Шкатулка
    music = np.zeros(N, dtype=np.float32)
    music_db = None
    if ev.get("music"):
        m0, m1 = ev["music"]
        mb = synth_music_box(sr, m1 - m0, seed + 11)
        target = voice_rms * db(-a["music_below_voice_db"])
        mb *= target / (active_rms(mb, sr) + 1e-9)
        f = int(0.008 * sr)
        mb[-f:] *= np.linspace(1, 0, f, dtype=np.float32)   # резкий обрыв
        i = int(m0 * sr)
        music[i:i + len(mb)] = mb[: max(0, N - i)]
        music_db = to_db(active_rms(mb, sr))

    # Звуковые эффекты
    sfx = np.zeros(N, dtype=np.float32)
    for ft in ev.get("flash", []):
        b = synth_static_burst(sr, 0.4, rng)
        b *= db(-21) / (rms(b) + 1e-9)
        i = int((ft - 0.05) * sr)
        sfx[i:i + len(b)] += b[: max(0, N - i)]
    for lt in ev.get("light", []):
        c = synth_click(sr, rng)
        c *= db(-12) / (np.max(np.abs(c)) + 1e-9)
        i = int((lt - 0.05) * sr)
        sfx[i:i + len(c)] += c[: max(0, N - i)]
    hit_t = ev.get("hit")
    if hit_t is not None:
        h = synth_hit(sr)
        i = int(hit_t * sr)
        sfx[i:i + len(h)] += h[: max(0, N - i)]

    # Резкая тишина: глушим всё, кроме голоса и удара
    gate = np.ones(N, dtype=np.float32)
    for s0, s1 in ev.get("silence", []):
        i0, i1 = int(s0 * sr), int(s1 * sr)
        f = int(0.004 * sr)
        gate[i0:i0 + f] = np.linspace(1, 0, f)
        gate[i0 + f:i1] = 0
        r = int(0.9 * sr)
        gate[i1:i1 + r] = np.linspace(0, 1, len(gate[i1:i1 + r]))
    # В финале шум уходит вместе с картинкой, остаётся хвост удара
    if ev.get("outro"):
        o0 = int(ev["outro"] * sr)
        fade = np.ones(N, dtype=np.float32)
        fade[o0:] = np.linspace(1, 0.15, N - o0)
        gate *= fade

    mix = voice + (noise + crackles + music) * gate + sfx
    peak = np.max(np.abs(mix))
    th = 0.9
    over = np.abs(mix) > th
    mix[over] = np.sign(mix[over]) * (th + (1 - th) * np.tanh((np.abs(mix[over]) - th) / (1 - th)))
    stats = {
        "voice_db": to_db(voice_rms),
        "music_db": music_db,
        "noise_db": to_db(rms(noise)),
        "peak_db": to_db(peak),
    }
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


def make_night_base(W, H, seed):
    """Детская в ИК-подсветке: стены, пол, окно, смутная кроватка."""
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(0, 1, W)[None, :]
    lum = 0.13 + 0.05 * y + 0 * x
    floor_y = 0.70
    lum = np.where(y > floor_y, 0.20 + 0.10 * (y - floor_y), lum)
    lum = lum + 0.025 * (np.abs(x - 0.5) < 0.003) * (y < floor_y)         # угол комнаты
    # ИК-прожектор камеры: пятно света в центре
    r = np.sqrt(((x - 0.5) / 0.75) ** 2 + ((y - 0.58) / 0.55) ** 2)
    lum = lum * (0.55 + 0.75 * np.exp(-r ** 2 * 1.6))
    im = Image.fromarray(np.clip(lum * 255, 0, 255).astype(np.uint8), "L")
    d = ImageDraw.Draw(im)
    # окно с занавеской слева сверху
    wx0, wy0, wx1, wy1 = int(W * 0.08), int(H * 0.22), int(W * 0.34), int(H * 0.44)
    d.rectangle([wx0, wy0, wx1, wy1], fill=62)
    d.line([(wx0 + wx1) // 2, wy0, (wx0 + wx1) // 2, wy1], fill=34, width=10)
    d.line([wx0, (wy0 + wy1) // 2, wx1, (wy0 + wy1) // 2], fill=34, width=10)
    d.rectangle([wx0 - 30, wy0 - 20, wx0 + 40, wy1 + 60], fill=44)
    # кроватка
    cx0, cx1 = int(W * 0.24), int(W * 0.76)
    top, bot = int(H * 0.53), int(H * 0.70)
    col = 118
    d.rectangle([cx0 - 18, top - 70, cx0 + 6, bot + 70], fill=col)          # стойки
    d.rectangle([cx1 - 6, top - 70, cx1 + 18, bot + 70], fill=col)
    d.rectangle([cx0, top - 14, cx1, top + 10], fill=col + 10)              # верхняя перекладина
    d.rectangle([cx0, bot - 30, cx1, bot - 6], fill=col)                    # нижняя
    for bx in range(cx0 + 30, cx1 - 10, 38):
        d.rectangle([bx, top, bx + 9, bot - 20], fill=col - 15)            # прутья
    d.ellipse([cx0 + 70, bot - 120, cx0 + 330, bot - 34], fill=96)          # одеяльце
    d.ellipse([cx0 + 300, bot - 110, cx0 + 380, bot - 44], fill=104)        # голова малыша
    d.rectangle([cx0 - 10, bot + 70, cx1 + 10, bot + 110], fill=50)         # тень
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


# ───────────────────────────── рендер кадра ─────────────────────────────

def env_ghost(t):
    a = 0.0
    for s0, s1 in G["ghost"]:
        if t >= s0:
            up = smoothstep((t - s0) / 0.8)
            down = 1.0 if s1 is None else 1 - smoothstep((t - s1) / 0.15)
            a = max(a, up * down)
    return a


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
    rng = np.random.default_rng(G["seed"] * 1_000_003 + i)
    tint = G["tint"]

    # 1. Фон (+ зум)
    z = 1.0
    if G["zoom"]:
        z0, amt = G["zoom"]
        z = 1 + amt * smoothstep((t - z0) / 1.6)
    if bg_bytes is None:
        lum = G["base"]
        ga = env_ghost(t)
        breathe = 0.96 + 0.04 * math.sin(2 * math.pi * 0.21 * t) + 0.015 * rng.standard_normal()
        if ga > 0:
            lum = lum + G["ghost_img"] * (0.16 * ga)
        lum = lum * breathe
        if z > 1.001:
            im = Image.fromarray(lum, "F")
            bw, bh = W / z, H / z
            box = ((W - bw) / 2, (H - bh) / 2 + bh * 0.0, (W + bw) / 2, (H + bh) / 2)
            lum = np.asarray(im.resize((W, H), Image.BILINEAR, box=box))
        # катящаяся полоса помех
        band_y = ((t * 0.09) % 1.3 - 0.15) * H
        band = (0.035 * np.exp(-((G["yy"] - band_y) / 55.0) ** 2)).astype(np.float32)
        rgb = (lum + band)[:, :, None] * tint[None, None, :]
        grain = G["gen_grain"]
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
    # Засветка камеры при включении света
    for lt in G["light"]:
        if lt - 0.02 <= t <= lt + 1.2:
            k = 2.2 * math.exp(-max(0.0, t - lt) / 0.22)
            rgb = rgb * (1 + k) + 90 * k
    # Удар — встряска
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

    # 3. Интерфейс ночной камеры
    if G["hud"]:
        draw_hud(img, t)

    # 4. Помехи: треск в эфире и финал
    g = 0.0
    for ct, cd in G["crackles"]:
        if ct <= t <= ct + cd + 0.05:
            g = max(g, 0.22)
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
    if g > 0 or dark < 1:
        arr = np.array(img)
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


def draw_hud(img, t):
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
    secs = 3 * 3600 + 7 + int(t)
    stamp = f"{secs // 3600:02d}:{secs // 60 % 60:02d}:{secs % 60:02d}"
    d.text((W - m - 34, m + 102), stamp, font=f, fill=col, anchor="rm")
    d.text((m + 34, H - m - 300), "CAM 01  ·  IR", font=G["hud_small"], fill=col, anchor="lm")
    # батарея
    bx, by = W - m - 34 - 92, H - m - 322
    d.rectangle([bx, by, bx + 80, by + 40], outline=col, width=4)
    d.rectangle([bx + 80, by + 12, bx + 88, by + 28], fill=col)
    d.rectangle([bx + 8, by + 8, bx + 30, by + 32], fill=col)


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


# ───────────────────────────── main ─────────────────────────────

def main():
    global FFMPEG
    ap = argparse.ArgumentParser(description="Генератор вертикальных хоррор-шортсов")
    ap.add_argument("story", nargs="?", default="story.txt")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--fps", type=int, default=None, help="30 (по умолчанию) или 60")
    ap.add_argument("--duration", type=float, default=None, help="отрендерить только первые N секунд (пробная версия)")
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    args = ap.parse_args()

    t_start = time.time()
    cfg = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    vid, colors, sc, bgc, acfg = cfg["video"], cfg["colors"], cfg["subtitles"], cfg["background"], cfg["audio"]
    W, H = vid["width"], vid["height"]
    fps = args.fps or vid["fps"]
    sr = acfg["sample_rate"]
    seed = args.seed if args.seed is not None else random.randint(0, 99999)
    FFMPEG = find_ffmpeg()
    patch_edge_tts_ssl()

    title, segments = parse_story(args.story)
    print(f"[story] «{title}»: {len(segments)} фраз(ы)")

    print("[voice] озвучка через edge-tts…")
    segs, starts, voice_end, total, pause, rate_shift = fit_duration(segments, cfg, sr)
    if rate_shift or abs(pause - cfg["voice"]["pause"]) > 1e-3:
        print(f"[voice] подогнал длину: пауза {pause:.2f} с, темп {rate_shift:+d}%")

    # Слова с абсолютным временем
    words = []
    for si, (s, st) in enumerate(zip(segs, starts)):
        for w, a, b in s["words"]:
            disp = w.upper() if sc["uppercase"] else w
            words.append({"text": w, "disp": disp, "start": st + a, "end": st + b, "seg": si, "quote": s["quote"]})
    toks = build_tokens(words)

    def first_hit(phrase, last=False):
        h = find_phrase(words, phrase, toks)
        if not h:
            return None
        return words[h[0][1]] if last else words[h[0][0]]

    outro_t = voice_end + vid["outro_gap"]
    ev = {"flash": [], "light": [], "silence": [], "ghost": [], "zoom": None, "hit": None,
          "music": None, "ending": None, "outro": outro_t}
    for e in cfg.get("events", []):
        typ = e.get("type")
        if typ == "music_box":
            a = first_hit(e["start"])
            b = first_hit(e["stop"]) if e.get("stop") else None
            if a:
                ev["music"] = (a["start"], b["start"] if b and b["start"] > a["start"] else voice_end)
        elif typ == "flash":
            hits = find_phrase(words, e["word"], toks)
            occ = e.get("occurrence", "all")
            if occ != "all":
                hits = hits[int(occ) - 1:int(occ)]
            ev["flash"] += [words[h[0]]["start"] for h in hits]
            G["flash_dur"] = e.get("duration", 0.3)
        elif typ == "ghost":
            a = first_hit(e["show"])
            if a:
                b = first_hit(e["hide"]) if e.get("hide") else None
                ev["ghost"].append((a["start"], b["start"] if b else None))
        elif typ == "light":
            w = first_hit(e["phrase"], last=True)
            if w:
                ev["light"].append(w["start"])
        elif typ == "zoom":
            w = first_hit(e["phrase"])
            if w:
                ev["zoom"] = (w["start"], e.get("amount", 0.08))
        elif typ == "silence":
            w = first_hit(e["phrase"], last=True)
            if w:
                ev["silence"].append((w["end"], w["end"] + e["duration"]))
        elif typ == "hit":
            w = first_hit(e["word"])
            if w:
                ev["hit"] = w["start"]
        elif typ == "ending":
            w = first_hit(e["phrase"])
            if w:
                ev["ending"] = w["start"]
    if ev["ending"] is None:
        ev["ending"] = max(vid["title_duration"], voice_end - 5)

    # Короткая версия
    T = total if args.duration is None else min(total, args.duration)
    nframes = int(round(T * fps))
    T = nframes / fps

    print(f"[timeline] полная длина {total:.2f} с, рендер {T:.2f} с @ {fps} fps")
    for k in ("music", "flash", "light", "zoom", "silence", "hit", "ending"):
        print(f"           {k:8s}: {ev[k]}")

    # Звук
    print("[audio] сведение…")
    mix, crackle_times, stats = build_audio(segs, starts, total, ev, cfg, sr, seed)
    mix = mix[: int(round(T * sr))]
    work = ROOT / ".cache" / "work"
    work.mkdir(parents=True, exist_ok=True)
    wav = work / "mix.wav"
    write_wav(wav, mix, sr)
    if stats["music_db"] is not None:
        print(f"[audio] голос {stats['voice_db']:.1f} dBFS, шкатулка {stats['music_db']:.1f} dBFS "
              f"(разница {stats['voice_db'] - stats['music_db']:.1f} dB), шум {stats['noise_db']:.1f} dBFS")

    # Фон
    bg_dir = ROOT / bgc["folder"] if not os.path.isabs(bgc["folder"]) else Path(bgc["folder"])
    vids = sorted([p for p in bg_dir.glob("*") if p.suffix.lower() in (".mp4", ".mov")]) if bg_dir.is_dir() else []
    bg_file = random.Random(seed).choice(vids) if vids else None
    print(f"[bg] {'видео: ' + bg_file.name if bg_file else 'генерирую ночную камеру'}")

    font_list = sc["fonts"]
    sub_font = load_font(font_list, sc["size"])
    tint = np.array(hex_rgb(colors["night_tint"]), dtype=np.float32)
    nrng = np.random.default_rng(seed + 99)
    G.update({
        "W": W, "H": H, "fps": fps, "seed": seed, "tint": tint,
        "base": make_night_base(W, H, seed) if bg_file is None else None,
        "yy": np.arange(H, dtype=np.float32)[:, None],
        "vignette": make_vignette(W, H, bgc["vignette"]),
        "noise": [np.clip(nrng.normal(0, 40, (H, W)), -127, 127).astype(np.int8) for _ in range(10)],
        "gen_grain": bgc["generated_grain"], "vid_grain": bgc["grain"],
        "zoom": ev["zoom"], "flash": ev["flash"], "light": ev["light"], "hit": ev["hit"],
        "ghost": ev["ghost"] if bg_file is None else [],
        "crackles": crackle_times,
        "ending": (ev["ending"], voice_end), "dark_from": ev["hit"] if ev["hit"] else ev["ending"],
        "outro_t": outro_t, "title_dur": vid["title_duration"],
        "hud": bg_file is None or bgc["hud_on_video"],
        "hud_col": hex_rgb(colors["hud"]), "rec_col": hex_rgb(colors["rec"]),
        "hud_font": load_font(["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Bold.ttf"] + font_list, 52),
        "hud_small": load_font(["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Bold.ttf"] + font_list, 38),
        "title_img": make_title_overlay(title, cfg, W),
        "outro_img": make_outro_overlay(cfg),
        "chunks": build_sub_chunks(words, cfg, sub_font, W, H),
        "fonts": {sc["size"]: sub_font}, "font_list": font_list, "sub_size": sc["size"],
        "stroke": sc["stroke"], "pulse": sc["pulse"],
        "col_sub": hex_rgb(colors["subtitle"]), "col_active": hex_rgb(colors["subtitle_active"]),
        "col_quote": hex_rgb(colors["subtitle_quote"]), "col_stroke": hex_rgb(colors["stroke"]),
    })
    G.setdefault("flash_dur", 0.3)
    # белый силуэт для вспышки (экранные координаты)
    fh = int(H * 0.56)
    core = np.asarray(figure_mask(fh, 4)).astype(np.float32) / 255
    glow = np.asarray(figure_mask(fh, 28)).astype(np.float32) / 255
    fm = np.zeros((H, W), dtype=np.float32)
    fw = core.shape[1]
    y0, x0 = int(H * 0.47 - fh / 2), (W - fw) // 2
    fm[y0:y0 + fh, x0:x0 + fw] = np.clip(core * 0.95 + glow * 0.6, 0, 1)
    G["flash_img"] = fm
    if bg_file is None:
        gh = int(H * 0.40)
        gm = np.asarray(figure_mask(gh, 14)).astype(np.float32) / 255
        gimg = np.zeros((H, W), dtype=np.float32)
        gx0 = int(W * 0.60)
        gy0 = int(H * 0.735) - gh
        gimg[gy0:gy0 + gh, gx0:gx0 + gm.shape[1]] = gm[:, : W - gx0]
        G["ghost_img"] = gimg

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
        "-movflags", "+faststart", "-shortest", args.output,
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
    print(f"[done] {args.output}  ({T:.2f} с, {os.path.getsize(args.output) / 1e6:.1f} МБ, "
          f"за {time.time() - t_start:.0f} с)")
    if bg_file is None:
        print(f"[tip] Положи свои .mp4/.mov в папку {bg_dir}/ — фон возьмётся оттуда.")


if __name__ == "__main__":
    main()
