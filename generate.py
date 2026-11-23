#!/usr/bin/env python3
"""
Генератор вертикальных роликов «фейковая переписка в мессенджере».

    python generate.py script.json                 -> output.mp4
    python generate.py script.json --lines 6 -o preview.mp4   (пробная версия)

Сюжет, имена, заголовок и плашка — в script.json. Внешний вид и голоса —
в блоках THEME и VOICES ниже (или в ключах "theme" / "voices" в script.json).
"""

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
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


# ----------------------------------------------------------------------------
# Зависимости: ставим недостающее автоматически
# ----------------------------------------------------------------------------
def _ensure_deps():
    missing = []
    for mod, pkg in (("PIL", "Pillow"), ("numpy", "numpy"), ("edge_tts", "edge-tts")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[deps] устанавливаю: {' '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing])
    if not shutil.which("ffmpeg"):
        sys.exit("Не найден ffmpeg. Установите его (apt install ffmpeg / brew install ffmpeg / winget install ffmpeg).")


_ensure_deps()

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402


ROOT = Path(__file__).resolve().parent

# ----------------------------------------------------------------------------
# НАСТРОЙКИ
# ----------------------------------------------------------------------------
W, H = 1080, 1920
FPS = 60
MIN_DUR, MAX_DUR = 45.0, 59.5        # целевая длина полного ролика, сек
HOOK_DUR = 1.0                        # заголовок-крючок в начале
OUTRO_DUR = 1.5                       # плашка «подписывайся» в конце
VOICE_DELAY = 0.06                    # голос стартует чуть позже «попа»
SR = 48000                            # частота аудио

# Голоса edge-tts. rate/pitch — как в edge-tts: "+10%", "-5Hz".
# У пассажирки темп и высота линейно растут от *_start к *_end (нервничает).
VOICES = {
    "driver": {
        "voice": "ru-RU-DmitryNeural",
        "rate": "+4%",          # чуть медленнее пассажирки
        "pitch": "-4Hz",        # ниже = увереннее
    },
    "passenger": {
        "voice": "ru-RU-SvetlanaNeural",
        "rate_start": "+12%", "rate_end": "+32%",
        "pitch_start": "+0Hz", "pitch_end": "+14Hz",
        "exclaim_rate": "+4%", "exclaim_pitch": "+6Hz",   # доп. к репликам с «!» / «?!»
    },
}

# Цвета (RGB hex). Можно переопределить в script.json -> "theme".
THEME = {
    "bg": "#0E0F14",
    "bg_dots": "#1A1C24",
    "header_bg": "#17181F",
    "divider": "#24262F",
    "text": "#F2F3F7",
    "muted": "#8B8E9C",
    "status": "#6FD08C",
    "typing_status": "#A98BFF",
    "avatar": "#F2A93B",
    "driver_bubble": "#2C2E37",
    "driver_text": "#F2F3F7",
    "passenger_bubble": "#7B4DFF",
    "passenger_text": "#FFFFFF",
    "bubble_time": "#C9CBD6",
    "tick_sent": "#8B8E9C",
    "tick_read": "#3FC3FF",
    "route_line": "#343744",
    "route_fill": "#9B7BFF",
    "car": "#FFC531",
    "sub_text": "#FFFFFF",
    "sub_hl": "#FFD60A",
    "sub_stroke": "#000000",
    "hook_hl": "#FFD60A",
    "outro_bg": "#7B4DFF",
    "outro_bg2": "#5427E0",
}

# Раскладка (px)
HEADER_Y0, HEADER_Y1 = 0, 238
ROUTE_Y0, ROUTE_Y1 = 238, 340
VIEW_Y0, VIEW_Y1 = 340, 1290           # видимая область чата
SUB_CY = 1468                          # центр субтитров
INPUT_Y0, INPUT_Y1 = 1668, 1792        # поле ввода
SIDE = 44                              # отступ пузырей от края
BUBBLE_MAX_W = 780
MSG_FONT = 46
GAP = 22

FONT_FILES = {
    "regular": ["fonts/Inter-Regular.otf", "DejaVuSans.ttf", "arial.ttf"],
    "medium": ["fonts/Inter-Medium.otf", "DejaVuSans.ttf", "arial.ttf"],
    "semibold": ["fonts/Inter-SemiBold.otf", "DejaVuSans-Bold.ttf", "arialbd.ttf"],
    "bold": ["fonts/Inter-Bold.otf", "DejaVuSans-Bold.ttf", "arialbd.ttf"],
    "black": ["fonts/Inter-Black.otf", "DejaVuSans-Bold.ttf", "arialbd.ttf"],
}


