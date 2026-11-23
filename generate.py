#!/usr/bin/env python3
"""
Генератор вертикального видео «фейковая переписка в мессенджере».

    python generate.py script.json                 -> output.mp4
    python generate.py script.json -o trial.mp4 --limit 6
    python generate.py script.json --frame 12.5    -> кадр в PNG для проверки

Сюжет, голоса, имена и цвета задаются в script.json — код при смене сюжета не трогаем.
Зависимости: Python 3.9+, Pillow, numpy, edge-tts, ffmpeg в PATH.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import ssl
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
SR = 48000  # частота дискретизации итогового звука

# --------------------------------------------------------------------------------------
# Настройки по умолчанию. Всё можно переопределить в script.json -> "settings".
# --------------------------------------------------------------------------------------
DEFAULTS = {
    "width": 1080,
    "height": 1920,
    "fps": 60,
    "duration_min": 45.0,          # авто-подгонка длительности полной версии
    "duration_max": 60.0,

    "title": "",
    "title_highlight": [],
    "hook_duration": 1.0,
    "outro_text": "Подписывайся!",
    "outro_duration": 1.5,

    "me": "tenant",                # чьи сообщения справа (салатовые, с галочками)
    "contact_name": "Сосед",
    "contact_status": "онлайн",
    "contact_typing": "печатает…",
    "avatar_initial": "",
    "date_chip": "",
    "start_time": "08:00",
    "minutes_per_message": 0.5,    # как быстро идут часы под сообщениями

    "voices": {
        "tenant": {"voice": "ru-RU-SvetlanaNeural", "rate": "+0%", "pitch": "+0Hz", "volume": "+0%"},
        "neighbor": {"voice": "ru-RU-DmitryNeural", "rate": "+0%", "pitch": "+0Hz", "volume": "+0%"},
    },

    "typing_min": 0.55,            # длительность «печатает…» (зависит от длины текста)
    "typing_max": 1.0,
    "typing_per_char": 0.008,
    "default_pause": 0.35,

    "subtitles": True,
    "subtitle_uppercase": True,
    "subtitle_max_words": 4,
    "subtitle_size": 74,

    "shake": True,                 # лёгкая тряска интерфейса, пока гудит «дрель»

    "audio": {
        "voice_level": 0.9,
        "beat_level": 0.10,
        "beat_bpm": 92,
        "beat_duck": 0.45,         # насколько бит приглушается под голосом
        "drill_level": 0.22,
        "pop_level": 0.22,
    },

    "colors": {
        "bg": "#0E0F13",
        "pattern": "#1A1C22",
        "header_bg": "#17191E",
        "header_text": "#F2F3F5",
        "muted": "#8A8F98",
        "accent": "#6FB6FF",
        "avatar": "#7A5CFA",
        "bubble_me": "#A4E26A",
        "bubble_me_text": "#10200A",
        "bubble_other": "#3A3C42",
        "bubble_other_text": "#F2F3F5",
        "checks": "#3AA0FF",
        "input_bg": "#24262C",
        "subtitle_zone": "#0A0B0E",
        "subtitle": "#FFFFFF",
        "subtitle_stroke": "#000000",
        "subtitle_highlight": {"tenant": "#B6F36A", "neighbor": "#FFD84D"},
        "hook_text": "#FFFFFF",
        "hook_highlight": "#FFD84D",
        "outro_bg": "#A4E26A",
        "outro_text": "#10200A",
    },

    "fonts": {},  # {"regular": "/path.ttf", "bold": ..., "black": ...} — по желанию
}

FONT_CANDIDATES = {
    "regular": [
        "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
    ],
    "medium": [
        "/usr/share/fonts/opentype/inter/Inter-Medium.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ],
    "bold": [
        "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ],
    "black": [
        "/usr/share/fonts/opentype/inter/Inter-Black.otf",
        "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    ],
}


# --------------------------------------------------------------------------------------
# Утилиты
# --------------------------------------------------------------------------------------
def deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def hex2rgb(h, a=None):
    h = h.lstrip("#")
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return rgb + (a,) if a is not None else rgb


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def ease_out_cubic(p):
    p = clamp(p)
    return 1 - (1 - p) ** 3


def ease_out_back(p, s=1.6):
    p = clamp(p) - 1
    return 1 + p * p * ((s + 1) * p + s)


def norm_word(s):
    return re.sub(r"[^\w]", "", s.lower().replace("ё", "е"))


def log(*a):
    print(*a, flush=True)


def load_font(kind, size, cfg):
    custom = cfg["fonts"].get(kind)
    for path in ([custom] if custom else []) + FONT_CANDIDATES[kind]:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def load_script(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"messages": data}
    cfg = deep_merge(DEFAULTS, data.get("settings", {}))
    msgs = [dict(m) for m in data["messages"]]
    for m in msgs:
        if m.get("who") not in cfg["voices"]:
            sys.exit(f"Неизвестный who={m.get('who')!r} в реплике {m.get('text')!r}")
    return cfg, msgs


# --------------------------------------------------------------------------------------
# Озвучка (edge-tts) с кешем
# --------------------------------------------------------------------------------------
def _patch_edge_tts_ssl():
    """Если в окружении задан свой CA (корпоративный прокси и т.п.) — доверяем ему."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        try:
            import edge_tts.communicate as ec
            ec._SSL_CTX = ssl.create_default_context(cafile=ca)
        except Exception:
            pass


