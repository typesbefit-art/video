#!/usr/bin/env python3
"""
Генератор вертикального видео «страшная и смешная история» (1080x1920, H.264 + AAC).

    python generate.py story.txt                  -> output.mp4
    python generate.py story.txt --fps 60         -> 60 fps
    python generate.py story.txt --limit 15 -o preview.mp4   -> пробные первые 15 секунд

История — в story.txt (первая строка = заголовок). Голос, цвета, паузы, триггеры
звуков и эффектов — в config.json. Сам код при смене истории трогать не нужно.
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import hashlib
import json
import math
import os
import random
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

W, H = 1080, 1920
SR = 48000
LEAD = 0.20            # тишина перед первой фразой, с
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "tts")

DEFAULT_CONFIG = {
    "voice": {"name": "ru-RU-DmitryNeural", "rate": -2, "pitch": -2,
              "mood_drift": {"enabled": False, "rate_end": -2, "pitch_end": -2}},
    "pauses": {"default": 0.4, "before": {}},
    "ghost": {"markers": ["он", "призрак"]},
    "colors": {"text": "#FFFFFF", "stroke": "#000000", "highlight": "#FF2B2B",
               "ghost_highlight": "#7FD8FF", "ghost_text": "#E6F7FF",
               "cta_plate": "#D7141E", "cta_text": "#FFFFFF",
               "bg_top": "#07122A", "bg_bottom": "#06393A", "fog": "#9CC7CF"},
    "subtitles": {"font": "Inter-ExtraBold", "size": 104, "stroke": 9, "y": 0.62,
                  "uppercase": True, "max_words": 4},
    "title": {"duration": 1.5, "size": 128},
    "cta": {"text": "Часть 2?\nПодписывайся", "duration": 1.5},
    "sfx": [], "vfx": [],
    "audio": {"drone_db": -28, "voice_rms_db": -14, "min_voice_over_music_db": 12},
    "duration": {"min": 50, "max": 65},
}


# ----------------------------------------------------------------------------- utils
def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]", "", s)


def db(x: float) -> float:
    return 20 * math.log10(max(x, 1e-12))


def undb(d: float) -> float:
    return 10 ** (d / 20)


def smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
        sys.exit("Не найден ffmpeg. Установите его: sudo apt install ffmpeg  /  brew install ffmpeg")


# ----------------------------------------------------------------------------- story
@dataclass
class Phrase:
    text: str
    speaker: str                  # title | narrator | ghost
    pause_before: float = 0.0
    rate: int = 0
    pitch: int = 0
    audio: np.ndarray | None = None
    words: list = field(default_factory=list)   # [{text, start, end}] локально
    t0: float = 0.0


SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def parse_story(path: str, cfg: dict) -> tuple[str, list[Phrase]]:
    with open(path, encoding="utf-8") as f:
        lines = [l.rstrip() for l in f.read().splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        sys.exit("story.txt пустой")
    title = lines[0].strip()
    body = " ".join(l.strip() for l in lines[1:] if l.strip())
    # приводим разные кавычки к «ёлочкам»
    body = re.sub(r"[“„]", "«", body).replace("”", "»")
    body = re.sub(r'"([^"]*)"', r"«\1»", body)

    markers = {norm(m) for m in cfg["ghost"]["markers"]}
    chunks = re.split(r"(«[^»]*»)", body)
    phrases: list[Phrase] = [Phrase(title, "title")]
    prev_outside = ""
    for ch in chunks:
        if not ch.strip():
            continue
        if ch.startswith("«"):
            inner = ch[1:-1].strip()
            clause = re.split(r"[.!?…]", prev_outside.strip().rstrip(":").strip())[-1]
            is_ghost = any(norm(w) in markers for w in clause.split())
            speaker = "ghost" if is_ghost else "narrator"
            for s in SENT_SPLIT.split(inner):
                if norm(s):
                    phrases.append(Phrase(s.strip(), speaker))
        else:
            prev_outside = ch
            text = re.sub(r"^[\s.,!?…:;—-]+", "", ch).strip()
            for s in SENT_SPLIT.split(text):
                if norm(s):
                    phrases.append(Phrase(s.strip(), "narrator"))

    # паузы
    pdef = float(cfg["pauses"]["default"])
    before = {norm(k): float(v) for k, v in cfg["pauses"].get("before", {}).items()}
    for i, ph in enumerate(phrases):
        if i == 0:
            continue
        ph.pause_before = pdef
        n = norm(ph.text)
        for k, v in before.items():
            if n.startswith(k):
                ph.pause_before = v

    # голос: настороженный -> всё более растерянный (лёгкий дрейф темпа/высоты)
    v = cfg["voice"]
    md = v.get("mood_drift", {})
    n = len(phrases)
    for i, ph in enumerate(phrases):
        p = (i / (n - 1)) if (md.get("enabled") and n > 1) else 0.0
        ph.rate = int(round(v["rate"] + p * (md.get("rate_end", v["rate"]) - v["rate"])))
        ph.pitch = int(round(v["pitch"] + p * (md.get("pitch_end", v["pitch"]) - v["pitch"])))
    return title, phrases


# ----------------------------------------------------------------------------- TTS
def _ssl_context():
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        p = os.environ.get(var)
        if p and os.path.isfile(p):
            try:
                ctx.load_verify_locations(p)
            except Exception:
                pass
    return ctx


async def _tts_one(ph: Phrase, voice: str, sem: asyncio.Semaphore):
    import edge_tts
    key = hashlib.sha1(f"{voice}|{ph.rate}|{ph.pitch}|{ph.text}".encode()).hexdigest()[:20]
    mp3, js = os.path.join(CACHE, key + ".mp3"), os.path.join(CACHE, key + ".json")
    if os.path.exists(mp3) and os.path.exists(js):
        with open(js, encoding="utf-8") as f:
            return mp3, json.load(f)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    async with sem:
        attempts = 8
        for attempt in range(attempts):
            try:
                kw = dict(rate=f"{ph.rate:+d}%", pitch=f"{ph.pitch:+d}Hz", boundary="WordBoundary")
                if proxy:
                    kw["proxy"] = proxy
                com = edge_tts.Communicate(ph.text, voice, **kw)
                audio, bounds = bytearray(), []
                async for c in com.stream():
                    if c["type"] == "audio":
                        audio += c["data"]
                    elif c["type"] == "WordBoundary":
                        bounds.append({"text": c["text"], "start": c["offset"] / 1e7,
                                       "end": (c["offset"] + c["duration"]) / 1e7})
                if not audio:
                    raise RuntimeError("пустой ответ edge-tts")
                with open(mp3, "wb") as f:
                    f.write(audio)
                with open(js, "w", encoding="utf-8") as f:
                    json.dump(bounds, f, ensure_ascii=False)
                return mp3, bounds
            except Exception as e:
                if attempt == attempts - 1:
                    raise
                wait = min(30, 3 * (attempt + 1))
                print(f"  edge-tts: «{ph.text[:30]}…» — повтор через {wait} c ({type(e).__name__})")
                await asyncio.sleep(wait)


def decode_audio(path: str) -> np.ndarray:
    raw = run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
              capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def align_words(text: str, bounds: list, uppercase: bool) -> list:
    """Сопоставляет слова из текста (с пунктуацией) с WordBoundary edge-tts."""
    def disp(tok):
        t = tok.strip("«»\"“”„()")
        t = re.sub(r"^[—–-]+", "", t)
        t = re.sub(r"[,.:;]+$", "", t)
        return t.upper() if uppercase else t

    tokens = [t for t in text.split() if norm(t)]
    out, i, ok = [], 0, True
    for tok in tokens:
        nt, coll, st, en = norm(tok), "", None, None
        while i < len(bounds) and len(coll) < len(nt):
            nb = norm(bounds[i]["text"])
            i += 1
            if not nb:
                continue
            if st is None:
                st = bounds[i - 1]["start"]
            coll += nb
            en = bounds[i - 1]["end"]
        if coll != nt:
            ok = False
            break
        out.append({"text": disp(tok), "raw": tok, "norm": nt, "start": st, "end": en})
    if not ok or i < len([b for b in bounds if norm(b["text"])]):
        # фолбэк: показываем слова как их вернул edge-tts (например, числа цифрами)
        out = [{"text": disp(b["text"]), "raw": b["text"], "norm": norm(b["text"]), "start": b["start"], "end": b["end"]}
               for b in bounds if norm(b["text"])]
    return out


def synthesize(phrases: list[Phrase], cfg: dict):
    os.makedirs(CACHE, exist_ok=True)
    voice = cfg["voice"]["name"]
    try:
        import edge_tts.communicate as cm
        if hasattr(cm, "_SSL_CTX"):
            cm._SSL_CTX = _ssl_context()
    except ImportError:
        sys.exit("Не установлен edge-tts: pip install -r requirements.txt")

    async def main():
        sem = asyncio.Semaphore(1)   # сервис edge-tts не любит параллельные запросы
        return await asyncio.gather(*[_tts_one(p, voice, sem) for p in phrases])

    results = asyncio.run(main())
    upper = cfg["subtitles"]["uppercase"]
    for ph, (mp3, bounds) in zip(phrases, results):
        a = decode_audio(mp3)
        # обрезаем тишину по краям, чтобы паузы между фразами были точными
        env = np.convolve(np.abs(a), np.ones(480) / 480, mode="same")
        thr = env.max() * undb(-40)
        idx = np.nonzero(env > thr)[0]
        s = max(0, idx[0] - int(0.03 * SR)) if len(idx) else 0
        e = min(len(a), idx[-1] + int(0.08 * SR)) if len(idx) else len(a)
        if bounds:
            s = min(s, int(bounds[0]["start"] * SR))
        ph.audio = a[s:e]
        ph.words = align_words(ph.text, bounds, upper)
        for w in ph.words:
            w["start"] = max(0.0, w["start"] - s / SR)
            w["end"] = min(len(ph.audio) / SR, w["end"] - s / SR)


# ----------------------------------------------------------------------------- timeline
@dataclass
class Timeline:
    phrases: list
    words: list          # глобальные слова (без заголовка)
    groups: list
    speech_end: float
    cta_start: float
    total: float


PREPS = {"в", "во", "на", "с", "со", "и", "а", "но", "к", "ко", "у", "о", "от", "по", "за", "из", "не", "что", "я"}


def split_groups(norms: list, maxw: int, raws: list | None = None) -> list:
    """Делит фразу на группы по 3–4 слова (DP): штраф за группы из 1–2 слов
    и за предлог/союз в конце группы."""
    n = len(norms)
    if n <= maxw:
        return [n]
    INF = float("inf")
    best = [0.0] + [INF] * n
    prev = [0] * (n + 1)
    for i in range(1, n + 1):
        for sz in range(1, min(maxw, i) + 1):
            j = i - sz
            cost = best[j] + {1: 9, 2: 3}.get(sz, 0) + (sz == maxw) * 0.2
            if i < n and norms[i - 1] in PREPS:
                cost += 6
            if i < n and raws and re.search(r"[,:;—–-]$", raws[i - 1]):
                cost -= 2.5
            if cost < best[i]:
                best[i], prev[i] = cost, j
    sizes, i = [], n
    while i > 0:
        sizes.append(i - prev[i])
        i = prev[i]
    return sizes[::-1]


def build_timeline(phrases: list[Phrase], cfg: dict) -> Timeline:
    t = LEAD
    for i, ph in enumerate(phrases):
        if i > 0:
            t += ph.pause_before
        ph.t0 = t
        t += len(ph.audio) / SR
    speech_end = t

    words, groups = [], []
    maxw = int(cfg["subtitles"]["max_words"])
    for pi, ph in enumerate(phrases):
        if ph.speaker == "title":
            continue
        pw = []
        for w in ph.words:
            gw = dict(w, start=ph.t0 + w["start"], end=ph.t0 + w["end"],
                      ghost=ph.speaker == "ghost", phrase=pi)
            pw.append(gw)
        n = len(pw)
        if not n:
            continue
        sizes = split_groups([w["norm"] for w in pw], maxw, [w.get("raw", "") for w in pw])
        pos = 0
        for sz in sizes:
            groups.append({"words": pw[pos:pos + sz], "ghost": ph.speaker == "ghost"})
            pos += sz
        words.extend(pw)

    for g in groups:
        g["start"] = g["words"][0]["start"]
    for gi, g in enumerate(groups):
        last_end = g["words"][-1]["end"]
        nxt = groups[gi + 1]["start"] if gi + 1 < len(groups) else None
        g["end"] = nxt if (nxt is not None and nxt - last_end < 0.75) else last_end + 0.35
        for wi, w in enumerate(g["words"]):
            w["hl_end"] = g["words"][wi + 1]["start"] if wi + 1 < len(g["words"]) else g["end"]

    cta_start = speech_end + 0.9
    total = cta_start + float(cfg["cta"]["duration"])
    dmin = float(cfg["duration"]["min"])
    if total < dmin:
        cta_start += dmin - total
        total = dmin
    return Timeline(phrases, words, groups, speech_end, cta_start, total)


def find_trigger(words: list, match: str):
    """Возвращает время срабатывания: начало первого слова совпадения."""
    if not words:
        return None
    if match.startswith("@last"):
        k = int(match.split(":")[1]) if ":" in match else 1
        return words[max(0, len(words) - k)]["start"]
    stems = [norm(s) for s in match.split() if norm(s)]
    for i in range(len(words) - len(stems) + 1):
        if all(words[i + j]["norm"].startswith(stems[j]) for j in range(len(stems))):
            return words[i]["start"]
    return None


# ----------------------------------------------------------------------------- audio
from scipy.signal import butter, sosfilt, fftconvolve  # noqa: E402

_rng = np.random.default_rng(7)


def noise(n):
    return _rng.standard_normal(n).astype(np.float64)


def lp(x, f, order=4):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x)


def hp(x, f, order=4):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=3):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def tvec(dur):
    return np.arange(int(dur * SR)) / SR


def peak_norm(x, d):
    m = np.max(np.abs(x))
    return x * (undb(d) / m) if m > 0 else x


def reverb(x, tau=0.35, length=1.2, wet=0.25, lowcut=3500):
    t = tvec(length)
    ir = lp(noise(len(t)), lowcut) * np.exp(-t / tau)
    ir /= np.sqrt(np.sum(ir ** 2))
    if x.ndim == 1:
        w = fftconvolve(x, ir)
        d = np.concatenate([x, np.zeros(len(w) - len(x))])
        return d + wet * w
    return np.stack([reverb(x[:, c], tau, length, wet, lowcut) for c in range(x.shape[1])], 1)


def stereo(x, pan=0.0):
    l, r = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
    return np.stack([x * l * 1.414, x * r * 1.414], 1)


def sfx_chair():
    out = np.zeros(int(1.4 * SR))
    for off, amp in [(0.0, 1.0), (0.30, 0.72), (0.63, 0.9)]:
        t = tvec(0.4)
        f = 52 + 75 * np.exp(-t / 0.022)
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.075)
        knock = bp(noise(len(t)), 140, 800) * np.exp(-t / 0.011) * 0.5
        thump = lp(noise(len(t)), 220) * np.exp(-t / 0.035) * 2.5
        s = body + knock + thump
        i = int(off * SR)
        out[i:i + len(s)] += amp * s
    out = lp(out, 1800, 2)
    out = reverb(out, tau=0.18, length=0.7, wet=0.22, lowcut=1500)
    return stereo(peak_norm(out, -10), -0.15)


def sfx_whoosh():
    t = tvec(1.2)
    peak = 0.55
    env = np.where(t < peak, (t / peak) ** 2.2, np.exp(-(t - peak) / 0.2))
    env_hi = np.where(t < peak - 0.08, (t / (peak - 0.08)) ** 2.5, np.exp(-(t - peak + 0.08) / 0.15))
    s = bp(noise(len(t)), 250, 1400) * env + 0.55 * bp(noise(len(t)), 1400, 5000) * env_hi
    s = peak_norm(s, -15)
    th = np.clip(t / 1.0, 0, 1) * (math.pi / 2)
    return np.stack([s * np.cos(th) * 1.3, s * np.sin(th) * 1.3], 1)


def sfx_slurp():
    dur = 0.85
    n = int(dur * SR)
    t = np.arange(n) / SR
    # источник: шум с «булькающей» амплитудной модуляцией
    jitter = np.cumsum(_rng.standard_normal(n)) * 0.002
    gurgle = 0.5 + 0.5 * np.tanh(4 * np.sin(2 * np.pi * 26 * t + jitter * 30))
    src = noise(n) * gurgle
    # резонансный фильтр с плавающей частотой (вверх — «втягивание»)
    fc = np.where(t < 0.55, 380 * (1700 / 380) ** (t / 0.55), 900 * (2100 / 900) ** np.clip((t - 0.6) / 0.2, 0, 1))
    out = np.zeros(n)
    low = band = 0.0
    q = 0.12
    f_arr = 2 * np.sin(np.pi * fc / SR)
    for i in range(n):
        f = f_arr[i]
        low += f * band
        high = src[i] - low - q * band
        band += f * high
        out[i] = band
    env = np.clip(t / 0.03, 0, 1) * np.where(t < 0.45, 1, np.exp(-(t - 0.45) / 0.05))
    env2 = np.where((t > 0.6) & (t < 0.82), np.sin(np.pi * (t - 0.6) / 0.22) * 0.55, 0)
    out = out * (env + env2)
    out = hp(out, 200, 2)
    out = reverb(out, tau=0.12, length=0.5, wet=0.15)
    return stereo(peak_norm(out, -13), 0.1)


def sfx_vanish():
    t = tvec(2.2)
    glide = 0.3 + 0.7 * np.exp(-t / 0.7)
    tone = np.zeros(len(t))
    for f0, a in [(1320, 1.0), (1760, 0.6), (2350, 0.35)]:
        tone += a * np.sin(2 * np.pi * np.cumsum(f0 * glide) / SR)
    tone *= (0.65 + 0.35 * np.sin(2 * np.pi * 9 * t)) * np.clip(t / 0.06, 0, 1) * np.exp(-t / 0.55)
    air = bp(noise(len(t)), 2500, 8000) * np.sin(np.pi * np.clip(t / 1.4, 0, 1)) ** 2
    s = 0.6 * tone + 0.5 * air * np.exp(-t / 0.8)
    s = reverb(s, tau=0.6, length=1.8, wet=0.45, lowcut=6000)
    st = np.stack([s, np.roll(s, 240) * 0.9], 1)
    return st * (undb(-17) / np.max(np.abs(st)))


SFX = {"chair": sfx_chair, "whoosh": sfx_whoosh, "slurp": sfx_slurp, "vanish": sfx_vanish}


def make_drone(n):
    t = np.arange(n) / SR
    out = []
    for det, ph in [(0.0, 0.0), (0.21, 1.3)]:
        x = (0.50 * np.sin(2 * np.pi * (55 + det) * t + ph)
             + 0.30 * np.sin(2 * np.pi * (55.37 + det) * t)
             + 0.22 * np.sin(2 * np.pi * (82.4 + det) * t + ph) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.05 * t))
             + 0.10 * np.sin(2 * np.pi * (110.7 + det) * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.08 * t + 1 + ph))
             + 0.35 * lp(noise(n), 260) * (0.7 + 0.3 * np.sin(2 * np.pi * 0.03 * t + ph)))
        out.append(x)
    x = np.stack(out, 1)
    fade = np.minimum(1, np.minimum(t / 1.5, (t[-1] - t) / 1.2 + 1e-9))[:, None]
    return x * np.clip(fade, 0, 1)


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def build_audio(tl: Timeline, cfg: dict, out_wav: str, limit: float | None):
    total = tl.total if limit is None else min(limit, tl.total)
    n = int(math.ceil(tl.total * SR)) + SR * 3
    voice = np.zeros(n)
    for ph in tl.phrases:
        i = int(ph.t0 * SR)
        voice[i:i + len(ph.audio)] += ph.audio
    # громкость голоса по активной речи
    frame = SR // 50
    fr = voice[: len(voice) // frame * frame].reshape(-1, frame)
    fr_rms = np.sqrt(np.mean(fr ** 2, 1))
    active = fr[fr_rms > fr_rms.max() * undb(-35)]
    g = undb(cfg["audio"]["voice_rms_db"]) / max(rms(active), 1e-9)
    voice *= g
    voice_db = db(rms(active) * g)

    drone = make_drone(n)
    drone *= undb(cfg["audio"]["drone_db"]) / rms(drone[: int(tl.total * SR)])
    drone_db = db(rms(drone[: int(tl.total * SR)]))
    min_gap = float(cfg["audio"]["min_voice_over_music_db"])
    if voice_db - drone_db < min_gap:
        drone *= undb(voice_db - min_gap - drone_db)
        drone_db = voice_db - min_gap

    sfx = np.zeros((n, 2))
    for s in cfg.get("sfx", []):
        tt = find_trigger(tl.words, s["match"])
        if tt is None:
            print(f"  [звук] триггер «{s['match']}» не найден в тексте — пропускаю")
            continue
        fn = SFX.get(s["type"])
        if not fn:
            print(f"  [звук] неизвестный тип {s['type']}")
            continue
        clip = fn() * undb(float(s.get("gain_db", 0)))
        i = int((tt + float(s.get("offset", 0))) * SR)
        sfx[i:i + len(clip)] += clip[: n - i]
        print(f"  [звук] {s['type']:7s} @ {tt:6.2f} c  («{s['match']}»)")

    mix = voice[:, None] + drone + sfx
    mix = mix[: int(math.ceil(total * SR))]
    if limit is not None and limit < tl.total:
        k = int(0.3 * SR)
        mix[-k:] *= np.linspace(1, 0, k)[:, None]
    peak = np.max(np.abs(mix))
    if peak > undb(-1):
        mix *= undb(-1) / peak
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    print(f"  голос (активная речь) {voice_db:.1f} dBFS, дрон {drone_db:.1f} dBFS → разница {voice_db - drone_db:.1f} dB")


# ----------------------------------------------------------------------------- fonts / text
_font_cache: dict = {}


def find_font(name: str) -> str | None:
    cands = [name, "Inter-ExtraBold", "InterDisplay-ExtraBold", "DejaVuSans-Bold"]
    dirs = [os.path.join(HERE, "fonts"), "/usr/share/fonts", "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts"),
            "/Library/Fonts", "/System/Library/Fonts", os.path.expanduser("~/Library/Fonts"),
            "C:/Windows/Fonts"]
    for c in cands:
        for d in dirs:
            for ext in ("ttf", "otf"):
                hits = glob.glob(os.path.join(d, "**", f"{c}.{ext}"), recursive=True)
                if hits:
                    return hits[0]
    if shutil.which("fc-match"):
        try:
            p = subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Sans:bold"],
                               capture_output=True, text=True).stdout.strip()
            if p and os.path.exists(p):
                return p
        except Exception:
            pass
    return None


FONT_PATH: str | None = None


def font(size: int):
    size = max(8, int(size))
    if size not in _font_cache:
        _font_cache[size] = (ImageFont.truetype(FONT_PATH, size) if FONT_PATH
                             else ImageFont.load_default(size))
    return _font_cache[size]


def layout_words(texts: list, size: int, max_w: int, max_lines=2):
    """Раскладывает слова по строкам; уменьшает шрифт, если не влезает."""
    while True:
        f = font(size)
        sp = f.getlength(" ") + size * 0.14
        widths = [f.getlength(t) for t in texts]
        lines, cur, cw = [], [], 0.0
        for i, w in enumerate(widths):
            add = w if not cur else cw + sp + w
            if cur and add > max_w:
                lines.append(cur)
                cur, cw = [i], w
            else:
                cur.append(i)
                cw = add
        if cur:
            lines.append(cur)
        if (len(lines) <= max_lines and max(widths) <= max_w) or size < 40:
            return size, lines, widths, sp
        size = int(size * 0.92)


def render_text_layer(lines_text: list, size: int, fill, stroke_fill, stroke_w, width=W, line_gap=1.12):
    f = font(size)
    lh = int(size * line_gap)
    hgt = lh * len(lines_text) + stroke_w * 4 + 20
    img = Image.new("RGBA", (width, hgt), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, s in enumerate(lines_text):
        y = stroke_w * 2 + 10 + lh * i + lh // 2
        d.text((width // 2, y + 7), s, font=f, anchor="mm", fill=(0, 0, 0, 150),
               stroke_width=stroke_w, stroke_fill=(0, 0, 0, 150))
        d.text((width // 2, y), s, font=f, anchor="mm", fill=fill, stroke_width=stroke_w, stroke_fill=stroke_fill)
    return img


def wrap_text(text: str, size: int, max_w: int) -> list:
    f = font(size)
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if cur and f.getlength(test) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


# ----------------------------------------------------------------------------- backgrounds
def fft_noise(h, w, scale, seed):
    r = np.random.default_rng(seed)
    wn = r.standard_normal((h, w))
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    g = np.exp(-((fy ** 2 + fx ** 2) * (scale ** 2)))
    x = np.fft.irfft2(np.fft.rfft2(wn) * g, s=(h, w))
    x = (x - x.min()) / (x.max() - x.min())
    return x


class GeneratedBG:
    """Тёмный сине-зелёный градиент, движущийся туман и редкие вспышки света."""
    LW, LH = 270, 480

    def __init__(self, cfg, total, seed):
        c = cfg["colors"]
        top, bot = np.array(hex_rgb(c["bg_top"]), float), np.array(hex_rgb(c["bg_bottom"]), float)
        y = np.linspace(0, 1, self.LH)[:, None, None]
        x = np.linspace(-1, 1, self.LW)[None, :, None]
        self.base = top * (1 - y) + bot * y + np.zeros((1, self.LW, 1))
        yy = np.linspace(-1, 1, self.LH)[:, None]
        xx = np.linspace(-1, 1, self.LW)[None, :]
        self.vign = (1 - 0.55 * np.clip((xx ** 2 * 0.9 + yy ** 2 * 0.6), 0, 1))[..., None]
        self.fogc = np.array(hex_rgb(c["fog"]), float)
        self.f1 = fft_noise(self.LH, self.LW, 22, seed)
        self.f2 = fft_noise(self.LH, self.LW, 10, seed + 1)
        self.fogmask = (0.35 + 0.65 * np.linspace(0, 1, self.LH) ** 1.3)[:, None]
        gx, gy = 0.75, -0.1
        d = np.sqrt((xx - (gx * 2 - 1)) ** 2 * 1.0 + (yy - (gy * 2 - 1)) ** 2 * 0.5)
        self.glow = (np.exp(-d ** 2 / 0.9) * 0.8 + 0.25)[..., None]
        rnd = random.Random(seed)
        self.flashes, t = [], rnd.uniform(4.0, 7.0)
        while t < total - 2:
            self.flashes.append(t)
            t += rnd.uniform(7.0, 13.0)

    def frame(self, t):
        s1 = (int(t * 7) % self.LW, int(t * 2) % self.LH)
        s2 = (-int(t * 13) % self.LW, int(t * 1) % self.LH)
        f1 = np.roll(np.roll(self.f1, s1[0], 1), s1[1], 0)
        f2 = np.roll(np.roll(self.f2, s2[0], 1), s2[1], 0)
        fog = np.clip((0.65 * f1 + 0.35 * f2 - 0.35) * 1.6, 0, 1) * self.fogmask
        a = (0.20 + 0.04 * math.sin(t * 0.6)) * fog[..., None]
        img = self.base * (1 - a) + self.fogc * a
        breathe = 1.0 + 0.05 * math.sin(t * 0.9)
        img = img * self.vign * breathe
        fl = 0.0
        for ft in self.flashes:
            dt = t - ft
            if 0 <= dt < 0.9:
                fl += math.exp(-dt / 0.05) + (0.7 * math.exp(-(dt - 0.2) / 0.08) if dt >= 0.2 else 0)
        if fl > 0:
            img = img + np.array([170, 195, 235.0]) * self.glow * min(fl, 1.3) * 0.45
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
        return im.resize((W, H), Image.BICUBIC)

    def close(self):
        pass


class VideoBG:
    """Случайное видео из bg/: зациклено, центральный вырез 9:16, -35% яркости, холодный оттенок."""

    def __init__(self, path, total, fps):
        k = 0.65
        vf = (f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={W}:{H}:flags=lanczos,setsar=1,fps={fps},"
              f"colorchannelmixer=rr={k * 0.86:.3f}:gg={k * 0.97:.3f}:bb={k * 1.12:.3f},"
              f"colorbalance=bs=0.10:bm=0.06:rs=-0.04:rm=-0.03")
        cmd = ["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", path, "-t", f"{total + 1:.2f}",
               "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        self.last = Image.new("RGB", (W, H), (10, 15, 25))

    def frame(self, t):
        buf = self.p.stdout.read(W * H * 3)
        if len(buf) == W * H * 3:
            self.last = Image.frombuffer("RGB", (W, H), buf, "raw", "RGB", 0, 1)
        return self.last.copy()

    def close(self):
        try:
            self.p.stdout.close()
            self.p.kill()
        except Exception:
            pass


def pick_background(bg_dir, total, fps, cfg, seed):
    files = []
    if os.path.isdir(bg_dir):
        files = [f for f in sorted(os.listdir(bg_dir)) if f.lower().endswith((".mp4", ".mov"))]
    if files:
        f = random.Random().choice(files)
        print(f"  фон: видео {os.path.join(bg_dir, f)}")
        return VideoBG(os.path.join(bg_dir, f), total, fps), False
    print("  фон: сгенерированный (градиент + туман + вспышки)")
    return GeneratedBG(cfg, total, seed), True


# ----------------------------------------------------------------------------- render
def ease_out_back(x):
    c1, c3 = 1.70158, 2.70158
    x = min(1.0, max(0.0, x))
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def paste_layer(frame: Image.Image, layer: Image.Image, center, alpha=1.0, scale=1.0):
    if alpha <= 0.01:
        return
    if abs(scale - 1) > 1e-3:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.BILINEAR)
    a = layer.getchannel("A")
    if alpha < 0.999:
        a = a.point(lambda v: int(v * alpha))
    x, y = int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)
    frame.paste(layer.convert("RGB"), (x, y), a)


class Renderer:
    def __init__(self, tl: Timeline, cfg: dict, title: str):
        self.tl, self.cfg = tl, cfg
        c = cfg["colors"]
        self.col = {k: hex_rgb(v) for k, v in c.items()}
        sc = cfg["subtitles"]
        self.size, self.stroke, self.yc = int(sc["size"]), int(sc["stroke"]), float(sc["y"]) * H
        self.max_w = int(W * 0.88)
        # заголовок
        tc = cfg["title"]
        ttxt = title.upper() if sc["uppercase"] else title
        tsize = int(tc["size"])
        tlines = wrap_text(ttxt, tsize, int(W * 0.86))
        self.title_layer = render_text_layer(tlines, tsize, self.col["text"], self.col["stroke"], 11)
        d = ImageDraw.Draw(self.title_layer)
        bw = 160
        d.rounded_rectangle([W // 2 - bw, self.title_layer.height - 14, W // 2 + bw, self.title_layer.height - 4],
                            radius=5, fill=self.col["highlight"] + (255,))
        self.title_dur = float(tc["duration"])
        # плашка CTA
        self.cta_layer = self._make_cta(cfg["cta"]["text"])
        # эффекты
        self.vfx = []
        for v in cfg.get("vfx", []):
            tt = find_trigger(tl.words, v["match"])
            if tt is None:
                print(f"  [эффект] триггер «{v['match']}» не найден — пропускаю")
                continue
            self.vfx.append((v, tt))
            print(f"  [эффект] {v['type']:7s} @ {tt:6.2f} c  («{v['match']}»)")
        self.layouts = {}

    def _make_cta(self, text):
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if self.cfg["subtitles"]["uppercase"]:
            lines = [l.upper() for l in lines]
        sizes = [118] + [84] * (len(lines) - 1)
        fs = [font(s) for s in sizes]
        tw = max(f.getlength(l) for f, l in zip(fs, lines))
        pad_x, pad_y, gap = 70, 50, 18
        hs = [int(s * 1.05) for s in sizes]
        pw, ph = int(tw + 2 * pad_x), int(sum(hs) + gap * (len(lines) - 1) + 2 * pad_y)
        img = Image.new("RGBA", (pw + 40, ph + 50), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([20, 34, 20 + pw, 34 + ph], radius=46, fill=(0, 0, 0, 120))
        d.rounded_rectangle([20, 20, 20 + pw, 20 + ph], radius=46, fill=self.col["cta_plate"] + (255,),
                            outline=(255, 255, 255, 255), width=6)
        y = 20 + pad_y
        for f, l, hh in zip(fs, lines, hs):
            d.text((20 + pw // 2, y + hh // 2), l, font=f, anchor="mm", fill=self.col["cta_text"],
                   stroke_width=4, stroke_fill=(90, 0, 0))
            y += hh + gap
        return img

    def bg_effects(self, im: Image.Image, t: float) -> Image.Image:
        for v, tt in self.vfx:
            dt = t - tt
            if v["type"] == "flicker" and 0 <= dt < float(v.get("length", 1.0)):
                L = float(v.get("length", 1.0))
                env = math.sin(math.pi * dt / L)
                fl = 1.0 + 0.28 * math.sin(2 * math.pi * 11 * dt) * math.sin(2 * math.pi * 2.7 * dt + 0.5)
                pale = Image.new("RGB", im.size, (165, 185, 195))
                im = Image.blend(im, pale, 0.28 * env)
                im = ImageEnhance.Color(im).enhance(1 - 0.5 * env)
                im = ImageEnhance.Brightness(im).enhance(fl)
            elif v["type"] == "dim" and dt >= 0:
                f = 1 - float(v.get("amount", 0.4)) * smoothstep(dt / float(v.get("fade", 1.2)))
                im = ImageEnhance.Brightness(im).enhance(f)
        return im

    def draw_subs(self, im: Image.Image, t: float):
        g = None
        for gr in self.tl.groups:
            if gr["start"] <= t < gr["end"]:
                g = gr
                break
        if g is None or t < self.title_dur * 0.9 or t >= self.tl.cta_start:
            return
        key = id(g)
        if key not in self.layouts:
            self.layouts[key] = layout_words([w["text"] for w in g["words"]], self.size, self.max_w)
        size, lines, widths, sp = self.layouts[key]
        lh = size * 1.27
        top = self.yc - lh * len(lines) / 2
        dtg = t - g["start"]
        slide = 16 * (1 - smoothstep(dtg / 0.1))
        d = ImageDraw.Draw(im)
        f = font(size)
        ghost = g["ghost"]
        base_col = self.col["ghost_text"] if ghost else self.col["text"]
        hl_col = self.col["ghost_highlight"] if ghost else self.col["highlight"]
        cur = None
        items = []
        for li, line in enumerate(lines):
            lw = sum(widths[i] for i in line) + sp * (len(line) - 1)
            x = (W - lw) / 2
            cy = top + lh * li + lh / 2 + slide
            for i in line:
                w = g["words"][i]
                cx = x + widths[i] / 2
                active = w["start"] <= t < w["hl_end"]
                items.append((w, cx, cy, active))
                if active:
                    cur = (w, cx, cy)
                x += widths[i] + sp
        sw = self.stroke
        for w, cx, cy, active in items:
            if active:
                continue
            d.text((cx, cy + 7), w["text"], font=f, anchor="mm", fill=(0, 0, 0), stroke_width=sw, stroke_fill=(0, 0, 0))
        for w, cx, cy, active in items:
            if active:
                continue
            d.text((cx, cy), w["text"], font=f, anchor="mm", fill=base_col, stroke_width=sw, stroke_fill=self.col["stroke"])
        if cur:
            w, cx, cy = cur
            dt = t - w["start"]
            s = 1 + 0.10 * math.exp(-dt / 0.12) + 0.045 * math.sin(math.pi * 2.4 * dt) ** 2
            fs = font(int(size * s))
            d.text((cx, cy + 8), w["text"], font=fs, anchor="mm", fill=(0, 0, 0), stroke_width=sw + 1, stroke_fill=(0, 0, 0))
            d.text((cx, cy), w["text"], font=fs, anchor="mm", fill=hl_col, stroke_width=sw + 1, stroke_fill=self.col["stroke"])

    def overlay(self, im: Image.Image, t: float):
        # заголовок
        if t < self.title_dur:
            fade_start = self.title_dur - 0.4
            a = 1.0 if t < fade_start else 1 - smoothstep((t - fade_start) / 0.4)
            sc = 1.0 + 0.04 * (t / self.title_dur)
            paste_layer(im, self.title_layer, (W / 2, H * 0.45), a, sc)
        self.draw_subs(im, t)
        # финальная плашка
        if t >= self.tl.cta_start:
            dt = t - self.tl.cta_start
            sc = 0.55 + 0.45 * ease_out_back(dt / 0.35)
            sc *= 1 + 0.02 * math.sin(2 * math.pi * 1.6 * max(0, dt - 0.35))
            a = smoothstep(dt / 0.12)
            paste_layer(im, self.cta_layer, (W / 2, H * 0.5), a, sc)


def render_video(tl, cfg, title, fps, out_path, wav, limit, bg_dir, seed):
    total = tl.total if limit is None else min(limit, tl.total)
    nframes = int(round(total * fps))
    bg, generated = pick_background(bg_dir, total, fps, cfg, seed)
    r = Renderer(tl, cfg, title)
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", wav,
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-g", str(fps * 2),
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
           "-shortest", "-movflags", "+faststart", out_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    step = max(1, nframes // 20)
    try:
        for i in range(nframes):
            t = i / fps
            im = bg.frame(t)
            im = r.bg_effects(im, t)
            r.overlay(im, t)
            p.stdin.write(im.tobytes())
            if i % step == 0:
                print(f"\r  кадры: {i}/{nframes} ({100 * i // nframes}%)", end="", flush=True)
        print(f"\r  кадры: {nframes}/{nframes} (100%)")
    finally:
        bg.close()
        p.stdin.close()
        p.wait()
    if p.returncode != 0:
        sys.exit("ffmpeg завершился с ошибкой")
    return generated


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Вертикальное видео-история с озвучкой и субтитрами")
    ap.add_argument("story", nargs="?", default="story.txt")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--fps", type=int, default=30, choices=[24, 25, 30, 50, 60])
    ap.add_argument("--limit", type=float, default=None, help="отрендерить только первые N секунд (пробная версия)")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--bg-dir", default=os.path.join(HERE, "bg"))
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    ensure_ffmpeg()
    cfg = DEFAULT_CONFIG
    if os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            cfg = deep_merge(DEFAULT_CONFIG, json.load(f))

    global FONT_PATH
    FONT_PATH = find_font(cfg["subtitles"]["font"])
    print(f"Шрифт: {FONT_PATH or 'встроенный Pillow (не найден Inter/DejaVu)'}")

    title, phrases = parse_story(args.story, cfg)
    seed = args.seed if args.seed is not None else int(hashlib.md5(title.encode()).hexdigest()[:6], 16)
    print(f"Заголовок: {title}\nФраз: {len(phrases) - 1} (+ заголовок)")
    for ph in phrases:
        tag = {"title": "ЗАГОЛОВОК", "narrator": "рассказчик", "ghost": "ПРИЗРАК"}[ph.speaker]
        print(f"  [{tag:10s}] пауза {ph.pause_before:.1f}с  {ph.rate:+d}% {ph.pitch:+d}Hz  {ph.text}")

    print("Озвучка (edge-tts)…")
    synthesize(phrases, cfg)
    tl = build_timeline(phrases, cfg)
    print(f"Длительность: речь до {tl.speech_end:.2f} c, плашка с {tl.cta_start:.2f} c, всего {tl.total:.2f} c")
    dmin, dmax = cfg["duration"]["min"], cfg["duration"]["max"]
    if tl.total > dmax:
        print(f"  ВНИМАНИЕ: ролик длиннее {dmax} c — сократите историю или ускорьте голос (voice.rate в config.json)")

    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "mix.wav")
        print("Звук…")
        build_audio(tl, cfg, wav, args.limit)
        print(f"Видео ({args.fps} fps)…")
        generated = render_video(tl, cfg, title, args.fps, args.output, wav, args.limit, args.bg_dir, seed)

    print(f"\nГотово: {os.path.abspath(args.output)}")
    if generated:
        print("Подсказка: положите свои .mp4/.mov в папку bg/ — фон будет взят оттуда "
              "(случайный файл, зациклен, обрезан до 9:16, затемнён и подкрашен в холодный синий).")


if __name__ == "__main__":
    main()
