#!/usr/bin/env python3
"""
Генератор вертикального видео «страшная и смешная история».

    python generate.py story.txt                 -> output.mp4 (30 fps)
    python generate.py story.txt --fps 60        -> 60 fps
    python generate.py story.txt --preview 15    -> только первые 15 секунд

История: story.txt (первая строка — заголовок).
Голос, цвета, фразы-триггеры эффектов: config.json.
Фоновые видео: папка bg/ (.mp4 / .mov). Если пусто — генерируется фон.
"""
from __future__ import annotations

import argparse
import asyncio
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
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
SR = 48000
LEAD_IN = 0.15  # тишина перед первой фразой, с


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(f"[gen] {msg}", flush=True)


def hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore


def norm_word(s: str) -> str:
    s = s.lower().replace("ё", "е")
    return re.sub(r"[^\w]", "", s)


def db2amp(db: float) -> float:
    return 10 ** (db / 20)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)) + 1e-12))


def amp2db(a: float) -> float:
    return 20 * math.log10(max(a, 1e-9))


def need_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"Не найден {tool}. Установите ffmpeg (apt install ffmpeg / brew install ffmpeg).")


def find_font() -> str:
    candidates = [
        ROOT / "fonts" / "Inter-ExtraBold.otf",
        ROOT / "fonts" / "Inter-ExtraBold.ttf",
        Path("/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf"),
        Path("/usr/share/fonts/truetype/inter/Inter-ExtraBold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/Library/Fonts/Inter-ExtraBold.otf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Sans:bold"],
                             capture_output=True, text=True).stdout.strip()
        if out:
            return out
    except FileNotFoundError:
        pass
    sys.exit("Не найден шрифт: положите Inter-ExtraBold.otf в папку fonts/")


_font_cache: dict[int, ImageFont.FreeTypeFont] = {}
FONT_PATH = ""


def font(size: int) -> ImageFont.FreeTypeFont:
    size = max(8, int(round(size)))
    f = _font_cache.get(size)
    if f is None:
        f = ImageFont.truetype(FONT_PATH, size)
        _font_cache[size] = f
    return f


# ──────────────────────────────────────────────────────────────────────────────
# Разбор истории
# ──────────────────────────────────────────────────────────────────────────────
SENT_SPLIT = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][»\"”]))\s+(?=[«\"„“(—-]?[A-ZА-ЯЁ0-9])")


@dataclass
class Segment:
    text: str
    pause_before: float
    is_title: bool = False
    is_joke: bool = False
    audio: np.ndarray | None = None
    words: list = field(default_factory=list)  # [(token, start, end)] локальное время


def find_phrase_pos(text: str, phrase: str) -> int:
    """Позиция фразы в тексте без учёта регистра и ё/е; -1 если нет."""
    t = text.lower().replace("ё", "е")
    p = phrase.lower().replace("ё", "е")
    return t.find(p)


def build_segments(story_path: Path, cfg: dict) -> tuple[str, list[Segment]]:
    raw = story_path.read_text(encoding="utf-8").strip().splitlines()
    if not raw:
        sys.exit("story.txt пуст")
    title = raw[0].strip()
    body = " ".join(l.strip() for l in raw[1:] if l.strip())
    sentences = [s.strip() for s in SENT_SPLIT.split(body) if s.strip()]

    v = cfg["voice"]
    cues = cfg["cues"]
    joke_start, joke_end = cues.get("joke_start", ""), cues.get("joke_end", "")

    segs: list[Segment] = []
    if v.get("speak_title", True):
        segs.append(Segment(title, 0.0, is_title=True))

    in_joke = False
    joke_done = False
    for s in sentences:
        pause = v["sentence_pause"] if segs else 0.0
        pos = find_phrase_pos(s, joke_start) if (joke_start and not joke_done) else -1
        if pos >= 0:
            # отделяем начало шутки длинной паузой (с открывающей кавычкой)
            cut = pos
            while cut > 0 and s[cut - 1] in "«\"„“ ":
                cut -= 1
            while cut < pos and s[cut] == " ":
                cut += 1
            head, tail = s[:cut].strip(), s[cut:].strip()
            if head:
                segs.append(Segment(head, pause))
            segs.append(Segment(tail, v["joke_pause"], is_joke=True))
            in_joke = True
            joke_done = True
            if joke_end and find_phrase_pos(tail, joke_end) >= 0:
                in_joke = False
            continue
        segs.append(Segment(s, pause, is_joke=in_joke))
        if in_joke and joke_end and find_phrase_pos(s, joke_end) >= 0:
            in_joke = False
    if joke_start and not joke_done:
        log(f"⚠ фраза шутки «{joke_start}» не найдена — пауза/жёлтая подсветка отключены")
    return title, segs