async def _tts_request(text, v, mp3_path):
    import edge_tts
    kw = dict(rate=v.get("rate", "+0%"), pitch=v.get("pitch", "+0Hz"), volume=v.get("volume", "+0%"))
    try:
        com = edge_tts.Communicate(text, v["voice"], boundary="WordBoundary", **kw)
    except TypeError:  # старые версии edge-tts
        com = edge_tts.Communicate(text, v["voice"], **kw)
    words = []
    with open(mp3_path, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"text": ch["text"], "start": ch["offset"] / 1e7, "dur": ch["duration"] / 1e7})
    return words


def tts(text, v):
    cache = ROOT / ".cache" / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps([text, v], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    mp3, meta = cache / f"{key}.mp3", cache / f"{key}.json"
    if not (mp3.exists() and meta.exists() and mp3.stat().st_size > 0):
        _patch_edge_tts_ssl()
        for attempt in range(7):
            try:
                words = asyncio.run(asyncio.wait_for(_tts_request(text, v, mp3), timeout=40))
                if mp3.stat().st_size == 0:
                    raise RuntimeError("пустой ответ edge-tts")
                meta.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
                break
            except Exception as e:
                if attempt == 6:
                    raise
                log(f"  edge-tts: {e!r}, повтор…")
                time.sleep(3 * (attempt + 1))
    return decode_audio(mp3), json.loads(meta.read_text(encoding="utf-8"))


def decode_audio(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32).copy()
    # срезаем тишину в конце
    idx = np.nonzero(np.abs(a) > 0.01)[0]
    if len(idx):
        a = a[: min(len(a), idx[-1] + int(0.06 * SR))]
    return a


# --------------------------------------------------------------------------------------
# Синтез звуков (numpy)
# --------------------------------------------------------------------------------------
def fft_filter(x, lo=None, hi=None):
    """Простая полосовая фильтрация через FFT с мягкими краями."""
    n = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    g = np.ones_like(f)
    if hi:
        g *= 1 / np.sqrt(1 + (f / hi) ** 8)
    if lo:
        g *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** 8)
    return np.fft.irfft(X * g, n).astype(np.float32)


def drill_bursts(total, seed=7):
    """Расписание «жжж»: список (start, end). Общий для звука и тряски."""
    rng = np.random.default_rng(seed)
    t, out = 0.0, []
    while t < total:
        on = rng.uniform(0.7, 1.15)
        out.append((t, t + on))
        t += on + rng.uniform(0.3, 0.55)
    return out


def synth_drill(total, bursts):
    n = int(total * SR)
    t = np.arange(n) / SR
    env = np.zeros(n, np.float32)
    ramp = int(0.012 * SR)
    for s, e in bursts:
        a, b = int(s * SR), min(n, int(e * SR))
        if b - a <= 2 * ramp:
            continue
        env[a:b] = 1
        env[a:a + ramp] = np.linspace(0, 1, ramp)
        env[b - ramp:b] = np.linspace(1, 0, ramp)
    f0 = 148 + 5 * np.sin(2 * np.pi * 6.3 * t)
    ph = 2 * np.pi * np.cumsum(f0) / SR
    sig = 0.55 * np.tanh(3 * np.sin(ph)) + 0.35 * np.sin(0.5 * ph) + 0.15 * np.sin(2 * ph)
    rng = np.random.default_rng(3)
    sig = sig * (0.75 + 0.25 * np.sin(2 * np.pi * 27 * t)) + 0.25 * rng.standard_normal(n)
    sig = fft_filter(sig.astype(np.float32), lo=40, hi=380)  # «через перекрытие» — глухо
    sig = sig / (np.abs(sig).max() + 1e-9)
    return (sig * env).astype(np.float32)


