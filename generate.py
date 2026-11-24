#!/usr/bin/env python3
"""Генератор вертикального хоррор-видео: озвучка (edge-tts) + субтитры + звук + эффекты.

    python generate.py story.txt                 -> output.mp4
    python generate.py story.txt --preview 15    -> output_preview.mp4 (первые 15 c)
    python generate.py story.txt --fps 60 -o out.mp4

Всё, что относится к конкретной истории (голос, паузы, реплики телефона, звуковые
и визуальные «якоря»), лежит в config.json — код при смене истории не меняется.
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
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1080, 1920
SR = 48000
CACHE = ROOT / "cache" / "tts"


def log(*a):
    print("[gen]", *a, flush=True)


# ----------------------------------------------------------------------------
# Текст
# ----------------------------------------------------------------------------
WORD_RE = re.compile(r"\w+(?:-\w+)*")


def norm(s):
    return " ".join(w.lower().replace("ё", "е") for w in WORD_RE.findall(s))


def split_sentences(text):
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p.strip() for p in parts if WORD_RE.search(p)]


def parse_story(path, cfg):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    lines = [l for l in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    title = lines[0].strip()
    body = " ".join(l.strip() for l in lines[1:] if l.strip())
    phone_keys = [norm(p) for p in cfg["voice"]["phone_quotes"]]

    segments = []  # (text, kind)  kind: narration | quote | phone
    pos = 0
    for m in re.finditer(r"«([^»]*)»", body):
        outside = body[pos:m.start()]
        pos = m.end()
        if WORD_RE.search(outside):
            segments.append((outside, "narration"))
        q = m.group(1).strip()
        kind = "phone" if any(norm(q).startswith(k) for k in phone_keys) else "quote"
        # авторская вставка внутри реплики: «Фраза, — сказал он. — Дальше»
        am = re.match(r"^(.*?)\s*[—–]\s*(.+?)\s*[—–]\s*(.*)$", q)
        if am and WORD_RE.search(am.group(1)) and WORD_RE.search(am.group(3)):
            segments += [(am.group(1), kind), (am.group(2), "narration"), (am.group(3), kind)]
        else:
            segments.append((q, kind))
    if WORD_RE.search(body[pos:]):
        segments.append((body[pos:], "narration"))

    chunks = []
    for text, kind in segments:
        text = re.sub(r"^[\s.,:;!?…—–-]+", "", text).strip()
        text = text.strip("—– ")
        for s in split_sentences(text):
            chunks.append({"text": s, "kind": kind,
                           "sentence_end": bool(re.search(r"[.!?…]$", s))})
    for c in chunks:
        if not c["sentence_end"] and c is chunks[-1]:
            c["sentence_end"] = True
    return title, chunks


# ----------------------------------------------------------------------------
# Озвучка
# ----------------------------------------------------------------------------
def _tts_kwargs():
    try:
        import edge_tts.communicate as ec
        ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        if ca and os.path.exists(ca):
            ec._SSL_CTX.load_verify_locations(ca)
    except Exception:
        pass
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    return {"proxy": proxy} if proxy else {}


async def _tts_once(text, voice, rate, pitch, volume, boundary):
    import edge_tts
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume,
                               boundary=boundary, **_tts_kwargs())
    audio, events = bytearray(), []
    async for ch in com.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] in ("WordBoundary", "SentenceBoundary"):
            events.append({"type": ch["type"], "offset": ch["offset"] / 1e7,
                           "duration": ch["duration"] / 1e7, "text": ch["text"]})
    return bytes(audio), events


def tts(text, voice, rate, pitch, volume, boundary, attempts=None):
    """Синтез с кэшем. Возвращает (путь к mp3, события)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(json.dumps([text, voice, rate, pitch, volume, boundary]).encode()).hexdigest()[:16]
    mp3, js = CACHE / f"{key}.mp3", CACHE / f"{key}.json"
    if mp3.exists() and js.exists():
        return mp3, json.loads(js.read_text())
    last = None
    tries = attempts or 6
    for attempt in range(tries):
        try:
            audio, events = asyncio.run(_tts_once(text, voice, rate, pitch, volume, boundary))
            if audio:
                mp3.write_bytes(audio)
                js.write_text(json.dumps(events, ensure_ascii=False))
                time.sleep(0.4)
                return mp3, events
        except Exception as e:  # noqa
            last = e
            if attempt == tries - 1 and "NoAudioReceived" in type(e).__name__:
                raise
        time.sleep(min(2.0 + attempt, 6))
    raise RuntimeError(f"edge-tts не ответил: {last}")


def synth_chunk(chunk, vcfg):
    """Синтезирует фразу и возвращает (mp3, тайминги слов, режим)."""
    v = vcfg["name"]
    args = (vcfg["rate"], vcfg["pitch"], vcfg.get("volume", "+0%"))
    words = WORD_RE.findall(chunk["text"])
    # 1) WordBoundary от основного голоса (основной путь; сервис иногда отвечает пусто — повторяем)
    try:
        mp3, ev = tts(chunk["text"], v, *args, "WordBoundary", attempts=8)
        wb = [e for e in ev if e["type"] == "WordBoundary"]
        if len(wb) == len(words):
            return mp3, [(e["offset"], e["offset"] + e["duration"]) for e in wb], "WordBoundary"
        log(f"  WordBoundary: {len(wb)} событий на {len(words)} слов — раскладываю слова сам")
    except Exception as e:
        if "NoAudioReceived" not in type(e).__name__:
            raise
        log("  WordBoundary не пришли — запасной путь (SentenceBoundary + раскладка слов)")
    # 2) SentenceBoundary от основного голоса + раскладка слов
    mp3, ev = tts(chunk["text"], v, *args, "SentenceBoundary")
    sb = [e for e in ev if e["type"] == "SentenceBoundary"]
    if sb:
        s0, s1 = sb[0]["offset"], sb[-1]["offset"] + sb[-1]["duration"]
    else:
        s0, s1 = None, None
    rel = None
    try:
        _, hev = tts(chunk["text"], vcfg["timing_helper_voice"], *args, "WordBoundary")
        hw = [e for e in hev if e["type"] == "WordBoundary"]
        if len(hw) == len(words) and hw:
            a, b = hw[0]["offset"], hw[-1]["offset"] + hw[-1]["duration"]
            rel = [((e["offset"] - a) / (b - a), (e["offset"] + e["duration"] - a) / (b - a)) for e in hw]
    except Exception:
        rel = None
    if rel is None:  # по слогам
        wts = [max(1, len(re.findall(r"[аеёиоуыэюяaeiouy]", w.lower()))) + 0.6 for w in words]
        tot, acc, rel = sum(wts), 0.0, []
        for wgt in wts:
            rel.append((acc / tot, (acc + wgt * 0.9) / tot))
            acc += wgt
    return mp3, rel, ("SentenceBoundary", s0, s1)