# ──────────────────────────────────────────────────────────────────────────────
# Озвучка edge-tts
# ──────────────────────────────────────────────────────────────────────────────
def _ssl_context() -> ssl.SSLContext:
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        p = os.environ.get(var)
        if p and Path(p).exists():
            return ssl.create_default_context(cafile=p)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


async def _tts_one(text: str, voice: str, rate: str, pitch: str, sem: asyncio.Semaphore):
    import edge_tts
    import edge_tts.communicate as ec
    ec._SSL_CTX = _ssl_context()  # корпоративные прокси / свои CA
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    async with sem:
        last_err = None
        for attempt in range(6):
            try:
                spoken = text if re.search(r"[.!?…][»\"”]?$", text) else text + "."
                comm = edge_tts.Communicate(spoken, voice, rate=rate, pitch=pitch,
                                            boundary="WordBoundary", proxy=proxy)
                audio = bytearray()
                words = []
                async for ch in comm.stream():
                    if ch["type"] == "audio":
                        audio.extend(ch["data"])
                    elif ch["type"] == "WordBoundary":
                        st = ch["offset"] / 1e7
                        words.append((ch["text"], st, st + ch["duration"] / 1e7))
                if not audio:
                    raise RuntimeError("пустой ответ edge-tts")
                return bytes(audio), words
            except Exception as e:  # noqa: BLE001
                last_err = e
                await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"edge-tts не ответил для «{text[:40]}»: {last_err}")


def decode_mp3(data: bytes) -> np.ndarray:
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", str(SR), "pipe:1"],
        input=data, capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def synthesize(segs: list[Segment], voice: str, rate: str, pitch: str) -> None:
    cache = ROOT / ".cache" / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    todo = []
    for s in segs:
        key = hashlib.sha1(f"{voice}|{rate}|{pitch}|{s.text}".encode()).hexdigest()[:16]
        todo.append((s, cache / f"{key}.mp3", cache / f"{key}.json"))

    missing = [t for t in todo if not (t[1].exists() and t[2].exists())]
    if missing:
        log(f"озвучка edge-tts: {len(missing)} фраз ({voice}, rate {rate}, pitch {pitch})")

        async def one(s, mp3, js, sem):
            audio, words = await _tts_one(s.text, voice, rate, pitch, sem)
            mp3.write_bytes(audio)  # кэш сразу: при сбое повторный запуск доозвучит только остальное
            js.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")

        async def run():
            sem = asyncio.Semaphore(2)
            await asyncio.gather(*[one(s, mp3, js, sem) for s, mp3, js in missing])
        asyncio.run(run())

    for s, mp3, js in todo:
        audio = decode_mp3(mp3.read_bytes())
        words = [tuple(w) for w in json.loads(js.read_text(encoding="utf-8"))]
        # обрезаем тишину по краям, чтобы паузы были точными
        env = np.abs(audio)
        thr = db2amp(-42) * max(env.max(), 1e-6)
        idx = np.nonzero(env > thr)[0]
        a, b = (idx[0], idx[-1]) if len(idx) else (0, len(audio) - 1)
        a = max(0, a - int(0.02 * SR))
        b = min(len(audio), b + int(0.06 * SR))
        off = a / SR
        s.audio = audio[a:b]
        s.words = align_words(s.text, [(t, st - off, en - off) for t, st, en in words], len(s.audio) / SR)


def align_words(text: str, bwords: list, seg_len: float) -> list:
    """Сопоставляет WordBoundary со словами исходного текста (с пунктуацией)."""
    tokens = text.split()
    # тире-одиночки приклеиваем к предыдущему слову
    merged: list[str] = []
    for t in tokens:
        if merged and not norm_word(t):
            merged[-1] += " " + t
        else:
            merged.append(t)
    tokens = merged
    times: list[list[float] | None] = [None] * len(tokens)
    j = 0
    for bt, st, en in bwords:
        nb = norm_word(bt)
        if not nb:
            continue
        k = j
        found = -1
        while k < len(tokens) and k < j + 4:
            nt = norm_word(tokens[k])
            if nb in nt or (nt and nt in nb):
                found = k
                break
            k += 1
        if found < 0:
            continue
        if times[found] is None:
            times[found] = [st, en]
        else:
            times[found][1] = max(times[found][1], en)
        j = found  # тот же токен может получить несколько границ (кто-то)
        # двигаемся дальше, если слово полностью покрыто
        if norm_word(tokens[found]).endswith(nb):
            j = found + 1
    # интерполяция для несопоставленных
    n = len(tokens)
    for i in range(n):
        if times[i] is None:
            prev_end = next((times[k][1] for k in range(i - 1, -1, -1) if times[k]), 0.0)
            nxt = next(((k, times[k][0]) for k in range(i + 1, n) if times[k]), (n, seg_len))
            gap = (nxt[1] - prev_end) / max(1, nxt[0] - i + 0)
            times[i] = [prev_end, prev_end + max(gap, 0.12)]
    out = []
    for t, (st, en) in zip(tokens, times):
        out.append((t, max(0.0, st), max(st + 0.05, en)))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Таймлайн
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Word:
    text: str
    start: float
    end: float
    seg: int
    joke: bool


