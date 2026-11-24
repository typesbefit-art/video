#!/usr/bin/env python3
"""
Генератор вертикального видео «фейковая переписка в мессенджере».

    python generate.py script.json              -> output.mp4
    python generate.py script.json -o clip.mp4  -> clip.mp4

Сюжет, имена, заголовок-крючок и финальная плашка берутся из script.json.
Голоса, цвета и тайминги по умолчанию задаются ниже (VOICES / THEME / TIMING)
и могут быть переопределены в script.json → "settings" → "voices" / "theme" / "timing".
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import wave
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ─────────────────────────────── НАСТРОЙКИ ────────────────────────────────

W, H, FPS = 1080, 1920, 60
SR = 44100  # частота дискретизации звука

# Голоса edge-tts. rate/pitch/volume интерполируются от *_start (первая реплика
# персонажа) к *_end (последняя) — так клиентка ускоряется и нервничает к концу.
VOICES = {
    "courier": {
        "voice": "ru-RU-DmitryNeural",
        "rate_start": -4, "rate_end": -6,       # %, невозмутимо и устало
        "pitch_start": -8, "pitch_end": -10,    # Hz, низко и монотонно
        "volume_start": 0, "volume_end": 0,     # %
    },
    "client": {
        "voice": "ru-RU-SvetlanaNeural",
        "rate_start": 6, "rate_end": 20,        # быстрее к концу
        "pitch_start": 6, "pitch_end": 18,      # выше = нервнее
        "volume_start": 0, "volume_end": 10,
    },
}

THEME = {
    "bg_top": "#0B0F14",
    "bg_bottom": "#121821",
    "pattern": "#1A222D",
    "header_bg": "#151B23",
    "header_line": "#222B36",
    "name": "#F2F5F8",
    "status": "#5FD39A",
    "status_typing": "#62E3B0",
    "avatar_a": "#FF9A5A",
    "avatar_b": "#E2485F",
    "courier_bubble": "#2A3038",
    "courier_text": "#EEF1F4",
    "client_bubble": "#62E3B0",
    "client_text": "#08241A",
    "time_courier": "#8D96A1",
    "time_client": "#2D6B53",
    "ticks_read": "#3BA7FF",
    "ticks_sent": "#7E8893",
    "input_bg": "#1C232C",
    "input_text": "#6F7A86",
    "send_btn": "#62E3B0",
    "typing_dot": "#A9B2BC",
    "sub_text": "#FFFFFF",
    "sub_stroke": "#000000",
    "sub_hl_courier": "#FFD54A",
    "sub_hl_client": "#62E3B0",
    "sub_hl_text": "#0A0A0A",
    "hook_text": "#FFFFFF",
    "hook_accent": "#FFD54A",
    "outro_bg": "#62E3B0",
    "outro_text": "#08241A",
}

TIMING = {
    "hook": 1.0,            # заголовок-крючок в начале, сек
    "outro": 1.5,           # финальная плашка, сек
    "typing_min": 0.55,     # «печатает…» перед сообщением
    "typing_max": 1.05,
    "typing_per_char": 0.012,
    "bubble_anim": 0.30,    # выезд пузыря
    "scroll_anim": 0.32,    # прокрутка чата
    "read_delay": 0.6,      # через сколько галочки становятся синими
    "start_clock": "21:47", # время на сообщениях
    "beat_bpm": 92,
    "beat_volume": 0.22,    # громкость фонового бита (0..1)
    "pop_volume": 0.22,
    "sfx_volume": 0.45,     # комедийные звуки (ба-дум-тсс, грустный тромбон…)
}

FONT_DIR = "/usr/share/fonts/opentype/inter"
FONTS = {
    "regular": "Inter-Regular.otf",
    "medium": "Inter-Medium.otf",
    "semibold": "Inter-SemiBold.otf",
    "bold": "Inter-Bold.otf",
    "black": "Inter-Black.otf",
}
FALLBACK_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Геометрия экрана
HEADER_H = 210
CHAT_TOP = HEADER_H
INPUT_Y = 1360          # верх строки ввода
INPUT_H = 120
CHAT_BOTTOM = INPUT_Y
SUB_CY = 1600           # центр субтитров
SIDE = 36               # отступ пузырей от краёв
BUBBLE_MAX_W = 760
BUBBLE_FONT = 44

# ─────────────────────────────── УТИЛИТЫ ──────────────────────────────────

_font_cache = {}


def font(kind, size):
    key = (kind, size)
    if key not in _font_cache:
        path = os.path.join(FONT_DIR, FONTS[kind])
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
        except OSError:
            _font_cache[key] = ImageFont.truetype(FALLBACK_FONT, size)
    return _font_cache[key]


def rgb(hex_color, alpha=None):
    h = hex_color.lstrip("#")
    c = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return c + (alpha,) if alpha is not None else c


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out_cubic(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_out_back(x, s=1.5):
    x = clamp(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def lerp(a, b, p):
    return a + (b - a) * p


def text_w(fnt, s):
    return fnt.getlength(s)


def wrap_words(words, fnt, max_w):
    lines, cur = [], []
    for w in words:
        trial = " ".join(map(str, cur + [w]))
        if cur and text_w(fnt, trial) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def with_alpha(img, a):
    if a >= 0.999:
        return img
    img = img.copy()
    alpha = img.getchannel("A").point(lambda v: int(v * a))
    img.putalpha(alpha)
    return img


def deep_update(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v


# ─────────────────────────────── ОЗВУЧКА ──────────────────────────────────

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tts_cache")


def _patch_edge_tts_ssl():
    """edge-tts использует certifi; если в системе задан свой CA (прокси) — подключаем его."""
    import edge_tts.communicate as ec
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        ec._SSL_CTX = ssl.create_default_context(cafile=ca)


async def _tts_once(text, voice, rate, pitch, volume, mp3_path):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume,
                                boundary="WordBoundary")
    words = []
    with open(mp3_path, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"text": ch["text"],
                              "start": ch["offset"] / 1e7,
                              "end": (ch["offset"] + ch["duration"]) / 1e7})
    return words


def synthesize(text, voice, rate, pitch, volume):
    """Возвращает (путь к mp3, список слов с таймингами). Результат кешируется."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.sha1(f"{voice}|{rate}|{pitch}|{volume}|{text}".encode()).hexdigest()[:16]
    mp3 = os.path.join(CACHE_DIR, key + ".mp3")
    meta = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(mp3) and os.path.exists(meta) and os.path.getsize(mp3) > 0:
        with open(meta, encoding="utf-8") as f:
            return mp3, json.load(f)
    _patch_edge_tts_ssl()
    last = None
    for attempt in range(25):
        try:
            words = asyncio.run(_tts_once(text, voice, rate, pitch, volume, mp3))
            if os.path.getsize(mp3) > 0:
                with open(meta, "w", encoding="utf-8") as f:
                    json.dump(words, f, ensure_ascii=False)
                return mp3, words
        except Exception as e:  # сервис иногда отвечает пустотой — повторяем
            last = e
        time.sleep(min(5.0, 0.7 * (attempt + 1)))
    raise RuntimeError(f"edge-tts не смог озвучить «{text}»: {last}")