def decode(mp3, af=None):
    cmd = ["ffmpeg", "-v", "error", "-i", str(mp3)]
    if af:
        cmd += ["-af", af]
    cmd += ["-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, check=True, capture_output=True).stdout, np.float32).copy()


def speech_span(x, thr_db=-42):
    fr = int(SR * 0.01)
    n = len(x) // fr
    if n == 0:
        return 0, len(x)
    e = np.sqrt(np.mean(x[:n * fr].reshape(n, fr) ** 2, axis=1) + 1e-12)
    on = np.where(20 * np.log10(e) > thr_db)[0]
    if len(on) == 0:
        return 0, len(x)
    return max(0, on[0] * fr - int(0.02 * SR)), min(len(x), (on[-1] + 1) * fr + int(0.04 * SR))


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


def build_voice(chunks, cfg):
    vc = cfg["voice"]
    out = []
    for i, ch in enumerate(chunks):
        mp3, timing, mode = synth_chunk(ch, vc)
        raw = decode(mp3)
        a, b = speech_span(raw)
        words = WORD_RE.findall(ch["text"])
        if mode == "WordBoundary":
            wt = [(s - a / SR, e - a / SR) for s, e in timing]
        else:
            _, s0, s1 = mode
            if s0 is None:
                s0, s1 = a / SR, b / SR
            s0 = max(s0, a / SR)
            s1 = min(max(s1, s0 + 0.2), b / SR)
            wt = [(s0 + r0 * (s1 - s0) - a / SR, s0 + r1 * (s1 - s0) - a / SR) for r0, r1 in timing]
        speech_len = (b - a) / SR
        if ch["kind"] == "phone":
            x = decode(mp3, vc["phone_filter"])
            x = x[a:b + int(0.45 * SR)]
        else:
            x = raw[a:b]
        r = np.sqrt(np.mean(x[: int(speech_len * SR)] ** 2) + 1e-12)
        x = x * (10 ** (cfg["audio"]["voice_rms_db"] / 20) / r)
        out.append({**ch, "audio": x, "len": speech_len,
                    "words": [{"text": w, "s": max(0, s), "e": min(speech_len, e)}
                              for w, (s, e) in zip(words, wt)]})
        log(f"  фраза {i + 1}/{len(chunks)} [{ch['kind']}] {speech_len:4.1f}c  {ch['text'][:50]}")
    return out


def plan_timeline(vchunks, cfg):
    vc, dc = cfg["voice"], cfg["duration"]
    special = {norm(k): v for k, v in vc["pauses_before"].items()}
    base = []
    for i, ch in enumerate(vchunks):
        if i == 0:
            base.append(("fixed", 0.0))
            continue
        n = norm(ch["text"])
        sp = next((v for k, v in special.items() if k.startswith(n) or n.startswith(k)), None)
        if i == len(vchunks) - 1:
            sp = max(sp or 0, vc["pause_before_last_sentence"])
        if sp is not None:
            base.append(("fixed", sp))
        else:
            prev = vchunks[i - 1]
            base.append(("flex", vc["pause_after_sentence"] if prev["sentence_end"] else vc["pause_after_clause"]))
    speech = sum(c["len"] for c in vchunks)

    def total(scale, tail):
        p = sum(v if k == "fixed" else v * scale for k, v in base)
        return dc["voice_start"] + speech + p + tail + dc["plate"]

    scale, tail, tempo = 1.0, dc["tail_before_plate"], 1.0
    T = total(scale, tail)
    if T > dc["max"]:
        flex = sum(v for k, v in base if k == "flex")
        need = T - dc["max"]
        scale = max(0.55, 1 - need / flex) if flex else 1.0
        T = total(scale, tail)
        if T > dc["max"]:
            tempo = min(1.12, (speech) / (speech - (T - dc["max"]) - 0.05))
            log(f"!! ролик длиннее {dc['max']} c — ускоряю речь x{tempo:.3f}")
    elif T < dc["min"]:
        tail += dc["min"] - T
        T = total(scale, tail)
    if scale != 1.0:
        log(f"обычные паузы масштабированы x{scale:.2f}, чтобы уложиться в {dc['max']} c")
    return base, scale, tail, tempo


def apply_tempo(vchunks, tempo):
    if abs(tempo - 1) < 1e-3:
        return
    for ch in vchunks:
        p = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                            "-af", f"atempo={tempo:.4f}", "-f", "f32le", "-"],
                           input=ch["audio"].astype(np.float32).tobytes(), capture_output=True, check=True)
        ch["audio"] = np.frombuffer(p.stdout, np.float32).copy()
        ch["len"] /= tempo
        for w in ch["words"]:
            w["s"] /= tempo
            w["e"] /= tempo


