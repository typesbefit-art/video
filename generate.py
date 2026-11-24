#!/usr/bin/env python3
"""
Генератор вертикального видео «страшная история с озвучкой и субтитрами».

    python generate.py story.txt                  -> output.mp4 (30 fps)
    python generate.py story.txt --fps 60         -> 60 fps
    python generate.py story.txt --preview 15     -> только первые 15 секунд
    python generate.py story.txt -o my.mp4 --seed 7

Все настройки (голос, цвета, громкости) — в config.py.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C  # noqa: E402

SR = 48000
W, H = C.WIDTH, C.HEIGHT


def log(*a):
    print(*a, flush=True)


def db(x):
    return 10.0 ** (x / 20.0)


def rms(x):
    x = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(x * x) + 1e-20))


def to_db(v):
    return 20.0 * math.log10(max(v, 1e-12))


def need_tool(name):
    if shutil.which(name) is None:
        sys.exit(f"Не найден {name}. Установите ffmpeg (https://ffmpeg.org) и добавьте в PATH.")


# =============================================================== ТЕКСТ ИСТОРИИ
def read_story(path):
    with open(path, encoding="utf-8") as f:
        lines = [l.strip() for l in f.read().splitlines()]
    lines = [l for l in lines if l]
    if len(lines) < 2:
        sys.exit("story.txt: первая строка — заголовок, дальше — текст истории.")
    title = lines[0]
    body = re.sub(r"\s+", " ", " ".join(lines[1:])).strip()
    sentences = [s.strip() for s in re.findall(r'[^.!?…]+(?:[.!?…]+[»"”’)\]]*|$)', body)]
    sentences = [s for s in sentences if re.search(r"\w", s)]
    return title, sentences


def norm(s):
    return re.sub(r"[^\w]", "", s.lower().replace("ё", "е"))


def tokenize(sentence):
    """Слова для субтитров (знаки препинания приклеены к соседнему слову)."""
    toks = []
    for raw in sentence.split():
        if norm(raw) or not toks:
            toks.append(raw)
        else:
            toks[-1] += " " + raw
    # токен из одной пунктуации в начале приклеиваем к следующему
    if len(toks) > 1 and not norm(toks[0]):
        toks[1] = toks[0] + " " + toks[1]
        toks = toks[1:]
    return toks


# =============================================================== ОЗВУЧКА
def _patch_edge_tts_ssl():
    """Если в окружении задан свой CA (корпоративный прокси) — добавляем его в edge-tts."""
    try:
        import edge_tts.communicate as ec
    except Exception:
        return
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        p = os.environ.get(var)
        if p and os.path.isfile(p):
            try:
                ec._SSL_CTX.load_verify_locations(p)
            except Exception:
                pass


def decode_audio(path):
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def tts(text, rate, cache_dir):
    """Возвращает (аудио float32 @SR, [ {text,start,end} ]) — тайминги из WordBoundary."""
    import edge_tts
    key = hashlib.sha1(json.dumps([text, C.VOICE, rate, C.PITCH]).encode()).hexdigest()[:20]
    mp3 = os.path.join(cache_dir, key + ".mp3")
    js = os.path.join(cache_dir, key + ".json")
    if not (os.path.exists(mp3) and os.path.exists(js)):
        async def run(r):
            comm = edge_tts.Communicate(text, C.VOICE, rate=r, pitch=C.PITCH,
                                        boundary="WordBoundary")
            words = []
            with open(mp3 + ".part", "wb") as f:
                async for ch in comm.stream():
                    if ch["type"] == "audio":
                        f.write(ch["data"])
                    elif ch["type"] == "WordBoundary":
                        s = ch["offset"] / 1e7
                        words.append({"text": ch["text"], "start": s, "end": s + ch["duration"] / 1e7})
            return words

        # сервис иногда случайно отвечает "No audio was received" — повторяем,
        # а после нескольких неудач пробуем темп ±1% (на слух неразличимо)
        rv = parse_rate(rate)
        variants = [rate] * 4 + [fmt_rate(rv + 1), fmt_rate(rv - 1)] * 3
        last = None
        for attempt, r in enumerate(variants):
            try:
                words = asyncio.run(run(r))
                if attempt >= 4:
                    log(f"    (фраза озвучена с темпом {r})")
                break
            except Exception as e:  # сеть / сбой сервиса
                last = e
                time.sleep(min(1.0 + attempt, 6.0))
        else:
            sys.exit(f"edge-tts не отвечает: {last}")
        os.replace(mp3 + ".part", mp3)
        with open(js, "w", encoding="utf-8") as f:
            json.dump(words, f, ensure_ascii=False)
    with open(js, encoding="utf-8") as f:
        words = json.load(f)
    return decode_audio(mp3), words


def align_words(tokens, bounds, clip_dur):
    """Сопоставляем слова текста событиям WordBoundary."""
    nt = [norm(t) for t in tokens]
    bn = [norm(b["text"]) for b in bounds]
    out, i = [], 0
    ok = True
    for tok in nt:
        if i >= len(bounds):
            ok = False
            break
        s, e, acc = bounds[i]["start"], bounds[i]["end"], bn[i]
        i += 1
        while len(acc) < len(tok) and i < len(bounds) and tok.startswith(acc + bn[i]):
            acc += bn[i]
            e = bounds[i]["end"]
            i += 1
        out.append((s, e))
    if ok and len(out) == len(tokens) and i == len(bounds):
        return out
    # запасной вариант: распределяем время пропорционально длине слов
    if bounds:
        t0, t1 = bounds[0]["start"], bounds[-1]["end"]
    else:
        t0, t1 = 0.05, clip_dur - 0.05
    lens = np.array([max(1, len(t)) for t in nt], dtype=float)
    edges = t0 + (t1 - t0) * np.concatenate([[0], np.cumsum(lens) / lens.sum()])
    return [(edges[k], edges[k + 1]) for k in range(len(tokens))]


def make_clip(text, rate, cache_dir):
    audio, bounds = tts(text, rate, cache_dir)
    tokens = tokenize(text)
    dur = len(audio) / SR
    times = align_words(tokens, bounds, dur)
    # обрезаем по реальной тишине, чтобы пауза между предложениями была ровно заданной
    hop = int(0.005 * SR)
    env = np.sqrt(np.convolve(audio.astype(np.float64) ** 2, np.ones(hop) / hop, mode="same"))
    loud = np.nonzero(env > db(-48) * max(1e-6, float(np.abs(audio).max())))[0]
    if loud.size:
        s0 = max(0.0, loud[0] / SR - 0.02)
        s1 = min(dur, loud[-1] / SR + 0.04)
    else:
        s0, s1 = max(0.0, times[0][0] - 0.05), min(dur, times[-1][1] + 0.12)
    a = audio[int(s0 * SR):int(s1 * SR)].copy()
    f = min(len(a) // 4, int(0.03 * SR))
    if f > 0:
        a[-f:] *= np.linspace(1, 0, f)
        a[:f // 3] *= np.linspace(0, 1, f // 3)
    L = (len(a) / SR)
    words = [(tok, min(max(0.0, st - s0), L), min(max(0.0, en - s0), L)) for tok, (st, en) in zip(tokens, times)]
    return {"text": text, "audio": a, "dur": len(a) / SR, "words": words}


def layout(title_clip, clips, pause, pause_last):
    t = 0.12
    plan = {"title_at": None}
    if title_clip is not None:
        plan["title_at"] = t
        t += title_clip["dur"] + pause
    t = max(t, C.TITLE_DURATION - 0.1)
    starts = []
    for i, c in enumerate(clips):
        starts.append(t)
        t += c["dur"]
        if i < len(clips) - 1:
            t += pause_last if i == len(clips) - 2 else pause
    plan["starts"] = starts
    plan["voice_end"] = t
    plan["outro_start"] = t + C.OUTRO_GAP
    plan["total"] = plan["outro_start"] + C.OUTRO_DURATION
    plan["pause"] = pause
    return plan


def parse_rate(r):
    return int(str(r).replace("%", "").replace("+", ""))


def fmt_rate(v):
    return f"{v:+d}%"


def build_voice(title, sentences, cache_dir):
    _patch_edge_tts_ssl()
    rate = parse_rate(C.RATE)
    plan = None
    for attempt in range(6):
        r = fmt_rate(rate)
        log(f"  озвучка: {C.VOICE}, rate {r}, pitch {C.PITCH} ({len(sentences)} предложений)")
        title_clip = make_clip(title.rstrip(".!?…") + ".", r, cache_dir) if C.VOICE_TITLE else None
        clips = [make_clip(s, r, cache_dir) for s in sentences]
        plan = layout(title_clip, clips, C.PAUSE_SENTENCE, C.PAUSE_BEFORE_LAST)
        tot = plan["total"]
        if C.TARGET_MIN_SEC <= tot <= C.TARGET_MAX_SEC:
            break
        # пробуем уложиться, подвинув обычные паузы (0.35…1.1 с)
        n_p = max(1, len(clips) - 2 + (1 if title_clip else 0))
        target = C.TARGET_MAX_SEC - 0.3 if tot > C.TARGET_MAX_SEC else C.TARGET_MIN_SEC + 0.3
        p = min(1.1, max(0.35, C.PAUSE_SENTENCE + (target - tot) / n_p))
        plan2 = layout(title_clip, clips, p, C.PAUSE_BEFORE_LAST)
        if C.TARGET_MIN_SEC <= plan2["total"] <= C.TARGET_MAX_SEC:
            log(f"  ! длина {tot:.1f} с вне {C.TARGET_MIN_SEC:.0f}–{C.TARGET_MAX_SEC:.0f} с: "
                f"пауза между предложениями {C.PAUSE_SENTENCE} → {p:.2f} с")
            plan = plan2
            break
        new_rate = rate + (5 if tot > C.TARGET_MAX_SEC else -5)
        log(f"  ! длина {tot:.1f} с вне диапазона: темп {fmt_rate(rate)} → {fmt_rate(new_rate)}")
        rate = new_rate
    plan["rate"] = fmt_rate(rate)
    plan["title_clip"] = title_clip
    plan["clips"] = clips
    return plan


def ffmpeg_af(x, af):
    """Прогоняет моно-сигнал float32 через фильтры ffmpeg (без потерь, через pipe)."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
         "-af", af, "-f", "f32le", "-ar", str(SR), "-ac", "1", "-"],
        input=np.asarray(x, np.float32).tobytes(), check=True, capture_output=True).stdout
    y = np.frombuffer(out, np.float32)[:len(x)].copy()
    return np.pad(y, (0, len(x) - len(y))) if len(y) < len(x) else y


