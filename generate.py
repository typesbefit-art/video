#!/usr/bin/env python3
"""
Генератор вертикального видео «фейковая переписка в мессенджере».

    python generate.py script.json                 -> output.mp4
    python generate.py script.json --lines 6 -o preview.mp4   (пробная версия)

Сюжет и имена — в script.json, голоса/цвета/тайминги — в config.json.
Сам код при смене сюжета трогать не нужно.
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
import wave
from multiprocessing import Pool, cpu_count
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "numpy", "pillow"])
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

try:
    import edge_tts
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "edge-tts"])
    import edge_tts

ROOT = Path(__file__).resolve().parent
SS = 3  # суперсэмплинг для сглаживания фигур


# ----------------------------------------------------------------------------
# Утилиты
# ----------------------------------------------------------------------------

def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def hex2rgb(h, a=None):
    h = h.lstrip("#")
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return rgb + (a,) if a is not None else rgb


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def ease_out_cubic(p):
    p = clamp(p)
    return 1 - (1 - p) ** 3


def ease_out_back(p, s=1.7):
    p = clamp(p) - 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def lerp(a, b, p):
    return a + (b - a) * p


def norm_word(s):
    return re.sub(r"[^\w]", "", s.lower().replace("ё", "е"))


def find_font(paths, size):
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    print("! шрифт не найден, использую встроенный (кириллица может не отображаться)")
    return ImageFont.load_default(size)


def wrap_words(words, font, max_w, space=None):
    """Разбивает список слов на строки по ширине. Возвращает список списков индексов."""
    space = space if space is not None else font.getlength(" ")
    lines, cur, cur_w = [], [], 0
    for i, w in enumerate(words):
        ww = font.getlength(w)
        if cur and cur_w + space + ww > max_w:
            lines.append(cur)
            cur, cur_w = [i], ww
        else:
            cur_w = ww if not cur else cur_w + space + ww
            cur.append(i)
    if cur:
        lines.append(cur)
    return lines


def aa_shape(size, draw_fn):
    """Рисует маску фигуры в увеличенном масштабе и уменьшает — получаем сглаживание."""
    w, h = size
    big = Image.new("L", (w * SS, h * SS), 0)
    draw_fn(ImageDraw.Draw(big), SS)
    return big.resize((w, h), Image.LANCZOS)


def rounded_mask(w, h, r, sharp_corner=None, small_r=10):
    def fn(d, s):
        d.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=r * s, fill=255)
        if sharp_corner:
            # перерисовываем один угол с маленьким радиусом — «хвостик» пузыря
            cw, ch = r * 2 * s, r * 2 * s
            if sharp_corner == "bl":
                box = [0, h * s - ch, cw, h * s - 1]
            else:
                box = [w * s - cw, h * s - ch, w * s - 1, h * s - 1]
            d.rounded_rectangle(box, radius=small_r * s, fill=255)
    return aa_shape((w, h), fn)


def color_layer(size, rgb, mask):
    img = Image.new("RGBA", size, rgb + (0,))
    img.putalpha(mask)
    return img


def with_alpha(img, a):
    if a >= 0.999:
        return img
    img = img.copy()
    img.putalpha(img.getchannel("A").point(lambda v: int(v * a)))
    return img


# ----------------------------------------------------------------------------
# Озвучка (edge-tts)
# ----------------------------------------------------------------------------

def _patch_ssl():
    """В средах с корпоративным/прокси-сертификатом edge-tts игнорирует системный CA."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        import ssl
        try:
            import edge_tts.communicate as cm
            cm._SSL_CTX = ssl.create_default_context(cafile=ca)
        except Exception:
            pass


async def _tts_one(text, spk, mp3_path, boundary="WordBoundary"):
    kwargs = dict(rate=spk.get("rate", "+0%"), pitch=spk.get("pitch", "+0Hz"),
                  volume=spk.get("volume", "+0%"))
    try:
        comm = edge_tts.Communicate(text, spk["voice"], boundary=boundary, **kwargs)
    except TypeError:  # старые версии edge-tts
        comm = edge_tts.Communicate(text, spk["voice"], **kwargs)
    words = []
    with open(mp3_path, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"text": ch["text"], "start": ch["offset"] / 1e7,
                              "dur": ch["duration"] / 1e7})
    return words