# ----------------------------------------------------------------------------
# Утилиты
# ----------------------------------------------------------------------------
def rgb(h, a=None):
    h = h.lstrip("#")
    c = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return c if a is None else (*c, a)


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def ease_out_cubic(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_out_back(x, s=1.6):
    x = clamp(x)
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def ease_in_out(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def parse_pct(s):
    return float(str(s).replace("%", "").replace("Hz", ""))


def fmt_rate(v):
    return f"{int(round(v)):+d}%"


def fmt_pitch(v):
    return f"{int(round(v)):+d}Hz"


_font_cache = {}


def font(kind, size):
    key = (kind, size)
    if key in _font_cache:
        return _font_cache[key]
    for cand in FONT_FILES[kind]:
        p = ROOT / cand
        try:
            f = ImageFont.truetype(str(p if p.exists() else cand), size)
            _font_cache[key] = f
            return f
        except OSError:
            continue
    f = ImageFont.load_default(size)
    _font_cache[key] = f
    return f


def wrap_words(words, fnt, max_w):
    """Разбивает список слов на строки по ширине. Возвращает список списков индексов."""
    lines, cur, cur_w = [], [], 0.0
    sp = fnt.getlength(" ")
    for i, w in enumerate(words):
        ww = fnt.getlength(w)
        if cur and cur_w + sp + ww > max_w:
            lines.append(cur)
            cur, cur_w = [i], ww
        else:
            cur_w = ww if not cur else cur_w + sp + ww
            cur.append(i)
    if cur:
        lines.append(cur)
    return lines


def paste(dst, src, x, y):
    """alpha_composite с обрезкой по краям (допускает отрицательные координаты)."""
    x, y = int(round(x)), int(round(y))
    sw, sh = src.size
    dw, dh = dst.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dw, x + sw), min(dh, y + sh)
    if x1 <= x0 or y1 <= y0:
        return
    if (x0, y0, x1, y1) != (x, y, x + sw, y + sh):
        src = src.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    dst.alpha_composite(src, (x0, y0))


def with_alpha(img, k):
    if k >= 0.999:
        return img
    img = img.copy()
    a = img.getchannel("A").point(lambda v: int(v * k))
    img.putalpha(a)
    return img


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        sys.stderr.write(r.stderr.decode("utf-8", "replace")[-3000:])
        raise RuntimeError("Команда завершилась с ошибкой: " + " ".join(map(str, cmd[:6])) + " ...")
    return r


# ----------------------------------------------------------------------------
# Озвучка (edge-tts) + тайминги слов
# ----------------------------------------------------------------------------
def _patch_ssl():
    """edge-tts использует только certifi; добавляем системный/корпоративный CA, если задан."""
    import edge_tts.communicate as c
    for k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        p = os.environ.get(k)
        if p and os.path.exists(p) and hasattr(c, "_SSL_CTX"):
            try:
                c._SSL_CTX.load_verify_locations(p)
            except Exception:
                pass


FALLBACK_VOICES = {"male": "uk-UA-OstapNeural", "female": "ru-RU-SvetlanaNeural"}


async def _tts_try(text, voice, rate, pitch):
    """Одна попытка синтеза. -> (mp3 bytes, words) или исключение."""
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    audio, words = bytearray(), []
    async for ch in com.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            words.append({"t": ch["offset"] / 1e7, "d": ch["duration"] / 1e7, "w": ch["text"]})
    if not audio:
        raise RuntimeError("пустой ответ")
    return bytes(audio), words


def _variants(text):
    # Сервис иногда стабильно «не отдаёт» фразу, но озвучивает её в другом регистре —
    # звучит это одинаково, поэтому перебираем варианты написания.
    v = [text, text[:1].lower() + text[1:], text.lower(), text.replace("...", "…")]
    return list(dict.fromkeys(v))


async def _tts_robust(text, voice, rate, pitch, tries):
    vs = _variants(text)
    last = None
    for attempt in range(tries):
        try:
            return await _tts_try(vs[attempt % len(vs)], voice, rate, pitch)
        except Exception as e:  # сеть / лимиты / NoAudioReceived
            last = e
            await asyncio.sleep(0.4 + 0.3 * attempt)
    raise last


async def _tts_pieces(text, voice, rate, pitch, tmp, level=0):
    """Озвучка целиком; если сервис упирается — по предложениям, затем по частям через запятую."""
    try:
        return await _tts_robust(text, voice, rate, pitch, tries=8 if level == 0 else 10)
    except Exception:
        pat = (r"(?<=[.!?…])\s+", r"(?<=[,;:—])\s+")
        if level >= len(pat):
            raise
        parts = [x for x in re.split(pat[level], text) if x.strip()]
        if len(parts) < 2:
            return await _tts_pieces(text, voice, rate, pitch, tmp, level + 1)
        audio, words, off = b"", [], 0.0
        for part in parts:
            a, w = await _tts_pieces(part, voice, rate, pitch, tmp, level + 1)
            words += [dict(x, t=x["t"] + off) for x in w]
            tmp.write_bytes(a)
            off += len(decode_audio(tmp)) / SR
            audio += a
        return audio, words


async def _tts_one(text, voice, rate, pitch, out_mp3, out_json, sem):
    flag = out_mp3.with_suffix(".fallback")
    async with sem:
        tmp = out_mp3.with_suffix(".part.mp3")
        try:
            audio, words = await _tts_pieces(text, voice, rate, pitch, tmp)
            flag.unlink(missing_ok=True)
        except Exception:
            if out_mp3.exists() and flag.exists():
                print(f"  [tts] ВНИМАНИЕ: {voice} снова не ответил, оставляю запасной голос: {text[:40]}")
                return
            fb = FALLBACK_VOICES["male" if "Dmitry" in voice else "female"]
            print(f"  [tts] ВНИМАНИЕ: {voice} не отвечает, запасной голос {fb}: {text[:40]}")
            print("         (перезапустите генерацию позже — реплика будет переозвучена)")
            audio, words = await _tts_robust(text, fb, rate, pitch, tries=6)
            flag.write_text(fb)
        finally:
            tmp.unlink(missing_ok=True)
        out_mp3.write_bytes(audio)
        out_json.write_text(json.dumps(words, ensure_ascii=False))
        print(f"  [tts] ок: {text[:50]}")


def synth_all(jobs, cache_dir):
    """jobs: list of (text, voice, rate, pitch). Возвращает list of (mp3_path, words)."""
    _patch_ssl()
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths, todo = [], []
    for text, voice, rate, pitch in jobs:
        key = hashlib.sha1(f"{voice}|{rate}|{pitch}|{text}".encode()).hexdigest()[:16]
        mp3, js = cache_dir / f"{key}.mp3", cache_dir / f"{key}.json"
        paths.append((mp3, js))
        if not (mp3.exists() and js.exists() and mp3.stat().st_size > 0) or mp3.with_suffix(".fallback").exists():
            todo.append((text, voice, rate, pitch, mp3, js))

    if todo:
        print(f"[tts] синтез {len(todo)} реплик...")

        async def main():
            sem = asyncio.Semaphore(6)
            await asyncio.gather(*[_tts_one(*j, sem) for j in todo])

        asyncio.run(main())
    return [(mp3, json.loads(js.read_text())) for mp3, js in paths]


def decode_audio(path):
    r = run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"])
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def tighten(a, words, max_gap=0.2, lead=0.04, tail=0.14):
    """Вырезает лишнюю тишину (по громкости): в начале, в конце и паузы длиннее max_gap.
    Возвращает (новое аудио, слова со сдвинутыми таймингами)."""
    hop = int(0.01 * SR)
    n = len(a) // hop
    if n < 5:
        return a, words
    rms = np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    loud = rms > max(rms.max() * 0.04, 1e-4)
    idx = np.flatnonzero(loud)
    if len(idx) == 0:
        return a, words
    first, last = idx[0] * hop / SR, (idx[-1] + 1) * hop / SR
    keep, cur = [], max(0.0, first - lead)
    k = idx[0]
    while k <= idx[-1]:
        if not loud[k]:
            j = k
            while j <= idx[-1] and not loud[j]:
                j += 1
            if (j - k) * 0.01 > max_gap:
                keep.append((cur, k * 0.01 + max_gap / 2))
                cur = j * 0.01 - max_gap / 2
            k = j
        else:
            k += 1
    keep.append((cur, min(len(a) / SR, last + tail)))
    xf = int(0.006 * SR)
    out, offs, pos = [], [], 0.0
    for a0, a1 in keep:
        seg = a[int(a0 * SR):int(a1 * SR)].copy()
        if len(seg) > 2 * xf:
            seg[:xf] *= np.linspace(0, 1, xf)
            seg[-xf:] *= np.linspace(1, 0, xf)
        out.append(seg)
        offs.append((a0, a1, pos))
        pos += len(seg) / SR

    def remap(t):
        prev_end = 0.0
        for a0, a1, p0 in offs:
            if t < a0:          # слово началось в вырезанной тишине
                return prev_end
            if t < a1:
                return p0 + (t - a0)
            prev_end = p0 + (a1 - a0)
        return pos

    nw = [dict(w, t=remap(w["t"])) for w in words]
    return np.concatenate(out).astype(np.float32), nw


def _norm(s):
    return re.sub(r"[^\w]", "", s.lower().replace("ё", "е"))


def align_words(display_words, boundaries, speech_len):
    """Сопоставляет слова из edge-tts словам текста (с пунктуацией). -> время старта каждого слова."""
    starts = [None] * len(display_words)
    j = 0
    for b in boundaries:
        tok = _norm(b["w"])
        if not tok:
            continue
        k = j
        while k < len(display_words) and tok not in _norm(display_words[k]) and _norm(display_words[k]) not in tok:
            k += 1
        if k < len(display_words) and _norm(display_words[k]):
            if starts[k] is None:
                starts[k] = b["t"]
            j = k + 1
    # дыры (тире, нераспознанные) — интерполяция
    n = len(display_words)
    if all(s is None for s in starts):
        return [speech_len * i / max(1, n) for i in range(n)]
    last = 0.0
    for i in range(n):
        if starts[i] is None:
            nxt = next((starts[k] for k in range(i + 1, n) if starts[k] is not None), None)
            starts[i] = last if nxt is None else (last + nxt) / 2
        last = starts[i]
    return starts


# ----------------------------------------------------------------------------
# Сценарий -> план (тайминги всего ролика)
# ----------------------------------------------------------------------------
def load_script(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"lines": data}
    meta = {
        "title": data.get("title", ""),
        "outro": data.get("outro", ""),
        "driver_name": data.get("driver_name", "Водитель"),
        "driver_status": data.get("driver_status", "в пути"),
        "typing_status": data.get("typing_status", "печатает…"),
        "route_from": data.get("route_from", "Старт"),
        "route_to": data.get("route_to", "Финиш"),
        "clock_start": data.get("clock_start", "08:14"),
    }
    theme = dict(THEME, **data.get("theme", {}))
    voices = json.loads(json.dumps(VOICES))
    for who, ov in data.get("voices", {}).items():
        voices.setdefault(who, {}).update(ov)
    lines = data["lines"]
    for ln in lines:
        if ln.get("who") not in ("driver", "passenger"):
            raise ValueError(f"who должен быть driver или passenger: {ln}")
    return meta, theme, voices, lines


def voice_params(lines, voices, extra_rate):
    """Голос, темп, высота для каждой реплики."""
    jobs = []
    p_idx = [i for i, l in enumerate(lines) if l["who"] == "passenger"]
    for i, ln in enumerate(lines):
        v = voices[ln["who"]]
        if ln["who"] == "passenger":
            k = p_idx.index(i) / max(1, len(p_idx) - 1)
            rate = parse_pct(v.get("rate_start", v.get("rate", "+0%")))
            rate += k * (parse_pct(v.get("rate_end", v.get("rate", "+0%"))) - rate)
            pitch = parse_pct(v.get("pitch_start", v.get("pitch", "+0Hz")))
            pitch += k * (parse_pct(v.get("pitch_end", v.get("pitch", "+0Hz"))) - pitch)
            if "!" in ln["text"]:
                rate += parse_pct(v.get("exclaim_rate", "+0%"))
                pitch += parse_pct(v.get("exclaim_pitch", "+0Hz"))
        else:
            rate = parse_pct(v.get("rate", "+0%"))
            pitch = parse_pct(v.get("pitch", "+0Hz"))
        if "rate" in ln:
            rate = parse_pct(ln["rate"])
        if "pitch" in ln:
            pitch = parse_pct(ln["pitch"])
        jobs.append((ln["text"], ln.get("voice", v["voice"]), fmt_rate(rate + extra_rate), fmt_pitch(pitch)))
    return jobs


def schedule(lines, speech, typing, pause_scale):
    """Расставляет реплики по времени. speech[i] — длительность речи.
    «Печатает…» занимает паузу между репликами (не меньше typing секунд)."""
    out = []
    for i, ln in enumerate(lines):
        if i == 0:
            t_msg = HOOK_DUR + 0.2
            t_type = t_msg - 0.45
        else:
            prev = out[-1]
            gap = max(typing, ln_pause(lines[i - 1]) * pause_scale + 0.12)
            t_msg = prev["t_end"] + gap
            t_type = prev["t_end"] + 0.04
        t_end = t_msg + VOICE_DELAY + speech[i]
        out.append({"t_type": t_type, "t_msg": t_msg, "t_end": t_end})
    content_end = out[-1]["t_end"] + 0.5
    return out, content_end + OUTRO_DUR


def ln_pause(ln):
    return float(ln.get("pause_after", 0.3))


def build_plan(script_path, n_lines=None, fit=True, cache_dir=None):
    meta, theme, voices, lines = load_script(script_path)
    trial = n_lines is not None and n_lines < len(lines)
    if n_lines:
        lines = lines[:n_lines]
    cache_dir = cache_dir or ROOT / ".tts_cache"

    extra_rate = 0.0
    for attempt in range(4):
        tts = synth_all(voice_params(lines, voices, extra_rate), cache_dir)
        speech, audios = [], []
        tts_t = []
        for mp3, words in tts:
            a, words = tighten(decode_audio(mp3), words)
            audios.append(a)
            tts_t.append((mp3, words))
            speech.append(len(a) / SR)
        tts = tts_t
        for typing, ps in ((0.42, 1.0), (0.36, 0.75), (0.3, 0.5)):
            sched, total = schedule(lines, speech, typing, ps)
            if total <= MAX_DUR or trial or not fit:
                break
        if total <= MAX_DUR or trial or not fit:
            break
        fixed = total - sum(speech)
        need = sum(speech) / max(1.0, MAX_DUR - 0.3 - fixed)
        extra_rate += math.ceil((need - 1) * 100) + 1
        print(f"[fit] {total:.1f}s > {MAX_DUR}s — ускоряю озвучку на {extra_rate:+.0f}%")

    if fit and not trial and total < MIN_DUR:
        pauses = sum(ln_pause(l) for l in lines[:-1]) or 1
        ps = min(4.0, 1 + (MIN_DUR - total) / pauses)
        sched, total = schedule(lines, speech, typing, ps)
        if total < MIN_DUR:
            total = MIN_DUR

    # Маршрут: точка прыгает назад на реплике с "route": "jump" (или первой с «налево»)
    jump_i = next((i for i, l in enumerate(lines) if l.get("route") == "jump"), None)
    if jump_i is None:
        jump_i = next((i for i, l in enumerate(lines) if "налево" in l["text"].lower()), None)
    arrive_i = next((i for i, l in enumerate(lines) if l.get("route") == "arrive"), None)

    h0, m0 = (int(x) for x in meta["clock_start"].split(":"))
    plan_lines = []
    for i, (ln, sc, (mp3, words)) in enumerate(zip(lines, sched, tts)):
        disp = ln["text"].split()
        starts = align_words(disp, words, speech[i])
        nxt_type = sched[i + 1]["t_type"] if i + 1 < len(sched) else total - OUTRO_DUR + 0.2
        mins = h0 * 60 + m0 + i
        plan_lines.append({
            "who": ln["who"], "text": ln["text"], "words": disp,
            "word_t": [float(sc["t_msg"] + VOICE_DELAY + s) for s in starts],
            "t_type": sc["t_type"], "t_msg": sc["t_msg"], "t_end": sc["t_end"],
            "t_sub_end": max(sc["t_end"] + 0.1, min(nxt_type + 0.15, sc["t_end"] + 0.9)),
            "clock": f"{(mins // 60) % 24:02d}:{mins % 60:02d}",
        })

    route_t0 = plan_lines[0]["t_msg"]
    route_t1 = plan_lines[arrive_i]["t_msg"] if arrive_i is not None else total - OUTRO_DUR
    plan = {
        "meta": meta, "theme": theme, "lines": plan_lines, "total": total,
        "route_t0": route_t0, "route_t1": route_t1,
        "jump_t": plan_lines[jump_i]["t_msg"] + 0.15 if jump_i is not None and (arrive_i is None or jump_i < arrive_i) else None,
    }
    return plan, audios


# ----------------------------------------------------------------------------
# Аудио: голоса + поп + фоновый бит
# ----------------------------------------------------------------------------
def synth_pop(freq=1150.0, dur=0.085, vol=0.28):
    t = np.arange(int(dur * SR)) / SR
    f = freq * np.exp(-t * 28) + freq * 0.32
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * np.exp(-t * 55) * vol).astype(np.float32)