SPEECH_HOP, SPEECH_WIN = 0.05, 0.4


def speech_frames(v):
    """Уровень голоса в окнах 0.4 с и маска окон, где реально звучит речь."""
    hop, win = int(SPEECH_HOP * SR), int(SPEECH_WIN * SR)
    nf = len(v) // hop + 1
    vdb = frame_rms_db(v, nf, hop, win)
    loud = vdb[vdb > -70]
    ref = np.percentile(loud, 90) if loud.size else -20
    return vdb, vdb > ref - 10, nf, hop, win


def speech_level_db(v):
    vdb, act, *_ = speech_frames(v)
    return float(10 * np.log10(np.mean(10 ** (vdb[act] / 10)))) if act.any() else -99.0


def process_voice(v, tmpdir=None):
    """Компрессия + лёгкая реверберация, нормировка громкости, лимитер."""
    af = "highpass=f=70,acompressor=threshold=-24dB:ratio=3.5:attack=6:release=150:makeup=1"
    if C.VOICE_REVERB:
        af += ",aecho=0.9:0.8:45|85|140:0.13|0.08|0.04"
    y = ffmpeg_af(v / (np.abs(v).max() + 1e-9) * 0.5, af)
    for _ in range(3):  # лимитер немного снижает уровень — догоняем за пару проходов
        y = y * db(C.VOICE_RMS_DB - speech_level_db(y))
        y = ffmpeg_af(y, "alimiter=limit=0.89:attack=4:release=60:level=disabled")
    return softclip(y, 0.95).astype(np.float32)


