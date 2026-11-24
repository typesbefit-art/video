#!/usr/bin/env python3
"""
Генератор вертикального видео «смешная история от первого лица».

    python generate.py story.txt                 -> output.mp4 (30 fps)
    python generate.py story.txt --fps 60        -> 60 fps
    python generate.py story.txt --preview 15    -> preview.mp4 (первые 15 секунд)

story.txt: первая строка — заголовок, дальше — текст истории.
Финальная шутка определяется автоматически (последнее предложение; если оно
короче 4 слов — два последних). Можно задать её явно: отделить строкой "---".
"""
import argparse
import asyncio
import functools
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
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ============================================================================
#                               НАСТРОЙКИ
# ============================================================================
W, H = 1080, 1920
SR = 48000                         # частота дискретизации звука

# --- Голос ---
VOICE = "ru-RU-SvetlanaNeural"     # список голосов: edge-tts --list-voices
RATE = "+10%"
PITCH = "+2Hz"
READ_TITLE = True                  # озвучивать заголовок в начале
PAUSE_SENTENCE = 0.25              # пауза между предложениями, с
PAUSE_BEFORE_JOKE = 0.7            # пауза перед финальной шуткой, с
PAUSE_BEFORE_TAG = 0.45            # пауза перед коротким «добивающим» хвостом шутки
MIN_DUR, MAX_DUR = 45.0, 60.0      # целевая длина ролика (темп подстраивается сам)

# --- Фон ---
BG_DIR = "bg"                      # сюда можно класть свои .mp4/.mov
BG_VIDEO_BRIGHTNESS = -0.08        # приглушение яркости фонового видео
BG_COLOR_A = (24, 212, 200)        # бирюзовый
BG_COLOR_B = (255, 214, 58)        # жёлтый
SHAPE_COLORS = [(255, 255, 255), (255, 92, 138), (255, 150, 40),
                (90, 120, 255), (255, 255, 160), (20, 160, 150)]

# --- Субтитры ---
FONT_CANDIDATES = [
    "fonts/Inter-ExtraBold.ttf", "fonts/Inter-ExtraBold.otf",
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/truetype/inter/Inter-ExtraBold.ttf",
    "/Library/Fonts/Inter-ExtraBold.ttf", "C:/Windows/Fonts/Inter-ExtraBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
SUB_FONT_SIZE = 104
SUB_Y = 0.60                       # центр субтитров — 60% высоты
SUB_COLOR = (255, 255, 255)
SUB_HIGHLIGHT = (255, 224, 0)      # текущее слово
SUB_HIGHLIGHT_SCALE = 1.10
SUB_STROKE = (0, 0, 0)
SUB_STROKE_W = 9
WORDS_PER_GROUP = 4                # 3–4 слова на экране
JOKE_FONT_SIZE = 180               # финальная шутка — крупно, по слову
TITLE_FONT_SIZE = 124
TITLE_HOLD = 1.5                   # сколько держится заголовок
TITLE_SLIDE = 0.45                 # за сколько уезжает вверх
ZOOM = 1.06                        # зум на слове «шутка» и в финале
END_CARD_TEXT = "Подписывайся,\nдальше смешнее"
END_CARD_DUR = 1.5
END_CARD_COLOR = (255, 48, 92)
END_CARD_TEXT_COLOR = (255, 255, 255)

# --- Звук ---
MUSIC_DB = -26.0                   # громкость бита (RMS, dBFS)
VOICE_DB = -13.0                   # громкость голоса (RMS речи, dBFS)
MIN_VOICE_OVER_MUSIC_DB = 12.0
MUSIC_DUCK_DB = 3.0                # доп. приглушение бита под голосом
BPM = 112
POP_EVERY = 3                      # «поп» на каждом N-м предложении

CACHE_DIR = ".cache"


# ============================================================================
#                               УТИЛИТЫ
# ============================================================================
def log(*a):
    print(*a, flush=True)


def need_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"Не найден {tool}. Установите ffmpeg (https://ffmpeg.org) и добавьте в PATH.")


def norm(s):
    return re.sub(r"[^0-9a-zа-я]", "", s.lower().replace("ё", "е"))


def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def ease_out_back(x, k=1.7):
    x = min(1.0, max(0.0, x)) - 1
    return 1 + (k + 1) * x ** 3 + k * x ** 2


def db_to_amp(db):
    return 10 ** (db / 20)


def rms_db(x):
    return 20 * math.log10(max(1e-9, float(np.sqrt(np.mean(x ** 2))))) if len(x) else -120.0


# ============================================================================
#                               ИСТОРИЯ
# ============================================================================
def split_sentences(text):
    text = " ".join(text.split())
    out, start = [], 0
    for m in re.finditer(r"[.!?…]+[»\"”)]*(\s+)", text):
        piece = text[start:m.start(1)]
        if piece.count("«") > piece.count("»"):      # внутри цитаты — не режем
            continue
        nxt = text[m.end():m.end() + 1]
        if nxt and (nxt.isupper() or nxt in "«\"„“—-"):
            out.append(piece.strip())
            start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return [s for s in out if norm(s)]