def synth_beat(total, bpm=94, seed=7):
    rng = np.random.default_rng(seed)
    n = int(total * SR) + SR
    out = np.zeros(n, np.float32)
    step = 60.0 / bpm / 4  # 16-е

    def kick():
        t = np.arange(int(0.42 * SR)) / SR
        f = 48 + 110 * np.exp(-t * 32)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5)

    def snare():
        t = np.arange(int(0.22 * SR)) / SR
        nz = rng.standard_normal(len(t))
        nz = np.convolve(nz, [1, -0.8], "same")
        return (nz * 0.35 + np.sin(2 * np.pi * 190 * t) * 0.4) * np.exp(-t * 20)

    def hat(open_=False):
        t = np.arange(int((0.12 if open_ else 0.04) * SR)) / SR
        nz = np.diff(rng.standard_normal(len(t) + 1))
        return nz * np.exp(-t * (25 if open_ else 90)) * 0.12

    K, S = kick(), snare()
    roots = [55.0, 43.65, 65.41, 49.0]  # A1 F1 C2 G1
    kick_steps, snare_steps = (0, 7, 8, 10), (4, 12)

    def add(sig, pos):
        i = int(pos * SR)
        if i >= n:
            return
        j = min(n, i + len(sig))
        out[i:j] += sig[: j - i]

    bar = 16 * step
    nbars = int(total / bar) + 2
    for b in range(nbars):
        t0 = b * bar
        for s in range(16):
            ts = t0 + s * step + (0.012 if s % 2 else 0)  # лёгкий свинг
            if s in kick_steps:
                add(K * 0.9, ts)
            if s in snare_steps:
                add(S * 0.55, ts)
            if s % 2 == 0:
                add(hat(s == 14) * (1.0 if s % 4 else 0.7), ts)
        # бас (мягкий саб)
        f = roots[b % 4]
        t = np.arange(int(bar * SR)) / SR
        env = np.minimum(1, t * 20) * np.exp(-t * 0.9)
        add((np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t)) * env * 0.35, t0)
    # лоу-фай: мягкий ФНЧ (сглаживание)
    y = np.convolve(out, np.hanning(9) / np.hanning(9).sum(), "same").astype(np.float32)
    y /= max(1e-6, np.abs(y).max())
    return y[: int(total * SR)]