def softclip(x, th=0.85):
    y = np.array(x, dtype=np.float32)
    a = np.abs(y)
    m = a > th
    y[m] = np.sign(y[m]) * (th + (1 - th) * np.tanh((a[m] - th) / (1 - th)))
    return y


def write_wav(path, data):
    data = np.asarray(data)
    if data.ndim == 1:
        data = data[:, None]
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# =============================================================== МУЗЫКА / SFX (numpy)
def fft_filter(x, lo, hi, soft=0.15):
    n = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    m = np.ones_like(f)
    if lo > 0:
        m *= 1 / (1 + (lo / np.maximum(f, 1e-3)) ** 4)
    if hi < SR / 2:
        m *= 1 / (1 + (f / hi) ** 4)
    return np.fft.irfft(X * m, n)


def band_noise(n, lo, hi, rng):
    y = fft_filter(rng.standard_normal(n), lo, hi)
    return y / (rms(y) + 1e-12)


def fft_conv(a, k):
    n = len(a) + len(k) - 1
    nf = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(a, nf) * np.fft.rfft(k, nf), nf)[:n]


def add_at(buf, sig, t, gain=1.0, pan=0.0):
    """buf: (N,2). pan -1..1"""
    i = int(t * SR)
    if i >= len(buf):
        return
    if i < 0:
        sig = sig[-i:]
        i = 0
    sig = sig[:len(buf) - i]
    l = math.cos((pan + 1) * math.pi / 4)
    r = math.sin((pan + 1) * math.pi / 4)
    buf[i:i + len(sig), 0] += sig * gain * l * math.sqrt(2)
    buf[i:i + len(sig), 1] += sig * gain * r * math.sqrt(2)


def make_drone(n, story_t0, climax_t, rng):
    t = np.arange(n) / SR
    out = np.zeros((n, 2))
    f0 = 43.65  # F1
    for ch, det in ((0, 1.0), (1, 1.004)):
        s = (np.sin(2 * np.pi * f0 * det * t)
             + 0.8 * np.sin(2 * np.pi * f0 * 1.006 * det * t + 1.3)
             + 0.45 * np.sin(2 * np.pi * f0 * 1.5 * det * t + 0.4)
             + 0.25 * np.sin(2 * np.pi * f0 * 2.003 * det * t)
             + 0.12 * np.sin(2 * np.pi * f0 * 2.12 * det * t + 2.0))  # диссонанс
        s *= 0.75 + 0.25 * np.sin(2 * np.pi * 0.063 * t + ch)
        rumble = band_noise(n, 25, 110, rng) * 0.5
        air = band_noise(n, 300, 900, rng) * 0.06 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.031 * t + 2 * ch))
        out[:, ch] = s / rms(s) + rumble + air
    # нарастание к кульминации
    p = np.clip((t - story_t0) / max(1.0, climax_t - story_t0), 0, 1)
    out *= (0.85 + 0.45 * p ** 2)[:, None]
    fade_in = np.clip(t / 1.2, 0, 1)
    out *= fade_in[:, None]
    seg = out[int(story_t0 * SR):int(climax_t * SR)]
    return out * (db(C.DRONE_DB) / rms(seg))


def make_creak(rng):
    dur = rng.uniform(0.6, 1.4)
    n = int(dur * SR)
    sig = np.zeros(n)
    pos, base = 0, rng.uniform(0.007, 0.02)
    ph = rng.uniform(0, 6.28)
    while pos < n:
        x = pos / n
        per = base * (1 + 0.6 * math.sin(2 * math.pi * 0.9 * x + ph) + rng.uniform(-0.2, 0.2))
        sig[pos] = rng.uniform(0.5, 1.0)
        pos += max(1, int(per * SR))
    f1 = rng.uniform(320, 850)
    kt = np.arange(int(0.05 * SR)) / SR
    kern = np.exp(-kt / 0.007) * (np.sin(2 * np.pi * f1 * kt) + 0.5 * np.sin(2 * np.pi * 2.71 * f1 * kt)
                                  + 0.25 * np.sin(2 * np.pi * 4.13 * f1 * kt))
    y = fft_conv(sig, kern)[:n]
    x = np.linspace(0, 1, n)
    y *= np.sin(np.pi * x) ** 0.7
    return y / rms(y)


