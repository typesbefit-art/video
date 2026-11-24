#!/usr/bin/env python3
"""
Генератор вертикального безлицевого видео «страшная и смешная история».

    python generate.py story.txt                 -> output.mp4 (1080x1920, 30 fps)
    python generate.py story.txt --fps 60        -> 60 fps
    python generate.py story.txt --preview 15    -> только первые 15 секунд

История берётся из текстового файла (первая строка — заголовок),
все настройки голоса, цветов, пауз и звуковых/световых событий — из config.json.
Код при смене истории менять не нужно.
"""
from __future__ import annotations

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
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
SR = 48000
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".MP4", ".MOV"}


# --------------------------------------------------------------------------- #
#  Утилиты
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore


def db_to_amp(db: float) -> float:
    return 10 ** (db / 20)


def rms_db(x: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0
    return 20 * math.log10(max(r, 1e-12))


def norm_word(s: str) -> str:
    """Нормализация для сопоставления слов: нижний регистр, ё→е, только буквы/цифры."""
    s = s.lower().replace("ё", "е")
    return "".join(ch for ch in s if ch.isalnum())


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"Не найден {tool}. Установите ffmpeg (https://ffmpeg.org) и повторите.")


def ensure_edge_tts():
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        log("Устанавливаю edge-tts ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "edge-tts"])
    import edge_tts
    # Если в окружении задан собственный CA (корпоративный/прокси) — доверяем ему тоже.
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and os.path.exists(ca):
        try:
            import edge_tts.communicate as ec
            ec._SSL_CTX.load_verify_locations(ca)
        except Exception:
            pass
    return edge_tts


# --------------------------------------------------------------------------- #
#  Разбор истории
# --------------------------------------------------------------------------- #
def read_story(path: Path) -> tuple[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    lines = [l.rstrip() for l in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        sys.exit("Файл истории пуст.")
    title = lines[0].strip()
    body = " ".join(l.strip() for l in lines[1:] if l.strip())
    if not body:
        sys.exit("После заголовка нет текста истории.")
    return title, body


def split_phrases(body: str, cfg: dict) -> list[dict]:
    """Режем текст на фразы (по предложениям) + отдельные разрезы перед
    фразами с особой паузой. Возвращает [{text, pause_before}]."""
    text = re.sub(r"\s+", " ", body).strip()
    closers = "»\"”’)"
    pieces, cur, i = [], "", 0
    while i < len(text):
        ch = text[i]
        cur += ch
        if ch in ".!?…":
            j = i + 1
            while j < len(text) and text[j] in ".!?…" + closers:
                cur += text[j]
                j += 1
            if j >= len(text) or text[j] == " ":
                pieces.append(cur.strip())
                cur = ""
            i = j
            continue
        i += 1
    if cur.strip():
        pieces.append(cur.strip())

    # «Почему?» — спросил я.  -> одна фраза
    merged: list[str] = []
    for p in pieces:
        if merged and (p.startswith(("—", "–", "-")) or p[:1].islower()):
            merged[-1] += " " + p
        else:
            merged.append(p)

    default_pause = float(cfg["pauses"].get("between_phrases", 0.5))
    special = cfg["pauses"].get("before", {}) or {}
    phrases = [{"text": p, "pause_before": default_pause} for p in merged]

    for trig, pause in special.items():
        tn = trig.lower().replace("ё", "е")
        out = []
        for ph in phrases:
            low = ph["text"].lower().replace("ё", "е")
            k = low.find(tn)
            if k > 0:
                # оставляем открывающую кавычку у второй части
                cut = k
                while cut > 0 and ph["text"][cut - 1] in "«\"“„ ":
                    cut -= 1
                a, b = ph["text"][:cut].strip(), ph["text"][cut:].strip()
                if a:
                    out.append({"text": a, "pause_before": ph["pause_before"]})
                out.append({"text": b, "pause_before": float(pause)})
            else:
                if k == 0:
                    ph["pause_before"] = float(pause)
                out.append(ph)
        phrases = out
    if phrases:
        phrases[0]["pause_before"] = 0.0
    return phrases


# --------------------------------------------------------------------------- #
#  Озвучка (edge-tts) + тайминги слов (WordBoundary)
# --------------------------------------------------------------------------- #
async def _tts_one(edge_tts, text: str, voice: dict, cache: Path) -> tuple[Path, list]:
    key = hashlib.sha1(json.dumps([text, voice], ensure_ascii=False).encode()).hexdigest()[:20]
    mp3, js = cache / f"{key}.mp3", cache / f"{key}.json"
    if mp3.exists() and js.exists() and mp3.stat().st_size > 0:
        return mp3, json.loads(js.read_text(encoding="utf-8"))
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
    last_err = None
    for attempt in range(8):
        try:
            comm = edge_tts.Communicate(
                text, voice["name"], rate=voice.get("rate", "+0%"),
                pitch=voice.get("pitch", "+0Hz"), volume=voice.get("volume", "+0%"),
                boundary="WordBoundary", proxy=proxy)
            audio, words = bytearray(), []
            async for ch in comm.stream():
                if ch["type"] == "audio":
                    audio += ch["data"]
                elif ch["type"] == "WordBoundary":
                    words.append({"text": ch["text"],
                                  "start": ch["offset"] / 1e7,
                                  "end": (ch["offset"] + ch["duration"]) / 1e7})
            if not audio or not words:
                raise RuntimeError("пустой ответ TTS")
            mp3.write_bytes(bytes(audio))
            js.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
            return mp3, words
        except Exception as e:  # сеть / сервис иногда отвечает пустотой — повторяем
            last_err = e
            await asyncio.sleep(1.0 + attempt * 1.5)
    raise RuntimeError(f"edge-tts не смог озвучить «{text}»: {last_err}")


def synthesize(phrases: list[dict], voice: dict, cache: Path) -> None:
    edge_tts = ensure_edge_tts()
    cache.mkdir(parents=True, exist_ok=True)

    async def run():
        for i, ph in enumerate(phrases):
            ph["mp3"], ph["wb"] = await _tts_one(edge_tts, ph["text"], voice, cache)
            log(f"  озвучка {i + 1}/{len(phrases)}: {ph['text']}")

    asyncio.run(run())


def decode_audio(path: Path, tempo: float = 1.0) -> np.ndarray:
    af = ["-af", f"atempo={tempo:.4f}"] if abs(tempo - 1) > 1e-3 else []
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), *af, "-f", "f32le", "-ac", "1",
         "-ar", str(SR), "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def trim_silence(x: np.ndarray, words: list, thr_db: float = -45) -> tuple[np.ndarray, float]:
    """Обрезаем тишину по краям фразы, чтобы паузы были ровно заданными."""
    win = int(0.01 * SR)
    n = len(x) // win
    if n == 0:
        return x, 0.0
    e = np.sqrt(np.mean(x[:n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    loud = np.where(20 * np.log10(e) > thr_db)[0]
    if not len(loud):
        return x, 0.0
    s = max(0, loud[0] * win - int(0.03 * SR))
    end = min(len(x), (loud[-1] + 1) * win + int(0.08 * SR))
    if words:  # никогда не режем внутри слов
        s = min(s, int(max(0.0, words[0]["start"] - 0.02) * SR))
        end = max(end, min(len(x), int((words[-1]["end"] + 0.05) * SR)))
    return x[s:end], s / SR


def align_display(phrase_text: str, wb: list) -> list[dict]:
    """Сопоставляем слова из WordBoundary с исходным текстом, чтобы на экране
    были правильные написания (дефисы, «?» и т.д.)."""
    tokens = phrase_text.split()
    tnorm = [norm_word(t) for t in tokens]
    out: list[dict] = []
    j, acc = 0, ""
    for b in wb:
        bn = norm_word(b["text"])
        if not bn:
            continue
        if out and out[-1]["tok_norm"] != acc and out[-1]["tok_norm"].startswith(acc + bn):
            acc += bn                       # «чьё» + «то» -> «чьё-то»
            out[-1]["end"] = b["end"]
            continue
        k, found = j, -1
        while k < len(tokens) and k < j + 4:
            tn = tnorm[k]
            if tn and (tn == bn or tn.startswith(bn) or bn.startswith(tn)):
                found = k
                break
            k += 1
        if found >= 0:
            tok = tokens[found]
            disp = tok.strip("«»\"“”„()—–").rstrip(".,;:").lstrip("-")
            end_p = tok.rstrip("»\"”)")[-1:] if tok.rstrip("»\"”)") else ""
            out.append({"text": disp or b["text"], "tok_norm": tnorm[found],
                        "start": b["start"], "end": b["end"],
                        "end_punct": end_p, "brk": tok[-1:] in ",:;—»" or end_p in ",:;"})
            j = found + 1
        else:
            out.append({"text": b["text"], "tok_norm": bn, "start": b["start"],
                        "end": b["end"], "end_punct": "", "brk": False})
        acc = bn
    return out


# --------------------------------------------------------------------------- #
#  Таймлайн
# --------------------------------------------------------------------------- #
def build_timeline(phrases: list[dict], cfg: dict) -> dict:
    tcfg = cfg["timing"]
    intro = float(tcfg.get("title_seconds", 1.5))
    outro = float(tcfg.get("outro_seconds", 1.5))
    tmin, tmax = float(tcfg.get("min_seconds", 45)), float(tcfg.get("max_seconds", 60))
    tail = 0.45

    def layout(tempo: float, pause_scale: float):
        clips, t = [], intro
        words: list[dict] = []
        for pi, ph in enumerate(phrases):
            x = decode_audio(ph["mp3"], tempo)
            wb = [{"text": w["text"], "start": w["start"] / tempo, "end": w["end"] / tempo}
                  for w in ph["wb"]]
            x, cut = trim_silence(x, wb)
            if pi > 0:
                p = ph["pause_before"]
                t += p if p > 0.9 else p * pause_scale
            for w in align_display(ph["text"], wb):
                w.update(start=w["start"] - cut + t, end=w["end"] - cut + t, phrase=pi)
                words.append(w)
            clips.append((t, x))
            t += len(x) / SR
        return clips, words, t

    tempo, pscale = 1.0, 1.0
    clips, words, vend = layout(tempo, pscale)
    total = vend + tail + outro
    if total > tmax:
        # 1) сокращаем обычные паузы (но не меньше 0.3 с)
        n_norm = sum(1 for p in phrases[1:] if p["pause_before"] <= 0.9)
        base = cfg["pauses"].get("between_phrases", 0.5)
        if n_norm and base > 0.3:
            need = total - tmax + 0.2
            pscale = max(0.3 / base, 1 - need / (n_norm * base))
            clips, words, vend = layout(tempo, pscale)
            total = vend + tail + outro
        # 2) слегка ускоряем голос
        if total > tmax:
            speech = sum(len(x) for _, x in clips) / SR
            tempo = min(1.25, speech / max(1.0, speech - (total - tmax + 0.2)))
            log(f"  история длинная — ускоряю голос x{tempo:.3f}")
            clips, words, vend = layout(tempo, pscale)
            total = vend + tail + outro
    if total < tmin:
        tail += tmin - total
        total = tmin
    return {"intro": intro, "outro": outro, "voice_end": vend, "total": total,
            "clips": clips, "words": words, "tail": tail}


def find_phrase(words: list[dict], phrase: str) -> list[tuple[int, int]]:
    """Все вхождения фразы в списке слов -> [(i_first, i_last)]."""
    target = norm_word(phrase)
    if not target:
        return []
    joined, owner = "", []
    for i, w in enumerate(words):
        n = norm_word(w["text"])
        joined += n
        owner += [i] * len(n)
    res, k = [], joined.find(target)
    while k >= 0:
        i0, i1 = owner[k], owner[k + len(target) - 1]
        if k == 0 or owner[k - 1] != i0:     # совпадение с начала слова
            res.append((i0, i1))
        k = joined.find(target, k + 1)
    return res


def resolve_events(words: list[dict], cfg: dict) -> list[dict]:
    evs = []
    for e in cfg.get("events", []):
        hits = find_phrase(words, e["trigger"])
        if not hits:
            log(f"  событие «{e['trigger']}» не найдено в тексте — пропускаю")
            continue
        i0, i1 = hits[0]
        evs.append({**e, "t": words[i0]["start"], "t_end": words[i1]["end"]})
    evs.sort(key=lambda e: e["t"])
    return evs


# --------------------------------------------------------------------------- #
#  Звук: всё синтезируется numpy
# --------------------------------------------------------------------------- #
def band_noise(n: int, lo: float, hi: float, rng, soft: float = 0.15) -> np.ndarray:
    x = rng.standard_normal(n)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    lo_w, hi_w = max(lo * soft, 1.0), max(hi * soft, 1.0)
    m = np.clip((f - (lo - lo_w)) / (2 * lo_w), 0, 1) * np.clip(((hi + hi_w) - f) / (2 * hi_w), 0, 1)
    y = np.fft.irfft(X * m, n)
    return y / (np.max(np.abs(y)) + 1e-9)


def env_ad(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-np.maximum(t - attack, 0) / max(decay, 1e-4))


def sfx_hum(n: int, rng) -> np.ndarray:
    t = np.arange(n) / SR
    wob = 1 + 0.12 * np.sin(2 * np.pi * 0.23 * t) + 0.05 * np.sin(2 * np.pi * 1.7 * t + 1.0)
    tone = (0.55 * np.sin(2 * np.pi * 50 * t) + 0.45 * np.sin(2 * np.pi * 100 * t + 0.4)
            + 0.30 * np.sin(2 * np.pi * 150 * t + 1.1) + 0.18 * np.sin(2 * np.pi * 200 * t + 2.0)
            + 0.10 * np.sin(2 * np.pi * 300 * t + 0.7) + 0.05 * np.sin(2 * np.pi * 450 * t))
    rumble = band_noise(n, 25, 220, rng)
    air = band_noise(n, 300, 1400, rng)
    y = tone * wob * 0.6 + rumble * 0.55 + air * 0.06
    return y.astype(np.float32)


def sfx_click(rng) -> np.ndarray:
    n = int(0.25 * SR)
    y = np.zeros(n)
    k = int(0.004 * SR)
    y[:k] += band_noise(k * 4, 1500, 9000, rng)[:k] * env_ad(k, 0.0003, 0.0012)
    t = np.arange(n) / SR
    y += 0.8 * np.sin(2 * np.pi * (140 - 60 * t) * t) * env_ad(n, 0.001, 0.025)
    o = int(0.045 * SR)
    y[o:o + k] += 0.5 * band_noise(k * 4, 2000, 8000, rng)[:k] * env_ad(k, 0.0003, 0.001)
    return y / np.max(np.abs(y)) * db_to_amp(-7)


def sfx_breath(rng, length: float = 5.2) -> np.ndarray:
    n = int(length * SR)
    y = np.zeros(n)
    pattern = [(0.0, 1.25, "in"), (1.45, 1.55, "out"), (3.2, 1.0, "in"), (4.25, 0.95, "out")]
    for start, dur, kind in pattern:
        m = int(dur * SR)
        s = int(start * SR)
        if kind == "in":
            nz = 0.6 * band_noise(m, 700, 3200, rng) + 0.4 * band_noise(m, 2500, 6000, rng)
            ph = np.linspace(0, 1, m)
            env = np.sin(np.pi * ph) ** 1.5 * (0.6 + 0.4 * ph)
        else:
            nz = 0.7 * band_noise(m, 250, 1600, rng) + 0.3 * band_noise(m, 1200, 3500, rng)
            ph = np.linspace(0, 1, m)
            env = np.sin(np.pi * ph ** 0.6) ** 2
        seg = nz * env
        e = min(m, n - s)
        y[s:s + e] += seg[:e]
    y = y / (np.max(np.abs(y)) + 1e-9)
    return y.astype(np.float32)


def sfx_squelch(rng) -> np.ndarray:
    n = int(0.55 * SR)
    y = np.zeros(n)
    t = np.arange(n) / SR
    grains = [(0.00, 0.09, 260, 900, 1.0), (0.07, 0.07, 600, 1700, 0.8),
              (0.13, 0.11, 350, 1200, 0.9), (0.24, 0.06, 900, 2400, 0.5),
              (0.29, 0.10, 220, 700, 0.6)]
    for st, d, lo, hi, a in grains:
        m = int(d * SR)
        s = int(st * SR)
        g = band_noise(m, lo, hi, rng, soft=0.4) * env_ad(m, 0.004, d / 3.5)
        # «булька»: короткий тон с падающей частотой
        tt = np.arange(m) / SR
        f0 = (lo + hi) / 2
        g += 0.5 * np.sin(2 * np.pi * (f0 * 0.6 - f0 * 1.5 * tt) * tt) * env_ad(m, 0.002, d / 4)
        e = min(m, n - s)
        y[s:s + e] += a * g[:e]
    y += 0.7 * np.sin(2 * np.pi * (170 - 140 * t) * t) * env_ad(n, 0.003, 0.05)  # низкий «плюх»
    y = np.tanh(1.6 * y)
    return y / np.max(np.abs(y)) * db_to_amp(-5)


def sfx_ding() -> np.ndarray:
    n = int(2.4 * SR)
    t = np.arange(n) / SR
    y = np.zeros(n)
    f0 = 1318.5
    for ratio, amp, dec in [(1.0, 1.0, 0.9), (2.0, 0.35, 0.45), (2.76, 0.22, 0.3),
                            (5.4, 0.08, 0.12), (0.5, 0.15, 0.7)]:
        y += amp * np.sin(2 * np.pi * f0 * ratio * t) * env_ad(n, 0.002, dec)
    y *= 1 + 0.03 * np.sin(2 * np.pi * 5 * t)
    return y / np.max(np.abs(y)) * db_to_amp(-9)


def mix_audio(tl: dict, events: list[dict], cfg: dict, rng) -> tuple[np.ndarray, dict]:
    total = tl["total"]
    n = int(math.ceil(total * SR)) + SR // 10
    acfg = cfg["audio"]

    voice = np.zeros(n, dtype=np.float32)
    for t0, x in tl["clips"]:
        s = int(t0 * SR)
        e = min(n, s + len(x))
        voice[s:e] += x[:e - s]
    # нормализация голоса по RMS активной речи
    win = int(0.05 * SR)
    m = len(voice) // win
    frames = voice[:m * win].reshape(m, win)
    fr = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    active = frames[20 * np.log10(fr) > -40].ravel()
    cur = rms_db(active) if len(active) else -30
    gain = db_to_amp(acfg.get("voice_rms_db", -14) - cur)
    peak = np.max(np.abs(voice)) + 1e-9
    gain = min(gain, 0.97 / peak * 1.25)
    voice *= gain
    voice = np.where(np.abs(voice) > 0.9, np.sign(voice) * (0.9 + 0.1 * np.tanh((np.abs(voice) - 0.9) / 0.1)), voice)
    mask = np.repeat(20 * np.log10(fr) > -40, win)
    voice_db = rms_db(voice[:len(mask)][mask]) if mask.any() else rms_db(voice)

    # фоновый «бед» (гул + дыхание) — не громче голоса минус запас
    bed_db = min(acfg.get("hum_db", -28), voice_db - acfg.get("voice_over_bed_min_db", 12) - 0.5)

    hum = sfx_hum(n, rng)
    hum *= db_to_amp(bed_db) / (10 ** (rms_db(hum) / 20))
    henv = np.ones(n, dtype=np.float32)
    fi = int(0.6 * SR)
    henv[:fi] = np.linspace(0, 1, fi)
    sfx = np.zeros(n, dtype=np.float32)
    bed_extra = np.zeros(n, dtype=np.float32)

    def place(buf, clip, t):
        s = int(t * SR)
        if s >= n:
            return
        e = min(n, s + len(clip))
        buf[s:e] += clip[:e - s]

    for ev in events:
        t = ev["t"]
        s = int(t * SR)
        if ev.get("hum") == "off":
            k = int(0.008 * SR)  # резкий обрыв
            henv[s:s + k] *= np.linspace(1, 0, min(k, n - s))
            henv[s + k:] = 0
        elif ev.get("hum") == "on":
            k = int(0.35 * SR)
            ramp = np.linspace(0, 1, min(k, n - s)) ** 0.5
            henv[s:s + len(ramp)] = ramp
            henv[s + len(ramp):] = 1
        kind = ev.get("sfx")
        if kind == "click":
            place(sfx, sfx_click(rng), t - 0.01)
        elif kind == "breath":
            br = sfx_breath(rng)
            br *= db_to_amp(bed_db + 2) / (10 ** (rms_db(br[br != 0]) / 20))
            place(bed_extra, br, t)
        elif kind == "squelch":
            place(sfx, sfx_squelch(rng), t + 0.02)
        elif kind == "ding":
            place(sfx, sfx_ding(), t - 0.05)

    fo = int(0.8 * SR)
    henv[-fo:] *= np.linspace(1, 0, fo)
    bed = hum * henv + bed_extra
    out = voice + bed + sfx
    pk = np.max(np.abs(out))
    if pk > 0.84:          # потолок ≈ -1.5 dBFS (запас под AAC)
        out *= 0.84 / pk
    stats = {"voice_db": voice_db, "hum_db": bed_db,
             "margin": voice_db - bed_db}
    return out[:int(total * SR)], stats


def write_wav(path: Path, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    st = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(st.tobytes())


# --------------------------------------------------------------------------- #
#  Шрифты и текст
# --------------------------------------------------------------------------- #
FONT_DIRS = [ROOT / "fonts", Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
             Path.home() / ".fonts", Path.home() / ".local/share/fonts",
             Path("/Library/Fonts"), Path.home() / "Library/Fonts",
             Path("C:/Windows/Fonts")]


def find_font(names: list[str]) -> str:
    for name in names:
        p = Path(name)
        if p.is_file():
            return str(p)
        for d in FONT_DIRS:
            if not d.exists():
                continue
            for ext in (".ttf", ".otf"):
                hits = list(d.rglob(name + ext))
                if hits:
                    return str(hits[0])
        if shutil.which("fc-match"):
            fam = re.sub(r"[-_]", " ", name)
            r = subprocess.run(["fc-match", "-f", "%{file}", fam], capture_output=True, text=True)
            f = r.stdout.strip()
            if f and Path(f).stem.lower().replace(" ", "").startswith(name.lower().split("-")[0]):
                return f
    sys.exit("Не найден жирный шрифт. Положите Inter-ExtraBold.ttf или DejaVuSans-Bold.ttf в папку fonts/.")


class Fonts:
    def __init__(self, path: str):
        self.path = path
        self.cache: dict[int, ImageFont.FreeTypeFont] = {}

    def get(self, size: float) -> ImageFont.FreeTypeFont:
        s = max(8, int(round(size)))
        if s not in self.cache:
            self.cache[s] = ImageFont.truetype(self.path, s)
        return self.cache[s]


def wrap_text(text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for wd in text.split():
        test = (cur + " " + wd).strip()
        if font.getlength(test) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def render_title(title: str, cfg: dict, fonts: Fonts, upper: bool) -> Image.Image:
    tc = cfg["title"]
    size = tc.get("size", 112)
    text = title.upper() if upper else title
    font = fonts.get(size)
    while True:
        lines = wrap_text(text, font, 940)
        if len(lines) <= 4 or size < 60:
            break
        size -= 8
        font = fonts.get(size)
    lh = int(size * 1.18)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    block_h = lh * len(lines)
    y0 = H // 2 - block_h // 2
    # тёмная подложка
    pad = 50
    d.rounded_rectangle((40, y0 - pad, W - 40, y0 + block_h + pad), radius=36, fill=(0, 0, 0, 120))
    accent = hex_rgb(tc.get("accent_color", "#FF2B2B"))
    d.rectangle((W // 2 - 90, y0 - pad + 18, W // 2 + 90, y0 - pad + 26), fill=accent + (255,))
    in_quote = False
    for li, line in enumerate(lines):
        y = y0 + li * lh
        lw = font.getlength(line)
        x = (W - lw) / 2
        for wi, wd in enumerate(line.split(" ")):
            if "«" in wd or "\"" in wd[:1]:
                in_quote = True
            col = accent if in_quote else hex_rgb(tc.get("color", "#FFFFFF"))
            d.text((x, y), wd, font=font, fill=col + (255,), stroke_width=8, stroke_fill=(0, 0, 0, 255))
            x += font.getlength(wd + " ")
            if "»" in wd or (wd.endswith("\"") and len(wd) > 1):
                in_quote = False
    return img


def render_outro(cfg: dict, fonts: Fonts, upper: bool) -> Image.Image:
    oc = cfg["outro"]
    lines = [l.upper() if upper else l for l in oc.get("lines", ["Часть 2?", "Подписывайся"])]
    sizes = [130] + [96] * (len(lines) - 1)
    fs = [fonts.get(s) for s in sizes]
    widths = [f.getlength(l) for f, l in zip(fs, lines)]
    pw = int(min(W - 80, max(widths) + 120))
    lh = [int(s * 1.2) for s in sizes]
    ph = sum(lh) + 110
    img = Image.new("RGBA", (pw + 40, ph + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20 + 10, 20 + 14, 20 + pw + 10, 20 + ph + 14), radius=46, fill=(0, 0, 0, 150))
    d.rounded_rectangle((20, 20, 20 + pw, 20 + ph), radius=46,
                        fill=hex_rgb(oc.get("plate_color", "#E0262B")) + (255,),
                        outline=(255, 255, 255, 255), width=6)
    y = 20 + 55
    for f, l, w_, h_ in zip(fs, lines, widths, lh):
        d.text((20 + (pw - w_) / 2, y), l, font=f, fill=hex_rgb(oc.get("text_color", "#FFFFFF")) + (255,),
               stroke_width=5, stroke_fill=(0, 0, 0, 255))
        y += h_
    return img


# --------------------------------------------------------------------------- #
#  Субтитры: группировка по 3–4 слова
# --------------------------------------------------------------------------- #
SHORT_WORDS = {"в", "во", "и", "а", "у", "на", "по", "не", "с", "со", "к", "ко", "о", "об", "из", "за", "до", "от", "что", "как"}


def make_chunks(words: list[dict], cfg: dict, hl_idx: set) -> list[dict]:
    mx = int(cfg["subtitles"].get("max_words", 4))
    chunks: list[list[int]] = []
    # по фразам, DP по местам разреза
    by_phrase: dict[int, list[int]] = {}
    for i, w in enumerate(words):
        by_phrase.setdefault(w["phrase"], []).append(i)
    for idxs in by_phrase.values():
        n = len(idxs)
        best = [math.inf] * (n + 1)
        prev = [0] * (n + 1)
        best[0] = 0
        for e in range(1, n + 1):
            for s in range(max(0, e - mx), e):
                size = e - s
                c = {1: 6.0, 2: 2.0}.get(size, 0.0)
                last = words[idxs[e - 1]]
                if e < n:
                    if last["brk"]:
                        c -= 1.5
                    if norm_word(last["text"]) in SHORT_WORDS:
                        c += 3.0
                    if idxs[e - 1] in hl_idx and idxs[e] in hl_idx:
                        c += 20.0
                if best[s] + c < best[e]:
                    best[e], prev[e] = best[s] + c, s
        cuts, e = [], n
        while e > 0:
            cuts.append((prev[e], e))
            e = prev[e]
        for s, e in reversed(cuts):
            chunks.append(idxs[s:e])
    # объединяем совсем короткие соседние фразы («Я замер. На ком?»)
    merged: list[list[int]] = []
    for c in chunks:
        if merged:
            p = merged[-1]
            gap = words[c[0]]["start"] - words[p[-1]]["end"]
            if (len(p) + len(c) <= mx and min(len(p), len(c)) <= 2 and gap < 0.85
                    and words[p[-1]]["phrase"] != words[c[0]]["phrase"]):
                merged[-1] = p + c
                continue
        merged.append(c)
    out = []
    for k, c in enumerate(merged):
        st = words[c[0]]["start"] - 0.05
        last_end = words[c[-1]]["end"]
        if k + 1 < len(merged):
            nxt = words[merged[k + 1][0]]["start"] - 0.05
            en = nxt if nxt - last_end < 0.9 else last_end + 0.35
        else:
            en = last_end + 0.45
        out.append({"idx": c, "start": st, "end": en})
    return out


# --------------------------------------------------------------------------- #
#  Фон
# --------------------------------------------------------------------------- #
def vignette_map(strength: float = 0.75) -> np.ndarray:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = (xx - W / 2) / (W / 2)
    ny = (yy - H / 2) / (H / 2)
    r = np.sqrt(nx ** 2 * 1.0 + ny ** 2 * 0.55)
    v = 1 - strength * np.clip(r - 0.35, 0, None) ** 1.6
    return np.clip(v, 0.1, 1)[..., None].astype(np.float32)


class GeneratedBG:
    """Тёмный сине-серый градиент + узкая полоса света по центру (щель дверей лифта)."""

    def __init__(self, cfg: dict, fps: int, rng):
        bc = cfg["background"]
        top = np.array(hex_rgb(bc.get("gradient_top", "#26303d")), np.float32)
        bot = np.array(hex_rgb(bc.get("gradient_bottom", "#07090c")), np.float32)
        slit_c = np.array(hex_rgb(bc.get("slit_color", "#d6e6ff")), np.float32)
        y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
        x = np.linspace(-1, 1, W, dtype=np.float32)[None, :, None]
        grad = top * (1 - y ** 0.8) + bot * y ** 0.8
        grad = grad * (1 - 0.35 * np.abs(x) ** 1.5)
        # «металл» дверей: лёгкие вертикальные штрихи
        streak = rng.standard_normal(W).astype(np.float32)
        streak = np.convolve(streak, np.ones(9) / 9, mode="same")[None, :, None]
        base = grad * (1 + 0.05 * streak)
        # стыки панелей
        for px in (W * 0.18, W * 0.82):
            base[:, int(px) - 2:int(px) + 2] *= 0.7
        xs = np.arange(W, dtype=np.float32)[None, :, None] - W / 2
        yprof = np.clip(np.sin(np.pi * np.linspace(0.02, 0.98, H, dtype=np.float32)), 0, 1) ** 0.5
        yprof = yprof[:, None, None]
        core = np.exp(-(xs / 3.5) ** 2)
        glow = np.exp(-(xs / 38) ** 2) * 0.35 + np.exp(-(xs / 160) ** 2) * 0.12
        self.slit = (core + glow) * yprof * slit_c
        self.base = base * vignette_map(0.8)
        self.slit *= vignette_map(0.4)
        self.grain = [(rng.standard_normal((H // 2, W // 2, 1)) * 5).astype(np.float32) for _ in range(6)]
        self.fps = fps
        self.rng = rng
        self.flick = rng.uniform(0.9, 1.0, 10000)

    def frame(self, i: int, t: float) -> np.ndarray:
        k = 0.88 + 0.12 * self.flick[i % len(self.flick)] * (0.95 + 0.05 * math.sin(t * 3.1))
        f = self.base + self.slit * k
        g = self.grain[i % len(self.grain)]
        f[0::2, 0::2] += g
        f[1::2, 1::2] += g
        return f

    def close(self):
        pass


class VideoBG:
    """Случайное видео из bg/: зацикливание, центр 9:16, -35% яркости, виньетка."""

    def __init__(self, path: Path, total: float, fps: int, dim: float):
        vf = (f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={W}:{H}:flags=lanczos,"
              f"fps={fps},format=rgb24,"
              f"lutrgb=r='val*{1 - dim:.3f}':g='val*{1 - dim:.3f}':b='val*{1 - dim:.3f}',"
              f"vignette=angle=PI/4.2")
        cmd = ["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(path),
               "-t", f"{total + 1:.3f}", "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=W * H * 3 * 2)
        self.last = np.zeros((H, W, 3), np.float32)

    def frame(self, i: int, t: float) -> np.ndarray:
        buf = self.proc.stdout.read(W * H * 3)
        if len(buf) == W * H * 3:
            self.last = np.frombuffer(buf, np.uint8).reshape(H, W, 3).astype(np.float32)
        return self.last.copy()

    def close(self):
        try:
            self.proc.stdout.close()
            self.proc.kill()
        except Exception:
            pass


def pick_background(cfg: dict, total: float, fps: int, rng):
    d = ROOT / cfg["background"].get("dir", "bg")
    if not d.is_absolute():
        d = ROOT / d
    files = sorted(p for p in d.glob("*") if p.suffix in VIDEO_EXT) if d.is_dir() else []
    if files:
        f = rng.choice(files)
        log(f"Фон: видео {f.name}")
        return VideoBG(f, total, fps, float(cfg["background"].get("video_dim", 0.35))), True
    log("Фон: папка bg/ пуста или отсутствует — генерирую тёмный градиент с полосой света")
    return GeneratedBG(cfg, fps, np.random.default_rng(7)), False


# --------------------------------------------------------------------------- #
#  Свет: яркость кадра во времени
# --------------------------------------------------------------------------- #
def light_curve(events: list[dict], dark: float):
    evs = [e for e in events if e.get("light")]

    def f(t: float) -> tuple[float, float]:
        level, flash = 1.0, 0.0
        for e in evs:
            dt = t - e["t"]
            if dt < 0:
                break
            kind = e["light"]
            if kind == "off":
                level = 1 - (1 - dark) * min(1.0, dt / 0.06)
            elif kind == "on":
                level = 1.0
            elif kind == "flash":
                level = 1.0
                flash = 0.85 * math.exp(-dt / 0.16) if dt < 1.2 else 0.0
            elif kind == "flicker" and level > 0.5:
                pat = [(0.00, 0.35), (0.07, 1.0), (0.14, 0.25), (0.22, 0.85), (0.30, 0.45), (0.40, 1.0)]
                v = 1.0
                for st, val in pat:
                    if dt >= st:
                        v = val
                level = v if dt < 0.45 else 1.0
        return level, flash

    return f


# --------------------------------------------------------------------------- #
#  Рендер
# --------------------------------------------------------------------------- #
def draw_subtitles(img: Image.Image, chunk: dict, words: list[dict], t: float, cfg: dict,
                   fonts: Fonts, hl: dict) -> None:
    sc = cfg["subtitles"]
    size = sc.get("size", 104)
    upper = sc.get("uppercase", True)
    white = hex_rgb(sc.get("color", "#FFFFFF"))
    red = hex_rgb(sc.get("active_color", "#FF2B2B"))
    stroke_c = hex_rgb(sc.get("stroke_color", "#000000"))
    sw = int(sc.get("stroke_width", 9))
    pulse_amt = float(sc.get("pulse", 0.06))
    max_w = int(sc.get("max_width", 960))

    items = []
    for wi in chunk["idx"]:
        w = words[wi]
        txt = w["text"].upper() if upper else w["text"]
        if w.get("show_punct"):
            txt += w["show_punct"]
        base_scale, col = 1.0, white
        if wi in hl:
            base_scale, col = hl[wi]
        items.append([wi, txt, base_scale, col])

    # раскладка по строкам с базовыми размерами
    # зазор с запасом, чтобы увеличенное активное слово не наезжало на соседей
    space = fonts.get(size).getlength(" ") + size * 0.16
    lines, cur, cur_w = [], [], 0.0
    for it in items:
        wlen = fonts.get(size * it[2]).getlength(it[1])
        add = wlen + (space if cur else 0)
        if cur and cur_w + add > max_w:
            lines.append((cur, cur_w))
            cur, cur_w = [], 0.0
            add = wlen
        cur.append((it, wlen))
        cur_w += add
    if cur:
        lines.append((cur, cur_w))

    lh = size * 1.22
    cy = H * float(sc.get("y", 0.62))
    y0 = cy - lh * len(lines) / 2
    d = ImageDraw.Draw(img)
    for li, (row, row_w) in enumerate(lines):
        x = (W - row_w) / 2
        yc = y0 + li * lh + lh / 2
        for (wi, txt, bscale, col), wlen in row:
            w = words[wi]
            scale = bscale
            colr = col
            if w["start"] - 0.03 <= t < max(w["end"], w["start"] + 0.12):
                dt = t - w["start"]
                pop = 0.07 * math.exp(-max(dt, 0) / 0.11)
                osc = pulse_amt * (0.5 + 0.5 * math.sin(2 * math.pi * 3.2 * dt))
                scale = bscale * (1 + pop + osc)
                if wi not in hl:
                    colr = red
                else:   # подсветка жёлтым, чуть ярче во время произнесения
                    colr = tuple(min(255, int(c * 1.0 + 25)) for c in col)
            f = fonts.get(size * scale)
            tw = f.getlength(txt)
            cx = x + wlen / 2
            # якорь «mm» — центр по горизонтали и вертикали
            d.text((cx + 4, yc + 7), txt, font=f, fill=(0, 0, 0), anchor="mm",
                   stroke_width=sw, stroke_fill=(0, 0, 0))
            d.text((cx, yc), txt, font=f, fill=colr, anchor="mm",
                   stroke_width=sw, stroke_fill=stroke_c)
            x += wlen + space
            _ = tw


def render(tl: dict, events: list[dict], cfg: dict, title: str, fps: int, audio_path: Path,
           out_path: Path, duration: float, rng) -> bool:
    sc = cfg["subtitles"]
    font_path = find_font(sc.get("fonts", ["Inter-ExtraBold", "DejaVuSans-Bold"]))
    log(f"Шрифт: {font_path}")
    fonts = Fonts(font_path)
    upper = sc.get("uppercase", True)
    words = tl["words"]

    # подсветки
    hl: dict[int, tuple[float, tuple]] = {}
    for h in cfg.get("highlights", []):
        for i0, i1 in find_phrase(words, h["phrase"]):
            for i in range(i0, i1 + 1):
                hl[i] = (float(h.get("scale", 1.15)), hex_rgb(h.get("color", "#FFD400")))
    chunks = make_chunks(words, cfg, set(hl))
    # пунктуация в конце фразы, если на экране склеены две фразы
    for c in chunks:
        for a, b in zip(c["idx"], c["idx"][1:]):
            if words[a]["phrase"] != words[b]["phrase"] and words[a]["end_punct"] in ".!?…":
                words[a]["show_punct"] = words[a]["end_punct"] if words[a]["end_punct"] != "." else "."

    title_img = render_title(title, cfg, fonts, upper)
    outro_img = render_outro(cfg, fonts, upper)
    intro = tl["intro"]
    outro_start = tl["total"] - tl["outro"]

    bg, is_video = pick_background(cfg, duration, fps, rng)
    light = light_curve(events, float(cfg["background"].get("dark_level", 0.15)))

    nframes = int(round(duration * fps))
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", str(audio_path),
           "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-g", str(fps * 2),
           "-c:a", "aac", "-b:a", "192k", "-ar", str(SR),
           "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out_path)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    ci = 0
    t_start = time.time()
    try:
        for i in range(nframes):
            t = i / fps
            f = bg.frame(i, t)
            level, flash = light(t)
            if level != 1.0:
                f *= level
            if flash > 0:
                f = f * (1 - flash) + 245 * flash
            np.clip(f, 0, 255, out=f)
            img = Image.fromarray(f.astype(np.uint8), "RGB")

            # заголовок
            if t < intro:
                a = min(1.0, t / 0.15) * min(1.0, max(0.0, (intro - t) / 0.35))
                if a > 0:
                    ti = title_img
                    if a < 1:
                        ti = title_img.copy()
                        ti.putalpha(title_img.getchannel("A").point(lambda v, a=a: int(v * a)))
                    img.paste(ti, (0, 0), ti)

            # субтитры
            if intro - 0.05 <= t < outro_start:
                while ci < len(chunks) and chunks[ci]["end"] <= t:
                    ci += 1
                if ci < len(chunks) and chunks[ci]["start"] <= t:
                    draw_subtitles(img, chunks[ci], words, t, cfg, fonts, hl)

            # финальная плашка
            if t >= outro_start:
                dt = t - outro_start
                s = 0.75 + 0.25 * min(1.0, dt / 0.18) + 0.06 * math.sin(min(1.0, dt / 0.35) * math.pi)
                oi = outro_img
                if abs(s - 1) > 0.005:
                    oi = outro_img.resize((int(outro_img.width * s), int(outro_img.height * s)),
                                          Image.BILINEAR)
                img.paste(oi, ((W - oi.width) // 2, int(H * 0.5 - oi.height / 2)), oi)

            enc.stdin.write(img.tobytes())
            if i % (fps * 5) == 0 and i:
                el = time.time() - t_start
                log(f"  кадр {i}/{nframes}  ({i / el:.1f} к/с, осталось ~{(nframes - i) / (i / el):.0f} с)")
    finally:
        bg.close()
        enc.stdin.close()
        enc.wait()
    if enc.returncode != 0:
        sys.exit("ffmpeg завершился с ошибкой при сборке видео.")
    return is_video


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Вертикальное видео-история с озвучкой и субтитрами")
    ap.add_argument("story", nargs="?", default="story.txt", help="файл истории (1-я строка — заголовок)")
    ap.add_argument("-o", "--output", default=None, help="выходной файл (по умолчанию output.mp4)")
    ap.add_argument("--fps", type=int, default=30, choices=[24, 25, 30, 50, 60])
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--preview", type=float, default=0, help="отрендерить только первые N секунд")
    ap.add_argument("--seed", type=int, default=None, help="зерно случайности (выбор фона)")
    args = ap.parse_args()

    require_ffmpeg()
    cfg = load_config(Path(args.config))
    story_path = Path(args.story)
    if not story_path.exists():
        sys.exit(f"Файл истории не найден: {story_path}")
    out = Path(args.output or ("output_preview.mp4" if args.preview else "output.mp4"))
    rng = random.Random(args.seed)
    nrng = np.random.default_rng(args.seed if args.seed is not None else 12345)

    title, body = read_story(story_path)
    phrases = split_phrases(body, cfg)
    log(f"Заголовок: {title}")
    log(f"Фраз: {len(phrases)}. Озвучка {cfg['voice']['name']} ({cfg['voice'].get('rate')}, {cfg['voice'].get('pitch')})")
    synthesize(phrases, cfg["voice"], ROOT / ".cache" / "tts")

    tl = build_timeline(phrases, cfg)
    events = resolve_events(tl["words"], cfg)
    log(f"Длительность ролика: {tl['total']:.2f} с (голос до {tl['voice_end']:.2f} с)")
    for e in events:
        log(f"  событие «{e['trigger']}» в {e['t']:.2f} с")

    audio, st = mix_audio(tl, events, cfg, nrng)
    log(f"Громкость: голос {st['voice_db']:.1f} dBFS, гул {st['hum_db']:.1f} dBFS, запас {st['margin']:.1f} dB")
    duration = tl["total"] if not args.preview else min(tl["total"], args.preview)
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "mix.wav"
        write_wav(wav, audio[:int(duration * SR)])
        is_video = render(tl, events, cfg, title, args.fps, wav, out, duration, rng)
    log(f"Готово: {out.resolve()}  ({duration:.2f} с, {args.fps} fps)")
    if not is_video:
        print("\nПодсказка: положите свои фоновые видео (.mp4 / .mov) в папку bg/ — "
              "будет выбран случайный файл, зациклен и обрезан под 9:16.")


if __name__ == "__main__":
    main()
