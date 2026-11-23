#!/usr/bin/env python3
"""
Генератор вертикального видео «фейковая переписка в мессенджере».

    python generate.py script.json                 -> output.mp4
    python generate.py script.json -o demo.mp4 -n 5  (только первые 5 реплик)

Сценарий и настройки лежат в JSON (см. script.json). Код править не нужно.
Зависимости: Pillow, numpy, edge-tts, ffmpeg в PATH (python-пакеты ставятся сами).
"""
from __future__ import annotations

import argparse
import asyncio
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
from dataclasses import dataclass, field
import multiprocessing as mp


# --------------------------------------------------------------------------- #
#  Автоустановка зависимостей
# --------------------------------------------------------------------------- #
def _ensure(pkg: str, import_name: str | None = None):
    try:
        return __import__(import_name or pkg)
    except ImportError:
        print(f"[setup] устанавливаю {pkg} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
        return __import__(import_name or pkg)


np = _ensure("numpy")
_ensure("Pillow", "PIL")
edge_tts = _ensure("edge-tts", "edge_tts")
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

if not shutil.which("ffmpeg"):
    sys.exit("Не найден ffmpeg. Установите его: https://ffmpeg.org/download.html "
             "(Windows: winget install ffmpeg, macOS: brew install ffmpeg, Linux: apt install ffmpeg)")

# --------------------------------------------------------------------------- #
#  Константы и тема
# --------------------------------------------------------------------------- #
W, H, FPS = 1080, 1920, 60
SR = 48000  # частота дискретизации звука

DEFAULT_THEME = {
    "bg": "#0D1117",              # фон всего кадра
    "wallpaper": "#10151C",       # фон чата
    "wallpaper_dots": "#18202A",  # узор на фоне чата
    "header": "#171C24",          # шапка
    "header_text": "#FFFFFF",
    "status_online": "#8A96A8",
    "status_typing": "#5FB3FF",
    "client_bubble": ["#2F6BFF", "#7B4DFF"],  # градиент пузыря клиента (справа)
    "master_bubble": "#232A35",               # пузырь мастера (слева)
    "client_text": "#FFFFFF",
    "master_text": "#E9EDF2",
    "time_client": "#D6DEFF",
    "time_master": "#7F8A9B",
    "avatar": ["#FF8A3D", "#FF3D6E"],
    "input_bg": "#1C222C",
    "input_text": "#FFFFFF",
    "input_placeholder": "#6B7586",
    "accent": "#3D7BFF",
    "chip_bg": "#1E2530",
    "chip_text": "#AEB8C7",
    "sub_text": "#FFFFFF",
    "sub_highlight": "#FFD84D",
    "sub_stroke": "#000000",
    "hook_text": "#FFFFFF",
    "hook_highlight": "#FFD84D",
    "cta_card": "#1A2029",
    "cta_button": "#FF3B47",
}

DEFAULT_VOICES = {
    "client": {"voice": "ru-RU-SvetlanaNeural", "rate": "+25%", "pitch": "+0Hz"},
    "master": {"voice": "ru-RU-DmitryNeural", "rate": "+20%", "pitch": "-2Hz"},
}

# Геометрия экрана
STATUSBAR_H = 64
HEADER_TOP, HEADER_BOTTOM = STATUSBAR_H, 210
CHAT_TOP, CHAT_BOTTOM = HEADER_BOTTOM, 1290
CHAT_H = CHAT_BOTTOM - CHAT_TOP
INPUT_TOP, INPUT_BOTTOM = CHAT_BOTTOM, 1395
SUB_CY = 1545            # центр субтитров по вертикали
SUB_MAX_W = 960
SIDE_PAD = 34            # отступ пузырей от краёв
BUBBLE_MAX_TEXT_W = 700
BUBBLE_GAP = 16


# --------------------------------------------------------------------------- #
#  Утилиты
# --------------------------------------------------------------------------- #
def hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(h: str, a: int = 255):
    return (*hex2rgb(h), a)


def clamp(x, a, b):
    return a if x < a else b if x > b else x


def ease_out_cubic(x):
    x = clamp(x, 0.0, 1.0)
    return 1 - (1 - x) ** 3


def ease_out_back(x, s=1.7):
    x = clamp(x, 0.0, 1.0)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def ease_in_out(x):
    x = clamp(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


FONT_CANDIDATES = {
    "regular": ["Inter-Regular.otf", "Inter-Regular.ttf", "Roboto-Regular.ttf", "SegoeUI.ttf", "segoeui.ttf",
                "arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "medium": ["Inter-Medium.otf", "Inter-Medium.ttf", "Roboto-Medium.ttf", "seguisb.ttf", "SegoeUI-Semibold.ttf",
               "arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "bold": ["Inter-Bold.otf", "Inter-Bold.ttf", "Roboto-Bold.ttf", "segoeuib.ttf", "arialbd.ttf",
             "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "black": ["Inter-Black.otf", "Inter-Black.ttf", "Inter-ExtraBold.otf", "Roboto-Black.ttf", "ariblk.ttf",
              "Arial Black.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
}
FONT_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
             os.path.expanduser("~/.local/share/fonts"), "/Library/Fonts", "/System/Library/Fonts",
             os.path.expanduser("~/Library/Fonts"), "C:/Windows/Fonts",
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")]
_font_index: dict[str, str] | None = None
_font_cache: dict = {}
FONT_OVERRIDE: dict[str, str] = {}


def _find_font(weight: str) -> str:
    global _font_index
    if weight in FONT_OVERRIDE:
        return FONT_OVERRIDE[weight]
    if _font_index is None:
        _font_index = {}
        for d in FONT_DIRS:
            if os.path.isdir(d):
                for root, _, files in os.walk(d):
                    for f in files:
                        _font_index.setdefault(f.lower(), os.path.join(root, f))
    for name in FONT_CANDIDATES[weight]:
        p = _font_index.get(name.lower())
        if p:
            return p
    sys.exit("Не найден шрифт с кириллицей. Положите, например, Inter-*.otf в папку fonts/ рядом со скриптом.")


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(_find_font(weight), size)
    return _font_cache[key]


def wrap(text: str, fnt, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if fnt.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def rounded_mask(w: int, h: int, radii, ss: int = 3) -> Image.Image:
    """Сглаженная маска скруглённого прямоугольника с разными углами (tl,tr,br,bl)."""
    big = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(big)
    d.rectangle([0, 0, w * ss, h * ss], fill=255)
    for i, r in enumerate(radii):
        r = int(r * ss)
        if r <= 0:
            continue
        corner = Image.new("L", (r, r), 0)
        cd = ImageDraw.Draw(corner)
        cd.pieslice([0, 0, 2 * r, 2 * r], 180, 270, fill=255)
        # i: 0=tl,1=tr,2=br,3=bl
        rot = {0: corner, 1: corner.transpose(Image.FLIP_LEFT_RIGHT),
               2: corner.transpose(Image.ROTATE_180), 3: corner.transpose(Image.FLIP_TOP_BOTTOM)}[i]
        pos = {0: (0, 0), 1: (w * ss - r, 0), 2: (w * ss - r, h * ss - r), 3: (0, h * ss - r)}[i]
        big.paste(rot, pos)
    return big.resize((w, h), Image.LANCZOS)


def gradient(w: int, h: int, c1: str, c2: str, diagonal=True) -> Image.Image:
    a, b = np.array(hex2rgb(c1), float), np.array(hex2rgb(c2), float)
    xs = np.linspace(0, 1, w)[None, :]
    ys = np.linspace(0, 1, h)[:, None]
    t = (xs * 0.7 + ys * 0.3) if diagonal else np.broadcast_to(ys, (h, w))
    arr = a[None, None, :] * (1 - t[..., None]) + b[None, None, :] * t[..., None]
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def norm_word(s: str) -> str:
    return re.sub(r"[^0-9a-zа-я]", "", s.lower().replace("ё", "е"))


def parse_marked(text: str) -> list[tuple[str, bool]]:
    """'Текст с *выделением*' -> [(слово, выделено)]."""
    out, hl = [], False
    for part in re.split(r"(\*)", text):
        if part == "*":
            hl = not hl
            continue
        for w in part.split():
            out.append((w, hl))
    return out


# --------------------------------------------------------------------------- #
#  Озвучка (edge-tts) с кэшем
# --------------------------------------------------------------------------- #
def _patch_edge_tts_ssl():
    """В средах с корпоративным/прокси-сертификатом edge-tts по умолчанию его не видит."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        try:
            import ssl
            import edge_tts.communicate as cm
            cm._SSL_CTX = ssl.create_default_context(cafile=ca)
        except Exception:
            pass


def _signed(val: str, delta: int, unit: str) -> str:
    m = re.match(r"([+-]?\d+)", val or "0")
    n = int(m.group(1)) if m else 0
    n += delta
    return f"{'+' if n >= 0 else ''}{n}{unit}"


def voice_params(line: dict, voices: dict) -> tuple[str, str, str]:
    base = voices[line["who"]]
    voice = line.get("voice", base["voice"])
    rate = base.get("rate", "+0%")
    pitch = base.get("pitch", "+0Hz")
    t = line["text"]
    # Немного «живости»: эмоция по пунктуации, если не задано вручную
    if "rate" not in line:
        if t.rstrip().endswith("!"):
            rate = _signed(rate, 6, "%")
        elif "..." in t or "…" in t:
            rate = _signed(rate, -3, "%")
    else:
        rate = line["rate"]
    if "pitch" not in line:
        if t.rstrip().endswith("!"):
            pitch = _signed(pitch, 8, "Hz")
        elif t.rstrip().endswith("?"):
            pitch = _signed(pitch, 4, "Hz")
    else:
        pitch = line["pitch"]
    return voice, rate, pitch


async def _tts_one(text, voice, rate, pitch, mp3_path, json_path, sem):
    async with sem:
        for attempt in range(6):
            try:
                kw = dict(rate=rate, pitch=pitch, boundary="WordBoundary")
                proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
                if proxy:
                    kw["proxy"] = proxy
                comm = edge_tts.Communicate(text, voice, **kw)
                audio, words = bytearray(), []
                async for ch in comm.stream():
                    if ch["type"] == "audio":
                        audio.extend(ch["data"])
                    elif ch["type"] == "WordBoundary":
                        words.append({"text": ch["text"], "start": ch["offset"] / 1e7,
                                      "end": (ch["offset"] + ch["duration"]) / 1e7})
                if not audio:
                    raise RuntimeError("пустой ответ TTS")
                with open(mp3_path, "wb") as f:
                    f.write(audio)
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(words, f, ensure_ascii=False)
                return
            except Exception as e:  # noqa: BLE001
                if attempt == 5:
                    raise RuntimeError(f"edge-tts не смог озвучить «{text}»: {e}") from e
                await asyncio.sleep(1.5 * (attempt + 1))


def synthesize_all(jobs: list[tuple[str, str, str, str]], cache_dir: str) -> list[tuple[str, list]]:
    """jobs: (text, voice, rate, pitch) -> [(mp3_path, words)]"""
    _patch_edge_tts_ssl()
    os.makedirs(cache_dir, exist_ok=True)
    todo, out = [], []
    for text, voice, rate, pitch in jobs:
        key = hashlib.sha1(f"{text}|{voice}|{rate}|{pitch}".encode()).hexdigest()[:16]
        mp3, js = os.path.join(cache_dir, key + ".mp3"), os.path.join(cache_dir, key + ".json")
        if not (os.path.exists(mp3) and os.path.exists(js)):
            todo.append((text, voice, rate, pitch, mp3, js))
        out.append((mp3, js))
    if todo:
        print(f"[tts] озвучиваю {len(todo)} реплик через edge-tts ...")

        async def run():
            sem = asyncio.Semaphore(2)
            await asyncio.gather(*[_tts_one(*j, sem) for j in todo])
        asyncio.run(run())
    res = []
    for mp3, js in out:
        with open(js, encoding="utf-8") as f:
            res.append((mp3, json.load(f)))
    return res


def tighten_speech(audio, words, text, max_gap=0.2, max_gap_sentence=0.32):
    """Сжимает длинные паузы TTS между словами/предложениями — речь звучит бодрее."""
    if len(words) < 2:
        return audio, words
    ends_sentence = set()
    toks = [t for t in text.split() if norm_word(t)]
    for i, tok in enumerate(toks):
        if tok.rstrip("»\")'").endswith((".", "!", "?", "…")):
            ends_sentence.add(i)
    fade = int(SR * 0.012)
    pieces, new_words, cursor, shift = [], [], 0, 0.0
    for i, w in enumerate(words):
        nw = dict(w)
        nw["start"] -= shift
        nw["end"] -= shift
        new_words.append(nw)
        if i + 1 >= len(words):
            continue
        gap = words[i + 1]["start"] - w["end"]
        limit = max_gap_sentence if i in ends_sentence else max_gap
        if gap > limit:
            cut = gap - limit
            a = int(SR * (w["end"] + limit / 2))
            b = int(SR * (w["end"] + limit / 2 + cut))
            seg = audio[cursor:a].copy()
            if len(seg) > fade:
                seg[-fade:] *= np.linspace(1, 0, fade)
            pieces.append(seg)
            cursor = b
            shift += (b - a) / SR
    tail = audio[cursor:].copy()
    if len(tail) > fade:
        tail[:fade] *= np.linspace(0, 1, fade)
    pieces.append(tail)
    return np.concatenate(pieces).astype(np.float32), new_words


def decode_audio(path: str) -> "np.ndarray":
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


# --------------------------------------------------------------------------- #
#  Модель таймлайна
# --------------------------------------------------------------------------- #
@dataclass
class Item:
    kind: str            # "client" | "master" | "system" | "date"
    text: str
    t_appear: float
    img: Image.Image | None = None
    y: int = 0           # верх в координатах контента
    x: int = 0
    h: int = 0
    # озвучка
    audio: "np.ndarray | None" = None
    t_voice: float = 0.0
    speech_dur: float = 0.0
    words: list = field(default_factory=list)   # [(token, start_abs, end_abs)]
    chunks: list = field(default_factory=list)  # [(first_word_idx, last_word_idx)]
    typing_start: float | None = None   # для мастера — «печатает»; для клиента — набор в поле ввода


class Timeline:
    def __init__(self):
        self.items: list[Item] = []
        self.total = 0.0
        self.hook_end = 0.0
        self.cta_start = 0.0
        self.scroll_keys: list[tuple[float, float, float]] = []  # (t, from, to)


# --------------------------------------------------------------------------- #
#  Отрисовка элементов
# --------------------------------------------------------------------------- #
class Renderer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.th = {**DEFAULT_THEME, **cfg.get("theme", {})}
        self.f_msg = font("medium", 44)
        self.f_time = font("regular", 26)
        self.f_name = font("bold", 42)
        self.f_status = font("regular", 31)
        self.f_input = font("regular", 40)
        self.f_chip = font("medium", 30)
        self.f_sub = font("black", 80)
        self.f_hook = font("black", 104)
        self.f_cta = font("black", 76)
        self.sub_cache: dict = {}
        self.upper = cfg.get("subtitle_uppercase", True)

    # ---------- статика ----------
    def build_base(self) -> Image.Image:
        th = self.th
        img = Image.new("RGB", (W, H), hex2rgb(th["bg"]))
        d = ImageDraw.Draw(img)
        # фон чата с узором
        self.wallpaper = Image.new("RGB", (W, CHAT_H), hex2rgb(th["wallpaper"]))
        wd = ImageDraw.Draw(self.wallpaper)
        dc = hex2rgb(th["wallpaper_dots"])
        for yy in range(0, CHAT_H + 60, 56):
            off = 28 if (yy // 56) % 2 else 0
            for xx in range(off, W + 56, 56):
                wd.ellipse([xx - 3, yy - 3, xx + 3, yy + 3], fill=dc)
        img.paste(self.wallpaper, (0, CHAT_TOP))
        # статус-бар
        d.rectangle([0, 0, W, HEADER_BOTTOM], fill=hex2rgb(th["header"]))
        sb = font("bold", 30)
        d.text((52, 16), self.cfg.get("start_time", "19:42"), font=sb, fill="#FFFFFF")
        # батарея / сеть / wifi — простые фигуры
        x0 = W - 60
        d.rounded_rectangle([x0 - 52, 22, x0, 46], radius=6, outline="#FFFFFF", width=3)
        d.rounded_rectangle([x0 - 47, 27, x0 - 14, 41], radius=3, fill="#FFFFFF")
        d.rectangle([x0 + 3, 29, x0 + 7, 39], fill="#FFFFFF")
        for i in range(4):
            hh = 8 + i * 6
            d.rounded_rectangle([x0 - 150 + i * 12, 46 - hh, x0 - 142 + i * 12, 46], radius=2, fill="#FFFFFF")
        for i, r in enumerate((24, 16, 8)):
            d.arc([x0 - 92 - r, 46 - r, x0 - 92 + r, 46 + r], 225, 315, fill="#FFFFFF", width=4)
        # шапка: назад, аватар, имя, меню
        cy = (HEADER_TOP + HEADER_BOTTOM) // 2 + 4
        d.line([(58, cy - 24), (36, cy), (58, cy + 24)], fill=hex2rgb(th["accent"]), width=6, joint="curve")
        av = 104
        ag = gradient(av, av, *th["avatar"])
        img.paste(ag, (84, cy - av // 2), rounded_mask(av, av, [av // 2] * 4))
        ini = self.cfg.get("contact_initials") or "".join(w[0] for w in self.cfg.get("contact_name", "?").split()[:2])
        fi = font("bold", 40)
        d.text((84 + av / 2, cy), ini, font=fi, fill="#FFFFFF", anchor="mm")
        # онлайн-точка
        d.ellipse([84 + av - 26, cy + av // 2 - 26, 84 + av - 2, cy + av // 2 - 2], fill=hex2rgb(th["header"]))
        d.ellipse([84 + av - 22, cy + av // 2 - 22, 84 + av - 6, cy + av // 2 - 6], fill="#3DDC84")
        self.name_x = 84 + av + 26
        self.header_cy = cy
        d.text((self.name_x, cy - 22), self.cfg.get("contact_name", "Собеседник"), font=self.f_name,
               fill=th["header_text"], anchor="ls")
        for i in range(3):
            d.ellipse([W - 52, cy - 26 + i * 22, W - 42, cy - 16 + i * 22], fill="#C9D1DC")
        # лупа (поиск)
        px = W - 135
        d.ellipse([px - 22, cy - 26, px + 14, cy + 10], outline="#C9D1DC", width=6)
        d.line([(px + 10, cy + 6), (px + 26, cy + 22)], fill="#C9D1DC", width=7)
        # разделитель
        d.line([(0, HEADER_BOTTOM - 1), (W, HEADER_BOTTOM - 1)], fill="#0A0D12", width=2)
        # поле ввода
        d.rectangle([0, INPUT_TOP, W, INPUT_BOTTOM], fill=hex2rgb(th["header"]))
        self.input_box = (28, INPUT_TOP + 14, W - 132, INPUT_BOTTOM - 14)
        d.rounded_rectangle(self.input_box, radius=40, fill=hex2rgb(th["input_bg"]))
        self.btn_c = (W - 70, (INPUT_TOP + INPUT_BOTTOM) // 2)
        self.base = img
        return img

    def draw_input(self, img: Image.Image, text: str | None, caret_on: bool):
        th = self.th
        d = ImageDraw.Draw(img)
        x0, y0, x1, y1 = self.input_box
        cy = (y0 + y1) // 2
        bx, by = self.btn_c
        if text is None:
            d.text((x0 + 36, cy), "Сообщение", font=self.f_input, fill=th["input_placeholder"], anchor="lm")
            # микрофон
            d.ellipse([bx - 42, by - 42, bx + 42, by + 42], fill=hex2rgb(th["input_bg"]))
            d.rounded_rectangle([bx - 10, by - 24, bx + 10, by + 6], radius=10, fill="#C9D1DC")
            d.arc([bx - 18, by - 14, bx + 18, by + 16], 0, 180, fill="#C9D1DC", width=4)
            d.line([(bx, by + 16), (bx, by + 24)], fill="#C9D1DC", width=4)
        else:
            # показываем хвост набираемого текста
            maxw = x1 - x0 - 80
            shown = text
            while self.f_input.getlength(shown) > maxw and len(shown) > 1:
                shown = shown[1:]
            if shown != text:
                shown = "…" + shown[1:]
            d.text((x0 + 36, cy), shown, font=self.f_input, fill=th["input_text"], anchor="lm")
            if caret_on:
                cx = x0 + 36 + self.f_input.getlength(shown) + 4
                d.line([(cx, cy - 24), (cx, cy + 24)], fill=th["accent"], width=3)
            d.ellipse([bx - 42, by - 42, bx + 42, by + 42], fill=hex2rgb(th["accent"]))
            d.polygon([(bx - 16, by - 20), (bx + 22, by), (bx - 16, by + 20), (bx - 8, by)], fill="#FFFFFF")

    def draw_status(self, img: Image.Image, typing: bool, t: float):
        d = ImageDraw.Draw(img)
        y = self.header_cy + 26
        if typing:
            n = int(t * 3) % 4
            d.text((self.name_x, y), "печатает" + "." * n, font=self.f_status, fill=self.th["status_typing"],
                   anchor="ls")
        else:
            d.text((self.name_x, y), self.cfg.get("contact_status", "в сети"), font=self.f_status,
                   fill=self.th["status_online"], anchor="ls")

    # ---------- пузыри ----------
    def bubble(self, kind: str, text: str, time_str: str) -> Image.Image:
        th = self.th
        lines = wrap(text, self.f_msg, BUBBLE_MAX_TEXT_W)
        lh = 58
        pad_x, pad_y = 32, 22
        tw_time = self.f_time.getlength(time_str) + (44 if kind == "client" else 0)
        last_w = self.f_msg.getlength(lines[-1])
        text_w = max(self.f_msg.getlength(ln) for ln in lines)
        extra_row = last_w + tw_time + 22 > BUBBLE_MAX_TEXT_W
        content_w = max(text_w, (last_w + tw_time + 22) if not extra_row else tw_time)
        bw = int(content_w + pad_x * 2)
        bh = int(pad_y * 2 + lh * len(lines) + (34 if extra_row else 4))
        if kind == "client":
            fill = gradient(bw, bh, *th["client_bubble"])
            radii = [34, 34, 8, 34]
            tc, tmc = th["client_text"], th["time_client"]
        else:
            fill = Image.new("RGB", (bw, bh), hex2rgb(th["master_bubble"]))
            radii = [34, 34, 34, 8]
            tc, tmc = th["master_text"], th["time_master"]
        img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        img.paste(fill, (0, 0), rounded_mask(bw, bh, radii))
        d = ImageDraw.Draw(img)
        for i, ln in enumerate(lines):
            d.text((pad_x, pad_y + i * lh + lh - 14), ln, font=self.f_msg, fill=tc, anchor="ls")
        ty = bh - pad_y + 2
        tx = bw - pad_x - tw_time
        d.text((tx, ty), time_str, font=self.f_time, fill=tmc, anchor="ls")
        if kind == "client":  # две галочки «прочитано»
            cx = bw - pad_x - 34
            for off in (0, 12):
                d.line([(cx + off, ty - 10), (cx + off + 7, ty - 3), (cx + off + 20, ty - 18)], fill=tmc, width=3)
        return self.with_shadow(img)

    def with_shadow(self, img: Image.Image) -> Image.Image:
        bw, bh = img.size
        out = Image.new("RGBA", (bw + 16, bh + 16), (0, 0, 0, 0))
        sh = Image.new("RGBA", (bw, bh), (0, 0, 0, 90))
        sh.putalpha(img.getchannel("A").point(lambda a: a * 90 // 255))
        out.paste(sh, (8, 12), sh)
        out = out.filter(ImageFilter.GaussianBlur(6))
        out.alpha_composite(img, (8, 4))
        return out

    def chip(self, text: str) -> Image.Image:
        tw = int(self.f_chip.getlength(text)) + 56
        h = 58
        img = Image.new("RGBA", (tw, h), (0, 0, 0, 0))
        m = rounded_mask(tw, h, [29] * 4)
        img.paste(Image.new("RGB", (tw, h), hex2rgb(self.th["chip_bg"])), (0, 0), m)
        ImageDraw.Draw(img).text((tw / 2, h / 2 + 1), text, font=self.f_chip, fill=self.th["chip_text"], anchor="mm")
        return img

    def typing_bubble(self, t: float) -> Image.Image:
        bw, bh = 170, 100
        img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        img.paste(Image.new("RGB", (bw, bh), hex2rgb(self.th["master_bubble"])), (0, 0),
                  rounded_mask(bw, bh, [34, 34, 34, 8]))
        d = ImageDraw.Draw(img)
        for i in range(3):
            ph = (t * 2.2 - i * 0.18) % 1.0
            k = max(0.0, math.sin(min(ph, 0.5) * 2 * math.pi)) if ph < 0.5 else 0.0
            dy = -12 * k
            c = int(110 + 120 * k)
            cx = 52 + i * 33
            d.ellipse([cx - 9, bh / 2 - 9 + dy, cx + 9, bh / 2 + 9 + dy], fill=(c, c + 6, c + 14))
        return self.with_shadow(img)

    # ---------- субтитры ----------
    def subtitle(self, tokens: list[str], hi: int) -> Image.Image:
        key = (tuple(tokens), hi)
        if key in self.sub_cache:
            return self.sub_cache[key]
        f = self.f_sub
        size = 80
        words = [t.upper() if self.upper else t for t in tokens]
        # подбираем размер, чтобы влезло в 2 строки
        while True:
            lines = wrap_tokens(words, f, SUB_MAX_W)
            if len(lines) <= 2 or size <= 50:
                break
            size -= 6
            f = font("black", size)
        sp = f.getlength(" ")
        if len(lines) == 2:  # балансируем две строки по ширине
            best = None
            for k in range(1, len(words)):
                w1 = sum(f.getlength(x) for x in words[:k]) + sp * (k - 1)
                w2 = sum(f.getlength(x) for x in words[k:]) + sp * (len(words) - k - 1)
                if max(w1, w2) <= SUB_MAX_W and (best is None or max(w1, w2) < best[0]):
                    best = (max(w1, w2), k)
            if best:
                lines = [list(range(best[1])), list(range(best[1], len(words)))]
        lh = int(size * 1.18)
        hgt = lh * len(lines) + 40
        img = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        stroke = max(5, size // 11)
        idx = 0
        for li, ln in enumerate(lines):
            lw = sum(f.getlength(words[i]) for i in ln) + sp * (len(ln) - 1)
            x = (W - lw) / 2
            y = 20 + li * lh + lh * 0.82
            for i in ln:
                col = self.th["sub_highlight"] if i == hi else self.th["sub_text"]
                d.text((x, y), words[i], font=f, fill=col, anchor="ls", stroke_width=stroke,
                       stroke_fill=self.th["sub_stroke"])
                x += f.getlength(words[i]) + sp
                idx += 1
        # мягкая тень
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow.putalpha(img.getchannel("A").point(lambda a: a * 120 // 255))
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        out = Image.new("RGBA", img.size, (0, 0, 0, 0))
        out.alpha_composite(shadow, (0, 6))
        out.alpha_composite(img)
        self.sub_cache[key] = out
        return out

    # ---------- хук и CTA ----------
    def marked_text_block(self, text: str, fnt, max_w: int, col: str, hcol: str) -> Image.Image:
        toks = parse_marked(text)
        words = [w for w, _ in toks]
        lines = wrap_tokens(words, fnt, max_w)
        size = fnt.size
        lh = int(size * 1.15)
        sp = fnt.getlength(" ")
        img = Image.new("RGBA", (W, lh * len(lines) + 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for li, ln in enumerate(lines):
            lw = sum(fnt.getlength(words[i]) for i in ln) + sp * (len(ln) - 1)
            x = (W - lw) / 2
            y = 30 + li * lh + lh * 0.82
            for i in ln:
                d.text((x, y), words[i], font=fnt, fill=hcol if toks[i][1] else col, anchor="ls",
                       stroke_width=max(4, size // 14), stroke_fill="#000000")
                x += fnt.getlength(words[i]) + sp
        return img

    def build_overlays(self):
        th = self.th
        self.hook_img = self.marked_text_block(self.cfg.get("hook", ""), self.f_hook, 960, th["hook_text"],
                                               th["hook_highlight"])
        # CTA-карточка
        txt = self.marked_text_block(self.cfg.get("cta", "Подписывайся"), self.f_cta, 860, "#FFFFFF",
                                     th["hook_highlight"])
        bbox = txt.getbbox() or (0, 0, W, 100)
        txt = txt.crop((0, bbox[1], W, bbox[3]))
        cw, chh = 940, txt.height + 250
        card = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
        card.paste(Image.new("RGB", (cw, chh), hex2rgb(th["cta_card"])), (0, 0), rounded_mask(cw, chh, [48] * 4))
        card.alpha_composite(txt.crop(((W - cw) // 2, 0, (W + cw) // 2, txt.height)), (0, 60))
        bw, bh = 520, 110
        btn = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        btn.paste(Image.new("RGB", (bw, bh), hex2rgb(th["cta_button"])), (0, 0), rounded_mask(bw, bh, [55] * 4))
        bd = ImageDraw.Draw(btn)
        bd.text((bw / 2 + 26, bh / 2 + 2), "ПОДПИСАТЬСЯ", font=font("black", 44), fill="#FFFFFF", anchor="mm")
        # колокольчик
        bx, by = 70, bh // 2
        bd.pieslice([bx - 22, by - 26, bx + 22, by + 18], 180, 360, fill="#FFFFFF")
        bd.rectangle([bx - 22, by - 4, bx + 22, by + 12], fill="#FFFFFF")
        bd.ellipse([bx - 7, by + 12, bx + 7, by + 24], fill="#FFFFFF")
        card.alpha_composite(btn, ((cw - bw) // 2, chh - bh - 50))
        self.cta_img = self.with_shadow(card)


def wrap_tokens(words: list[str], fnt, max_w: int) -> list[list[int]]:
    lines, cur, cur_w = [], [], 0.0
    sp = fnt.getlength(" ")
    for i, w in enumerate(words):
        ww = fnt.getlength(w)
        if cur and cur_w + sp + ww > max_w:
            lines.append(cur)
            cur, cur_w = [i], ww
        else:
            cur_w = cur_w + (sp if cur else 0) + ww
            cur.append(i)
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------- #
#  Построение таймлайна
# --------------------------------------------------------------------------- #
def align_words(text: str, boundaries: list, t0: float, dur: float) -> list[tuple[str, float, float]]:
    """Сопоставляем слова текста (с пунктуацией) с таймингами edge-tts."""
    tokens = text.split()
    res = []
    j = 0
    ok = True
    for tok in tokens:
        target = norm_word(tok)
        if not target:
            # чистая пунктуация (например «—») — приклеим к предыдущему
            if res:
                w, s, e = res[-1]
                res[-1] = (w + " " + tok, s, e)
            continue
        if j >= len(boundaries):
            ok = False
            break
        start = boundaries[j]["start"]
        acc = ""
        end = boundaries[j]["end"]
        while j < len(boundaries) and len(acc) < len(target):
            acc += norm_word(boundaries[j]["text"])
            end = boundaries[j]["end"]
            j += 1
        if acc != target:
            ok = False
            break
        res.append((tok, t0 + start, t0 + end))
    if ok and res:
        return res
    # запасной вариант: пропорционально длине слов
    total = sum(len(t) + 1 for t in tokens)
    acc, res = 0.0, []
    for tok in tokens:
        s = t0 + dur * acc / total
        acc += len(tok) + 1
        res.append((tok, s, t0 + dur * acc / total))
    return res


def make_chunks(words: list[tuple[str, float, float]], fnt, max_words=4) -> list[tuple[int, int]]:
    chunks, start = [], 0
    for i, (w, _, _) in enumerate(words):
        n = i - start + 1
        width = fnt.getlength(" ".join(x[0] for x in words[start:i + 1]).upper())
        end_here = w.endswith((".", "!", "?", "…")) or (w.endswith(",") and n >= 2)
        lim = SUB_MAX_W * 1.6  # кусок может занять до двух строк
        nxt_too_wide = (i + 1 < len(words) and
                        fnt.getlength(" ".join(x[0] for x in words[start:i + 2]).upper()) > lim)
        if end_here or n >= max_words or nxt_too_wide or width > lim:
            # не обрываем кусок на коротком предлоге/частице («у», «не», «в») — переносим его дальше
            if not end_here and i > start and len(norm_word(w)) <= 2 and not w.endswith(","):
                chunks.append((start, i - 1))
                start = i
            else:
                chunks.append((start, i))
                start = i + 1
    if start < len(words):
        chunks.append((start, len(words) - 1))
    return chunks


def add_minutes(hhmm: str, mins: int) -> str:
    h, m = map(int, hhmm.split(":"))
    tot = (h * 60 + m + mins) % (24 * 60)
    return f"{tot // 60:02d}:{tot % 60:02d}"


def build_timeline(cfg: dict, lines: list[dict], rnd: Renderer, voiced: list, gap_scale: float) -> Timeline:
    tl = Timeline()
    hook_dur = float(cfg.get("hook_duration", 1.5))
    t = float(cfg.get("first_message_at", 1.0))
    tl.hook_end = hook_dur
    clock = cfg.get("start_time", "19:42")
    # чип «Сегодня»
    date = Item("date", cfg.get("date_label", "Сегодня"), 0.0)
    date.img = rnd.chip(date.text)
    tl.items.append(date)
    vi = 0
    prev_appear = -1.0
    for ln in lines:
        who = ln["who"]
        pause = float(ln.get("pause_after", 0.3)) * gap_scale
        if who == "system":
            clock = add_minutes(clock, int(ln.get("skip_minutes", 0)))
            it = Item("system", ln["text"], t)
            it.img = rnd.chip(ln["text"])
            tl.items.append(it)
            t += 0.6 * gap_scale + pause
            prev_appear = it.t_appear
            continue
        mp3, words_b, audio = voiced[vi]
        vi += 1
        it = Item(who, ln["text"], 0.0)
        if who == "master":
            typing = float(ln.get("typing", clamp(0.35 + 0.008 * len(ln["text"]), 0.55, 0.9)))
        else:
            typing = float(ln.get("typing", clamp(0.22 + 0.004 * len(ln["text"]), 0.3, 0.45)))
        # собеседник начинает печатать, пока ещё звучит предыдущая реплика (как в жизни).
        # Лишнее ожидание появляется, только если «печатает» дольше, чем доступный нахлёст.
        it.typing_start = max(prev_appear + 0.35, t - typing)
        t = max(t, it.typing_start + typing * gap_scale)
        it.t_appear = t
        it.img = rnd.bubble(who, ln["text"], clock)
        it.audio = audio
        it.t_voice = t + 0.04
        if words_b:
            speech_end = words_b[-1]["end"] + 0.12
        else:
            speech_end = len(audio) / SR
        speech_end = min(speech_end, len(audio) / SR)
        it.speech_dur = speech_end
        it.words = align_words(ln["text"], words_b, it.t_voice, speech_end)
        it.chunks = make_chunks(it.words, rnd.f_sub)
        tl.items.append(it)
        t = it.t_voice + speech_end + pause
        prev_appear = it.t_appear
        clock = add_minutes(clock, 1 if len(ln["text"]) > 40 else 0)
    t += 0.25
    tl.cta_start = t
    tl.total = t + float(cfg.get("cta_duration", 1.5))
    layout(tl)
    return tl


def layout(tl: Timeline):
    """Позиции пузырей в координатах контента и ключи прокрутки."""
    y = 24
    for it in tl.items:
        w, h = it.img.size
        if it.kind == "client":
            it.x = W - SIDE_PAD - w + 8
        elif it.kind == "master":
            it.x = SIDE_PAD - 8
        else:
            it.x = (W - w) // 2
        if it.kind in ("system", "date"):
            y += 10
        it.y = y
        it.h = h
        y += h + BUBBLE_GAP - 16 + (10 if it.kind in ("system", "date") else 0)
    # события, меняющие нижнюю границу контента
    TYPING_H = 100 + 16 + BUBBLE_GAP - 16
    events = []  # (t, bottom)
    for it in tl.items:
        if it.kind == "master" and it.typing_start is not None:
            events.append((it.typing_start, it.y + TYPING_H))
        events.append((it.t_appear, it.y + it.h))
    events.sort()
    keys = []
    cur = 0.0
    for t, bottom in events:
        target = max(0.0, bottom - CHAT_H + 30)
        if keys:
            # значение прокрутки в момент t по предыдущему ключу
            pt, pf, pto = keys[-1]
            cur = pf + (pto - pf) * ease_in_out((t - pt) / 0.32)
        keys.append((t, cur, target))
        cur = target
    tl.scroll_keys = keys


def scroll_at(tl: Timeline, t: float) -> float:
    s = 0.0
    for kt, f, to in tl.scroll_keys:
        if kt > t:
            break
        s = f + (to - f) * ease_in_out((t - kt) / 0.32)
    return s


# --------------------------------------------------------------------------- #
#  Рендер кадра
# --------------------------------------------------------------------------- #
G: dict = {}  # глобальное состояние для воркеров (fork)


def render_frame(t: float) -> Image.Image:
    rnd: Renderer = G["rnd"]
    tl: Timeline = G["tl"]
    frame = rnd.base.copy()
    chat = rnd.wallpaper.copy()
    scroll = scroll_at(tl, t)
    typing_master = False
    input_text = None

    for it in tl.items:
        if it.kind == "master" and it.typing_start is not None and it.typing_start <= t < it.t_appear:
            typing_master = True
            age = t - it.typing_start
            tb = rnd.typing_bubble(t)
            k = ease_out_back(age / 0.25)
            a = clamp(age / 0.15, 0, 1)
            if k < 0.999:
                tb = tb.resize((max(1, int(tb.width * (0.6 + 0.4 * k))), max(1, int(tb.height * (0.6 + 0.4 * k)))),
                               Image.BILINEAR)
            if a < 1:
                tb.putalpha(tb.getchannel("A").point(lambda v: int(v * a)))
            ty = int(it.y - scroll + (116 - tb.height))  # нижний край на месте будущего пузыря
            chat.paste(tb, (SIDE_PAD - 8, ty), tb)
        if it.kind == "client" and it.typing_start is not None and it.typing_start <= t < it.t_appear:
            frac = (t - it.typing_start) / max(1e-3, it.t_appear - it.typing_start)
            n = int(len(it.text) * clamp(frac * 1.15, 0, 1))
            input_text = it.text[:n]
        if t < it.t_appear:
            continue
        age = t - it.t_appear
        img = it.img
        x, y = it.x, it.y - scroll
        if age < 0.35:
            k = ease_out_back(age / 0.32, 1.4)
            a = clamp(age / 0.12, 0, 1)
            sc = 0.82 + 0.18 * k
            nw, nh = max(1, int(img.width * sc)), max(1, int(img.height * sc))
            img = img.resize((nw, nh), Image.BILINEAR)
            if a < 1:
                img = img.copy()
                img.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
            slide = (1 - ease_out_cubic(age / 0.3)) * 90
            if it.kind == "client":
                x = it.x + it.img.width - nw + slide  # от правого края
                y = y + (it.img.height - nh)
            elif it.kind == "master":
                x = it.x - slide
                y = y + (it.img.height - nh)
            else:
                x = it.x + (it.img.width - nw) // 2
                y = y + (it.img.height - nh) // 2
            y += (1 - ease_out_cubic(age / 0.3)) * 40
        if y > CHAT_H or y + img.height < 0:
            continue
        chat.paste(img, (int(x), int(y)), img)

    frame.paste(chat, (0, CHAT_TOP))
    # тень под шапкой
    frame.paste(G["header_shadow"], (0, CHAT_TOP), G["header_shadow"])
    rnd.draw_status(frame, typing_master, t)
    rnd.draw_input(frame, input_text, (int(t * 2.5) % 2 == 0))

    # субтитры
    for it in tl.items:
        if it.kind not in ("client", "master") or not it.words:
            continue
        if not (it.t_voice - 0.02 <= t < it.t_voice + it.speech_dur + 0.15):
            continue
        # текущий кусок
        ci = 0
        for c_idx, (a, b) in enumerate(it.chunks):
            if t >= it.words[a][1] - 0.05:
                ci = c_idx
        a, b = it.chunks[ci]
        hi = a
        for i in range(a, b + 1):
            if t >= it.words[i][1]:
                hi = i
        sub = rnd.subtitle([w for w, _, _ in it.words[a:b + 1]], hi - a)
        age = t - max(it.t_voice, it.words[a][1] - 0.05)
        if age < 0.14:
            k = ease_out_back(age / 0.14, 2.0)
            sc = 0.85 + 0.15 * k
            sub = sub.resize((int(sub.width * sc), max(1, int(sub.height * sc))), Image.BILINEAR)
        frame.paste(sub, ((W - sub.width) // 2, SUB_CY - sub.height // 2), sub)
        break

    # хук
    if t < tl.hook_end:
        a = 1.0 if t < tl.hook_end - 0.3 else (tl.hook_end - t) / 0.3
        frame = overlay_dim(frame, int(170 * a))
        k = ease_out_back(t / 0.25, 1.8)
        hk = rnd.hook_img
        sc = 0.7 + 0.3 * k
        if sc != 1:
            hk = hk.resize((max(1, int(hk.width * sc)), max(1, int(hk.height * sc))), Image.BILINEAR)
        if a < 1 or t < 0.1:
            aa = a * clamp(t / 0.1, 0, 1)
            hk = hk.copy()
            hk.putalpha(hk.getchannel("A").point(lambda v: int(v * aa)))
        frame.paste(hk, ((W - hk.width) // 2, 760 - hk.height // 2), hk)

    # CTA
    if t >= tl.cta_start:
        age = t - tl.cta_start
        frame = overlay_dim(frame, int(160 * clamp(age / 0.25, 0, 1)))
        card = rnd.cta_img
        k = ease_out_back(age / 0.4, 1.5)
        y = int(H + 50 - (H + 50 - (820 - card.height // 2)) * k)
        frame.paste(card, ((W - card.width) // 2, y), card)
    return frame


def overlay_dim(frame: Image.Image, alpha: int) -> Image.Image:
    if alpha <= 0:
        return frame
    return Image.blend(frame, Image.new("RGB", frame.size, (0, 0, 0)), alpha / 255)


def render_segment(args):
    idx, f0, f1, path, crf, preset = args
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-g", str(FPS * 2), "-r", str(FPS), path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(f0, f1):
        p.stdin.write(render_frame(fi / FPS).tobytes())
        if idx == 0 and (fi - f0) % 120 == 0:
            done = (fi - f0) / max(1, f1 - f0)
            print(f"\r[video] ~{done * 100:4.0f}%", end="", flush=True)
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg упал при кодировании сегмента")
    return path


# --------------------------------------------------------------------------- #
#  Звук: поп, фоновый бит, сведение
# --------------------------------------------------------------------------- #
def synth_pop(freq0=1100, freq1=520, dur=0.09) -> "np.ndarray":
    n = int(SR * dur)
    tt = np.arange(n) / SR
    f = freq1 + (freq0 - freq1) * np.exp(-tt * 45)
    ph = 2 * np.pi * np.cumsum(f) / SR
    env = np.exp(-tt * 38) * np.minimum(1, tt * 2000)
    return (np.sin(ph) * env).astype(np.float32)


def synth_whoosh(dur=0.5) -> "np.ndarray":
    n = int(SR * dur)
    rng = np.random.default_rng(1)
    noise = rng.standard_normal(n).astype(np.float32)
    # простой «фильтр» скользящим средним с меняющимся окном
    out = np.convolve(noise, np.ones(8) / 8, mode="same")
    tt = np.arange(n) / n
    env = np.sin(np.pi * tt) ** 2
    return (out * env * 0.5).astype(np.float32)


def synth_beat(duration: float, bpm=96) -> "np.ndarray":
    """Лёгкий лоу-фай луп: бочка, клэп, хэты, бас. Всё синтезируется, без внешних файлов."""
    n = int(SR * duration) + SR
    out = np.zeros(n, np.float32)
    beat = 60 / bpm
    rng = np.random.default_rng(7)

    def kick():
        d = int(SR * 0.35)
        tt = np.arange(d) / SR
        f = 45 + 90 * np.exp(-tt * 30)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9)

    def clap():
        d = int(SR * 0.18)
        tt = np.arange(d) / SR
        nz = rng.standard_normal(d)
        nz = nz - np.convolve(nz, np.ones(6) / 6, mode="same")
        return nz * np.exp(-tt * 22) * 0.5

    def hat():
        d = int(SR * 0.05)
        tt = np.arange(d) / SR
        nz = rng.standard_normal(d)
        nz = np.diff(nz, prepend=0)
        return nz * np.exp(-tt * 90) * 0.18

    def bass(freq, dur):
        d = int(SR * dur)
        tt = np.arange(d) / SR
        s = np.sin(2 * np.pi * freq * tt) + 0.3 * np.sin(4 * np.pi * freq * tt)
        return s * np.minimum(1, tt * 80) * np.exp(-tt * 2.5) * 0.35

    K, C, Hh = kick(), clap(), hat()
    bass_notes = [55.0, 55.0, 65.41, 49.0]  # A1 A1 C2 G1
    steps = int(duration / (beat / 2)) + 2
    for s in range(steps):
        pos = int(s * beat / 2 * SR)
        bar_step = s % 8
        if pos >= n:
            break

        def add(x, p=pos):
            e = min(n, p + len(x))
            out[p:e] += x[:e - p]
        if bar_step in (0, 5):
            add(K)
        if bar_step in (2, 6):
            add(C)
        add(Hh * (1.0 if s % 2 else 0.6))
        if bar_step == 0:
            bar = (s // 8) % 4
            add(bass(bass_notes[bar], beat * 3.5).astype(np.float32))
    return out[:int(SR * duration)]


def build_audio(cfg: dict, tl: Timeline, path: str):
    n = int(SR * tl.total) + SR
    voice = np.zeros(n, np.float32)
    fx = np.zeros(n, np.float32)
    pop_vol = float(cfg.get("pop_volume", 0.35))
    pop_out, pop_in = synth_pop(1250, 650) * pop_vol, synth_pop(850, 420) * pop_vol

    def put(buf, x, t):
        p = int(t * SR)
        e = min(len(buf), p + len(x))
        if p < e:
            buf[p:e] += x[:e - p]

    put(fx, synth_whoosh(0.45) * 0.5, 0.0)
    for it in tl.items:
        if it.kind in ("client", "master"):
            put(fx, pop_out if it.kind == "client" else pop_in, it.t_appear)
            put(voice, it.audio * float(cfg.get("voice_volume", 1.0)), it.t_voice)
        elif it.kind == "system" and it.t_appear > 0:
            put(fx, synth_pop(700, 500, 0.08) * pop_vol * 0.6, it.t_appear)
    put(fx, synth_whoosh(0.4) * 0.4, tl.cta_start)
    put(fx, pop_out * 1.2, tl.cta_start + 0.25)

    music_vol = float(cfg.get("music_volume", 0.10))
    music_file = cfg.get("music_file")
    if music_file and os.path.exists(music_file):
        m = decode_audio(music_file)
        reps = int(math.ceil(n / max(1, len(m))))
        music = np.tile(m, reps)[:n]
    else:
        music = synth_beat(n / SR)
        music = np.pad(music, (0, max(0, n - len(music))))[:n]
    music = music / (np.max(np.abs(music)) + 1e-9)
    # дакинг: приглушаем музыку, пока звучит голос
    env = np.abs(voice)
    win = int(SR * 0.05)
    env = np.convolve(env, np.ones(win) / win, mode="same")
    duck = np.where(env > 0.01, 0.45, 1.0).astype(np.float32)
    duck = np.convolve(duck, np.ones(int(SR * 0.25)) / int(SR * 0.25), mode="same")
    # плавные вход/выход музыки
    fade = np.ones(n, np.float32)
    fi = int(SR * 0.4)
    fade[:fi] = np.linspace(0, 1, fi)
    end = int(SR * tl.total)
    fo = int(SR * 0.6)
    fade[end - fo:end] = np.linspace(1, 0.3, fo)
    mix = voice + fx + music * music_vol * duck * fade
    mix = mix[:end]
    peak = np.max(np.abs(mix))
    if peak > 0.98:
        mix *= 0.98 / peak
    stereo = np.repeat((mix * 32767).astype(np.int16)[:, None], 2, axis=1)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(stereo.tobytes())


# --------------------------------------------------------------------------- #
#  main
# --------------------------------------------------------------------------- #
def load_script(path: str) -> tuple[dict, list[dict]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {}, data
    return data.get("meta", {}), data["lines"]


def main():
    ap = argparse.ArgumentParser(description="Фейковая переписка -> вертикальное видео")
    ap.add_argument("script", help="путь к script.json")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("-n", "--limit", type=int, default=0, help="взять только первые N реплик (для пробы)")
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 2)))
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="veryfast")
    ap.add_argument("--no-fit", action="store_true", help="не подгонять длительность под 45–60 c")
    args = ap.parse_args()

    cfg, lines = load_script(args.script)
    for wgt, p in cfg.get("fonts", {}).items():
        FONT_OVERRIDE[wgt] = p
    if args.limit:
        # считаем только реплики собеседников, системные плашки идут «бесплатно»
        out, cnt = [], 0
        for ln in lines:
            if ln["who"] in ("client", "master"):
                if cnt >= args.limit:
                    break
                cnt += 1
            out.append(ln)
        lines = out
    for ln in lines:
        if ln["who"] not in ("client", "master", "system"):
            sys.exit(f"Неизвестный who: {ln['who']!r} (нужно client | master | system)")

    voices = {**DEFAULT_VOICES, **cfg.get("voices", {})}
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(args.script)), ".tts_cache")
    rnd = Renderer(cfg)
    rnd.build_base()
    rnd.build_overlays()

    target_min, target_max = float(cfg.get("min_duration", 45)), float(cfg.get("max_duration", 60))
    rate_boost = 0
    gap_scale = 1.0
    for attempt in range(6):
        jobs = []
        for ln in lines:
            if ln["who"] == "system":
                continue
            v, r, p = voice_params(ln, voices)
            jobs.append((ln["text"], v, _signed(r, rate_boost, "%"), p))
        res = synthesize_all(jobs, cache_dir)
        voiced = []
        speech_lines = [ln for ln in lines if ln["who"] != "system"]
        for (mp3, words), ln in zip(res, speech_lines):
            audio = decode_audio(mp3)
            if cfg.get("tighten_pauses", True):
                audio, words = tighten_speech(audio, words, ln["text"], float(cfg.get("max_word_gap", 0.2)),
                                              float(cfg.get("max_sentence_gap", 0.32)))
            voiced.append((mp3, words, audio))
        tl = build_timeline(cfg, lines, rnd, voiced, gap_scale)
        print(f"[timeline] длительность {tl.total:.1f} c (ускорение речи {rate_boost:+d}%, паузы x{gap_scale:.2f})")
        if args.no_fit or args.limit or tl.total <= target_max - 0.3:
            break
        # сначала поджимаем паузы, потом ускоряем голос
        if gap_scale > 0.7:
            gap_scale = max(0.7, gap_scale - 0.15)
        else:
            rate_boost += max(3, int((tl.total / (target_max - 0.5) - 1) * 100) + 2)
    if not args.limit and tl.total < target_min:
        print(f"[!] видео короче {target_min:.0f} c — добавьте реплик или увеличьте pause_after")

    # тень под шапкой
    sh = Image.new("RGBA", (W, 24), (0, 0, 0, 0))
    sa = np.linspace(110, 0, 24).astype(np.uint8)
    sh.putalpha(Image.fromarray(np.repeat(sa[:, None], W, axis=1), "L"))
    G.update(rnd=rnd, tl=tl, header_shadow=sh)

    work = tempfile.mkdtemp(prefix="chatvid_")
    try:
        audio_path = os.path.join(work, "audio.wav")
        build_audio(cfg, tl, audio_path)
        nframes = int(round(tl.total * FPS))
        nseg = max(1, args.workers)
        bounds = [round(i * nframes / nseg) for i in range(nseg + 1)]
        segs = [(i, bounds[i], bounds[i + 1], os.path.join(work, f"seg{i:02d}.mp4"), args.crf, args.preset)
                for i in range(nseg) if bounds[i + 1] > bounds[i]]
        print(f"[video] рендер {nframes} кадров ({W}x{H}@{FPS}) в {len(segs)} потоков ...")
        if len(segs) == 1:
            render_segment(segs[0])
        elif "fork" in mp.get_all_start_methods():
            with mp.get_context("fork").Pool(len(segs)) as pool:
                pool.map(render_segment, segs)
        else:  # Windows: процессы без fork не видят состояние, используем потоки
            from multiprocessing.pool import ThreadPool
            with ThreadPool(len(segs)) as pool:
                pool.map(render_segment, segs)
        print("\r[video] 100%            ")
        lst = os.path.join(work, "list.txt")
        with open(lst, "w") as f:
            for s in segs:
                f.write(f"file '{s[3]}'\n")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-i", audio_path,
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", f"loudnorm=I={cfg.get('loudness', -14)}:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
                        "-shortest", "-movflags", "+faststart", args.output], check=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"[done] {os.path.abspath(args.output)}  ({tl.total:.1f} c)")


if __name__ == "__main__":
    main()