def make_rustle(rng):
    n = int(rng.uniform(0.7, 1.6) * SR)
    y = band_noise(n, 1200, 6500, rng)
    env = np.abs(band_noise(n, 0.5, 9, rng))
    y *= env * np.sin(np.pi * np.linspace(0, 1, n)) ** 1.5
    return y / rms(y)


def make_thump(f=52.0, decay=0.09, rng=None):
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    freq = f * (1 + 1.3 * np.exp(-t / 0.014))
    ph = 2 * np.pi * np.cumsum(freq) / SR
    env = (1 - np.exp(-t / 0.002)) * np.exp(-t / decay)
    s = np.sin(ph) * env
    if rng is not None:
        click = fft_filter(rng.standard_normal(n), 60, 600) * np.exp(-t / 0.006)
        s += 0.3 * click / (np.abs(click).max() + 1e-9)
    return s


def make_stinger(rng):
    n = int(3.2 * SR)
    t = np.arange(n) / SR
    # низкий "бум" со скольжением вниз
    f = 35 + 120 * np.exp(-t / 0.12)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.7) * (1 - np.exp(-t / 0.002))
    # шумовой удар
    hit = band_noise(n, 80, 5000, rng) * np.exp(-t / 0.07)
    # металлический визг-кластер
    scr = np.zeros(n)
    for fr in (1180, 1253, 1790, 2537, 3310):
        vib = 1 + 0.006 * np.sin(2 * np.pi * rng.uniform(5, 8) * t)
        scr += np.sin(2 * np.pi * np.cumsum(fr * vib) / SR + rng.uniform(0, 6))
    scr *= (1 - np.exp(-t / 0.01)) * np.exp(-t / 0.8) * 0.12
    y = 1.0 * boom / np.abs(boom).max() + 0.45 * hit / np.abs(hit).max() + scr
    return y / np.abs(y).max()


def make_riser(dur, rng):
    n = int(dur * SR)
    x = np.linspace(0, 1, n)
    y = band_noise(n, 400, 8000, rng) * x ** 3
    tone = np.sin(2 * np.pi * np.cumsum(200 + 900 * x ** 2) / SR) * x ** 4 * 0.3
    y = y / (np.abs(y).max() + 1e-9) + tone
    return y / (np.abs(y).max() + 1e-9)