def synth_all(lines, cfg, cache_dir):
    _patch_ssl()
    cache_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, ln in enumerate(lines):
        spk = deep_merge(cfg["speakers"][ln["who"]], {k: ln[k] for k in ("voice", "rate", "pitch", "volume") if k in ln})
        key = hashlib.sha1(json.dumps([ln["text"], spk["voice"], spk.get("rate"), spk.get("pitch"),
                                       spk.get("volume")], ensure_ascii=False).encode()).hexdigest()[:16]
        mp3, meta = cache_dir / f"{key}.mp3", cache_dir / f"{key}.json"
        if not (mp3.exists() and meta.exists() and mp3.stat().st_size > 0):
            for attempt in range(8):
                try:
                    # после 4 неудач — запасной режим без пословных таймингов
                    b = "WordBoundary" if attempt < 4 else "SentenceBoundary"
                    words = asyncio.run(_tts_one(ln["text"], spk, mp3, b))
                    if mp3.stat().st_size == 0:
                        raise RuntimeError("пустой ответ TTS")
                    meta.write_text(json.dumps(words, ensure_ascii=False))
                    break
                except Exception as e:
                    print(f"  ! TTS ошибка ({e}), повтор {attempt + 1}/8")
                    time.sleep(min(2 + 2 * attempt, 10))
            else:
                sys.exit("Не удалось получить озвучку от edge-tts (нужен интернет).")
        print(f"  [{i + 1}/{len(lines)}] {ln['who']}: {ln['text']}")
        results.append((mp3, json.loads(meta.read_text())))
    return results


def decode_audio(path, sr):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1",
                          "-ar", str(sr), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def speech_end(x, sr, thr=0.01):
    idx = np.nonzero(np.abs(x) > thr)[0]
    return (idx[-1] / sr + 0.04) if len(idx) else len(x) / sr


def map_word_times(text, boundaries, total):
    """Сопоставляет слова текста (с пунктуацией) с таймингами из TTS."""
    tokens = text.split()
    times = [None] * len(tokens)
    bi = 0
    for ti, tok in enumerate(tokens):
        nt = norm_word(tok)
        if not nt:
            continue
        for j in range(bi, min(bi + 3, len(boundaries))):
            nb = norm_word(boundaries[j]["text"])
            if nb and (nb == nt or nt.startswith(nb) or nb.startswith(nt)):
                times[ti] = boundaries[j]["start"]
                bi = j + 1
                break
    # заполняем пропуски интерполяцией по длине слов
    if all(t is None for t in times):
        lens = np.cumsum([0] + [len(t) + 1 for t in tokens])
        return [total * lens[i] / lens[-1] for i in range(len(tokens))]
    last = 0.0
    for i in range(len(times)):
        if times[i] is None:
            nxt = next((times[j] for j in range(i + 1, len(times)) if times[j] is not None), None)
            times[i] = last if nxt is None else (last + nxt) / 2
        last = times[i]
    return times


# ----------------------------------------------------------------------------
# Таймлайн
# ----------------------------------------------------------------------------

def build_timeline(script, cfg, tts, sr, fit_duration):
    T = cfg["timing"]
    lines = script["lines"]
    audios, voice_durs = [], []
    for (mp3, words), ln in zip(tts, lines):
        a = decode_audio(mp3, sr)
        audios.append(a)
        voice_durs.append(speech_end(a, sr))

    def layout(extra_pause):
        t = T["first_typing_at"]
        events = []
        for i, ln in enumerate(lines):
            typing = ln.get("typing", T["typing_" + ln["who"]] if "typing_" + ln["who"] in T else 0.6)
            ts, tm = t, t + typing
            v0 = tm + T["voice_delay"]
            v1 = v0 + voice_durs[i]
            t = v1 + ln.get("pause_after", 0.3) + extra_pause
            events.append({"typing_start": ts, "msg_t": tm, "voice_start": v0, "voice_end": v1, "end": t})
        outro_start = t + T["tail_before_outro"]
        return events, outro_start, outro_start + T["outro_duration"]

    events, outro_start, total = layout(0.0)
    vmin, vmax = cfg["video"]["min_duration"], cfg["video"]["max_duration"]
    if fit_duration and total < vmin:
        extra = min((vmin - total) / len(lines), 0.9)
        events, outro_start, total = layout(extra)
        print(f"  паузы растянуты на +{extra:.2f} c, чтобы уложиться в {vmin}+ c")
    if fit_duration and total > vmax:
        print(f"  ! ролик длиннее {vmax} c ({total:.1f} c) — сократите сценарий или ускорьте голоса")

    # слова и время
    for i, (ev, ln) in enumerate(zip(events, lines)):
        wt = map_word_times(ln["text"], tts[i][1], voice_durs[i])
        ev["words"] = ln["text"].split()
        ev["word_times"] = [ev["voice_start"] + x for x in wt]

    # часы в пузырях
    hh, mm = map(int, T.get("start_clock", "23:47").split(":"))
    for i, ev in enumerate(events):
        m = hh * 60 + mm + i // 4
        ev["clock"] = f"{(m // 60) % 24:02d}:{m % 60:02d}"

    return events, audios, outro_start, total