def build_audio(plan, audios, path):
    total = plan["total"]
    n = int(math.ceil(total * SR))
    voice = np.zeros(n, np.float32)
    fx = np.zeros(n, np.float32)

    def add(buf, sig, t):
        i = int(t * SR)
        if i >= n:
            return
        j = min(n, i + len(sig))
        buf[i:j] += sig[: j - i]

    for ln, a in zip(plan["lines"], audios):
        add(voice, a * 0.95, ln["t_msg"] + VOICE_DELAY)
        add(fx, synth_pop(1250 if ln["who"] == "passenger" else 950), ln["t_msg"])
    # вжух на заголовке и «дзынь» на плашке
    t = np.arange(int(0.5 * SR)) / SR
    wh = np.random.default_rng(1).standard_normal(len(t)) * np.sin(np.pi * t / 0.5) ** 2 * 0.06
    add(fx, np.convolve(wh, np.ones(8) / 8, "same").astype(np.float32), 0.0)
    t = np.arange(int(0.7 * SR)) / SR
    chime = (np.sin(2 * np.pi * 1318.5 * t) + 0.6 * np.sin(2 * np.pi * 1975.5 * t)) * np.exp(-t * 6) * 0.12
    add(fx, chime.astype(np.float32), total - OUTRO_DUR + 0.05)

    beat = synth_beat(total)
    beat = np.pad(beat, (0, max(0, n - len(beat))))[:n]
    # сайдчейн: бит тише, когда говорят
    env = np.abs(voice)
    win = int(0.08 * SR)
    env = np.convolve(env, np.ones(win) / win, "same")
    duck = 1 - 0.55 * np.clip(env / 0.04, 0, 1)
    fade = np.ones(n, np.float32)
    fi, fo = int(0.25 * SR), int(0.9 * SR)
    fade[:fi] = np.linspace(0, 1, fi)
    fade[-fo:] = np.linspace(1, 0, fo)
    mix = voice + fx + beat * 0.11 * duck * fade
    mix /= max(1.0, np.abs(mix).max() / 0.98)
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())