def frame_rms_db(x, n_frames, hop, win):
    """x: (N,) или (N,ch) — RMS в окнах win вокруг центров k*hop, в dB."""
    e = x.astype(np.float64) ** 2
    if e.ndim == 2:
        e = e.mean(axis=1)
    c = np.concatenate([[0.0], np.cumsum(e)])
    centers = np.arange(n_frames) * hop
    a = np.clip(centers - win // 2, 0, len(e))
    b = np.clip(centers + win // 2, 0, len(e))
    v = (c[b] - c[a]) / np.maximum(b - a, 1)
    return 10 * np.log10(np.maximum(v, 1e-14))


def duck_music(voice, music):
    """Гарантирует: в каждом окне речи музыка тише голоса минимум на VOICE_OVER_MUSIC_DB."""
    vdb, active, nf, hop, win = speech_frames(voice)
    mdb = frame_rms_db(music, nf, hop, win)
    req = np.where(active, np.minimum(0.0, vdb - C.VOICE_OVER_MUSIC_DB - 0.5 - mdb), 0.0)
    R = win // hop
    pad = np.pad(req, R, mode="edge")
    mn = np.lib.stride_tricks.sliding_window_view(pad, 2 * R + 1).min(axis=1)
    r = R // 2
    k = np.ones(2 * r + 1) / (2 * r + 1)
    sm = np.convolve(np.pad(mn, r, mode="edge"), k, mode="valid")
    g = np.interp(np.arange(len(voice)), np.arange(nf) * hop, sm)
    music = music * (10 ** (g / 20))[:, None]
    mdb2 = frame_rms_db(music, nf, hop, win)
    diff = (vdb - mdb2)[active]
    return music, (float(diff.min()) if diff.size else 99.0), float(sm.min())


def build_audio(plan, rng, tmpdir):
    total = plan["total"]
    n = int(math.ceil(total * SR))
    # ---- голос
    v = np.zeros(n, dtype=np.float32)
    if plan["title_clip"] is not None:
        a = plan["title_clip"]["audio"]
        i = int(plan["title_at"] * SR)
        v[i:i + len(a)] += a[:n - i]
    for c, st in zip(plan["clips"], plan["starts"]):
        i = int(st * SR)
        v[i:i + len(c["audio"])] += c["audio"][:n - i]
    v = process_voice(v, tmpdir)

    story_t0 = plan["starts"][0]
    last_t = plan["starts"][-1]
    music_end = total - C.TAIL_SILENCE
    # ---- дрон
    m = make_drone(n, story_t0, last_t, rng)
    # ---- скрипы и шорохи
    t = story_t0 + rng.uniform(1.5, 3.5)
    kind = rng.random() < 0.5
    while t < last_t - 2.0:
        sfx = make_creak(rng) if kind else make_rustle(rng)
        add_at(m, sfx, t, db(C.SFX_DB + rng.uniform(-3, 1)), pan=rng.uniform(-0.8, 0.8))
        kind = not kind
        t += rng.uniform(4.5, 9.0)
    # ---- сердцебиение, ускоряется к кульминации
    hb0 = story_t0 + 0.3 * (last_t - story_t0)
    t = hb0
    lub, dub = make_thump(54, 0.09, rng), make_thump(47, 0.07, rng)
    bpm0, bpm1 = C.HEARTBEAT_BPM
    peak = np.abs(lub).max()
    while t < last_t - 0.25:
        p = (t - hb0) / max(1e-3, last_t - hb0)
        bpm = bpm0 + (bpm1 - bpm0) * p ** 1.5
        g = db(C.HEARTBEAT_DB) * 3.0 / peak * (0.45 + 0.55 * p)
        add_at(m, lub, t, g)
        add_at(m, dub, t + min(0.3, 0.35 * 60 / bpm), g * 0.7)
        t += 60.0 / bpm
    # ---- нарастающий шум в паузе и удар на последней фразе
    rdur = min(1.0, C.PAUSE_BEFORE_LAST)
    add_at(m, make_riser(rdur, rng), last_t - rdur - 0.02, db(C.STINGER_DB - 10))
    add_at(m, make_stinger(rng), last_t - 0.03, db(C.STINGER_DB))
    # ---- финальное затухание и тишина
    tt = np.arange(n) / SR
    fade = np.clip((music_end - tt) / 0.7, 0, 1)
    m *= fade[:, None]

    m, min_diff, max_duck = duck_music(v, m)
    mix = m + v[:, None]
    mix[int(music_end * SR):] = 0.0
    mix = softclip(mix, 0.9)
    path = os.path.join(tmpdir, "mix.wav")
    write_wav(path, mix)
    stats = {
        "voice_rms_db": speech_level_db(v),
        "music_rms_db": to_db(rms(m[int(story_t0 * SR):int(last_t * SR)])),
        "min_diff_db": min_diff,
        "max_duck_db": max_duck,
    }
    return path, stats


# =============================================================== КАДРЫ
def load_font(size, _cache={}):
    if size in _cache:
        return _cache[size]
    for p in C.FONT_CANDIDATES:
        pp = p if os.path.isabs(p) else os.path.join(HERE, p)
        if os.path.exists(pp):
            f = ImageFont.truetype(pp, size)
            _cache[size] = f
            return f
    sys.exit("Не найден жирный шрифт: положите Inter-ExtraBold.otf в папку fonts/ "
             "или установите DejaVu Sans (fonts-dejavu-core).")


def periodic_noise(n, cutoff, rng, beta=3.0):
    fx = np.fft.fftfreq(n)[:, None]
    fy = np.fft.rfftfreq(n)[None, :]
    f = np.sqrt(fx ** 2 + fy ** 2)
    f[0, 0] = 1.0
    amp = f ** (-beta / 2) * np.exp(-(f / cutoff) ** 2)
    amp[0, 0] = 0
    spec = amp * (rng.standard_normal(f.shape) + 1j * rng.standard_normal(f.shape))
    img = np.fft.irfft2(spec, s=(n, n))
    img = (img - img.min()) / (img.max() - img.min())
    return img.astype(np.float32)


def smoothstep(a, b, x):
    x = np.clip((x - a) / (b - a), 0, 1)
    return x * x * (3 - 2 * x)


class GeneratedBG:
    """Тёмный сине-чёрный градиент + плывущий туман + редкие мерцания."""
    LW, LH = W // 2, H // 2

    def __init__(self, total, rng):
        LW, LH = self.LW, self.LH
        y = np.linspace(0, 1, LH)[:, None, None]
        top = np.array(C.BG_TOP_COLOR, np.float32)
        bot = np.array(C.BG_BOTTOM_COLOR, np.float32)
        self.base = (top * (1 - y) ** 1.3 + bot * (1 - (1 - y) ** 1.3)) * np.ones((1, LW, 1), np.float32)
        yy, xx = np.mgrid[0:LH, 0:LW].astype(np.float32)
        d = np.sqrt(((xx - LW / 2) / LW) ** 2 + ((yy - LH * 0.38) / LH) ** 2 * 0.7)
        self.base += (np.clip(1 - d * 2.2, 0, 1) ** 2 * 14)[..., None] * np.array([0.5, 0.7, 1.0], np.float32)
        dv = np.sqrt(((xx - LW / 2) / (LW / 2)) ** 2 + ((yy - LH / 2) / (LH / 2)) ** 2)
        self.vig = (1 - 0.55 * smoothstep(0.55, 1.45, dv))[..., None].astype(np.float32)
        self.fog_prof = (0.55 + 0.6 * (yy / LH) ** 1.2)[..., None].astype(np.float32)
        self.texA = periodic_noise(1024, 0.012, rng)
        self.texB = periodic_noise(1024, 0.006, rng)
        self.texC = periodic_noise(1024, 0.04, rng, beta=2.2)
        self.velA = (rng.uniform(9, 15), rng.uniform(-4, -1))
        self.velB = (-rng.uniform(5, 9), rng.uniform(1, 3))
        self.offA = rng.uniform(0, 1024, 2)
        self.offB = rng.uniform(0, 1024, 2)
        self.velC = (rng.uniform(14, 22), rng.uniform(-6, -2))
        self.offC = rng.uniform(0, 1024, 2)
        self.fog_col = np.array(C.FOG_COLOR, np.float32)
        self.fl_col = np.array(C.FLICKER_COLOR, np.float32) / 255.0
        # мерцания
        self.flickers = []
        t = rng.uniform(4, 8)
        while t < total - 1:
            pulses = [(t + k * rng.uniform(0.07, 0.14), rng.uniform(0.25, 0.7)) for k in range(rng.integers(1, 4))]
            self.flickers += pulses
            t += rng.uniform(6, 12)
        self.rng = np.random.default_rng(int(rng.integers(1 << 30)))
        self.ar_y = np.arange(LH)
        self.ar_x = np.arange(LW)

    def _sample(self, tex, ox, oy):
        N = tex.shape[0]
        ix, iy = int(math.floor(ox)), int(math.floor(oy))
        fx, fy = ox - ix, oy - iy
        r0 = (self.ar_y + iy) % N
        r1 = (r0 + 1) % N
        c0 = (self.ar_x + ix) % N
        c1 = (c0 + 1) % N
        a = tex[r0][:, c0]
        b = tex[r0][:, c1]
        c = tex[r1][:, c0]
        d = tex[r1][:, c1]
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy

    def flicker(self, t):
        v = 0.0
        for ft, amp in self.flickers:
            dt = t - ft
            if 0 <= dt < 0.25:
                v = max(v, amp * math.exp(-dt / 0.05))
        return v

    def frame(self, t):
        a = self._sample(self.texA, self.offA[0] + t * self.velA[0], self.offA[1] + t * self.velA[1])
        b = self._sample(self.texB, self.offB[0] + t * self.velB[0], self.offB[1] + t * self.velB[1])
        c = self._sample(self.texC, self.offC[0] + t * self.velC[0], self.offC[1] + t * self.velC[1])
        dens = 0.5 * a + 0.5 * b + 0.35 * (c - 0.5)
        fog = smoothstep(0.30, 0.85, dens)[..., None] * self.fog_prof
        fl = self.flicker(t)
        img = self.base * (1 + 2.5 * fl) + fog * self.fog_col * C.FOG_STRENGTH * (1 + 1.8 * fl)
        if fl > 0:
            img += fl * 60 * self.fl_col
        img *= self.vig
        img += self.rng.uniform(-1.5, 1.5, (self.LH, self.LW, 1)).astype(np.float32)  # дизеринг/зерно
        small = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
        return small.resize((W, H), Image.BICUBIC)


class VideoBG:
    """Случайное видео из bg/: зацикливание, центральная вертикаль 9:16, -35% яркости, виньетка."""

    def __init__(self, path, total, fps, rng):
        self.path = path
        try:
            dur = float(subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                capture_output=True, text=True, check=True).stdout.strip())
        except Exception:
            dur = 0.0
        start = rng.uniform(0, dur - total) if dur > total + 1 else 0.0
        b = C.BG_VIDEO_BRIGHTNESS
        vf = (f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={W}:{H}:flags=lanczos,setsar=1,fps={fps},"
              f"lutrgb=r='val*{b}':g='val*{b}':b='val*{b}',vignette=angle=PI/5,format=rgb24")
        cmd = ["ffmpeg", "-v", "error", "-stream_loop", "-1", "-ss", f"{start:.3f}", "-i", path,
               "-t", f"{total + 1:.3f}", "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.last = Image.new("RGB", (W, H))
        self.size = W * H * 3

    def frame(self, t):
        buf = self.proc.stdout.read(self.size)
        if buf and len(buf) == self.size:
            self.last = Image.frombytes("RGB", (W, H), buf)
        return self.last.copy()

    def close(self):
        try:
            self.proc.kill()
        except Exception:
            pass


def find_bg_videos():
    d = os.path.join(HERE, C.BG_DIR) if not os.path.isabs(C.BG_DIR) else C.BG_DIR
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".mp4", ".mov")))