# ----------------------------------------------------------------------------
# Звук
# ----------------------------------------------------------------------------

def synth_pop(sr, f0=900, f1=420, dur=0.07):
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = f1 + (f0 - f1) * np.exp(-t * 60)
    ph = 2 * np.pi * np.cumsum(f) / sr
    env = np.exp(-t * 55) * (1 - np.exp(-t * 2000))
    return (np.sin(ph) * env).astype(np.float32)


def synth_beat(sr, bpm, seconds):
    rng = np.random.default_rng(7)
    beat = 60.0 / bpm
    bar = 4 * beat
    loop_len = int(sr * bar * 4)
    out = np.zeros(loop_len, np.float32)

    def add(sig, at):
        i = int(at * sr)
        j = min(loop_len, i + len(sig))
        if i < loop_len:
            out[i:j] += sig[:j - i]

    def kick():
        n = int(sr * 0.35); t = np.arange(n) / sr
        f = 48 + 90 * np.exp(-t * 30)
        return (np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 9)).astype(np.float32) * 0.9

    def snare():
        n = int(sr * 0.2); t = np.arange(n) / sr
        noise = rng.standard_normal(n).astype(np.float32)
        noise = np.convolve(noise, np.ones(4) / 4, "same")
        body = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)
        return ((noise * 0.35 * np.exp(-t * 22)) + body * 0.25).astype(np.float32)

    def hat(v):
        n = int(sr * 0.05); t = np.arange(n) / sr
        noise = rng.standard_normal(n).astype(np.float32)
        noise = np.diff(noise, prepend=0)  # грубый ВЧ-фильтр
        return (noise * np.exp(-t * 90) * 0.12 * v).astype(np.float32)

    def tone(freqs, dur, amp, decay):
        n = int(sr * dur); t = np.arange(n) / sr
        s = sum(np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) for f in freqs)
        env = (1 - np.exp(-t * 40)) * np.exp(-t * decay)
        return (s * env * amp / len(freqs)).astype(np.float32)

    # Am – F – C – G
    chords = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [196.0, 261.63, 329.63], [196.0, 246.94, 293.66]]
    roots = [55.0, 43.65, 65.41, 49.0]
    k, s = kick(), snare()
    for b in range(4):
        t0 = b * bar
        add(tone(chords[b], bar, 0.10, 0.6), t0)
        for q in range(4):
            tq = t0 + q * beat
            if q in (0, 2):
                add(k, tq)
                add(tone([roots[b]], beat * 1.5, 0.35, 2.0), tq)
            if q in (1, 3):
                add(s, tq)
            add(hat(1.0), tq)
            add(hat(0.55), tq + beat / 2)
        add(k * 0.6, t0 + 2.5 * beat)
    reps = int(math.ceil(seconds * sr / loop_len)) + 1
    return np.tile(out, reps)[: int(seconds * sr)]


def build_audio(events, audios, outro_start, total, cfg, script, out_wav):
    A = cfg["audio"]
    sr = A["sample_rate"]
    n = int(total * sr) + sr
    voice = np.zeros(n, np.float32)
    fx = np.zeros(n, np.float32)
    for ev, a, ln in zip(events, audios, script["lines"]):
        i = int(ev["voice_start"] * sr)
        voice[i:i + len(a)] += a[: n - i] * A["voice_gain"]
        side = cfg["speakers"][ln["who"]]["side"]
        pop = synth_pop(sr, 1050, 520) if side == "right" else synth_pop(sr, 780, 380)
        j = int(ev["msg_t"] * sr)
        fx[j:j + len(pop)] += pop[: n - j] * A["pop_gain"]
    pop = synth_pop(sr, 1200, 600, 0.09)
    j = int(outro_start * sr)
    fx[j:j + len(pop)] += pop[: n - j] * A["pop_gain"] * 1.2

    beat = synth_beat(sr, A["beat_bpm"], n / sr)
    # дакинг: бит тише, когда звучит голос
    win = int(sr * 0.12)
    env = np.convolve((np.abs(voice) > 0.015).astype(np.float32), np.ones(win) / win, "same")
    env = np.clip(env * 3, 0, 1)
    gain = A["beat_gain"] * (1 - A["beat_duck"] * env)
    t = np.arange(n) / sr
    gain *= np.clip(t / 0.4, 0, 1) * np.clip((total - t) / 0.8, 0, 1)
    mix = voice + fx + beat * gain
    peak = np.max(np.abs(mix)) or 1.0
    mix = mix / peak * 0.89
    mix = mix[: int(total * sr)]
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(stereo.tobytes())


# ----------------------------------------------------------------------------
# Рендер кадров
# ----------------------------------------------------------------------------

