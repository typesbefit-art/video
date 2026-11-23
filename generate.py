#!/usr/bin/env python3
"""
Генератор вертикального видео «фейковая переписка в мессенджере».

    python generate.py script.json                      -> output.mp4
    python generate.py script.json --limit 6 -o preview.mp4   (пробная версия)

Всё, что касается сюжета, лежит в script.json. Голоса, цвета и имена можно
менять либо в блоке CONFIG ниже, либо (без правки кода) в script.json —
ключи "voices", "colors", "contact_name" и т.д. перекрывают CONFIG.
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
import subprocess
import sys
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# НАСТРОЙКИ ПО УМОЛЧАНИЮ (любой ключ можно перекрыть в script.json)
# ---------------------------------------------------------------------------
CONFIG = {
    "width": 1080,
    "height": 1920,
    "fps": 60,
    "min_duration": 45.0,   # для полной версии ролик подгоняется в этот диапазон
    "max_duration": 60.0,

    "contact_name": "Начальник",
    "contact_initial": None,          # None = первая буква contact_name
    "status_online": "в сети",
    "status_typing": "печатает",
    "date_prefix": "Сегодня",
    "start_time": "23:00",
    "hook": "Начальник пишет в 23:00:\n\"Ты не спишь?\"",
    "hook_seconds": 1.3,
    "final_typing_seconds": 3.0,
    "cta": "Подписывайся на\n«Прочитано и проигнорировано»",
    "cta_seconds": 1.5,
    "final_typing_subtitle": "печатает",

    # Голоса. edge = голос edge-tts; rate в %, pitch в Гц.
    # *_step — насколько меняется голос с каждой следующей репликой этого
    # персонажа (у сотрудницы: медленнее и ниже = всё более уставшая и саркастичная).
    # rhvoice* — офлайн-запасной вариант, если edge-tts недоступен.
    "voices": {
        "boss": {
            "edge": "ru-RU-DmitryNeural", "rate": 10, "pitch": 4,
            "rate_step": 0.0, "pitch_step": 0.0, "volume": 0,
            "rhvoice": "aleksandr-hq", "rh_rate": 112, "rh_pitch": 104,
        },
        "employee": {
            "edge": "ru-RU-SvetlanaNeural", "rate": -4, "pitch": -2,
            "rate_step": -1.5, "pitch_step": -1.0, "volume": 0,
            "rhvoice": "anna", "rh_rate": 98, "rh_pitch": 96,
        },
    },

    "colors": {
        "bg": "#0E1116",
        "header_bg": "#171A21",
        "divider": "#252A33",
        "text": "#FFFFFF",
        "muted": "#8A93A3",
        "status": "#4FA3FF",
        "boss_bubble": "#2C3039",
        "employee_bubble_top": "#FF6F61",
        "employee_bubble_bottom": "#E2434E",
        "typing_dots": "#C9CED8",
        "checks": "#4FA3FF",
        "avatar_top": "#7C83FF",
        "avatar_bottom": "#A35CF0",
        "date_pill": "#1F232B",
        "input_field": "#20242C",
        "subtitle": "#FFFFFF",
        "subtitle_highlight": "#FFE14D",
        "subtitle_stroke": "#000000",
        "hook_text": "#FFFFFF",
        "hook_accent": "#FFE14D",
        "cta_top": "#FF6F61",
        "cta_bottom": "#D93A4A",
    },

    "audio": {
        "voice_rms": 0.14,       # громкость голоса
        "pop_volume": 0.16,      # «поп» на каждое сообщение
        "beat_volume": 0.10,     # фоновый бит
        "beat_duck": 0.45,       # бит приглушается под голосом до этой доли
        "bpm": 92,
    },

    "fonts": {
        "regular": ["fonts/Roboto-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
        "medium": ["fonts/Roboto-Medium.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
        "bold": ["fonts/Roboto-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
        "heavy": ["fonts/Montserrat-ExtraBold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
        "black": ["fonts/Montserrat-Black.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    },
}

SR = 48000          # частота дискретизации аудио
SS = 2              # суперсэмплинг для гладких спрайтов

# Геометрия экрана
HEADER_H = 220
CHAT_TOP = HEADER_H
CHAT_BOTTOM = 1290
INPUT_Y0, INPUT_Y1 = 1290, 1400
SUB_CENTER_Y = 1580
MARGIN = 40
BUBBLE_FONT = 50
BUBBLE_MAX_TEXT_W = 700
BUBBLE_PAD_X, BUBBLE_PAD_Y = 38, 26
BUBBLE_RADIUS, TAIL_RADIUS = 44, 12
META_H = 46
ITEM_GAP = 22
TYPING_W, TYPING_H = 168, 104


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------
def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def clamp(x, a, b):
    return max(a, min(b, x))


def ease_out_cubic(x):
    x = clamp(x, 0.0, 1.0)
    return 1 - (1 - x) ** 3


def ease_out_back(x, s=1.7):
    x = clamp(x, 0.0, 1.0)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


_font_cache = {}


def font(kind, size):
    key = (kind, size)
    if key not in _font_cache:
        for p in CFG["fonts"][kind]:
            path = p if os.path.isabs(p) else os.path.join(HERE, p)
            if os.path.exists(path):
                _font_cache[key] = ImageFont.truetype(path, size)
                break
        else:
            raise SystemExit(f"Не найден шрифт для '{kind}': {CFG['fonts'][kind]}")
    return _font_cache[key]


def wrap_text(text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            cand = (cur + " " + word).strip()
            if fnt.getlength(cand) <= max_w or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def vertical_gradient(w, h, top, bottom):
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    a = np.array(hex_rgb(top), np.float32)
    b = np.array(hex_rgb(bottom), np.float32)
    arr = (a * (1 - t) + b * t).repeat(w, axis=1)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def with_alpha(img, k):
    if k >= 0.999:
        return img
    img = img.copy()
    a = img.getchannel("A").point(lambda v: int(v * k))
    img.putalpha(a)
    return img


def run(cmd, **kw):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-3000:])
        raise SystemExit(f"Команда упала: {' '.join(cmd[:4])} ...")
    return r.stdout


def decode_audio(path):
    raw = run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"])
    return np.frombuffer(raw, dtype=np.float32).copy()


# ---------------------------------------------------------------------------
# Озвучка
# ---------------------------------------------------------------------------
def voice_params(who, nth):
    v = CFG["voices"][who]
    return {
        "edge": v["edge"],
        "rate": v["rate"] + v.get("rate_step", 0) * nth,
        "pitch": v["pitch"] + v.get("pitch_step", 0) * nth,
        "volume": v.get("volume", 0),
        "rhvoice": v.get("rhvoice", "anna"),
        "rh_rate": v.get("rh_rate", 100) + v.get("rh_rate_step", 0) * nth,
        "rh_pitch": v.get("rh_pitch", 100) + v.get("rh_pitch_step", 0) * nth,
    }


def _sgn(x, unit):
    x = int(round(x))
    return f"{'+' if x >= 0 else '-'}{abs(x)}{unit}"


def tts_edge(text, p, out_mp3):
    import edge_tts
    import edge_tts.communicate as ec
    # В сетях с перехватом TLS (корпоративный прокси и т.п.) доверяем
    # дополнительному CA из стандартных переменных окружения.
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        ca = os.environ.get(var)
        if ca and os.path.exists(ca):
            try:
                ec._SSL_CTX.load_verify_locations(ca)
            except Exception:
                pass
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

    async def go():
        kw = dict(rate=_sgn(p["rate"], "%"), pitch=_sgn(p["pitch"], "Hz"),
                  volume=_sgn(p["volume"], "%"))
        try:
            com = edge_tts.Communicate(text, p["edge"], boundary="WordBoundary", proxy=proxy, **kw)
        except TypeError:  # старые версии edge-tts
            com = edge_tts.Communicate(text, p["edge"], proxy=proxy, **kw)
        words = []
        with open(out_mp3, "wb") as f:
            async for ch in com.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append((ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7))
        return words

    words = asyncio.run(asyncio.wait_for(go(), timeout=30))
    return decode_audio(out_mp3), words


def tts_rhvoice(text, p, out_wav):
    exe = shutil.which("RHVoice-test")
    if not exe:
        raise RuntimeError("RHVoice не установлен")
    subprocess.run([exe, "-p", p["rhvoice"], "-r", str(int(p["rh_rate"])),
                    "-t", str(int(p["rh_pitch"])), "-o", out_wav],
                   input=text.encode("utf-8"), check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return decode_audio(out_wav), []   # таймингов слов нет — посчитаем пропорционально


def trim_silence(audio, words, thr=0.012, lead=0.03, tail=0.08):
    """Обрезает тишину по краям и сдвигает тайминги слов."""
    idx = np.where(np.abs(audio) > thr)[0]
    if not len(idx):
        return audio, words
    a = max(0, idx[0] - int(lead * SR))
    b = min(len(audio), idx[-1] + int(tail * SR))
    sh = a / SR
    return audio[a:b], [(w, max(0.0, s - sh), max(0.0, e - sh)) for w, s, e in words]


def synthesize(text, who, nth, eng, cache_dir):
    """Озвучивает реплику одним движком (edge | rhvoice). Бросает RuntimeError при неудаче."""
    import time
    p = voice_params(who, nth)
    key = hashlib.sha1(json.dumps([eng, text, p], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    npy, js = os.path.join(cache_dir, key + ".npy"), os.path.join(cache_dir, key + ".json")
    if os.path.exists(npy) and os.path.exists(js):
        with open(js, encoding="utf-8") as f:
            return trim_silence(np.load(npy), [tuple(w) for w in json.load(f)])
    tmp = os.path.join(cache_dir, key + (".mp3" if eng == "edge" else ".wav"))
    attempts = int(os.environ.get("EDGE_RETRIES", 15)) if eng == "edge" else 1
    last = None
    for k in range(attempts):
        try:
            if eng == "edge":
                audio, words = tts_edge(text, p, tmp)
            else:
                audio, words = tts_rhvoice(text, p, tmp)
            if len(audio) < SR * 0.1:
                raise RuntimeError("пустое аудио")
            break
        except Exception as e:  # noqa
            last = e
            if k + 1 < attempts:
                time.sleep(min(6.0, 1.0 + k))
    else:
        raise RuntimeError(f"{type(last).__name__}: {str(last)[:150]}")
    if os.path.exists(tmp):
        os.remove(tmp)
    audio, words = trim_silence(audio, words)
    np.save(npy, audio.astype(np.float32))
    with open(js, "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False)
    return audio, words


def word_timings(text, words, dur):
    """Возвращает список (токен, начало) для слов текста в секундах от начала реплики."""
    tokens = text.split()
    starts = [None] * len(tokens)
    # смещения токенов в строке
    offs, pos = [], 0
    for tk in tokens:
        i = text.find(tk, pos)
        offs.append(i)
        pos = i + len(tk)
    if words:
        low, cur = text.lower(), 0
        for w, st, _ in words:
            i = low.find(w.lower(), cur)
            if i < 0:
                continue
            cur = i + len(w)
            for k in range(len(tokens)):
                if offs[k] <= i < offs[k] + len(tokens[k]):
                    if starts[k] is None:
                        starts[k] = st
                    break
    if not words or all(s is None for s in starts):
        weights = [len(re.sub(r"\W", "", tk)) + 1.5 for tk in tokens]
        tot = sum(weights)
        acc = 0.0
        for k, wt in enumerate(weights):
            starts[k] = dur * 0.97 * acc / tot
            acc += wt
    # заполняем пропуски
    last = 0.0
    for k in range(len(starts)):
        if starts[k] is None:
            starts[k] = last
        last = starts[k]
    return list(zip(tokens, starts))


# ---------------------------------------------------------------------------
# Таймлайн
# ---------------------------------------------------------------------------
class Msg:
    pass


def build_timeline(lines, pause_add=0.0, typing_k=1.0):
    t = CFG["hook_seconds"] - 0.3
    out = []
    for m in lines:
        typing = clamp(0.5 + 0.012 * len(m.text), 0.55, 1.05) * typing_k
        m.typing_start = t
        m.appear = t + typing
        m.voice_start = m.appear + 0.06
        m.voice_end = m.voice_start + m.dur
        t = m.voice_end + max(0.15, m.pause + pause_add)
        out.append(m)
    final_typing_start = t
    final_typing_end = t + CFG["final_typing_seconds"]
    cta_start = final_typing_end + 0.2
    end = cta_start + CFG["cta_seconds"]
    return final_typing_start, final_typing_end, cta_start, end


# ---------------------------------------------------------------------------
# Графика
# ---------------------------------------------------------------------------
def rounded_mask(w, h, r, tail=None, tail_r=TAIL_RADIUS):
    """Маска пузыря со «срезанным» углом-хвостиком (tail = 'bl' | 'br')."""
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    corners = (True, True, tail != "br", tail != "bl")   # (tl, tr, br, bl)
    d.rounded_rectangle([0, 0, w - 1, h - 1], r, fill=255, corners=corners)
    tr = tail_r * SS
    if tail == "bl":
        d.rectangle([0, h - tr, tr, h - 1], fill=0)
        d.ellipse([0, h - 2 * tr, 2 * tr, h - 1], fill=255)
    elif tail == "br":
        d.rectangle([w - 1 - tr, h - tr, w - 1, h - 1], fill=0)
        d.ellipse([w - 1 - 2 * tr, h - 2 * tr, w - 1, h - 1], fill=255)
    return m


def draw_checks(d, x, y, s, color, width):
    """Две галочки «прочитано» с левым верхним углом в (x, y), размер s."""
    for dx in (0, s * 0.42):
        pts = [(x + dx, y + s * 0.55), (x + dx + s * 0.28, y + s * 0.85), (x + dx + s * 0.85, y + s * 0.15)]
        d.line(pts, fill=color, width=width, joint="curve")


class Sprites:
    def __init__(self, msgs):
        C = CFG["colors"]
        self.W, self.H = CFG["width"], CFG["height"]
        self.msgs = msgs
        self.bubbles = [self.make_bubble(m) for m in msgs]
        self.typing = {who: self.make_typing(who) for who in ("boss", "employee")}
        self.dot = self.make_dot()
        self.date = self.make_date()
        self.base = self.make_base()
        self.header = self.base.crop((0, 0, self.W, HEADER_H))
        self.input = self.base.crop((0, INPUT_Y0, self.W, self.H))
        self.status_online = self.make_status(CFG["status_online"])
        self.status_typing = [self.make_status(CFG["status_typing"] + "." * k) for k in range(4)]
        self.hook = self.make_hook()
        self.cta = self.make_cta()
        self.dim = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 255))
        self.final_sub = [self.make_plain_sub(CFG["final_typing_subtitle"] + "." * k, C["muted"]) for k in range(4)]

    # --- пузырь сообщения -------------------------------------------------
    def make_bubble(self, m):
        C = CFG["colors"]
        f = font("regular", BUBBLE_FONT * SS)
        lines = wrap_text(m.text, f, BUBBLE_MAX_TEXT_W * SS)
        lh = int(BUBBLE_FONT * 1.28 * SS)
        tw = max(f.getlength(l) for l in lines)
        bw = int(tw + 2 * BUBBLE_PAD_X * SS)
        bh = int(lh * len(lines) + 2 * BUBBLE_PAD_Y * SS - (lh - BUBBLE_FONT * 1.12 * SS))
        H = bh + META_H * SS
        img = Image.new("RGBA", (bw, H), (0, 0, 0, 0))
        if m.who == "boss":
            fill = Image.new("RGB", (bw, bh), hex_rgb(C["boss_bubble"]))
            mask = rounded_mask(bw, bh, BUBBLE_RADIUS * SS, "bl")
        else:
            fill = vertical_gradient(bw, bh, C["employee_bubble_top"], C["employee_bubble_bottom"])
            mask = rounded_mask(bw, bh, BUBBLE_RADIUS * SS, "br")
        img.paste(fill, (0, 0), mask)
        d = ImageDraw.Draw(img)
        y = BUBBLE_PAD_Y * SS - int(BUBBLE_FONT * 0.08 * SS)
        for l in lines:
            d.text((BUBBLE_PAD_X * SS, y), l, font=f, fill=C["text"])
            y += lh
        # мета-строка: время (+ галочки у сотрудницы)
        mf = font("regular", 28 * SS)
        my = bh + 10 * SS
        if m.who == "boss":
            d.text((8 * SS, my), m.clock, font=mf, fill=C["muted"])
        else:
            cs = 30 * SS
            cx = bw - 8 * SS - int(cs * 1.27)
            draw_checks(d, cx, my + 2 * SS, cs, C["checks"], 4 * SS)
            tw2 = mf.getlength(m.clock)
            d.text((cx - 10 * SS - tw2, my), m.clock, font=mf, fill=C["muted"])
        img = img.resize((bw // SS, H // SS), Image.LANCZOS)
        x = MARGIN if m.who == "boss" else self.W - MARGIN - img.width
        return {"img": img, "x": x, "h": img.height, "bh": bh // SS}

    def make_typing(self, who):
        C = CFG["colors"]
        w, h = TYPING_W * SS, TYPING_H * SS
        if who == "boss":
            fill = Image.new("RGB", (w, h), hex_rgb(C["boss_bubble"]))
            mask = rounded_mask(w, h, BUBBLE_RADIUS * SS, "bl")
        else:
            fill = vertical_gradient(w, h, C["employee_bubble_top"], C["employee_bubble_bottom"])
            mask = rounded_mask(w, h, BUBBLE_RADIUS * SS, "br")
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.paste(fill, (0, 0), mask)
        img = img.resize((TYPING_W, TYPING_H), Image.LANCZOS)
        x = MARGIN if who == "boss" else self.W - MARGIN - TYPING_W
        dot_color = C["typing_dots"] if who == "boss" else "#FFFFFF"
        return {"img": img, "x": x, "dot_color": dot_color}

    def make_dot(self):
        r = 11
        img = Image.new("RGBA", (r * 2 * SS, r * 2 * SS), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([0, 0, r * 2 * SS - 1, r * 2 * SS - 1], fill=(255, 255, 255, 255))
        return img.resize((r * 2, r * 2), Image.LANCZOS)

    def make_date(self):
        C = CFG["colors"]
        f = font("medium", 30 * SS)
        txt = f"{CFG['date_prefix']}, {CFG['start_time']}"
        tw = f.getlength(txt)
        w, h = int(tw + 48 * SS), 58 * SS
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w - 1, h - 1], h // 2, fill=C["date_pill"])
        d.text((w / 2, h / 2), txt, font=f, fill=C["muted"], anchor="mm")
        img = img.resize((w // SS, h // SS), Image.LANCZOS)
        return {"img": img, "x": (self.W - img.width) // 2, "h": img.height}

    # --- статичный фон с шапкой и полем ввода --------------------------------
    def make_base(self):
        C = CFG["colors"]
        W, H = self.W * SS, self.H * SS
        img = Image.new("RGB", (W, H), C["bg"])
        d = ImageDraw.Draw(img)
        # лёгкий узор на фоне чата
        rng = np.random.default_rng(7)
        bgc = hex_rgb(C["bg"])
        dotc = tuple(min(255, c + 9) for c in bgc)
        for _ in range(140):
            x, y = rng.integers(0, W), rng.integers(HEADER_H * SS, INPUT_Y0 * SS)
            r = int(rng.integers(3, 7)) * SS
            d.ellipse([x - r, y - r, x + r, y + r], fill=dotc)
        # шапка
        d.rectangle([0, 0, W, HEADER_H * SS], fill=C["header_bg"])
        d.rectangle([0, HEADER_H * SS - 2 * SS, W, HEADER_H * SS], fill=C["divider"])
        cy = 128 * SS
        # стрелка «назад»
        d.line([(62 * SS, cy - 26 * SS), (38 * SS, cy), (62 * SS, cy + 26 * SS)],
               fill=C["status"], width=6 * SS, joint="curve")
        # аватар
        ar = 58 * SS
        ax = 150 * SS
        av = vertical_gradient(2 * ar, 2 * ar, C["avatar_top"], C["avatar_bottom"])
        am = Image.new("L", (2 * ar, 2 * ar), 0)
        ImageDraw.Draw(am).ellipse([0, 0, 2 * ar - 1, 2 * ar - 1], fill=255)
        img.paste(av, (ax - ar, cy - ar), am)
        initial = CFG.get("contact_initial") or CFG["contact_name"][:1].upper()
        d.text((ax, cy + 2 * SS), initial, font=font("heavy", 56 * SS), fill="#FFFFFF", anchor="mm")
        # имя
        d.text((232 * SS, cy - 8 * SS), CFG["contact_name"], font=font("bold", 46 * SS),
               fill=C["text"], anchor="ls")
        # иконки справа: трубка (упрощённо) и «⋮»
        for k in range(3):
            yy = cy - 22 * SS + k * 22 * SS
            d.ellipse([1028 * SS - 5 * SS, yy - 5 * SS, 1028 * SS + 5 * SS, yy + 5 * SS], fill=C["muted"])
        px, py = 930 * SS, cy
        d.rounded_rectangle([px - 26 * SS, py - 18 * SS, px + 14 * SS, py + 18 * SS], 8 * SS, outline=C["muted"], width=5 * SS)
        d.polygon([(px + 18 * SS, py - 4 * SS), (px + 34 * SS, py - 14 * SS), (px + 34 * SS, py + 14 * SS), (px + 18 * SS, py + 4 * SS)], fill=C["muted"])
        # поле ввода
        d.rectangle([0, INPUT_Y0 * SS, W, INPUT_Y1 * SS], fill=C["header_bg"])
        d.rectangle([0, INPUT_Y0 * SS, W, INPUT_Y0 * SS + 2 * SS], fill=C["divider"])
        fy0, fy1 = INPUT_Y0 * SS + 18 * SS, INPUT_Y1 * SS - 18 * SS
        d.rounded_rectangle([MARGIN * SS, fy0, 930 * SS, fy1], (fy1 - fy0) // 2, fill=C["input_field"])
        d.text((MARGIN * SS + 34 * SS, (fy0 + fy1) // 2), "Сообщение", font=font("regular", 36 * SS),
               fill=C["muted"], anchor="lm")
        bx, by, br = 990 * SS, (fy0 + fy1) // 2, 37 * SS
        btn = vertical_gradient(2 * br, 2 * br, C["employee_bubble_top"], C["employee_bubble_bottom"])
        bm = Image.new("L", (2 * br, 2 * br), 0)
        ImageDraw.Draw(bm).ellipse([0, 0, 2 * br - 1, 2 * br - 1], fill=255)
        img.paste(btn, (bx - br, by - br), bm)
        d.polygon([(bx - 14 * SS, by - 16 * SS), (bx + 18 * SS, by), (bx - 14 * SS, by + 16 * SS), (bx - 8 * SS, by)], fill="#FFFFFF")
        # зона субтитров — чуть темнее
        d.rectangle([0, INPUT_Y1 * SS, W, H], fill=tuple(max(0, c - 4) for c in hex_rgb(C["bg"])))
        return img.resize((self.W, self.H), Image.LANCZOS)

    def make_status(self, txt):
        f = font("regular", 33 * SS)
        w = int(f.getlength(CFG["status_typing"] + "...") + 20 * SS)
        w = max(w, int(f.getlength(txt) + 20 * SS))
        img = Image.new("RGBA", (w, 50 * SS), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((0, 40 * SS), txt, font=f, fill=CFG["colors"]["status"], anchor="ls")
        return img.resize((w // SS, 50), Image.LANCZOS)

    # --- заголовок-крючок и финальная плашка --------------------------------
    def _big_text(self, text, kind, size, max_w, colors, stroke=0):
        paras = text.split("\n")
        while True:
            f = font(kind, size)
            lines = []  # (text, color)
            for i, para in enumerate(paras):
                col = colors[min(i, len(colors) - 1)] if len(paras) > 1 else colors[0]
                for l in wrap_text(para, f, max_w):
                    lines.append((l, col))
            widest = max(f.getlength(l) for l, _ in lines)
            if widest <= max_w or size < 30:
                break
            size -= 4
        lh = int(size * 1.18)
        w = int(widest + 2 * stroke + 8)
        h = lh * len(lines) + 2 * stroke + int(size * 0.3)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y = stroke
        for l, col in lines:
            d.text((w / 2, y), l, font=f, fill=col, anchor="ma",
                   stroke_width=stroke, stroke_fill=CFG["colors"]["subtitle_stroke"])
            y += lh
        return img

    def make_hook(self):
        C = CFG["colors"]
        return self._big_text(CFG["hook"], "black", 92, 960, [C["hook_text"], C["hook_accent"]], stroke=6)

    def make_cta(self):
        C = CFG["colors"]
        txt = self._big_text(CFG["cta"], "heavy", 64, 860, ["#FFFFFF"], stroke=0)
        pw, ph = txt.width + 120, txt.height + 110
        S = SS
        plate = Image.new("RGBA", (pw * S, ph * S), (0, 0, 0, 0))
        grad = vertical_gradient(pw * S, ph * S, C["cta_top"], C["cta_bottom"])
        m = Image.new("L", (pw * S, ph * S), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, pw * S - 1, ph * S - 1], 56 * S, fill=255)
        plate.paste(grad, (0, 0), m)
        plate = plate.resize((pw, ph), Image.LANCZOS)
        plate.alpha_composite(txt, ((pw - txt.width) // 2, (ph - txt.height) // 2 + 6))
        return plate

    def make_plain_sub(self, txt, color):
        f = font("heavy", 70)
        w = int(f.getlength(CFG["final_typing_subtitle"] + "...") + 40)
        img = Image.new("RGBA", (w, 110), (0, 0, 0, 0))
        base_w = f.getlength(CFG["final_typing_subtitle"])
        ImageDraw.Draw(img).text(((w - base_w) / 2, 10), txt, font=f, fill=color,
                                 stroke_width=6, stroke_fill=CFG["colors"]["subtitle_stroke"])
        return img


# ---------------------------------------------------------------------------
# Субтитры с подсветкой текущего слова
# ---------------------------------------------------------------------------
SUB_FONT = 76
SUB_MAX_W = 920
SUB_STROKE = 7


class Subtitles:
    def __init__(self, msgs):
        self.msgs = msgs
        self.layouts = {}
        self.cache = {}

    def layout(self, i):
        if i in self.layouts:
            return self.layouts[i]
        f = font("heavy", SUB_FONT)
        toks = [w for w, _ in self.msgs[i].timings]
        space = f.getlength(" ")
        rows, cur, cur_w = [], [], 0.0
        for k, tk in enumerate(toks):
            tw = f.getlength(tk)
            add = tw if not cur else cur_w + space + tw
            if cur and add > SUB_MAX_W:
                rows.append((cur, cur_w))
                cur, cur_w = [k], tw
            else:
                cur.append(k)
                cur_w = add
        if cur:
            rows.append((cur, cur_w))
        lh = int(SUB_FONT * 1.2)
        W = SUB_MAX_W + 2 * SUB_STROKE + 40
        H = lh * len(rows) + 2 * SUB_STROKE + 20
        pos = {}
        for r, (ks, rw) in enumerate(rows):
            x = (W - rw) / 2
            for k in ks:
                pos[k] = (x, SUB_STROKE + r * lh)
                x += f.getlength(toks[k]) + space
        self.layouts[i] = (W, H, pos, toks)
        return self.layouts[i]

    def image(self, i, active):
        key = (i, active)
        if key not in self.cache:
            C = CFG["colors"]
            W, H, pos, toks = self.layout(i)
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            f = font("heavy", SUB_FONT)
            for k, tk in enumerate(toks):
                col = C["subtitle_highlight"] if k == active else C["subtitle"]
                d.text(pos[k], tk, font=f, fill=col, stroke_width=SUB_STROKE, stroke_fill=C["subtitle_stroke"])
            self.cache[key] = img
        return self.cache[key]


# ---------------------------------------------------------------------------
# Рендер кадров
# ---------------------------------------------------------------------------
class Scene:
    def __init__(self, msgs, final_start, final_end, cta_start, end):
        self.msgs = msgs
        self.final_start, self.final_end = final_start, final_end
        self.cta_start, self.end = cta_start, end
        self.sp = Sprites(msgs)
        self.subs = Subtitles(msgs)
        self.fps = CFG["fps"]
        self.n_frames = int(math.ceil(end * self.fps))
        # раскладка ленты чата
        y = 24
        self.date_y = y
        y += self.sp.date["h"] + 30
        self.msg_y = []
        for b in self.sp.bubbles:
            self.msg_y.append(y)
            y += b["h"] + ITEM_GAP
        self.final_y = y
        self.compute_scroll()

    def compute_scroll(self):
        vh = CHAT_BOTTOM - CHAT_TOP - 16
        events = []
        for i, m in enumerate(self.msgs):
            events.append((m.typing_start, self.msg_y[i] + TYPING_H))
            events.append((m.appear, self.msg_y[i] + self.sp.bubbles[i]["h"]))
        events.append((self.final_start, self.final_y + TYPING_H))
        events = [(t, max(0.0, bottom - vh)) for t, bottom in events]
        D = 0.32
        self.scroll = np.zeros(self.n_frames + 1)
        cur, frm, t0, tgt, ei = 0.0, 0.0, -10.0, 0.0, 0
        for f in range(self.n_frames + 1):
            t = f / self.fps
            while ei < len(events) and events[ei][0] <= t:
                frm, t0, tgt = cur, events[ei][0], events[ei][1]
                ei += 1
            cur = frm + (tgt - frm) * ease_out_cubic((t - t0) / D)
            self.scroll[f] = cur

    def paste_typing(self, frame, who, y, t_local):
        tp = self.sp.typing[who]
        k = ease_out_cubic(t_local / 0.15)
        img = tp["img"]
        if k < 1:
            img = with_alpha(img.resize((max(1, int(img.width * (0.7 + 0.3 * k))), max(1, int(img.height * (0.7 + 0.3 * k))))), k)
        x = tp["x"] if who == "boss" else tp["x"] + TYPING_W - img.width
        yy = int(y + TYPING_H - img.height)
        frame.paste(img, (x, yy), img)
        if k < 1:
            return
        dot = self.sp.dot
        col = Image.new("RGBA", dot.size, hex_rgb(tp["dot_color"]) + (255,))
        for i in range(3):
            ph = (t_local * 1.4 - i * 0.18) % 1.0
            bounce = math.sin(ph * math.pi * 2) if ph < 0.5 else 0.0
            a = 0.45 + 0.55 * max(0.0, bounce)
            dx = tp["x"] + 40 + i * 34
            dy = int(y + TYPING_H / 2 - dot.height / 2 - 9 * max(0.0, bounce))
            mask = with_alpha(dot, a).getchannel("A")
            frame.paste(col, (dx, dy), mask)

    def render(self, f):
        t = f / self.fps
        sp = self.sp
        frame = sp.base.copy()
        off = CHAT_TOP - self.scroll[f]
        # дата
        dy = self.date_y + off
        if dy > CHAT_TOP - 80:
            frame.paste(sp.date["img"], (sp.date["x"], int(dy)), sp.date["img"])
        # сообщения
        boss_typing = False
        for i, m in enumerate(self.msgs):
            y = self.msg_y[i] + off
            if t < m.typing_start:
                break
            b = sp.bubbles[i]
            if t < m.appear:
                if m.who == "boss":
                    boss_typing = True
                self.paste_typing(frame, m.who, y, t - m.typing_start)
                continue
            if y + b["h"] < CHAT_TOP or y > CHAT_BOTTOM:
                continue
            a = (t - m.appear) / 0.28
            img, x = b["img"], b["x"]
            if a < 1:
                k = ease_out_back(a)
                sc = 0.82 + 0.18 * k
                w2, h2 = max(1, int(img.width * sc)), max(1, int(img.height * sc))
                img = with_alpha(img.resize((w2, h2), Image.BILINEAR), clamp(a * 2.2, 0, 1))
                if m.who == "employee":
                    x = b["x"] + b["img"].width - w2 + int(50 * (1 - k))
                else:
                    x = b["x"] - int(50 * (1 - k))
                y = y + (b["img"].height - h2) + int(36 * (1 - ease_out_cubic(a)))
            frame.paste(img, (int(x), int(y)), img)
        # финальное «печатает...» сотрудницы
        if self.final_start <= t < self.final_end:
            self.paste_typing(frame, "employee", self.final_y + off, t - self.final_start)
        # шапка и поле ввода поверх ленты
        frame.paste(sp.header, (0, 0))
        frame.paste(sp.input, (0, INPUT_Y0))
        st = sp.status_typing[int(t / 0.3) % 4] if boss_typing else sp.status_online
        frame.paste(st, (233, 128 + 6), st)
        # субтитры
        for i, m in enumerate(self.msgs):
            hold = min(0.35, m.pause)
            if m.voice_start <= t < m.voice_end + hold:
                lt = t - m.voice_start
                active = 0
                for k, (_, s) in enumerate(m.timings):
                    if s <= lt:
                        active = k
                if t >= m.voice_end:
                    active = -1
                img = self.subs.image(i, active)
                pa = (t - m.voice_start) / 0.14
                if pa < 1:
                    sc = 0.86 + 0.14 * ease_out_back(pa)
                    img = img.resize((int(img.width * sc), int(img.height * sc)), Image.BILINEAR)
                frame.paste(img, ((self.sp.W - img.width) // 2, SUB_CENTER_Y - img.height // 2), img)
                break
        if self.final_start + 0.2 <= t < self.final_end:
            img = sp.final_sub[int((t - self.final_start) / 0.35) % 4]
            frame.paste(img, ((sp.W - img.width) // 2, SUB_CENTER_Y - img.height // 2), img)
        # заголовок-крючок
        hs = CFG["hook_seconds"]
        if t < hs:
            fade = 1.0 if t < hs - 0.3 else (hs - t) / 0.3
            frame = frame.convert("RGBA")
            frame.alpha_composite(with_alpha(sp.dim, 0.74 * fade))
            k = ease_out_back(t / 0.22)
            img = sp.hook
            sc = 0.8 + 0.2 * k
            img = with_alpha(img.resize((int(img.width * sc), int(img.height * sc)), Image.BILINEAR), fade * clamp(t / 0.1, 0, 1))
            frame.alpha_composite(img, ((sp.W - img.width) // 2, (sp.H - img.height) // 2 - 80))
            frame = frame.convert("RGB")
        # финальная плашка
        if t >= self.cta_start:
            lt = t - self.cta_start
            frame = frame.convert("RGBA")
            frame.alpha_composite(with_alpha(sp.dim, 0.7 * clamp(lt / 0.2, 0, 1)))
            k = ease_out_back(lt / 0.3)
            img = sp.cta
            sc = 0.7 + 0.3 * k
            img = with_alpha(img.resize((int(img.width * sc), int(img.height * sc)), Image.BILINEAR), clamp(lt / 0.12, 0, 1))
            frame.alpha_composite(img, ((sp.W - img.width) // 2, (sp.H - img.height) // 2 - 80))
            frame = frame.convert("RGB")
        return frame


SCENE = None


def render_segment(args):
    a, b, path = args
    W, H, fps = CFG["width"], CFG["height"], CFG["fps"]
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-threads", "2", "-g", str(fps * 2), path],
        stdin=subprocess.PIPE)
    for f in range(a, b):
        p.stdin.write(SCENE.render(f).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg (видео) упал")
    return b - a


# ---------------------------------------------------------------------------
# Звук
# ---------------------------------------------------------------------------
def make_pop():
    n = int(0.08 * SR)
    t = np.arange(n) / SR
    freq = 520 + 900 * np.exp(-t * 45)
    ph = 2 * np.pi * np.cumsum(freq) / SR
    env = np.exp(-t * 55) * (1 - np.exp(-t * 2000))
    return (np.sin(ph) * env).astype(np.float32)


def make_beat(dur, bpm):
    n = int(dur * SR)
    out = np.zeros(n, np.float32)
    rng = np.random.default_rng(1)
    beat = 60.0 / bpm
    def add(sig, t0, g=1.0):
        i = int(t0 * SR)
        if i >= n:
            return
        j = min(n, i + len(sig))
        out[i:j] += sig[: j - i] * g
    # кик
    kt = np.arange(int(0.35 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(48 + 110 * np.exp(-kt * 28)) / SR) * np.exp(-kt * 9)
    # снейр/клэп
    st = np.arange(int(0.2 * SR)) / SR
    noise = rng.standard_normal(len(st))
    snare = (np.diff(noise, prepend=0) * 0.5 * np.exp(-st * 22) + 0.3 * np.sin(2 * np.pi * 190 * st) * np.exp(-st * 30))
    # хэт
    ht = np.arange(int(0.05 * SR)) / SR
    hat = np.diff(np.diff(rng.standard_normal(len(ht)), prepend=0), prepend=0) * 0.12 * np.exp(-ht * 90)
    # гармония: Am - F - C - G
    roots = [110.0, 87.31, 130.81, 98.0]
    chords = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [196.0, 261.63, 329.63], [196.0, 246.94, 293.66]]
    bar = beat * 4
    nbars = int(dur / bar) + 2
    for b in range(nbars):
        t0 = b * bar
        ci = b % 4
        for q in range(4):
            tq = t0 + q * beat
            if q in (0, 2):
                add(kick, tq, 0.9)
            if q == 2 and b % 2 == 1:
                add(kick, tq + beat * 0.5, 0.6)
            if q in (1, 3):
                add(snare, tq, 0.55)
            for e in (0, 0.5):
                add(hat, tq + e * beat, 0.9 if e == 0.5 else 0.5)
        # бас
        bt = np.arange(int(bar * SR)) / SR
        bass = np.sin(2 * np.pi * roots[ci] * bt) * (0.6 + 0.4 * np.exp(-((bt % beat) * 6)))
        add(bass * 0.35 * np.minimum(1, (bar - bt) * 20), t0)
        # мягкий пэд
        pad = sum(np.sin(2 * np.pi * fq * bt) + 0.3 * np.sin(4 * np.pi * fq * bt) for fq in chords[ci])
        penv = np.minimum(1, bt / 0.4) * np.minimum(1, (bar - bt) / 0.3)
        add(pad * penv * 0.07, t0)
    out /= max(1e-6, np.abs(out).max())
    return out


def build_audio(scene, path):
    A = CFG["audio"]
    n = int(scene.end * SR) + SR
    voice = np.zeros(n, np.float32)
    duck = np.zeros(n, np.float32)
    for m in scene.msgs:
        a = m.audio
        rms = np.sqrt(np.mean(a ** 2)) + 1e-9
        a = a * (A["voice_rms"] / rms)
        pk = np.abs(a).max()
        if pk > 0.95:
            a = a * (0.95 / pk)
        i = int(m.voice_start * SR)
        j = min(n, i + len(a))
        voice[i:j] += a[: j - i]
        duck[i:j] = 1.0
    sfx = np.zeros(n, np.float32)
    pop = make_pop() * A["pop_volume"]
    for m in scene.msgs:
        i = int(m.appear * SR)
        sfx[i:i + len(pop)] += pop[: max(0, min(len(pop), n - i))]
    i = int(scene.cta_start * SR)
    sfx[i:i + len(pop)] += pop[: max(0, min(len(pop), n - i))] * 1.3
    # сглаживаем огибающую приглушения
    k = int(0.15 * SR)
    duck = np.convolve(duck, np.ones(k) / k, mode="same")
    beat = make_beat(scene.end + 1, A["bpm"]) [:n] * A["beat_volume"]
    beat *= 1 - (1 - A["beat_duck"]) * np.clip(duck, 0, 1)
    fade_n = int(0.6 * SR)
    end_i = int(scene.end * SR)
    beat[max(0, end_i - fade_n):end_i] *= np.linspace(1, 0, min(fade_n, end_i))
    beat[end_i:] = 0
    beat[: int(0.05 * SR)] *= np.linspace(0, 1, int(0.05 * SR))
    mix = (voice + sfx + beat)[:end_i]
    pk = np.abs(mix).max()
    if pk > 0.98:
        mix = np.tanh(mix / pk * 1.5) / np.tanh(1.5) * 0.98
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())


# ---------------------------------------------------------------------------
def clock_add(start, minutes):
    h, m = map(int, start.split(":"))
    tot = (h * 60 + m + minutes) % (24 * 60)
    return f"{tot // 60:02d}:{tot % 60:02d}"


def main():
    global CFG, SCENE
    ap = argparse.ArgumentParser(description="Видео-переписка в мессенджере")
    ap.add_argument("script", help="путь к script.json")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--limit", type=int, default=0, help="взять только первые N реплик (пробная версия)")
    ap.add_argument("--tts", choices=["auto", "edge", "rhvoice"], default="auto",
                    help="движок озвучки: auto = edge-tts, при недоступности RHVoice")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--no-fit", action="store_true", help="не подгонять длительность под 45–60 с")
    args = ap.parse_args()

    with open(args.script, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        data = {"lines": data}
    lines = data.pop("lines")
    CFG = deep_merge(CONFIG, data)
    if args.limit:
        lines = lines[: args.limit]

    if not shutil.which("ffmpeg"):
        raise SystemExit("Нужен ffmpeg в PATH")

    cache_dir = os.path.join(HERE, ".cache", "tts")
    os.makedirs(cache_dir, exist_ok=True)

    print(f"[1/4] Озвучка {len(lines)} реплик...")
    msgs = []
    for i, L in enumerate(lines):
        m = Msg()
        m.who = L["who"]
        if m.who not in ("boss", "employee"):
            raise SystemExit(f"Реплика {i + 1}: who должен быть boss или employee")
        m.text = L["text"].strip()
        m.pause = float(L.get("pause_after", 0.3))
        m.clock = clock_add(CFG["start_time"], i // 3)
        msgs.append(m)
    # весь ролик озвучивается ОДНИМ движком, чтобы голоса не скакали
    engines = {"edge": ["edge"], "rhvoice": ["rhvoice"], "auto": ["edge", "rhvoice"]}[args.tts]
    used = None
    for eng in engines:
        try:
            nth = {"boss": 0, "employee": 0}
            for m in msgs:
                m.audio, words = synthesize(m.text, m.who, nth[m.who], eng, cache_dir)
                nth[m.who] += 1
                m.dur = len(m.audio) / SR
                m.timings = word_timings(m.text, words, m.dur)
            used = eng
            break
        except RuntimeError as e:
            print(f"  ! {eng}: не удалось озвучить «{m.text}» ({e})")
            if eng != engines[-1]:
                print("    Озвучиваю весь ролик запасным движком RHVoice.")
    if used is None:
        raise SystemExit("Озвучка не удалась ни одним движком.")
    engines_used = {used}
    for i, m in enumerate(msgs):
        print(f"   {i + 1:2d}. {m.who:8s} {m.dur:4.1f}s  {m.text}")

    timing = build_timeline(msgs)
    if not args.limit and not args.no_fit:
        lo, hi = CFG["min_duration"], CFG["max_duration"]
        end = timing[3]
        if end < lo:
            timing = build_timeline(msgs, pause_add=(lo - end + 0.3) / len(msgs))
        elif end > hi:
            for k in np.linspace(0.95, 0.5, 10):
                timing = build_timeline(msgs, pause_add=-(1 - k) * 0.6, typing_k=k)
                if timing[3] <= hi:
                    break
            if timing[3] > hi:
                print(f"   ! Ролик длиннее {hi:.0f} с ({timing[3]:.1f} с) — сократите сценарий.")
    final_start, final_end, cta_start, end = timing
    print(f"   длительность: {end:.1f} с, озвучка: {', '.join(sorted(engines_used))}")

    print("[2/4] Подготовка графики...")
    SCENE = Scene(msgs, final_start, final_end, cta_start, end)

    tmp = tempfile.mkdtemp(prefix="chatvid_")
    try:
        print("[3/4] Звук...")
        wav = os.path.join(tmp, "audio.wav")
        build_audio(SCENE, wav)

        n = SCENE.n_frames
        workers = max(1, min(args.workers, n // 60 or 1))
        print(f"[4/4] Рендер {n} кадров ({CFG['fps']} fps) в {workers} потоков...")
        bounds = np.linspace(0, n, workers + 1).astype(int)
        jobs = [(int(bounds[k]), int(bounds[k + 1]), os.path.join(tmp, f"seg{k:02d}.mp4")) for k in range(workers)]
        if workers == 1:
            render_segment(jobs[0])
        else:
            import multiprocessing as mp
            ctx = mp.get_context("fork")
            with ctx.Pool(workers) as pool:
                pool.map(render_segment, jobs)
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            for _, _, p in jobs:
                f.write(f"file '{p}'\n")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-i", wav,
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-t", f"{end:.3f}", "-movflags", "+faststart", args.output])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"Готово: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