@dataclass
class Timeline:
    title: str
    words: list[Word]          # слова для субтитров (без заголовка)
    all_words: list[Word]      # включая заголовок
    voice: np.ndarray
    speech_end: float
    duration: float
    cues: dict


def build_timeline(title: str, segs: list[Segment], cfg: dict) -> Timeline:
    t = LEAD_IN
    pieces = []
    words: list[Word] = []
    all_words: list[Word] = []
    for i, s in enumerate(segs):
        t += s.pause_before
        start_sample = int(round(t * SR))
        pieces.append((start_sample, s.audio))
        for tok, st, en in s.words:
            w = Word(tok, t + st, t + en, i, s.is_joke)
            all_words.append(w)
            if not s.is_title:
                words.append(w)
        t += len(s.audio) / SR
    speech_end = t
    dur_cfg = cfg["duration"]
    duration = max(speech_end + 0.35 + dur_cfg["outro"], dur_cfg["min"])
    n = int(math.ceil(duration * SR)) + SR
    voice = np.zeros(n, dtype=np.float32)
    for st, a in pieces:
        voice[st:st + len(a)] += a

    # ── поиск фраз-триггеров
    norm_seq = [norm_word(w.text) for w in words]

    def find(phrase: str):
        if not phrase:
            return None
        p = [norm_word(x) for x in phrase.split() if norm_word(x)]
        for i in range(len(norm_seq) - len(p) + 1):
            if all(norm_seq[i + k] == p[k] for k in range(len(p))):
                return words[i], words[i + len(p) - 1]
        log(f"⚠ фраза-триггер «{phrase}» не найдена в истории — эффект пропущен")
        return None

    cues = {}
    c = cfg["cues"]
    if (r := find(c.get("light_on", ""))):
        cues["light_on"] = r[1].start                    # на слове «свет»
    if (r := find(c.get("red_glow", ""))):
        cues["red_glow"] = r[0].start + (r[1].start - r[0].start) * 0.5
        cues["beep"] = r[1].start                        # на «красным»
    if (r := find(c.get("joke_end", ""))):
        cues["joke_end"] = r[1].end
    if (r := find(c.get("relief", ""))):
        cues["relief"] = r[0].start
    if (r := find(c.get("final", ""))):
        cues["final"] = r[1].end + 0.05
    return Timeline(title, words, all_words, voice, speech_end, duration, cues)


# ──────────────────────────────────────────────────────────────────────────────
# Звук: дрон, шорохи, писки, весёлая нота
# ──────────────────────────────────────────────────────────────────────────────
def band_noise(n: int, lo: float, hi: float, rng: np.random.Generator) -> np.ndarray:
    x = rng.standard_normal(n).astype(np.float32)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    mask = ((f >= lo) & (f <= hi)).astype(np.float32)
    # мягкие края
    mask = np.convolve(mask, np.hanning(64) / np.hanning(64).sum(), mode="same")
    y = np.fft.irfft(X * mask, n).astype(np.float32)
    return y / (np.abs(y).max() + 1e-9)


def make_drone(n: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / SR
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.09 * t)
    sig = (0.55 * np.sin(2 * np.pi * 55.0 * t)
           + 0.40 * np.sin(2 * np.pi * 55.35 * t + 1.1)
           + 0.22 * np.sin(2 * np.pi * 82.4 * t + 0.6 * np.sin(2 * np.pi * 0.05 * t))
           + 0.10 * np.sin(2 * np.pi * 110.7 * t))
    rumble = band_noise(n, 30, 160, rng) * 0.35
    out = (sig * lfo).astype(np.float32) + rumble
    fade = np.clip(t / 2.0, 0, 1).astype(np.float32)
    return out * fade


def env_ar(n: int, attack: float, release: float) -> np.ndarray:
    a = max(1, int(attack * SR))
    r = max(1, int(release * SR))
    e = np.ones(n, dtype=np.float32)
    e[:a] = np.linspace(0, 1, a)
    e[-r:] = np.minimum(e[-r:], np.linspace(1, 0, r))
    return e


