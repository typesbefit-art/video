#!/usr/bin/env python3
"""
Генератор вертикального хоррор-ролика «страшная история с озвучкой и субтитрами».

    python generate.py story.txt                    -> output.mp4 (1080x1920, 30 fps)
    python generate.py story.txt --fps 60           -> 60 fps
    python generate.py story.txt --preview 15       -> только первые 15 секунд (preview.mp4)

История — в story.txt (первая строка — заголовок). Голос, паузы, цвета, громкости
и привязка эффектов к фразам — в config.json. Код при смене истории не трогаем.
Свои фоновые видео (.mp4/.mov) кладите в папку bg/.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
SR = 48000


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ════════════════════════════════════════════════════════════════════════════
#  Конфиг
# ════════════════════════════════════════════════════════════════════════════

def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def first_existing(paths, base: Path = ROOT):
    for p in paths:
        pp = Path(p)
        if not pp.is_absolute():
            pp = base / pp
        if pp.exists():
            return str(pp)
    return None


# ════════════════════════════════════════════════════════════════════════════
#  Текст: разбор истории, нормализация, числа
# ════════════════════════════════════════════════════════════════════════════

PAUSE_MARK = re.compile(r"\[(?:пауза|pause)\s*([\d.,]+)\s*(?:с|s|сек)?\]", re.I)


def norm(word: str) -> str:
    w = word.lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]+", "", w)


def norm_phrase(phrase: str) -> list[str]:
    return [n for n in (norm(x) for x in phrase.split()) if n]


def parse_story(path: Path):
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    if not lines:
        sys.exit("story.txt пустой")
    title = lines[0]
    body = " ".join(ln for ln in lines[1:] if ln)
    body = re.sub(r"\s+", " ", body).strip()
    # Разбиваем на предложения: после .!?… (и возможной закрывающей кавычки)
    sentences = []
    pattern = re.compile(r"[.!?…]+[»\"”)]*(?=\s|$)")
    pos = 0
    for m in pattern.finditer(body):
        s = body[pos:m.end()].strip()
        if s:
            sentences.append(s)
        pos = m.end()
    tail = body[pos:].strip()
    if tail:
        sentences.append(tail)
    # Вытаскиваем маркеры пауз вида [пауза 1.2]
    result = []
    for s in sentences:
        pause = None
        m = PAUSE_MARK.search(s)
        if m:
            pause = float(m.group(1).replace(",", "."))
            s = PAUSE_MARK.sub("", s).strip()
        if s:
            result.append({"text": s, "pause": pause})
    return title, result


# Русские числительные (именительный/родительный и др. частые формы)
_NUM = {}
for v, forms in {
    1: "один одна одно одного одной одному одним одну",
    2: "два две двух двум двумя", 3: "три трех трем тремя",
    4: "четыре четырех четырем четырьмя", 5: "пять пяти пятью",
    6: "шесть шести", 7: "семь семи", 8: "восемь восьми", 9: "девять девяти",
}.items():
    for f in forms.split():
        _NUM[f] = (v, 0)
for v, stem in {10: "десят", 11: "одиннадцат", 12: "двенадцат", 13: "тринадцат",
                14: "четырнадцат", 15: "пятнадцат", 16: "шестнадцат",
                17: "семнадцат", 18: "восемнадцат", 19: "девятнадцат"}.items():
    for end in ("ь", "и", "ью"):
        _NUM[stem + end] = (v, 1)
for v, forms in {20: "двадцать двадцати", 30: "тридцать тридцати", 40: "сорок сорока",
                 50: "пятьдесят пятидесяти", 60: "шестьдесят шестидесяти",
                 70: "семьдесят семидесяти", 80: "восемьдесят восьмидесяти",
                 90: "девяносто девяноста"}.items():
    for f in forms.split():
        _NUM[f] = (v, 2)
for v, forms in {100: "сто ста", 200: "двести двухсот", 300: "триста трехсот",
                 400: "четыреста четырехсот", 500: "пятьсот пятисот",
                 600: "шестьсот шестисот", 700: "семьсот семисот",
                 800: "восемьсот восьмисот", 900: "девятьсот девятисот"}.items():
    for f in forms.split():
        _NUM[f] = (v, 3)


def num_word(n: str):
    """-> (value, class) или None. class: 0 единицы, 1 десять-девятнадцать, 2 десятки, 3 сотни."""
    if n.isdigit():
        return (int(n), 9)
    return _NUM.get(n)


def number_groups(words):
    """Склеивает подряд идущие числительные в числа: «двухсот четырнадцати» -> 214,
    но «три, четыре, пять» остаются тремя отдельными числами."""
    groups, i = [], 0
    while i < len(words):
        nw = num_word(words[i]["norm"])
        if not nw:
            i += 1
            continue
        val, cls = nw
        j = i + 1
        last_cls = cls
        while j < len(words) and words[j]["sent"] == words[i]["sent"]:
            nx = num_word(words[j]["norm"])
            if not nx or nx[1] >= last_cls or last_cls in (0, 1, 9) or nx[1] == 9:
                break
            val += nx[0]
            last_cls = nx[1]
            j += 1
        groups.append({"i0": i, "i1": j - 1, "value": val})
        i = j
    return groups


def find_phrase(words, phrase, start_at=0):
    toks = norm_phrase(phrase or "")
    if not toks:
        return None
    seq = [w["norm"] for w in words]
    for i in range(start_at, len(seq) - len(toks) + 1):
        if seq[i:i + len(toks)] == toks:
            return (i, i + len(toks) - 1)
    return None


# ════════════════════════════════════════════════════════════════════════════
#  Озвучка: edge-tts + WordBoundary
# ════════════════════════════════════════════════════════════════════════════

def _patch_edge_tts_ssl():
    """Если в системе задан свой CA (корпоративный прокси и т.п.) — доверяем ему."""
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        try:
            import edge_tts.communicate as ec
            ctx = ssl.create_default_context(cafile=ca)
            ec._SSL_CTX = ctx
        except Exception:
            pass


async def _tts_request(text, voice, rate, pitch):
    import edge_tts
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
    kwargs = dict(rate=rate, pitch=pitch, proxy=proxy)
    try:
        comm = edge_tts.Communicate(text, voice, boundary="WordBoundary", **kwargs)
    except TypeError:  # старые версии edge-tts: WordBoundary по умолчанию
        comm = edge_tts.Communicate(text, voice, **kwargs)
    audio = bytearray()
    words = []
    async for ch in comm.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            words.append({"text": ch["text"], "offset": ch["offset"] / 1e7,
                          "duration": ch["duration"] / 1e7})
    if not audio:
        raise RuntimeError("edge-tts не вернул аудио")
    return bytes(audio), words


def tts_cached(text, voice, rate, pitch, cache_dir: Path):
    key = hashlib.sha1(json.dumps([text, voice, rate, pitch], ensure_ascii=False)
                       .encode("utf-8")).hexdigest()[:20]
    mp3, js = cache_dir / f"{key}.mp3", cache_dir / f"{key}.json"
    if mp3.exists() and js.exists():
        return mp3, json.loads(js.read_text(encoding="utf-8"))
    last = None
    r0 = int(rate.rstrip("%"))
    for attempt in range(12):
        # сервис иногда стабильно «не любит» конкретную пару текст+темп — слегка сдвигаем темп
        r = r0 if attempt < 5 else r0 + (1, -1, 2, -2, 1, -1, 2)[attempt - 5]
        try:
            audio, words = asyncio.run(_tts_request(text, voice, f"{r:+d}%", pitch))
            if not words:
                raise RuntimeError("нет WordBoundary")
            mp3.write_bytes(audio)
            js.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
            return mp3, words
        except Exception as e:  # сервис иногда отвечает пусто — повторяем
            last = e
            time.sleep(min(6.0, 0.6 * (1.5 ** attempt)) + random.random() * 0.5)
    sys.exit(f"edge-tts не отвечает на фразу «{text}» ({last}). Проверьте интернет и повторите запуск.")


def decode_audio(path: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "1", "-ar", str(SR), "pipe:1"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def align_display(sentence: str, wb_words):
    """Сопоставляет слова из WordBoundary с исходным текстом, чтобы забрать пунктуацию."""
    out, pos, low = [], 0, sentence.lower()
    for w in wb_words:
        t = w["text"]
        k = low.find(t.lower(), pos)
        if k < 0:
            out.append(t)
            continue
        a, b = k, k + len(t)
        while a > 0 and sentence[a - 1] in "«\"„(":
            a -= 1
        while b < len(sentence) and sentence[b] in ",.:;!?»\"”)…":
            b += 1
        out.append(sentence[a:b])
        pos = k + len(t)
    return out


def _trim_bounds(a, wb):
    """Границы фразы по реальной громкости речи (edge-tts оставляет тишину по краям)."""
    hop = 480
    fr = np.sqrt(np.mean(a[: len(a) // hop * hop].reshape(-1, hop) ** 2, 1))
    act = np.where(fr > fr.max() * 0.03)[0]
    if len(act) == 0:
        return 0.0, len(a) / SR
    e0, e1 = act[0] * hop / SR, (act[-1] + 1) * hop / SR
    t0 = max(0.0, min(e0, wb[0]["offset"]) - 0.03)
    t1 = min(len(a) / SR, e1 + 0.07)
    return t0, t1


def voice_segments(title, sentences):
    return [{"text": title.rstrip(".") + ".", "pause": None, "is_title": True}] + \
           [dict(s, is_title=False) for s in sentences]


def segment_rates(cfg, n, extra_ramp=0.0):
    """Темп по ходу истории: старт ровно с базового rate, к финалу — быстрее
    (рассказчик теряет самообладание). Пик ограничен voice.max_rate."""
    vc = cfg["voice"]
    ramp = vc.get("tension_ramp", 0) + extra_ramp
    cap = vc.get("max_rate", 100)
    return [min(cap, vc["rate"] + ramp * (i / max(1, n - 1))) for i in range(n)]


def synth_segments(segs, rates, cfg, cache_dir):
    vc = cfg["voice"]
    jobs = [(s["text"], vc["name"], f"{int(round(r)):+d}%", f"{int(vc['pitch']):+d}Hz")
            for s, r in zip(segs, rates)]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(lambda j: tts_cached(*j, cache_dir), jobs))
    out = []
    for s, (mp3, wb) in zip(segs, results):
        a = decode_audio(mp3)
        t0, t1 = _trim_bounds(a, wb)
        clip = a[int(t0 * SR):int(t1 * SR)].copy()
        fade = min(len(clip) // 2, int(0.012 * SR))
        clip[:fade] *= np.linspace(0, 1, fade)
        clip[-fade:] *= np.linspace(1, 0, fade)
        words = [dict(w, offset=w["offset"] - t0) for w in wb]
        out.append((clip, words))
    return out


def segment_pauses(segs, cfg):
    vc = cfg["voice"]
    n = len(segs)
    rules = [(norm_phrase(k), float(v)) for k, v in vc.get("pause_before", {}).items()]
    pauses = [0.0]
    for i in range(1, n):
        s = segs[i]
        pause = vc["pause"]
        if i == 1:
            pause = vc.get("pause_after_title", pause)
        ntoks = [norm(x) for x in s["text"].split() if norm(x)]
        for toks, sec in rules:
            if toks and ntoks[:len(toks)] == toks:
                pause = sec
        if i == n - 1:
            pause = vc.get("pause_before_last", pause)
        if s.get("pause") is not None:
            pause = s["pause"]
        pauses.append(pause)
    return pauses


VOICE_LEAD = 0.35


def assemble_voice(segs, synth, pauses):
    pieces, words = [], []
    cursor = VOICE_LEAD
    for i, (s, (clip, wb)) in enumerate(zip(segs, synth)):
        cursor += pauses[i]
        pieces.append((cursor, clip))
        disp = align_display(s["text"], wb)
        for w, d in zip(wb, disp):
            words.append({"text": d, "raw": w["text"], "norm": norm(w["text"]),
                          "start": cursor + w["offset"],
                          "end": cursor + w["offset"] + w["duration"],
                          "sent": i, "title": s["is_title"]})
        cursor += len(clip) / SR
    voice = np.zeros(int((cursor + 0.1) * SR), dtype=np.float32)
    for st, clip in pieces:
        k = int(st * SR)
        voice[k:k + len(clip)] += clip
    return voice, words, cursor


def build_voice_fitted(title, sentences, cfg, cache_dir):
    """Озвучка + подгонка длины ролика под duration.max:
    1) нарастание темпа к финалу (до voice.max_rate), 2) при нехватке — обычные паузы
    ужимаются до voice.min_pause (особые паузы 1,2 / 1,5 с не трогаем)."""
    vc = cfg["voice"]
    segs = voice_segments(title, sentences)
    n = len(segs)
    pauses = segment_pauses(segs, cfg)
    regular = [i for i, p in enumerate(pauses) if i > 0 and abs(p - vc["pause"]) < 1e-6]
    dmax = cfg["duration"]["max"]
    tail = cfg["duration"]["end_tail"]
    fit = cfg["duration"].get("fit", "auto") != "none"
    extra = 0.0
    for attempt in range(4):
        rates = segment_rates(cfg, n, extra)
        log(f"Озвучка edge-tts: {vc['name']}, rate {rates[0]:+.0f}% → {max(rates):+.0f}%, "
            f"pitch {vc['pitch']:+d}Hz, паузы {pauses[regular[0]] if regular else vc['pause']:.2f} с")
        synth = synth_segments(segs, rates, cfg, cache_dir)
        lens = [len(c) / SR for c, _ in synth]
        total = VOICE_LEAD + sum(pauses) + tail + sum(lens)
        log(f"  длина ролика: {total:.1f} с")
        if total <= dmax + 0.05 or not fit:
            break
        target = dmax - 0.5
        base_speed = [l * (1 + r / 100) for l, r in zip(lens, rates)]

        def predict(ex, pz):
            pr = segment_rates(cfg, n, ex)
            return VOICE_LEAD + pz + tail + sum(b / (1 + r / 100) for b, r in zip(base_speed, pr))

        fixed_p = sum(p for i, p in enumerate(pauses) if i not in regular)
        cur_p = sum(pauses)
        if predict(extra + 200, cur_p) > target:
            # темпа не хватает: упираемся в max_rate и ужимаем обычные паузы
            extra = 200
            need = predict(extra, fixed_p)  # длина без обычных пауз
            per = (target - need) / max(1, len(regular))
            per = max(vc.get("min_pause", 0.3), min(vc["pause"], per))
            for i in regular:
                pauses[i] = per
        else:
            lo, hi = extra, extra + 200
            for _ in range(40):
                mid = (lo + hi) / 2
                if predict(mid, cur_p) > target:
                    lo = mid
                else:
                    hi = mid
            extra = hi
        log(f"  длиннее {dmax} с — подгоняю темп/паузы")
    voice, words, end = assemble_voice(segs, synth, pauses)
    return voice, words, end, rates


# ════════════════════════════════════════════════════════════════════════════
#  Таймлайн: счётчик, щелчки, эффекты
# ════════════════════════════════════════════════════════════════════════════

def build_timeline(words, voice_end, cfg, fps):
    cues = cfg["cues"]
    tl = {"fps": fps}
    T = voice_end + cfg["duration"]["end_tail"]
    T = max(T, cfg["duration"]["min"])
    tl["T"] = T
    tl["voice_end"] = voice_end

    silence_r = find_phrase(words, cues.get("silence_at"))
    silence_t = words[silence_r[0]]["start"] if silence_r else None
    tl["silence_t"] = silence_t

    clicks_r = find_phrase(words, cues.get("clicks_from"))
    counter_r = find_phrase(words, cues.get("counter_start"))
    groups = number_groups(words)

    clicks = []          # (time, gain)
    counter_steps = []   # (time, value)
    ramp = None
    if clicks_r:
        prev_val, prev_end_i = 0, clicks_r[0]
        for g in groups:
            if g["i0"] < clicks_r[0]:
                continue
            if silence_r and g["i0"] >= silence_r[0]:
                break
            w0, w1 = words[g["i0"]], words[g["i1"]]
            in_counter = counter_r is not None and g["i1"] >= counter_r[0]
            if in_counter and prev_val and g["value"] - prev_val > 10:
                # Быстрая ускоряющаяся очередь щелчков, счётчик догоняет до значения
                lead_i = max(prev_end_i + 1, g["i0"] - 2)
                t0 = words[lead_i]["start"]
                t1 = w1["end"] - 0.02
                times, dt, t = [], 0.030, t1
                while t > t0:
                    times.append(t)
                    t -= dt
                    dt = min(dt / 0.90, 0.24)
                times = sorted(times)
                K = len(times)
                for k, ct in enumerate(times):
                    v = prev_val + int(round((g["value"] - prev_val) * ((k + 1) / K) ** 1.7))
                    counter_steps.append((ct, v))
                    clicks.append((ct, 0.62 + 0.38 * (1 - k / K)))
                ramp = (t0, t1)
            else:
                clicks.append((w0["start"] + 0.02, 1.0))
                if in_counter:
                    counter_steps.append((w0["start"] + 0.02, g["value"]))
            if in_counter:
                prev_val = g["value"]
            prev_end_i = g["i1"]
    tl["clicks"] = clicks
    tl["counter_steps"] = sorted(counter_steps)
    tl["counter_start"] = words[counter_r[0]]["start"] if counter_r else None
    tl["counter_final"] = counter_steps[-1][1] if counter_steps else None
    tl["ramp"] = ramp

    fl = find_phrase(words, cues.get("monitors_flicker"))
    tl["flicker"] = (words[fl[0]]["start"], words[fl[1]]["end"] + 0.35) if fl else None
    si = find_phrase(words, cues.get("silhouettes"))
    tl["silhouette_t"] = words[si[1]]["start"] if si else None
    cr = find_phrase(words, cues.get("crowd"))
    tl["crowd_t"] = words[cr[0]]["start"] if cr else None
    tl["hit_t"] = words[cr[1]]["start"] if cr else None

    # Синхронизация часов на мониторах с упомянутым временем (например «3:07»)
    clock = None
    for w in words:
        m = re.match(r"^(\d{1,2}):(\d{2})$", w["raw"])
        if m:
            clock = (int(m.group(1)) * 3600 + int(m.group(2)) * 60, w["start"])
            break
    tl["clock"] = clock or (3 * 3600, 0.0)

    # Субтитры: 3–4 слова, не переходя через границу предложения
    body = [i for i, w in enumerate(words) if not w["title"]]
    chunks = []
    per = int(cfg["text"].get("words_per_screen", 4))
    by_sent = {}
    for i in body:
        by_sent.setdefault(words[i]["sent"], []).append(i)
    for sent in sorted(by_sent):
        idx = by_sent[sent]
        n = len(idx)
        k = max(1, math.ceil(n / per))
        base, rem = divmod(n, k)
        pos = 0
        for c in range(k):
            size = base + (1 if c < rem else 0)
            chunks.append(idx[pos:pos + size])
            pos += size
    out = []
    for ci, ch in enumerate(chunks):
        st = words[ch[0]]["start"]
        en = words[ch[-1]]["end"] + 0.45
        if ci + 1 < len(chunks):
            en = min(en, words[chunks[ci + 1][0]]["start"])
        out.append({"words": ch, "start": st, "end": min(en, T - cfg["text"]["end_card_seconds"])})
    tl["chunks"] = out
    return tl


# ════════════════════════════════════════════════════════════════════════════
#  Звук: всё синтезируется в numpy
# ════════════════════════════════════════════════════════════════════════════

def db(x):
    return 10 ** (x / 20)


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x, dtype=np.float64))) + 1e-12)


def fft_filter(x, lo=None, hi=None, order=4):
    n = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    m = np.ones_like(f)
    if lo:
        m *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** (2 * order))
    if hi:
        m *= 1 / np.sqrt(1 + (f / hi) ** (2 * order))
    return np.fft.irfft(X * m, n=n).astype(np.float32)


def fft_convolve(x, ir):
    n = len(x) + len(ir) - 1
    nf = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nf) * np.fft.rfft(ir, nf), nf)[:len(x)]
    return y.astype(np.float32)


def reverb_ir(sec, decay, rng, lo=None, hi=None):
    n = int(sec * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-t / decay)
    if lo or hi:
        ir = fft_filter(ir, lo, hi, order=2)
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    return ir


def smooth_noise(n, rate_hz, rng):
    """Медленная случайная огибающая 0..1."""
    k = max(2, int(n / SR * rate_hz) + 2)
    pts = rng.random(k)
    x = np.linspace(0, k - 1, n)
    i = np.floor(x).astype(int)
    fr = x - i
    fr = fr * fr * (3 - 2 * fr)
    i2 = np.minimum(i + 1, k - 1)
    return (pts[i] * (1 - fr) + pts[i2] * fr).astype(np.float32)


def gen_hum(n, rng, level_db):
    white = rng.standard_normal(n).astype(np.float32)
    X = np.fft.rfft(white)
    f = np.fft.rfftfreq(n, 1 / SR)
    shape = 1 / np.sqrt(np.maximum(f, 20)) * (1 / np.sqrt(1 + (f / 700) ** 6)) \
        * (1 / np.sqrt(1 + (35 / np.maximum(f, 1e-3)) ** 4))
    air = np.fft.irfft(X * shape, n=n).astype(np.float32)
    t = np.arange(n) / SR
    mains = (np.sin(2 * np.pi * 50 * t) * 0.35 + np.sin(2 * np.pi * 100 * t) * 0.5
             + np.sin(2 * np.pi * 150 * t) * 0.15).astype(np.float32)
    air /= np.sqrt(np.mean(air ** 2)) + 1e-9
    mains /= np.sqrt(np.mean(mains ** 2)) + 1e-9
    hum = air + 0.25 * mains
    hum *= 0.85 + 0.3 * smooth_noise(n, 0.15, rng)
    hum *= db(level_db) / (np.sqrt(np.mean(hum ** 2)) + 1e-9)
    # лёгкая стереоширина
    dl = int(0.011 * SR)
    left, right = hum, np.concatenate([np.zeros(dl, np.float32), hum[:-dl]])
    return np.stack([left, right], 1)


def one_step(rng):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    thud = np.sin(2 * np.pi * (75 + rng.random() * 20) * t) * np.exp(-t / 0.045)
    scuff = fft_filter(rng.standard_normal(n).astype(np.float32), 120, 1100) * np.exp(-t / 0.03)
    s = (thud * 0.9 + scuff * 0.6).astype(np.float32)
    return s / (np.max(np.abs(s)) + 1e-9)


def gen_steps(n, rng, level_db, until):
    out = np.zeros((n, 2), np.float32)
    t = 4.0 + rng.random() * 3
    end = (until if until else n / SR) - 2.0
    while t < end:
        count = rng.integers(4, 8)
        pan = rng.uniform(-0.8, 0.8)
        interval = rng.uniform(0.55, 0.68)
        for k in range(count):
            st = t + k * interval + rng.uniform(-0.02, 0.02)
            if st >= end:
                break
            env = math.sin(math.pi * (k + 0.5) / count)  # приближаются и удаляются
            s = one_step(rng) * env * rng.uniform(0.8, 1.0)
            i0 = int(st * SR)
            i1 = min(n, i0 + len(s))
            out[i0:i1, 0] += s[:i1 - i0] * (1 - pan) / 2
            out[i0:i1, 1] += s[:i1 - i0] * (1 + pan) / 2
        t += count * interval + rng.uniform(7, 13)
    # далеко: глухо и с хвостом
    ir = reverb_ir(1.4, 0.45, rng, 80, 2500)
    for c in range(2):
        dry = fft_filter(out[:, c], 60, 900)
        out[:, c] = dry * 0.35 + fft_convolve(dry, ir) * 0.9
    peak = np.max(np.abs(out)) + 1e-9
    return out / peak * db(level_db)


def turnstile_click(rng, gain=1.0):
    n = int(0.07 * SR)
    t = np.arange(n) / SR
    tick = fft_filter(rng.standard_normal(n).astype(np.float32), 1800, 9000) * np.exp(-t / 0.0012)
    f1 = 2100 + rng.uniform(-150, 150)
    ring = np.sin(2 * np.pi * f1 * t) * np.exp(-t / 0.006) * 0.35 \
        + np.sin(2 * np.pi * 860 * t) * np.exp(-t / 0.010) * 0.25
    thunk = np.sin(2 * np.pi * 150 * t) * np.exp(-t / 0.016) * 0.45
    # второй, тише — механика «щёлк-клак»
    d = int(0.011 * SR)
    s = tick * 1.0 + ring + thunk
    s2 = np.zeros_like(s)
    s2[d:] = (tick[:-d] * 0.45 + thunk[:-d] * 0.25)
    s = (s + s2).astype(np.float32)
    return s / (np.max(np.abs(s)) + 1e-9) * gain


def gen_crowd(n, rng, level_db, start, total):
    out = np.zeros((n, 2), np.float32)
    i0 = int(start * SR)
    m = n - i0
    if m <= SR:
        return out
    acc = np.zeros((m, 2), np.float32)
    for v in range(10):  # шёпот: полосовой шум с «слоговой» огибающей
        src = fft_filter(rng.standard_normal(m).astype(np.float32), 1300, 5200, order=2)
        syl = smooth_noise(m, rng.uniform(3, 6), rng) ** 3
        phrase = (smooth_noise(m, 0.35, rng) > 0.45).astype(np.float32)
        phrase = fft_filter(phrase, None, 3)
        s = src * syl * np.clip(phrase, 0, 1)
        pan = rng.uniform(-0.9, 0.9)
        acc[:, 0] += s * (1 - pan) / 2
        acc[:, 1] += s * (1 + pan) / 2
    murmur = fft_filter(rng.standard_normal(m).astype(np.float32), 110, 420, order=3)
    murmur *= 0.6 + 0.4 * smooth_noise(m, 1.5, rng)
    acc[:, 0] += murmur * 1.6
    acc[:, 1] += murmur * 1.6
    ir = reverb_ir(1.8, 0.6, rng, 150, 4000)
    for c in range(2):
        acc[:, c] = acc[:, c] * 0.4 + fft_convolve(acc[:, c], ir)
    acc *= db(level_db) / (np.sqrt(np.mean(acc ** 2)) + 1e-9)
    fade = np.clip(np.arange(m) / (2.5 * SR), 0, 1)[:, None]
    out[i0:] = acc * fade
    return out


def gen_hit(rng, level_db):
    n = int(3.0 * SR)
    t = np.arange(n) / SR
    freq = 32 + 26 * np.exp(-t / 0.35)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    boom = np.sin(phase) * np.exp(-t / 0.9)
    trans = fft_filter(rng.standard_normal(n).astype(np.float32), None, 350) * np.exp(-t / 0.06) * 3
    s = (boom + trans).astype(np.float32)
    ir = reverb_ir(2.5, 0.8, rng, 40, 1500)
    s = s * 0.8 + fft_convolve(s, ir) * 0.5
    s /= np.max(np.abs(s)) + 1e-9
    return s * db(level_db)


def build_audio(voice, tl, cfg, seed=7):
    ac = cfg["audio"]
    rng = np.random.default_rng(seed)
    T = tl["T"]
    n = int(math.ceil(T * SR))
    v = np.zeros(n, np.float32)
    v[:min(n, len(voice))] = voice[:n]
    v = fft_filter(v, 70, None, order=2)
    # нормируем голос по RMS активной речи
    frames = v[: len(v) // 1024 * 1024].reshape(-1, 1024)
    fr = np.sqrt(np.mean(frames ** 2, 1))
    active = fr > (np.max(fr) * 0.08)
    v_rms = np.sqrt(np.mean(fr[active] ** 2)) if active.any() else 1e-3
    v *= db(ac["voice_rms_db"]) / v_rms
    pk = np.max(np.abs(v))
    if pk > db(-1.5):
        v *= db(-1.5) / pk

    silence = tl["silence_t"]
    bed = gen_hum(n, rng, ac["hum_db"]) + gen_steps(n, rng, ac["steps_db"], silence)
    if silence:
        g = np.ones(n, np.float32)
        k = int(silence * SR)
        r = int(0.03 * SR)
        g[k:k + r] = np.linspace(1, 0, r)[: max(0, min(r, n - k))]
        g[k + r:] = 0
        bed *= g[:, None]

    sfx = np.zeros((n, 2), np.float32)
    for (ct, gain) in tl["clicks"]:
        c = turnstile_click(rng, gain) * db(ac["clicks_db"])
        i0 = int(ct * SR)
        i1 = min(n, i0 + len(c))
        if i0 < n:
            sfx[i0:i1, 0] += c[:i1 - i0] * 0.9
            sfx[i0:i1, 1] += c[:i1 - i0]

    crowd = np.zeros((n, 2), np.float32)
    if tl["crowd_t"]:
        crowd = gen_crowd(n, rng, ac["crowd_db"], tl["crowd_t"], T)
        h = gen_hit(rng, ac["hit_db"])
        i0 = int(tl["hit_t"] * SR)
        i1 = min(n, i0 + len(h))
        sfx[i0:i1, 0] += h[:i1 - i0]
        sfx[i0:i1, 1] += h[:i1 - i0]

    music = bed + crowd
    # финальное затухание фона вместе с картинкой
    fade = np.ones(n, np.float32)
    f0 = int((T - 3.0) * SR)
    fade[f0:] = np.linspace(1, 0, n - f0) ** 1.5
    music *= fade[:, None]
    sfx *= fade[:, None]

    mix = np.stack([v, v], 1) + music + sfx
    pk = np.max(np.abs(mix))
    if pk > db(-1.0):
        mix = np.tanh(mix / db(-1.0)) * db(-1.0)

    # контроль: голос громче фона минимум на 12 dB
    pre = int((silence or T) * SR)
    bed_rms = rms_db(music[:pre].mean(1)) if pre > SR else -99
    report = {"voice_rms": 20 * math.log10(db(ac["voice_rms_db"])), "bed_rms": bed_rms,
              "diff": ac["voice_rms_db"] - bed_rms}
    return mix.astype(np.float32), report


def write_wav(path, stereo):
    data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


# ════════════════════════════════════════════════════════════════════════════
#  Картинка: мониторы охраны (генерация)
# ════════════════════════════════════════════════════════════════════════════

CAMS = [("CAM 01", "ВХОД", "entrance"), ("CAM 02", "ГАЛЕРЕЯ 1", "corridor"),
        ("CAM 03", "АТРИУМ", "hall"), ("CAM 04", "ПАРКОВКА -1", "parking"),
        ("CAM 05", "СЛУЖ. КОРИДОР", "service"), ("CAM 06", "ФУДКОРТ", "food")]


def window_rects():
    m, gap = 22, 16
    ww = (W - 2 * m - gap) // 2
    wh = (H - 2 * m - 2 * gap) // 3
    rects = []
    for r in range(3):
        for c in range(2):
            x0 = m + c * (ww + gap)
            y0 = m + r * (wh + gap)
            rects.append((x0, y0, x0 + ww, y0 + wh))
    return rects


class Cam3D:
    def __init__(self, w, h, f, cx, cy, cam_h, ceil_h):
        self.w, self.h, self.f, self.cx, self.cy = w, h, f, cx, cy
        self.ch, self.ceil = cam_h, ceil_h

    def p(self, x, y, z):
        """x вправо, y — высота от пола, z — вперёд."""
        z = max(z, 0.05)
        return (self.cx + self.f * x / z, self.cy + self.f * (self.ch - y) / z)

    def quad(self, d, pts, fill):
        d.polygon([self.p(*q) for q in pts], fill=fill)

    def line(self, d, a, b, fill, width=1):
        d.line([self.p(*a), self.p(*b)], fill=fill, width=width)


def draw_person(d, cam: Cam3D, x, z, height=1.75, fill=10, rng=None):
    rng = rng or random.Random(0)
    fx, fy = cam.p(x, 0, z)
    hx, hy = cam.p(x, height, z)
    s = (fy - hy) / height  # пикселей на метр
    head_r = 0.11 * s
    sh = 0.23 * s * rng.uniform(0.9, 1.1)
    hip = 0.17 * s
    neck_y = hy + 2.1 * head_r
    d.ellipse([hx - head_r, hy, hx + head_r, hy + 2.2 * head_r], fill=fill)
    torso_bottom = hy + 0.52 * (fy - hy)
    d.polygon([(hx - sh * 0.55, neck_y), (hx + sh * 0.55, neck_y), (hx + sh, neck_y + 0.08 * s),
               (hx + hip, torso_bottom), (hx - hip, torso_bottom), (hx - sh, neck_y + 0.08 * s)],
              fill=fill)
    # руки вдоль тела
    d.polygon([(hx - sh, neck_y + 0.08 * s), (hx - sh * 0.8, neck_y + 0.08 * s),
               (hx - hip * 0.95, torso_bottom + 0.1 * s), (hx - hip * 1.25, torso_bottom + 0.1 * s)],
              fill=fill)
    d.polygon([(hx + sh, neck_y + 0.08 * s), (hx + sh * 0.8, neck_y + 0.08 * s),
               (hx + hip * 0.95, torso_bottom + 0.1 * s), (hx + hip * 1.25, torso_bottom + 0.1 * s)],
              fill=fill)
    leg = 0.075 * s
    d.polygon([(hx - hip, torso_bottom), (hx - 0.01 * s, torso_bottom), (hx - 0.03 * s, fy),
               (hx - hip * 0.9, fy)], fill=fill)
    d.polygon([(hx + hip, torso_bottom), (hx + 0.01 * s, torso_bottom), (hx + 0.03 * s, fy),
               (hx + hip * 0.9, fy)], fill=fill)
    _ = leg


def draw_scene(kind, w, h, seed, people=False):
    rng = random.Random(seed)
    img = Image.new("L", (w, h), 20)
    d = ImageDraw.Draw(img)
    # Камеры висят высоко и смотрят чуть вниз => горизонт выше центра
    cfgs = {
        "entrance": dict(rw=9.0, ceil=4.2, depth=22, camh=3.4, cy=0.30, xoff=0.0),
        "corridor": dict(rw=6.0, ceil=4.0, depth=40, camh=3.3, cy=0.28, xoff=-0.8),
        "hall": dict(rw=16.0, ceil=7.0, depth=34, camh=5.5, cy=0.22, xoff=1.2),
        "parking": dict(rw=14.0, ceil=2.8, depth=36, camh=2.5, cy=0.36, xoff=0.5),
        "service": dict(rw=3.2, ceil=3.0, depth=30, camh=2.7, cy=0.30, xoff=0.3),
        "food": dict(rw=14.0, ceil=5.0, depth=26, camh=4.4, cy=0.25, xoff=-1.0),
    }
    c = cfgs[kind]
    cam = Cam3D(w, h, f=w * 0.62, cx=w * 0.5, cy=h * c["cy"], cam_h=c["camh"], ceil_h=c["ceil"])
    rw, ceil, D, xo = c["rw"] / 2, c["ceil"], c["depth"], c["xoff"]
    zn = 0.3
    L, R = -rw + xo, rw + xo
    # пол, потолок, стены, торцевая стена
    cam.quad(d, [(L, 0, zn), (R, 0, zn), (R, 0, D), (L, 0, D)], 92)
    cam.quad(d, [(L, ceil, zn), (R, ceil, zn), (R, ceil, D), (L, ceil, D)], 38)
    cam.quad(d, [(L, 0, zn), (L, ceil, zn), (L, ceil, D), (L, 0, D)], 66)
    cam.quad(d, [(R, 0, zn), (R, ceil, zn), (R, ceil, D), (R, 0, D)], 58)
    cam.quad(d, [(L, 0, D), (R, 0, D), (R, ceil, D), (L, ceil, D)], 44)
    # плитка на полу
    step = 1.2 if kind != "parking" else 2.5
    x = L
    while x <= R:
        cam.line(d, (x, 0, zn), (x, 0, D), 78)
        x += step
    z = 1.0
    while z < D:
        cam.line(d, (L, 0, z), (R, 0, z), 80)
        z += step
    if kind == "parking":
        for x in np.arange(L + 2.5, R, 2.6):
            cam.line(d, (x, 0.01, 4), (x, 0.01, D - 2), 150, 2)
    # лампы на потолке
    for z in np.arange(3, D - 1, 3.5 if kind != "service" else 4.5):
        for lx in ([xo] if rw < 4 else [L / 2 + xo / 2, R / 2 + xo / 2]):
            cam.quad(d, [(lx - 0.6, ceil - 0.01, z), (lx + 0.6, ceil - 0.01, z),
                         (lx + 0.6, ceil - 0.01, z + 0.5), (lx - 0.6, ceil - 0.01, z + 0.5)],
                     185 if rng.random() > 0.12 else 70)
    # витрины / двери на стенах
    if kind in ("corridor", "hall", "food", "entrance"):
        z = 2.0
        while z < D - 3:
            ln = rng.uniform(3, 6)
            for wx in (L, R):
                lit = rng.random() < 0.3
                cam.quad(d, [(wx, 0.05, z), (wx, 2.9, z), (wx, 2.9, z + ln), (wx, 0.05, z + ln)],
                         110 if lit else 30)
                cam.line(d, (wx, 2.9, z), (wx, 2.9, z + ln), 120, 2)
                cam.line(d, (wx, 0.05, z), (wx, 2.9, z), 100, 2)
            z += ln + rng.uniform(0.5, 1.5)
    if kind == "service":
        for z in np.arange(3, D - 2, 5):
            wx = L if rng.random() < 0.5 else R
            cam.quad(d, [(wx, 0, z), (wx, 2.1, z), (wx, 2.1, z + 0.9), (wx, 0, z + 0.9)], 48)
        cam.line(d, (L + 0.05, 2.5, zn), (L + 0.05, 2.5, D), 90, 3)
        cam.line(d, (L + 0.05, 2.65, zn), (L + 0.05, 2.65, D), 80, 2)
    # колонны
    if kind in ("hall", "parking", "food"):
        for z in np.arange(6, D - 2, 7 if kind != "parking" else 6):
            for cx in ([L / 2 + xo / 2, R / 2 + xo / 2] if kind != "parking" else [L / 3, R / 3]):
                cam.quad(d, [(cx - 0.45, 0, z), (cx + 0.45, 0, z), (cx + 0.45, ceil, z),
                             (cx - 0.45, ceil, z)], 74)
                cam.quad(d, [(cx - 0.45, 0, z), (cx - 0.45, ceil, z), (cx - 0.45, ceil, z + 0.9),
                             (cx - 0.45, 0, z + 0.9)], 60)
    if kind == "food":
        for _ in range(14):
            tx, tz = rng.uniform(L + 1, R - 1), rng.uniform(4, D - 4)
            cam.quad(d, [(tx - 0.5, 0.75, tz - 0.4), (tx + 0.5, 0.75, tz - 0.4),
                         (tx + 0.5, 0.75, tz + 0.4), (tx - 0.5, 0.75, tz + 0.4)], 120)
            cam.line(d, (tx, 0, tz), (tx, 0.75, tz), 50, 2)
    if kind == "hall":
        # эскалатор
        cam.quad(d, [(xo - 1.0, 0, 10), (xo + 1.0, 0, 10), (xo + 1.0, 5.5, 22), (xo - 1.0, 5.5, 22)], 70)
        cam.line(d, (xo - 1.0, 1.0, 10), (xo - 1.0, 6.5, 22), 140, 2)
        cam.line(d, (xo + 1.0, 1.0, 10), (xo + 1.0, 6.5, 22), 140, 2)
    if kind == "entrance":
        # стеклянные двери на торце и турникеты
        for dx in (-3, -1, 1, 3):
            cam.quad(d, [(dx - 0.9, 0, D), (dx + 0.9, 0, D), (dx + 0.9, 2.6, D), (dx - 0.9, 2.6, D)], 26)
            cam.line(d, (dx, 0, D), (dx, 2.6, D), 110, 2)
        for tx in (-2.4, -0.8, 0.8, 2.4):
            cam.quad(d, [(tx - 0.12, 0, 6), (tx + 0.12, 0, 6), (tx + 0.12, 1.0, 6), (tx - 0.12, 1.0, 6)], 150)
            cam.quad(d, [(tx - 0.12, 1.0, 6), (tx + 0.12, 1.0, 6), (tx + 0.12, 1.0, 6.8),
                         (tx - 0.12, 1.0, 6.8)], 170)
            cam.line(d, (tx + 0.12, 0.9, 6.3), (tx + 0.75, 0.9, 6.3), 175, 3)
    # люди
    if people:
        prng = random.Random(seed * 31 + 7)
        count = prng.randint(3, 6)
        spots = sorted([(prng.uniform(L + 0.6, R - 0.6), prng.uniform(4.5, min(D - 2, 16)))
                        for _ in range(count)], key=lambda p: -p[1])
        for (px, pz) in spots:
            draw_person(d, cam, px, pz, prng.uniform(1.65, 1.9), fill=prng.randint(4, 14), rng=prng)
    # «свет» ламп: мягкое свечение и затемнение вдаль
    img = img.filter(ImageFilter.GaussianBlur(1.1))
    arr = np.asarray(img).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h * 0.45) / (h / 2)) ** 2)
    arr *= np.clip(1.15 - 0.45 * r ** 1.6, 0.35, 1.2)
    glow = np.asarray(img.filter(ImageFilter.GaussianBlur(10))).astype(np.float32)
    arr = arr + np.clip(glow - 110, 0, None) * 0.6
    return np.clip(arr, 0, 255)


def build_monitor_bases(cfg, seed=11):
    tint = np.array(cfg["colors"]["monitor_tint"], np.float32)
    rects = window_rects()
    bases = []
    for people in (False, True):
        full = np.zeros((H, W, 3), np.float32)
        full[:] = (9, 11, 10)
        for k, ((x0, y0, x1, y1), (_, _, kind)) in enumerate(zip(rects, CAMS)):
            w, h = x1 - x0, y1 - y0
            L = draw_scene(kind, w, h, seed + k, people=people)
            expo = 0.78 + 0.16 * ((k * 37) % 7) / 6
            rgb = L[..., None] * tint[None, None, :] * expo + np.array([6, 10, 7], np.float32)
            full[y0:y1, x0:x1] = rgb
            # рамка окна
            full[y0:y0 + 2, x0:x1] = 70
            full[y1 - 2:y1, x0:x1] = 40
            full[y0:y1, x0:x0 + 2] = 55
            full[y0:y1, x1 - 2:x1] = 45
        img = Image.fromarray(np.clip(full, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        mono = ImageFont.truetype(first_existing(cfg["fonts"]["mono"]), 24) \
            if first_existing(cfg["fonts"]["mono"]) else ImageFont.load_default()
        hud = tuple(cfg["colors"]["hud"])
        for (x0, y0, x1, y1), (cam, name, _) in zip(rects, CAMS):
            d.text((x0 + 14, y0 + 12), f"{cam}  {name}", font=mono, fill=hud)
        bases.append(np.asarray(img).astype(np.uint8))
    return bases[0], bases[1], rects


# ════════════════════════════════════════════════════════════════════════════
#  Рендер кадров (в нескольких процессах)
# ════════════════════════════════════════════════════════════════════════════

CTX: dict = {}


class Fonts:
    def __init__(self, cfg):
        self.bold_path = first_existing(cfg["fonts"]["bold"])
        self.mono_path = first_existing(cfg["fonts"]["mono"])
        self._cache = {}

    def bold(self, size):
        key = ("b", int(size))
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(self.bold_path, int(size)) if self.bold_path \
                else ImageFont.load_default()
        return self._cache[key]

    def mono(self, size):
        key = ("m", int(size))
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(self.mono_path, int(size)) if self.mono_path \
                else ImageFont.load_default()
        return self._cache[key]


def make_title_layer(title, fonts: Fonts, cfg):
    col = cfg["colors"]
    t = title.upper() if cfg["text"]["uppercase"] else title
    size = 150
    words = t.split()
    while True:
        f = fonts.bold(size)
        lines = wrap_words(words, f, 940, size)
        if max(text_w(f, ln, 10) for ln in lines) <= 960 or size < 60:
            break
        size -= 8
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lh = size * 1.08
    y = H * 0.45 - lh * (len(lines) - 1) / 2
    for ln in lines:
        d.text((W / 2, y), ln, font=f, fill=(*col["subtitle"], 255), anchor="mm",
               stroke_width=10, stroke_fill=(*col["stroke"], 255))
        y += lh
    # тонкая красная линия под заголовком
    ly = int(y - lh / 2 + size * 0.35)
    d.rectangle([W / 2 - 170, ly, W / 2 + 170, ly + 6], fill=(*col["highlight"], 255))
    return np.asarray(img).astype(np.float32) / 255.0


def make_end_card(cfg, fonts: Fonts):
    col = cfg["colors"]
    lines = cfg["text"]["end_card"].split("\n")
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    big, small = fonts.bold(118), fonts.bold(84)
    bw, bh = 860, 400
    x0, y0 = (W - bw) / 2, H * 0.5 - bh / 2
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=36, fill=(12, 6, 6, 235),
                        outline=(*col["highlight"], 255), width=6)
    if len(lines) == 1:
        d.text((W / 2, H * 0.5), lines[0], font=big, fill=(*col["subtitle"], 255), anchor="mm",
               stroke_width=6, stroke_fill=(0, 0, 0, 255))
    else:
        d.text((W / 2, H * 0.5 - 70), lines[0], font=big, fill=(*col["highlight"], 255),
               anchor="mm", stroke_width=6, stroke_fill=(0, 0, 0, 255))
        d.text((W / 2, H * 0.5 + 80), " ".join(lines[1:]).upper() if cfg["text"]["uppercase"]
               else " ".join(lines[1:]), font=small, fill=(*col["subtitle"], 255), anchor="mm",
               stroke_width=6, stroke_fill=(0, 0, 0, 255))
    return np.asarray(img).astype(np.float32) / 255.0


def text_w(font, s, stroke=0):
    b = font.getbbox(s, stroke_width=stroke)
    return b[2] - b[0]


def wrap_words(words, font, maxw, size):
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and text_w(font, trial) > maxw:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def display_word(w, cfg):
    keep = cfg["text"]["keep_punct"]
    s = w["text"]
    s = "".join(ch for ch in s if ch.isalnum() or ch in keep or ch in "-–—'’")
    s = s.strip("-–— ")
    if not s:
        s = w["raw"]
    return s.upper() if cfg["text"]["uppercase"] else s


def chunk_layout(ci):
    """Раскладка слов субтитра по строкам: центры слов и размер шрифта."""
    cache = CTX.setdefault("layouts", {})
    if ci in cache:
        return cache[ci]
    cfg, fonts, words = CTX["cfg"], CTX["fonts"], CTX["words"]
    ch = CTX["tl"]["chunks"][ci]
    texts = [display_word(words[i], cfg) for i in ch["words"]]
    size = cfg["text"]["subtitle_size"]
    maxw = 900
    stroke = max(4, size // 12)
    while True:
        f = fonts.bold(size)
        ws = [text_w(f, t, stroke) for t in texts]
        sp = size * 0.34
        total = sum(ws) + sp * (len(ws) - 1)
        if total <= maxw:
            lines = [list(range(len(ws)))]
        else:
            best = None
            for k in range(1, len(ws)):
                a = sum(ws[:k]) + sp * (k - 1)
                b = sum(ws[k:]) + sp * (len(ws) - k - 1)
                score = max(a, b)
                if best is None or score < best[0]:
                    best = (score, k)
            lines = [list(range(best[1])), list(range(best[1], len(ws)))]
        widest = max(sum(ws[i] for i in ln) + sp * (len(ln) - 1) for ln in lines)
        if widest <= maxw or size <= 50:
            break
        size -= 6
    lh = size * 1.16
    cy0 = H * cfg["text"]["subtitle_y"] - lh * (len(lines) - 1) / 2
    pos = [None] * len(ws)
    for li, ln in enumerate(lines):
        lw = sum(ws[i] for i in ln) + sp * (len(ln) - 1)
        x = W / 2 - lw / 2
        for i in ln:
            pos[i] = (x + ws[i] / 2, cy0 + li * lh)
            x += ws[i] + sp
    cache[ci] = (texts, pos, size, stroke)
    return cache[ci]


def draw_subtitles(d: ImageDraw.ImageDraw, t):
    tl, words, cfg, fonts = CTX["tl"], CTX["words"], CTX["cfg"], CTX["fonts"]
    col = cfg["colors"]
    for ci, ch in enumerate(tl["chunks"]):
        if not (ch["start"] <= t < ch["end"]):
            continue
        texts, pos, size, stroke = chunk_layout(ci)
        idx = ch["words"]
        cur = None
        for k, wi in enumerate(idx):
            nxt = words[idx[k + 1]]["start"] if k + 1 < len(idx) else words[wi]["end"] + 0.15
            if words[wi]["start"] <= t < nxt:
                cur = k
        # появление чанка: короткий «наезд»
        age = t - ch["start"]
        for k, (txt, (x, y)) in enumerate(zip(texts, pos)):
            if k == cur:
                ws = t - words[idx[k]]["start"]
                scale = 1 + 0.08 * math.exp(-ws / 0.09) + 0.025 * math.sin(2 * math.pi * 4.5 * ws)
                glow = 0.5 + 0.5 * math.sin(2 * math.pi * 4.5 * ws)
                hc = col["highlight"]
                fill = (hc[0], int(min(255, hc[1] + 40 * glow)), int(min(255, hc[2] + 30 * glow)))
                f = fonts.bold(round(size * scale))
                d.text((x, y), txt, font=f, fill=fill, anchor="mm",
                       stroke_width=stroke + 1, stroke_fill=tuple(col["stroke"]))
            else:
                sc = 1.0 + 0.06 * math.exp(-age / 0.07)
                f = fonts.bold(round(size * sc))
                d.text((x, y), txt, font=f, fill=tuple(col["subtitle"]), anchor="mm",
                       stroke_width=stroke, stroke_fill=tuple(col["stroke"]))


COUNTER_BOX = (40, 100, 400, 286)


def counter_value(t):
    tl = CTX["tl"]
    if tl["counter_start"] is None or t < tl["counter_start"]:
        return None, None
    val, last_t = None, None
    for (ct, v) in tl["counter_steps"]:
        if ct <= t:
            val, last_t = v, ct
        else:
            break
    if val is None:
        val, last_t = 1, tl["counter_start"]
    return val, last_t


def draw_counter(d: ImageDraw.ImageDraw, t):
    val, last_t = counter_value(t)
    if val is None:
        return
    cfg, fonts = CTX["cfg"], CTX["fonts"]
    col = cfg["colors"]
    x0, y0, x1, y1 = COUNTER_BOX
    final = CTX["tl"]["counter_final"]
    age = t - last_t
    if final is not None and val >= final:
        pulse = 0.5 + 0.5 * math.sin(2 * math.pi * 1.2 * t)
        c = col["counter_alert"]
        fill = tuple(int(v * (0.75 + 0.25 * pulse)) for v in c)
        border = fill
    else:
        k = math.exp(-age / 0.18)
        a, b = np.array(col["counter_alert"]), np.array(col["counter"])
        fill = tuple(int(v) for v in b + (a - b) * k)
        border = (90, 120, 95)
    d.rectangle([x0, y0, x1, y1], outline=border, width=3)
    d.text((x0 + 22, y0 + 18), cfg["cues"].get("counter_label", ""), font=fonts.mono(36),
           fill=tuple(col["hud"]))
    # точка «связи» турникета
    if age < 0.12:
        d.ellipse([x1 - 34, y0 + 22, x1 - 18, y0 + 38], fill=tuple(col["counter_alert"]))
    sc = 1 + 0.08 * math.exp(-age / 0.1)
    d.text((x0 + 22, y1 - 20), str(val), font=fonts.bold(round(108 * sc)), fill=fill, anchor="ls",
           stroke_width=3, stroke_fill=(0, 0, 0))


def fmt_clock(t):
    c0, ct = CTX["tl"]["clock"]
    s = int(c0 + (t - ct)) % 86400
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"


def frame_rng(fi):
    return np.random.default_rng(CTX["seed"] * 100003 + fi)


def monitor_events():
    """Расписание случайных мерцаний одного окна."""
    rng = random.Random(CTX["seed"] + 5)
    ev, t = [], 2.5
    T = CTX["tl"]["T"]
    while t < T:
        t += rng.uniform(2.5, 6.0)
        ev.append((t, rng.uniform(0.15, 0.5), rng.randrange(6)))
    return ev


def background_generated(t, fi, rng):
    tl = CTX["tl"]
    sil_t = tl["silhouette_t"]
    sil = sil_t is not None and 0 <= t - sil_t < (1 / 30) - 1e-6
    base = CTX["base_sil"] if sil else CTX["base"]
    f = base.astype(np.float32)
    bank = CTX["noise"]
    nz = bank[rng.integers(len(bank))]
    if rng.random() < 0.5:
        nz = nz[::-1]
    f += nz[..., None] * 1.0
    # строки развёртки и бегущая полоса
    f *= CTX["scan"][:, None, None]
    band_y = (t * 140) % (H + 400) - 200
    yy = CTX["yy"]
    f *= (1 + 0.10 * np.exp(-((yy - band_y) / 60) ** 2))[:, None, None]
    hidden = set()
    rects = CTX["rects"]
    fl = tl["flicker"]
    global_flick = fl is not None and fl[0] <= t < fl[1]
    for wi, (x0, y0, x1, y1) in enumerate(rects):
        g = 1.0 + rng.uniform(-0.03, 0.03)
        tear = 0
        if global_flick:
            r = rng.random()
            g = 0.0 if r < 0.22 else (rng.uniform(1.25, 1.6) if r < 0.4 else rng.uniform(0.2, 1.0))
            tear = int(rng.integers(-40, 40)) if rng.random() < 0.4 else 0
        else:
            for (et, ed, ew) in CTX["events"]:
                if ew == wi and et <= t < et + ed:
                    r = rng.random()
                    g = 0.05 if r < 0.3 else rng.uniform(0.4, 1.35)
                    tear = int(rng.integers(-25, 25)) if rng.random() < 0.5 else 0
        if g != 1.0:
            f[y0 + 2:y1 - 2, x0 + 2:x1 - 2] *= g
        if g < 0.1:
            hidden.add(wi)
        if tear:
            ty = int(rng.integers(y0 + 20, y1 - 80))
            th = int(rng.integers(20, 70))
            f[ty:ty + th, x0 + 2:x1 - 2] = np.roll(f[ty:ty + th, x0 + 2:x1 - 2], tear, axis=1)
    return f, hidden


def background_video(t, fi, rng):
    tl = CTX["tl"]
    raw = CTX["reader"].stdout.read(W * H * 3)
    if len(raw) < W * H * 3:
        raw = CTX.get("last_raw", bytes(W * H * 3))
    CTX["last_raw"] = raw
    f = np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.float32)
    bank = CTX["noise"]
    f += bank[rng.integers(len(bank))][..., None] * 1.1
    f *= CTX["scan"][:, None, None]
    sil_t = tl["silhouette_t"]
    if sil_t is not None and 0 <= t - sil_t < (1 / 30) - 1e-6:
        f *= (1 - CTX["sil_alpha"][..., None] * 0.9)
    fl = tl["flicker"]
    if fl is not None and fl[0] <= t < fl[1]:
        r = rng.random()
        f *= 0.05 if r < 0.25 else (rng.uniform(1.2, 1.5) if r < 0.4 else rng.uniform(0.3, 1.0))
    else:
        for (et, ed, _) in CTX["events"]:
            if et <= t < et + ed * 0.5:
                f *= rng.uniform(0.55, 1.1)
                break
    return f, set()


def draw_hud(d, t, hidden, rng):
    fonts, cfg = CTX["fonts"], CTX["cfg"]
    hud = tuple(cfg["colors"]["hud"])
    red = tuple(cfg["colors"]["counter_alert"])
    clock = fmt_clock(t)
    if CTX["mode"] == "generated":
        f = fonts.mono(24)
        for wi, (x0, y0, x1, y1) in enumerate(CTX["rects"]):
            if wi in hidden:
                continue
            ph = (wi * 0.37) % 1
            # таймкод мигает, двоеточия — каждую секунду
            blink = ((t + ph) % 1.0) < 0.5
            tc = clock if blink else clock.replace(":", " ")
            if rng.random() < 0.015:
                continue
            d.text((x0 + 14, y0 + 42), f"2026-11-24  {tc}", font=f, fill=hud)
            if blink:
                d.ellipse([x1 - 104, y0 + 16, x1 - 88, y0 + 32], fill=red)
            d.text((x1 - 80, y0 + 12), "REC", font=f, fill=hud)
    else:
        f = fonts.mono(34)
        blink = (t % 1.0) < 0.5
        d.text((44, H - 120), "CAM 07  КОРИДОР", font=f, fill=hud)
        d.text((44, H - 76), f"2026-11-24  {clock if blink else clock.replace(':', ' ')}", font=f, fill=hud)
        if blink:
            d.ellipse([W - 190, 82, W - 166, 106], fill=red)
        d.text((W - 150, 76), "REC", font=f, fill=hud)


def render_frame(fi):
    tl, cfg = CTX["tl"], CTX["cfg"]
    fps = tl["fps"]
    t = fi / fps
    T = tl["T"]
    rng = frame_rng(fi)
    if CTX["mode"] == "generated":
        f, hidden = background_generated(t, fi, rng)
    else:
        f, hidden = background_video(t, fi, rng)
    f *= CTX["vignette"][..., None]
    # мягкая тёмная подложка под субтитрами (читаемость поверх мониторов)
    f *= CTX["sub_band"][:, None, None]
    # затемнение под счётчиком
    if tl["counter_start"] is not None and t >= tl["counter_start"]:
        x0, y0, x1, y1 = COUNTER_BOX
        f[y0:y1, x0:x1] *= 0.25
    # заголовок
    title_s = cfg["text"]["title_seconds"]
    if t < title_s:
        a = 1.0 if t < title_s - 0.45 else max(0.0, (title_s - t) / 0.45)
        f *= (1 - 0.45 * a)
        lay = CTX["title"]
        al = lay[..., 3:4] * a
        f = f * (1 - al) + lay[..., :3] * 255 * al
    img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    draw_hud(d, t, hidden, rng)
    draw_counter(d, t)
    draw_subtitles(d, t)
    end_s = cfg["text"]["end_card_seconds"]
    if t < T - 3.0:
        return np.asarray(img)
    # последние 3 секунды: красное свечение по краям и уход в чёрное
    f = np.asarray(img).astype(np.float32)
    k = (t - (T - 3.0)) / 3.0
    glow = min(1.0, k * 1.6) * (0.85 + 0.15 * math.sin(2 * math.pi * 1.3 * t))
    f += CTX["edge"][..., None] * np.array(cfg["colors"]["edge_glow"], np.float32) * glow
    bright = max(0.0, 1 - min(1.0, k / 0.85) ** 1.3)
    f *= bright
    if t >= T - end_s:
        a = min(1.0, (t - (T - end_s)) / 0.2)
        lay = CTX["end_card"]
        al = lay[..., 3:4] * a
        f = f * (1 - al) + lay[..., :3] * 255 * al
    return np.clip(f, 0, 255).astype(np.uint8)


def prepare_ctx(cfg, tl, words, mode, bg_prepped, seed=1337):
    CTX.clear()
    CTX.update(cfg=cfg, tl=tl, words=words, mode=mode, seed=seed, bg_prepped=bg_prepped)
    CTX["fonts"] = Fonts(cfg)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    CTX["vignette"] = np.clip(1.08 - 0.42 * r ** 2.0, 0.25, 1.0).astype(np.float32)
    CTX["edge"] = (np.clip((r - 0.62) / 0.75, 0, 1) ** 1.4).astype(np.float32)
    CTX["yy"] = np.arange(H, dtype=np.float32)
    sy = H * cfg["text"]["subtitle_y"]
    CTX["sub_band"] = (1 - 0.5 * np.exp(-((CTX["yy"] - sy) / 150) ** 4)).astype(np.float32)
    scan = np.ones(H, np.float32)
    scan[::3] = 0.84
    CTX["scan"] = scan
    rng = np.random.default_rng(seed)
    bank = []
    for _ in range(10):  # зерно камер наблюдения: крупное (полуразрешение) + мелкое
        coarse = rng.normal(0, 9, (H // 2, W // 2)).astype(np.float32)
        coarse = np.repeat(np.repeat(coarse, 2, 0), 2, 1)
        fine = rng.normal(0, 6, (H, W)).astype(np.float32)
        bank.append((coarse + fine).astype(np.float32))
    CTX["noise"] = bank
    CTX["events"] = monitor_events()
    CTX["title"] = make_title_layer(CTX["words"] and _title_text(words), CTX["fonts"], cfg)
    CTX["end_card"] = make_end_card(cfg, CTX["fonts"])
    if mode == "generated":
        CTX["base"], CTX["base_sil"], CTX["rects"] = build_monitor_bases(cfg)
    else:
        CTX["rects"] = []
        CTX["sil_alpha"] = silhouette_alpha_fullframe(seed)


def _title_text(words):
    return " ".join(w["text"] for w in words if w["title"]).rstrip(".")


def silhouette_alpha_fullframe(seed):
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    cam = Cam3D(W, H, f=W * 0.62, cx=W / 2, cy=H * 0.32, cam_h=2.2, ceil_h=3.0)
    prng = random.Random(seed)
    spots = sorted([(prng.uniform(-2.4, 2.4), prng.uniform(3.5, 14)) for _ in range(7)],
                   key=lambda p: -p[1])
    for (x, z) in spots:
        draw_person(d, cam, x, z, prng.uniform(1.65, 1.9), fill=255, rng=prng)
    img = img.filter(ImageFilter.GaussianBlur(3))
    return np.asarray(img).astype(np.float32) / 255.0


def worker_segment(args):
    seg_idx, f0, f1, out_path = args
    fps = CTX["tl"]["fps"]
    if CTX["mode"] == "video":
        CTX["reader"] = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-ss", f"{f0 / fps:.6f}", "-i", CTX["bg_prepped"],
             "-frames:v", str(f1 - f0), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            stdout=subprocess.PIPE)
    enc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(fps), "-i", "pipe:0",
         "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "10M" if fps <= 30 else "14M",
         "-bufsize", "20M", "-profile:v", "high",
         "-level", "4.2", "-colorspace", "bt709", "-color_primaries", "bt709",
         "-color_trc", "bt709", "-g", str(fps * 2), "-threads", "2", str(out_path)],
        stdin=subprocess.PIPE)
    for fi in range(f0, f1):
        enc.stdin.write(render_frame(fi).tobytes())
    enc.stdin.close()
    enc.wait()
    if CTX["mode"] == "video":
        CTX["reader"].stdout.close()
        CTX["reader"].wait()
    if enc.returncode != 0:
        raise RuntimeError(f"ffmpeg упал на сегменте {seg_idx}")
    return seg_idx


def prep_bg_video(src: Path, T, fps, cfg, out: Path):
    tint = cfg["colors"]["bg_video_tint"]
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},"
          f"format=gray,format=rgb24,"
          f"colorchannelmixer=rr={tint[0]}:gg={tint[1]}:bb={tint[2]},"
          f"eq=contrast=1.08")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", str(src),
                    "-t", f"{T + 0.5:.3f}", "-an", "-vf", vf, "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv444p", str(out)],
                   check=True)


# ════════════════════════════════════════════════════════════════════════════
#  main
# ════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Хоррор-шортс: озвучка + субтитры + атмосфера")
    ap.add_argument("story", nargs="?", default="story.txt")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--fps", type=int, default=30, choices=[30, 60])
    ap.add_argument("--preview", type=float, default=0,
                    help="отрендерить только первые N секунд (пробная версия)")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--bg", default=str(ROOT / "bg"), help="папка с фоновыми видео")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--seed", type=int, default=None, help="зерно случайности (фон, звук)")
    ap.add_argument("--keep-temp", action="store_true")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"Не найден {tool}. Установите ffmpeg (https://ffmpeg.org) и повторите.")
    try:
        __import__("edge_tts")
    except ImportError:
        log("Устанавливаю edge-tts…")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "edge-tts"], check=True)
    _patch_edge_tts_ssl()

    cfg = load_config(Path(args.config))
    story_path = Path(args.story)
    out = Path(args.output or ("preview.mp4" if args.preview else "output.mp4"))
    fps = args.fps
    seed = args.seed if args.seed is not None else 1337
    cache_dir = ROOT / ".cache" / "tts"
    cache_dir.mkdir(parents=True, exist_ok=True)

    title, sentences = parse_story(story_path)
    log(f"История «{title}»: {len(sentences)} предложений")

    # 1. Озвучка (с контролем длины 50–65 с)
    voice, words, voice_end, rates = build_voice_fitted(title, sentences, cfg, cache_dir)
    log(f"  голос: {voice_end:.1f} с, слов с таймингами: {len(words)}")

    tl = build_timeline(words, voice_end, cfg, fps)
    T = tl["T"]
    render_T = min(T, args.preview) if args.preview else T

    # 2. Звук
    log("Синтез звука: вентиляция, шаги, турникет, толпа, удар…")
    mix, rep = build_audio(voice, tl, cfg, seed=seed)
    log(f"  голос {rep['voice_rms']:.1f} dBFS RMS, фон {rep['bed_rms']:.1f} dBFS RMS → "
        f"разница {rep['diff']:.1f} dB {'(OK ≥12)' if rep['diff'] >= 12 else '(!) меньше 12'}")

    tmp = Path(tempfile.mkdtemp(prefix="horror_"))
    try:
        wav = tmp / "audio.wav"
        write_wav(wav, mix[: int(render_T * SR)])

        # 3. Фон
        bg_dir = Path(args.bg)
        vids = sorted([p for p in bg_dir.glob("*") if p.suffix.lower() in (".mp4", ".mov")]) \
            if bg_dir.is_dir() else []
        bg_prepped = None
        if vids:
            src = random.Random(seed if args.seed is not None else None).choice(vids)
            log(f"Фон: {src.name} → 9:16, холодная гамма, -35% яркости, зерно")
            bg_prepped = tmp / "bg.mp4"
            prep_bg_video(src, render_T, fps, cfg, bg_prepped)
            mode = "video"
        else:
            log("Фон: папка bg/ пуста — генерирую мониторы охраны (2×3)")
            mode = "generated"

        # 4. Кадры
        log("Подготовка рендера…")
        prepare_ctx(cfg, tl, words, mode, str(bg_prepped) if bg_prepped else None, seed)
        n_frames = int(round(render_T * fps))
        n_seg = max(1, min(args.workers * 2, n_frames // fps))
        bounds = np.linspace(0, n_frames, n_seg + 1).astype(int)
        jobs = [(i, int(bounds[i]), int(bounds[i + 1]), tmp / f"seg_{i:03d}.mp4")
                for i in range(n_seg) if bounds[i + 1] > bounds[i]]
        log(f"Рендер {n_frames} кадров ({W}x{H}, {fps} fps) в {args.workers} процессах…")
        t0 = time.time()
        ctx = mp.get_context("fork") if hasattr(os, "fork") else mp.get_context()
        if ctx.get_start_method() == "fork" and args.workers > 1:
            with ctx.Pool(args.workers) as pool:
                for k, _ in enumerate(pool.imap_unordered(worker_segment, jobs), 1):
                    log(f"  сегмент {k}/{len(jobs)} готов")
        else:
            for k, j in enumerate(jobs, 1):
                worker_segment(j)
                log(f"  сегмент {k}/{len(jobs)} готов")
        log(f"  кадры готовы за {time.time() - t0:.0f} с")

        # 5. Сборка
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{j[3].as_posix()}'\n" for j in jobs), encoding="utf-8")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-t", f"{render_T:.3f}",
                        "-movflags", "+faststart", str(out)], check=True)
    finally:
        if args.keep_temp:
            log(f"Временные файлы: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout)
    log(f"Готово: {out.resolve()}  ({dur:.1f} с, {out.stat().st_size / 1e6:.1f} МБ)")
    if mode == "generated":
        log("Подсказка: положите свои .mp4/.mov в папку bg/ — фон возьмётся оттуда.")


if __name__ == "__main__":
    main()