def synth_beat(total, bpm):
    n = int(total * SR) + SR
    out = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    rng = np.random.default_rng(11)

    def add(sig, t0):
        a = int(t0 * SR)
        if a >= n:
            return
        b = min(n, a + len(sig))
        out[a:b] += sig[: b - a]

    tk = np.arange(int(0.35 * SR)) / SR
    kick = np.sin(2 * np.pi * (45 * tk + 90 * (1 - np.exp(-tk * 30)) / 30)) * np.exp(-tk * 9)
    ts = np.arange(int(0.2 * SR)) / SR
    snare = fft_filter(rng.standard_normal(len(ts)).astype(np.float32), lo=900, hi=5000) * np.exp(-ts * 22) * 0.5
    th = np.arange(int(0.05 * SR)) / SR
    hat = fft_filter(rng.standard_normal(len(th)).astype(np.float32), lo=6000) * np.exp(-th * 90) * 0.25
    roots = [55.0, 43.65, 65.41, 49.0]  # A, F, C, G (лоу-фай прогрессия)
    tb = np.arange(int(beat * 1.8 * SR)) / SR

    i = 0
    while i * beat < total + 1:
        t0 = i * beat
        pos = i % 4
        if pos in (0, 2):
            add(kick, t0)
        if pos == 2 and (i // 4) % 2 == 1:
            add(kick * 0.6, t0 + beat * 0.5)
        if pos in (1, 3):
            add(snare, t0)
        add(hat, t0)
        add(hat * 0.6, t0 + beat / 2)
        if pos in (0, 2):
            f = roots[(i // 4) % 4]
            bass = (np.sin(2 * np.pi * f * tb) + 0.3 * np.sin(4 * np.pi * f * tb)) * np.minimum(1, tb * 60) * np.exp(-tb * 2.2) * 0.55
            add(bass, t0)
        i += 1
    out = fft_filter(out, hi=6000)
    return (out / (np.abs(out).max() + 1e-9))[: int(total * SR)]


def synth_pop():
    t = np.arange(int(0.09 * SR)) / SR
    f = 950 * np.exp(-t * 18) + 380
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * np.exp(-t * 55) * np.minimum(1, t * 2000)).astype(np.float32)


def write_wav(path, mono):
    pcm = (np.clip(mono, -1, 1) * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())


# --------------------------------------------------------------------------------------
# Таймлайн
# --------------------------------------------------------------------------------------
def map_word_times(text, boundaries, dur):
    """Сопоставляет слова текста (с пунктуацией) с таймингами из edge-tts."""
    toks = [{"text": w, "norm": norm_word(w), "start": None} for w in text.split()]
    bnd = [dict(b, norm=norm_word(b["text"])) for b in boundaries if norm_word(b["text"])]
    bi = 0
    for tk in toks:
        if not tk["norm"] or bi >= len(bnd):
            continue
        # ищем ближайшее совпадение впереди (edge иногда добавляет/дробит слова)
        for j in range(bi, min(len(bnd), bi + 3)):
            bn = bnd[j]["norm"]
            if bn == tk["norm"] or tk["norm"].startswith(bn) or bn.startswith(tk["norm"]):
                tk["start"] = bnd[j]["start"]
                bi = j + 1
                acc = bn
                while bi < len(bnd) and len(acc) < len(tk["norm"]) and tk["norm"][len(acc):].startswith(bnd[bi]["norm"]):
                    acc += bnd[bi]["norm"]
                    bi += 1
                break
    # заполняем пропуски интерполяцией по длине слов
    known = [i for i, t in enumerate(toks) if t["start"] is not None]
    if not known:
        total_chars = sum(len(t["text"]) for t in toks) or 1
        acc = 0.0
        for t in toks:
            t["start"] = dur * acc / total_chars
            acc += len(t["text"])
    else:
        anchors = [(-1, 0.0)] + [(i, toks[i]["start"]) for i in known] + [(len(toks), dur)]
        for (ia, ta), (ib, tb) in zip(anchors, anchors[1:]):
            for k in range(ia + 1, ib):
                toks[k]["start"] = ta + (tb - ta) * (k - ia) / (ib - ia)
        if toks[0]["start"] is None:
            toks[0]["start"] = 0.0
    return toks


def add_minutes(hhmm, minutes):
    h, m = map(int, hhmm.split(":"))
    total = (h * 60 + m + int(minutes)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def build_timeline(cfg, msgs, squeeze=1.0):
    """squeeze < 1 укорачивает «печатает…» и паузы, чтобы уложиться в duration_max."""
    t = cfg["hook_duration"] - 0.15
    clock = cfg["start_time"]
    base_clock, base_idx = cfg["start_time"], 0
    for i, m in enumerate(msgs):
        if "time" in m:
            base_clock, base_idx = m["time"], i
            clock = m["time"]
        else:
            clock = add_minutes(base_clock, (i - base_idx) * cfg["minutes_per_message"])
        m["clock"] = clock
        n_chars = len(m["text"])
        typing = m.get("typing", clamp(cfg["typing_min"] + n_chars * cfg["typing_per_char"],
                                       cfg["typing_min"], cfg["typing_max"]))
        pause = m.get("pause_after", cfg["default_pause"])
        m["typing_eff"] = min(typing, 0.35 + (typing - 0.35) * squeeze)
        pause = min(pause, 0.12 + (pause - 0.12) * squeeze)
        m["t_typing"] = t
        m["t_show"] = t + m["typing_eff"]
        m["t_voice"] = m["t_show"] + 0.06
        m["t_voice_end"] = m["t_voice"] + m["dur"]
        t = m["t_voice_end"] + pause + m.get("extra_pause", 0)
    return t + cfg["outro_duration"]


# --------------------------------------------------------------------------------------
# Отрисовка
# --------------------------------------------------------------------------------------
class Renderer:
    STATUS_H, HEADER_H = 70, 160
    CHAT_TOP = 230
    INPUT_TOP, INPUT_H = 1330, 112
    SIDE = 34
    BUBBLE_MAX_TEXT = 690

    def __init__(self, cfg, msgs, total):
        self.cfg, self.msgs, self.total = cfg, msgs, total
        self.W, self.H, self.fps = cfg["width"], cfg["height"], cfg["fps"]
        self.C = cfg["colors"]
        self.me = cfg["me"]
        self.chat_h = self.INPUT_TOP - self.CHAT_TOP
        f = lambda k, s: load_font(k, s, cfg)
        self.f_msg = f("regular", 44)
        self.f_meta = f("regular", 28)
        self.f_name = f("bold", 44)
        self.f_status = f("regular", 32)
        self.f_clock = f("bold", 32)
        self.f_avatar = f("bold", 50)
        self.f_input = f("regular", 38)
        self.f_chip = f("medium", 30)
        self.f_sub = f("black", cfg["subtitle_size"])
        self.f_hook = f("black", 96)
        self.f_outro_small = f("bold", 46)
        self.f_outro_big = f("black", 58)

        self.bursts = drill_bursts(total)
        self.drill_stop = next((m["t_voice"] for m in msgs if m.get("stop_drill")), None)

        self._build_static()
        self._build_bubbles()
        self._build_layout()
        self._build_subtitles()
        self._precompute_scroll()
        self.hook_img = self._render_hook() if cfg["title"] else None
        self.outro_img = self._render_outro()
        self._sub_cache = {}

    # ---------- статичный фон ----------
    def _build_static(self):
        C, W, H = self.C, self.W, self.H
        img = Image.new("RGB", (W, H), hex2rgb(C["bg"]))
        d = ImageDraw.Draw(img)
        # фон чата: еле заметный узор
        pat = hex2rgb(C["pattern"])
        for yy in range(self.CHAT_TOP + 20, self.INPUT_TOP, 70):
            off = 35 if (yy // 70) % 2 else 0
            for xx in range(20 + off, W, 70):
                d.ellipse([xx - 3, yy - 3, xx + 3, yy + 3], fill=pat)
        self.chat_bg = img.crop((0, self.CHAT_TOP, W, self.INPUT_TOP))
        # статус-бар + шапка
        d.rectangle([0, 0, W, self.CHAT_TOP], fill=hex2rgb(C["header_bg"]))
        d.line([0, self.CHAT_TOP - 1, W, self.CHAT_TOP - 1], fill=(40, 42, 48), width=2)
        # сигнал и батарея
        tx = hex2rgb(C["header_text"])
        for i in range(4):
            h = 10 + i * 6
            d.rounded_rectangle([880 + i * 13, 48 - h, 888 + i * 13, 48], 2, fill=tx)
        d.rounded_rectangle([950, 24, 1010, 50], 7, outline=tx, width=3)
        d.rounded_rectangle([955, 29, 995, 45], 3, fill=tx)
        d.rectangle([1012, 32, 1017, 42], fill=tx)
        # кнопка «назад»
        cy = self.STATUS_H + self.HEADER_H // 2
        d.line([(58, cy - 22), (38, cy), (58, cy + 22)], fill=tx, width=6, joint="curve")
        # аватар
        ax, r = 140, 54
        d.ellipse([ax - r, cy - r, ax + r, cy + r], fill=hex2rgb(C["avatar"]))
        initial = self.cfg["avatar_initial"] or self.cfg["contact_name"][:1]
        d.text((ax, cy + 2), initial.upper(), font=self.f_avatar, fill=(255, 255, 255), anchor="mm")
        # имя
        d.text((218, cy - 12), self.cfg["contact_name"], font=self.f_name, fill=tx, anchor="ls")
        # иконки справа: трубка + меню
        d.ellipse([1020, cy - 26, 1032, cy - 14], fill=tx)
        d.ellipse([1020, cy - 6, 1032, cy + 6], fill=tx)
        d.ellipse([1020, cy + 14, 1032, cy + 26], fill=tx)

        # поле ввода
        iy = self.INPUT_TOP
        d.rectangle([0, iy, W, iy + self.INPUT_H], fill=hex2rgb(C["header_bg"]))
        d.rounded_rectangle([30, iy + 20, 900, iy + self.INPUT_H - 20], 36, fill=hex2rgb(C["input_bg"]))
        d.ellipse([925, iy + 16, 1005, iy + 96], fill=hex2rgb(C["accent"]))
        # «самолётик»
        cx, cyy = 965, iy + 56
        d.polygon([(cx - 18, cyy - 20), (cx + 22, cyy), (cx - 18, cyy + 20), (cx - 10, cyy)], fill=(255, 255, 255))
        # зона субтитров
        d.rectangle([0, iy + self.INPUT_H, W, H], fill=hex2rgb(C["subtitle_zone"]))
        self.static = img

    @staticmethod
    def _phone_icon(d, x, y, col):
        d.arc([x - 22, y - 22, x + 22, y + 22], 100, 250, fill=col, width=9)
        d.ellipse([x - 20, y - 26, x - 6, y - 12], fill=col)
        d.ellipse([x - 20, y + 12, x - 6, y + 26], fill=col)

    # ---------- пузыри ----------
    def _wrap(self, text, font, max_w):
        lines, cur = [], ""
        for w in text.split():
            cand = (cur + " " + w).strip()
            if font.getlength(cand) <= max_w or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def _draw_checks(self, d, x, y, col, k=1.0):
        for dx in (0, 14):
            pts = [(x + k * dx, y), (x + k * (dx + 8), y + k * 9), (x + k * (dx + 24), y - k * 9)]
            d.line(pts, fill=col, width=int(round(4 * k)), joint="curve")

    def _render_bubble(self, m):
        C = self.C
        mine = m["who"] == self.me
        lines = self._wrap(m["text"], self.f_msg, self.BUBBLE_MAX_TEXT)
        lh, px, py = 58, 34, 22
        tw = max(self.f_msg.getlength(l) for l in lines)
        bw, bh = int(tw + 2 * px), int(len(lines) * lh + 2 * py)
        meta_h = 42
        img = Image.new("RGBA", (bw, bh + meta_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        fill = hex2rgb(C["bubble_me" if mine else "bubble_other"])
        d.rounded_rectangle([0, 0, bw - 1, bh - 1], 36, fill=fill)
        # «хвостик» — острый нижний угол со стороны отправителя
        if mine:
            d.rounded_rectangle([bw - 60, bh - 60, bw - 1, bh - 1], 8, fill=fill)
        else:
            d.rounded_rectangle([0, bh - 60, 59, bh - 1], 8, fill=fill)
        col = hex2rgb(C["bubble_me_text" if mine else "bubble_other_text"])
        for i, l in enumerate(lines):
            d.text((px, py + i * lh + lh * 0.78), l, font=self.f_msg, fill=col, anchor="ls")
        # время (+ синие галочки под своими сообщениями)
        muted = hex2rgb(C["muted"])
        if mine:
            self._draw_checks(d, bw - 44, bh + 22, hex2rgb(C["checks"]))
            d.text((bw - 56, bh + 32), m["clock"], font=self.f_meta, fill=muted, anchor="rs")
        else:
            d.text((8, bh + 32), m["clock"], font=self.f_meta, fill=muted, anchor="ls")
        return img

    def _render_typing(self, mine):
        w, h = 150, 88
        fill = hex2rgb(self.C["bubble_me" if mine else "bubble_other"])
        base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(base)
        d.rounded_rectangle([0, 0, w - 1, h - 1], 36, fill=fill)
        return base

    def _build_bubbles(self):
        for m in self.msgs:
            m["img"] = self._render_bubble(m)
        self.typing_imgs = {True: self._render_typing(True), False: self._render_typing(False)}
        if self.cfg["date_chip"]:
            txt = self.cfg["date_chip"]
            w = int(self.f_chip.getlength(txt) + 48)
            chip = Image.new("RGBA", (w, 54), (0, 0, 0, 0))
            d = ImageDraw.Draw(chip)
            d.rounded_rectangle([0, 0, w - 1, 53], 27, fill=(36, 38, 44, 230))
            d.text((w / 2, 28), txt, font=self.f_chip, fill=hex2rgb(self.C["muted"]), anchor="mm")
            self.chip = chip
        else:
            self.chip = None

    def _build_layout(self):
        """Координаты сообщений в «ленте» (ось y вниз, 0 — верх ленты)."""
        y = 24
        if self.chip:
            self.chip_y = y
            y += self.chip.height + 26
        prev = None
        for m in self.msgs:
            if prev is not None:
                y += 30 if prev == m["who"] else 46
            m["y"] = y
            y += m["img"].height
            prev = m["who"]
        self.feed_pad = 24

    def _content_bottom(self, t):
        """Нижняя граница видимого контента в ленте на момент t (для скролла)."""
        bottom = (self.chip_y + self.chip.height) if self.chip else 0
        for i, m in enumerate(self.msgs):
            if t >= m["t_show"]:
                bottom = m["y"] + m["img"].height
            elif t >= m["t_typing"]:
                gap = 0 if i == 0 else (30 if self.msgs[i - 1]["who"] == m["who"] else 46)
                prev_bottom = self.msgs[i - 1]["y"] + self.msgs[i - 1]["img"].height if i else bottom
                bottom = prev_bottom + gap + 88
                break
            else:
                break
        return bottom + self.feed_pad

    def _precompute_scroll(self):
        n = int(math.ceil(self.total * self.fps))
        self.n_frames = n
        dt = 1 / self.fps
        offs = np.zeros(n)
        cur = None
        k = 1 - math.exp(-dt * 11)
        for i in range(n):
            target = self._content_bottom(i * dt) - self.chat_h  # сколько ленты уехало вверх
            cur = target if cur is None else cur + (target - cur) * k
            offs[i] = cur
        self.scroll = offs

    # ---------- субтитры ----------
    def _build_subtitles(self):
        mx = self.cfg["subtitle_max_words"]
        for m in self.msgs:
            toks = m["words"]
            chunks, cur = [], []
            for i, tk in enumerate(toks):
                cur.append(i)
                chars = sum(len(toks[j]["text"]) + 1 for j in cur)
                if len(cur) >= mx or chars >= 24 or tk["text"][-1] in ".!?…":
                    chunks.append(cur)
                    cur = []
            if cur:
                if chunks and len(cur) == 1 and toks[chunks[-1][-1]]["text"][-1] not in ".!?…" and len(chunks[-1]) < mx + 1:
                    chunks[-1] += cur
                else:
                    chunks.append(cur)
            m["chunks"] = chunks

    def _render_sub(self, m, ci, hl):
        key = (id(m), ci, hl)
        if key in self._sub_cache:
            return self._sub_cache[key]
        C = self.C
        hc = C["subtitle_highlight"]
        hcol = hex2rgb(hc.get(m["who"], "#FFD84D") if isinstance(hc, dict) else hc)
        words = [m["words"][j]["text"] for j in m["chunks"][ci]]
        if self.cfg["subtitle_uppercase"]:
            words = [w.upper() for w in words]
        f = self.f_sub
        space = f.getlength(" ")
        max_w = 900
        lines, cur, cw = [], [], 0
        for wi, w in enumerate(words):
            wl = f.getlength(w)
            if cur and cw + space + wl > max_w:
                lines.append(cur)
                cur, cw = [], 0
            cw += (space if cur else 0) + wl
            cur.append((wi, w, wl))
        if cur:
            lines.append(cur)
        lh = int(f.size * 1.15)
        img = Image.new("RGBA", (self.W, lh * len(lines) + 30), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for li, line in enumerate(lines):
            lw = sum(x[2] for x in line) + space * (len(line) - 1)
            x = (self.W - lw) / 2
            y = 15 + li * lh + f.size * 0.9
            for wi, w, wl in line:
                col = hcol if wi == hl else hex2rgb(C["subtitle"])
                d.text((x, y), w, font=f, fill=col, anchor="ls", stroke_width=7, stroke_fill=hex2rgb(C["subtitle_stroke"]))
                x += wl + space
        self._sub_cache[key] = img
        return img

    def _subtitle_state(self, t):
        for m in self.msgs:
            if m["t_voice"] - 0.05 <= t < m["t_voice_end"] + 0.25:
                lt = t - m["t_voice"]
                wi = 0
                for j, w in enumerate(m["words"]):
                    if lt >= w["start"] - 0.03:
                        wi = j
                for ci, ch in enumerate(m["chunks"]):
                    if wi in ch:
                        start = m["t_voice"] + m["words"][ch[0]]["start"]
                        return m, ci, ch.index(wi), t - start
        return None

    # ---------- крючок и финальная плашка ----------
    def _render_hook(self):
        f = self.f_hook
        hl = {norm_word(w) for w in self.cfg["title_highlight"]}
        words = self.cfg["title"].upper().split()
        space = f.getlength(" ")
        lines, cur, cw = [], [], 0
        for w in words:
            wl = f.getlength(w)
            if cur and cw + space + wl > 940:
                lines.append(cur)
                cur, cw = [], 0
            cw += (space if cur else 0) + wl
            cur.append((w, wl))
        lines.append(cur)
        lh = int(f.size * 1.12)
        img = Image.new("RGBA", (self.W, lh * len(lines) + 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for li, line in enumerate(lines):
            lw = sum(x[1] for x in line) + space * (len(line) - 1)
            x = (self.W - lw) / 2
            for w, wl in line:
                col = self.C["hook_highlight"] if norm_word(w) in hl else self.C["hook_text"]
                d.text((x, 20 + li * lh + f.size * 0.9), w, font=f, fill=hex2rgb(col), anchor="ls",
                       stroke_width=8, stroke_fill=(0, 0, 0))
                x += wl + space
        return img

    def _render_outro(self):
        lines = self.cfg["outro_text"].split("\n")
        fonts = [self.f_outro_small] + [self.f_outro_big] * (len(lines) - 1)
        wrapped = []
        for l, f in zip(lines, fonts):
            for wl in self._wrap(l, f, 860):
                wrapped.append((wl, f))
        h = sum(int(f.size * 1.3) for _, f in wrapped) + 150
        w = 960
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w - 1, h - 1], 48, fill=hex2rgb(self.C["outro_bg"]))
        self._draw_checks(d, w / 2 - 50, 62, hex2rgb(self.C["checks"]), 2.6)
        y = 105
        for l, f in wrapped:
            y += int(f.size * 1.05)
            d.text((w / 2, y), l, font=f, fill=hex2rgb(self.C["outro_text"]), anchor="ms")
            y += int(f.size * 0.25)
        return img

    # ---------- кадр ----------
    def shake_offset(self, t):
        if not self.cfg["shake"]:
            return 0, 0
        stop = self.drill_stop if self.drill_stop is not None else self.total - self.cfg["outro_duration"]
        if t >= stop:
            return 0, 0
        for s, e in self.bursts:
            if s <= t < e:
                a = 3.0
                return int(round(a * math.sin(t * 157))), int(round(a * math.sin(t * 211 + 1)))
            if s > t:
                break
        return 0, 0

    def frame(self, fi):
        t = fi / self.fps
        img = self.static.copy()
        d = ImageDraw.Draw(img)
        C = self.C

        # часы в статус-баре и статус собеседника
        shown = [m for m in self.msgs if t >= m["t_show"]]
        clock = shown[-1]["clock"] if shown else self.cfg["start_time"]
        d.text((60, 48), clock, font=self.f_clock, fill=hex2rgb(C["header_text"]), anchor="ls")
        typing_now = next((m for m in self.msgs if m["t_typing"] <= t < m["t_show"]), None)
        cy = self.STATUS_H + self.HEADER_H // 2
        if typing_now is not None and typing_now["who"] != self.me:
            d.text((218, cy + 32), self.cfg["contact_typing"], font=self.f_status, fill=hex2rgb(C["accent"]), anchor="ls")
        else:
            d.text((218, cy + 32), self.cfg["contact_status"], font=self.f_status, fill=hex2rgb(C["accent"]), anchor="ls")

        # лента
        chat = self.chat_bg.copy()
        off = self.scroll[fi]
        if self.chip:
            chat.paste(self.chip, ((self.W - self.chip.width) // 2, int(self.chip_y - off)), self.chip)
        for i, m in enumerate(self.msgs):
            mine = m["who"] == self.me
            if t >= m["t_show"]:
                bub = m["img"]
                p = (t - m["t_show"]) / 0.3
                y = int(m["y"] - off)
                if y > self.chat_h or y + bub.height < 0:
                    continue
                if p < 1:
                    s = 0.55 + 0.45 * ease_out_back(p)
                    a = clamp(p * 3)
                    bw, bh = max(1, int(bub.width * s)), max(1, int(bub.height * s))
                    b2 = bub.resize((bw, bh), Image.BILINEAR)
                    if a < 1:
                        alpha = b2.getchannel("A").point(lambda v: int(v * a))
                        b2.putalpha(alpha)
                    dx = int(50 * (1 - ease_out_cubic(p)))
                    x = (self.W - self.SIDE - bw + dx) if mine else (self.SIDE - dx)
                    chat.paste(b2, (x, y + bub.height - bh), b2)
                else:
                    x = (self.W - self.SIDE - bub.width) if mine else self.SIDE
                    chat.paste(bub, (x, y), bub)
            elif t >= m["t_typing"]:
                prev = self.msgs[i - 1] if i else None
                base_y = (prev["y"] + prev["img"].height + (30 if prev["who"] == m["who"] else 46)) if prev else \
                    ((self.chip_y + self.chip.height + 26) if self.chip else 24)
                ty = int(base_y - off)
                tb = self.typing_imgs[mine].copy()
                td = ImageDraw.Draw(tb)
                lt = t - m["t_typing"]
                dot = (60, 90, 30) if mine else (200, 202, 208)
                for k in range(3):
                    ph = (lt * 7.5 - k * 0.9)
                    bounce = max(0.0, math.sin(ph)) * 10
                    cxk = 47 + k * 28
                    cyk = 44 - bounce
                    td.ellipse([cxk - 9, cyk - 9, cxk + 9, cyk + 9], fill=dot)
                pin = clamp(lt / 0.15)
                if pin < 1:
                    s = 0.6 + 0.4 * ease_out_cubic(pin)
                    tb = tb.resize((max(1, int(150 * s)), max(1, int(88 * s))), Image.BILINEAR)
                x = (self.W - self.SIDE - tb.width) if mine else self.SIDE
                chat.paste(tb, (x, ty + 88 - tb.height), tb)
                break
            else:
                break
        img.paste(chat, (0, self.CHAT_TOP))

        # поле ввода: «моя» реплика набирается по буквам
        iy = self.INPUT_TOP
        if typing_now is not None and typing_now["who"] == self.me:
            p = clamp((t - typing_now["t_typing"]) / (typing_now["typing_eff"] * 0.9))
            txt = typing_now["text"][: int(len(typing_now["text"]) * p)]
            while self.f_input.getlength(txt) > 800 and len(txt) > 1:
                txt = txt[1:]
            caret = "|" if int(t * 3) % 2 == 0 else ""
            d.text((66, iy + 70), txt + caret, font=self.f_input, fill=hex2rgb(C["header_text"]), anchor="ls")
        else:
            d.text((66, iy + 70), "Сообщение", font=self.f_input, fill=hex2rgb(C["muted"]), anchor="ls")

        # тряска (как люстра)
        dx, dy = self.shake_offset(t)
        if dx or dy:
            ui = img.crop((0, 0, self.W, iy + self.INPUT_H))
            img.paste(hex2rgb(C["bg"]), (0, 0, self.W, iy + self.INPUT_H))
            img.paste(ui, (dx, dy))

        # субтитры
        if self.cfg["subtitles"]:
            st = self._subtitle_state(t)
            if st:
                m, ci, hl, age = st
                sub = self._render_sub(m, ci, hl)
                p = clamp(age / 0.12)
                if p < 1:
                    s = 0.85 + 0.15 * ease_out_back(p)
                    sub = sub.resize((max(1, int(sub.width * s)), max(1, int(sub.height * s))), Image.BILINEAR)
                zone_c = iy + self.INPUT_H + (self.H - iy - self.INPUT_H) * 0.36
                img.paste(sub, ((self.W - sub.width) // 2, int(zone_c - sub.height / 2)), sub)

        # крючок
        if self.hook_img is not None and t < self.cfg["hook_duration"]:
            hd = self.cfg["hook_duration"]
            fade = clamp((hd - t) / 0.18)
            dim = Image.new("RGBA", (self.W, self.H), (0, 0, 0, int(190 * fade)))
            img.paste(dim, (0, 0), dim)
            s = 0.8 + 0.2 * ease_out_back(t / 0.25)
            hk = self.hook_img.resize((int(self.W * s), int(self.hook_img.height * s)), Image.BILINEAR)
            if fade < 1:
                hk.putalpha(hk.getchannel("A").point(lambda v: int(v * fade)))
            img.paste(hk, ((self.W - hk.width) // 2, int(760 - hk.height / 2)), hk)

        # финальная плашка
        od = self.cfg["outro_duration"]
        if t >= self.total - od:
            lt = t - (self.total - od)
            p = ease_out_back(lt / 0.35, 1.2)
            dim = Image.new("RGBA", (self.W, self.H), (0, 0, 0, int(150 * clamp(lt / 0.25))))
            img.paste(dim, (0, 0), dim)
            o = self.outro_img
            y = int(self.H + 50 - (self.H + 50 - (self.H / 2 - o.height / 2 - 120)) * p)
            img.paste(o, ((self.W - o.width) // 2, y), o)
        return img


# --------------------------------------------------------------------------------------
# Звук
# --------------------------------------------------------------------------------------
def build_audio(cfg, msgs, total, renderer, path):
    A = cfg["audio"]
    n = int(math.ceil(total * SR))
    mix = np.zeros(n, np.float32)
    voice_mask = np.zeros(n, np.float32)
    for m in msgs:
        a = int(m["t_voice"] * SR)
        v = m["audio"]
        v = v / (np.abs(v).max() + 1e-9) * A["voice_level"]
        b = min(n, a + len(v))
        mix[a:b] += v[: b - a]
        voice_mask[a:b] = 1
    # сглаживаем маску для «дакинга»
    k = int(0.15 * SR)
    voice_mask = np.convolve(voice_mask, np.ones(k) / k, mode="same").astype(np.float32)

    beat = np.pad(synth_beat(total, A["beat_bpm"]), (0, n))[:n]
    fade = np.ones(n, np.float32)
    fl = int(0.8 * SR)
    fade[-fl:] = np.linspace(1, 0, fl)
    mix += beat[:n] * A["beat_level"] * (1 - A["beat_duck"] * voice_mask) * fade

    drill = np.pad(synth_drill(total, renderer.bursts), (0, n))[:n]
    stop = renderer.drill_stop
    if stop is not None:
        s = int(stop * SR)
        r = int(0.006 * SR)  # резкий обрыв, но без щелчка
        drill[s:s + r] *= np.linspace(1, 0, len(drill[s:s + r]))
        drill[s + r:] = 0
    else:
        s = int((total - cfg["outro_duration"]) * SR)
        r = int(0.3 * SR)
        drill[s:s + r] *= np.linspace(1, 0, len(drill[s:s + r]))
        drill[s + r:] = 0
    mix += drill * A["drill_level"] * (1 - 0.35 * voice_mask)

    pop = synth_pop() * A["pop_level"]
    for t0 in [m["t_show"] for m in msgs] + [total - cfg["outro_duration"]]:
        a = int(t0 * SR)
        b = min(n, a + len(pop))
        mix[a:b] += pop[: b - a]

    peak = np.abs(mix).max()
    if peak > 0.97:
        mix *= 0.97 / peak
    write_wav(path, mix)


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Фейковая переписка -> вертикальное видео")
    ap.add_argument("script", nargs="?", default="script.json")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--limit", type=int, default=0, help="взять только первые N реплик (пробная версия)")
    ap.add_argument("--frame", type=float, default=None, help="сохранить один кадр (секунда) в PNG и выйти")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="medium")
    args = ap.parse_args()

    cfg, msgs = load_script(args.script)
    trial = args.limit > 0
    if trial:
        msgs = msgs[: args.limit]

    log(f"Озвучка {len(msgs)} реплик через edge-tts…")
    boost = 0
    for attempt in range(3):
        for m in msgs:
            v = dict(cfg["voices"][m["who"]])
            for k in ("rate", "pitch", "volume", "voice"):
                if k in m:
                    v[k] = m[k]
            if boost:
                r = int(str(v.get("rate", "+0%")).rstrip("%")) + boost
                v["rate"] = f"{r:+d}%"
            log(f"  [{m['who']}] {v.get('rate')} {v.get('pitch')}  {m['text'][:50]}")
            m["audio"], bnd = tts(m["text"], v)
            m["dur"] = len(m["audio"]) / SR
            m["words"] = map_word_times(m["text"], bnd, m["dur"])
            m["extra_pause"] = 0
        total = build_timeline(cfg, msgs)
        if trial:
            break
        lo, hi = cfg["duration_min"], cfg["duration_max"]
        if total < lo:
            extra = (lo - total + 0.3) / len(msgs)
            for m in msgs:
                m["extra_pause"] = extra
            total = build_timeline(cfg, msgs)
            log(f"  ролик короче {lo:.0f} с — добавил по {extra:.2f} с паузы после каждой реплики")
            break
        if total <= hi:
            break
        # 1) сжимаем «печатает» и паузы
        squeeze = 1.0
        while squeeze > 0.0 and total > hi - 0.5:
            squeeze = round(squeeze - 0.05, 2)
            total = build_timeline(cfg, msgs, squeeze)
        if total <= hi:
            log(f"  сжал паузы и «печатает» (коэффициент {squeeze}) чтобы уложиться в {hi:.0f} с")
            cfg["_squeeze"] = squeeze
            break
        # 2) не хватило — ускоряем речь
        boost += int(math.ceil((total / hi - 1) * 100)) + 3
        log(f"  ролик {total:.1f} с > {hi:.0f} с — ускоряю речь на {boost}% и переозвучиваю")
    total = build_timeline(cfg, msgs, cfg.get("_squeeze", 1.0))
    log(f"Длительность: {total:.2f} с")

    r = Renderer(cfg, msgs, total)
    if args.frame is not None:
        out = Path(args.output).with_suffix(".png")
        r.frame(int(args.frame * r.fps)).save(out)
        log(f"Кадр сохранён: {out}")
        return

    tmp = ROOT / ".cache"
    tmp.mkdir(exist_ok=True)
    wav = tmp / "mix.wav"
    log("Сведение звука…")
    build_audio(cfg, msgs, total, r, wav)

    log(f"Рендер {r.n_frames} кадров {r.W}x{r.H}@{r.fps}…")
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{r.W}x{r.H}", "-r", str(r.fps), "-i", "-",
           "-i", str(wav),
           "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf), "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-r", str(r.fps),
           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
           "-movflags", "+faststart", "-shortest", args.output]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    for fi in range(r.n_frames):
        proc.stdin.write(r.frame(fi).tobytes())
        if fi % (r.fps * 5) == 0 and fi:
            el = time.time() - t0
            log(f"  {fi}/{r.n_frames} кадров, ~{el / fi * (r.n_frames - fi):.0f} с осталось")
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg завершился с ошибкой")
    log(f"Готово: {Path(args.output).resolve()}  ({total:.1f} с)")


if __name__ == "__main__":
    main()