def make_rustle(rng: np.random.Generator) -> np.ndarray:
    dur = rng.uniform(0.35, 0.9)
    n = int(dur * SR)
    x = band_noise(n, 900, 5000, rng)
    # «шуршание» — рваная амплитуда
    grains = np.repeat(rng.uniform(0.2, 1.0, n // 480 + 1), 480)[:n].astype(np.float32)
    k = np.hanning(1200).astype(np.float32)
    grains = np.convolve(grains, k / k.sum(), mode="same")
    return x * grains * np.hanning(n).astype(np.float32)


def tone(freq: float, dur: float, harmonics=(1.0,), decay: float = 0.0) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = sum(a * np.sin(2 * np.pi * freq * (i + 1) * t) for i, a in enumerate(harmonics))
    if decay:
        y = y * np.exp(-t / decay)
    return y.astype(np.float32)


def make_beep(pulses: int = 3, freq: float = 3150.0, length: float = 0.07, gap: float = 0.09) -> np.ndarray:
    one = tone(freq, length) * env_ar(int(length * SR), 0.004, 0.012)
    sil = np.zeros(int(gap * SR), dtype=np.float32)
    parts = []
    for i in range(pulses):
        parts += [one, sil] if i < pulses - 1 else [one]
    return np.concatenate(parts)


def pluck(freq: float, dur: float = 0.9) -> np.ndarray:
    y = tone(freq, dur, harmonics=(1.0, 0.35, 0.12, 0.05), decay=0.22)
    return y * env_ar(len(y), 0.004, 0.05)


def place(buf: np.ndarray, sig: np.ndarray, at: float, gain: float = 1.0) -> None:
    i = int(at * SR)
    if i >= len(buf) or i + len(sig) <= 0:
        return
    j = min(len(buf), i + len(sig))
    buf[max(0, i):j] += sig[max(0, -i):j - i] * gain


def build_audio(tl: Timeline, cfg: dict, seed: int) -> tuple[np.ndarray, dict]:
    rng = np.random.default_rng(seed)
    acfg = cfg["audio"]
    n = len(tl.voice)
    cues = tl.cues
    final_cut = cues.get("final", tl.speech_end + 0.05)

    # ── голос: нормализация по активной речи
    voice = tl.voice.copy()
    frame = int(0.05 * SR)
    nfr = n // frame
    fr = voice[:nfr * frame].reshape(nfr, frame)
    fr_rms = np.sqrt(np.mean(fr ** 2, axis=1))
    active = fr_rms > db2amp(-40) * (fr_rms.max() + 1e-9) * 10
    v_rms = float(np.sqrt(np.mean(fr[active] ** 2))) if active.any() else rms(voice)
    voice *= db2amp(acfg["voice_db"]) / v_rms

    # ── дрон
    light = cues.get("light_on", final_cut)
    drone = make_drone(n, rng)
    drone *= db2amp(acfg["drone_db"]) / rms(drone[int(2 * SR):int(max(light, 3) * SR)])
    li = int(light * SR)
    drone[li:] = 0.0                         # резкий обрыв на «Я включил свет»
    drone[li - 96:li] *= np.linspace(1, 0, 96, dtype=np.float32)  # без щелчка

    # ── шорохи (редкие, только в темноте)
    sfx = np.zeros(n, dtype=np.float32)
    t = rng.uniform(2.5, 4.0)
    while t < light - 1.0:
        place(sfx, make_rustle(rng), t, db2amp(acfg["drone_db"] - 4) * 2.2)
        t += rng.uniform(4.5, 8.5)

    # ── писк «светилась красным»
    if "beep" in cues:
        place(sfx, make_beep(), cues["beep"], db2amp(-27))

    # ── весёлая нота после шутки
    music = np.zeros(n, dtype=np.float32)
    if "relief" in cues:
        r0 = cues["relief"]
        for k, f in enumerate([523.25, 659.25, 783.99, 1046.5]):     # C E G C
            place(music, pluck(f, 1.2), r0 + 0.11 * k, db2amp(-25))
        # лёгкая подложка (пентатоника), тихо, до финала
        scale = [523.25, 587.33, 659.25, 783.99, 880.0]
        bt = r0 + 1.0
        step = 0.42
        k = 0
        while bt < final_cut - 0.2:
            f = scale[(k * 3 + (k // 4)) % len(scale)] / (1 if k % 4 else 2)
            place(music, pluck(f, 0.6), bt, db2amp(-34))
            bt += step
            k += 1

    # ── финальный тихий писк и резкая тишина
    bed = drone + sfx + music
    if "final" in cues:
        fc = int(final_cut * SR)
        bed[fc:] = 0.0
        place(bed, make_beep(1, 2700.0, 0.32, 0.0), final_cut, db2amp(-31))
        cut2 = int((final_cut + 0.33) * SR)
        bed[cut2:] = 0.0

    # ── гарантия: голос громче фона минимум на N dB (по 400-мс окнам)
    win = int(0.4 * SR)
    nw = n // win
    bw = np.sqrt(np.mean(bed[:nw * win].reshape(nw, win) ** 2, axis=1))
    act = bw[bw > db2amp(-60)]
    bed_level = float(np.sqrt(np.mean(act ** 2))) if len(act) else 1e-6  # средний RMS фона, где он звучит
    voice_level = db2amp(acfg["voice_db"])
    margin = amp2db(voice_level) - amp2db(bed_level)
    need = acfg["min_voice_over_music_db"] + 0.5
    if margin < need:
        bed *= db2amp(margin - need)
        margin = need

    mix = voice + bed
    # мягкий лимитер выше -2 dBFS
    knee = 0.8
    ax = np.abs(mix)
    over = ax > knee
    mix[over] = np.sign(mix[over]) * (knee + 0.17 * np.tanh((ax[over] - knee) / 0.17))
    total = int(tl.duration * SR)
    stats = {"voice_db": acfg["voice_db"], "bed_db": round(amp2db(bed_level), 1),
             "margin_db": round(margin, 1)}
    return mix[:total].astype(np.float32), stats


def write_wav(path: Path, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ──────────────────────────────────────────────────────────────────────────────
# Фон
# ──────────────────────────────────────────────────────────────────────────────
def vignette_mask(strength: float = 0.55) -> np.ndarray:
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    dx = (x - W / 2) / (W / 2)
    dy = (y - H / 2) / (H / 2)
    d = np.sqrt(dx * dx * 1.0 + dy * dy * 0.8)
    return np.clip(1 - strength * np.clip(d - 0.35, 0, None) ** 1.5, 0, 1).astype(np.float32)


class VideoBackground:
    def __init__(self, path: Path, duration: float, fps: int, dim: float):
        vf = (f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={W}:{H}:flags=lanczos,fps={fps},"
              f"colorchannelmixer=rr={1 - dim}:gg={1 - dim}:bb={1 - dim},vignette=PI/4.2,format=rgb24")
        cmd = ["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(path), "-t", f"{duration:.3f}",
               "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        self.size = W * H * 3
        self.last = np.zeros((H, W, 3), np.uint8)

    def frame(self, i: int, t: float) -> np.ndarray:
        buf = self.proc.stdout.read(self.size)
        if len(buf) == self.size:
            self.last = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        return self.last.copy()

    def close(self):
        try:
            self.proc.kill()
        except Exception:  # noqa: BLE001
            pass


class GeneratedBackground:
    """Сине-фиолетовый градиент с медленным туманом."""
    LW, LH = 120, 214  # низкое разрешение тумана

    def __init__(self, cfg: dict, seed: int):
        rng = np.random.default_rng(seed)
        top = np.array(hex2rgb(cfg["gradient_top"]), np.float32)
        bot = np.array(hex2rgb(cfg["gradient_bottom"]), np.float32)
        g = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
        base = top * (1 - g) + bot * g
        self.base = np.broadcast_to(base, (H, W, 3)).astype(np.float32)
        self.vig = vignette_mask(0.75)[..., None]
        self.fog_color = np.array(hex2rgb(cfg["fog_color"]), np.float32)

        def layer(size, blur):
            w, h = size
            noise = np.tile((rng.random((h, w)) * 255).astype(np.uint8), (3, 3))
            im = Image.fromarray(noise, "L").filter(ImageFilter.GaussianBlur(blur))
            a = np.asarray(im, np.float32)[h:2 * h, w:2 * w]  # центр 3x3 — бесшовная текстура
            a = (a - a.min()) / (a.max() - a.min() + 1e-6)
            return np.tile(a, (2, 2))  # бесшовная прокрутка
        self.l1 = layer((240, 420), 9)
        self.l2 = layer((200, 360), 6)

    def _win(self, layer, ox, oy):
        h, w = layer.shape[0] // 2, layer.shape[1] // 2
        ox, oy = int(ox) % w, int(oy) % h
        return layer[oy:oy + self.LH, ox:ox + self.LW]

    def frame(self, i: int, t: float) -> np.ndarray:
        a = self._win(self.l1, t * 4.0, t * 1.5)
        b = self._win(self.l2, 50 - t * 2.5, 30 + t * 3.2)
        fog = np.clip((a * 0.65 + b * 0.55) - 0.30, 0, 1) ** 1.2
        breathe = 0.85 + 0.15 * math.sin(t * 0.6)
        fog_im = Image.fromarray((fog * 255 * breathe).astype(np.uint8), "L").resize((W, H), Image.BILINEAR)
        f = np.asarray(fog_im, np.float32)[..., None] / 255.0
        img = self.base + f * self.fog_color * 0.85
        img *= self.vig
        return np.clip(img, 0, 255).astype(np.uint8)

    def close(self):
        pass


def pick_background(cfg: dict, duration: float, fps: int, seed: int):
    folder = ROOT / cfg["folder"] if not Path(cfg["folder"]).is_absolute() else Path(cfg["folder"])
    vids = sorted([p for p in folder.glob("*") if p.suffix.lower() in (".mp4", ".mov")]) if folder.is_dir() else []
    if vids:
        p = random.Random(seed).choice(vids)
        log(f"фон: видео {p.name}")
        return VideoBackground(p, duration, fps, cfg["dim"]), True
    log("фон: генерируется (градиент + туман) — папка bg/ пуста")
    return GeneratedBackground(cfg, seed), False


# ──────────────────────────────────────────────────────────────────────────────
# Графика: субтитры, заголовок, свечение, финальная плашка
# ──────────────────────────────────────────────────────────────────────────────
def composite(frame: np.ndarray, rgba: Image.Image, x: int, y: int, alpha: float = 1.0) -> None:
    """Накладывает RGBA-картинку на кадр (numpy) в точке x,y (левый верхний угол)."""
    ov = np.asarray(rgba)
    h, w = ov.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    o = ov[y0 - y:y1 - y, x0 - x:x1 - x]
    a = o[..., 3:4].astype(np.float32) * (alpha / 255.0)
    region = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (region * (1 - a) + o[..., :3] * a).astype(np.uint8)


def chunk_words(words: list[Word], max_words: int) -> list[list[Word]]:
    """По 3–4 слова на экране, в пределах одного предложения."""
    chunks: list[list[Word]] = []
    i = 0
    while i < len(words):
        j = i
        while j < len(words) and words[j].seg == words[i].seg:
            j += 1
        seg = words[i:j]
        n = len(seg)
        k = max(1, math.ceil(n / max_words))
        base, extra = divmod(n, k)
        p = 0
        for c in range(k):
            sz = base + (1 if c < extra else 0)
            chunks.append(seg[p:p + sz])
            p += sz
        i = j
    return chunks


class Renderer:
    def __init__(self, tl: Timeline, cfg: dict, fps: int):
        self.tl, self.cfg, self.fps = tl, cfg, fps
        sc = cfg["subtitles"]
        self.sc = sc
        self.upper = sc.get("uppercase", True)
        self.chunks = chunk_words(tl.words, sc["max_words"])
        # время показа каждого чанка
        self.chunk_times = []
        for ci, ch in enumerate(self.chunks):
            st = ch[0].start - 0.05
            if ci + 1 < len(self.chunks):
                nxt = self.chunks[ci + 1][0].start - 0.05
                en = min(nxt, ch[-1].end + 0.6)
            else:
                en = ch[-1].end + 0.6
            self.chunk_times.append((st, en))
        self.band_h = 560
        self.band_y = int(H * sc["y_position"]) - self.band_h // 2
        self.white = hex2rgb(sc["text_color"])
        self.stroke = hex2rgb(sc["stroke_color"])
        self.red = hex2rgb(sc["highlight_color"])
        self.yellow = hex2rgb(sc["joke_highlight_color"])

        gl = cfg["glow"]
        y, x = np.mgrid[0:H, 0:W].astype(np.float32)
        ex = np.exp(-np.minimum(x, W - 1 - x) / gl["width"])
        ey = np.exp(-np.minimum(y, H - 1 - y) / gl["width"])
        self.glow_mask = (1 - (1 - ex) * (1 - ey)).astype(np.float32)[..., None]  # мягкие углы
        self.glow_red = np.array(hex2rgb(gl["scary_color"]), np.float32)
        self.glow_green = np.array(hex2rgb(gl["relief_color"]), np.float32)

        self.title_img = self._render_title(tl.title)
        self.outro_img = self._render_outro()
        self.outro_start = tl.duration - cfg["duration"]["outro"]

    # ── заголовок
    def _render_title(self, title: str) -> Image.Image:
        tc = self.cfg["title"]
        size = tc["font_size"]
        text = title.upper() if self.upper else title
        while True:
            f = font(size)
            lines = self._wrap(text, f, W - 120)
            widest = max(f.getlength(l) for l in lines)
            if widest <= W - 120 or size < 50:
                break
            size -= 6
        lh = int(size * 1.15)
        img = Image.new("RGBA", (W, lh * len(lines) + 80), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        for i, l in enumerate(lines):
            dr.text((W // 2, 40 + lh * i + lh // 2), l, font=f, anchor="mm", fill=hex2rgb(tc["color"]),
                    stroke_width=max(6, size // 11), stroke_fill=hex2rgb(tc["stroke_color"]))
        return img

    @staticmethod
    def _wrap(text: str, f, maxw: int) -> list[str]:
        lines, cur = [], ""
        for w in text.split():
            cand = (cur + " " + w).strip()
            if f.getlength(cand) <= maxw or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    # ── финальная плашка
    def _render_outro(self) -> Image.Image:
        oc = self.cfg["outro"]
        f = font(oc["font_size"])
        text = oc["text"]
        lines = self._wrap(text, f, W - 260)
        lh = int(oc["font_size"] * 1.2)
        tw = int(max(f.getlength(l) for l in lines))
        pw, ph = tw + 110, lh * len(lines) + 80
        img = Image.new("RGBA", (pw + 40, ph + 40), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        dr.rounded_rectangle((24, 28, pw + 24, ph + 28), radius=40, fill=(0, 0, 0, 120))   # тень
        dr.rounded_rectangle((20, 20, pw + 20, ph + 20), radius=40, fill=hex2rgb(oc["plate_color"]) + (255,),
                             outline=(255, 255, 255, 255), width=5)
        for i, l in enumerate(lines):
            dr.text((20 + pw // 2, 20 + 40 + lh * i + lh // 2), l, font=f, anchor="mm",
                    fill=hex2rgb(oc["text_color"]))
        return img

    # ── субтитры
    def _subtitle(self, t: float) -> tuple[Image.Image, int] | None:
        ci = None
        for k, (st, en) in enumerate(self.chunk_times):
            if st <= t < en:
                ci = k
                break
        if ci is None:
            return None
        ch = self.chunks[ci]
        st, _ = self.chunk_times[ci]
        size = self.sc["font_size"]
        f = font(size)
        texts = [(w.text.upper() if self.upper else w.text).strip(".,;:") or w.text for w in ch]
        space0 = f.getlength(" ")
        widths0 = [f.getlength(x) for x in texts]
        maxw = W - 90

        def layout(k: float) -> list[list[int]]:
            res: list[list[int]] = [[]]
            cur = 0.0
            for i, wd0 in enumerate(widths0):
                wd = wd0 * k
                add = wd if not res[-1] else wd + space0 * 1.55 * k
                if res[-1] and cur + add > maxw:
                    res.append([i])
                    cur = wd
                else:
                    res[-1].append(i)
                    cur += add
            return res

        # не больше двух строк: при необходимости слегка уменьшаем шрифт
        scale_fit = min(1.0, maxw / max(widths0))
        lines = layout(scale_fit)
        while len(lines) > 2 and scale_fit > 0.62:
            scale_fit *= 0.95
            lines = layout(scale_fit)
        space, widths = space0 * 1.55, widths0  # запас под пульсацию
        lh = size * 1.18 * scale_fit
        img = Image.new("RGBA", (W, self.band_h), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        # появление чанка: лёгкий «поп»
        pop = 1.0 - 0.12 * max(0.0, 1 - (t - st) / 0.12)
        total_h = lh * len(lines)
        y0 = self.band_h / 2 - total_h / 2 + lh / 2
        sw = self.sc["stroke_width"]
        for li, line in enumerate(lines):
            lw = sum(widths[i] for i in line) + space * (len(line) - 1)
            x = W / 2 - lw * pop * scale_fit / 2
            y = y0 + li * lh
            for i in line:
                w = ch[i]
                wd = widths[i] * pop * scale_fit
                cx = x + wd / 2
                active = w.start <= t < max(w.end, w.start + 0.12) or (
                    i + 1 < len(ch) and w.start <= t < ch[i + 1].start)
                if active:
                    dt = t - w.start
                    s = 1.0 + 0.08 * math.exp(-dt / 0.12) + 0.03 * math.sin(dt * 2 * math.pi * 3.2)
                    color = self.yellow if w.joke else self.red
                else:
                    s = 1.0
                    color = self.white
                fs = size * s * pop * scale_fit
                dr.text((cx, y), texts[i], font=font(fs), anchor="mm", fill=color,
                        stroke_width=max(2, int(sw * s * scale_fit)), stroke_fill=self.stroke)
                x += wd + space * pop * scale_fit
        return img, self.band_y

    # ── кадр
    def render(self, base: np.ndarray, t: float) -> np.ndarray:
        frame = base
        cues = self.tl.cues
        final = cues.get("final", self.tl.speech_end + 0.05)
        fx = None  # аддитивные эффекты во float

        # вспышка света на «Я включил свет»
        if "light_on" in cues and 0 <= t - cues["light_on"] < 0.5:
            k = math.exp(-(t - cues["light_on"]) / 0.12) * 0.55
            fx = frame.astype(np.float32)
            fx += (255 - fx) * k

        # пульсирующее свечение по краям
        if "red_glow" in cues and cues["red_glow"] <= t < final + 0.33:
            tt = t - cues["red_glow"]
            ramp = min(1.0, tt / 0.35)
            pulse = 0.35 + 0.65 * math.sin(tt * math.pi * 1.1) ** 2
            je = cues.get("joke_end")
            if je is not None and t >= je:
                mix = min(1.0, (t - je) / 0.6)
                color = self.glow_red * (1 - mix) + self.glow_green * mix
            else:
                color = self.glow_red
            inten = 0.6 * ramp * pulse
            if fx is None:
                fx = frame.astype(np.float32)
            fx += self.glow_mask * (color * inten)

        # затемнение под финальную плашку
        if t >= self.outro_start:
            k = min(1.0, (t - self.outro_start) / 0.25) * 0.45
            if fx is None:
                fx = frame.astype(np.float32)
            fx *= (1 - k)

        if fx is not None:
            frame = np.clip(fx, 0, 255).astype(np.uint8)

        # заголовок: первые 1.5 с
        tdur = self.cfg["duration"]["title"]
        if t < tdur:
            a = 1.0 if t < tdur - 0.35 else max(0.0, (tdur - t) / 0.35)
            a *= min(1.0, t / 0.15 + 0.3)
            img = self.title_img
            composite(frame, img, 0, H // 2 - img.height // 2, a)

        # субтитры
        if t < self.outro_start:
            sub = self._subtitle(t)
            if sub:
                composite(frame, sub[0], 0, sub[1])

        # финальная плашка
        if t >= self.outro_start:
            dt = t - self.outro_start
            s = 0.6 + 0.4 * (1 - math.exp(-dt / 0.08)) + 0.06 * math.sin(min(dt, 0.5) / 0.5 * math.pi)
            s *= 1.0 + 0.02 * math.sin(dt * 2 * math.pi * 1.5)
            img = self.outro_img
            if abs(s - 1) > 0.005:
                img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.BILINEAR)
            composite(frame, img, W // 2 - img.width // 2, H // 2 - img.height // 2,
                      min(1.0, dt / 0.1))
        return frame


# ──────────────────────────────────────────────────────────────────────────────
# Сборка
# ──────────────────────────────────────────────────────────────────────────────
def render_video(tl: Timeline, cfg: dict, audio_wav: Path, out: Path, fps: int, limit: float | None,
                 seed: int) -> bool:
    duration = tl.duration if limit is None else min(limit, tl.duration)
    nframes = int(round(duration * fps))
    bg, from_video = pick_background(cfg["background"], duration + 1, fps, seed)
    rnd = Renderer(tl, cfg, fps)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
           "-i", str(audio_wav),
           "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-g", str(fps * 2),
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "2",
           "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(nframes):
            t = i / fps
            frame = rnd.render(bg.frame(i, t), t)
            enc.stdin.write(frame.tobytes())
            if i % (fps * 5) == 0:
                log(f"кадры: {t:5.1f} / {duration:.1f} с")
    finally:
        enc.stdin.close()
        enc.wait()
        bg.close()
    if enc.returncode != 0:
        sys.exit("ffmpeg завершился с ошибкой")
    return from_video


def main() -> None:
    global FONT_PATH
    ap = argparse.ArgumentParser(description="Вертикальное видео: страшная и смешная история")
    ap.add_argument("story", nargs="?", default="story.txt")
    ap.add_argument("-o", "--output", default=None, help="выходной файл (по умолчанию output.mp4)")
    ap.add_argument("--fps", type=int, default=30, choices=[24, 25, 30, 50, 60])
    ap.add_argument("--preview", type=float, default=None, metavar="SEC",
                    help="рендерить только первые SEC секунд (пробная версия)")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    need_ffmpeg()
    FONT_PATH = find_font()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out = Path(args.output or ("preview.mp4" if args.preview else "output.mp4"))
    log(f"шрифт: {Path(FONT_PATH).name}")

    title, segs = build_segments(Path(args.story), cfg)
    v = cfg["voice"]
    rate = v["rate"]
    dmax = cfg["duration"]["max"]
    for _ in range(6):
        synthesize(segs, v["name"], rate, v["pitch"])
        tl = build_timeline(title, segs, cfg)
        if tl.duration <= dmax:
            break
        r = int(rate.rstrip("%")) + 6
        log(f"длительность {tl.duration:.1f} с > {dmax} с — ускоряю речь до {r:+d}%")
        rate = f"{r:+d}%"
    log(f"речь: {tl.speech_end:.1f} с, ролик: {tl.duration:.1f} с, слов в субтитрах: {len(tl.words)}")
    log("триггеры: " + ", ".join(f"{k}={v:.2f}s" for k, v in tl.cues.items()))

    audio, stats = build_audio(tl, cfg, args.seed)
    tmp = ROOT / ".cache"
    tmp.mkdir(exist_ok=True)
    wav = tmp / "mix.wav"
    write_wav(wav, audio)
    log(f"звук: голос {stats['voice_db']} dBFS, фон {stats['bed_db']} dBFS, "
        f"запас {stats['margin_db']} dB")

    from_video = render_video(tl, cfg, wav, out, args.fps, args.preview, args.seed)
    log(f"готово: {out.resolve()}")
    if not from_video:
        print("\nПодсказка: положите свои вертикальные/горизонтальные ролики (.mp4/.mov) в папку "
              f"{(ROOT / cfg['background']['folder']).resolve()} — будет взят случайный, "
              "зациклен, обрезан до 9:16, затемнён на 35% и с виньеткой.")


if __name__ == "__main__":
    main()