# ----------------------------------------------------------------------------
# Синтез звуков (numpy)
# ----------------------------------------------------------------------------
def fft_band(x, lo=None, hi=None, order=4):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR) + 1e-6
    m = np.ones_like(f)
    if lo:
        m *= 1 / (1 + (lo / f) ** (2 * order))
    if hi:
        m *= 1 / (1 + (f / hi) ** (2 * order))
    return np.fft.irfft(X * m, len(x)).astype(np.float32)


def sweep_noise(dur, fc, bw, rng, n=2048, hop=512):
    """Шум с полосой, центр которой fc(t) плывёт во времени (STFT-синтез)."""
    L = int(dur * SR)
    out = np.zeros(L + n, np.float32)
    win = np.hanning(n).astype(np.float32)
    f = np.fft.rfftfreq(n, 1 / SR)
    for st in range(0, L, hop):
        t = st / SR
        c, b = fc(t), bw(t)
        mag = np.exp(-0.5 * ((f - c) / b) ** 2)
        spec = mag * np.exp(2j * np.pi * rng.random(len(f)))
        out[st:st + n] += np.fft.irfft(spec, n).astype(np.float32) * win
    out = out[:L]
    return out / (np.max(np.abs(out)) + 1e-9)


def reverb(x, rt=0.6, mix=0.3, rng=None):
    rng = rng or np.random.default_rng(1)
    n = int(rt * SR)
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-6.9 * np.arange(n) / n).astype(np.float32)
    ir = fft_band(ir, 200, 4000)
    L = len(x) + n
    y = np.fft.irfft(np.fft.rfft(x, L) * np.fft.rfft(ir, L), L)[:L].astype(np.float32)
    y /= (np.max(np.abs(y)) + 1e-9)
    xx = np.concatenate([x, np.zeros(n, np.float32)])
    return xx * (1 - mix) + y * mix * np.max(np.abs(x))


def env_adsr(L, a, r):
    e = np.ones(L, np.float32)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return e


def snd_ring(rng):
    """Звонок: две ноты, глухо (как сквозь стену / из кармана)."""
    notes = [784.0, 622.3]
    note_len, out = 0.16, []
    for rep in range(2):
        for k in range(6):
            fr = notes[k % 2]
            t = np.arange(int(note_len * SR)) / SR
            s = np.sin(2 * np.pi * fr * t) + 0.35 * np.sin(2 * np.pi * 2 * fr * t) + 0.12 * np.sin(2 * np.pi * 3 * fr * t)
            out.append((s * env_adsr(len(t), 0.006, 0.03)).astype(np.float32))
        out.append(np.zeros(int(0.55 * SR), np.float32))
    x = np.concatenate(out)
    x = fft_band(x, 250, 1100, order=3)
    x = reverb(x, 0.9, 0.35, rng)
    return x / np.max(np.abs(x))


def snd_creak(rng, dur=1.7):
    """Скрип двери: прерывистое трение с глиссандо + плывущая полоса шума."""
    L = int(dur * SR)
    t = np.arange(L) / SR
    rate = 22 + 70 * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.5 + 8 * np.sin(2 * np.pi * 1.3 * t)
    phase = np.cumsum(rate / SR)
    pulses = np.zeros(L, np.float32)
    idx = np.where(np.diff(np.floor(phase)) > 0)[0]
    pulses[idx] = 0.6 + 0.4 * rng.random(len(idx))
    kt = np.arange(int(0.03 * SR)) / SR
    kern = sum(a * np.sin(2 * np.pi * f * kt) for f, a in [(620, 1), (1180, .7), (1930, .5), (2850, .3)])
    kern *= np.exp(-kt / 0.006)
    fric = np.convolve(pulses, kern)[:L].astype(np.float32)
    fric /= np.max(np.abs(fric)) + 1e-9
    gl = sweep_noise(dur, lambda tt: 700 + 1300 * math.sin(math.pi * min(tt / dur, 1)) ** 2,
                     lambda tt: 90, rng)
    x = 0.75 * fric + 0.45 * gl
    x *= env_adsr(L, 0.25, 0.35) * (0.7 + 0.3 * np.sin(2 * np.pi * 2.1 * t))
    x = reverb(x, 1.1, 0.35, rng)
    return x / np.max(np.abs(x))


def snd_whisper(rng, dur=1.5):
    """Шёпот: отфильтрованный шум с «слоговой» огибающей и плывущими формантами."""
    L = int(dur * SR)
    t = np.arange(L) / SR
    a = sweep_noise(dur, lambda tt: 2600 + 900 * math.sin(2 * math.pi * 3.1 * tt), lambda tt: 700, rng)
    b = sweep_noise(dur, lambda tt: 5200 + 700 * math.sin(2 * math.pi * 4.3 * tt + 1), lambda tt: 900, rng)
    syl = np.clip(np.sin(2 * np.pi * 4.6 * t + 2 * np.sin(2 * np.pi * 1.1 * t)), 0, 1) ** 1.5
    x = (a + 0.6 * b) * (0.25 + 0.75 * syl) * env_adsr(L, 0.12, 0.4)
    x = fft_band(x, 1200, 8000)
    return x / np.max(np.abs(x))


def snd_rustle(rng):
    dur = rng.uniform(0.35, 0.9)
    L = int(dur * SR)
    x = fft_band(rng.standard_normal(L).astype(np.float32), 1400, 5500)
    bumps = np.zeros(L, np.float32)
    for _ in range(rng.integers(3, 9)):
        c, w = rng.uniform(0, dur), rng.uniform(0.02, 0.09)
        bumps += rng.uniform(.3, 1) * np.exp(-0.5 * ((np.arange(L) / SR - c) / w) ** 2)
    x = x * bumps
    return x / (np.max(np.abs(x)) + 1e-9)


