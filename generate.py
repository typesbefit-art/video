#!/usr/bin/env python3
"""
Генератор вертикального видео «фейковая переписка» (1080x1920, 60 fps, H.264 + AAC).

    python generate.py script.json                  -> output.mp4
    python generate.py script.json -o my.mp4
    python generate.py script.json --limit 6 -o preview.mp4   (пробная версия)

Сценарий, имена, голоса и цвета пузырей берутся из script.json.
Визуальные константы (фон, размеры, шрифты) собраны в блоке THEME ниже.
"""
import argparse
import asyncio
import copy
import hashlib
import json
import math
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 60
SR = 48000

# ----------------------------------------------------------------------------
# ТЕМА / ВИЗУАЛ
# ----------------------------------------------------------------------------
THEME = {
    "bg_top": "#12141B",           # фон чата (градиент)
    "bg_bottom": "#0A0B10",
    "pattern": "#1A1D27",          # точки-узор на фоне
    "bar_bg": "#14161D",           # шапка и строка ввода
    "separator": "#20232D",
    "text": "#FFFFFF",
    "muted": "#8A8FA3",
    "typing_status": "#A78BFA",    # цвет «печатает...» в шапке
    "receipt_blue": "#4FB3FF",     # галочки «прочитано»
    "receipt_grey": "#6B7082",
    "input_bg": "#232631",
    "send_btn": "#7C3AED",
    "sub_text": "#FFFFFF",
    "sub_highlight": "#FFE14D",    # подсветка текущего слова в субтитрах
    "hook_accent": "#FFE14D",
    "outro_grad": ["#8B5CF6", "#5B21B6"],
}

DEFAULT_CHARACTERS = {
    "lera": {"name": "Лера", "side": "right", "voice": "ru-RU-SvetlanaNeural",
             "pitch": "-2Hz", "rate": "+0%", "bubble": ["#8B5CF6", "#6D28D9"],
             "avatar": "#7C3AED"},
    "yana": {"name": "Яна", "side": "left", "voice": "ru-RU-SvetlanaNeural",
             "pitch": "+6Hz", "rate": "+12%", "bubble": ["#2B2E38", "#2B2E38"],
             "avatar": "#EC4899"},
}

# Раскладка экрана
STATUS_H = 64
HEADER_Y, HEADER_H = STATUS_H, 160
CHAT_Y = HEADER_Y + HEADER_H            # 224
INPUT_Y, INPUT_H = 1340, 120
CHAT_H = INPUT_Y - CHAT_Y               # 1092
SUB_TOP = 1508            # верх блока субтитров (плашка с именем)

MARGIN = 40
BUBBLE_MAX_W = 760
PAD_X, PAD_Y = 34, 24
MSG_FONT_SIZE = 50
RADIUS = 40
TAIL_RADIUS = 12
RECEIPT_H = 40
GAP_SAME, GAP_OTHER = 8, 26
BOTTOM_PAD = 24

# Тайминги (секунды)
HOOK_DUR = 1.0
OUTRO_DUR = 1.5
APPEAR_ANIM = 0.28
SCROLL_ANIM = 0.32
TYPING_MIN, TYPING_MAX = 0.55, 0.95
TYPING_TAIL = 0.22        # минимальная пауза «печатает» перед сообщением
VOICE_DELAY = 0.04        # голос стартует чуть после появления пузыря
TARGET_MIN, TARGET_MAX = 45.0, 60.0
MAX_INNER_PAUSE = 0.22    # паузы внутри фразы длиннее этого сжимаются…
KEEP_INNER_PAUSE = 0.14   # …до этой длины

# Громкости (линейные)
VOICE_GAIN = 1.0
POP_GAIN = 0.22
BEAT_GAIN = 0.16
BEAT_DUCK = 0.45          # во время голоса бит приглушается до 45%

FONT_FILES = {
    "regular": "Inter-Regular.otf",
    "medium": "Inter-Medium.otf",
    "semibold": "Inter-SemiBold.otf",
    "bold": "Inter-Bold.otf",
    "extrabold": "Inter-ExtraBold.otf",
    "black": "Inter-Black.otf",
}


def log(*a):
    print(*a, flush=True)