def decode_audio(path):
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0


def fmt_pct(v):
    return f"{'+' if v >= 0 else ''}{int(round(v))}%"


def fmt_hz(v):
    return f"{'+' if v >= 0 else ''}{int(round(v))}Hz"


# ──────────────────────────── ВЫРАВНИВАНИЕ СЛОВ ───────────────────────────

def _norm(s):
    s = re.sub(r"[^\wёЁ]+", "", s.lower().replace("ё", "е"))
    return re.sub(r"(.)\1+", r"\1", s)


def align_words(display_words, boundaries, total_dur):
    """Сопоставляет слова субтитров с WordBoundary от edge-tts.
    Возвращает список времён начала для каждого слова субтитров."""
    n = len(display_words)
    starts = [None] * n
    j = 0
    for b in boundaries:
        bn = _norm(b["text"])
        if not bn:
            continue
        for k in range(j, min(n, j + 3)):
            if bn in _norm(display_words[k]) or _norm(display_words[k]) in bn:
                if starts[k] is None:
                    starts[k] = b["start"]
                j = k + 1 if _norm(display_words[k]).endswith(bn) else k
                break
    # заполняем пропуски пропорционально длине слов
    lens = [max(1, len(_norm(w))) for w in display_words]
    known = [i for i, s in enumerate(starts) if s is not None]
    if not known:
        acc, tot = 0, sum(lens)
        for i in range(n):
            starts[i] = total_dur * acc / tot
            acc += lens[i]
        return starts
    if starts[0] is None:
        starts[0] = 0.0
    for i in range(n):
        if starts[i] is None:
            a = i - 1
            b = next((k for k in range(i + 1, n) if starts[k] is not None), None)
            t_end = starts[b] if b is not None else total_dur * 0.95
            span = range(i, b if b is not None else n)
            seg = sum(lens[k] for k in span) + 1
            acc = lens[a] if a >= 0 else 0
            base = starts[a]
            for k in span:
                starts[k] = base + (t_end - base) * (acc / (seg + lens[a]))
                acc += lens[k]
    return starts


# ───────────────────────────────── ЗВУК ───────────────────────────────────

def make_pop(freq_from=950, freq_to=480, dur=0.07):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = np.linspace(freq_from, freq_to, n)
    phase = 2 * np.pi * np.cumsum(f) / SR
    env = np.exp(-t * 55) * np.minimum(1, t * 900)
    return (np.sin(phase) * env).astype(np.float32)


def make_beat(total, bpm):
    """Лёгкий lo-fi бит: бочка, клэп, хэты, басовая линия и мягкий пэд."""
    n = int(total * SR)
    out = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(7)
    beat = 60.0 / bpm
    step = beat / 2

    def add(sig, at):
        i = int(at * SR)
        if i >= n:
            return
        m = min(len(sig), n - i)
        out[i:i + m] += sig[:m]

    kt = np.arange(int(0.35 * SR)) / SR
    kick = np.sin(2 * np.pi * (45 * kt + 60 * (1 - np.exp(-kt * 30)) / 30)) * np.exp(-kt * 9) * 0.9
    st = np.arange(int(0.18 * SR)) / SR
    noise = rng.standard_normal(len(st)).astype(np.float32)
    snare = (noise * np.exp(-st * 22) * 0.35 + np.sin(2 * np.pi * 190 * st) * np.exp(-st * 30) * 0.25)
    ht = np.arange(int(0.04 * SR)) / SR
    hn = rng.standard_normal(len(ht)).astype(np.float32)
    hn = np.diff(hn, prepend=0)  # грубый ВЧ-фильтр
    hat = hn * np.exp(-ht * 120) * 0.12

    # Am - F - C - G
    roots = [110.0, 87.31, 130.81, 98.0]
    chords = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63],
              [196.0, 261.63, 329.63], [196.0, 246.94, 293.66]]
    bar = beat * 4
    t_bar = np.arange(int(bar * SR)) / SR
    bar_idx = 0
    t0 = 0.0
    while t0 < total:
        c = bar_idx % 4
        # пэд
        pad = sum(np.sin(2 * np.pi * f * t_bar) for f in chords[c]) / 3
        pad *= np.minimum(1, t_bar * 3) * np.minimum(1, (bar - t_bar) * 3) * 0.10
        add(pad.astype(np.float32), t0)
        # бас
        for k, off in enumerate([0, 1.5, 2.5]):
            bt = np.arange(int(beat * 0.9 * SR)) / SR
            bass = np.sin(2 * np.pi * roots[c] * bt) * np.exp(-bt * 3) * 0.35
            add(bass.astype(np.float32), t0 + off * beat)
        # ударные
        for s in range(8):
            tt = t0 + s * step + (0.018 if s % 2 else 0)  # лёгкий свинг
            if s in (0, 5):
                add(kick.astype(np.float32), tt)
            if s in (2, 6):
                add(snare.astype(np.float32), tt)
            add(hat * (1.0 if s % 2 == 0 else 0.6), tt)
        t0 += bar
        bar_idx += 1
    out /= max(1e-6, np.abs(out).max())
    return out


