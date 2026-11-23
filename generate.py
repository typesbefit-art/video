#!/usr/bin/env python3
"""
Генератор вертикального видео «фейковая переписка в мессенджере».

    python generate.py script.json                # -> output.mp4
    python generate.py script.json -o demo.mp4 --limit 6
    python generate.py script.json --frames 0.5,5,12   # PNG-превью кадров без рендера видео

Сюжет, имена, голоса, цвета — в script.json (секция "settings" переопределяет DEFAULTS ниже).
Код при смене сюжета трогать не нужно.
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
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------------------
# Настройки по умолчанию. Любой ключ можно переопределить в script.json -> "settings".
# --------------------------------------------------------------------------------------
DEFAULTS = {
    "width": 1080,
    "height": 1920,
    "fps": 60,
    "duration": {"min": 45.0, "max": 60.0},   # подгонка длины ролика (паузы/«печатает»)
    "hook": "Друг обещал вернуть деньги «завтра»",
    "hook_duration": 1.0,
    "outro_top": "Подписывайся на",
    "outro_title": "«Прочитано и проигнорировано»",
    "outro_duration": 1.5,
    "silence_after_last": 1.0,
    "contact_name": "Друг",
    "contact_status": "был в сети давно",
    "clock_start": "21:04",
    "date_label": "Сегодня",
    "voices": {
        # rate/pitch плавно меняются от *_start к *_end по ходу реплик этого персонажа
        "me": {"voice": "ru-RU-SvetlanaNeural",
               "rate_start": 6, "rate_end": -10,      # % скорости
               "pitch_start": 2, "pitch_end": -12,    # Гц
               "volume": 0},                          # %
        "friend": {"voice": "ru-RU-DmitryNeural",
                   "rate_start": -6, "rate_end": -8,
                   "pitch_start": -4, "pitch_end": -6,
                   "volume": 0},
    },
    "colors": {
        "bg": "#0E0F13",
        "bg_pattern": "#16171D",
        "header": "#18191F",
        "header_line": "#24252D",
        "avatar": "#E0785A",
        "avatar_text": "#FFFFFF",
        "name": "#F2F2F5",
        "status": "#8A8C99",
        "friend_bubble": "#2C2D35",
        "friend_text": "#EDEDF2",
        "me_bubble": "#8E6CEB",
        "me_text": "#FFFFFF",
        "time_friend": "#8E909C",
        "time_me": "#E4DAFF",
        "checks": "#4DA6FF",
        "typing_dots": "#B9BBC6",
        "date_pill": "#22232A",
        "date_text": "#9C9EAA",
        "input_bar": "#18191F",
        "input_field": "#25262E",
        "input_text": "#6E707C",
        "sub_text": "#FFFFFF",
        "sub_active": "#FFE14D",
        "sub_stroke": "#000000",
        "hook_text": "#FFFFFF",
        "hook_accent": "#FFE14D",
        "outro_panel": "#8E6CEB",
        "outro_text": "#FFFFFF",
    },
    "fonts": {
        "regular": "fonts/Roboto-Regular.ttf",
        "medium": "fonts/Roboto-Medium.ttf",
        "bold": "fonts/Roboto-Bold.ttf",
        "black": "fonts/Roboto-Black.ttf",
    },
    "audio": {
        "voice_gain": 1.0,
        "pop_gain": 0.22,
        "beat_gain": 0.13,       # фоновый бит (~ -20 dB к голосу), дополнительно приглушается под голосом
        "beat_bpm": 92,
        "beat_duck": 0.45,       # во сколько раз бит тише, когда кто-то говорит
    },
    "timing": {
        "typing_base": 0.55,     # длительность «печатает» = base + per_char * len (с ограничением)
        "typing_per_char": 0.012,
        "typing_max": 1.3,
        "voice_delay": 0.08,     # голос стартует чуть позже появления пузыря
        "anim": 0.28,            # выезд пузыря / скролл
    },
}

SR = 48000  # частота дискретизации аудио


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ease_out(p):
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def ease_out_back(p):
    p = max(0.0, min(1.0, p))
    c1, c3 = 1.4, 2.4
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


# --------------------------------------------------------------------------------------
# Озвучка (edge-tts) с кешем и таймингами слов
# --------------------------------------------------------------------------------------
def _patch_edge_tts_ssl():
    """edge-tts использует только certifi; добавляем системный CA (корпоративные прокси и т.п.)."""
    try:
        import certifi
        import edge_tts.communicate as c
        ctx = ssl.create_default_context(cafile=certifi.where())
        for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
            p = os.environ.get(var)
            if p and os.path.isfile(p):
                ctx.load_verify_locations(p)
        c._SSL_CTX = ctx
    except Exception:
        pass


async def _tts_one(text, voice, rate, pitch, volume, mp3_path, meta_path):
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume,
                               boundary="WordBoundary")
    words = []
    with open(mp3_path, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"t": ch["offset"] / 1e7, "d": ch["duration"] / 1e7, "w": ch["text"]})
    meta_path.write_text(json.dumps(words, ensure_ascii=False))


def synthesize(jobs, cache_dir):
    """jobs: list of dict(text, voice, rate, pitch, volume). Возвращает [(samples, words)]."""
    _patch_edge_tts_ssl()
    cache_dir.mkdir(exist_ok=True)
    todo, results = [], []
    for j in jobs:
        key = hashlib.sha1(json.dumps(j, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        mp3, meta = cache_dir / f"{key}.mp3", cache_dir / f"{key}.json"
        if not (mp3.exists() and meta.exists() and mp3.stat().st_size > 0):
            todo.append((j, mp3, meta))
        results.append((mp3, meta))

    async def run_all():
        sem = asyncio.Semaphore(2)

        async def one(j, mp3, meta):
            async with sem:
                for attempt in range(10):
                    try:
                        await _tts_one(j["text"], j["voice"], j["rate"], j["pitch"], j["volume"], mp3, meta)
                        return
                    except Exception as e:
                        if attempt == 9:
                            mp3.unlink(missing_ok=True)
                            raise
                        print(f"  TTS retry ({e.__class__.__name__}): {j['text'][:30]}")
                        await asyncio.sleep(min(6.0, 1.0 + attempt))
        await asyncio.gather(*(one(*t) for t in todo))

    if todo:
        print(f"Озвучка: {len(todo)} реплик через edge-tts...")
        asyncio.run(run_all())
    out = []
    for mp3, meta in results:
        out.append((decode_audio(mp3), json.loads(meta.read_text())))
    return out


def decode_audio(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1",
                          "-ar", str(SR), "-"], check=True, capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32).copy()
    # срезаем тишину по краям (edge-tts добавляет ~50-100 мс)
    thr = 0.01
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx):
        start = max(0, idx[0] - int(0.02 * SR))
        end = min(len(a), idx[-1] + int(0.06 * SR))
        a = a[start:end]
        return a, start / SR
    return a, 0.0


# --------------------------------------------------------------------------------------
# Привязка таймингов слов озвучки к словам текста (для подсветки в субтитрах)
# --------------------------------------------------------------------------------------
def _norm(s):
    return re.sub(r"[^0-9a-zа-я]", "", s.lower().replace("ё", "е"))


def map_word_times(text, boundaries, audio_len, trim):
    tokens = text.split()
    char_tok, norm = [], ""
    for i, tok in enumerate(tokens):
        n = _norm(tok)
        norm += n
        char_tok += [i] * len(n)
    starts = [None] * len(tokens)
    cur = 0
    for b in boundaries:
        nb = _norm(b["w"])
        if not nb:
            continue
        pos = norm.find(nb, cur)
        if pos < 0:
            continue
        ti = char_tok[pos]
        t = max(0.0, b["t"] - trim)
        if starts[ti] is None:
            starts[ti] = t
        cur = pos + len(nb)
    # заполнить пропуски равномерно
    known = [(i, s) for i, s in enumerate(starts) if s is not None]
    if not known:
        step = audio_len / max(1, len(tokens))
        return [i * step for i in range(len(tokens))]
    for i in range(len(tokens)):
        if starts[i] is None:
            prev = max([k for k in known if k[0] < i], default=(-1, 0.0), key=lambda k: k[0])
            nxt = min([k for k in known if k[0] > i], default=(len(tokens), audio_len), key=lambda k: k[0])
            frac = (i - prev[0]) / (nxt[0] - prev[0])
            starts[i] = prev[1] + (nxt[1] - prev[1]) * frac
    starts[0] = min(starts[0], 0.05)
    return starts


# --------------------------------------------------------------------------------------
# Графика
# --------------------------------------------------------------------------------------
class Fonts:
    def __init__(self, cfg):
        self.paths = {}
        for k, p in cfg["fonts"].items():
            pp = Path(p)
            if not pp.is_absolute():
                pp = ROOT / pp
            self.paths[k] = str(pp) if pp.exists() else None
        self._cache = {}

    def get(self, kind, size):
        key = (kind, size)
        if key not in self._cache:
            path = self.paths.get(kind)
            for cand in [path, "DejaVuSans-Bold.ttf" if kind in ("bold", "black") else "DejaVuSans.ttf"]:
                if not cand:
                    continue
                try:
                    self._cache[key] = ImageFont.truetype(cand, size)
                    break
                except OSError:
                    continue
            else:
                self._cache[key] = ImageFont.load_default(size)
        return self._cache[key]


def wrap(text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.getlength(test) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def aa_shape(size, draw_fn, scale=3):
    """Рисует белую маску в увеличенном масштабе и уменьшает — сглаженные края."""
    w, h = size
    m = Image.new("L", (w * scale, h * scale), 0)
    draw_fn(ImageDraw.Draw(m), scale)
    return m.resize((w, h), Image.LANCZOS)


def colored(mask, color):
    img = Image.new("RGBA", mask.size, hex2rgb(color) + (255,))
    img.putalpha(mask)
    return img


def draw_checks(d, x, y, s, width):
    """Две галочки «прочитано» (рисуется на маске масштаба s)."""
    lw = int(width * s)
    for dx in (0, 11):
        pts = [((x + dx) * s, (y + 9) * s), ((x + dx + 6) * s, (y + 15) * s), ((x + dx + 18) * s, (y + 2) * s)]
        d.line(pts, fill=255, width=lw, joint="curve")


class Renderer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.C = cfg["colors"]
        self.W, self.H = cfg["width"], cfg["height"]
        self.F = Fonts(cfg)
        sy = self.H / 1920
        self.header_h = int(250 * sy)
        self.chat_top = self.header_h
        self.chat_bottom = int(1330 * sy)
        self.sub_center = int(1500 * sy)
        self.input_top = int(1730 * sy)
        self.side_pad = 36
        self.max_bubble_text_w = int(self.W * 0.64)
        self.gap = 20
        self.msg_font = self.F.get("regular", 50)
        self.time_font = self.F.get("regular", 27)
        self._bubble_cache = {}
        self._sub_cache = {}
        self._alpha_cache = {}
        self.base = self._make_base()
        self.chat_bg = self.base.crop((0, self.chat_top, self.W, self.chat_bottom))
        self.header_img = self.base.crop((0, 0, self.W, self.header_h))
        self.date_pill = self._make_date_pill()
        self.typing_h = 96
        self.typing_w = 170

    # ---------- статичный фон ----------
    def _make_base(self):
        C, W, H = self.C, self.W, self.H
        img = Image.new("RGB", (W, H), hex2rgb(C["bg"]))
        d = ImageDraw.Draw(img)
        # лёгкий узор фона
        pc = hex2rgb(C["bg_pattern"])
        for yy in range(0, H, 64):
            for xx in range((yy // 64 % 2) * 32, W, 64):
                d.ellipse((xx - 3, yy - 3, xx + 3, yy + 3), fill=pc)
        # шапка
        d.rectangle((0, 0, W, self.header_h), fill=hex2rgb(C["header"]))
        d.line((0, self.header_h - 1, W, self.header_h - 1), fill=hex2rgb(C["header_line"]), width=2)
        # статус-бар
        sb = self.F.get("medium", 32)
        d.text((60, 28), self.cfg["clock_start"], font=sb, fill=hex2rgb(C["name"]))
        bx = W - 70
        d.rounded_rectangle((bx - 52, 34, bx, 60), radius=6, outline=hex2rgb(C["name"]), width=3)
        d.rectangle((bx - 46, 40, bx - 14, 54), fill=hex2rgb(C["name"]))
        d.rectangle((bx + 3, 42, bx + 7, 52), fill=hex2rgb(C["name"]))
        for i in range(4):
            x0 = bx - 120 + i * 13
            d.rectangle((x0, 58 - (i + 1) * 6, x0 + 8, 58), fill=hex2rgb(C["name"]))
        # кнопка «назад»
        cy = 165
        arr = aa_shape((40, 60), lambda dd, s: dd.line([(30 * s, 6 * s), (8 * s, 30 * s), (30 * s, 54 * s)],
                                                       fill=255, width=6 * s, joint="curve"))
        img.paste(colored(arr, C["checks"]), (34, cy - 30), colored(arr, C["checks"]))
        # аватар
        r = 50
        ax = 100 + r
        av = aa_shape((2 * r, 2 * r), lambda dd, s: dd.ellipse((0, 0, 2 * r * s - 1, 2 * r * s - 1), fill=255))
        img.paste(colored(av, C["avatar"]), (ax - r, cy - r), av)
        name = self.cfg["contact_name"]
        initial = (name.strip()[:1] or "?").upper()
        d.text((ax, cy + 2), initial, font=self.F.get("bold", 50), fill=hex2rgb(C["avatar_text"]), anchor="mm")
        # имя и статус
        tx = ax + r + 28
        d.text((tx, cy - 8), name, font=self.F.get("bold", 46), fill=hex2rgb(C["name"]), anchor="ls")
        d.text((tx, cy + 38), self.cfg["contact_status"], font=self.F.get("regular", 32),
               fill=hex2rgb(C["status"]), anchor="ls")
        # три точки меню справа
        for i in range(3):
            d.ellipse((W - 62, cy - 26 + i * 22, W - 52, cy - 16 + i * 22), fill=hex2rgb(C["status"]))
        # поле ввода снизу
        d.rectangle((0, self.input_top, W, H), fill=hex2rgb(C["input_bar"]))
        fy0, fy1 = self.input_top + 28, self.input_top + 118
        d.rounded_rectangle((110, fy0, W - 130, fy1), radius=45, fill=hex2rgb(C["input_field"]))
        d.text((150, (fy0 + fy1) // 2), "Сообщение", font=self.F.get("regular", 38),
               fill=hex2rgb(C["input_text"]), anchor="lm")
        # скрепка и микрофон (условные значки)
        d.ellipse((30, fy0 + 15, 90, fy1 - 15), outline=hex2rgb(C["input_text"]), width=4)
        d.line((60, fy0 + 30, 60, fy1 - 30), fill=hex2rgb(C["input_text"]), width=4)
        d.line((45, (fy0 + fy1) // 2, 75, (fy0 + fy1) // 2), fill=hex2rgb(C["input_text"]), width=4)
        mx = W - 70
        d.rounded_rectangle((mx - 12, fy0 + 18, mx + 12, fy0 + 58), radius=12, fill=hex2rgb(C["input_text"]))
        d.arc((mx - 22, fy0 + 30, mx + 22, fy0 + 68), 0, 180, fill=hex2rgb(C["input_text"]), width=4)
        d.line((mx, fy0 + 68, mx, fy1 - 14), fill=hex2rgb(C["input_text"]), width=4)
        return img

    def _make_date_pill(self):
        f = self.F.get("medium", 30)
        txt = self.cfg["date_label"]
        w = int(f.getlength(txt)) + 48
        h = 54
        m = aa_shape((w, h), lambda d, s: d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=h * s // 2, fill=255))
        img = colored(m, self.C["date_pill"])
        ImageDraw.Draw(img).text((w // 2, h // 2 + 1), txt, font=f, fill=hex2rgb(self.C["date_text"]), anchor="mm")
        return img

    # ---------- пузырь сообщения ----------
    def bubble(self, idx, who, text, clock):
        key = (idx,)
        if key in self._bubble_cache:
            return self._bubble_cache[key]
        C = self.C
        me = who == "me"
        f, tf = self.msg_font, self.time_font
        asc, desc = f.getmetrics()
        lh = asc + desc + 6
        lines = wrap(text, f, self.max_bubble_text_w)
        lw = [f.getlength(l) for l in lines]
        time_w = tf.getlength(clock)
        px, py = 34, 22
        text_w = max(lw)
        last_fits = lw[-1] + 18 + time_w <= self.max_bubble_text_w
        extra_line = 0
        if last_fits:
            text_w = max(text_w, lw[-1] + 18 + time_w)
        else:
            extra_line = 30
        bw = int(text_w + 2 * px)
        bh = int(len(lines) * lh - 6 + 2 * py + extra_line + (4 if last_fits else 0))
        checks_h = 40 if me else 0
        r, rt = 40, 10

        def shape(d, s):
            d.rounded_rectangle((0, 0, bw * s - 1, bh * s - 1), radius=r * s, fill=255)
            if me:  # «хвостик» — острый нижний правый угол
                d.rectangle(((bw - r) * s, (bh - r) * s, bw * s - 1, bh * s - 1), fill=255)
                d.rectangle(((bw - rt) * s, (bh - rt) * s, bw * s, bh * s), fill=0)
                d.ellipse(((bw - 2 * rt) * s, (bh - 2 * rt) * s, bw * s - 1, bh * s - 1), fill=255)
            else:
                d.rectangle((0, (bh - r) * s, r * s, bh * s - 1), fill=255)
                d.rectangle((0, (bh - rt) * s, rt * s, bh * s), fill=0)
                d.ellipse((0, (bh - 2 * rt) * s, 2 * rt * s, bh * s - 1), fill=255)
        mask = aa_shape((bw, bh), shape)
        img = Image.new("RGBA", (bw, bh + checks_h), (0, 0, 0, 0))
        img.paste(colored(mask, C["me_bubble" if me else "friend_bubble"]), (0, 0))
        d = ImageDraw.Draw(img)
        tc = hex2rgb(C["me_text" if me else "friend_text"])
        for i, l in enumerate(lines):
            d.text((px, py + i * lh + asc), l, font=f, fill=tc, anchor="ls")
        d.text((bw - px + 6, bh - 14), clock, font=tf,
               fill=hex2rgb(C["time_me" if me else "time_friend"]), anchor="rs")
        if me:
            cm = aa_shape((34, 22), lambda dd, s: draw_checks(dd, 2, 2, s, 3.2))
            img.paste(colored(cm, C["checks"]), (bw - 40, bh + 10), cm)
        self._bubble_cache[key] = img
        return img

    def typing_bubble(self, who, t):
        C = self.C
        me = who == "me"
        w, h = self.typing_w, self.typing_h
        key = ("typing_base", who)
        if key not in self._bubble_cache:
            m = aa_shape((w, h), lambda d, s: d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=h * s // 2, fill=255))
            self._bubble_cache[key] = colored(m, C["me_bubble" if me else "friend_bubble"])
        img = self._bubble_cache[key].copy()
        d = ImageDraw.Draw(img)
        base = hex2rgb(C["me_text"] if me else C["typing_dots"])
        for k in range(3):
            ph = (t * 2.2 - k * 0.18) % 1.0
            bounce = math.sin(ph * math.pi) if ph < 0.5 else 0.0
            bounce = max(0.0, math.sin(min(ph, 0.5) * 2 * math.pi)) if ph < 0.5 else 0.0
            yoff = -12 * bounce
            a = 0.45 + 0.55 * bounce
            col = tuple(int(c * a + hex2rgb(C["me_bubble" if me else "friend_bubble"])[i] * (1 - a)) for i, c in enumerate(base))
            cx, cy = w // 2 + (k - 1) * 36, h // 2 + yoff
            d.ellipse((cx - 11, cy - 11, cx + 11, cy + 11), fill=col)
        return img

    # ---------- субтитры ----------
    def subtitle(self, idx, text, active):
        key = (idx, active)
        if key in self._sub_cache:
            return self._sub_cache[key]
        C = self.C
        f = self.F.get("black", 84)
        sp = f.getlength(" ")
        words = text.split()
        lines, cur, cur_w = [], [], 0
        maxw = self.W - 140
        for i, w in enumerate(words):
            ww = f.getlength(w)
            if cur and cur_w + sp + ww > maxw:
                lines.append(cur)
                cur, cur_w = [], 0
            cur_w = cur_w + (sp if cur else 0) + ww
            cur.append((i, w, ww))
        if cur:
            lines.append(cur)
        asc, desc = f.getmetrics()
        lh = asc + desc - 2
        pad = 20
        H = lh * len(lines) + 2 * pad
        img = Image.new("RGBA", (self.W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for li, line in enumerate(lines):
            tw = sum(x[2] for x in line) + sp * (len(line) - 1)
            x = (self.W - tw) / 2
            y = pad + li * lh + asc
            for i, w, ww in line:
                col = C["sub_active"] if i == active else C["sub_text"]
                d.text((x, y), w, font=f, fill=hex2rgb(col), anchor="ls",
                       stroke_width=9, stroke_fill=hex2rgb(C["sub_stroke"]))
                x += ww + sp
        self._sub_cache[key] = img
        return img

    # ---------- заголовок-крючок и финальная плашка ----------
    def hook_layer(self):
        if "hook" in self._bubble_cache:
            return self._bubble_cache["hook"]
        C = self.C
        img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 200))
        d = ImageDraw.Draw(img)
        f = self.F.get("black", 104)
        lines = wrap(self.cfg["hook"], f, self.W - 150)
        asc, desc = f.getmetrics()
        lh = asc + desc + 6
        y = self.H // 2 - lh * len(lines) // 2 - 80
        sp = f.getlength(" ")
        in_quote = False
        for li, line in enumerate(lines):
            words = line.split()
            tw = f.getlength(line)
            x = (self.W - tw) / 2
            for w in words:
                acc = in_quote or any(q in w for q in "«\"“„")
                if any(q in w for q in "«“„") and not any(q in w for q in "»”"):
                    in_quote = True
                if any(q in w for q in "»”"):
                    in_quote = False
                d.text((x, y + li * lh + asc), w, font=f, anchor="ls",
                       fill=hex2rgb(C["hook_accent"] if acc else C["hook_text"]),
                       stroke_width=6, stroke_fill=(0, 0, 0))
                x += f.getlength(w) + sp
        self._bubble_cache["hook"] = img
        return img

    def outro_layer(self):
        if "outro" in self._bubble_cache:
            return self._bubble_cache["outro"]
        C = self.C
        pw = self.W - 120
        f1, f2 = self.F.get("medium", 52), self.F.get("black", 70)
        lines = wrap(self.cfg["outro_title"], f2, pw - 100)
        a2, d2 = f2.getmetrics()
        lh2 = a2 + d2 + 4
        ph = 60 + 64 + 20 + lh2 * len(lines) + 70 + 60
        m = aa_shape((pw, ph), lambda d, s: d.rounded_rectangle((0, 0, pw * s - 1, ph * s - 1), radius=56 * s, fill=255))
        img = colored(m, C["outro_panel"])
        d = ImageDraw.Draw(img)
        y = 60
        d.text((pw // 2, y + 46), self.cfg["outro_top"], font=f1, fill=hex2rgb(C["outro_text"]), anchor="ms")
        y += 64 + 20
        for i, l in enumerate(lines):
            d.text((pw // 2, y + i * lh2 + a2), l, font=f2, fill=hex2rgb(C["outro_text"]), anchor="ls" if False else "ms")
        y += lh2 * len(lines) + 20
        cm = aa_shape((70, 44), lambda dd, s: draw_checks(dd, 4, 4, s * 1.9, 3.5))
        img.paste(colored(cm, C["checks"]), (pw // 2 - 35, y), cm)
        self._bubble_cache["outro"] = img
        return img

    def with_alpha(self, img, a, key):
        a = round(a, 2)
        if a >= 0.999:
            return img
        k = (key, a)
        if k not in self._alpha_cache:
            out = img.copy()
            out.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
            self._alpha_cache[k] = out
        return self._alpha_cache[k]


# --------------------------------------------------------------------------------------
# Таймлайн
# --------------------------------------------------------------------------------------
def build_timeline(cfg, messages, audios, fit=True):
    T = cfg["timing"]
    n = len(messages)
    typing = []
    pauses = []
    for m in messages:
        typing.append(min(T["typing_max"], T["typing_base"] + T["typing_per_char"] * len(m["text"])))
        pauses.append(float(m.get("pause_after", 0.3)))
    lens = [len(a[0][0]) / SR for a in audios]
    start0 = cfg["hook_duration"] - 0.3
    tail = cfg["silence_after_last"] + cfg["outro_duration"]

    def total():
        t = start0 + sum(typing) + n * T["voice_delay"] + sum(lens) + sum(pauses[:-1])
        return t + tail

    natural = total()
    if fit:
        lo, hi = cfg["duration"]["min"], cfg["duration"]["max"]
        cur = total()
        if cur < lo:
            extra = (lo + 0.5) - cur
            per = extra / n
            for i in range(n):
                add_t = min(per * 0.45, 2.2 - typing[i])
                typing[i] += add_t
                if i < n - 1:
                    pauses[i] += per - add_t
                else:
                    typing[i] += per - add_t
        elif cur > hi:
            over = cur - (hi - 0.5)
            slack = sum(max(0, t - 0.45) for t in typing) + sum(max(0, p - 0.12) for p in pauses[:-1])
            k = min(1.0, over / slack) if slack > 0 else 0
            typing = [t - max(0, t - 0.45) * k for t in typing]
            pauses = [p - max(0, p - 0.12) * k for p in pauses[:-1]] + [pauses[-1]]
            if total() > hi:
                print(f"ВНИМАНИЕ: даже с минимальными паузами ролик {total():.1f} с > {hi} с")
    events = []
    t = start0
    for i, m in enumerate(messages):
        ev = {"i": i, "who": m["who"], "text": m["text"], "typing": t}
        t += typing[i]
        ev["bubble"] = t
        ev["voice"] = t + T["voice_delay"]
        ev["voice_end"] = ev["voice"] + lens[i]
        t = ev["voice_end"] + (pauses[i] if i < n - 1 else 0)
        events.append(ev)
    last_end = events[-1]["voice_end"]
    duration = last_end + tail
    return events, duration, natural


# --------------------------------------------------------------------------------------
# Аудио: голоса + поп + бит
# --------------------------------------------------------------------------------------
def make_pop(freq=820):
    n = int(0.07 * SR)
    t = np.arange(n) / SR
    f = freq * (1 - 0.45 * t / t[-1])
    ph = 2 * np.pi * np.cumsum(f) / SR
    env = np.exp(-t * 55) * np.minimum(1, t * 900)
    return (np.sin(ph) * env).astype(np.float32)


def make_beat(dur, bpm, seed=7):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    out = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    step = beat / 2  # восьмые

    def kick():
        m = int(0.32 * SR)
        t = np.arange(m) / SR
        f = 45 + 90 * np.exp(-t * 28)
        return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)).astype(np.float32)

    def snare():
        m = int(0.18 * SR)
        t = np.arange(m) / SR
        noise = rng.standard_normal(m).astype(np.float32)
        noise = np.convolve(noise, np.ones(4) / 4, mode="same")
        tone = np.sin(2 * np.pi * 190 * t)
        return ((noise * 0.6 + tone * 0.4) * np.exp(-t * 22)).astype(np.float32) * 0.55

    def hat():
        m = int(0.045 * SR)
        t = np.arange(m) / SR
        noise = rng.standard_normal(m).astype(np.float32)
        noise = np.diff(noise, prepend=0)
        return (noise * np.exp(-t * 90)).astype(np.float32) * 0.12

    def bass(freq, length):
        m = int(length * SR)
        t = np.arange(m) / SR
        env = np.minimum(1, t * 60) * np.exp(-t * 2.5)
        return (np.sin(2 * np.pi * freq * t) * 0.8 + np.sin(4 * np.pi * freq * t) * 0.15).astype(np.float32) * env * 0.45

    K, S, Hh = kick(), snare(), hat()
    roots = [55.0, 55.0, 43.65, 49.0]  # A1 A1 F1 G1
    k = 0
    t = 0.0
    while t < dur:
        i = int(t * SR)
        pos = k % 8
        bar = (k // 8) % 4

        def add(s, at=i, g=1.0):
            e = min(n, at + len(s))
            if e > at:
                out[at:e] += s[:e - at] * g

        if pos in (0, 5):
            add(K)
        if pos in (2, 6):
            add(S)
        add(Hh, g=1.0 if pos % 2 else 0.6)
        if pos in (0, 3, 4):
            add(bass(roots[bar], step * 1.6))
        k += 1
        t += step
    # мягкий «тёплый» фильтр
    out = np.convolve(out, np.ones(6) / 6, mode="same").astype(np.float32)
    return out / (np.max(np.abs(out)) + 1e-9)


def build_audio(cfg, events, audios, duration, path):
    A = cfg["audio"]
    n = int(math.ceil(duration * SR)) + SR // 10
    voice = np.zeros(n, np.float32)
    fx = np.zeros(n, np.float32)
    duck = np.zeros(n, np.float32)
    for ev, ((samples, _trim), _w) in zip(events, audios):
        s = int(ev["voice"] * SR)
        e = min(n, s + len(samples))
        voice[s:e] += samples[:e - s] * A["voice_gain"]
        duck[s:e] = 1.0
        pop = make_pop(950 if ev["who"] == "me" else 700)
        ps = int(ev["bubble"] * SR)
        pe = min(n, ps + len(pop))
        fx[ps:pe] += pop[:pe - ps] * A["pop_gain"]
    # поп на финальной плашке
    ps = int((duration - cfg["outro_duration"]) * SR)
    pop = make_pop(1100)
    fx[ps:ps + len(pop)] += pop[:max(0, min(len(pop), n - ps))] * A["pop_gain"]
    # нормализуем голос
    peak = np.max(np.abs(voice)) + 1e-9
    voice *= 0.85 / peak
    # бит до конца последней реплики, затем секунда тишины
    last_end = events[-1]["voice_end"]
    beat = make_beat(last_end + 0.4, A["beat_bpm"]) * A["beat_gain"]
    fade = int(0.35 * SR)
    beat[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    # сглаженный сайдчейн
    k = int(0.15 * SR)
    duck_s = np.convolve(duck, np.ones(k) / k, mode="same")[:len(beat)]
    beat *= 1 - (1 - A["beat_duck"]) * np.clip(duck_s, 0, 1)
    fade_in = int(0.3 * SR)
    beat[:fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)
    mix = voice + fx
    mix[:len(beat)] += beat
    mix = np.tanh(mix * 1.05) / np.tanh(1.05)  # мягкий лимитер
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())


# --------------------------------------------------------------------------------------
# Кадры
# --------------------------------------------------------------------------------------
class Scene:
    def __init__(self, cfg, R, events, audios, duration):
        self.cfg, self.R, self.events, self.duration = cfg, R, events, duration
        self.anim = cfg["timing"]["anim"]
        # часы в пузырях
        hh, mm = map(int, cfg["clock_start"].split(":"))
        self.clocks = []
        for i in range(len(events)):
            m = mm + i // 3
            self.clocks.append(f"{(hh + m // 60) % 24:02d}:{m % 60:02d}")
        # тайминги слов для субтитров
        self.word_starts = []
        for ev, ((samples, trim), words) in zip(events, audios):
            self.word_starts.append(map_word_times(ev["text"], words, len(samples) / SR, trim))
        self.sub_until = []
        for i, ev in enumerate(events):
            nxt = events[i + 1]["bubble"] if i + 1 < len(events) else ev["voice_end"] + 0.5
            self.sub_until.append(min(nxt, ev["voice_end"] + 0.45))

    def state(self, t):
        """Возвращает описание кадра (хешируемое) — одинаковые кадры не рисуются повторно."""
        R, evs, A = self.R, self.events, self.anim
        blocks = []  # (kind, idx, extra)
        shift = 0.0
        newest = None
        for ev in evs:
            if t >= ev["bubble"]:
                blocks.append(("msg", ev["i"]))
        typing_ev = next((ev for ev in evs if ev["typing"] <= t < ev["bubble"]), None)
        if typing_ev:
            blocks.append(("typing", typing_ev["i"]))
        # анимация последнего события
        last_evt = None
        for ev in evs:
            for kind, tt in (("typing", ev["typing"]), ("msg", ev["bubble"])):
                if tt <= t and (last_evt is None or tt >= last_evt[2]):
                    last_evt = (kind, ev["i"], tt)
        if last_evt:
            kind, i, tt = last_evt
            p = (t - tt) / A
            if p < 1:
                e = ease_out(p)
                if kind == "typing":
                    shift = (1 - e) * (R.typing_h + R.gap)
                else:
                    bh = R.bubble(i, evs[i]["who"], evs[i]["text"], self.clocks[i]).height
                    shift = (1 - e) * (bh - R.typing_h)
                newest = (kind, i, round(p, 3))
        typing_phase = round((t * 2.2) % 1.0, 2) if typing_ev else None
        # субтитры
        sub = None
        for i, ev in enumerate(evs):
            if ev["voice"] - 0.05 <= t < self.sub_until[i]:
                rel = t - ev["voice"]
                ws = self.word_starts[i]
                active = 0
                for j, s in enumerate(ws):
                    if rel >= s:
                        active = j
                if t > ev["voice_end"]:
                    active = -1
                sub = (i, active)
        hook_a = 0.0
        hd = self.cfg["hook_duration"]
        if t < hd:
            hook_a = 1.0 if t < hd - 0.25 else (hd - t) / 0.25
            hook_a = round(hook_a, 2)
        outro_p = None
        od = self.cfg["outro_duration"]
        if t >= self.duration - od:
            outro_p = round(min(1.0, (t - (self.duration - od)) / 0.35), 3)
        return (tuple(blocks), round(shift), newest, typing_phase, sub, hook_a, outro_p, round(t, 3) if hook_a and hook_a < 1 else None)

    def render(self, st, t):
        R, evs = self.R, self.events
        blocks, shift, newest, typing_phase, sub, hook_a, outro_p, _ = st
        frame = R.base.copy()
        chat = R.chat_bg.copy()
        ch = chat.height
        y_bottom = ch - 24 + shift
        placed = []
        for b in reversed(blocks):
            kind, i = b
            who = evs[i]["who"]
            img = R.typing_bubble(who, t) if kind == "typing" else R.bubble(i, who, evs[i]["text"], self.clocks[i])
            h = R.typing_h if kind == "typing" else img.height
            y = y_bottom - h
            placed.append((kind, i, who, img, y))
            y_bottom = y - R.gap
            if y_bottom < -50:
                break
        # плашка с датой над первым сообщением
        top_y = (placed[-1][4] if placed else ch - 24 + shift) - R.gap - R.date_pill.height
        if len(placed) == len(blocks) and top_y > -R.date_pill.height:
            chat.paste(R.date_pill, ((R.W - R.date_pill.width) // 2, int(top_y)), R.date_pill)
        for kind, i, who, img, y in placed:
            me = who == "me"
            x = R.W - R.side_pad - img.width if me else R.side_pad
            if newest and newest[0] == kind and newest[1] == i:
                p = newest[2]
                e = ease_out_back(p)
                a = min(1.0, p * 2.2)
                sc = 0.82 + 0.18 * e
                nw, nh = max(1, int(img.width * sc)), max(1, int(img.height * sc))
                im2 = img.resize((nw, nh), Image.BILINEAR)
                if a < 1:
                    im2.putalpha(im2.getchannel("A").point(lambda v: int(v * a)))
                slide = (1 - ease_out(p)) * 60
                if me:
                    x2 = R.W - R.side_pad - nw + slide
                else:
                    x2 = R.side_pad - slide
                y2 = y + (img.height - nh)
                chat.paste(im2, (int(x2), int(y2)), im2)
            else:
                chat.paste(img, (int(x), int(y)), img)
        frame.paste(chat, (0, R.chat_top))
        if sub is not None:
            si, active = sub
            simg = R.subtitle(si, evs[si]["text"], active)
            frame.paste(simg, (0, R.sub_center - simg.height // 2), simg)
        if hook_a > 0:
            hl = R.hook_layer()
            hl = R.with_alpha(hl, hook_a, "hook")
            frame.paste(hl, (0, 0), hl)
        if outro_p is not None:
            dim = Image.new("RGBA", (R.W, R.H), (0, 0, 0, int(150 * ease_out(outro_p))))
            frame.paste(dim, (0, 0), dim)
            ol = R.outro_layer()
            e = ease_out_back(outro_p)
            y = int(R.H * 0.40 + (1 - e) * 500)
            ola = R.with_alpha(ol, min(1.0, outro_p * 2), "outro")
            frame.paste(ola, ((R.W - ol.width) // 2, y - ol.height // 2), ola)
        return frame


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------
def load_script(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return deep_merge(DEFAULTS, {}), data
    return deep_merge(DEFAULTS, data.get("settings", {})), data["messages"]


def prosody(cfg, messages):
    jobs = []
    counts = {w: sum(1 for m in messages if m["who"] == w) for w in ("me", "friend")}
    seen = {"me": 0, "friend": 0}
    for m in messages:
        who = m["who"]
        if who not in cfg["voices"]:
            sys.exit(f"Неизвестный who={who!r}: ожидается me или friend")
        v = cfg["voices"][who]
        p = seen[who] / max(1, counts[who] - 1)
        seen[who] += 1
        rate = m.get("rate", round(v["rate_start"] + (v["rate_end"] - v["rate_start"]) * p))
        pitch = m.get("pitch", round(v["pitch_start"] + (v["pitch_end"] - v["pitch_start"]) * p))
        jobs.append({
            "text": m.get("say", m["text"]).replace("«", "").replace("»", ""),
            "voice": m.get("voice", v["voice"]),
            "rate": f"{int(rate):+d}%",
            "pitch": f"{int(pitch):+d}Hz",
            "volume": f"{int(v.get('volume', 0)):+d}%",
        })
    return jobs


def main():
    ap = argparse.ArgumentParser(description="Фейковая переписка -> вертикальное видео")
    ap.add_argument("script", nargs="?", default="script.json")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--limit", type=int, default=0, help="взять только первые N реплик (пробный ролик)")
    ap.add_argument("--no-fit", action="store_true", help="не подгонять длительность под 45–60 с")
    ap.add_argument("--frames", default="", help="только сохранить PNG-кадры в указанные секунды, напр. 0.5,10")
    ap.add_argument("--preset", default="medium", help="x264 preset (ultrafast…veryslow)")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("Не найден ffmpeg. Установите его (apt install ffmpeg / brew install ffmpeg / winget install ffmpeg).")

    cfg, messages = load_script(args.script)
    if args.limit:
        messages = messages[:args.limit]
    fit = not (args.no_fit or args.limit)

    audios = synthesize(prosody(cfg, messages), ROOT / ".tts_cache")
    events, duration, natural = build_timeline(cfg, messages, audios, fit=fit)
    print(f"Реплик: {len(events)}; естественная длина {natural:.1f} с; итог {duration:.1f} с")

    R = Renderer(cfg)
    scene = Scene(cfg, R, events, audios, duration)
    fps = cfg["fps"]

    if args.frames:
        out_dir = Path(args.output).with_suffix("")
        out_dir = out_dir.parent / (out_dir.name + "_frames")
        out_dir.mkdir(exist_ok=True)
        for s in args.frames.split(","):
            t = float(s)
            img = scene.render(scene.state(t), t)
            p = out_dir / f"frame_{t:06.2f}.png"
            img.save(p)
            print(p)
        return

    tmp = Path(args.output).with_suffix(".tmp.wav")
    build_audio(cfg, events, audios, duration, tmp)

    total_frames = int(round(duration * fps))
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{R.W}x{R.H}", "-r", str(fps), "-i", "-",
           "-i", str(tmp),
           "-c:v", "libx264", "-preset", args.preset, "-crf", "18", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
           "-t", f"{total_frames / fps:.3f}", "-movflags", "+faststart", args.output]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    last_key, last_bytes = None, None
    try:
        for fi in range(total_frames):
            t = fi / fps
            st = scene.state(t)
            if st != last_key:
                last_bytes = scene.render(st, t).tobytes()
                last_key = st
            proc.stdin.write(last_bytes)
            if fi % (fps * 5) == 0:
                print(f"\rкадры: {fi}/{total_frames}", end="", file=sys.stderr, flush=True)
    finally:
        proc.stdin.close()
        proc.wait()
        tmp.unlink(missing_ok=True)
    if proc.returncode != 0:
        sys.exit("ffmpeg завершился с ошибкой")
    print(f"\nГотово: {args.output} ({duration:.1f} с, {R.W}x{R.H}, {fps} fps)")


if __name__ == "__main__":
    main()