def snd_heartbeat_one(rng, last=False):
    def thump(f0, f1, dur, amp):
        t = np.arange(int(dur * SR)) / SR
        f = f1 + (f0 - f1) * np.exp(-t / 0.03)
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.055)
        click = fft_band(rng.standard_normal(len(t)).astype(np.float32), None, 300) * np.exp(-t / 0.01) * 0.6
        return ((s + click) * amp).astype(np.float32)
    lub = thump(95, 48, 0.32, 1.0)
    if last:
        return lub
    dub = thump(110, 58, 0.28, 0.65)
    out = np.zeros(int(0.2 * SR) + len(dub), np.float32)
    out[:len(lub)] += lub
    out[int(0.2 * SR):] += dub
    return out


def make_drone(L, rng):
    t = np.arange(L) / SR
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.07 * t)
    tone = (np.sin(2 * np.pi * 36.7 * t) + 0.8 * np.sin(2 * np.pi * 37.05 * t + 1) +
            0.55 * np.sin(2 * np.pi * 55.0 * t + 2) + 0.3 * np.sin(2 * np.pi * 73.6 * t) +
            0.12 * np.sin(2 * np.pi * 110.3 * t + 0.4 * np.sin(2 * np.pi * 0.2 * t)))
    rumble = fft_band(rng.standard_normal(L).astype(np.float32), 25, 160, order=2)
    rumble /= np.max(np.abs(rumble)) + 1e-9
    wind = fft_band(rng.standard_normal(L).astype(np.float32), 250, 700, order=2)
    wind /= np.max(np.abs(wind)) + 1e-9
    wind *= 0.5 + 0.5 * np.sin(2 * np.pi * 0.045 * t + 1.3)
    x = (tone / 2.5 * lfo + 0.7 * rumble + 0.18 * wind).astype(np.float32)
    left = x
    right = np.roll(x, int(0.013 * SR))
    return np.stack([left, right], 1)


def place(buf, x, t, gain=1.0, pan=0.0):
    s = int(t * SR)
    if s >= len(buf) or s + len(x) <= 0:
        return
    if s < 0:
        x, s = x[-s:], 0
    x = x[: len(buf) - s]
    if x.ndim == 1:
        lg, rg = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
        buf[s:s + len(x), 0] += x * gain * lg * 1.414
        buf[s:s + len(x), 1] += x * gain * rg * 1.414
    else:
        buf[s:s + len(x)] += x * gain


def db(x):
    return 10 ** (x / 20)


def build_audio(tl, cfg, out_wav):
    T = tl["T"]
    L = int(T * SR) + SR
    rng = np.random.default_rng(13)
    voice = np.zeros((L, 2), np.float32)
    for ch in tl["chunks"]:
        place(voice, ch["audio"], ch["t0"])
    bed = np.zeros((L, 2), np.float32)
    sfx = np.zeros((L, 2), np.float32)

    drone = make_drone(L, rng)
    drone *= db(cfg["audio"]["drone_db"]) / (np.sqrt(np.mean(drone ** 2)) + 1e-9)
    gain = np.ones(L, np.float32)
    fi = int(1.0 * SR)
    gain[:fi] = np.linspace(0, 1, fi)
    # обрыв дрона
    for c in tl["cues"]:
        if c["effect"] == "drone_cut":
            a, b = int(c["t"] * SR), int((c["t"] + 1.0) * SR)
            gain[a:b] = 0
            r = int(0.5 * SR)
            gain[b:b + r] = np.minimum(gain[b:b + r], np.linspace(0, 1, len(gain[b:b + r])))
    # тишина на последнем предложении
    hs = int(tl["silence_from"] * SR)
    gain[hs:hs + int(0.15 * SR)] *= np.linspace(1, 0, len(gain[hs:hs + int(0.15 * SR)]))
    gain[hs + int(0.15 * SR):] = 0
    bed += drone * gain[:, None]

    # редкие шорохи
    t = rng.uniform(4, 7)
    while t < tl["silence_from"] - 1.5:
        g = db(-30) * rng.uniform(0.5, 1.0)
        place(bed, snd_rustle(rng), t, g * gain[int(t * SR)], pan=rng.uniform(-0.9, 0.9))
        t += rng.uniform(5, 11)

    for c in tl["cues"]:
        e, ct = c["effect"], c["t"]
        if e == "ring":
            place(sfx, snd_ring(rng), ct + 0.05, db(-17), pan=-0.15)
        elif e == "ring_quiet":
            place(sfx, snd_ring(rng), ct + 0.05, db(-27), pan=0.2)
        elif e == "creak":
            place(sfx, snd_creak(rng), ct, db(-16), pan=-0.5)
        elif e == "whisper":
            w = snd_whisper(rng)
            place(sfx, w, ct, db(-20), pan=-0.75)
            place(sfx, w, ct + 0.012, db(-26), pan=0.6)

    # сердцебиение: замедляется и останавливается ровно на последнем слове
    last_t, hb_from = tl["last_word_t"], tl["silence_from"]
    beats, t, iv = [], last_t, 1.25
    while t > hb_from - 0.05:
        beats.append(t)
        t -= iv
        iv = max(0.78, iv * 0.93)
    for k, bt in enumerate(sorted(beats)):
        is_last = abs(bt - last_t) < 1e-6
        place(sfx, snd_heartbeat_one(rng, last=is_last), bt, db(-9 if is_last else -11))

    # баланс: голос громче «музыки» минимум на N dB
    vmask = np.abs(voice[:, 0]) > 1e-4
    v_rms = rms_db(voice[vmask, 0]) if vmask.any() else -20
    music = bed + sfx
    seg = music[: int(tl["silence_from"] * SR)]
    m_rms = rms_db(seg) if len(seg) else -60
    need = cfg["audio"]["min_voice_over_music_db"] + 1
    if v_rms - m_rms < need:
        k = db(-(need - (v_rms - m_rms)))
        music *= k
        m_rms = rms_db(music[: int(tl["silence_from"] * SR)])
    log(f"уровни: голос {v_rms:.1f} dBFS, дрон+шумы {m_rms:.1f} dBFS (разница {v_rms - m_rms:.1f} dB)")

    mix = voice + music
    peak = np.max(np.abs(mix))
    if peak > db(-1):
        mix *= db(-1) / peak
    mix = mix[: int(T * SR)]
    f = int(0.05 * SR)
    mix[-f:] *= np.linspace(1, 0, f)[:, None]
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    import wave
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


