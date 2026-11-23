#!/usr/bin/env python3
"""
Генератор вертикальных видео «фейковая переписка в мессенджере».

    python generate.py script.json                 -> output.mp4
    python generate.py script.json -o test.mp4 --limit 6
    python generate.py script.json --frames 1.5,10,30   (PNG-кадры для проверки)

Сюжет, имена, голоса, цвета и тексты меняются в script.json, код трогать не нужно.
Стек: Pillow (кадры) + edge-tts (озвучка) + numpy (звук) + ffmpeg (сборка).
"""
import argparse
import asyncio
import copy
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
import multiprocessing as mp

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 60
SR = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache", "tts")

# ----------------------------------------------------------------------------
# Настройки по умолчанию (любое поле можно переопределить в script.json → "config")
# ----------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "contact_name": "Мама",
    "contact_initial": None,            # None → первая буква имени
    "status_online": "в сети",
    "status_typing": "печатает",
    "clock_start": "21:47",
    "hook": "Когда мама пишет\n[«ты поел?»]",       # [ ] — выделение цветом
    "hook_duration": 1.0,
    "outro": "Подписывайся на\n[«Прочитано и проигнорировано»]",
    "outro_duration": 1.5,
    "knock_caption": "ТУК. ТУК. ТУК.",
    "knock_interval": 0.26,
    "blackout_duration": 0.5,
    "min_duration": 45,
    "max_duration": 60,
    "history": [],
    "voices": {
        "mom": {"voice": "ru-RU-SvetlanaNeural", "rate": "-10%", "pitch": "-2Hz", "volume": "+0%"},
        "son": {"voice": "ru-RU-DmitryNeural", "rate": "+0%", "pitch": "+0Hz", "volume": "+0%"},
    },
    "audio": {
        "voice_level": 0.85,
        "beat_volume": 0.17,
        "beat_bpm": 88,
        "beat_duck": 0.5,
        "pop_volume": 0.22,
        "knock_volume": 0.95,
    },
    "colors": {
        "bg_top": "#0B0D12",
        "bg_bottom": "#141823",
        "header": "#171A21",
        "header_border": "#262B36",
        "name": "#F4F5F7",
        "online": "#5ED37D",
        "typing_status": "#8AB4FF",
        "avatar_top": "#FF9A6B",
        "avatar_bottom": "#D9467A",
        "mom_bubble": "#262A33",
        "mom_text": "#F1F2F4",
        "mom_dots": "#9AA0AC",
        "son_bubble_top": "#FFC6A5",
        "son_bubble_bottom": "#FFA77E",
        "son_text": "#2A160C",
        "son_dots": "#8A5236",
        "ticks": "#3EA6FF",
        "meta": "#7D8494",
        "chip_bg": "#1E222B",
        "chip_text": "#9AA0AC",
        "input_field": "#232731",
        "input_text": "#F1F2F4",
        "placeholder": "#7C8290",
        "send_button": "#FFB38A",
        "subtitle": "#FFFFFF",
        "subtitle_highlight": "#FFE14D",
        "subtitle_stroke": "#000000",
        "hook_highlight": "#FFE14D",
        "outro_card": "#1B1F28",
        "outro_accent": "#FFB38A",
    },
}

# Геометрия экрана
STATUS_H = 64
HEADER_H = 250
VIEW_TOP = HEADER_H
VIEW_BOTTOM = 1200
PANEL_H = 118
SIDE = 36
SUB_CENTER_Y = 1450
BUBBLE_MAX_TEXT_W = 700
GAP = 20
META_H = 42
TYPING_W, TYPING_H = 156, 96


# ----------------------------------------------------------------------------
# Утилиты
# ----------------------------------------------------------------------------
def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out_cubic(x):
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ease_out_back(x, s=1.70158):
    x = clamp01(x) - 1
    return x * x * ((s + 1) * x + s) + 1


def vgradient(w, h, c1, c2):
    a = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    arr = np.array(c1, np.float32) * (1 - a) + np.array(c2, np.float32) * a
    arr = np.broadcast_to(arr, (h, w, 3)).astype(np.uint8)
    return Image.fromarray(np.ascontiguousarray(arr), "RGB")


def with_alpha(img, k):
    """Копия RGBA-картинки с прозрачностью, умноженной на k."""
    if k >= 0.999:
        return img
    out = img.copy()
    a = out.getchannel("A").point(lambda v: int(v * k))
    out.putalpha(a)
    return out


def check_tools():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"Не найден {tool}. Установите ffmpeg (apt install ffmpeg / brew install ffmpeg).")


# ----------------------------------------------------------------------------
# Шрифты
# ----------------------------------------------------------------------------
FONT_CANDIDATES = {
    "regular": ["Inter-Regular.otf", "Inter-Regular.ttf", "DejaVuSans.ttf", "Arial.ttf", "arial.ttf"],
    "medium": ["Inter-Medium.otf", "Inter-Medium.ttf", "DejaVuSans.ttf", "Arial.ttf", "arial.ttf"],
    "semibold": ["Inter-SemiBold.otf", "Inter-SemiBold.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"],
    "bold": ["Inter-Bold.otf", "Inter-Bold.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"],
    "black": ["InterDisplay-Black.otf", "Inter-Black.otf", "InterDisplay-ExtraBold.otf", "Inter-ExtraBold.otf",
              "DejaVuSans-Bold.ttf", "Arial Black.ttf", "ariblk.ttf"],
}
FONT_DIRS = [os.path.join(HERE, "fonts"), "/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/inter",
             "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts", "/Library/Fonts", "/System/Library/Fonts",
             os.path.expanduser("~/Library/Fonts"), "C:/Windows/Fonts"]