def make_chunks(plan):
    chunks = []
    n = len(plan["clips"])
    for si, (c, st) in enumerate(zip(plan["clips"], plan["starts"])):
        words = [(w if not C.SUB_UPPERCASE else w.upper(), st + a, st + b) for w, a, b in c["words"]]
        k = math.ceil(len(words) / C.SUB_MAX_WORDS)
        base, rem = divmod(len(words), k)
        i = 0
        for j in range(k):
            sz = base + (1 if j < rem else 0)
            chunks.append({"words": words[i:i + sz], "final": si == n - 1})
            i += sz
    for j, ch in enumerate(chunks):
        ch["start"] = ch["words"][0][1]
        end = ch["words"][-1][2] + 0.8
        if j + 1 < len(chunks):
            end = min(end, chunks[j + 1]["words"][0][1])
        ch["end"] = min(end, plan["outro_start"])
    return chunks


def ease_out_back(x):
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def text_layer(lines, size, color, stroke, accent=None, max_w=None):
    """RGBA-слой с центрированным многострочным текстом."""
    font = load_font(size)
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    boxes = [tmp.textbbox((0, 0), l, font=font, stroke_width=stroke) for l in lines]
    lh = int(size * 1.12)
    w = max(b[2] - b[0] for b in boxes) + 40
    h = lh * len(lines) + 40 + (30 if accent else 0)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        d.text((w / 2 + 5, 20 + lh * (i + 0.5) + 6), l, font=font, fill=(0, 0, 0, 150), anchor="mm",
               stroke_width=stroke, stroke_fill=(0, 0, 0, 150))
        d.text((w / 2, 20 + lh * (i + 0.5)), l, font=font, fill=color + (255,), anchor="mm",
               stroke_width=stroke, stroke_fill=C.SUB_STROKE_COLOR + (255,))
    if accent:
        y = 20 + lh * len(lines) + 12
        aw = w * 0.22
        d.rounded_rectangle([w / 2 - aw, y, w / 2 + aw, y + 12], radius=6, fill=accent + (255,),
                            outline=(0, 0, 0, 255), width=3)
    return img