def tokens(sentence):
    """Слова для показа: знаки-одиночки (—) приклеиваются к предыдущему слову."""
    out = []
    for tok in sentence.split():
        if not norm(tok) and out:
            out[-1] += " " + tok
        elif norm(tok):
            out.append(tok)
    return out


def parse_story(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    lines = [l.strip() for l in lines]
    while lines and not lines[0]:
        lines.pop(0)
    if not lines:
        sys.exit("story.txt пустой")
    title = lines[0]
    body = "\n".join(lines[1:]).strip()
    parts = re.split(r"^\s*---\s*$", body, flags=re.M)
    if len(parts) >= 2:
        story = split_sentences(parts[0])
        joke = split_sentences(" ".join(parts[1:]))
    else:
        story = split_sentences(body)
        joke = [story.pop()]
        if len(tokens(joke[0])) <= 3 and story:
            joke.insert(0, story.pop())
    if not story:
        sys.exit("В истории слишком мало предложений")
    return title, story, joke


# ============================================================================
#                               ОЗВУЧКА (edge-tts)
# ============================================================================
def _patch_edge_ssl():
    """edge-tts доверяет только certifi; добавляем CA из SSL_CERT_FILE (корп. прокси)."""
    try:
        import certifi
        import edge_tts.communicate as ec
    except Exception:
        return
    extra = [os.environ.get(v) for v in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")]
    extra = [p for p in extra if p and os.path.isfile(p)]
    if not extra or not hasattr(ec, "_SSL_CTX"):
        return
    ctx = ssl.create_default_context(cafile=certifi.where())
    for p in extra:
        try:
            ctx.load_verify_locations(p)
        except Exception:
            pass
    ec._SSL_CTX = ctx


async def _tts_one(text, voice, rate, pitch, cache, sem):
    import edge_tts
    key = hashlib.sha1(json.dumps([text, voice, rate, pitch]).encode()).hexdigest()[:16]
    mp3, meta = cache / f"{key}.mp3", cache / f"{key}.json"
    if mp3.exists() and meta.exists():
        return mp3, json.loads(meta.read_text(encoding="utf-8"))
    async with sem:
        for attempt in range(4):
            try:
                try:
                    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                                               boundary="WordBoundary")
                except TypeError:          # старые версии edge-tts
                    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
                audio, words = bytearray(), []
                async for ch in com.stream():
                    if ch["type"] == "audio":
                        audio += ch["data"]
                    elif ch["type"] == "WordBoundary":
                        s = ch["offset"] / 1e7
                        words.append([s, s + ch["duration"] / 1e7, ch["text"]])
                if not audio:
                    raise RuntimeError("пустой ответ edge-tts")
                tmp = mp3.with_suffix(".tmp")
                tmp.write_bytes(bytes(audio))
                tmp.replace(mp3)
                meta.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
                return mp3, words
            except Exception as e:
                if attempt == 3:
                    raise RuntimeError(f"edge-tts не смог озвучить «{text[:40]}…»: {e}")
                await asyncio.sleep(1.5 * (attempt + 1))


def tts_all(texts, voice, rate, pitch):
    _patch_edge_ssl()
    cache = Path(CACHE_DIR) / "tts"
    cache.mkdir(parents=True, exist_ok=True)

    async def run():
        sem = asyncio.Semaphore(4)
        return await asyncio.gather(*[_tts_one(t, voice, rate, pitch, cache, sem) for t in texts])
    return asyncio.run(run())


def decode_audio(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def align_words(display, bounds):
    """Сопоставляем слова текста (с пунктуацией) с WordBoundary от edge-tts."""
    n = len(display)
    times = [None] * n
    dn = [norm(w) for w in display]
    j, last, remainder = 0, -1, ""
    for s, e, txt in bounds:
        b = norm(txt)
        if not b:
            continue
        if last >= 0 and remainder.startswith(b):          # «из-за» -> «из», «за»
            times[last][1] = e
            remainder = remainder[len(b):]
            continue
        for k in range(j, min(n, j + 4)):
            if dn[k] == b or dn[k].startswith(b) or b.startswith(dn[k]):
                times[k] = [s, e]
                last, j = k, k + 1
                remainder = dn[k][len(b):] if dn[k].startswith(b) else ""
                break
    # интерполяция для несопоставленных слов (числа и т.п.)
    known = [i for i in range(n) if times[i]]
    if not known:
        total = bounds[-1][1] if bounds else 1.0
        return [[total * i / n, total * (i + 1) / n] for i in range(n)]
    for i in range(n):
        if times[i]:
            continue
        prev = max([k for k in known if k < i], default=None)
        nxt = min([k for k in known if k > i], default=None)
        a = times[prev][1] if prev is not None else 0.0
        b = times[nxt][0] if nxt is not None else a + 0.3 * (i - (prev or 0) + 1)
        lo = prev if prev is not None else -1
        hi = nxt if nxt is not None else n
        span = (b - a) / (hi - lo - 1 + 1e-9)
        times[i] = [a + span * (i - lo - 1), a + span * (i - lo)]
    return times


def trim_bounds(audio):
    env = np.convolve(np.abs(audio), np.ones(480) / 480, mode="same")
    idx = np.where(env > 0.004)[0]
    if not len(idx):
        return 0, len(audio)
    return max(0, idx[0] - int(0.03 * SR)), min(len(audio), idx[-1] + int(0.07 * SR))


def build_voice(title, story, joke, voice, rate, pitch):
    """Синтез, раскладка предложений по таймлайну с паузами."""
    items = ([("title", title)] if READ_TITLE else []) + \
            [("story", s) for s in story] + [("joke", s) for s in joke]
    res = tts_all([t for _, t in items], voice, rate, pitch)
    segs, words, pops = [], [], []
    t = 0.15
    story_i = 0
    for n, ((kind, text), (mp3, bounds)) in enumerate(zip(items, res)):
        if n > 0:
            prev_kind = items[n - 1][0]
            if kind == "story" and prev_kind == "title":
                t += 0.35
            elif kind == "joke" and prev_kind != "joke":
                t += PAUSE_BEFORE_JOKE
            elif kind == "joke" and n == len(items) - 1 and len(tokens(text)) <= 3:
                t += PAUSE_BEFORE_TAG
            else:
                t += PAUSE_SENTENCE
        audio = decode_audio(mp3)
        a, b = trim_bounds(audio)
        disp = tokens(text)
        times = align_words(disp, bounds)
        off = a / SR
        if times:   # не обрезаем начало первого / хвост последнего слова
            a = min(a, max(0, int((times[0][0] - 0.02) * SR)))
            b = max(b, min(len(audio), int((times[-1][1] + 0.05) * SR)))
            off = a / SR
        clip = audio[a:b]
        if kind == "story":
            story_i += 1
            if story_i % POP_EVERY == 0:
                pops.append(t - 0.06)
        for w, (s, e) in zip(disp, times):
            words.append(dict(text=w, norm=norm(w), start=t + s - off, end=t + e - off,
                              kind=kind, sent=n))
        segs.append((t, clip))
        t += len(clip) / SR
    return segs, words, pops, t


# ============================================================================
#                               ЗВУК: бит и эффекты
# ============================================================================
def _env(n, decay, attack=0.004):
    t = np.arange(n) / SR
    e = np.exp(-t * decay)
    na = max(1, int(attack * SR))
    e[:na] *= np.linspace(0, 1, na)
    return t, e


def _noise(n, rng):
    return rng.standard_normal(n)


def _hp(x):            # грубый фильтр высоких частот
    return np.diff(x, prepend=0)


def _lp(x, k=8):
    return np.convolve(x, np.ones(k) / k, mode="same")


def gen_music(dur, seed=1):
    rng = np.random.default_rng(seed)
    beat = 60 / BPM
    bar = 4 * beat
    prog = [(261.63, 329.63, 392.00, 65.41),    # C
            (196.00, 246.94, 293.66, 98.00),    # G
            (220.00, 261.63, 329.63, 110.00),   # Am
            (174.61, 220.00, 261.63, 87.31)]    # F
    loop_len = int(round(len(prog) * bar * SR))
    loop = np.zeros(loop_len)

    def add(sig, t, g):
        i = int(t * SR) % loop_len
        n = min(len(sig), loop_len - i)
        loop[i:i + n] += sig[:n] * g
        if n < len(sig):
            loop[:len(sig) - n] += sig[n:] * g

    n = int(0.35 * SR)
    t, e = _env(n, 9, 0.001)
    kick = np.sin(2 * np.pi * np.cumsum(45 + 95 * np.exp(-t * 28)) / SR) * e
    t, e = _env(int(0.2 * SR), 22, 0.001)
    snare = _hp(_noise(len(t), rng)) * 0.5 * e + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30) * 0.6
    t, e = _env(int(0.06 * SR), 75, 0.001)
    hat = _hp(_hp(_noise(len(t), rng))) * 0.25 * e
    t, e = _env(int(0.25 * SR), 2.8, 0.004)
    shaker = _hp(_noise(len(t), rng)) * np.exp(-((t - 0.04) ** 2) / 0.0008) * 0.15

    def pluck(freqs, length=0.4):
        t, e = _env(int(length * SR), 10, 0.003)
        s = sum(np.sin(2 * np.pi * f * t) + 0.45 * np.sin(4 * np.pi * f * t) +
                0.2 * np.sin(6 * np.pi * f * t) for f in freqs)
        return s * e / len(freqs)

    def bass(f, length=0.45):
        t, e = _env(int(length * SR), 4.5, 0.006)
        return (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t)) * e

    def bell(f):
        t, e = _env(int(0.5 * SR), 7, 0.002)
        return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2.76 * t)) * e

    melody = [0, 2, 1, None, 2, None, 0, 1]   # индексы нот аккорда, по восьмым (вторая половина такта)
    for bi, (a, b, c, root) in enumerate(prog):
        t0 = bi * bar
        for k in (0, 2):
            add(kick, t0 + k * beat, 0.9)
        if bi % 2 == 1:
            add(kick, t0 + 3.5 * beat, 0.55)
        for k in (1, 3):
            add(snare, t0 + k * beat, 0.42)
        for k in range(8):
            add(hat, t0 + k * beat / 2, 0.22 if k % 2 else 0.12)
        for k in range(4):
            add(shaker, t0 + (k + 0.75) * beat, 0.5)
            add(pluck((a, b, c)), t0 + (k + 0.5) * beat, 0.22)
        add(bass(root), t0, 0.42)
        add(bass(root), t0 + 1.5 * beat, 0.32)
        add(bass(root * 1.5), t0 + 2.5 * beat, 0.3)
        if bi % 2 == 1:
            for k, mi in enumerate(melody):
                if mi is not None:
                    add(bell((a, b, c)[mi] * 2), t0 + 2 * beat + k * beat / 4, 0.09)
    reps = int(math.ceil(dur * SR / loop_len)) + 1
    music = np.tile(loop, reps)[:int(dur * SR)]
    # плавное начало и конец
    fi, fo = int(0.3 * SR), int(1.2 * SR)
    music[:fi] *= np.linspace(0, 1, fi)
    music[-fo:] *= np.linspace(1, 0, fo)
    return music