class Renderer:
    def __init__(self, data):
        self.cfg = cfg = data["cfg"]
        self.script = data["script"]
        self.events = data["events"]
        self.outro_start = data["outro_start"]
        self.total = data["total"]
        V, C = cfg["video"], cfg["colors"]
        self.W, self.H = V["width"], V["height"]
        self.k = self.W / 1080.0
        k = self.k
        F = cfg["fonts"]
        self.f_msg = find_font(F["regular"], int(46 * k))
        self.f_time = find_font(F["regular"], int(26 * k))
        self.f_name = find_font(F["medium"], int(46 * k))
        self.f_status = find_font(F["regular"], int(33 * k))
        self.f_read = find_font(F["medium"], int(26 * k))
        self.f_sub = find_font(F["bold"], int(80 * k))
        self.f_hook = find_font(F["bold"], int(88 * k))
        self.f_out1 = find_font(F["medium"], int(54 * k))
        self.f_out2 = find_font(F["bold"], int(62 * k))
        self.f_btn = find_font(F["bold"], int(40 * k))
        self.f_avatar = find_font(F["medium"], int(52 * k))
        self.f_hint = find_font(F["regular"], int(38 * k))

        self.header_h = int(230 * k)
        self.chat_bottom = int(1300 * k)
        self.sub_center = int(1505 * k)
        self.input_top = int(1770 * k)
        self.margin = int(38 * k)
        self.gap = int(20 * k)
        self.gap_switch = int(34 * k)

        self.bg = self._make_background()
        self.headers = {}
        self.bubbles = [self._make_bubble(i) for i in range(len(self.events))]
        self.typing = {s: self._make_typing_frames(s) for s in ("left", "right")}
        self.typing_h = self.typing["left"][0].height
        self.sub_cache = {}
        self.hook = self._make_hook()
        self.outro_dim, self.outro_card = self._make_outro()
        self.top_fade = self._make_top_fade()

    # ---- статичные элементы ------------------------------------------------

    def _make_background(self):
        C, W, H, k = self.cfg["colors"], self.W, self.H, self.k
        top, bot = np.array(hex2rgb(C["bg_top"]), float), np.array(hex2rgb(C["bg_bottom"]), float)
        grad = np.linspace(0, 1, H)[:, None]
        arr = (top * (1 - grad) + bot * grad)[:, None, :].repeat(W, axis=1)
        # еле заметный узор-точки, чтобы фон не был «пустым»
        yy, xx = np.mgrid[0:H, 0:W]
        dots = ((xx % int(54 * k) < 3) & (yy % int(54 * k) < 3)).astype(float) * 6
        arr += dots[:, :, None]
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
        d = ImageDraw.Draw(img)
        # нижняя панель ввода
        d.rectangle([0, self.input_top, W, H], fill=hex2rgb(C["input_bar"]))
        fh = int(96 * k)
        fy = self.input_top + int(28 * k)
        fw = W - int(200 * k)
        field = color_layer((fw, fh), hex2rgb(C["input_field"]), rounded_mask(fw, fh, fh // 2))
        img.paste(field, (int(40 * k), fy), field)
        d.text((int(84 * k), fy + fh // 2), "Сообщение", font=self.f_hint, fill=hex2rgb(C["input_hint"]), anchor="lm")
        # кнопка-микрофон
        r = fh // 2
        cx, cy = W - int(40 * k) - r - int(10 * k), fy + r
        circ = color_layer((2 * r, 2 * r), hex2rgb(C["read_check"]),
                           aa_shape((2 * r, 2 * r), lambda dd, s: dd.ellipse([0, 0, 2 * r * s - 1, 2 * r * s - 1], fill=255)))
        img.paste(circ, (cx - r, cy - r), circ)
        mw, mh = int(20 * k), int(34 * k)
        d.rounded_rectangle([cx - mw // 2, cy - mh // 2 - int(6 * k), cx + mw // 2, cy + mh // 2 - int(6 * k)],
                            radius=mw // 2, fill=(255, 255, 255))
        d.arc([cx - int(18 * k), cy - int(22 * k), cx + int(18 * k), cy + int(18 * k)], 20, 160,
              fill=(255, 255, 255), width=max(2, int(4 * k)))
        d.line([cx, cy + int(18 * k), cx, cy + int(28 * k)], fill=(255, 255, 255), width=max(2, int(4 * k)))
        return img

    def _make_top_fade(self):
        C, W, k = self.cfg["colors"], self.W, self.k
        h = int(70 * k)
        top = hex2rgb(C["bg_top"])
        a = np.linspace(255, 0, h).astype(np.uint8)
        img = Image.new("RGBA", (W, h), top + (0,))
        img.putalpha(Image.fromarray(np.repeat(a[:, None], W, axis=1), "L"))
        return img

    def header(self, status):
        if status in self.headers:
            return self.headers[status]
        C, W, k = self.cfg["colors"], self.W, self.k
        chat = self.script.get("chat", {})
        h = self.header_h
        img = Image.new("RGB", (W, h), hex2rgb(C["header"]))
        d = ImageDraw.Draw(img)
        d.line([0, h - 1, W, h - 1], fill=hex2rgb(C["header_line"]), width=max(1, int(2 * k)))
        cy = int(140 * k)
        # стрелка «назад»
        aw = max(3, int(6 * k))
        d.line([(int(62 * k), cy - int(22 * k)), (int(40 * k), cy), (int(62 * k), cy + int(22 * k))],
               fill=hex2rgb(C["status"]), width=aw, joint="curve")
        # аватар-кружок с инициалом
        r = int(52 * k)
        ax = int(100 * k)
        ga, gb = np.array(hex2rgb(C["avatar_a"]), float), np.array(hex2rgb(C["avatar_b"]), float)
        g = np.linspace(0, 1, 2 * r)
        grad = (ga * (1 - g[:, None]) + gb * g[:, None])[:, None, :].repeat(2 * r, axis=1).astype(np.uint8)
        av = Image.fromarray(grad, "RGB").convert("RGBA")
        av.putalpha(aa_shape((2 * r, 2 * r), lambda dd, s: dd.ellipse([0, 0, 2 * r * s - 1, 2 * r * s - 1], fill=255)))
        img.paste(av, (ax, cy - r), av)
        name = chat.get("name", "Врач")
        d.text((ax + r, cy), (name[:1] or "?").upper(), font=self.f_avatar, fill=(255, 255, 255), anchor="mm")
        tx = ax + 2 * r + int(28 * k)
        d.text((tx, cy - int(4 * k)), name, font=self.f_name, fill=hex2rgb(C["name"]), anchor="ls")
        d.text((tx, cy + int(10 * k)), status, font=self.f_status, fill=hex2rgb(C["status"]), anchor="lt")
        # меню «три точки»
        mx = W - int(56 * k)
        for dy in (-18, 0, 18):
            rr = int(5 * k)
            d.ellipse([mx - rr, cy + int(dy * k) - rr, mx + rr, cy + int(dy * k) + rr], fill=hex2rgb(C["name"]))
        self.headers[status] = img
        return img

    def _make_bubble(self, i):
        ev, ln = self.events[i], self.script["lines"][i]
        spk, C, k = self.cfg["speakers"][ln["who"]], self.cfg["colors"], self.k
        side = spk["side"]
        pad_x, pad_y = int(34 * k), int(22 * k)
        max_inner = int(self.W * 0.70) - 2 * pad_x
        words = ln["text"].split()
        rows = wrap_words(words, self.f_msg, max_inner)
        row_txt = [" ".join(words[j] for j in r) for r in rows]
        lh = int(self.f_msg.size * 1.28)
        time_w = self.f_time.getlength(ev["clock"]) + int(18 * k)
        widths = [self.f_msg.getlength(t) for t in row_txt]
        extra_row = widths[-1] + time_w > max_inner
        inner_w = max(max(widths), (widths[-1] + time_w) if not extra_row else time_w)
        bw = int(inner_w + 2 * pad_x)
        bh = int(len(rows) * lh + 2 * pad_y + (int(30 * k) if extra_row else int(4 * k)))
        receipt = spk.get("read_receipt", False)
        rh = int(46 * k) if receipt else 0
        img = Image.new("RGBA", (bw, bh + rh), (0, 0, 0, 0))
        mask = rounded_mask(bw, bh, int(38 * k), "br" if side == "right" else "bl", int(10 * k))
        img.paste(color_layer((bw, bh), hex2rgb(spk["bubble"]), mask), (0, 0))
        d = ImageDraw.Draw(img)
        for r, t in enumerate(row_txt):
            d.text((pad_x, pad_y + r * lh + int(lh * 0.78)), t, font=self.f_msg, fill=hex2rgb(spk["text"]), anchor="ls")
        d.text((bw - int(22 * k), bh - int(14 * k)), ev["clock"], font=self.f_time, fill=hex2rgb(spk["time"]), anchor="rs")
        if receipt:
            col = hex2rgb(C["read_check"])
            label = "Прочитано"
            lw = self.f_read.getlength(label)
            y = bh + int(30 * k)
            d.text((bw - int(6 * k), y), label, font=self.f_read, fill=col, anchor="rs")
            self._draw_checks(d, bw - int(6 * k) - lw - int(14 * k), y - int(4 * k), col)
        return {"img": img, "side": side, "who": ln["who"]}

    def _draw_checks(self, d, right_x, base_y, col):
        k = self.k
        w = max(2, int(4 * k))
        s = int(16 * k)
        for off in (0, int(14 * k)):
            x = right_x - off
            d.line([(x - s * 1.25, base_y - s * 0.45), (x - s * 0.8, base_y), (x, base_y - s)], fill=col, width=w, joint="curve")

    def _make_typing_frames(self, side):
        C, k = self.cfg["colors"], self.k
        bw, bh = int(150 * k), int(90 * k)
        col = hex2rgb(C["typing_bubble_right" if side == "right" else "typing_bubble_left"])
        mask = rounded_mask(bw, bh, int(38 * k), "br" if side == "right" else "bl", int(10 * k))
        base = color_layer((bw, bh), col, mask)
        frames = []
        dot = hex2rgb(C["typing_dot"])
        n = 24
        for f in range(n):
            img = base.copy()
            d = ImageDraw.Draw(img)
            for j in range(3):
                ph = (f / n - j * 0.15) % 1.0
                lift = max(0.0, math.sin(ph * 2 * math.pi)) if ph < 0.5 else 0.0
                r = int(9 * k)
                cx = bw // 2 + int((j - 1) * 30 * k)
                cy = bh // 2 - int(lift * 10 * k)
                a = int(140 + 115 * lift)
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dot + (a,))
            frames.append(img)
        return frames

    def _make_hook(self):
        C, W, H, k = self.cfg["colors"], self.W, self.H, self.k
        text = self.script.get("hook", "")
        if not text:
            return None
        words = text.split()
        rows = wrap_words(words, self.f_hook, int(W * 0.80))
        lh = int(self.f_hook.size * 1.32)
        pad = int(26 * k)
        boxes = []
        for r in rows:
            t = " ".join(words[j] for j in r)
            boxes.append((t, self.f_hook.getlength(t)))
        h = len(rows) * lh + pad
        img = Image.new("RGBA", (W, h + 2 * pad), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for r, (t, tw) in enumerate(boxes):
            y = pad + r * lh
            bw, bhh = int(tw + 2 * pad), lh - int(8 * k)
            x = (W - bw) // 2
            m = rounded_mask(bw, bhh, int(22 * k))
            col = hex2rgb(C["hook_accent"]) if r % 2 == 0 else (255, 255, 255)
            img.paste(color_layer((bw, bhh), col, m), (x, y), m)
            d.text((W // 2, y + bhh // 2), t, font=self.f_hook, fill=(15, 15, 18), anchor="mm")
        return img

    def _make_outro(self):
        C, W, H, k = self.cfg["colors"], self.W, self.H, self.k
        o = self.script.get("outro", {})
        dim = Image.new("RGBA", (W, H), (0, 0, 0, 150))
        cw = int(920 * k)
        words2 = o.get("channel", "").split()
        rows2 = wrap_words(words2, self.f_out2, cw - int(100 * k))
        lh2 = int(self.f_out2.size * 1.25)
        ch = int(110 * k) + len(rows2) * lh2 + int(190 * k)
        card = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        card.paste(color_layer((cw, ch), hex2rgb(C["outro_card"]), rounded_mask(cw, ch, int(48 * k))), (0, 0))
        d = ImageDraw.Draw(card)
        d.text((cw // 2, int(78 * k)), o.get("top", ""), font=self.f_out1, fill=hex2rgb(C["outro_text"]), anchor="ms")
        y = int(110 * k)
        for r in rows2:
            d.text((cw // 2, y + int(lh2 * 0.8)), " ".join(words2[j] for j in r), font=self.f_out2,
                   fill=hex2rgb(C["outro_accent"]), anchor="ms")
            y += lh2
        # кнопка
        bw, bh = int(520 * k), int(100 * k)
        bx, by = (cw - bw) // 2, y + int(50 * k)
        card.paste(color_layer((bw, bh), hex2rgb(C["outro_accent"]), rounded_mask(bw, bh, bh // 2)), (bx, by),
                   rounded_mask(bw, bh, bh // 2))
        label = "ПОДПИСАТЬСЯ"
        lw = self.f_btn.getlength(label)
        d.text((cw // 2 + int(26 * k), by + bh // 2), label, font=self.f_btn, fill=(255, 255, 255), anchor="mm")
        self._draw_checks(d, cw // 2 - lw / 2 + int(6 * k), by + bh // 2 + int(10 * k), (255, 255, 255))
        return dim, card

    # ---- субтитры ----------------------------------------------------------

    def subtitle(self, i, hl):
        key = (i, hl)
        if key in self.sub_cache:
            return self.sub_cache[key]
        C, W, k = self.cfg["colors"], self.W, self.k
        words = self.events[i]["words"]
        f = self.f_sub
        rows = wrap_words(words, f, int(W * 0.86))
        lh = int(f.size * 1.18)
        stroke = int(8 * k)
        space = f.getlength(" ")
        h = len(rows) * lh + 2 * stroke + int(20 * k)
        img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for r, row in enumerate(rows):
            ws = [f.getlength(words[j]) for j in row]
            x = (W - (sum(ws) + space * (len(row) - 1))) / 2
            y = stroke + r * lh + int(lh * 0.82)
            for j, w in zip(row, ws):
                col = C["subtitle_highlight"] if j == hl else C["subtitle"]
                d.text((x, y), words[j], font=f, fill=hex2rgb(col), anchor="ls",
                       stroke_width=stroke, stroke_fill=hex2rgb(C["subtitle_stroke"]))
                x += w + space
        if len(self.sub_cache) > 400:
            self.sub_cache.clear()
        self.sub_cache[key] = img
        return img

    # ---- кадр --------------------------------------------------------------

    def slot_height(self, i, t):
        ev = self.events[i]
        if t < ev["typing_start"]:
            return 0.0
        g = self.gap_switch if i > 0 and self.bubbles[i - 1]["side"] != self.bubbles[i]["side"] else self.gap
        th = self.typing_h + g
        mh = self.bubbles[i]["img"].height + g
        if t < ev["msg_t"]:
            return th * ease_out_cubic((t - ev["typing_start"]) / 0.22)
        return lerp(th, mh, ease_out_cubic((t - ev["msg_t"]) / 0.28))

    def render(self, t):
        W, H, k = self.W, self.H, self.k
        frame = self.bg.copy()
        n = len(self.events)
        heights = [self.slot_height(i, t) for i in range(n)]
        y_bottom = self.chat_bottom
        status = self.script.get("chat", {}).get("status", "в сети")
        for i in range(n - 1, -1, -1):
            if heights[i] <= 0:
                continue
            ev, b = self.events[i], self.bubbles[i]
            yb = y_bottom
            y_bottom -= heights[i]
            if yb < self.header_h - 10:
                break
            right = b["side"] == "right"
            if t < ev["msg_t"]:
                # индикатор «печатает»
                fr = self.typing[b["side"]][int(t * 40) % len(self.typing[b["side"]])]
                p = ease_out_cubic((t - ev["typing_start"]) / 0.18)
                img = with_alpha(fr, p)
                x = W - self.margin - img.width if right else self.margin
                frame.paste(img, (int(x), int(yb - img.height)), img)
                if not right:
                    dots = "." * (int(t * 3) % 4)
                    status = self.script.get("chat", {}).get("typing_status", "печатает") + dots
            else:
                p = (t - ev["msg_t"]) / 0.32
                img = b["img"]
                if p < 1:
                    e = ease_out_back(p, 1.4)
                    sc = 0.86 + 0.14 * e
                    nw, nh = max(1, int(img.width * sc)), max(1, int(img.height * sc))
                    img = with_alpha(img.resize((nw, nh), Image.BILINEAR), clamp(p * 3))
                    dx = (1 - ease_out_cubic(p)) * 50 * k * (1 if right else -1)
                    dy = (1 - ease_out_cubic(p)) * 40 * k
                else:
                    dx = dy = 0
                x = W - self.margin - img.width if right else self.margin
                frame.paste(img, (int(x + dx), int(yb - img.height + dy)), img)
        frame.paste(self.top_fade, (0, self.header_h), self.top_fade)
        frame.paste(self.header(status), (0, 0))

        # субтитры
        for i in range(n - 1, -1, -1):
            ev = self.events[i]
            if ev["msg_t"] <= t < ev["end"]:
                hl = -1
                if ev["voice_start"] <= t <= ev["voice_end"] + 0.05:
                    for j, wt in enumerate(ev["word_times"]):
                        if wt <= t:
                            hl = j
                sub = self.subtitle(i, hl)
                p = (t - ev["msg_t"]) / 0.15
                fade_out = clamp((ev["end"] - t) / 0.12)
                if p < 1 or fade_out < 1:
                    sc = 0.9 + 0.1 * ease_out_back(p)
                    sub = sub.resize((int(sub.width * sc), int(sub.height * sc)), Image.BILINEAR) if p < 1 else sub
                    sub = with_alpha(sub, clamp(p * 2) * fade_out)
                frame.paste(sub, ((W - sub.width) // 2, int(self.sub_center - sub.height / 2)), sub)
                break

        # хук
        hd = self.cfg["timing"]["hook_duration"]
        if self.hook is not None and t < hd:
            fade = clamp((hd - t) / 0.2)
            dim = Image.new("RGBA", (W, H), (0, 0, 0, int(170 * fade)))
            frame.paste(dim, (0, 0), dim)
            p = t / 0.25
            sc = 0.75 + 0.25 * ease_out_back(p)
            img = self.hook
            if sc != 1:
                img = img.resize((int(img.width * sc), int(img.height * sc)), Image.BILINEAR)
            img = with_alpha(img, clamp(p * 3) * fade)
            frame.paste(img, ((W - img.width) // 2, int(H * 0.42 - img.height / 2)), img)

        # финальная плашка
        if t >= self.outro_start:
            p = (t - self.outro_start) / 0.4
            frame.paste(with_alpha(self.outro_dim, clamp(p * 2)), (0, 0), with_alpha(self.outro_dim, clamp(p * 2)))
            card = self.outro_card
            pulse = 1 + 0.02 * math.sin((t - self.outro_start) * 8) * clamp(p - 1, 0, 1)
            sc = (0.8 + 0.2 * ease_out_back(p)) * pulse
            if abs(sc - 1) > 1e-3:
                card = card.resize((int(card.width * sc), int(card.height * sc)), Image.BILINEAR)
            card = with_alpha(card, clamp(p * 3))
            dy = (1 - ease_out_cubic(p)) * 140 * k
            frame.paste(card, ((W - card.width) // 2, int(H * 0.44 - card.height / 2 + dy)), card)
        return frame.tobytes()


_R = None


def _init_worker(data):
    global _R
    _R = Renderer(data)


def _render_frame(idx):
    return _R.render(idx / _R.cfg["video"]["fps"])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Видео-переписка для Shorts/TikTok/Reels")
    ap.add_argument("script", nargs="?", default="script.json")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("-c", "--config", default=str(ROOT / "config.json"))
    ap.add_argument("--lines", type=int, default=0, help="взять только первые N реплик (пробная версия)")
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 0))
    ap.add_argument("--frame", type=float, default=None, help="сохранить один кадр (секунда) в PNG и выйти")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("Нужен ffmpeg в PATH (https://ffmpeg.org/download.html)")

    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    if isinstance(script, list):
        script = {"lines": script}
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if Path(args.config).exists() else {}
    cfg = deep_merge(cfg, script.get("config", {}))
    preview = args.lines > 0
    if preview:
        script["lines"] = script["lines"][: args.lines]
    for ln in script["lines"]:
        if ln["who"] not in cfg["speakers"]:
            sys.exit(f"Неизвестный говорящий '{ln['who']}' — добавьте его в config.json → speakers")

    sr = cfg["audio"]["sample_rate"]
    fps = cfg["video"]["fps"]
    print("1/4 Озвучка (edge-tts)…")
    tts = synth_all(script["lines"], cfg, ROOT / ".tts_cache")
    print("2/4 Таймлайн…")
    events, audios, outro_start, total = build_timeline(script, cfg, tts, sr, fit_duration=not preview)
    print(f"  длительность: {total:.2f} c, кадров: {int(total * fps)}")

    data = {"cfg": cfg, "script": script, "events": events, "outro_start": outro_start, "total": total}

    if args.frame is not None:
        r = Renderer(data)
        img = Image.frombytes("RGB", (r.W, r.H), r.render(args.frame))
        out = Path(args.output).with_suffix(".png")
        img.save(out)
        print("кадр сохранён:", out)
        return

    out = Path(args.output).resolve()
    tmp_wav = out.with_suffix(".audio.wav")
    print("3/4 Звук (голоса + поп + бит)…")
    build_audio(events, audios, outro_start, total, cfg, script, tmp_wav)

    print(f"4/4 Кадры и сборка ({args.workers} процессов)…")
    n_frames = int(round(total * fps))
    V = cfg["video"]
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{V['width']}x{V['height']}", "-r", str(fps), "-i", "-",
           "-i", str(tmp_wav),
           "-c:v", "libx264", "-preset", V.get("preset", "medium"), "-crf", str(V.get("crf", 19)),
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(fps),
           "-c:a", "aac", "-b:a", "192k", "-ar", str(sr),
           "-shortest", "-movflags", "+faststart", str(out)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    with Pool(args.workers, initializer=_init_worker, initargs=(data,)) as pool:
        for i, fr in enumerate(pool.imap(_render_frame, range(n_frames), chunksize=6)):
            ff.stdin.write(fr)
            if i % (fps * 5) == 0:
                print(f"\r  кадр {i}/{n_frames}  ({time.time() - t0:.0f} c)", end="", flush=True)
    ff.stdin.close()
    ff.wait()
    tmp_wav.unlink(missing_ok=True)
    print()
    if ff.returncode != 0:
        sys.exit("ffmpeg завершился с ошибкой")
    print(f"Готово: {out}  ({total:.1f} c, {time.time() - t0:.0f} c рендера)")


if __name__ == "__main__":
    main()