def wrap(words, font, stroke, max_w):
    lines, cur = [], []
    sp = font.getlength(" ") * 1.0
    for w in words:
        test = cur + [w]
        width = sum(font.getbbox(x, stroke_width=stroke)[2] - font.getbbox(x, stroke_width=stroke)[0]
                    for x in test) + sp * (len(test) - 1)
        if cur and width > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


class Renderer:
    def __init__(self, title, plan, fps, rng, bg_files):
        self.plan, self.fps, self.total = plan, fps, plan["total"]
        self.chunks = make_chunks(plan)
        if bg_files:
            f = bg_files[int(rng.integers(len(bg_files)))]
            log(f"  фон: видео {os.path.relpath(f, HERE)}")
            self.bg = VideoBG(f, self.total, fps, rng)
        else:
            log("  фон: генерируемый (градиент + туман + мерцания)")
            self.bg = GeneratedBG(self.total, rng)
        # заголовок
        tf = load_font(C.TITLE_FONT_SIZE)
        tw = title.upper().split()
        tl = [" ".join(l) for l in wrap(tw, tf, 8, W - 140)]
        self.title_img = text_layer(tl, C.TITLE_FONT_SIZE, C.TITLE_COLOR, 9, accent=C.TITLE_ACCENT)
        # плашка
        self.outro_img = self._make_outro()
        # красное свечение по краям
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        dd = np.minimum(np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy))
        self.glow = (np.clip(1 - dd / (W * 0.22), 0, 1) ** 2.2)[..., None].astype(np.float32)
        self.glow_col = np.array(C.GLOW_COLOR, np.float32)
        self.shake_ph = rng.uniform(0, 6.28, 4)
        self.sub_font_base = load_font(C.SUB_FONT_SIZE)

    def _make_outro(self):
        f1, f2 = load_font(104), load_font(84)
        tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        b1 = tmp.textbbox((0, 0), C.OUTRO_TEXT_1, font=f1)
        b2 = tmp.textbbox((0, 0), C.OUTRO_TEXT_2, font=f2)
        w = max(b1[2] - b1[0], b2[2] - b2[0]) + 140
        h = 330
        img = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([18, 22, w + 18, h + 18], radius=44, fill=(0, 0, 0, 120))
        d.rounded_rectangle([10, 10, w + 10, h + 10], radius=44, fill=(14, 12, 16, 236),
                            outline=C.SUB_HIGHLIGHT + (255,), width=7)
        d.text((w / 2 + 10, 10 + h * 0.32), C.OUTRO_TEXT_1, font=f1, fill=C.SUB_HIGHLIGHT + (255,),
               anchor="mm", stroke_width=4, stroke_fill=(0, 0, 0, 255))
        d.text((w / 2 + 10, 10 + h * 0.70), C.OUTRO_TEXT_2, font=f2, fill=(255, 255, 255, 255),
               anchor="mm", stroke_width=4, stroke_fill=(0, 0, 0, 255))
        return img

    @staticmethod
    def _paste(frame, layer, cx, cy, scale=1.0, alpha=1.0):
        if scale != 1.0:
            layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))),
                                 Image.BICUBIC)
        if alpha < 1.0:
            a = layer.getchannel("A").point(lambda v: int(v * alpha))
            layer = layer.copy()
            layer.putalpha(a)
        frame.paste(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)), layer)

    def _subs(self, frame, t):
        ch = None
        for c in self.chunks:
            if c["start"] <= t < c["end"]:
                ch = c
                break
        if ch is None:
            return
        d = ImageDraw.Draw(frame)
        words = ch["words"]
        cur = max([i for i, w in enumerate(words) if w[1] <= t], default=0)
        sw = C.SUB_STROKE
        base = C.SUB_FONT_SIZE
        pop = min(1.0, (t - ch["start"]) / 0.09)
        base_scale = 0.88 + 0.12 * pop
        bf = load_font(max(10, int(round(base * base_scale))))
        lines = wrap([w[0] for w in words], bf, sw, W - 110)
        lh = bf.size * 1.18
        y0 = H * C.SUB_Y - lh * (len(lines) - 1) / 2
        idx = 0
        items = []
        sp = bf.getlength(" ") * 1.0
        for li, line in enumerate(lines):
            widths = [bf.getbbox(w, stroke_width=sw)[2] - bf.getbbox(w, stroke_width=sw)[0] for w in line]
            tot = sum(widths) + sp * (len(line) - 1)
            x = W / 2 - tot / 2
            for w, wd in zip(line, widths):
                items.append((idx, w, x + wd / 2, y0 + li * lh))
                x += wd + sp
                idx += 1
        items.sort(key=lambda it: it[0] == cur)  # текущее слово рисуем последним
        for i, w, cx, cy in items:
            red = ch["final"] or i == cur
            color = C.SUB_HIGHLIGHT if red else C.SUB_COLOR
            font = bf
            if i == cur:
                p = (t - words[i][1]) / 0.32
                s = 1 + C.SUB_PULSE * math.sin(math.pi * min(max(p, 0), 1)) if p < 1 else 1.0
                font = load_font(max(10, int(round(bf.size * s))))
            d.text((cx + 4, cy + 6), w, font=font, fill=(0, 0, 0), anchor="mm",
                   stroke_width=sw, stroke_fill=(0, 0, 0))
            d.text((cx, cy), w, font=font, fill=color, anchor="mm",
                   stroke_width=sw, stroke_fill=C.SUB_STROKE_COLOR)

    def frame(self, i):
        t = i / self.fps
        img = self.bg.frame(t)
        end_fx = self.total - C.FINAL_SHAKE_SEC
        if t >= end_fx:
            k = min(1.0, (t - end_fx) / 0.6)
            a = k * (0.75 + 0.25 * math.sin(2 * math.pi * 2.2 * (t - end_fx)))
            arr = np.asarray(img, dtype=np.float32)
            g = self.glow * (0.85 * a)
            arr = arr * (1 - g * 0.7) + g * self.glow_col
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        # заголовок
        if t < C.TITLE_DURATION:
            fin = min(1.0, t / 0.15)
            fout = min(1.0, max(0.0, (C.TITLE_DURATION - t) / 0.35))
            self._paste(img, self.title_img, W / 2, H * 0.45, scale=1.0 + 0.05 * t / C.TITLE_DURATION,
                        alpha=min(fin, fout))
        # субтитры
        if t < self.plan["outro_start"]:
            self._subs(img, t)
        # плашка «Часть 2?»
        if t >= self.plan["outro_start"]:
            x = min(1.0, (t - self.plan["outro_start"]) / 0.3)
            self._paste(img, self.outro_img, W / 2, H * 0.5, scale=0.6 + 0.4 * ease_out_back(x),
                        alpha=min(1.0, x * 1.6))
        # дрожание кадра
        if t >= end_fx:
            k = min(1.0, (t - end_fx) / 0.8)
            ph = self.shake_ph
            dx = C.SHAKE_PX * k * (0.6 * math.sin(t * 47 + ph[0]) + 0.4 * math.sin(t * 83 + ph[1]))
            dy = C.SHAKE_PX * k * (0.6 * math.sin(t * 53 + ph[2]) + 0.4 * math.sin(t * 71 + ph[3]))
            s = 1.0 + 0.03 * k
            img = img.transform((W, H), Image.AFFINE,
                                (1 / s, 0, (W - W / s) / 2 + dx, 0, 1 / s, (H - H / s) / 2 + dy),
                                resample=Image.BILINEAR)
        return img

    def close(self):
        if hasattr(self.bg, "close"):
            self.bg.close()