_font_cache, _font_path_cache = {}, {}


def _find_font(weight):
    if weight in _font_path_cache:
        return _font_path_cache[weight]
    for name in FONT_CANDIDATES[weight]:
        for d in FONT_DIRS:
            if not os.path.isdir(d):
                continue
            p = os.path.join(d, name)
            if os.path.exists(p):
                _font_path_cache[weight] = p
                return p
            for root, _, files in os.walk(d):
                if name in files:
                    _font_path_cache[weight] = os.path.join(root, name)
                    return _font_path_cache[weight]
    sys.exit("Не найден шрифт с кириллицей. Положите Inter-*.otf (или DejaVuSans.ttf) в папку fonts/.")


def font(weight, size):
    key = (weight, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(_find_font(weight), size)
    return _font_cache[key]


def wrap_words(words, fnt, max_w):
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        if cur and fnt.getlength(test) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


# ----------------------------------------------------------------------------
# Озвучка (edge-tts)
# ----------------------------------------------------------------------------
def _patch_edge_tts_ssl():
    """edge-tts использует свой certifi; за корпоративным/песочным прокси нужен системный CA."""
    try:
        import edge_tts.communicate as c
    except ImportError:
        sys.exit("Не установлен edge-tts: pip install -r requirements.txt")
    ca = next((p for p in (os.environ.get("SSL_CERT_FILE"), os.environ.get("REQUESTS_CA_BUNDLE"))
               if p and os.path.exists(p)), None)
    if ca and hasattr(c, "_SSL_CTX"):
        ctx = ssl.create_default_context(cafile=ca)
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except Exception:
            pass
        c._SSL_CTX = ctx


async def _tts_one(text, voice, rate, pitch, volume, sem):
    import edge_tts
    key = hashlib.sha1(json.dumps([text, voice, rate, pitch, volume]).encode()).hexdigest()[:20]
    mp3 = os.path.join(CACHE_DIR, key + ".mp3")
    meta = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(mp3) and os.path.exists(meta):
        return mp3, json.load(open(meta, encoding="utf-8"))
    async with sem:
        for attempt in range(6):
            try:
                com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume,
                                           boundary="WordBoundary")
                audio, words = bytearray(), []
                async for ch in com.stream():
                    if ch["type"] == "audio":
                        audio += ch["data"]
                    elif ch["type"] == "WordBoundary":
                        words.append([ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]])
                if not audio:
                    raise RuntimeError("пустой ответ")
                with open(mp3, "wb") as f:
                    f.write(audio)
                json.dump(words, open(meta, "w", encoding="utf-8"), ensure_ascii=False)
                return mp3, words
            except Exception as e:  # сеть / лимиты
                if attempt == 5:
                    raise RuntimeError(f"edge-tts не смог озвучить «{text}»: {e}")
                await asyncio.sleep(1.5 * (attempt + 1))


def synthesize_all(jobs):
    os.makedirs(CACHE_DIR, exist_ok=True)
    _patch_edge_tts_ssl()

    async def run():
        sem = asyncio.Semaphore(2)
        return await asyncio.gather(*[_tts_one(*j, sem) for j in jobs])

    return asyncio.run(run())