# ----------------------------------------------------------------------------
# Утилиты
# ----------------------------------------------------------------------------
def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ease_out_cubic(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def ease_out_back(x, s=1.4):
    x = min(max(x, 0.0), 1.0)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def clamp(v, a, b):
    return max(a, min(b, v))


_font_cache = {}


def font(kind, size):
    key = (kind, size)
    if key not in _font_cache:
        path = os.path.join(ROOT, "fonts", FONT_FILES[kind])
        if not os.path.exists(path):
            for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                         if kind in ("bold", "extrabold", "black", "semibold")
                         else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
                path = cand
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


def wrap_text(text, fnt, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if fnt.getlength(test) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def rounded_mask(w, h, r, tail_corner=None, tail_r=TAIL_RADIUS, ss=3):
    """Маска пузыря со сглаживанием. tail_corner: 'br' / 'bl' — угол-«хвостик»."""
    m = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=r * ss, fill=255)
    if tail_corner:
        hw, hh = w * ss // 2, h * ss // 2
        box = [hw, hh, w * ss - 1, h * ss - 1] if tail_corner == "br" else [0, hh, hw, h * ss - 1]
        d.rounded_rectangle(box, radius=tail_r * ss, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def gradient(w, h, c1, c2, diagonal=True):
    a = np.array(hex2rgb(c1), dtype=np.float32)
    b = np.array(hex2rgb(c2), dtype=np.float32)
    ys = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    xs = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    t = (ys * 0.75 + xs * 0.25) if diagonal else np.repeat(ys, w, axis=1)
    t = np.clip(t, 0, 1)[..., None]
    arr = a * (1 - t) + b * t
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def with_alpha(img, alpha):
    if alpha >= 0.999:
        return img
    out = img.copy()
    a = out.getchannel("A").point(lambda v: int(v * alpha))
    out.putalpha(a)
    return out


def paste_rgba(dst, img, x, y, alpha=1.0):
    if alpha <= 0.003:
        return
    img = with_alpha(img, alpha)
    dst.paste(img, (int(round(x)), int(round(y))), img)


def draw_checks(double, color, scale=1.0):
    ss = 4
    w, h = int(34 * scale), int(20 * scale)
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    lw = int(3.2 * scale * ss)

    def check(ox):
        pts = [(ox + 1 * scale, 10 * scale), (ox + 7 * scale, 16 * scale), (ox + 19 * scale, 3 * scale)]
        d.line([(x * ss, y * ss) for x, y in pts], fill=color, width=lw, joint="curve")

    check(1 * scale if double else 7 * scale)
    if double:
        check(11 * scale)
    return im.resize((w, h), Image.LANCZOS)


def add_minutes(hhmm, minutes):
    h, m = map(int, hhmm.split(":"))
    tot = (h * 60 + m + minutes) % (24 * 60)
    return f"{tot // 60:02d}:{tot % 60:02d}"


# ----------------------------------------------------------------------------
# Сценарий
# ----------------------------------------------------------------------------
def load_script(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        data = {"messages": data}
    chars = copy.deepcopy(DEFAULT_CHARACTERS)
    for k, v in (data.get("characters") or {}).items():
        chars.setdefault(k, {}).update(v)
    data["characters"] = chars
    data.setdefault("title", "")
    data.setdefault("outro", "")
    data.setdefault("start_time", "19:42")
    for i, m in enumerate(data["messages"]):
        if m.get("who") not in chars:
            sys.exit(f"Реплика {i + 1}: неизвестный персонаж '{m.get('who')}'. "
                     f"Доступны: {', '.join(chars)}")
        m.setdefault("pause_after", 0.3)
    # «Собеседница» в шапке = персонаж слева
    left = [k for k, c in chars.items() if c.get("side") == "left"]
    data["contact"] = data.get("contact") or (left[0] if left else list(chars)[0])
    return data


# ----------------------------------------------------------------------------
# Озвучка (edge-tts) с кэшем
# ----------------------------------------------------------------------------
def shift_percent(rate, extra):
    m = re.match(r"([+-]?\d+)%", rate.strip())
    v = int(m.group(1)) if m else 0
    v += extra
    return f"{'+' if v >= 0 else ''}{v}%"


async def _edge_tts(text, voice, pitch, rate):
    import edge_tts
    try:  # корпоративный/облачный прокси с собственным CA
        from edge_tts import communicate as _c
        ca = os.environ.get("SSL_CERT_FILE")
        if ca and os.path.exists(ca) and hasattr(_c, "_SSL_CTX"):
            _c._SSL_CTX.load_verify_locations(ca)
    except Exception:
        pass
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    kw = dict(rate=rate, pitch=pitch, proxy=proxy)
    try:
        comm = edge_tts.Communicate(text, voice, boundary="WordBoundary", **kw)
    except TypeError:
        comm = edge_tts.Communicate(text, voice, **kw)
    audio, words = bytearray(), []
    async for ch in comm.stream():
        if ch["type"] == "audio":
            audio.extend(ch["data"])
        elif ch["type"] == "WordBoundary":
            words.append({"text": ch["text"], "start": ch["offset"] / 1e7,
                          "end": (ch["offset"] + ch["duration"]) / 1e7})
    return bytes(audio), words


def decode_audio(path):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def tts(text, voice, pitch, rate, cache_dir):
    key = hashlib.sha1(json.dumps([text, voice, pitch, rate]).encode()).hexdigest()[:16]
    mp3, js = os.path.join(cache_dir, key + ".mp3"), os.path.join(cache_dir, key + ".json")
    if not (os.path.exists(mp3) and os.path.exists(js)):
        last = None
        for attempt in range(4):
            try:
                audio, words = asyncio.run(_edge_tts(text, voice, pitch, rate))
                if not audio:
                    raise RuntimeError("пустой ответ edge-tts")
                break
            except Exception as e:  # noqa
                last = e
                time.sleep(1.5 * (attempt + 1))
        else:
            sys.exit(f"edge-tts не ответил: {last}")
        with open(mp3, "wb") as f:
            f.write(audio)
        with open(js, "w", encoding="utf-8") as f:
            json.dump(words, f, ensure_ascii=False)
    with open(js, encoding="utf-8") as f:
        words = json.load(f)
    samples = decode_audio(mp3)
    # обрезаем тишину по краям по границам слов
    if words:
        s = max(0.0, words[0]["start"] - 0.03)
        e = min(len(samples) / SR, words[-1]["end"] + 0.12)
    else:
        nz = np.where(np.abs(samples) > 0.01)[0]
        s = nz[0] / SR if len(nz) else 0
        e = nz[-1] / SR + 0.1 if len(nz) else len(samples) / SR
    clip = samples[int(s * SR):int(e * SR)]
    for w in words:
        w["start"] -= s
        w["end"] -= s
    return compress_silences(clip, words)


def compress_silences(clip, words, max_gap=MAX_INNER_PAUSE, keep=KEEP_INNER_PAUSE):
    """Сжимает длинные паузы внутри фразы (jump-cut): речь звучит бодрее."""
    hop = int(0.01 * SR)
    n = len(clip) // hop
    if n < 10:
        return clip, words
    rms = np.sqrt(np.mean(clip[:n * hop].reshape(n, hop) ** 2, axis=1))
    silent = rms < max(0.004, 0.06 * float(np.percentile(rms, 95)))
    cuts = []  # (start_sample, end_sample) — что вырезаем
    i = 0
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            if i > 0 and j < n and (j - i) * 0.01 > max_gap:
                a = i * hop + int(keep / 2 * SR)
                b = j * hop - int(keep / 2 * SR)
                if b > a:
                    cuts.append((a, b))
            i = j
        else:
            i += 1
    if not cuts:
        return clip, words
    parts, last = [], 0
    for a, b in cuts:
        parts.append(clip[last:a])
        last = b
    parts.append(clip[last:])
    # короткие кроссфейды на стыках, чтобы не щёлкало
    out = parts[0]
    xf = int(0.006 * SR)
    for pt in parts[1:]:
        if len(out) > xf and len(pt) > xf:
            ramp = np.linspace(0, 1, xf, dtype=np.float32)
            mid = out[-xf:] * (1 - ramp) + pt[:xf] * ramp
            out = np.concatenate([out[:-xf], mid, pt[xf:]])
        else:
            out = np.concatenate([out, pt])

    def remap(t):
        smp = t * SR
        removed = 0
        for a, b in cuts:
            if smp >= b:
                removed += b - a
            elif smp > a:
                removed += smp - a
        return (smp - removed) / SR

    for w in words:
        w["start"], w["end"] = remap(w["start"]), remap(w["end"])
    return out.astype(np.float32), words


def _norm(s):
    return re.sub(r"[^\w]", "", s.lower().replace("ё", "е"))


def align_words(text, words, dur):
    """Привязка отображаемых слов (с пунктуацией) к таймингам edge-tts."""
    tokens = text.split()
    result = []
    norms = [_norm(t) for t in tokens]
    wi = 0
    ok = True
    for tok, n in zip(tokens, norms):
        if not n:
            result.append([tok, None])
            continue
        if wi < len(words) and (_norm(words[wi]["text"]) == n or n.startswith(_norm(words[wi]["text"]))
                                or _norm(words[wi]["text"]).startswith(n)):
            st = words[wi]["start"]
            # токен может распасться на несколько границ (например «20-го»)
            wi += 1
            acc = _norm(words[wi - 1]["text"])
            while wi < len(words) and len(acc) < len(n) and n.startswith(acc + _norm(words[wi]["text"])):
                acc += _norm(words[wi]["text"])
                wi += 1
            result.append([tok, st])
        elif wi < len(words):
            result.append([tok, words[wi]["start"]])
            wi += 1
        else:
            ok = False
            result.append([tok, None])
    if not ok or not words or all(r[1] is None for r in result):
        # равномерно по длине символов
        total = sum(max(1, len(t)) for t in tokens)
        acc = 0
        result = []
        for t in tokens:
            result.append([t, dur * 0.9 * acc / total])
            acc += max(1, len(t))
    # заполняем пропуски
    prev = 0.0
    for r in result:
        if r[1] is None:
            r[1] = prev
        prev = r[1]
    return [(t, s) for t, s in result]


# ----------------------------------------------------------------------------
# План (тайминги)
# ----------------------------------------------------------------------------
def build_plan(script, cache_dir, fit=True):
    chars = script["characters"]
    msgs = script["messages"]
    rate_boost = 0
    voices = None

    def synth(boost):
        from concurrent.futures import ThreadPoolExecutor

        def one(m):
            c = chars[m["who"]]
            rate = shift_percent(c.get("rate", "+0%"), boost)
            return tts(m.get("tts", m["text"]), c["voice"], c.get("pitch", "+0Hz"), rate, cache_dir)

        with ThreadPoolExecutor(6) as ex:
            return list(ex.map(one, msgs))

    def timing(voices, pscale):
        t = HOOK_DUR + 0.55
        items = []
        prev_end, prev_appear = None, None
        for i, m in enumerate(msgs):
            clip, words = voices[i]
            dur = len(clip) / SR
            typing = clamp(0.35 + 0.012 * len(m["text"]), TYPING_MIN, TYPING_MAX)
            if i == 0:
                appear = t
                typing_start = HOOK_DUR - 0.05
            else:
                appear = prev_end + msgs[i - 1]["pause_after"] * pscale + TYPING_TAIL
                typing_start = max(prev_appear + 0.45, appear - typing)
            v_start = appear + VOICE_DELAY
            v_end = v_start + dur
            items.append(dict(typing_start=typing_start, appear=appear, voice_start=v_start,
                              voice_end=v_end))
            prev_end, prev_appear = v_end, appear
        total = prev_end + msgs[-1]["pause_after"] * pscale + 0.25 + OUTRO_DUR
        return items, total

    voices = synth(0)
    pscale = 1.0
    items, total = timing(voices, pscale)

    def shrink_pauses(voices, goal):
        for ps in np.linspace(1.0, 0.6, 9):
            items, total = timing(voices, ps)
            if total <= goal:
                break
        return items, total, ps

    if fit and total > TARGET_MAX:
        goal = TARGET_MAX - 1.0
        items, total, pscale = shrink_pauses(voices, goal)
        tries = 0
        while total > goal and tries < 4 and rate_boost < 40:
            # длительность речи ~ 1/(1+rate): считаем нужное ускорение сразу
            vtot = sum(len(v[0]) for v in voices) / SR
            need = (total - goal) + 0.3
            f = max(0.5, (vtot - need) / vtot)
            rate_boost = int(math.ceil((1.0 + rate_boost / 100) / f * 100 - 100)) + 1
            log(f"  ролик длинноват ({total:.1f} с) — ускоряю речь на +{rate_boost}%")
            voices = synth(rate_boost)
            items, total, pscale = shrink_pauses(voices, goal)
            tries += 1
    elif fit and total < TARGET_MIN:
        for ps in np.linspace(1.0, 2.5, 31):
            items, total = timing(voices, ps)
            pscale = ps
            if total >= TARGET_MIN:
                break
    log(f"  длительность: {total:.2f} с (паузы x{pscale:.2f}, ускорение речи +{rate_boost}%)")

    plan_msgs = []
    for i, (m, it) in enumerate(zip(msgs, items)):
        clip, words = voices[i]
        dur = len(clip) / SR
        aligned = align_words(m["text"], words, dur)
        it.update(who=m["who"], text=m["text"],
                  words=[(tok, it["voice_start"] + st) for tok, st in aligned],
                  clock=add_minutes(script["start_time"], i // 4))
        plan_msgs.append(it)
    plan = dict(total=total, messages=plan_msgs, characters=chars, contact=script["contact"],
                title=script["title"], outro=script["outro"], start_time=script["start_time"],
                outro_start=total - OUTRO_DUR)
    return plan, [v[0] for v in voices]


# ----------------------------------------------------------------------------
# Аудио: поп, бит, микс
# ----------------------------------------------------------------------------
def synth_pop(high=True):
    d = 0.09
    t = np.arange(int(d * SR)) / SR
    f0, f1 = (1350, 560) if high else (900, 380)
    f = f1 + (f0 - f1) * np.exp(-t * 55)
    ph = 2 * np.pi * np.cumsum(f) / SR
    env = (1 - np.exp(-t * 900)) * np.exp(-t * 48)
    x = np.sin(ph) * env
    rng = np.random.default_rng(1)
    x += rng.standard_normal(len(t)) * np.exp(-t * 400) * 0.15
    return (x / np.max(np.abs(x))).astype(np.float32)


def synth_beat(total, bpm=96, seed=7):
    rng = np.random.default_rng(seed)
    n = int(total * SR) + SR
    out = np.zeros(n, np.float32)
    step = 60 / bpm / 4  # 16-е

    def kick():
        t = np.arange(int(0.4 * SR)) / SR
        f = 48 + 95 * np.exp(-t * 32)
        return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 8)).astype(np.float32)

    def snare():
        t = np.arange(int(0.25 * SR)) / SR
        nz = rng.standard_normal(len(t))
        nz = np.diff(nz, prepend=0)  # грубый ВЧ-фильтр
        x = nz * np.exp(-t * 20) * 0.35 + np.sin(2 * np.pi * 185 * t) * np.exp(-t * 28) * 0.6
        return x.astype(np.float32)

    def hat(open_=False):
        t = np.arange(int((0.18 if open_ else 0.05) * SR)) / SR
        nz = np.diff(rng.standard_normal(len(t)), prepend=0)
        nz = np.diff(nz, prepend=0)
        return (nz * np.exp(-t * (18 if open_ else 70)) * 0.12).astype(np.float32)

    def tone(freq, dur, decay, harm=0.25):
        t = np.arange(int(dur * SR)) / SR
        x = np.sin(2 * np.pi * freq * t) + harm * np.sin(4 * np.pi * freq * t)
        env = (1 - np.exp(-t * 200)) * np.exp(-t * decay)
        return (x * env).astype(np.float32)

    K, S, Hh, Ho = kick(), snare(), hat(), hat(True)

    def add(sig, pos, g):
        i = int(pos * SR)
        if i >= n:
            return
        j = min(n, i + len(sig))
        out[i:j] += sig[:j - i] * g

    # Am - F - C - G
    roots = [110.0, 87.31, 130.81, 98.0]
    chords = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63],
              [261.63, 329.63, 392.0], [196.0, 246.94, 293.66]]
    bars = int(total / (step * 16)) + 2
    for b in range(bars):
        t0 = b * step * 16
        root, chord = roots[b % 4], chords[b % 4]
        for note in chord:
            add(tone(note, step * 16, 1.6, 0.15), t0, 0.07)
        for s in range(16):
            ts = t0 + s * step + (0.018 if s % 2 else 0)  # лёгкий свинг
            if s in (0, 7, 10):
                add(K, ts, 0.9)
                add(tone(root, step * 3, 6), ts, 0.35)
            if s in (4, 12):
                add(S, ts, 0.55)
            if s % 2 == 0:
                add(Hh, ts, 0.9 if s % 4 == 2 else 0.6)
            if s == 14:
                add(Ho, ts, 0.5)
    out = out[:int(total * SR)]
    out /= max(1e-6, np.max(np.abs(out)))
    return out


def build_audio(plan, clips, path):
    total = plan["total"]
    n = int(total * SR)
    voice = np.zeros(n, np.float32)
    fx = np.zeros(n, np.float32)
    duck = np.zeros(n, np.float32)

    def place(buf, sig, t, g=1.0):
        i = int(t * SR)
        if i >= n:
            return
        j = min(n, i + len(sig))
        buf[i:j] += sig[:j - i] * g

    pop_hi, pop_lo = synth_pop(True), synth_pop(False)
    peak = max(float(np.max(np.abs(c))) for c in clips) or 1.0
    for m, clip in zip(plan["messages"], clips):
        place(voice, clip / peak * 0.9, m["voice_start"], VOICE_GAIN)
        side = plan["characters"][m["who"]].get("side", "left")
        place(fx, pop_hi if side == "right" else pop_lo, m["appear"], POP_GAIN)
        i, j = int(m["voice_start"] * SR), int(m["voice_end"] * SR)
        duck[i:j] = 1.0
    place(fx, pop_lo, 0.02, POP_GAIN * 1.2)                     # появление заголовка
    place(fx, pop_hi, plan["outro_start"] + 0.05, POP_GAIN * 1.2)  # плашка подписки

    # сглаживаем огибающую дакинга (~120 мс)
    k = int(0.12 * SR)
    kern = np.ones(k, np.float32) / k
    duck = np.convolve(duck, kern, mode="same")
    beat = synth_beat(total) * BEAT_GAIN
    beat *= (1 - duck * (1 - BEAT_DUCK))
    fade_in, fade_out = int(0.3 * SR), int(0.9 * SR)
    beat[:fade_in] *= np.linspace(0, 1, fade_in)
    beat[-fade_out:] *= np.linspace(1, 0, fade_out)

    mix = voice + fx + beat
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)   # мягкий лимитер
    pcm = (np.clip(mix, -1, 1) * 32000).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ----------------------------------------------------------------------------