def build_audio(tl, path):
    total = tl["total"]
    n = int(total * SR) + SR
    voice = np.zeros(n, dtype=np.float32)
    fx = np.zeros(n, dtype=np.float32)

    def add(buf, sig, at, gain=1.0):
        i = int(at * SR)
        m = min(len(sig), n - i)
        if m > 0:
            buf[i:i + m] += sig[:m] * gain

    for m in tl["messages"]:
        sig = m["audio"]
        peak = max(1e-6, np.abs(sig).max())
        add(voice, sig / peak * 0.85, m["show"])
        pop = make_pop(1050, 560) if m["who"] == "client" else make_pop(820, 430)
        add(fx, pop, m["show"], TIMING["pop_volume"])
        if m.get("sfx"):
            sfx = m["sfx"] if isinstance(m["sfx"], dict) else {"name": m["sfx"]}
            at = {"before": m["typing_start"], "start": m["show"]}.get(sfx.get("at", "end"), m["voice_end"])
            add(fx, make_sfx(sfx["name"]), at + sfx.get("offset", 0.0), TIMING["sfx_volume"] * sfx.get("volume", 1.0))
    add(fx, make_pop(1300, 700, 0.09), tl["outro_start"], TIMING["pop_volume"] * 1.2)

    beat = make_beat(n / SR, TIMING["beat_bpm"])[:n] * TIMING["beat_volume"]
    # «ducking»: бит тише, когда звучит голос
    env = np.abs(voice)
    win = int(0.15 * SR)
    env = np.convolve(env, np.ones(win) / win, mode="same")
    duck = 1.0 - 0.45 * np.clip(env / 0.05, 0, 1)
    beat *= duck
    fade_in = np.minimum(1, np.arange(n) / (0.4 * SR))
    fade_out = np.clip((total - np.arange(n) / SR) / 0.8, 0, 1)
    beat *= fade_in * fade_out

    mix = voice + fx + beat
    mix = mix[:int(total * SR)]
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)  # мягкий лимитер
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(stereo.tobytes())



# ─────────────────────── СМЕШНАЯ ИНТОНАЦИЯ И ЭФФЕКТЫ ──────────────────────

def time_warp(x, rate):
    """Плёночное изменение скорости: rate[i] — скорость чтения исходника в i-м
    выходном сэмпле (>1 — быстрее и выше, <1 — медленнее и ниже).
    Возвращает (новый сигнал, функцию пересчёта времени исходник→результат)."""
    pos = np.concatenate([[0.0], np.cumsum(rate)[:-1]])
    pos = pos[pos < len(x) - 1]
    y = np.interp(pos, np.arange(len(x)), x).astype(np.float32)
    out_t = np.arange(len(pos)) / SR
    src_t = pos / SR
    return y, (lambda t: float(np.interp(t, src_t, out_t)))


def voice_fx(x, name, amount=1.0):
    """wobble — дрожащий от паники голос; melt — голос «тает» и сползает вниз;
    chipmunk — ускорение и писк; slowmo — замедление и бас."""
    n_max = int(len(x) * 2) + SR
    t = np.arange(n_max) / SR
    if name == "wobble":
        rate = 1 + 0.07 * amount * np.sin(2 * np.pi * 7.5 * t)
    elif name == "melt":
        dur = len(x) / SR
        k = np.clip(t / max(0.1, dur), 0, 1)
        rate = 1 - 0.38 * amount * k ** 1.6
        rate = np.maximum(rate, 0.5)
    elif name == "chipmunk":
        rate = np.full(n_max, 1 + 0.18 * amount)
    elif name == "slowmo":
        rate = np.full(n_max, 1 - 0.2 * amount)
    else:
        raise ValueError(f"Неизвестный эффект голоса: {name}")
    return time_warp(x, rate)