def decode_audio(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def trim_voice(x, words):
    """Убираем тишину по краям, сдвигаем тайминги слов."""
    idx = np.nonzero(np.abs(x) > 0.012)[0]
    if len(idx) == 0:
        return x, words
    a = max(0, idx[0] - int(0.02 * SR))
    b = min(len(x), idx[-1] + int(0.06 * SR))
    shift = a / SR
    return x[a:b].copy(), [[s - shift, e - shift, w] for s, e, w in words]


def align_words(text, boundaries, dur):
    """Сопоставляет слова текста с WordBoundary → список (word, start, end)."""
    tokens = text.split()
    norm = lambda s: re.sub(r"[^\w]", "", s.lower().replace("ё", "е"))
    bnd = [(s, e, norm(w)) for s, e, w in boundaries if norm(w)]
    out, j, ok = [], 0, True
    for tok in tokens:
        n = norm(tok)
        if not n:
            out.append([tok, None, None])
            continue
        found = None
        for k in range(j, min(j + 3, len(bnd))):
            if bnd[k][2] == n or bnd[k][2].startswith(n) or n.startswith(bnd[k][2]):
                found = k
                break
        if found is None:
            ok = False
            out.append([tok, None, None])
        else:
            out.append([tok, bnd[found][0], bnd[found][1]])
            j = found + 1
    if not ok or not any(o[1] is not None for o in out):
        # запасной вариант — равномерно по длине слов
        total = sum(max(1, len(t)) for t in tokens)
        t0 = 0.0
        out = []
        for tok in tokens:
            d = dur * max(1, len(tok)) / total
            out.append([tok, t0, t0 + d])
            t0 += d
    # слова без собственного тайминга (например «...») наследуют соседние
    for i, o in enumerate(out):
        if o[1] is None:
            nxt = next((p for p in out[i + 1:] if p[1] is not None), None)
            o[1] = o[2] = nxt[1] if nxt else dur
    return out


# ----------------------------------------------------------------------------
# Звук: поп, бит, тук-тук
# ----------------------------------------------------------------------------
def smooth(x, n):
    if n <= 1:
        return x
    k = np.ones(n, np.float32) / n
    return np.convolve(x, k, mode="same")


def make_pop(base=900.0):
    n = int(0.07 * SR)
    t = np.arange(n) / SR
    f = base * 0.45 + base * np.exp(-t * 55)
    ph = 2 * np.pi * np.cumsum(f) / SR
    y = np.sin(ph) * np.exp(-t * 55)
    y[: int(0.002 * SR)] *= np.linspace(0, 1, int(0.002 * SR))
    return (y / np.max(np.abs(y))).astype(np.float32)


def make_knock():
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    thump = np.sin(2 * np.pi * (78 + 40 * np.exp(-t * 40)) * t) * np.exp(-t * 22)
    body = 0.55 * np.sin(2 * np.pi * 168 * t) * np.exp(-t * 38)
    wood = 0.35 * np.sin(2 * np.pi * 410 * t) * np.exp(-t * 70)
    click = smooth(rng.standard_normal(n).astype(np.float32), 6) * np.exp(-t * 260) * 0.9
    y = thump + body + wood + click
    out = np.zeros(n + int(0.08 * SR), np.float32)
    out[:n] += y
    for d, g in ((0.023, 0.35), (0.047, 0.2), (0.071, 0.1)):  # немного «подъезда»
        o = int(d * SR)
        out[o:o + n] += g * y
    return out / np.max(np.abs(out))


def make_beat(duration, bpm, seed=3):
    n = int(duration * SR)
    out = np.zeros(n + SR, np.float32)
    rng = np.random.default_rng(seed)
    step = 60.0 / bpm / 4  # 16-е

    def env_sound(length, fn):
        t = np.arange(int(length * SR)) / SR
        return fn(t).astype(np.float32)

    kick = env_sound(0.4, lambda t: np.sin(2 * np.pi * np.cumsum(48 + 95 * np.exp(-t * 28)) / SR) * np.exp(-t * 8))
    noise = rng.standard_normal(int(0.25 * SR)).astype(np.float32)
    hp = noise - smooth(noise, 5)
    tt = np.arange(len(noise)) / SR
    snare = (0.6 * smooth(noise, 3) * np.exp(-tt * 18) + 0.4 * np.sin(2 * np.pi * 190 * tt) * np.exp(-tt * 30))
    hat = hp[: int(0.06 * SR)] * np.exp(-tt[: int(0.06 * SR)] * 70) * 0.35

    chords = [(110.0, [220.0, 261.63, 329.63]),   # Am
              (87.31, [174.61, 220.0, 261.63]),   # F
              (130.81, [196.0, 261.63, 329.63]),  # C
              (98.0, [196.0, 246.94, 293.66])]    # G
    bar_len = step * 16
    n_bars = int(duration / bar_len) + 2

    def put(sig, at, gain):
        i = int(at * SR)
        if i >= len(out):
            return
        m = min(len(sig), len(out) - i)
        out[i:i + m] += gain * sig[:m]

    for b in range(n_bars):
        t0 = b * bar_len
        root, notes = chords[b % 4]
        for s in (0, 6, 10):
            put(kick, t0 + s * step, 0.9)
        for s in (4, 12):
            put(snare, t0 + s * step, 0.45)
        for s in range(0, 16, 2):
            swing = step * 0.18 if (s // 2) % 2 else 0
            put(hat, t0 + s * step + swing, 0.5 if s % 4 else 0.3)
        # бас и мягкий пэд
        L = int(bar_len * SR)
        t = np.arange(L) / SR
        bass = np.sin(2 * np.pi * root * t) * (1 - np.exp(-t * 30)) * np.exp(-t * 0.9)
        pad = sum(np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 1.003 * t) for f in notes)
        pad *= np.minimum(1, t / 0.35) * np.minimum(1, (bar_len - t) / 0.2) * 0.07
        put((0.5 * bass + pad).astype(np.float32), t0, 1.0)
    out = smooth(out, 4)[:n]
    out /= max(1e-6, np.max(np.abs(out)))
    fade = int(0.6 * SR)
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    return out


# ----------------------------------------------------------------------------
# Сцена: таймлайн + заранее отрисованные элементы
# ----------------------------------------------------------------------------
class Scene:
    def __init__(self, cfg, messages, voices):
        self.cfg = cfg
        self.C = {k: rgb(v) for k, v in cfg["colors"].items()}
        self.messages = messages
        self.voices = voices          # список (samples, words) на каждую реплику
        self.build_timeline()
        self.prerender()

    # ---------------- таймлайн ----------------
    def build_timeline(self, extra_pause=0.0):
        cfg = self.cfg
        t = max(0.35, cfg["hook_duration"] - 0.55)
        self.tl = []
        for i, (m, (x, words)) in enumerate(zip(self.messages, self.voices)):
            dur = len(x) / SR
            typ = m.get("typing")
            if typ is None:
                L = len(m["text"])
                typ = min(1.3, max(0.6, 0.55 + 0.02 * L)) if m["who"] == "mom" else min(1.1, max(0.5, 0.45 + 0.015 * L))
            ts = t
            appear = ts + typ
            vs = appear + 0.10
            ve = vs + dur
            pause = float(m.get("pause_after", 0.3)) + (extra_pause if i < len(self.messages) - 1 else 0)
            end = ve + max(0.05, pause)
            self.tl.append(dict(ts=ts, typ=typ, appear=appear, vs=vs, ve=ve, end=end,
                                words=align_words(m["text"], words, dur)))
            t = end
        last = self.tl[-1]
        self.knock_start = last["ve"] + max(0.35, float(self.messages[-1].get("pause_after", 0.3)))
        ki = cfg["knock_interval"]
        self.knocks = [self.knock_start + k * ki for k in range(3)]
        self.blackout_start = self.knocks[-1] + 0.12
        self.outro_start = self.blackout_start + cfg["blackout_duration"]
        self.total = self.outro_start + cfg["outro_duration"]

    def fit_duration(self):
        lo, hi = self.cfg["min_duration"], self.cfg["max_duration"]
        n = max(1, len(self.messages) - 1)
        if self.total < lo:
            extra = (lo - self.total) / n
            self.build_timeline(extra)
            print(f"  ролик короче {lo} c — паузы между репликами увеличены на {extra:.2f} c")
        elif self.total > hi:
            extra = -min((self.total - hi) / n, 0.25)
            self.build_timeline(extra)
            print(f"  ролик длиннее {hi} c — паузы сокращены на {-extra:.2f} c")
        self.prerender_items()

    # ---------------- отрисовка заготовок ----------------
    def prerender(self):
        C = self.C
        self.bg = vgradient(W, H, C["bg_top"], C["bg_bottom"])
        d = ImageDraw.Draw(self.bg)
        for y in range(VIEW_TOP + 20, VIEW_BOTTOM, 56):           # еле заметный узор
            for x in range(28 + (y // 56 % 2) * 28, W, 56):
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=tuple(min(255, c + 9) for c in C["bg_top"]))
        self.black = Image.new("RGB", (W, H), (0, 0, 0))
        self.headers = {"online": self.render_header(None)}
        for k in range(4):
            self.headers[k] = self.render_header(k)
        self.panel_cache = {}
        self.sub_cache = {}
        self.typing_bubbles = {w: self.render_shape(TYPING_W, TYPING_H, w) for w in ("mom", "son")}
        self.dot = {}
        for w in ("mom", "son"):
            s = 3
            im = Image.new("RGBA", (22 * s, 22 * s), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse((0, 0, 22 * s - 1, 22 * s - 1), fill=C[w + "_dots"] + (255,))
            self.dot[w] = im.resize((22, 22), Image.LANCZOS)
        self.hook_img = self.render_card_text(self.cfg["hook"], 92, C["hook_highlight"], max_w=980)
        self.outro_img = self.render_outro()
        self.prerender_items()

    def render_header(self, typing_phase):
        C, cfg = self.C, self.cfg
        img = Image.new("RGB", (W, HEADER_H), C["header"])
        d = ImageDraw.Draw(img)
        d.line((0, HEADER_H - 2, W, HEADER_H - 2), fill=C["header_border"], width=2)
        # статус-бар
        d.text((48, STATUS_H // 2 + 6), cfg["clock_start"], font=font("semibold", 32), fill=C["name"], anchor="lm")
        bx = W - 60 - 54
        d.rounded_rectangle((bx, 26, bx + 54, 52), radius=7, outline=C["name"], width=3)
        d.rounded_rectangle((bx + 5, 31, bx + 38, 47), radius=3, fill=C["name"])
        d.rectangle((bx + 56, 34, bx + 60, 44), fill=C["name"])
        for i in range(4):
            x = bx - 70 + i * 13
            d.rounded_rectangle((x, 50 - 7 - i * 6, x + 8, 50), radius=2, fill=C["name"])
        # стрелка назад
        cy = STATUS_H + (HEADER_H - STATUS_H) // 2
        d.line([(66, cy - 24), (44, cy), (66, cy + 24)], fill=C["name"], width=6, joint="curve")
        # аватар
        av = 120
        s = 3
        grad = vgradient(av * s, av * s, C["avatar_top"], C["avatar_bottom"])
        mask = Image.new("L", (av * s, av * s), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, av * s - 1, av * s - 1), fill=255)
        avatar = Image.new("RGBA", (av * s, av * s))
        avatar.paste(grad, (0, 0), mask)
        avatar = avatar.resize((av, av), Image.LANCZOS)
        ImageDraw.Draw(avatar).text((av // 2, av // 2 + 2), cfg.get("contact_initial") or cfg["contact_name"][:1],
                                    font=font("bold", 58), fill=(255, 255, 255), anchor="mm")
        img.paste(avatar, (96, cy - av // 2), avatar)
        # имя и статус
        d.text((246, cy - 22), cfg["contact_name"], font=font("semibold", 50), fill=C["name"], anchor="lm")
        if typing_phase is None:
            d.text((246, cy + 32), cfg["status_online"], font=font("regular", 34), fill=C["online"], anchor="lm")
        else:
            d.text((246, cy + 32), cfg["status_typing"] + "." * typing_phase, font=font("regular", 34),
                   fill=C["typing_status"], anchor="lm")
        # иконки справа: камера и меню
        x0 = W - 210
        d.rounded_rectangle((x0, cy - 18, x0 + 46, cy + 18), radius=8, outline=C["name"], width=4)
        d.polygon([(x0 + 50, cy - 4), (x0 + 66, cy - 15), (x0 + 66, cy + 15), (x0 + 50, cy + 4)], outline=C["name"],
                  fill=C["name"])
        for k in (-1, 0, 1):
            d.ellipse((W - 62, cy + k * 18 - 5, W - 52, cy + k * 18 + 5), fill=C["name"])
        return img

    def render_shape(self, w, h, who, radius=40, tail=10):
        C, s = self.C, 3
        mask = Image.new("L", (w * s, h * s), 0)
        d = ImageDraw.Draw(mask)
        d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=radius * s, fill=255)
        R = radius * s
        if who == "mom":
            d.rounded_rectangle((0, h * s - 2 * R, 2 * R, h * s - 1), radius=tail * s, fill=255,
                                corners=(False, False, False, True))
        else:
            d.rounded_rectangle((w * s - 2 * R, h * s - 2 * R, w * s - 1, h * s - 1), radius=tail * s, fill=255,
                                corners=(False, False, True, False))
        mask = mask.resize((w, h), Image.LANCZOS)
        if who == "mom":
            fill = Image.new("RGB", (w, h), C["mom_bubble"])
        else:
            fill = vgradient(w, h, C["son_bubble_top"], C["son_bubble_bottom"])
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.paste(fill, (0, 0), mask)
        return out

    def render_ticks(self, color):
        s = 3
        im = Image.new("RGBA", (34 * s, 22 * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for off in (0, 11):
            pts = [((1 + off) * s, 11 * s), ((7 + off) * s, 18 * s), ((20 + off) * s, 3 * s)]
            d.line(pts, fill=color + (255,), width=int(3.2 * s), joint="curve")
        return im.resize((34, 22), Image.LANCZOS)

    def render_bubble(self, text, who, clock):
        C = self.C
        f = font("medium", 48)
        lines = [" ".join(l) for l in wrap_words(text.split(), f, BUBBLE_MAX_TEXT_W)]
        lh, px, py = 62, 34, 24
        tw = max(f.getlength(l) for l in lines)
        bw = int(tw + 2 * px)
        bh = int(py * 2 + lh * len(lines) - 6)
        bubble = self.render_shape(bw, bh, who)
        d = ImageDraw.Draw(bubble)
        for i, l in enumerate(lines):
            d.text((px, py + lh * i + lh / 2 - 3), l, font=f, fill=C[who + "_text"], anchor="lm")
        mf = font("regular", 28)
        cw = int(mf.getlength(clock))
        meta_w = cw + (46 if who == "son" else 0)
        full_w = max(bw, meta_w + 16)
        img = Image.new("RGBA", (full_w, bh + META_H), (0, 0, 0, 0))
        md = ImageDraw.Draw(img)
        if who == "mom":
            img.paste(bubble, (0, 0), bubble)
            md.text((10, bh + META_H // 2 + 2), clock, font=mf, fill=C["meta"], anchor="lm")
        else:
            img.paste(bubble, (full_w - bw, 0), bubble)
            ticks = self.render_ticks(C["ticks"])
            tx = full_w - 8 - ticks.width
            img.paste(ticks, (tx, bh + META_H // 2 - 9), ticks)
            md.text((tx - 10, bh + META_H // 2 + 2), clock, font=mf, fill=C["meta"], anchor="rm")
        return img

    def render_chip(self, text):
        C = self.C
        f = font("medium", 30)
        w = int(f.getlength(text)) + 48
        h = 54
        im = Image.new("RGBA", (w * 3, h * 3), (0, 0, 0, 0))
        ImageDraw.Draw(im).rounded_rectangle((0, 0, w * 3 - 1, h * 3 - 1), radius=h * 3 // 2, fill=C["chip_bg"] + (255,))
        im = im.resize((w, h), Image.LANCZOS)
        ImageDraw.Draw(im).text((w // 2, h // 2), text, font=f, fill=C["chip_text"], anchor="mm")
        return im

    def clock_at(self, i):
        hh, mm = (int(v) for v in self.cfg["clock_start"].split(":"))
        total = hh * 60 + mm + i // 3
        return f"{total // 60 % 24:02d}:{total % 60:02d}"

    def prerender_items(self):
        """Элементы чата: история (видна сразу) + реплики со временем появления."""
        self.items = []
        hh, mm = (int(v) for v in self.cfg["clock_start"].split(":"))
        for k, h in enumerate(self.cfg.get("history") or []):
            if "chip" in h:
                img = self.render_chip(h["chip"])
                self.items.append(dict(kind="chip", img=img, h=img.height + GAP + 6))
            else:
                img = self.render_bubble(h["text"], h["who"], f"{(hh + 23) % 24:02d}:{(mm * 7 + k * 3) % 60:02d}")
                self.items.append(dict(kind="static", who=h["who"], img=img, h=img.height + GAP))
        for i, (m, tl) in enumerate(zip(self.messages, self.tl)):
            img = self.render_bubble(m["text"], m["who"], self.clock_at(i))
            self.items.append(dict(kind="msg", who=m["who"], img=img, h=img.height + GAP, tl=tl, idx=i,
                                   text=m["text"]))

    def render_panel(self, typed):
        key = typed
        if key in self.panel_cache:
            return self.panel_cache[key]
        C = self.C
        img = self.bg.crop((0, VIEW_BOTTOM, W, H)).copy()
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, W, PANEL_H), fill=C["header"])
        d.line((0, 0, W, 0), fill=C["header_border"], width=2)
        fh, fy = 84, (PANEL_H - 84) // 2
        s = 3
        field = Image.new("RGBA", ((W - 2 * SIDE - 110) * s, fh * s), (0, 0, 0, 0))
        ImageDraw.Draw(field).rounded_rectangle((0, 0, field.width - 1, field.height - 1), radius=fh * s // 2,
                                                fill=C["input_field"] + (255,))
        field = field.resize((W - 2 * SIDE - 110, fh), Image.LANCZOS)
        img.paste(field, (SIDE, fy), field)
        f = font("regular", 40)
        if typed:
            txt = typed
            maxw = field.width - 80
            while f.getlength(txt) > maxw:
                txt = txt[1:]
            d.text((SIDE + 36, fy + fh // 2), txt, font=f, fill=C["input_text"], anchor="lm")
            cx = SIDE + 36 + f.getlength(txt) + 4
            d.rectangle((cx, fy + 22, cx + 3, fy + fh - 22), fill=C["send_button"])
        else:
            d.text((SIDE + 36, fy + fh // 2), "Сообщение", font=f, fill=C["placeholder"], anchor="lm")
        # кнопка отправки
        bx, r = W - SIDE - 84, 84
        btn = Image.new("RGBA", (r * s, r * s), (0, 0, 0, 0))
        ImageDraw.Draw(btn).ellipse((0, 0, r * s - 1, r * s - 1), fill=C["send_button"] + (255,))
        btn = btn.resize((r, r), Image.LANCZOS)
        bd = ImageDraw.Draw(btn)
        bd.polygon([(28, 22), (64, 42), (28, 62), (34, 42)], fill=C["son_text"])
        img.paste(btn, (bx, fy), btn)
        if len(self.panel_cache) < 400:
            self.panel_cache[key] = img
        return img

    def render_sub(self, words, hi, reveal=False):
        """Субтитры: words — список слов; hi — индекс подсвеченного (или -1);
        reveal=True — показываются только слова до hi включительно."""
        key = (tuple(words), hi, reveal)
        if key in self.sub_cache:
            return self.sub_cache[key]
        C = self.C
        f = font("black", 84)
        lines = wrap_words(words, f, 960)
        lh = 104
        img = Image.new("RGBA", (W, lh * len(lines) + 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        space = f.getlength(" ")
        k = 0
        for li, line in enumerate(lines):
            lw = f.getlength(" ".join(line))
            x = (W - lw) / 2
            y = 20 + lh * li + lh / 2
            for w in line:
                visible = (not reveal) or k <= hi
                if visible:
                    col = C["subtitle_highlight"] if k == hi else C["subtitle"]
                    d.text((x, y + 6), w, font=f, fill=(0, 0, 0, 150), anchor="lm", stroke_width=10,
                           stroke_fill=(0, 0, 0, 150))
                    d.text((x, y), w, font=f, fill=col, anchor="lm", stroke_width=9, stroke_fill=C["subtitle_stroke"])
                x += f.getlength(w) + space
                k += 1
        if len(self.sub_cache) < 600:
            self.sub_cache[key] = img
        return img

    def render_card_text(self, text, size, hl_color, card=False, max_w=920):
        """Крупный центрированный текст; фрагменты в [квадратных скобках] выделяются цветом."""
        C = self.C
        f = font("black", size)
        lh = int(size * 1.18)
        rows = []
        for para in text.split("\n"):
            tokens, on = [], False
            for part in re.split(r"(\[|\])", para):
                if part == "[":
                    on = True
                elif part == "]":
                    on = False
                else:
                    tokens += [(w, on) for w in part.split()]
            cur, cur_w = [], 0
            for w, on in tokens:
                ww = f.getlength(w)
                add = ww + (f.getlength(" ") if cur else 0)
                if cur and cur_w + add > max_w:
                    rows.append(cur)
                    cur, cur_w = [], 0
                    add = ww
                cur.append((w, on))
                cur_w += add
            if cur:
                rows.append(cur)
        img = Image.new("RGBA", (W, lh * len(rows) + 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for ri, row in enumerate(rows):
            rw = f.getlength(" ".join(w for w, _ in row))
            x = (W - rw) / 2
            y = 30 + lh * ri + lh / 2
            for w, on in row:
                d.text((x, y), w, font=f, fill=hl_color if on else C["subtitle"], anchor="lm", stroke_width=8,
                       stroke_fill=(0, 0, 0))
                x += f.getlength(w + " ")
        return img

    def render_outro(self):
        C = self.C
        txt = self.render_card_text(self.cfg["outro"], 72, C["outro_accent"], max_w=860)
        pad = 60
        icon_h = 110
        cw, ch = 980, txt.height + icon_h + pad
        s = 2
        card = Image.new("RGBA", (cw * s, ch * s), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((0, 0, cw * s - 1, ch * s - 1), radius=56 * s, fill=C["outro_card"] + (245,),
                             outline=C["outro_accent"] + (255,), width=5 * s)
        card = card.resize((cw, ch), Image.LANCZOS)
        ticks = self.render_ticks(C["ticks"]).resize((136, 88), Image.LANCZOS)
        card.paste(ticks, ((cw - 136) // 2, 44), ticks)
        card.alpha_composite(txt.crop(((W - cw) // 2, 0, (W - cw) // 2 + cw, txt.height)), (0, icon_h + 10))
        return card

    # ---------------- кадр ----------------
    def item_height(self, it, t):
        if it["kind"] != "msg":
            return it["h"]
        tl = it["tl"]
        h_typ = TYPING_H + GAP + 8
        if t < tl["ts"]:
            return 0.0
        if t < tl["appear"]:
            return h_typ * ease_out_cubic((t - tl["ts"]) / 0.22)
        return h_typ + (it["h"] - h_typ) * ease_out_cubic((t - tl["appear"]) / 0.3)

    def draw_item(self, frame, it, top, t):
        img = it["img"]
        if it["kind"] == "chip":
            frame.paste(img, ((W - img.width) // 2, int(top)), img)
            return
        who = it["who"]
        if it["kind"] == "static":
            x = SIDE if who == "mom" else W - SIDE - img.width
            frame.paste(img, (x, int(top)), img)
            return
        tl = it["tl"]
        if t < tl["ts"]:
            return
        if t < tl["appear"]:  # «печатает»
            tb = self.typing_bubbles[who]
            a = clamp01((t - tl["ts"]) / 0.15)
            sc = 0.7 + 0.3 * ease_out_back((t - tl["ts"]) / 0.25)
            tw_, th_ = max(1, int(TYPING_W * sc)), max(1, int(TYPING_H * sc))
            bub = tb.resize((tw_, th_), Image.BILINEAR) if sc < 0.999 else tb.copy()
            for k in range(3):
                ph = (t - tl["ts"]) * 7.5 - k * 0.9
                dy = -9 * max(0.0, math.sin(ph))
                dot = with_alpha(self.dot[who], 0.55 + 0.45 * max(0.0, math.sin(ph)))
                cx = int((TYPING_W / 2 - 34 + k * 34) * sc)
                cy = int((TYPING_H / 2 + dy) * sc)
                bub.alpha_composite(dot, (max(0, cx - 11), max(0, cy - 11)))
            bub = with_alpha(bub, a)
            x = SIDE if who == "mom" else W - SIDE - tw_
            frame.paste(bub, (x, int(top + (TYPING_H - th_))), bub)
            return
        p = t - tl["appear"]
        if p >= 0.3:
            x = SIDE if who == "mom" else W - SIDE - img.width
            frame.paste(img, (x, int(top)), img)
            return
        k = ease_out_back(p / 0.28)
        sc = 0.8 + 0.2 * k
        a = clamp01(p / 0.12)
        w_, h_ = max(1, int(img.width * sc)), max(1, int(img.height * sc))
        im = with_alpha(img.resize((w_, h_), Image.BILINEAR), a)
        slide = (1 - ease_out_cubic(p / 0.28)) * 60
        if who == "mom":
            x = SIDE - slide
        else:
            x = W - SIDE - w_ + slide
        y = top + (img.height - h_) + (1 - ease_out_cubic(p / 0.28)) * 30
        frame.paste(im, (int(x), int(y)), im)

    def current_typing(self, t):
        for it in self.items:
            if it["kind"] == "msg" and it["tl"]["ts"] <= t < it["tl"]["appear"]:
                return it
        return None

    def render_frame(self, t):
        if self.blackout_start <= t < self.outro_start:
            return self.black.copy()
        frame = self.bg.copy()
        # чат (снизу вверх)
        y = VIEW_BOTTOM - 14
        placed = []
        for it in reversed(self.items):
            h = self.item_height(it, t)
            top = y - h
            placed.append((it, top))
            y = top
            if y < VIEW_TOP - 400:
                break
        for it, top in placed:
            if top < VIEW_BOTTOM and top + it["img"].height > VIEW_TOP:
                self.draw_item(frame, it, top, t)
        # шапка
        typing = self.current_typing(t)
        if typing is not None and typing["who"] == "mom":
            frame.paste(self.headers[int((t - typing["tl"]["ts"]) / 0.3) % 4], (0, 0))
        else:
            frame.paste(self.headers["online"], (0, 0))
        # поле ввода (сын «набирает» текст)
        typed = ""
        if typing is not None and typing["who"] == "son":
            tl = typing["tl"]
            n = int(len(typing["text"]) * clamp01((t - tl["ts"]) / (tl["typ"] * 0.85)))
            typed = typing["text"][:n]
        frame.paste(self.render_panel(typed), (0, VIEW_BOTTOM))
        # субтитры
        self.draw_subtitles(frame, t)
        # крючок
        hd = self.cfg["hook_duration"]
        if t < hd:
            a = 1.0 if t < hd - 0.18 else clamp01((hd - t) / 0.18)
            dark = Image.new("L", (W, H), int(200 * a))
            frame.paste((0, 0, 0), (0, 0, W, H), dark)
            sc = 0.86 + 0.14 * ease_out_back(t / 0.22)
            hk = self.hook_img
            im = hk.resize((int(hk.width * sc), int(hk.height * sc)), Image.BILINEAR) if sc < 0.999 else hk
            im = with_alpha(im, a)
            frame.paste(im, ((W - im.width) // 2, 860 - im.height // 2), im)
        # тряска на «тук»
        dx = dy = 0
        for kt in self.knocks:
            if 0 <= t - kt < 0.14:
                e = math.exp(-(t - kt) * 25)
                dx += int(16 * e * math.sin((t - kt) * 140))
                dy += int(10 * e * math.cos((t - kt) * 110))
        if dx or dy:
            shaken = Image.new("RGB", (W, H), self.C["bg_top"])
            shaken.paste(frame, (dx, dy))
            frame = shaken
        # финальная плашка
        if t >= self.outro_start:
            frame = Image.blend(frame, self.black, 0.72)
            p = t - self.outro_start
            sc = 0.8 + 0.2 * ease_out_back(p / 0.32)
            card = self.outro_img
            im = card.resize((int(card.width * sc), int(card.height * sc)), Image.BILINEAR) if sc < 0.999 else card
            im = with_alpha(im, clamp01(p / 0.12))
            frame.paste(im, ((W - im.width) // 2, 900 - im.height // 2), im)
        return frame

    def draw_subtitles(self, frame, t):
        sub, pop_t = None, None
        if self.knock_start - 0.05 <= t < self.blackout_start:
            words = self.cfg["knock_caption"].split()
            n = len(words)
            hi = -1
            for k, kt in enumerate(self.knocks[:n]):
                if t >= kt:
                    hi = k
            if hi >= 0:
                sub = self.render_sub(words, hi, reveal=True)
                pop_t = t - self.knocks[hi]
        else:
            for m, tl in zip(self.messages, self.tl):
                if tl["appear"] <= t < tl["end"]:
                    words = [w for w, _, _ in tl["words"]]
                    rel = t - tl["vs"]
                    hi = -1
                    if rel <= (tl["ve"] - tl["vs"]) + 0.05:
                        hi = 0
                        for k, (_, s, _) in enumerate(tl["words"]):
                            if rel >= s - 0.03:
                                hi = k
                    sub = self.render_sub(words, hi)
                    pop_t = t - tl["appear"]
                    break
        if sub is None:
            return
        if pop_t is not None and pop_t < 0.14:
            sc = 0.82 + 0.18 * ease_out_back(pop_t / 0.14)
            sub = sub.resize((int(sub.width * sc), int(sub.height * sc)), Image.BILINEAR)
        frame.paste(sub, ((W - sub.width) // 2, int(SUB_CENTER_Y - sub.height / 2)), sub)

    # ---------------- звук ----------------
    def build_audio(self, path):
        A = self.cfg["audio"]
        n = int((self.total + 0.5) * SR)
        voice = np.zeros(n, np.float32)
        fx = np.zeros(n, np.float32)
        duck = np.zeros(n, np.float32)

        def put(buf, sig, at, gain=1.0):
            i = int(at * SR)
            m = min(len(sig), n - i)
            if m > 0:
                buf[i:i + m] += gain * sig[:m]

        pops = {"mom": make_pop(820), "son": make_pop(1150)}
        for m, tl, (x, _) in zip(self.messages, self.tl, self.voices):
            peak = max(1e-4, float(np.max(np.abs(x))))
            put(voice, x * (A["voice_level"] / peak), tl["vs"])
            put(fx, pops[m["who"]], tl["appear"], A["pop_volume"])
            put(duck, np.ones(int((tl["ve"] - tl["vs"]) * SR), np.float32), tl["vs"])
        knock = make_knock()
        for kt in self.knocks:
            put(fx, knock, kt, A["knock_volume"])
        put(fx, pops["son"], self.outro_start, A["pop_volume"] * 0.8)
        # бит: до тук-тук, с «подныриванием» под голос
        beat_len = self.knock_start - 0.15
        beat = make_beat(beat_len, A["beat_bpm"])
        duck = smooth(np.minimum(duck, 1.0), int(0.12 * SR))
        g = (1 - A["beat_duck"] * duck[:len(beat)]) * A["beat_volume"]
        bed = np.zeros(n, np.float32)
        bed[:len(beat)] = beat * g
        mix = voice + fx + bed
        peak = np.max(np.abs(mix))
        if peak > 0.98:
            mix = np.tanh(mix * 1.1) / np.tanh(1.1 * peak) * 0.98
        pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
        stereo = np.repeat(pcm[:, None], 2, axis=1)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes(stereo.tobytes())


# ----------------------------------------------------------------------------
# Рендер видео (параллельно по сегментам)
# ----------------------------------------------------------------------------
SCENE = None


def render_segment(args):
    k, f0, f1, path = args
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-level", "4.2", "-threads", "2", "-g", "120", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    for f in range(f0, f1):
        proc.stdin.write(SCENE.render_frame(f / FPS).tobytes())
        if k == 0 and (f - f0) % 120 == 0 and f > f0:
            done = (f - f0) / (f1 - f0)
            print(f"  рендер: {done * 100:4.0f}%  (~{(time.time() - t0) / done * (1 - done):.0f} c осталось)",
                  flush=True)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg упал на сегменте {k}")
    return path


def main():
    global SCENE
    ap = argparse.ArgumentParser(description="Фейковая переписка → вертикальное видео")
    ap.add_argument("script", help="script.json")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--limit", type=int, default=0, help="взять только первые N реплик (пробная версия)")
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 2)))
    ap.add_argument("--frames", default="", help="вместо видео сохранить PNG-кадры на указанных секундах")
    args = ap.parse_args()
    check_tools()

    data = json.load(open(args.script, encoding="utf-8"))
    if isinstance(data, list):
        cfg_over, messages = {}, data
    else:
        cfg_over, messages = data.get("config", {}), data["messages"]
    cfg = deep_merge(DEFAULT_CONFIG, cfg_over)
    for m in messages:
        if m.get("who") not in ("mom", "son"):
            sys.exit(f"Поле who должно быть mom или son: {m}")
    if args.limit:
        messages = messages[:args.limit]
        cfg["min_duration"], cfg["max_duration"] = 0, 10 ** 6

    print(f"1/4 Озвучка {len(messages)} реплик (edge-tts)...")
    jobs = []
    for m in messages:
        v = cfg["voices"][m["who"]]
        jobs.append((m.get("tts", m["text"]), m.get("voice", v["voice"]), m.get("rate", v.get("rate", "+0%")),
                     m.get("pitch", v.get("pitch", "+0Hz")), m.get("volume", v.get("volume", "+0%"))))
    results = synthesize_all(jobs)
    voices = [trim_voice(decode_audio(p), w) for p, w in results]

    print("2/4 Таймлайн и графика...")
    SCENE = Scene(cfg, messages, voices)
    SCENE.fit_duration()
    total = SCENE.total
    n_frames = int(round(total * FPS))
    print(f"  длительность: {total:.2f} c, кадров: {n_frames}")

    if args.frames:
        for s in args.frames.split(","):
            t = float(s)
            p = f"frame_{t:06.2f}.png"
            SCENE.render_frame(t).save(p)
            print("  сохранён", p)
        return

    tmp = tempfile.mkdtemp(prefix="msgvid_")
    try:
        print("3/4 Звук...")
        wav = os.path.join(tmp, "audio.wav")
        SCENE.build_audio(wav)

        print(f"4/4 Видео ({args.workers} потоков)...")
        nseg = args.workers
        bounds = [round(n_frames * i / nseg) for i in range(nseg + 1)]
        segs = [(k, bounds[k], bounds[k + 1], os.path.join(tmp, f"seg{k:02d}.mp4"))
                for k in range(nseg) if bounds[k + 1] > bounds[k]]
        if len(segs) > 1:
            with mp.get_context("fork").Pool(len(segs)) as pool:
                paths = pool.map(render_segment, segs)
        else:
            paths = [render_segment(segs[0])]
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            for p in paths:
                f.write(f"file '{p}'\n")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-i", wav,
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
                        "-t", f"{total:.3f}", "-movflags", "+faststart", args.output], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"Готово: {os.path.abspath(args.output)}  ({total:.1f} c)")


if __name__ == "__main__":
    main()