# Видео
# ----------------------------------------------------------------------------
class Renderer:
    def __init__(self, plan):
        self.p = plan
        self.chars = plan["characters"]
        self.msgs = plan["messages"]
        self.f_msg = font("regular", MSG_FONT_SIZE)
        self.f_small = font("medium", 26)
        self._build_static()
        self._layout_messages()
        self._build_scroll()
        self._sub_cache = {}
        self._build_overlays()

    # ---------- статичные слои ----------
    def _build_static(self):
        base = Image.new("RGB", (W, H), hex2rgb(THEME["bg_bottom"]))
        d = ImageDraw.Draw(base)
        # статус-бар
        d.rectangle([0, 0, W, CHAT_Y], fill=hex2rgb(THEME["bar_bg"]))
        d.text((56, STATUS_H // 2 + 4), self.msgs[-1]["clock"] if self.msgs else self.p["start_time"], font=font("semibold", 30),
               fill=hex2rgb(THEME["text"]), anchor="lm")
        # сигнал + батарея
        x = W - 200
        for i in range(4):
            hgt = 8 + i * 5
            d.rounded_rectangle([x + i * 11, 44 - hgt, x + i * 11 + 7, 44], radius=2, fill="#FFFFFF")
        d.rounded_rectangle([W - 120, 22, W - 64, 46], radius=6, outline="#FFFFFF", width=3)
        d.rounded_rectangle([W - 115, 27, W - 82, 41], radius=3, fill="#FFFFFF")
        d.rounded_rectangle([W - 61, 30, W - 56, 38], radius=2, fill="#FFFFFF")
        # шапка
        cy = HEADER_Y + HEADER_H // 2
        d.line([(58, cy - 22), (38, cy), (58, cy + 22)], fill=hex2rgb(THEME["typing_status"]), width=6,
               joint="curve")
        contact = self.chars[self.p["contact"]]
        av = self._avatar(contact, 100)
        base.paste(av, (84, cy - 50), av)
        d.text((210, cy - 22), contact["name"], font=font("semibold", 44),
               fill=hex2rgb(THEME["text"]), anchor="lm")
        # иконки справа: «звонок» (трубка упрощённо) и меню
        for k in range(3):
            d.ellipse([W - 56, cy - 26 + k * 22, W - 46, cy - 16 + k * 22], fill=hex2rgb(THEME["muted"]))
        cam_x = W - 170
        d.rounded_rectangle([cam_x, cy - 18, cam_x + 50, cy + 18], radius=8, outline=hex2rgb(THEME["muted"]),
                            width=4)
        d.polygon([(cam_x + 54, cy - 4), (cam_x + 74, cy - 16), (cam_x + 74, cy + 16), (cam_x + 54, cy + 4)],
                  fill=hex2rgb(THEME["muted"]))
        d.line([(0, CHAT_Y - 1), (W, CHAT_Y - 1)], fill=hex2rgb(THEME["separator"]), width=2)
        # строка ввода
        d.rectangle([0, INPUT_Y, W, INPUT_Y + INPUT_H], fill=hex2rgb(THEME["bar_bg"]))
        d.line([(0, INPUT_Y), (W, INPUT_Y)], fill=hex2rgb(THEME["separator"]), width=2)
        icy = INPUT_Y + INPUT_H // 2
        d.line([(48, icy), (84, icy)], fill=hex2rgb(THEME["muted"]), width=5)
        d.line([(66, icy - 18), (66, icy + 18)], fill=hex2rgb(THEME["muted"]), width=5)
        self.field_box = (112, icy - 40, W - 140, icy + 40)
        d.rounded_rectangle(self.field_box, radius=40, fill=hex2rgb(THEME["input_bg"]))
        self.placeholder_xy = (self.field_box[0] + 34, icy)
        d.text(self.placeholder_xy, "Сообщение", font=font("regular", 38), fill="#6B7080", anchor="lm")
        bx = W - 72
        btn = rounded_mask(84, 84, 42)
        bimg = Image.new("RGBA", (84, 84), hex2rgb(THEME["send_btn"]) + (255,))
        bimg.putalpha(btn)
        base.paste(bimg, (bx - 42, icy - 42), bimg)
        d.polygon([(bx - 14, icy - 20), (bx + 20, icy), (bx - 14, icy + 20), (bx - 6, icy)], fill="#FFFFFF")
        # нижняя панель под субтитры — мягкий градиент
        lower = gradient(W, H - INPUT_Y - INPUT_H, "#0D0E14", "#07080B", diagonal=False)
        base.paste(lower, (0, INPUT_Y + INPUT_H))
        self.base = base

        # фон чата: градиент + узор из точек
        bg = gradient(W, CHAT_H, THEME["bg_top"], THEME["bg_bottom"], diagonal=False)
        bd = ImageDraw.Draw(bg)
        pc = hex2rgb(THEME["pattern"])
        for yy in range(20, CHAT_H, 56):
            off = 28 if (yy // 56) % 2 else 0
            for xx in range(20 + off, W, 56):
                bd.ellipse([xx - 2, yy - 2, xx + 2, yy + 2], fill=pc)
        self.chat_bg = bg

        # статусы
        self.f_status = font("regular", 32)
        self.status_xy = (210, cy + 26)

    def _avatar(self, c, size):
        m = rounded_mask(size, size, size // 2)
        col = c.get("avatar", "#888888")
        light = tuple(min(255, v + 50) for v in hex2rgb(col))
        g = gradient(size, size, "#%02x%02x%02x" % light, col)
        g = g.convert("RGBA")
        g.putalpha(m)
        d = ImageDraw.Draw(g)
        d.text((size / 2, size / 2 + 2), c["name"][:1].upper(), font=font("bold", int(size * 0.46)),
               fill="#FFFFFF", anchor="mm")
        return g

    # ---------- пузыри ----------
    def _bubble(self, who, text):
        c = self.chars[who]
        right = c.get("side") == "right"
        lines = wrap_text(text, self.f_msg, BUBBLE_MAX_W - 2 * PAD_X)
        asc, desc = self.f_msg.getmetrics()
        lh = int(MSG_FONT_SIZE * 1.3)
        tw = max(self.f_msg.getlength(l) for l in lines)
        bw = int(max(tw + 2 * PAD_X, 2 * RADIUS + 10))
        bh = int(PAD_Y * 2 + asc + desc + (len(lines) - 1) * lh)
        mask = rounded_mask(bw, bh, RADIUS, "br" if right else "bl")
        col = c.get("bubble", ["#2B2E38", "#2B2E38"])
        if isinstance(col, str):
            col = [col, col]
        img = gradient(bw, bh, col[0], col[1]).convert("RGBA")
        img.putalpha(mask)
        d = ImageDraw.Draw(img)
        for k, l in enumerate(lines):
            d.text((PAD_X, PAD_Y + asc + k * lh), l, font=self.f_msg, fill=hex2rgb(THEME["text"]), anchor="ls")
        return img

    def _typing_bubble(self, who):
        c = self.chars[who]
        right = c.get("side") == "right"
        bw, bh = 150, 94
        col = c.get("bubble", ["#2B2E38", "#2B2E38"])
        if isinstance(col, str):
            col = [col, col]
        img = gradient(bw, bh, col[0], col[1]).convert("RGBA")
        img.putalpha(rounded_mask(bw, bh, RADIUS, "br" if right else "bl"))
        return img

    def _layout_messages(self):
        y = 16
        self.items = []
        prev_who = None
        self.typing_imgs = {k: self._typing_bubble(k) for k in self.chars}
        self.checks_blue = draw_checks(True, hex2rgb(THEME["receipt_blue"]), 1.3)
        self.checks_grey = draw_checks(False, hex2rgb(THEME["receipt_grey"]), 1.3)
        for m in self.msgs:
            if prev_who is not None:
                y += GAP_SAME if m["who"] == prev_who else GAP_OTHER
            img = self._bubble(m["who"], m["text"])
            right = self.chars[m["who"]].get("side") == "right"
            x = W - MARGIN - img.width if right else MARGIN
            tx = self.typing_imgs[m["who"]]
            typing_x = W - MARGIN - tx.width if right else MARGIN
            # время под пузырём
            clock = Image.new("RGBA", (120, RECEIPT_H), (0, 0, 0, 0))
            cd = ImageDraw.Draw(clock)
            cd.text((120 if right else 0, RECEIPT_H // 2), m["clock"], font=self.f_small,
                    fill=hex2rgb(THEME["muted"]), anchor="rm" if right else "lm")
            self.items.append(dict(m=m, img=img, x=x, y=y, h=img.height + RECEIPT_H, right=right,
                                   typing_x=typing_x, clock=clock))
            y += img.height + RECEIPT_H
            prev_who = m["who"]

    def _build_scroll(self):
        events = [(0.0, 0.0)]

        def target(bottom):
            return max(0.0, bottom + BOTTOM_PAD - CHAT_H)

        for it in self.items:
            m = it["m"]
            events.append((m["typing_start"], target(it["y"] + self.typing_imgs[m["who"]].height)))
            events.append((m["appear"], target(it["y"] + it["h"])))
        events.sort(key=lambda e: e[0])
        segs = []
        cur = 0.0
        for t, tgt in events:
            start_val = self._scroll_from(segs, t) if segs else cur
            segs.append((t, start_val, tgt))
        self.scroll_segs = segs

    @staticmethod
    def _scroll_from(segs, t):
        t0, a, b = segs[-1]
        k = ease_out_cubic((t - t0) / SCROLL_ANIM)
        return a + (b - a) * k

    def scroll_at(self, t):
        seg = self.scroll_segs[0]
        for s in self.scroll_segs:
            if s[0] <= t:
                seg = s
            else:
                break
        t0, a, b = seg
        return a + (b - a) * ease_out_cubic((t - t0) / SCROLL_ANIM)

    # ---------- оверлеи ----------
    def _build_overlays(self):
        # заголовок-крючок
        title = self.p.get("title") or ""
        self.hook_img = self._big_text_card(title) if title else None
        self.outro_img = self._outro_card(self.p.get("outro") or "") if self.p.get("outro") else None

    def _rich_lines(self, text, fnt, max_w):
        """Разбивка с выделением текста в «ёлочках» / "кавычках" акцентным цветом."""
        tokens = text.split()
        flags, inside = [], False
        for t in tokens:
            starts = t[0] in "«\"“"
            if starts:
                inside = True
            flags.append(inside)
            if t[-1] in "»\"”" and (not starts or len(t) > 1):
                inside = False
        lines, cur, curf = [], [], []
        for t, f in zip(tokens, flags):
            test = " ".join(cur + [t])
            if cur and fnt.getlength(test) > max_w:
                lines.append(list(zip(cur, curf)))
                cur, curf = [], []
            cur.append(t)
            curf.append(f)
        if cur:
            lines.append(list(zip(cur, curf)))
        return lines

    def _big_text_card(self, text):
        fnt = font("black", 96)
        lines = self._rich_lines(text, fnt, 920)
        lh = 116
        h = lh * len(lines) + 40
        img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        space = fnt.getlength(" ")
        for k, line in enumerate(lines):
            lw = sum(fnt.getlength(t) for t, _ in line) + space * (len(line) - 1)
            x = (W - lw) / 2
            for t, accent in line:
                col = THEME["hook_accent"] if accent else THEME["text"]
                d.text((x, 20 + k * lh + lh / 2), t, font=fnt, fill=col, anchor="lm",
                       stroke_width=8, stroke_fill="#000000")
                x += fnt.getlength(t) + space
        return img

    def _outro_card(self, text):
        # «Подписывайся на» + название канала
        m = re.match(r"\s*(.*?)\s*([«\"“].*[»\"”])\s*$", text)
        top, name = (m.group(1), m.group(2)) if m else ("", text)
        cw = 940
        f1, f2 = font("bold", 50), font("black", 66)
        name_lines = wrap_text(name, f2, cw - 100)
        ch = 150 + 82 * len(name_lines) + (70 if top else 0)
        card = gradient(cw, ch, *THEME["outro_grad"]).convert("RGBA")
        card.putalpha(rounded_mask(cw, ch, 48))
        d = ImageDraw.Draw(card)
        y = 66
        icon = draw_checks(True, hex2rgb(THEME["receipt_blue"]), scale=2.4)
        bg = Image.new("RGBA", (icon.width + 40, icon.height + 26), (0, 0, 0, 0))
        ImageDraw.Draw(bg).rounded_rectangle([0, 0, bg.width - 1, bg.height - 1], radius=bg.height // 2,
                                             fill=(255, 255, 255, 235))
        bg.paste(icon, (20, 13), icon)
        card.paste(bg, ((cw - bg.width) // 2, 28), bg)
        y = 28 + bg.height + 40
        if top:
            d.text((cw / 2, y), top, font=f1, fill="#FFFFFF", anchor="mm")
            y += 72
        for l in name_lines:
            d.text((cw / 2, y), l, font=f2, fill="#FFFFFF", anchor="mm")
            y += 82
        return card

    # ---------- субтитры ----------
    def _chunks(self, words):
        """Режем по предложениям, внутри — на равные куски до 4 слов / одной строки."""
        fnt = font("black", 84)
        sentences, cur = [], []
        for i, (tok, _) in enumerate(words):
            cur.append(i)
            if re.search(r"[.?!…]»?$", tok) and not re.match(r"^[.…]+$", tok) and not tok.endswith("..."):
                sentences.append(cur)
                cur = []
        if cur:
            sentences.append(cur)
        chunks = []
        for sent in sentences:
            n = len(sent)
            width = fnt.getlength(" ".join(words[j][0] for j in sent))
            k = max(math.ceil(n / 4), math.ceil(width / 900))
            k = min(k, n)
            base, extra = divmod(n, k)
            pos = 0
            for c in range(k):
                size = base + (1 if c < extra else 0)
                chunks.append(sent[pos:pos + size])
                pos += size
        return chunks

    def _sub_image(self, mi, chunk_idx, active):
        key = (mi, chunk_idx, active)
        if key in self._sub_cache:
            return self._sub_cache[key]
        m = self.msgs[mi]
        chunk = self._subs[mi][chunk_idx]
        fnt = font("black", 84)
        toks = [m["words"][j][0] for j in chunk]
        space = fnt.getlength(" ")
        # перенос строк
        lines, cur = [], []
        for idx, t in zip(chunk, toks):
            test = " ".join([m["words"][j][0] for j in cur] + [t])
            if cur and fnt.getlength(test) > 940:
                lines.append(cur)
                cur = []
            cur.append(idx)
        if cur:
            lines.append(cur)
        lh = 104
        c = self.chars[m["who"]]
        tag_f = font("extrabold", 30)
        tag_text = c["name"].upper()
        tag_w = int(tag_f.getlength(tag_text) + 40)
        img = Image.new("RGBA", (W, 70 + lh * len(lines) + 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # плашка с именем говорящей
        tx = (W - tag_w) // 2
        d.rounded_rectangle([tx, 0, tx + tag_w, 50], radius=25, fill=hex2rgb(c.get("avatar", "#888888")))
        d.text((W / 2, 26), tag_text, font=tag_f, fill="#FFFFFF", anchor="mm")
        for k, line in enumerate(lines):
            lw = sum(fnt.getlength(m["words"][j][0]) for j in line) + space * (len(line) - 1)
            x = (W - lw) / 2
            for j in line:
                t = m["words"][j][0]
                col = THEME["sub_highlight"] if j == active else THEME["sub_text"]
                d.text((x, 70 + k * lh + lh / 2), t, font=fnt, fill=col, anchor="lm",
                       stroke_width=7, stroke_fill="#000000")
                x += fnt.getlength(t) + space
        self._sub_cache[key] = img
        return img

    def _subtitle(self, frame, t):
        if not hasattr(self, "_subs"):
            self._subs = [self._chunks(m["words"]) for m in self.msgs]
        for mi, m in enumerate(self.msgs):
            if m["voice_start"] - 0.02 <= t <= m["voice_end"] + 0.18:
                words = m["words"]
                chunks = self._subs[mi]
                ci = 0
                for k, ch in enumerate(chunks):
                    if words[ch[0]][1] <= t + 0.02:
                        ci = k
                active = None
                for j in chunks[ci]:
                    if words[j][1] <= t + 0.02:
                        active = j
                if active is None:
                    active = chunks[ci][0]
                img = self._sub_image(mi, ci, active)
                chunk_start = max(m["voice_start"], words[chunks[ci][0]][1])
                p = ease_out_back((t - chunk_start + 0.02) / 0.16)
                y = SUB_TOP
                if p < 0.999:
                    s = 0.85 + 0.15 * p
                    sw, sh = max(1, int(img.width * s)), max(1, int(img.height * s))
                    sc = img.resize((sw, sh), Image.BILINEAR)
                    paste_rgba(frame, sc, (W - sw) / 2, y + (img.height - sh) / 2, clamp(p, 0, 1))
                else:
                    fade = clamp((m["voice_end"] + 0.18 - t) / 0.12, 0, 1)
                    paste_rgba(frame, img, 0, y, fade)
                return

    # ---------- кадр ----------
    def frame(self, t):
        frame = self.base.copy()
        chat = self.chat_bg.copy()
        scroll = self.scroll_at(t)
        contact = self.p["contact"]
        typing_who = None
        typing_msg = None

        for it in self.items:
            m = it["m"]
            if t < m["typing_start"]:
                break
            if t < m["appear"]:
                # анимация «печатает»
                typing_who, typing_msg = m["who"], m
                img = self.typing_imgs[m["who"]]
                p = ease_out_back((t - m["typing_start"]) / 0.18)
                ty = it["y"] - scroll
                tb = img.copy()
                d = ImageDraw.Draw(tb)
                dot_col = (255, 255, 255)
                for k in range(3):
                    ph = (t - m["typing_start"]) * 2 * math.pi * 1.7 - k * 0.9
                    off = -9 * max(0.0, math.sin(ph))
                    a = int(140 + 115 * max(0.0, math.sin(ph)))
                    cx = 45 + k * 30
                    cy = tb.height / 2 + off
                    d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=dot_col + (a,))
                s = 0.7 + 0.3 * p
                sw, shh = max(1, int(tb.width * s)), max(1, int(tb.height * s))
                tb = tb.resize((sw, shh), Image.BILINEAR)
                x = it["typing_x"] + (tb.width * 0 if not it["right"] else (img.width - sw))
                paste_rgba(chat, tb, x, ty + (img.height - shh), clamp(p, 0, 1))
                break
            # сообщение
            ys = it["y"] - scroll
            if ys > CHAT_H or ys + it["h"] < -10:
                continue
            k = (t - m["appear"]) / APPEAR_ANIM
            img = it["img"]
            if k < 1:
                p = ease_out_back(k, 1.2)
                s = 0.86 + 0.14 * p
                sw, shh = max(1, int(img.width * s)), max(1, int(img.height * s))
                sc = img.resize((sw, shh), Image.BILINEAR)
                dx = (1 - ease_out_cubic(k)) * 70 * (1 if it["right"] else -1)
                bx = (it["x"] + img.width - sw if it["right"] else it["x"]) + dx
                by = ys + (img.height - shh) + (1 - ease_out_cubic(k)) * 30
                paste_rgba(chat, sc, bx, by, clamp(ease_out_cubic(k) * 1.5, 0, 1))
            else:
                paste_rgba(chat, img, it["x"], ys)
            # время + галочки
            ra = clamp((t - m["appear"] - 0.12) / 0.2, 0, 1)
            ry = ys + img.height
            if it["right"]:
                read = t - m["appear"] > 0.55
                chk = self.checks_blue if read else self.checks_grey
                cx = W - MARGIN - chk.width
                paste_rgba(chat, chk, cx, ry + (RECEIPT_H - chk.height) / 2, ra)
                paste_rgba(chat, it["clock"], cx - 8 - it["clock"].width, ry, ra)
            else:
                paste_rgba(chat, it["clock"], MARGIN + 6, ry, ra)

        frame.paste(chat, (0, CHAT_Y))
        d = ImageDraw.Draw(frame)

        # статус собеседницы в шапке
        if typing_who == contact:
            n = int(t * 3) % 3 + 1
            d.text(self.status_xy, "печатает" + "." * n, font=self.f_status,
                   fill=hex2rgb(THEME["typing_status"]), anchor="lm")
        else:
            d.text(self.status_xy, "в сети", font=self.f_status, fill=hex2rgb(THEME["muted"]), anchor="lm")

        # строка ввода: «наша» героиня набирает текст
        if typing_msg is not None and self.chars[typing_who].get("side") == "right":
            prog = clamp((t - typing_msg["typing_start"]) / max(0.1, typing_msg["appear"] -
                                                                typing_msg["typing_start"] - 0.05), 0, 1)
            txt = typing_msg["text"][:int(len(typing_msg["text"]) * prog)]
            fb = self.field_box
            d.rounded_rectangle(fb, radius=40, fill=hex2rgb(THEME["input_bg"]))
            f = font("regular", 38)
            maxw = fb[2] - fb[0] - 80
            while txt and f.getlength(txt) > maxw:
                txt = txt[1:]
            d.text(self.placeholder_xy, txt, font=f, fill="#FFFFFF", anchor="lm")
            cxp = self.placeholder_xy[0] + f.getlength(txt) + 4
            if int(t * 4) % 2 == 0:
                d.line([(cxp, self.placeholder_xy[1] - 22), (cxp, self.placeholder_xy[1] + 22)],
                       fill=hex2rgb(THEME["typing_status"]), width=3)

        # субтитры
        self._subtitle(frame, t)

        # заголовок-крючок
        if self.hook_img is not None and t < HOOK_DUR + 0.2:
            dim = clamp(1 - (t - HOOK_DUR + 0.1) / 0.25, 0, 1)
            if dim > 0:
                ov = Image.new("RGBA", (W, H), (0, 0, 0, int(150 * dim)))
                frame.paste(ov, (0, 0), ov)
                p = ease_out_back(t / 0.22)
                img = self.hook_img
                s = 0.75 + 0.25 * p
                sw, shh = int(img.width * s), int(img.height * s)
                sc = img.resize((sw, shh), Image.BILINEAR) if s < 0.999 else img
                paste_rgba(frame, sc, (W - sw) / 2, 820 - shh / 2, dim * clamp(p * 2, 0, 1))

        # плашка подписки
        if self.outro_img is not None and t >= self.p["outro_start"]:
            k = t - self.p["outro_start"]
            ov = Image.new("RGBA", (W, H), (0, 0, 0, int(140 * clamp(k / 0.25, 0, 1))))
            frame.paste(ov, (0, 0), ov)
            p = ease_out_back(k / 0.38, 1.3)
            img = self.outro_img
            y = 760 - img.height / 2 + (1 - p) * 500
            paste_rgba(frame, img, (W - img.width) / 2, y, clamp(k / 0.15, 0, 1))
        return frame


def _render_segment(args):
    plan, f0, f1, path, crf, preset = args
    r = Renderer(plan)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-threads", "2", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(f0, f1):
        proc.stdin.write(r.frame(fi / FPS).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg (видео) завершился с ошибкой")
    return path


def render_video(plan, out_path, audio_path, workers, crf=19, preset="medium"):
    nframes = int(round(plan["total"] * FPS))
    tmp = tempfile.mkdtemp(prefix="chatvid_")
    try:
        workers = max(1, workers)
        bounds = np.linspace(0, nframes, workers + 1).astype(int)
        jobs = [(plan, int(bounds[i]), int(bounds[i + 1]), os.path.join(tmp, f"seg{i:02d}.mp4"), crf, preset)
                for i in range(workers) if bounds[i + 1] > bounds[i]]
        t0 = time.time()
        log(f"  кадров: {nframes}, процессов: {len(jobs)}")
        if len(jobs) == 1:
            segs = [_render_segment(jobs[0])]
        else:
            with mp.get_context("spawn").Pool(len(jobs)) as pool:
                segs = pool.map(_render_segment, jobs)
        log(f"  кадры готовы за {time.time() - t0:.0f} с")
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            for s in segs:
                f.write(f"file '{s}'\n")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-i", audio_path, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
                        out_path], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Видео-переписка для Shorts/TikTok/Reels")
    ap.add_argument("script", nargs="?", default="script.json")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--limit", type=int, default=0, help="взять только первые N реплик (пробная версия)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--no-fit", action="store_true", help="не подгонять длительность под 45–60 с")
    ap.add_argument("--frame", type=float, default=None, help="сохранить один кадр (сек) в PNG и выйти")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("Не найден ffmpeg. Установите его (apt install ffmpeg / brew install ffmpeg).")

    script = load_script(args.script)
    if args.limit:
        script["messages"] = script["messages"][:args.limit]
    cache = os.path.join(ROOT, ".cache", "tts")
    os.makedirs(cache, exist_ok=True)

    log("1/3 Озвучка (edge-tts)…")
    plan, clips = build_plan(script, cache, fit=not (args.no_fit or args.limit))

    if args.frame is not None:
        png = os.path.splitext(args.output)[0] + f"_{args.frame:.2f}s.png"
        Renderer(plan).frame(args.frame).save(png)
        log(f"Кадр сохранён: {png}")
        return

    log("2/3 Звук (голос + поп + бит)…")
    tmpwav = os.path.join(tempfile.gettempdir(), f"chatvid_{os.getpid()}.wav")
    build_audio(plan, clips, tmpwav)
    log("3/3 Кадры и сборка…")
    try:
        render_video(plan, args.output, tmpwav, args.workers)
    finally:
        if os.path.exists(tmpwav):
            os.remove(tmpwav)
    log(f"Готово: {os.path.abspath(args.output)}  ({plan['total']:.1f} с)")


if __name__ == "__main__":
    main()