def _tone(freqs, dur, wave="saw", vib=0.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = np.interp(t, np.linspace(0, dur, len(freqs)), freqs) * (1 + vib * np.sin(2 * np.pi * 5.5 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    if wave == "saw":
        sig = sum(np.sin(k * ph) / k for k in range(1, 9))
    else:
        sig = np.sin(ph)
    return sig.astype(np.float32)


def make_sfx(name):
    rng = np.random.default_rng(3)
    if name == "rimshot":  # ба-дум-тсс
        out = np.zeros(int(SR * 1.3), np.float32)
        for at, f in [(0.0, 190), (0.17, 140)]:
            d = _tone([f * 1.3, f], 0.25, "sine") * np.exp(-np.arange(int(SR * .25)) / SR * 14)
            i = int(at * SR); out[i:i + len(d)] += d * 0.8
        n = int(SR * 0.9)
        cym = np.diff(rng.standard_normal(n + 1)).astype(np.float32) * np.exp(-np.arange(n) / SR * 4)
        i = int(0.36 * SR); out[i:i + n] += cym * 0.25
        return out
    if name == "sad_trombone":  # вау-вау-вау-ваааа
        notes = [(311, 0.32), (294, 0.32), (277, 0.32), (262, 1.1)]
        parts = []
        for k, (f, d) in enumerate(notes):
            tone = _tone([f, f * 0.98], d, "saw", vib=0.03 if k == 3 else 0.0)
            env = np.minimum(1, np.arange(len(tone)) / (0.04 * SR)) * np.minimum(1, (len(tone) - np.arange(len(tone))) / (0.08 * SR))
            parts.append(tone * env)
        sig = np.concatenate(parts)
        sig = np.convolve(sig, np.ones(6) / 6, mode="same")  # чуть приглушить
        return (sig / np.abs(sig).max() * 0.6).astype(np.float32)
    if name == "boing":
        d = 0.6
        t = np.arange(int(SR * d)) / SR
        sig = _tone([180, 520, 300], d, "sine", vib=0.25) * np.exp(-t * 4)
        return sig * 0.7
    if name == "record_scratch":
        d = 0.45
        t = np.arange(int(SR * d)) / SR
        noise = rng.standard_normal(len(t)).astype(np.float32)
        f = np.interp(t, [0, 0.15, 0.3, d], [300, 1800, 400, 1500])
        carrier = np.sin(2 * np.pi * np.cumsum(f) / SR)
        sig = noise * carrier * np.minimum(1, (d - t) * 10) * 0.35
        return np.convolve(sig, np.ones(3) / 3, mode="same").astype(np.float32)
    if name == "crickets":  # неловкая тишина
        out = np.zeros(int(SR * 1.6), np.float32)
        for k in range(6):
            at = 0.05 + k * 0.26 + (0.04 if k % 2 else 0)
            ch = _tone([4300], 0.09, "sine") * (np.sin(np.pi * np.arange(int(SR * .09)) / (SR * .09)) ** 2)
            ch *= (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 45 * np.arange(len(ch)) / SR)))
            i = int(at * SR); out[i:i + len(ch)] += ch * 0.25
        return out
    if name == "applause":
        n = int(SR * 2.2)
        out = np.zeros(n, np.float32)
        for _ in range(260):
            at = rng.uniform(0, 1.9)
            c = rng.standard_normal(int(SR * 0.012)).astype(np.float32) * np.exp(-np.arange(int(SR * .012)) / SR * 300)
            i = int(at * SR); out[i:i + len(c)] += c * rng.uniform(0.1, 0.3)
        env = np.minimum(1, np.arange(n) / (0.2 * SR)) * np.clip((n - np.arange(n)) / (0.8 * SR), 0, 1)
        out = np.diff(np.concatenate([[0], out])) * env
        return (out / np.abs(out).max() * 0.5).astype(np.float32)
    raise ValueError(f"Неизвестный звук: {name}")


def trim_silence(x, thr=0.012, keep=0.03):
    nz = np.nonzero(np.abs(x) > thr)[0]
    if not len(nz):
        return x, 0.0
    a = max(0, nz[0] - int(keep * SR))
    b = min(len(x), nz[-1] + int(keep * SR * 2))
    return x[a:b], a / SR


def speak(m, voice, rate, pitch, vol):
    """Озвучивает реплику. Если в реплике есть "say" — по сегментам, у каждого
    своя интонация (смещение rate/pitch/volume), пауза и эффект."""
    segs = m.get("say") or [{"text": m["text"]}]
    pieces, bounds, t_cur = [], [], 0.0
    for seg in segs:
        if isinstance(seg, str):
            seg = {"text": seg}
        if seg.get("text"):
            mp3, bb = synthesize(seg["text"], seg.get("voice", voice),
                                 fmt_pct(rate + seg.get("rate", 0)),
                                 fmt_hz(pitch + seg.get("pitch", 0)),
                                 fmt_pct(vol + seg.get("volume", 0)))
            a, lead = trim_silence(decode_audio(mp3))
            remap = lambda tt: tt
            if seg.get("fx"):
                a, remap = voice_fx(a, seg["fx"], seg.get("fx_amount", 1.0))
            a = a * (10 ** (seg.get("gain_db", 0) / 20))
            for b in bb:
                bounds.append({"text": b["text"], "start": t_cur + remap(max(0, b["start"] - lead)),
                               "end": t_cur + remap(max(0, b["end"] - lead))})
            pieces.append(a)
            t_cur += len(a) / SR
        gap = seg.get("gap", 0.0)
        if gap:
            pieces.append(np.zeros(int(gap * SR), np.float32))
            t_cur += gap
    return np.concatenate(pieces), bounds

# ─────────────────────────────── ТАЙМЛАЙН ─────────────────────────────────

def build_timeline(script):
    settings = script["settings"]
    msgs = script["messages"]
    counts = {"courier": 0, "client": 0}
    totals = {w: sum(1 for m in msgs if m["who"] == w) for w in counts}

    out = []
    print(f"Озвучка {len(msgs)} реплик…")
    for i, m in enumerate(msgs):
        who = m["who"]
        if who not in VOICES:
            raise ValueError(f"Реплика {i + 1}: who должно быть courier или client, а не {who!r}")
        v = VOICES[who]
        p = counts[who] / max(1, totals[who] - 1)
        counts[who] += 1
        rate = m.get("rate", lerp(v["rate_start"], v["rate_end"], p))
        pitch = m.get("pitch", lerp(v["pitch_start"], v["pitch_end"], p))
        vol = m.get("volume", lerp(v["volume_start"], v["volume_end"], p))
        audio, bounds = speak(m, m.get("voice", v["voice"]), rate, pitch, vol)
        dur = len(audio) / SR
        words = m["text"].split()
        starts = align_words(words, bounds, dur)
        typing = clamp(TIMING["typing_min"] + TIMING["typing_per_char"] * len(m["text"]),
                       TIMING["typing_min"], TIMING["typing_max"])
        out.append({"who": who, "text": m["text"], "audio": audio, "dur": dur,
                    "words": words, "word_starts": starts, "typing": typing,
                    "pause": float(m.get("pause_after", 0.3)), "sfx": m.get("sfx")})
        print(f"  {i + 1:2d}. {who:7s} {dur:4.1f}s  rate {fmt_pct(rate)} pitch {fmt_hz(pitch)}  {m['text']}")

    def total_len():
        return TIMING["hook"] + sum(m["typing"] + m["dur"] + m["pause"] for m in out) + TIMING["outro"]

    lo, hi = settings.get("min_duration", 45), settings.get("max_duration", 60)
    T = total_len()
    if T < lo:  # растягиваем паузы, чтобы попасть в минимум
        extra = lo - T + 0.3
        for m in out:
            m["pause"] += extra * 0.6 / len(out)
            m["typing"] += extra * 0.4 / len(out)
    elif T > hi:  # поджимаем паузы и «печатает»
        over = T - hi + 0.3
        slack = sum((m["pause"] - 0.12) + (m["typing"] - 0.4) for m in out)
        k = clamp(over / slack) if slack > 0 else 0
        for m in out:
            m["pause"] -= (m["pause"] - 0.12) * k
            m["typing"] -= (m["typing"] - 0.4) * k
    T2 = total_len()
    if not (lo <= T2 <= hi):
        print(f"ВНИМАНИЕ: длительность {T2:.1f}s вне диапазона {lo}–{hi}s — "
              f"сократите/дополните сценарий.")

    t = TIMING["hook"]
    hh, mm = map(int, TIMING["start_clock"].split(":"))
    for i, m in enumerate(out):
        m["typing_start"] = t
        m["show"] = t + m["typing"]
        m["voice_end"] = m["show"] + m["dur"]
        t = m["voice_end"] + m["pause"]
        minute = mm + i // 3
        m["clock"] = f"{(hh + minute // 60) % 24:02d}:{minute % 60:02d}"
        m["word_abs"] = [m["show"] + s for s in m["word_starts"]]
    return {"messages": out, "outro_start": t, "total": t + TIMING["outro"], "settings": settings}


# ─────────────────────────────── ОТРИСОВКА ────────────────────────────────

SS = 2  # суперсэмплинг для сглаженных фигур


def draw_ticks(d, x, y, color, double=True, scale=1.0):
    """Рисует галочки (одну или две), x,y — левый верх."""
    s = scale
    lw = max(2, int(4 * s))
    pts1 = [(x, y + 12 * s), (x + 7 * s, y + 19 * s), (x + 20 * s, y + 3 * s)]
    d.line(pts1, fill=color, width=lw, joint="curve")
    if double:
        pts2 = [(x + 11 * s, y + 17 * s), (x + 13 * s, y + 19 * s), (x + 26 * s, y + 3 * s)]
        d.line(pts2, fill=color, width=lw, joint="curve")


class Renderer:
    def __init__(self, tl):
        self.tl = tl
        self.msgs = tl["messages"]
        self.settings = tl["settings"]
        self._sub_cache = {}
        self._build_static()
        self._build_bubbles()
        self._build_overlays()

    # --- статичные слои ---
    def _build_static(self):
        bg = Image.new("RGB", (W, H))
        top, bot = np.array(rgb(THEME["bg_top"]), float), np.array(rgb(THEME["bg_bottom"]), float)
        grad = np.linspace(0, 1, H)[:, None]
        arr = (top * (1 - grad) + bot * grad)[:, None, :].repeat(W, axis=1)
        bg = Image.fromarray(arr.astype(np.uint8))
        d = ImageDraw.Draw(bg)
        pc = rgb(THEME["pattern"])
        for yy in range(CHAT_TOP + 30, CHAT_BOTTOM, 64):
            for xx in range(24 + (yy // 64 % 2) * 32, W, 64):
                d.ellipse([xx - 2, yy - 2, xx + 2, yy + 2], fill=pc)
        self.chat_bg = bg.crop((0, CHAT_TOP, W, CHAT_BOTTOM))

        # нижняя зона (строка ввода + субтитры)
        d.rectangle([0, INPUT_Y, W, H], fill=rgb(THEME["bg_top"]))
        big = Image.new("RGBA", (W * SS, INPUT_H * SS), (0, 0, 0, 0))
        bd = ImageDraw.Draw(big)
        pill = [SIDE * SS, 22 * SS, (W - SIDE - 110) * SS, (INPUT_H - 22) * SS]
        bd.rounded_rectangle(pill, radius=38 * SS, fill=rgb(THEME["input_bg"]))
        cx, cy, r = (W - SIDE - 44) * SS, (INPUT_H // 2) * SS, 40 * SS
        bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgb(THEME["send_btn"]))
        a = 15 * SS
        bd.polygon([(cx - a + 4 * SS, cy - a), (cx + a + 2 * SS, cy), (cx - a + 4 * SS, cy + a),
                    (cx - a + 9 * SS, cy)], fill=rgb(THEME["client_text"]))
        inp = big.resize((W, INPUT_H), Image.LANCZOS)
        ImageDraw.Draw(inp).text((SIDE + 36, INPUT_H // 2), "Сообщение", font=font("regular", 38),
                                 fill=rgb(THEME["input_text"]), anchor="lm")
        bg.paste(inp, (0, INPUT_Y), inp)
        self.base = bg

        # шапка: два варианта статуса
        self.headers = {}
        name = self.settings.get("contact_name", "Курьер")
        status = self.settings.get("contact_status", "онлайн")
        for key, st, col in [("online", status, THEME["status"]),
                             ("typing0", "печатает", THEME["status_typing"]),
                             ("typing1", "печатает.", THEME["status_typing"]),
                             ("typing2", "печатает..", THEME["status_typing"]),
                             ("typing3", "печатает...", THEME["status_typing"])]:
            self.headers[key] = self._make_header(name, st, col)

    def _make_header(self, name, status, status_col):
        hb = Image.new("RGBA", (W * SS, HEADER_H * SS), rgb(THEME["header_bg"], 255))
        d = ImageDraw.Draw(hb)
        d.line([(0, HEADER_H * SS - 2), (W * SS, HEADER_H * SS - 2)], fill=rgb(THEME["header_line"]), width=3)
        cy = (HEADER_H // 2 + 28) * SS
        # стрелка назад
        d.line([(62 * SS, cy - 22 * SS), (40 * SS, cy), (62 * SS, cy + 22 * SS)],
               fill=rgb(THEME["name"]), width=6 * SS, joint="curve")
        # аватар с градиентом
        r = 56
        ax = 100
        av = Image.new("RGBA", (2 * r * SS, 2 * r * SS))
        g = np.linspace(0, 1, 2 * r * SS)[:, None, None]
        ca, cb = np.array(rgb(THEME["avatar_a"]), float), np.array(rgb(THEME["avatar_b"]), float)
        grad = (ca * (1 - g) + cb * g).repeat(2 * r * SS, axis=1)
        av = Image.fromarray(np.dstack([grad, np.full(grad.shape[:2] + (1,), 255)]).astype(np.uint8), "RGBA")
        mask = Image.new("L", av.size, 0)
        ImageDraw.Draw(mask).ellipse([0, 0, av.size[0] - 1, av.size[1] - 1], fill=255)
        hb.paste(av, (ax * SS, cy - r * SS), mask)
        d.text(((ax + r) * SS, cy), name[:1].upper(), font=font("bold", 58 * SS),
               fill=(255, 255, 255), anchor="mm")
        # онлайн-точка
        ox, oy = (ax + 2 * r - 14) * SS, cy + (r - 14) * SS
        d.ellipse([ox - 15 * SS, oy - 15 * SS, ox + 15 * SS, oy + 15 * SS], fill=rgb(THEME["header_bg"]))
        d.ellipse([ox - 10 * SS, oy - 10 * SS, ox + 10 * SS, oy + 10 * SS], fill=rgb(THEME["status"]))
        # имя и статус
        tx = (ax + 2 * r + 28) * SS
        d.text((tx, cy - 6 * SS), name, font=font("bold", 46 * SS), fill=rgb(THEME["name"]), anchor="ls")
        d.text((tx, cy + 44 * SS), status, font=font("medium", 34 * SS), fill=rgb(status_col), anchor="ls")
        # три точки меню
        for k in range(3):
            yy = cy - 22 * SS + k * 22 * SS
            d.ellipse([(W - 52) * SS - 6 * SS, yy - 6 * SS, (W - 52) * SS + 6 * SS, yy + 6 * SS],
                      fill=rgb(THEME["name"]))
        return hb.resize((W, HEADER_H), Image.LANCZOS).convert("RGB")

    # --- пузыри ---
    def _bubble(self, m, read_state):
        """read_state: None (курьер), 'sent' или 'read' (клиентка)."""
        mine = m["who"] == "client"
        fnt = font("medium", BUBBLE_FONT)
        pad_x, pad_y = 34, 24
        lines = wrap_words(m["words"], fnt, BUBBLE_MAX_W - 2 * pad_x)
        line_h = int(BUBBLE_FONT * 1.28)
        clock_f = font("medium", 27)
        widths = [text_w(fnt, " ".join(l)) for l in lines]
        clock_w = text_w(clock_f, m["clock"])
        last_w = widths[-1] + 22 + clock_w
        inner_w = max(max(widths), last_w if last_w <= BUBBLE_MAX_W - 2 * pad_x else 0)
        extra_line = last_w > BUBBLE_MAX_W - 2 * pad_x
        bw = int(inner_w + 2 * pad_x)
        bh = int(len(lines) * line_h + 2 * pad_y + (30 if extra_line else 0))
        ticks_h = 46 if mine else 0
        img = Image.new("RGBA", (bw * SS, (bh + ticks_h) * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        col = rgb(THEME["client_bubble" if mine else "courier_bubble"])
        R = 38 * SS
        d.rounded_rectangle([0, 0, bw * SS - 1, bh * SS - 1], radius=R, fill=col)
        # «хвостик»: нижний угол со стороны отправителя почти острый
        cs = R
        if mine:
            d.rectangle([bw * SS - cs, bh * SS - cs, bw * SS - 1, bh * SS - 1], fill=col)
            d.rounded_rectangle([bw * SS - cs, bh * SS - cs, bw * SS - 1, bh * SS - 1], radius=8 * SS, fill=col)
        else:
            d.rectangle([0, bh * SS - cs, cs, bh * SS - 1], fill=col)
        tc = rgb(THEME["client_text" if mine else "courier_text"])
        for i, l in enumerate(lines):
            d.text((pad_x * SS, (pad_y + i * line_h + line_h * 0.78) * SS), " ".join(l),
                   font=font("medium", BUBBLE_FONT * SS), fill=tc, anchor="ls")
        d.text(((bw - pad_x + 8) * SS, (bh - 16) * SS), m["clock"], font=font("medium", 27 * SS),
               fill=rgb(THEME["time_client" if mine else "time_courier"]), anchor="rs")
        if mine:
            tcol = rgb(THEME["ticks_read"] if read_state == "read" else THEME["ticks_sent"])
            label = "Прочитано" if read_state == "read" else "Отправлено"
            lf = font("semibold", 28 * SS)
            lw = lf.getlength(label)
            tx = bw * SS - 44 * SS
            draw_ticks(d, tx, (bh + 12) * SS, tcol, double=(read_state == "read"), scale=SS * 1.45)
            d.text((tx - 12 * SS, (bh + 38) * SS), label, font=lf, fill=tcol, anchor="rs")
        return img.resize((bw, bh + ticks_h), Image.LANCZOS)

    def _build_bubbles(self):
        y = 34
        prev = None
        for i, m in enumerate(self.msgs):
            if m["who"] == "client":
                m["img_sent"] = self._bubble(m, "sent")
                m["img"] = self._bubble(m, "read")
            else:
                m["img"] = self._bubble(m, None)
            gap = 0 if prev is None else (16 if prev == m["who"] else 34)
            y += gap
            m["y"] = y
            m["h"] = m["img"].size[1]
            y += m["h"]
            prev = m["who"]
        # пузырь «печатает»
        tw, th = 150, 92
        self.typing_size = (tw, th)
        imgs = {}
        for who in ("courier", "client"):
            big = Image.new("RGBA", (tw * SS, th * SS), (0, 0, 0, 0))
            d = ImageDraw.Draw(big)
            col = rgb(THEME["client_bubble" if who == "client" else "courier_bubble"])
            d.rounded_rectangle([0, 0, tw * SS - 1, th * SS - 1], radius=40 * SS, fill=col)
            imgs[who] = big.resize((tw, th), Image.LANCZOS)
        self.typing_bg = imgs
        dot_big = Image.new("RGBA", (36, 36), (0, 0, 0, 0))
        ImageDraw.Draw(dot_big).ellipse([0, 0, 35, 35], fill=(255, 255, 255, 255))
        self.dot = dot_big.resize((18, 18), Image.LANCZOS)

        # прокрутка: ключевые кадры (время, целевое смещение)
        chat_h = CHAT_BOTTOM - CHAT_TOP
        bottom_pad = 34
        kfs = [(0.0, 0.0)]
        for m in self.msgs:
            kfs.append((m["typing_start"], max(0, m["y"] + th + bottom_pad - chat_h)))
            kfs.append((m["show"], max(0, m["y"] + m["h"] + bottom_pad - chat_h)))
        self.kfs = kfs
        starts = [0.0]
        for k in range(1, len(kfs)):
            starts.append(self._scroll_eval(k - 1, starts[k - 1], kfs[k][0]))
        self.kf_start_vals = starts

    def _scroll_eval(self, k, start_val, t):
        t0, target = self.kfs[k]
        p = ease_out_cubic((t - t0) / TIMING["scroll_anim"])
        return lerp(start_val, target, p)

    def scroll_at(self, t):
        k = 0
        for i, (tt, _) in enumerate(self.kfs):
            if tt <= t:
                k = i
        return self._scroll_eval(k, self.kf_start_vals[k], t)

    # --- оверлеи ---
    def _build_overlays(self):
        # крючок
        hook = self.settings.get("hook", "")
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        f = font("black", 92)
        lines = wrap_words(hook.split(), f, W - 140)
        lh = 112
        y0 = H * 0.40 - len(lines) * lh / 2
        accent_from = None
        if "," in hook:  # вторая половина фразы — акцентным цветом
            first = hook.split(",")[0].split()
            accent_from = len(first)
        wi = 0
        for li, l in enumerate(lines):
            lw = text_w(f, " ".join(l))
            x = (W - lw) / 2
            for w in l:
                col = THEME["hook_accent"] if accent_from is not None and wi >= accent_from else THEME["hook_text"]
                d.text((x, y0 + li * lh + 84), w, font=f, fill=rgb(col), anchor="ls",
                       stroke_width=6, stroke_fill=(0, 0, 0))
                x += text_w(f, w + " ")
                wi += 1
        self.hook_img = img

        # финальная плашка
        t1 = self.settings.get("outro_title", "Подписывайся на")
        t2 = self.settings.get("outro_channel", "«Прочитано и проигнорировано»")
        f1, f2 = font("bold", 50), font("black", 60)
        l2 = wrap_words(t2.split(), f2, W - 260)
        pw = int(max(text_w(f1, t1), *[text_w(f2, " ".join(l)) for l in l2]) + 120)
        ph = int(70 + 70 + len(l2) * 74 + 30 + 76 + 60)
        big = Image.new("RGBA", (pw * SS, ph * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        d.rounded_rectangle([0, 0, pw * SS - 1, ph * SS - 1], radius=48 * SS, fill=rgb(THEME["outro_bg"]))
        tc = rgb(THEME["outro_text"])
        d.text((pw * SS / 2, 70 * SS), t1, font=font("bold", 50 * SS), fill=tc, anchor="mt")
        for i, l in enumerate(l2):
            d.text((pw * SS / 2, (70 + 70 + i * 74) * SS), " ".join(l), font=font("black", 60 * SS),
                   fill=tc, anchor="mt")
        # кнопка
        by = (70 + 70 + len(l2) * 74 + 30) * SS
        bw2 = 360 * SS
        d.rounded_rectangle([pw * SS / 2 - bw2 / 2, by, pw * SS / 2 + bw2 / 2, by + 76 * SS],
                            radius=38 * SS, fill=tc)
        d.text((pw * SS / 2, by + 38 * SS), "ПОДПИСАТЬСЯ", font=font("black", 38 * SS),
               fill=rgb(THEME["outro_bg"]), anchor="mm")
        self.outro_img = big.resize((pw, ph), Image.LANCZOS)

    # --- субтитры ---
    def _sub_chunks(self, m):
        if "chunks" in m:
            return m["chunks"]
        f = font("black", 76)
        lines = wrap_words(list(range(len(m["words"]))), _IdxFont(f, m["words"]), W - 140)
        chunks = [sum(lines[i:i + 2], []) for i in range(0, len(lines), 2)]
        m["chunks"] = chunks
        return chunks

    def _subtitle(self, mi, ci, wi):
        key = (mi, ci, wi)
        if key in self._sub_cache:
            return self._sub_cache[key]
        m = self.msgs[mi]
        idxs = self._sub_chunks(m)[ci]
        f = font("black", 76)
        lines = wrap_words(idxs, _IdxFont(f, m["words"]), W - 140)
        lh = 100
        img = Image.new("RGBA", (W, lh * len(lines) + 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        hl = rgb(THEME["sub_hl_client" if m["who"] == "client" else "sub_hl_courier"])
        space = text_w(f, " ")
        for li, l in enumerate(lines):
            ws = [m["words"][k].upper() for k in l]
            total = sum(text_w(f, w) for w in ws) + space * (len(ws) - 1)
            x = (W - total) / 2
            y = 20 + li * lh
            for k, w in zip(l, ws):
                ww = text_w(f, w)
                if k == wi:
                    d.rounded_rectangle([x - 14, y - 4, x + ww + 14, y + 90], radius=18, fill=hl)
                    d.text((x, y + 43), w, font=f, fill=rgb(THEME["sub_hl_text"]), anchor="lm")
                else:
                    d.text((x, y + 43), w, font=f, fill=rgb(THEME["sub_text"]), anchor="lm",
                           stroke_width=6, stroke_fill=rgb(THEME["sub_stroke"]))
                x += ww + space
        self._sub_cache[key] = img
        return img

    # --- кадр ---
    def frame(self, t):
        frame = self.base.copy()
        chat = self.chat_bg.copy()
        scroll = self.scroll_at(t)
        th = self.typing_size[1]

        typing_who = None
        for i, m in enumerate(self.msgs):
            if m["typing_start"] <= t < m["show"]:
                typing_who = m["who"]
                p = ease_out_cubic((t - m["typing_start"]) / 0.18)
                bg = with_alpha(self.typing_bg[m["who"]], p)
                tw = self.typing_size[0]
                x = SIDE if m["who"] == "courier" else W - SIDE - tw
                y = int(m["y"] - scroll + (1 - p) * 20)
                chat.paste(bg, (x, y), bg)
                dot_col = THEME["typing_dot"] if m["who"] == "courier" else THEME["client_text"]
                dot = Image.new("RGBA", self.dot.size, rgb(dot_col, 255))
                dot.putalpha(self.dot.getchannel("A"))
                for k in range(3):
                    ph = (t - m["typing_start"]) * 2 * math.pi * 1.9 - k * 0.9
                    bounce = max(0, math.sin(ph))
                    a = 0.45 + 0.55 * bounce
                    dd = with_alpha(dot, a * p)
                    chat.paste(dd, (x + 39 + k * 30, int(y + th / 2 - 9 - bounce * 9)), dd)
            if t >= m["show"]:
                img = m["img"]
                if m["who"] == "client" and t < m["show"] + TIMING["read_delay"]:
                    img = m["img_sent"]
                p = (t - m["show"]) / TIMING["bubble_anim"]
                bw = img.size[0]
                x = SIDE if m["who"] == "courier" else W - SIDE - bw
                y = m["y"] - scroll
                if p < 1:
                    e = ease_out_cubic(p)
                    x += int((1 - e) * (-70 if m["who"] == "courier" else 70))
                    y += int((1 - e) * 36)
                    img = with_alpha(img, clamp(p * 1.6))
                if y + img.size[1] < 0 or y > chat.size[1]:
                    continue
                chat.paste(img, (int(x), int(y)), img)
        frame.paste(chat, (0, CHAT_TOP))

        # шапка
        if typing_who == "courier":
            hk = f"typing{int(t * 3) % 4}"
        else:
            hk = "online"
        frame.paste(self.headers[hk], (0, 0))

        # субтитры
        for mi, m in enumerate(self.msgs):
            if m["show"] <= t < m["voice_end"] + 0.25:
                wi = 0
                for k, s in enumerate(m["word_abs"]):
                    if s <= t:
                        wi = k
                chunks = self._sub_chunks(m)
                ci = next(c for c, ch in enumerate(chunks) if wi in ch)
                sub = self._subtitle(mi, ci, wi)
                pin = clamp((t - m["show"]) / 0.12)
                if pin < 1:
                    sub = with_alpha(sub, pin)
                frame.paste(sub, (0, int(SUB_CY - sub.size[1] / 2)), sub)
                break

        # крючок
        hd = TIMING["hook"]
        if t < hd:
            dim_a = 0.72 if t < hd - 0.18 else 0.72 * (hd - t) / 0.18
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * dim_a)))
            frame.paste(overlay, (0, 0), overlay)
            s = lerp(0.86, 1.0, ease_out_back(t / 0.22))
            a = 1.0 if t < hd - 0.15 else (hd - t) / 0.15
            img = self.hook_img
            if s < 0.999:
                img = img.resize((int(W * s), int(H * s)), Image.BILINEAR)
            img = with_alpha(img, a)
            frame.paste(img, ((W - img.size[0]) // 2, int(H * 0.40 - img.size[1] * 0.40)), img)

        # финал
        os_ = self.tl["outro_start"]
        if t >= os_:
            p = (t - os_) / 0.35
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, int(160 * clamp(p))))
            frame.paste(overlay, (0, 0), overlay)
            img = self.outro_img
            e = ease_out_back(p, 1.2)
            y = int(lerp(H + 50, H * 0.42 - img.size[1] / 2, e))
            img = with_alpha(img, clamp(p * 2))
            frame.paste(img, ((W - img.size[0]) // 2, y), img)

        return frame.tobytes()


class _IdxFont:
    """Позволяет переносить строки по индексам слов (для субтитров)."""

    def __init__(self, f, words):
        self.f, self.words = f, words

    def getlength(self, s):
        return self.f.getlength(" ".join(self.words[int(k)].upper() for k in s.split()))


# ───────────────────────────── ПАРАЛЛЕЛЬНЫЙ РЕНДЕР ────────────────────────

_R = None


def _init_worker(tl):
    global _R
    _R = Renderer(tl)


def _render(i):
    return _R.frame(i / FPS)


def main():
    ap = argparse.ArgumentParser(description="Фейковая переписка → вертикальное видео")
    ap.add_argument("script", help="путь к script.json")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--preview", type=float, default=None,
                    help="сохранить один кадр на этой секунде в preview.png и выйти")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("Нужен ffmpeg: https://ffmpeg.org/download.html")

    with open(args.script, encoding="utf-8") as f:
        script = json.load(f)
    if isinstance(script, list):
        script = {"messages": script}
    script.setdefault("settings", {})
    deep_update(VOICES, script["settings"].get("voices"))
    deep_update(THEME, script["settings"].get("theme"))
    deep_update(TIMING, script["settings"].get("timing"))

    tl = build_timeline(script)
    n_frames = int(round(tl["total"] * FPS))
    print(f"Длительность: {tl['total']:.2f} с, кадров: {n_frames}")

    # аудио больше не нужно передавать в процессы рендера
    audio_tl = tl
    render_tl = dict(tl, messages=[{k: v for k, v in m.items() if k != "audio"} for m in tl["messages"]])

    if args.preview is not None:
        r = Renderer(render_tl)
        Image.frombytes("RGB", (W, H), r.frame(args.preview)).save("preview.png")
        print("preview.png сохранён")
        return

    tmp = tempfile.mkdtemp(prefix="chatvid_")
    wav = os.path.join(tmp, "audio.wav")
    build_audio(audio_tl, wav)

    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", wav,
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
           "-movflags", "+faststart", "-shortest", args.output]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    with Pool(args.jobs, initializer=_init_worker, initargs=(render_tl,)) as pool:
        for i, buf in enumerate(pool.imap(_render, range(n_frames), chunksize=8)):
            ff.stdin.write(buf)
            if i % (FPS * 5) == 0:
                print(f"\r  рендер {i}/{n_frames} ({time.time() - t0:.0f} с)", end="", flush=True)
    ff.stdin.close()
    ff.wait()
    shutil.rmtree(tmp, ignore_errors=True)
    if ff.returncode != 0:
        sys.exit("ffmpeg завершился с ошибкой")
    print(f"\nГотово: {os.path.abspath(args.output)}  ({time.time() - t0:.0f} с)")


if __name__ == "__main__":
    main()