# ----------------------------------------------------------------------------
# Отрисовка кадров
# ----------------------------------------------------------------------------
SS = 2  # суперсэмплинг для гладких фигур


class Renderer:
    def __init__(self, plan):
        self.p = plan
        self.th = {k: v for k, v in plan["theme"].items()}
        self.meta = plan["meta"]
        self.lines = plan["lines"]
        self.base = self._make_base()
        self.headers = {False: self._make_header(False), True: self._make_header(True)}
        self.view_bg = self.base.crop((0, VIEW_Y0, W, VIEW_Y1))
        self.bubbles = {}
        self.typing_cache = {}
        self.sub_cache = {}
        self.car = self._make_car()
        self.hook = self._make_hook() if self.meta["title"] else None
        self.outro = self._make_outro() if self.meta["outro"] else None
        self.fade_top = self._make_fade()

    # ---------- статичные слои ----------
    def _make_base(self):
        th = self.th
        im = Image.new("RGBA", (W, H), rgb(th["bg"], 255))
        d = ImageDraw.Draw(im)
        # лёгкий узор точками
        for y in range(VIEW_Y0 + 10, H, 46):
            off = 23 if (y // 46) % 2 else 0
            for x in range(off + 10, W, 46):
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=rgb(th["bg_dots"], 255))
        # полоса маршрута
        d.rectangle((0, ROUTE_Y0, W, ROUTE_Y1), fill=rgb(th["header_bg"], 255))
        d.line((0, ROUTE_Y1, W, ROUTE_Y1), fill=rgb(th["divider"], 255), width=2)
        f = font("medium", 26)
        d.text((86, ROUTE_Y0 + 62), self.meta["route_from"], font=f, fill=rgb(th["muted"]), anchor="lm")
        d.text((W - 86, ROUTE_Y0 + 62), self.meta["route_to"], font=f, fill=rgb(th["muted"]), anchor="rm")
        # затемнение зоны субтитров
        grad = Image.new("L", (1, INPUT_Y0 - VIEW_Y1))
        for i in range(grad.size[1]):
            grad.putpixel((0, i), int(140 * min(1, i / 60)))
        shade = Image.new("RGBA", (W, grad.size[1]), (0, 0, 0, 255))
        shade.putalpha(grad.resize((W, grad.size[1])))
        im.alpha_composite(shade, (0, VIEW_Y1))
        # поле ввода
        big = Image.new("RGBA", ((W) * SS, (INPUT_Y1 - INPUT_Y0) * SS), (0, 0, 0, 0))
        bd = ImageDraw.Draw(big)
        bd.rounded_rectangle((30 * SS, 10 * SS, (W - 150) * SS, (INPUT_Y1 - INPUT_Y0 - 10) * SS),
                             radius=52 * SS, fill=rgb(th["header_bg"], 255), outline=rgb(th["divider"], 255), width=2 * SS)
        cx, cy, r = (W - 82) * SS, (INPUT_Y1 - INPUT_Y0) // 2 * SS, 52 * SS
        bd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgb(th["passenger_bubble"], 255))
        # микрофон
        bd.rounded_rectangle((cx - 11 * SS, cy - 26 * SS, cx + 11 * SS, cy + 8 * SS), radius=11 * SS, fill=(255, 255, 255, 255))
        bd.arc((cx - 19 * SS, cy - 14 * SS, cx + 19 * SS, cy + 18 * SS), 0, 180, fill=(255, 255, 255, 255), width=4 * SS)
        bd.line((cx, cy + 18 * SS, cx, cy + 27 * SS), fill=(255, 255, 255, 255), width=4 * SS)
        big = big.resize((W, INPUT_Y1 - INPUT_Y0), Image.LANCZOS)
        im.alpha_composite(big, (0, INPUT_Y0))
        d = ImageDraw.Draw(im)
        d.text((90, (INPUT_Y0 + INPUT_Y1) // 2), "Сообщение", font=font("regular", 38), fill=rgb(th["muted"]), anchor="lm")
        return im

    def _make_header(self, typing):
        th = self.th
        h = HEADER_Y1 - HEADER_Y0
        big = Image.new("RGBA", (W * SS, h * SS), rgb(th["header_bg"], 255))
        d = ImageDraw.Draw(big)
        s = SS
        cy = 150
        # назад
        d.line(((62 * s, (cy - 24) * s), (40 * s, cy * s), (62 * s, (cy + 24) * s)), fill=rgb(th["text"], 255), width=6 * s, joint="curve")
        # аватар
        ax, r = 150, 56
        d.ellipse(((ax - r) * s, (cy - r) * s, (ax + r) * s, (cy + r) * s), fill=rgb(th["avatar"], 255))
        initial = (self.meta["driver_name"] or "?")[0].upper()
        d.text((ax * s, (cy + 2) * s), initial, font=font("bold", 56 * s), fill=(255, 255, 255, 255), anchor="mm")
        gx, gy, gr = ax + 40, cy + 40, 14
        d.ellipse(((gx - gr) * s, (gy - gr) * s, (gx + gr) * s, (gy + gr) * s), fill=rgb(th["status"], 255),
                  outline=rgb(th["header_bg"], 255), width=5 * s)
        # имя и статус
        d.text((232 * s, (cy - 22) * s), self.meta["driver_name"], font=font("semibold", 46 * s), fill=rgb(th["text"], 255), anchor="ls")
        st = self.meta["typing_status"] if typing else self.meta["driver_status"]
        col = th["typing_status"] if typing else th["status"]
        d.text((232 * s, (cy + 30) * s), st, font=font("medium", 34 * s), fill=rgb(col, 255), anchor="ls")
        # меню «три точки»
        for k in (-18, 0, 18):
            d.ellipse(((W - 60 - 5) * s, (cy + k - 5) * s, (W - 60 + 5) * s, (cy + k + 5) * s), fill=rgb(th["text"], 255))
        img = big.resize((W, h), Image.LANCZOS)
        ImageDraw.Draw(img).line((0, h - 1, W, h - 1), fill=rgb(th["divider"], 255), width=2)
        return img

    def _make_fade(self):
        g = Image.new("RGBA", (W, 50), rgb(self.th["bg"], 255))
        a = Image.new("L", (1, 50))
        for i in range(50):
            a.putpixel((0, i), int(255 * (1 - i / 50) ** 1.5))
        g.putalpha(a.resize((W, 50)))
        return g

    def _make_car(self):
        s = 4
        w, h = 66, 40
        im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        col = rgb(self.th["car"], 255)
        d.rounded_rectangle((2 * s, 14 * s, 64 * s, 30 * s), radius=7 * s, fill=col)
        d.polygon([(14 * s, 15 * s), (22 * s, 4 * s), (44 * s, 4 * s), (54 * s, 15 * s)], fill=col)
        d.polygon([(19 * s, 14 * s), (24 * s, 7 * s), (32 * s, 7 * s), (32 * s, 14 * s)], fill=(40, 50, 70, 255))
        d.polygon([(35 * s, 14 * s), (35 * s, 7 * s), (43 * s, 7 * s), (50 * s, 14 * s)], fill=(40, 50, 70, 255))
        d.rectangle((26 * s, 0, 38 * s, 4 * s), fill=(30, 30, 30, 255))  # шашечка
        d.rectangle((60 * s, 17 * s, 64 * s, 21 * s), fill=(255, 250, 210, 255))
        for cx in (16, 50):
            d.ellipse(((cx - 7) * s, (25) * s, (cx + 7) * s, (39) * s), fill=(20, 20, 24, 255))
            d.ellipse(((cx - 3) * s, (29) * s, (cx + 3) * s, (35) * s), fill=(150, 150, 160, 255))
        im = im.resize((w, h), Image.LANCZOS)
        return {1: im, -1: im.transpose(Image.FLIP_LEFT_RIGHT)}

    # ---------- пузыри ----------
    def _ticks(self, d, x, y, col, s, double=True):
        w = 4 * s
        d.line(((x, y + 9 * s), (x + 6 * s, y + 15 * s), (x + 17 * s, y + 2 * s)), fill=col, width=w, joint="curve")
        if double:
            x2 = x + 10 * s
            d.line(((x2 + 4 * s, y + 13 * s), (x2 + 6 * s, y + 15 * s), (x2 + 17 * s, y + 2 * s)), fill=col, width=w, joint="curve")

    def bubble(self, i, read=False):
        key = (i, read)
        if key in self.bubbles:
            return self.bubbles[key]
        ln = self.lines[i]
        th = self.th
        mine = ln["who"] == "passenger"
        s = SS
        f = font("regular", MSG_FONT * s)
        fm = font("regular", 28 * s)
        pad_x, pad_y = 34, 22
        words = ln["words"]
        rows = wrap_words(words, f, (BUBBLE_MAX_W - 2 * pad_x) * s)
        texts = [" ".join(words[k] for k in r) for r in rows]
        line_h = int(MSG_FONT * 1.32)
        tw = max(f.getlength(t) for t in texts) / s
        meta_w = fm.getlength(ln["clock"]) / s + 12
        last_w = f.getlength(texts[-1]) / s
        # у водителя время внутри пузыря; у пассажирки время + галочки — под пузырём
        inline = mine or last_w + meta_w + 10 <= BUBBLE_MAX_W - 2 * pad_x
        bw = int(max(tw, (last_w + meta_w + 10) if not mine else 0, meta_w) + 2 * pad_x)
        bh = int(pad_y * 2 + line_h * len(texts) + (0 if inline else 30) + 4)
        below = 44 if mine else 0
        im = Image.new("RGBA", (bw * s, (bh + below) * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        col = rgb(th["passenger_bubble" if mine else "driver_bubble"], 255)
        d.rounded_rectangle((0, 0, bw * s - 1, bh * s - 1), radius=38 * s, fill=col)
        # «хвостик»: нижний угол со стороны автора почти острый
        cx0 = bw - 60 if mine else 0
        d.rectangle((cx0 * s, (bh - 60) * s, (cx0 + 60) * s - 1, (bh - 30) * s), fill=col)
        d.rounded_rectangle((cx0 * s, (bh - 60) * s, (cx0 + 60) * s - 1, bh * s - 1), radius=10 * s, fill=col)
        if mine:
            d.rectangle(((cx0 - 30) * s, (bh - 60) * s, (cx0 + 30) * s, bh * s - 1), fill=col)
        else:
            d.rectangle(((cx0 + 30) * s, (bh - 60) * s, (cx0 + 90) * s, bh * s - 1), fill=col)
        tcol = rgb(th["passenger_text" if mine else "driver_text"], 255)
        for k, t in enumerate(texts):
            d.text((pad_x * s, (pad_y + k * line_h + line_h * 0.5 + 2) * s), t, font=f, fill=tcol, anchor="lm")
        if mine:
            my = bh + 24
            self._ticks(d, (bw - 34) * s, (my - 9) * s, rgb(th["tick_read" if read else "tick_sent"], 255), s, double=True)
            d.text(((bw - 46) * s, my * s), ln["clock"], font=fm, fill=rgb(th["muted"], 255), anchor="rm")
            bh += below
        else:
            my = bh - pad_y - 16
            d.text(((bw - pad_x) * s, my * s), ln["clock"], font=fm, fill=rgb(th["bubble_time"], 230), anchor="rm")
        im = im.resize((bw, bh), Image.LANCZOS)
        self.bubbles[key] = im
        return im

    def typing(self, who, phase):
        ph = int(phase * 24) % 24
        key = (who, ph)
        if key in self.typing_cache:
            return self.typing_cache[key]
        s = SS
        w, h = 138, 84
        im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        mine = who == "passenger"
        col = rgb(self.th["passenger_bubble" if mine else "driver_bubble"], 255)
        d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=40 * s, fill=col)
        for j in range(3):
            v = math.sin(2 * math.pi * (ph / 24 - j * 0.16))
            dy = -9 * max(0.0, v)
            a = int(150 + 105 * max(0.0, v))
            cx, cy = (38 + j * 31) * s, (h / 2 + dy) * s
            r = 9 * s
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, a))
        im = im.resize((w, h), Image.LANCZOS)
        self.typing_cache[key] = im
        return im

    # ---------- субтитры ----------
    def _sub_layout(self, i):
        ln = self.lines[i]
        f = font("black", 76)
        rows = wrap_words(ln["words"], f, 940)
        pages = [rows[k:k + 2] for k in range(0, len(rows), 2)]
        return f, pages

    def subtitle(self, i, t):
        ln = self.lines[i]
        f, pages = self._sub_layout(i)
        wt = ln["word_t"]
        cur = -1
        for k, st in enumerate(wt):
            if t >= st:
                cur = k
        if t > ln["t_end"] + 0.05:
            cur = -1
        # страница: та, где текущее слово (или последняя прошедшая)
        ref = cur if cur >= 0 else (len(ln["words"]) - 1 if t > ln["t_end"] else 0)
        pg = next((n for n, pgr in enumerate(pages) if any(ref in r for r in pgr)), 0)
        key = (i, pg, cur)
        if key not in self.sub_cache:
            th = self.th
            line_h = 94
            rows = pages[pg]
            hh = line_h * len(rows) + 30
            im = Image.new("RGBA", (W, hh), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            sp = f.getlength(" ")
            for rn, r in enumerate(rows):
                ws = [ln["words"][k] for k in r]
                total_w = sum(f.getlength(w) for w in ws) + sp * (len(ws) - 1)
                x = (W - total_w) / 2
                y = 15 + rn * line_h + line_h / 2
                for k, w in zip(r, ws):
                    colr = th["sub_hl"] if k == cur else th["sub_text"]
                    d.text((x, y), w, font=f, fill=rgb(colr, 255), anchor="lm",
                           stroke_width=7, stroke_fill=rgb(th["sub_stroke"], 255))
                    x += f.getlength(w) + sp
            self.sub_cache[key] = im
        return self.sub_cache[key]

    # ---------- заголовок и плашка ----------
    def _make_hook(self):
        th = self.th
        f = font("black", 104)
        words = self.meta["title"].split()
        rows = wrap_words(words, f, 920)
        line_h = 124
        hh = line_h * len(rows) + 40
        im = Image.new("RGBA", (W, hh), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        hl_from = max(0, len(words) - 2)  # последние два слова — цветом
        for rn, r in enumerate(rows):
            ws = [words[k] for k in r]
            sp = f.getlength(" ")
            tw = sum(f.getlength(w) for w in ws) + sp * (len(ws) - 1)
            x = (W - tw) / 2
            for k, w in zip(r, ws):
                colr = th["hook_hl"] if k >= hl_from else "#FFFFFF"
                d.text((x, 20 + rn * line_h + line_h / 2), w, font=f, fill=rgb(colr, 255), anchor="lm",
                       stroke_width=9, stroke_fill=(0, 0, 0, 255))
                x += f.getlength(w) + sp
        return im

    def _make_outro(self):
        th = self.th
        text = self.meta["outro"]
        if "«" in text:
            top, rest = text.split("«", 1)
            name = "«" + rest
        else:
            top, name = "", text
        s = SS
        f1, f2 = font("semibold", 50 * s), font("black", 64 * s)
        name_rows = wrap_words(name.split(), f2, 800 * s)
        name_lines = [" ".join(name.split()[k] for k in r) for r in name_rows]
        w = 940
        h = 70 + (66 if top.strip() else 0) + 80 * len(name_lines) + 40 + 96 + 50
        im = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        # градиент
        g = Image.new("RGBA", (1, h * s))
        c1, c2 = rgb(th["outro_bg"]), rgb(th["outro_bg2"])
        for y in range(h * s):
            k = y / (h * s)
            g.putpixel((0, y), tuple(int(c1[i] + (c2[i] - c1[i]) * k) for i in range(3)) + (255,))
        g = g.resize((w * s, h * s))
        mask = Image.new("L", (w * s, h * s), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=56 * s, fill=255)
        im.paste(g, (0, 0), mask)
        d = ImageDraw.Draw(im)
        y = 70
        if top.strip():
            d.text((w / 2 * s, (y + 25) * s), top.strip(), font=f1, fill=(255, 255, 255, 235), anchor="mm")
            y += 66
        for t in name_lines:
            d.text((w / 2 * s, (y + 36) * s), t, font=f2, fill=(255, 255, 255, 255), anchor="mm")
            y += 80
        y += 40
        # «кнопка» с галочками
        bw_, bh_ = 520, 96
        bx = (w - bw_) / 2
        d.rounded_rectangle((bx * s, y * s, (bx + bw_) * s, (y + bh_) * s), radius=48 * s, fill=(255, 255, 255, 255))
        fb = font("bold", 40 * s)
        label = "ПОДПИСАТЬСЯ"
        lw = fb.getlength(label) / s
        lx = w / 2 - (lw + 44) / 2
        self._ticks(d, lx * s, (y + bh_ / 2 - 9) * s, rgb(th["tick_read"], 255), s)
        d.text(((lx + 44) * s, (y + bh_ / 2) * s), label, font=fb, fill=rgb(th["outro_bg2"], 255), anchor="lm")
        return im.resize((w, h), Image.LANCZOS)

    # ---------- маршрут ----------
    def route_progress(self, t):
        p = self.p
        t0, t1 = p["route_t0"], p["route_t1"]
        jt = p["jump_t"]
        lin = lambda a, b, x: a + (b - a) * clamp(x)  # noqa: E731
        start, end = 0.03, 0.97
        if t1 <= t0:
            return start, 1
        if jt is None or t < jt:
            # едем вперёд (с небольшой «уверенностью»)
            k = (t - t0) / (t1 - t0) if jt is None else (t - t0) / (t1 - t0) * 1.15
            return lin(start, end, k), 1
        pj = lin(start, end, (jt - t0) / (t1 - t0) * 1.15)
        back = max(start, pj - 0.24)
        dt = t - jt
        if dt < 0.22:  # резкий прыжок в обратную сторону
            return pj + (back - pj) * ease_out_back(dt / 0.22, 2.2), -1
        k = (t - jt - 0.22) / max(0.1, t1 - jt - 0.22)
        return lin(back, end, ease_in_out(k)), (-1 if dt < 0.9 else 1)

    def draw_route(self, frame, t):
        th = self.th
        d = ImageDraw.Draw(frame)
        y = ROUTE_Y0 + 26
        x0, x1 = 86, W - 86
        p, direction = self.route_progress(t)
        px = x0 + (x1 - x0) * p
        d.line((x0, y, x1, y), fill=rgb(th["route_line"]), width=6)
        d.line((x0, y, max(x0, px), y), fill=rgb(th["route_fill"]), width=6)
        for x, col in ((x0, th["route_fill"]), (x1, th["text"])):
            d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=rgb(col))
        car = self.car[direction]
        shake = 0
        if self.p["jump_t"] is not None and 0 <= t - self.p["jump_t"] < 0.5:
            shake = 4 * math.sin((t - self.p["jump_t"]) * 70)
        paste(frame, car, px - car.width / 2, y - car.height + 14 + shake)

    # ---------- кадр ----------
    def frame(self, t):
        fr = self.base.copy()
        lines = self.lines
        # кто печатает сейчас
        typing_who = None
        for ln in lines:
            if ln["t_type"] <= t < ln["t_msg"]:
                typing_who = ln["who"]
        fr.alpha_composite(self.headers[typing_who == "driver"], (0, HEADER_Y0))
        self.draw_route(fr, t)

        # ----- чат -----
        view = self.view_bg.copy()
        vh = VIEW_Y1 - VIEW_Y0
        items = []
        typ_h = 84
        for i, ln in enumerate(lines):
            if t < ln["t_type"]:
                break
            if t < ln["t_msg"]:
                a = ease_out_cubic((t - ln["t_type"]) / 0.22)
                items.append(("typing", i, (typ_h + GAP) * a, typ_h, a))
            else:
                b = self.bubble(i)
                a = (t - ln["t_msg"]) / 0.3
                full = b.height + GAP
                eff = (typ_h + GAP) + (full - typ_h - GAP) * ease_out_cubic(a)
                items.append(("msg", i, eff, b.height, a))
        total_h = 26 + sum(it[2] for it in items)
        scroll = max(0.0, total_h + 10 - vh)
        y = 26 - scroll
        for kind, i, eff, h, a in items:
            ln = lines[i]
            mine = ln["who"] == "passenger"
            bottom = y + eff - GAP
            if bottom > -20 and y < vh + 20:
                if kind == "typing":
                    im = self.typing(ln["who"], (t - ln["t_type"]) * 1.6)
                    im = with_alpha(im, clamp(a * 1.5))
                    x = W - SIDE - im.width if mine else SIDE
                    paste(view, im, x, bottom - im.height)
                else:
                    read = mine and t >= ln["t_msg"] + 0.55
                    im = self.bubble(i, read)
                    k = ease_out_cubic(a)
                    slide = (1 - k) * 70
                    if a < 1:
                        sc = 0.9 + 0.1 * ease_out_back(a, 1.4)
                        if abs(sc - 1) > 0.004:
                            im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.BILINEAR)
                        im = with_alpha(im, clamp(a * 2.2))
                    x = (W - SIDE - im.width + slide) if mine else (SIDE - slide)
                    paste(view, im, x, bottom - im.height)
            y += eff
        view.alpha_composite(self.fade_top, (0, 0))
        fr.alpha_composite(view, (0, VIEW_Y0))

        # ----- субтитры -----
        for i, ln in enumerate(lines):
            if ln["t_msg"] <= t < ln["t_sub_end"]:
                sub = self.subtitle(i, t)
                a = clamp((t - ln["t_msg"]) / 0.08) * clamp((ln["t_sub_end"] - t) / 0.1)
                paste(fr, with_alpha(sub, a), 0, SUB_CY - sub.height / 2)
                break

        # ----- заголовок-крючок -----
        if self.hook is not None and t < HOOK_DUR:
            k = 1 - clamp((t - (HOOK_DUR - 0.18)) / 0.18)
            dim = Image.new("RGBA", (W, H), (0, 0, 0, int(185 * k)))
            fr.alpha_composite(dim)
            sc = 1.18 - 0.18 * ease_out_back(t / 0.22, 1.8)
            im = self.hook
            if abs(sc - 1) > 0.003:
                im = im.resize((int(im.width * sc), int(im.height * sc)), Image.BILINEAR)
            paste(fr, with_alpha(im, k), (W - im.width) / 2, 880 - im.height / 2)

        # ----- плашка в конце -----
        t_out = self.p["total"] - OUTRO_DUR
        if self.outro is not None and t >= t_out:
            a = (t - t_out) / 0.35
            dim = Image.new("RGBA", (W, H), (0, 0, 0, int(160 * clamp(a))))
            fr.alpha_composite(dim)
            im = self.outro
            yy = 900 - im.height / 2 + (1 - ease_out_back(a, 1.3)) * 700
            paste(fr, im, (W - im.width) / 2, yy)

        return fr.convert("RGB")


# ----------------------------------------------------------------------------
# Сборка видео
# ----------------------------------------------------------------------------
def render_segment(args):
    plan, f0, f1, fps, path = args
    r = Renderer(plan)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-g", str(fps * 2), str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for n in range(f0, f1):
        proc.stdin.write(r.frame(n / fps).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg (видео) упал")
    return path


def main():
    ap = argparse.ArgumentParser(description="Генератор видео-переписки")
    ap.add_argument("script", nargs="?", default="script.json")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--lines", type=int, default=None, help="взять только первые N реплик (пробная версия)")
    ap.add_argument("--fps", type=int, default=FPS)
    ap.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2))))
    ap.add_argument("--no-fit", action="store_true", help="не подгонять длину под 45–60 c")
    ap.add_argument("--frame", type=float, default=None, help="сохранить только кадр на этой секунде (PNG)")
    args = ap.parse_args()

    t_start = time.time()
    plan, audios = build_plan(args.script, args.lines, fit=not args.no_fit)
    total = plan["total"]
    print(f"[plan] реплик: {len(plan['lines'])}, длительность: {total:.2f} c")

    if args.frame is not None:
        out = Path(args.output).with_suffix(".png")
        Renderer(plan).frame(args.frame).save(out)
        print(f"[frame] {out}")
        return

    build = ROOT / ".build"
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir()
    wav = build / "audio.wav"
    build_audio(plan, audios, wav)

    nframes = int(round(total * args.fps))
    nw = max(1, min(args.workers, nframes // 60 or 1))
    bounds = [round(nframes * k / nw) for k in range(nw + 1)]
    jobs = [(plan, bounds[k], bounds[k + 1], args.fps, build / f"seg{k:02d}.mp4") for k in range(nw)]
    print(f"[video] {nframes} кадров, {nw} процесс(а/ов)...")
    if nw == 1:
        segs = [render_segment(jobs[0])]
    else:
        with ProcessPoolExecutor(nw) as ex:
            segs = list(ex.map(render_segment, jobs))
    lst = build / "list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs))
    out = Path(args.output)
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(wav),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
         "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)])
    shutil.rmtree(build, ignore_errors=True)
    print(f"[done] {out.resolve()}  ({total:.1f} c, {time.time() - t_start:.0f} c на сборку)")


if __name__ == "__main__":
    main()