def gen_pop(seed=2):
    t, e = _env(int(0.09 * SR), 45, 0.001)
    f = 300 + 700 * np.exp(-t * 60)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * e
    click = _hp(np.random.default_rng(seed).standard_normal(len(t))) * np.exp(-t * 400) * 0.3
    return (s + click) * 0.45


def gen_badum_tss(seed=3):
    """Барабанный раскат -> «ба-дум» (томы) -> «тсс» (тарелка). Возвращает (звук, время удара тарелки)."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(2.4 * SR))

    def add(sig, t, g):
        i = int(t * SR)
        n = min(len(sig), len(out) - i)
        out[i:i + n] += sig[:n] * g

    t, e = _env(int(0.12 * SR), 35, 0.001)
    roll_hit = _hp(rng.standard_normal(len(t))) * 0.5 * e + np.sin(2 * np.pi * 200 * t) * e * 0.5
    roll_len, step = 0.42, 0.035
    for i in range(int(roll_len / step)):
        add(roll_hit, i * step, 0.15 + 0.35 * i * step / roll_len)

    def tom(f0, f1):
        t, e = _env(int(0.4 * SR), 9, 0.001)
        return np.sin(2 * np.pi * np.cumsum(f1 + (f0 - f1) * np.exp(-t * 20)) / SR) * e
    add(tom(210, 150), 0.47, 0.75)          # ба-
    add(tom(150, 100), 0.66, 0.85)          # -дум
    crash_t = 0.92
    t, e = _env(int(1.45 * SR), 2.6, 0.002)
    noise = _hp(_hp(rng.standard_normal(len(t))))
    metal = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in (3150, 4270, 5390, 6610, 8120))
    crash = (noise * 0.35 + metal * 0.06) * e
    t2, e2 = _env(int(0.35 * SR), 9, 0.001)
    kick = np.sin(2 * np.pi * np.cumsum(45 + 90 * np.exp(-t2 * 28)) / SR) * e2
    add(crash, crash_t, 0.6)
    add(kick, crash_t, 0.7)
    add(roll_hit, crash_t, 0.6)
    return out * 0.8, crash_t


def build_audio(segs, words, pops, total, voice_end, badum_t):
    n = int(round(total * SR))
    voice = np.zeros(n)
    for t, clip in segs:
        i = int(t * SR)
        m = min(len(clip), n - i)
        voice[i:i + m] += clip[:m]
    # нормализация голоса по RMS активной речи
    env = np.convolve(np.abs(voice), np.ones(2400) / 2400, mode="same")
    active = env > 0.01 * max(1e-6, env.max())
    voice *= db_to_amp(VOICE_DB) / max(1e-9, float(np.sqrt(np.mean(voice[active] ** 2))))

    music = gen_music(total)
    music *= db_to_amp(MUSIC_DB) / max(1e-9, float(np.sqrt(np.mean(music ** 2))))
    # лёгкий дакинг бита под голосом
    speech = np.convolve(active.astype(float), np.ones(int(0.25 * SR)) / int(0.25 * SR), mode="same")
    duck = 1 - (1 - db_to_amp(-MUSIC_DUCK_DB)) * np.clip(speech * 1.5, 0, 1)
    music_d = music * duck

    v_db = rms_db(voice[active])
    m_db = rms_db(music_d[active])
    if v_db - m_db < MIN_VOICE_OVER_MUSIC_DB:
        fix = MIN_VOICE_OVER_MUSIC_DB + 0.5 - (v_db - m_db)
        music_d *= db_to_amp(-fix)
        m_db -= fix
    sfx = np.zeros(n)
    pop = gen_pop()
    for t in pops:
        i = max(0, int(t * SR))
        m = min(len(pop), n - i)
        sfx[i:i + m] += pop[:m] * db_to_amp(VOICE_DB + 6)
    bd, _ = gen_badum_tss()
    i = int(badum_t * SR)
    m = min(len(bd), n - i)
    sfx[i:i + m] += bd[:m] * db_to_amp(VOICE_DB + 9)

    mix = voice + music_d + sfx
    log(f"   голос {v_db:.1f} dB, бит {rms_db(music):.1f} dB (под голосом {m_db:.1f} dB) "
        f"-> голос громче на {v_db - m_db:.1f} dB")
    return np.stack([mix, mix], axis=1).astype(np.float32)


# ============================================================================
#                               ГРАФИКА
# ============================================================================
@functools.lru_cache(maxsize=None)
def font_path():
    for p in FONT_CANDIDATES:
        if os.path.isfile(p):
            return p
    try:
        p = subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Sans:bold"],
                           capture_output=True, text=True).stdout.strip()
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    sys.exit("Не найден жирный шрифт. Положите Inter-ExtraBold.ttf в папку fonts/")


@functools.lru_cache(maxsize=None)
def get_font(size):
    return ImageFont.truetype(font_path(), int(size))


@functools.lru_cache(maxsize=4096)
def render_text(text, size, fill, stroke_w=SUB_STROKE_W, stroke=SUB_STROKE, shadow=True):
    """Слово/строка в RGBA, центр картинки = центр текста (anchor 'mm')."""
    font = get_font(size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font, anchor="mm", stroke_width=stroke_w)
    pad = 16 + stroke_w
    w = int(2 * max(-l, r) + 2 * pad)
    h = int(2 * max(-t, b) + 2 * pad)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((w / 2, h / 2 + size * 0.06), text, font=font, anchor="mm",
                                fill=(0, 0, 0, 150), stroke_width=stroke_w, stroke_fill=(0, 0, 0, 150))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(size * 0.05)))
    ImageDraw.Draw(img).text((w / 2, h / 2), text, font=font, anchor="mm", fill=fill,
                             stroke_width=stroke_w, stroke_fill=stroke)
    return img


def text_width(text, size, stroke_w=SUB_STROKE_W):
    return get_font(size).getlength(text) + 2 * stroke_w


def paste_center(frame, img, cx, cy, scale=1.0, alpha=1.0):
    if scale != 1.0:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                         Image.BILINEAR)
    if alpha < 1.0:
        img = img.copy()
        img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    frame.paste(img, (int(cx - img.width / 2), int(cy - img.height / 2)), img)


# ---------------------------- фон ----------------------------
class GeneratedBG:
    """Анимированный градиент бирюзовый→жёлтый с плывущими фигурами."""

    def __init__(self, seed):
        rng = random.Random(seed)
        self.sw, self.sh = W // 2, H // 2
        gx, gy = np.meshgrid(np.linspace(0, 1, W // 8), np.linspace(0, 1, H // 8))
        self.gx, self.gy = gx, gy * (H / W)
        self.A = np.array(BG_COLOR_A, float)
        self.B = np.array(BG_COLOR_B, float)
        self.shapes = []
        for _ in range(18):
            size = rng.uniform(25, 120)
            self.shapes.append(dict(
                kind=rng.choice(["circle", "circle", "ring", "triangle", "square", "plus"]),
                x=rng.uniform(0, self.sw), y=rng.uniform(0, self.sh), size=size,
                vy=-rng.uniform(15, 55) * (60 / size) ** 0.3,
                amp=rng.uniform(10, 40), freq=rng.uniform(0.2, 0.6), ph=rng.uniform(0, 6.3),
                rot=rng.uniform(-60, 60), rot0=rng.uniform(0, 360),
                color=rng.choice(SHAPE_COLORS) + (rng.randint(130, 210),)))

    def frame(self, t):
        a = 0.9 + 0.35 * math.sin(t * 0.35)
        proj = self.gx * math.cos(a) + self.gy * math.sin(a)
        proj = (proj - proj.min()) / (proj.max() - proj.min() + 1e-9)
        m = proj + 0.13 * np.sin(proj * 6 + t * 0.9) + 0.06 * np.sin(self.gx * 9 - t * 0.7)
        m = np.clip(m, 0, 1)[..., None]
        m = m * m * (3 - 2 * m)
        small = (self.A * (1 - m) + self.B * m).astype(np.uint8)
        img = Image.fromarray(small).resize((self.sw, self.sh), Image.BILINEAR).convert("RGBA")
        over = Image.new("RGBA", (self.sw, self.sh), (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        for s in self.shapes:
            r = s["size"] / 2
            span = self.sh + 2 * s["size"]
            y = (s["y"] + s["vy"] * t) % span - s["size"]
            x = s["x"] + s["amp"] * math.sin(s["freq"] * t * 2 * math.pi + s["ph"])
            ang = math.radians(s["rot0"] + s["rot"] * t)
            c = s["color"]
            if s["kind"] == "circle":
                d.ellipse((x - r, y - r, x + r, y + r), fill=c)
            elif s["kind"] == "ring":
                d.ellipse((x - r, y - r, x + r, y + r), outline=c, width=max(4, int(r * 0.25)))
            elif s["kind"] in ("triangle", "square"):
                k = 3 if s["kind"] == "triangle" else 4
                pts = [(x + r * math.cos(ang + 2 * math.pi * i / k),
                        y + r * math.sin(ang + 2 * math.pi * i / k)) for i in range(k)]
                d.polygon(pts, fill=c)
            else:
                wbar = r * 0.35
                for base in (ang, ang + math.pi / 2):
                    dx, dy = math.cos(base), math.sin(base)
                    px, py = -dy * wbar, dx * wbar
                    d.polygon([(x - dx * r + px, y - dy * r + py), (x + dx * r + px, y + dy * r + py),
                               (x + dx * r - px, y + dy * r - py), (x - dx * r - px, y - dy * r - py)],
                              fill=c)
        return Image.alpha_composite(img, over).convert("RGB")

    def get(self, t, zoom):
        img = self.frame(t)
        bw, bh = self.sw / zoom, self.sh / zoom
        box = ((self.sw - bw) / 2, (self.sh - bh) / 2, (self.sw + bw) / 2, (self.sh + bh) / 2)
        return img.resize((W, H), Image.BILINEAR, box=box)

    def close(self):
        pass


class VideoBG:
    """Случайное видео из bg/: обрезка/зацикливание, центр 9:16, приглушённая яркость."""

    def __init__(self, path, total, fps, seed):
        dur = 0.0
        try:
            dur = float(subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                 str(path)], capture_output=True, text=True).stdout.strip())
        except ValueError:
            pass
        rng = random.Random(seed)
        inp = []
        if dur > total + 0.5:
            inp = ["-ss", f"{rng.uniform(0, dur - total - 0.2):.2f}"]
        else:
            inp = ["-stream_loop", "-1"]
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"fps={fps},eq=brightness={BG_VIDEO_BRIGHTNESS}:saturation=1.03,format=rgb24")
        cmd = ["ffmpeg", "-v", "error", *inp, "-i", str(path), "-t", f"{total:.3f}", "-an",
               "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        self.last = Image.new("RGB", (W, H), (20, 20, 20))

    def get(self, t, zoom):
        data = self.proc.stdout.read(W * H * 3)
        if len(data) == W * H * 3:
            self.last = Image.frombytes("RGB", (W, H), data)
        img = self.last
        if zoom > 1.0005:
            bw, bh = W / zoom, H / zoom
            img = img.resize((W, H), Image.BILINEAR,
                             box=((W - bw) / 2, (H - bh) / 2, (W + bw) / 2, (H + bh) / 2))
        return img

    def close(self):
        self.proc.stdout.close()
        self.proc.kill()


def pick_background(total, fps, seed):
    d = Path(BG_DIR)
    vids = sorted([p for p in d.iterdir() if p.suffix.lower() in (".mp4", ".mov")]) if d.is_dir() else []
    if vids:
        p = random.Random(seed).choice(vids)
        log(f"   фон: видео {p}")
        return VideoBG(p, total, fps, seed), True
    log("   фон: сгенерированный градиент (папка bg/ пуста или отсутствует)")
    return GeneratedBG(seed), False


# ---------------------------- субтитры ----------------------------
def make_groups(words):
    """Группы по 3–4 слова в пределах предложения (кроме финальной шутки)."""
    groups = []
    by_sent = {}
    for w in words:
        if w["kind"] == "story":
            by_sent.setdefault(w["sent"], []).append(w)
    for sent in sorted(by_sent):
        ws = by_sent[sent]
        k = math.ceil(len(ws) / WORDS_PER_GROUP)
        base, extra = divmod(len(ws), k)
        i = 0
        for g in range(k):
            n = base + (1 if g < extra else 0)
            groups.append(ws[i:i + n])
            i += n
    return groups


def layout_group(ws):
    size = SUB_FONT_SIZE
    max_w = W - 2 * 70
    while True:
        space = size * 0.3
        widths = [text_width(w["text"], size) for w in ws]
        total = sum(widths) + space * (len(ws) - 1)
        if max_w < total <= max_w * 1.25 and size > SUB_FONT_SIZE * 0.8:
            size -= 4          # чуть уменьшаем шрифт, чтобы уместиться в одну строку
            continue
        if total <= max_w:
            lines = [list(range(len(ws)))]
        else:   # две строки, наиболее ровное деление
            best = None
            for cut in range(1, len(ws)):
                l1 = sum(widths[:cut]) + space * (cut - 1)
                l2 = sum(widths[cut:]) + space * (len(ws) - cut - 1)
                if best is None or max(l1, l2) < best[0]:
                    best = (max(l1, l2), cut)
            lines = [list(range(best[1])), list(range(best[1], len(ws)))] if best else [[0]]
        widest = max(sum(widths[i] for i in ln) + space * (len(ln) - 1) for ln in lines)
        if widest <= max_w or size < 50:
            break
        size -= 6
    lh = size * 1.2
    cy0 = H * SUB_Y - lh * (len(lines) - 1) / 2
    pos = {}
    for li, ln in enumerate(lines):
        lw = sum(widths[i] for i in ln) + space * (len(ln) - 1)
        x = (W - lw) / 2
        for i in ln:
            pos[i] = (x + widths[i] / 2, cy0 + li * lh)
            x += widths[i] + space
    return size, pos


def zoom_at(t, zoom_events, final_start):
    z = 0.0
    for s in zoom_events:     # слово «шутка»: наезд 0.35 с, держим 0.8 с, отъезд 0.5 с
        if s - 0.1 <= t <= s + 1.75:
            z = max(z, smoothstep((t - s + 0.1) / 0.35) * (1 - smoothstep((t - s - 1.15) / 0.5)))
    if t >= final_start:
        z = max(z, smoothstep((t - final_start) / 0.6))
    return 1 + (ZOOM - 1) * z


def build_title_image(title):
    size = TITLE_FONT_SIZE
    max_w = W - 2 * 80
    while True:
        lines, cur = [], []
        for word in title.split():
            trial = " ".join(cur + [word])
            if cur and text_width(trial, size, 10) > max_w:
                lines.append(" ".join(cur))
                cur = [word]
            else:
                cur.append(word)
        if cur:
            lines.append(" ".join(cur))
        if all(text_width(l, size, 10) <= max_w for l in lines) or size < 60:
            break
        size -= 6
    imgs = [render_text(l, size, (255, 255, 255), 10, (0, 0, 0)) for l in lines]
    lh = int(size * 1.12)
    tw = max(i.width for i in imgs)
    th = lh * (len(imgs) - 1) + imgs[-1].height
    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    for k, im in enumerate(imgs):
        out.alpha_composite(im, ((tw - im.width) // 2, k * lh))
    return out


def build_end_card():
    lines = END_CARD_TEXT.split("\n")
    size = 86
    imgs = [render_text(l, size, END_CARD_TEXT_COLOR, 4, (120, 0, 30), shadow=False) for l in lines]
    lh = int(size * 1.15)
    tw = max(i.width for i in imgs)
    th = lh * (len(imgs) - 1) + imgs[-1].height
    pw, ph = tw + 90, th + 70
    card = Image.new("RGBA", (pw + 40, ph + 50), (0, 0, 0, 0))
    sh = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((20, 32, 20 + pw, 32 + ph), 44, fill=(0, 0, 0, 120))
    card = Image.alpha_composite(card, sh.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((20, 20, 20 + pw, 20 + ph), 44, fill=END_CARD_COLOR + (255,),
                        outline=(255, 255, 255, 255), width=6)
    y = 20 + (ph - th) // 2
    for k, im in enumerate(imgs):
        card.alpha_composite(im, (20 + (pw - im.width) // 2, y + k * lh))
    return card


# ============================================================================
#                               СБОРКА
# ============================================================================
def render(story_path, out, fps, preview, voice, rate, pitch, seed):
    need_ffmpeg()
    title, story, joke = parse_story(story_path)
    log(f"Заголовок: {title}")
    log(f"Предложений: {len(story)} + финальная шутка: {' '.join(joke)}")

    # --- озвучка, с подстройкой темпа под 45–60 с ---
    cur_rate = rate
    for attempt in range(3):
        log(f"1) Озвучка edge-tts ({voice}, rate {cur_rate}, pitch {pitch})…")
        segs, words, pops, voice_end = build_voice(title, story, joke, voice, cur_rate, pitch)
        badum_t = voice_end + 0.12
        crash_t = badum_t + 0.92
        end_start = crash_t + 0.25
        total = end_start + END_CARD_DUR + 0.25
        if MIN_DUR <= total <= MAX_DUR:
            break
        speech = sum(len(c) / SR for _, c in segs)
        fixed = total - speech
        target = (MAX_DUR - 1.5) if total > MAX_DUR else (MIN_DUR + 1.5)
        r = int(cur_rate.rstrip("%"))
        new_r = int(round((100 + r) * speech / max(1.0, target - fixed) - 100))
        new_r = max(-25, min(50, new_r))
        if new_r == r:
            break
        log(f"   длина {total:.1f} с вне диапазона {MIN_DUR:.0f}–{MAX_DUR:.0f} с, меняю темп на {new_r:+d}%")
        cur_rate = f"{new_r:+d}%"
    log(f"   длина ролика: {total:.1f} с")
    if not (MIN_DUR <= total <= MAX_DUR):
        log("   ВНИМАНИЕ: длина вне 45–60 с — история слишком длинная/короткая.")

    # --- звук ---
    log("2) Бит, эффекты, сведение…")
    audio = build_audio(segs, words, pops, total, voice_end, badum_t)
    render_len = min(total, preview) if preview else total
    audio = audio[:int(round(render_len * SR))]
    tmpdir = Path(tempfile.mkdtemp(prefix="storyvid_"))
    audio_path = tmpdir / "mix.f32"
    audio.tofile(audio_path)

    # --- подготовка графики ---
    groups = make_groups(words)
    layouts = [layout_group(g) for g in groups]
    g_times = []
    for gi, g in enumerate(groups):
        s = g[0]["start"] - 0.05
        e = g[-1]["end"] + 0.45
        if gi + 1 < len(groups):
            e = min(e, groups[gi + 1][0]["start"] - 0.05)
        g_times.append((s, max(e, g[-1]["end"])))
    joke_words = [w for w in words if w["kind"] == "joke"]
    final_start = joke_words[0]["start"] - 0.25 if joke_words else total
    zoom_events = [w["start"] for w in words if w["norm"].startswith("шутк")]
    title_img = build_title_image(title)
    card_img = build_end_card()
    title_end = TITLE_HOLD + TITLE_SLIDE

    bg, is_video = pick_background(total, fps, seed)
    n_frames = int(round(render_len * fps))
    log(f"3) Рендер {n_frames} кадров ({W}x{H}, {fps} fps) + кодирование…")
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(audio_path),
           "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-g", str(fps * 2),
           "-af", "alimiter=limit=0.94:level=0:attack=3:release=60",
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
           "-movflags", "+faststart", "-shortest", str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for fi in range(n_frames):
            t = fi / fps
            frame = bg.get(t, zoom_at(t, zoom_events, final_start))

            # заголовок
            if t < title_end:
                pop = ease_out_back(t / 0.3) if t < 0.3 else 1.0
                sc = 0.75 + 0.25 * pop
                y = H * 0.42
                alpha = 1.0
                if t > TITLE_HOLD:
                    k = (t - TITLE_HOLD) / TITLE_SLIDE
                    y -= (H * 0.42 + title_img.height) * (k * k)
                    alpha = max(0.0, 1 - k * 0.6)
                paste_center(frame, title_img, W / 2, y, sc, alpha)

            in_card = t >= end_start
            # обычные субтитры
            if t >= TITLE_HOLD and not in_card:
                for gi, (s, e) in enumerate(g_times):
                    if s <= t < e:
                        g, (size, pos) = groups[gi], layouts[gi]
                        rise = 18 * (1 - smoothstep((t - s) / 0.1))
                        cur = None
                        for i, w in enumerate(g):
                            nxt = g[i + 1]["start"] if i + 1 < len(g) else w["end"] + 0.15
                            if w["start"] <= t < nxt:
                                cur = i
                        for i, w in enumerate(g):
                            cx, cy = pos[i]
                            if i == cur:
                                img = render_text(w["text"], int(size * SUB_HIGHLIGHT_SCALE), SUB_HIGHLIGHT)
                            else:
                                img = render_text(w["text"], size, SUB_COLOR)
                            paste_center(frame, img, cx, cy + rise)
                        break
            # финальная шутка: крупно, по одному слову
            if joke_words and not in_card:
                for i, w in enumerate(joke_words):
                    nxt = joke_words[i + 1]["start"] - 0.03 if i + 1 < len(joke_words) else end_start
                    if w["start"] - 0.03 <= t < nxt:
                        txt = w["text"].rstrip(".,…")
                        size = JOKE_FONT_SIZE
                        while text_width(txt, size, 12) > W - 120 and size > 60:
                            size -= 8
                        img = render_text(txt, size, SUB_HIGHLIGHT, 12)
                        sc = 0.7 + 0.3 * ease_out_back((t - w["start"] + 0.03) / 0.16)
                        paste_center(frame, img, W / 2, H * SUB_Y, sc)
                        break
            # плашка «Подписывайся»
            if in_card:
                k = (t - end_start) / 0.28
                sc = 0.5 + 0.5 * ease_out_back(k) if k < 1 else 1 + 0.025 * math.sin((t - end_start) * 9)
                paste_center(frame, card_img, W / 2, H * 0.5, sc)

            enc.stdin.write(frame.tobytes())
            if fi % max(1, n_frames // 10) == 0:
                log(f"   {100 * fi // n_frames:3d}%")
        enc.stdin.close()
        if enc.wait() != 0:
            sys.exit("ffmpeg завершился с ошибкой")
    finally:
        bg.close()
        shutil.rmtree(tmpdir, ignore_errors=True)
    log(f"Готово: {Path(out).resolve()}  ({render_len:.1f} с)")
    if not is_video:
        log("Подсказка: положите свои .mp4/.mov в папку bg/ — фон возьмётся оттуда.")


def main():
    ap = argparse.ArgumentParser(description="Вертикальное видео-история с озвучкой и субтитрами")
    ap.add_argument("story", nargs="?", default="story.txt")
    ap.add_argument("-o", "--out", default=None, help="выходной файл (по умолчанию output.mp4)")
    ap.add_argument("--fps", type=int, default=30, choices=[24, 25, 30, 50, 60])
    ap.add_argument("--preview", type=float, default=0, metavar="СЕК",
                    help="отрендерить только первые N секунд (файл preview.mp4)")
    ap.add_argument("--voice", default=VOICE)
    ap.add_argument("--rate", default=RATE)
    ap.add_argument("--pitch", default=PITCH)
    ap.add_argument("--seed", type=int, default=None, help="зерно случайности (фон/фигуры)")
    a = ap.parse_args()
    out = a.out or ("preview.mp4" if a.preview else "output.mp4")
    seed = a.seed if a.seed is not None else random.randrange(1 << 30)
    render(a.story, out, a.fps, a.preview, a.voice, a.rate, a.pitch, seed)


if __name__ == "__main__":
    main()