# =============================================================== СБОРКА
def main():
    ap = argparse.ArgumentParser(description="Вертикальное видео «страшная история».")
    ap.add_argument("story", nargs="?", default="story.txt")
    ap.add_argument("-o", "--output", default="output.mp4")
    ap.add_argument("--fps", type=int, default=C.DEFAULT_FPS, choices=[24, 25, 30, 50, 60])
    ap.add_argument("--preview", type=float, default=0, help="отрендерить только первые N секунд")
    ap.add_argument("--seed", type=int, default=None, help="зерно случайности (фон, звуки)")
    args = ap.parse_args()

    need_tool("ffmpeg")
    need_tool("ffprobe")
    seed = args.seed if args.seed is not None else random.randrange(1 << 30)
    rng = np.random.default_rng(seed)
    t_start = time.time()

    title, sentences = read_story(args.story)
    log(f"История: «{title}», {len(sentences)} предложений, seed={seed}")
    cache = os.path.join(HERE, ".cache", "tts")
    os.makedirs(cache, exist_ok=True)

    log("[1/4] Озвучка (edge-tts) и тайминги слов…")
    plan = build_voice(title, sentences, cache)
    total = plan["total"]
    log(f"  длина ролика: {total:.2f} с (голос до {plan['voice_end']:.2f} с)")

    tmpdir = tempfile.mkdtemp(prefix="horror_")
    try:
        log("[2/4] Звук: дрон, скрипы, сердцебиение, стингер, сведение…")
        wav, st = build_audio(plan, rng, tmpdir)
        log(f"  голос {st['voice_rms_db']:.1f} dB RMS, музыка {st['music_rms_db']:.1f} dB RMS; "
            f"мин. перевес голоса в окнах речи: {st['min_diff_db']:.1f} dB "
            f"(авто-приглушение музыки до {st['max_duck_db']:.1f} dB)")

        dur = min(total, args.preview) if args.preview > 0 else total
        nframes = int(round(dur * args.fps))
        bg_files = find_bg_videos()
        log(f"[3/4] Кадры: {nframes} шт., {W}x{H} @ {args.fps} fps…")
        r = Renderer(title, plan, args.fps, rng, bg_files)
        out = os.path.abspath(args.output)
        cmd = ["ffmpeg", "-v", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(args.fps), "-i", "-",
               "-i", wav, "-t", f"{dur:.3f}",
               "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "medium", "-crf", str(C.CRF), "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-g", str(args.fps * 2),
               "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
               "-movflags", "+faststart", out]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        t0 = time.time()
        step = max(1, nframes // 20)
        try:
            for i in range(nframes):
                proc.stdin.write(r.frame(i).tobytes())
                if i % step == 0 and i:
                    el = time.time() - t0
                    log(f"  {100 * i / nframes:5.1f}%  ({el:.0f} с, осталось ~{el / i * (nframes - i):.0f} с)")
        finally:
            r.close()
            proc.stdin.close()
            rc = proc.wait()
        if rc != 0:
            sys.exit("ffmpeg завершился с ошибкой")
        log("[4/4] Готово.")
        info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,r_frame_rate",
                               "-of", "compact=p=0:nk=1", out], capture_output=True, text=True).stdout.strip()
        log(f"  {out}\n  {info.replace(chr(10), ' | ')}")
        log(f"  время работы: {time.time() - t_start:.0f} с")
        if not bg_files:
            log(f"\nПодсказка: положите свои вертикальные/горизонтальные видео (.mp4/.mov) в папку "
                f"{C.BG_DIR}/ — генератор возьмёт случайное и использует как фон.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