# ----------------------------------------------------------------------------
# Таймлайн
# ----------------------------------------------------------------------------
def find_phrase(words, phrase, occurrence=1):
    toks = norm(phrase).split()
    seen = 0
    for i in range(len(words) - len(toks) + 1):
        if [w["n"] for w in words[i:i + len(toks)]] == toks:
            seen += 1
            if seen == occurrence:
                return i
    return None


def group_words(words, cfg):
    sc = cfg["subtitles"]
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        brk = (nxt is None or nxt["chunk"] != w["chunk"] or len(cur) >= sc["words_max"] or
               (len(cur) >= sc["words_min"] and w["punct"]))
        if not brk and nxt is not None and len(cur) >= sc["words_min"]:
            # не оставлять одно слово висеть в конце фразы
            rest = sum(1 for x in words[i + 1:] if x["chunk"] == w["chunk"])
            if rest == 1 and len(cur) < sc["words_max"]:
                brk = False
            elif rest <= sc["words_max"] - 1 and rest >= 2 and len(cur) >= sc["words_min"]:
                brk = True
        if brk:
            groups.append(cur)
            cur = []
    out = []
    for gi, g in enumerate(groups):
        s = words[g[0]]["s"]
        e_last = words[g[-1]]["e"]
        nxt_s = words[groups[gi + 1][0]]["s"] if gi + 1 < len(groups) else e_last + 0.8
        out.append({"w": g, "s": s, "e": min(nxt_s, e_last + 0.7)})
    return out


def build_timeline(title, vchunks, base, scale, tail, cfg):
    dc = cfg["duration"]
    t = dc["voice_start"]
    words = []
    for i, ch in enumerate(vchunks):
        kind, pv = base[i]
        t += pv if kind == "fixed" else pv * scale
        ch["t0"] = t
        toks = list(re.finditer(r"\w+(?:-\w+)*([^\w\s]*)", ch["text"]))
        for w, m in zip(ch["words"], toks):
            words.append({"text": w["text"], "n": norm(w["text"]), "s": t + w["s"], "e": t + w["e"],
                          "kind": ch["kind"], "chunk": i, "punct": bool(m.group(1).strip("-"))})
        t += ch["len"]
    last_end = t
    plate_t = last_end + tail
    T = plate_t + dc["plate"]
    cues = []
    for c in cfg["cues"]:
        i = find_phrase(words, c["phrase"], c.get("occurrence", 1))
        if i is None:
            log(f"!! фраза для эффекта «{c['effect']}» не найдена в истории: «{c['phrase']}» — пропускаю")
            continue
        n = len(norm(c["phrase"]).split())
        cues.append({"effect": c["effect"], "t": words[i]["s"], "end": words[i + n - 1]["e"]})
    last = vchunks[-1]
    return {
        "title": title, "T": T, "chunks": vchunks, "words": words,
        "groups": group_words(words, cfg), "cues": cues,
        "plate_t": plate_t, "last_word_t": words[-1]["s"],
        "silence_from": last["t0"] - base[-1][1] * (1 if base[-1][0] == "fixed" else scale) + 0.05,
    }


# ----------------------------------------------------------------------------
# Видео
# ----------------------------------------------------------------------------
def load_font(cands, size):
    for c in cands:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def smooth_noise(w, h, scale, rng):
    small = rng.random((max(2, h // scale), max(2, w // scale))).astype(np.float32)
    im = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    im = im.filter(ImageFilter.GaussianBlur(scale / 3))
    a = np.asarray(im, np.float32) / 255
    return (a - a.min()) / (a.max() - a.min() + 1e-9)


class Background:
    """Сгенерированный фон: сине-чёрный градиент, коридор, полоска света, туман."""
    LW, LH = 360, 640

    def __init__(self, cfg):
        bc = cfg["background"]
        rng = np.random.default_rng(7)
        w, h = self.LW, self.LH
        y = np.linspace(0, 1, h)[:, None, None]
        top, bot = np.array(bc["top_color"], np.float32), np.array(bc["bottom_color"], np.float32)
        base = (top * (1 - y) + bot * y) * np.ones((1, w, 1), np.float32)
        xs = np.linspace(-1, 1, w)[None, :]
        ys = np.linspace(-1, 1, h)[:, None]
        vx, vy = 0.0, -0.12            # точка схода коридора
        dx, dy = np.abs(xs - vx), np.abs(ys - vy)
        door_w, door_h = 0.16, 0.30    # дальняя дверь
        inside = (dx < door_w) & (dy < door_h)
        walls = np.clip(1 - np.maximum(dx / 1.0, dy / 1.1), 0, 1) ** 2.2
        # рёбра коридора (стык стен с полом/потолком) и рамка двери
        edges = (np.abs(dy - dx * 1.7) < 0.010).astype(np.float32) * (dy > door_h)
        frame = ((np.abs(dx - door_w) < 0.008) & (dy < door_h)) | ((np.abs(dy - door_h) < 0.006) & (dx < door_w))
        edges = np.maximum(edges, frame.astype(np.float32) * 0.8)
        edges = np.asarray(Image.fromarray((edges * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.3)),
                           np.float32) / 255
        corridor = 0.13 * walls + 0.10 * edges
        corridor[inside] = 0.012
        fog_col = np.array(bc["fog_color"], np.float32)
        base += corridor[..., None] * fog_col[None, None] * 1.6
        light_col = np.array(bc["light_color"], np.float32)
        sx = (np.arange(w) - (w / 2 + door_w * w / 2 * 0.55))
        core = np.exp(-0.5 * (sx / 1.5) ** 2)[None, :] * (dy < door_h)
        glow = np.exp(-0.5 * (sx / 26) ** 2)[None, :] * np.exp(-0.5 * (np.maximum(dy - door_h, 0) / 0.25) ** 2)
        floor = (ys > vy + door_h) * np.exp(-0.5 * (sx / 10) ** 2)[None, :] * np.exp(-(ys - vy - door_h) * 3.5)
        light = core * 1.6 + glow * 0.35 + floor * 0.5
        r = np.sqrt(xs ** 2 * 1.1 + ys ** 2 * 0.75)
        vign = np.clip(1.15 - r ** 2.2 * 0.95, 0.05, 1)[..., None].astype(np.float32)
        self.static = (base * vign).astype(np.float32)
        self.light = (light[..., None] * light_col[None, None] * 0.75 * vign).astype(np.float32)
        self.fogc = (fog_col[None, None] * 0.6 * vign).astype(np.float32)
        self.fog1 = smooth_noise(w, h * 2, 60, rng)
        self.fog2 = smooth_noise(w * 2, h, 40, rng)
        self.grain = [rng.normal(0, 4.0, (h, w, 1)).astype(np.float32) for _ in range(8)]

    @staticmethod
    def _scroll(tex, off, axis):
        n = tex.shape[axis] // 2
        i, fr = int(off) % n, off - int(off)
        if axis == 0:
            return tex[i:i + n] * (1 - fr) + tex[i + 1:i + 1 + n] * fr
        return tex[:, i:i + n] * (1 - fr) + tex[:, i + 1:i + 1 + n] * fr

    def frame(self, t, fi):
        flick = 0.85 + 0.1 * math.sin(t * 2.3) + 0.05 * math.sin(t * 13.7)
        if (int(t * 7) % 37) == 0:
            flick *= 0.55
        fog = 0.6 * self._scroll(self.fog1, t * 6.0, 0) + 0.4 * self._scroll(self.fog2, t * 4.0, 1)
        fog = np.clip(fog - 0.35, 0, None)
        fog *= fog * 1.6
        img = self.static + self.light * flick + fog[..., None] * self.fogc + self.grain[fi % len(self.grain)]
        small = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
        return np.asarray(small.resize((W, H), Image.BILINEAR))


class VideoBackground:
    def __init__(self, path, start_frame, fps):
        self.p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{start_frame / fps:.4f}", "-i", str(path),
                                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.last = np.zeros((H, W, 3), np.uint8)

    def frame(self, t, fi):
        b = self.p.stdout.read(W * H * 3)
        if len(b) == W * H * 3:
            self.last = np.frombuffer(b, np.uint8).reshape(H, W, 3)
        return self.last

    def close(self):
        self.p.kill()


def prepare_bg_video(cfg, T, fps, tmp):
    folder = ROOT / cfg["background"]["folder"]
    if not folder.is_dir():
        return None
    files = [p for p in folder.iterdir() if p.suffix.lower() in (".mp4", ".mov")]
    if not files:
        return None
    src = random.choice(files)
    log(f"фон: {src.name}")
    dim = cfg["background"]["dim"]
    vf = (f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={W}:{H},fps={fps},"
          f"lutrgb=r='val*{dim}':g='val*{dim}':b='val*{dim}',eq=saturation=0.75,"
          f"vignette=angle=PI/2.6,vignette=angle=PI/3.2")
    out = Path(tmp) / "bg.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", str(src), "-t", f"{T + 1:.3f}",
                    "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", str(out)], check=True)
    return out


class Renderer:
    def __init__(self, tl, cfg, fps, bg_path, start_frame):
        self.tl, self.cfg, self.fps = tl, cfg, fps
        sc = cfg["subtitles"]
        self.sc = sc
        self.font_c = sc["font"]
        self.bg = VideoBackground(bg_path, start_frame, fps) if bg_path else Background(cfg)
        self.cache = {}
        self.fonts = {}
        self.base_size = sc["size"]
        words = tl["words"]
        self.disp = [(w["text"].upper() if sc["uppercase"] else w["text"]) for w in words]
        self.layouts = [self.layout(g) for g in tl["groups"]]
        self.title_img = self.make_title()
        self.plate_img = self.make_plate()
        # маска краёв для красного свечения
        xs = np.linspace(-1, 1, 270)[None, :]
        ys = np.linspace(-1, 1, 480)[:, None]
        r = np.maximum(np.abs(xs) ** 6, np.abs(ys) ** 8) * 0.75 + (xs ** 2 * 0.5 + ys ** 2 * 0.3) ** 2.5
        edge = np.clip(r, 0, 1).astype(np.float32)
        self.edge = np.asarray(Image.fromarray((edge * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR),
                               np.float32)[..., None] / 255
        self.cue = {}
        for c in tl["cues"]:
            self.cue.setdefault(c["effect"], []).append(c)

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = load_font(self.font_c, size)
        return self.fonts[size]

    def sprite(self, text, size, color):
        key = (text, size, tuple(color))
        if key not in self.cache:
            f = self.font(size)
            st = max(2, int(self.sc["stroke"] * size / self.base_size))
            l, t, r, b = f.getbbox(text, stroke_width=st)
            pad = 14
            im = Image.new("RGBA", (r - l + pad * 2, b - t + pad * 2), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).text((pad - l + 3, pad - t + 5), text, font=f, fill=(0, 0, 0, 170),
                                    stroke_width=st, stroke_fill=(0, 0, 0, 170))
            sh = sh.filter(ImageFilter.GaussianBlur(5))
            im.alpha_composite(sh)
            d.text((pad - l, pad - t), text, font=f, fill=tuple(color) + (255,),
                   stroke_width=st, stroke_fill=tuple(self.sc["stroke_color"]) + (255,))
            self.cache[key] = (im, -l + pad, -t + pad)
        return self.cache[key]

    def layout(self, g):
        """Раскладка группы слов в 1–3 строки; если не влезает — уменьшаем шрифт группы."""
        f = self.font(self.base_size)
        space = self.base_size * 0.26
        ws = [f.getlength(self.disp[i]) * 1.12 for i in g["w"]]   # запас под пульсацию
        n = len(ws)

        def width(seq):
            return sum(ws[j] for j in seq) + space * (len(seq) - 1)

        best = None
        for nl in range(1, min(3, n) + 1):
            import itertools
            for cuts in itertools.combinations(range(1, n), nl - 1):
                b = (0,) + cuts + (n,)
                lines = [list(range(b[k], b[k + 1])) for k in range(nl)]
                mw = max(width(l) for l in lines)
                fits = mw <= self.sc["max_width"]
                key = (not fits, nl, mw)
                if best is None or key < best[0]:
                    best = (key, lines, mw)
            if best[0][0] is False:
                break
        _, lines, mw = best
        scale = min(1.0, self.sc["max_width"] / mw)
        lh = self.base_size * 1.18 * scale
        cy = H * self.sc["y"]
        y0 = cy - lh * (len(lines) - 1) / 2
        pos = []
        for li, line in enumerate(lines):
            x = W / 2 - width(line) * scale / 2
            for j in line:
                pos.append((j, x + ws[j] * scale / 2, y0 + li * lh))
                x += (ws[j] + space) * scale
        pos.sort()
        return [(cx, cy, scale) for _, cx, cy in pos]

    def make_title(self):
        tc = self.cfg["title"]
        f = load_font(self.font_c, tc["size"])
        words, lines, cur = self.tl["title"].upper().split(), [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if f.getlength(test) > 900 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = test
        lines.append(cur)
        lh = int(tc["size"] * 1.18)
        im = Image.new("RGBA", (W, lh * len(lines) + 120), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for i, l in enumerate(lines):
            d.text((W / 2, 30 + i * lh + lh / 2), l, font=f, anchor="mm", fill=tuple(tc["color"]) + (255,),
                   stroke_width=8, stroke_fill=(0, 0, 0, 255))
        yb = 30 + lh * len(lines) + 25
        d.rectangle((W / 2 - 110, yb, W / 2 + 110, yb + 8), fill=tuple(tc["accent"]) + (255,))
        glow = im.filter(ImageFilter.GaussianBlur(18))
        out = Image.new("RGBA", im.size, (0, 0, 0, 0))
        out.alpha_composite(glow)
        out.alpha_composite(im)
        return out

    def make_plate(self):
        pc = self.cfg["plate"]
        f = load_font(self.font_c, pc["size"])
        lines = pc["text"].split("\n")
        lh = int(pc["size"] * 1.25)
        tw = max(f.getlength(l) for l in lines)
        bw, bh = int(tw + 140), lh * len(lines) + 90
        im = Image.new("RGBA", (bw + 80, bh + 80), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((40, 40, 40 + bw, 40 + bh), radius=36, fill=(8, 6, 8, 235),
                            outline=tuple(pc["border"]) + (255,), width=7)
        glow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle((40, 40, 40 + bw, 40 + bh), radius=36,
                                               outline=tuple(pc["border"]) + (200,), width=16)
        glow = glow.filter(ImageFilter.GaussianBlur(20))
        out = Image.new("RGBA", im.size, (0, 0, 0, 0))
        out.alpha_composite(glow)
        out.alpha_composite(im)
        d = ImageDraw.Draw(out)
        for i, l in enumerate(lines):
            col = (255, 255, 255, 255) if i else (235, 40, 40, 255)
            d.text((out.width / 2, 40 + 45 + lh * i + lh / 2), l, font=f, anchor="mm", fill=col)
        return out

    @staticmethod
    def with_alpha(im, a):
        if a >= 0.999:
            return im
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
        return im

    def draw_subs(self, img, t):
        tl, sc = self.tl, self.sc
        if t < self.cfg["title"]["show"] or t >= tl["plate_t"]:
            return
        for gi, g in enumerate(tl["groups"]):
            if g["s"] <= t < g["e"]:
                break
        else:
            return
        words = tl["words"]
        cur = None
        for k, wi in enumerate(g["w"]):
            nxt_s = words[g["w"][k + 1]]["s"] if k + 1 < len(g["w"]) else g["e"]
            if words[wi]["s"] <= t < nxt_s:
                cur = wi
        age_g = t - g["s"]
        appear = min(1.0, age_g / 0.09)
        for (cx, cy, gs), wi in zip(self.layouts[gi], g["w"]):
            phone = words[wi]["kind"] == "phone"
            if wi == cur:
                age = t - words[wi]["s"]
                s = 1.05 + 0.06 * math.exp(-age * 9) + 0.025 * math.sin(2 * math.pi * 2.6 * age)
                col = sc["phone_highlight"] if phone else sc["highlight"]
            else:
                s = 1.0
                col = sc["phone_color"] if phone else sc["color"]
            s *= (0.9 + 0.1 * appear) * gs
            size = int(round(self.base_size * s / 2) * 2)
            spr, _, _ = self.sprite(self.disp[wi], size, col)
            spr = self.with_alpha(spr, appear)
            img.paste(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2)), spr)

    def render(self, fi):
        t = fi / self.fps
        tl = self.tl
        arr = self.bg.frame(t, fi)
        img = Image.fromarray(arr).convert("RGB") if arr.flags.writeable is False else Image.fromarray(arr)
        # заголовок
        ts = self.cfg["title"]["show"]
        if t < ts:
            a = 1.0 if t < ts - 0.45 else max(0.0, (ts - t) / 0.45)
            ti = self.with_alpha(self.title_img, a)
            img.paste(ti, (0, int(H * 0.44 - ti.height / 2)), ti)
        self.draw_subs(img, t)
        frame = np.asarray(img)
        # дрожание кадра
        for c in self.cue.get("shake", []):
            if c["t"] <= t < c["end"] + 0.6:
                k = 1 - (t - c["t"]) / (c["end"] + 0.6 - c["t"])
                rng = random.Random(fi)
                dx, dy = int(rng.uniform(-14, 14) * k), int(rng.uniform(-10, 10) * k)
                frame = shift(frame, dx, dy)
        # эффект двойника
        for c in self.cue.get("double", []):
            if c["t"] <= t < c["t"] + 0.55:
                p = (t - c["t"]) / 0.55
                off = int(46 * math.sin(p * math.pi)) + (8 if (fi % 3 == 0) else 0)
                ghost = shift(frame, off, 0).astype(np.uint16)
                ghost2 = shift(frame, -off // 2, 0).astype(np.uint16)
                frame = ((frame.astype(np.uint16) * 5 + ghost * 4 + ghost2 * 2) // 11).astype(np.uint8)
        # финал: красное свечение + затемнение
        T = tl["T"]
        if t >= T - 3:
            p = min(1.0, (t - (T - 3)) / 3)
            fade = (1 - p) ** 1.4
            glow = math.sin(math.pi * min(1, p * 1.15)) * 0.7 + 0.15 * (1 - p)
            pulse = 0.85 + 0.15 * math.sin(t * 7)
            f = frame.astype(np.float32) * fade
            f[..., 0:1] += self.edge * 200 * glow * pulse
            f[..., 1:3] += self.edge * 18 * glow * pulse
            frame = np.clip(f, 0, 255).astype(np.uint8)
        if t >= tl["plate_t"]:
            a = min(1.0, (t - tl["plate_t"]) / 0.2)
            img = Image.fromarray(frame)
            pi = self.with_alpha(self.plate_img, a)
            img.paste(pi, ((W - pi.width) // 2, int(H * 0.5 - pi.height / 2)), pi)
            frame = np.asarray(img)
        return frame


def shift(a, dx, dy):
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = a[ys, xs]
    return out


def render_segment(args):
    tl, cfg, fps, bg_path, a, b, out = args
    r = Renderer(tl, cfg, fps, bg_path, a)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
                            "-profile:v", "high", "-threads", "2", str(out)], stdin=subprocess.PIPE)
    for fi in range(a, b):
        enc.stdin.write(np.ascontiguousarray(r.render(fi)).tobytes())
    enc.stdin.close()
    enc.wait()
    if isinstance(r.bg, VideoBackground):
        r.bg.close()
    return out


def strip_audio(tl):
    tl = dict(tl)
    tl["chunks"] = [{k: v for k, v in c.items() if k != "audio"} for c in tl["chunks"]]
    return tl


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Хоррор-шортс: озвучка + субтитры")
    ap.add_argument("story", nargs="?", default="story.txt")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--preview", type=float, default=None, help="отрендерить только первые N секунд")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--workers", type=int, default=max(1, min(cpu_count(), 8)))
    ap.add_argument("--seed", type=int, default=None, help="зерно для выбора фонового видео")
    ap.add_argument("--frames", default=None, help="отладка: сохранить PNG кадров в моменты t1,t2,... (сек)")
    args = ap.parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    if not shutil.which("ffmpeg"):
        sys.exit("Нужен ffmpeg в PATH")
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    out = Path(args.output or ("output_preview.mp4" if args.preview else "output.mp4"))

    title, chunks = parse_story(args.story, cfg)
    log(f"заголовок: {title}; фраз: {len(chunks)}")
    log("озвучка (edge-tts)…")
    vchunks = build_voice(chunks, cfg)
    base, scale, tail, tempo = plan_timeline(vchunks, cfg)
    apply_tempo(vchunks, tempo)
    tl = build_timeline(title, vchunks, base, scale, tail, cfg)
    T = tl["T"]
    log(f"длительность ролика: {T:.2f} c")
    for c in tl["cues"]:
        log(f"  эффект {c['effect']:<10} @ {c['t']:6.2f} c")

    if args.frames:
        with tempfile.TemporaryDirectory(prefix="horror_") as tmp:
            bg = prepare_bg_video(cfg, T, args.fps, tmp)
            for ts in args.frames.split(","):
                fi = int(float(ts) * args.fps)
                r = Renderer(strip_audio(tl), cfg, args.fps, bg, fi)
                Image.fromarray(r.render(fi)).save(f"frame_{float(ts):05.2f}.png")
                log(f"frame_{float(ts):05.2f}.png")
        return

    with tempfile.TemporaryDirectory(prefix="horror_") as tmp:
        tmp = Path(tmp)
        wav = tmp / "audio.wav"
        log("звук…")
        build_audio(tl, cfg, wav)
        RT = min(T, args.preview) if args.preview else T
        bg = prepare_bg_video(cfg, T, args.fps, tmp)
        if bg is None:
            log("фон: генерирую (папка bg/ пуста или отсутствует)")
        n = int(round(RT * args.fps))
        k = max(1, min(args.workers, n // 30))
        bounds = [round(n * i / k) for i in range(k + 1)]
        slim = strip_audio(tl)
        jobs = [(slim, cfg, args.fps, bg, bounds[i], bounds[i + 1], tmp / f"seg{i:02d}.mp4") for i in range(k)]
        log(f"рендер {n} кадров ({args.fps} fps) в {k} потоков…")
        with Pool(k) as pool:
            segs = pool.map(render_segment, jobs)
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{s}'\n" for s in segs))
        log("сборка mp4…")
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(wav),
               "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-t", f"{RT:.3f}", "-movflags", "+faststart"]
        if args.preview and RT < T:
            cmd[cmd.index("-c:a"):cmd.index("-c:a")] = ["-af", f"afade=t=out:st={RT - 0.4:.2f}:d=0.4"]
        subprocess.run(cmd + [str(out)], check=True)
    log(f"готово: {out.resolve()}  ({RT:.1f} c)")
    if bg is None:
        log("подсказка: положите свои .mp4/.mov в папку bg/ — будет взят случайный ролик как фон")


if __name__ == "__main__":
    main()
