#!/usr/bin/env python3
"""Музыка и звуковые эффекты — чистый синтез на numpy, без внешних файлов.

  build/music.wav — напряжённый эмбиент, нарастающий к концу (стерео)
  build/sfx.wav   — эффекты: пуф, хлопок, свист, бульк + «вжух» на каждой смене кадра
Тайминги берутся из build/timeline.json (то есть из реальной озвучки).
"""
import json
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
SR = 48000
RNG = np.random.default_rng(42)


# ------------------------------------------------------------ утилиты
def env_adsr(n, a=0.01, r=0.2, sr=SR):
    e = np.ones(n)
    na, nr = max(1, int(a * sr)), max(1, int(r * sr))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return e


def fft_filter(x, lo=None, hi=None):
    """Полосовой фильтр через FFT (мягкие края)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    g = np.ones_like(f)
    if lo:
        g *= 1 / (1 + (lo / np.maximum(f, 1)) ** 4)
    if hi:
        g *= 1 / (1 + (f / hi) ** 4)
    return np.fft.irfft(X * g, len(x))


def sweep_filter_noise(n, f0, f1, q=3.0):
    """Шум, пропущенный через резонансный фильтр с плавающей частотой (state-variable)."""
    x = RNG.standard_normal(n)
    y = np.zeros(n)
    low = band = 0.0
    fc = np.geomspace(f0, f1, n)
    for i in range(n):
        f = 2 * np.sin(np.pi * fc[i] / SR)
        low += f * band
        high = x[i] - low - band / q
        band += f * high
        y[i] = band
    return y / (np.abs(y).max() + 1e-9)


def osc(freq, n, kind="sine", phase0=0.0):
    """freq — число или массив (для глайдов)."""
    ph = phase0 + 2 * np.pi * np.cumsum(np.broadcast_to(freq, (n,))) / SR
    if kind == "sine":
        return np.sin(ph)
    if kind == "tri":
        return 2 / np.pi * np.arcsin(np.sin(ph))
    raise ValueError(kind)


def soft_saw(freq, n, harmonics=8, bright=1.0):
    """Пила из гармоник с затуханием (мягче цифровой)."""
    out = np.zeros(n)
    for h in range(1, harmonics + 1):
        out += np.sin(2 * np.pi * freq * h * np.arange(n) / SR + h * 0.7) / h ** (1.6 - 0.6 * bright)
    return out


# ------------------------------------------------------------ эффекты
def sfx_poof():
    n = int(0.65 * SR)
    t = np.arange(n) / SR
    noise = fft_filter(RNG.standard_normal(n), 80, 1800)
    body = np.sin(2 * np.pi * np.cumsum(np.geomspace(260, 60, n)) / SR)
    e = np.exp(-t * 7) * env_adsr(n, 0.008, 0.1)
    return (0.8 * noise / np.abs(noise).max() + 0.6 * body) * e


def sfx_clap():
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    noise = fft_filter(RNG.standard_normal(n), 700, 6000)
    noise /= np.abs(noise).max()
    e = np.zeros(n)
    for k, d in enumerate([0, 0.011, 0.022]):  # три микро-удара, как у настоящего хлопка
        m = t >= d
        e[m] += np.exp(-(t[m] - d) * (60 if k < 2 else 22)) * (0.7 if k < 2 else 1.0)
    thump = np.sin(2 * np.pi * 140 * t) * np.exp(-t * 30) * 0.5
    return noise * e + thump


def sfx_whistle(pitch=1):
    n = int(0.7 * SR)
    t = np.arange(n) / SR
    f = np.geomspace(700, 2400, n) if pitch >= 0 else np.geomspace(2200, 500, n)
    f = f * (1 + 0.02 * np.sin(2 * np.pi * 9 * t))
    tone = osc(f, n) + 0.15 * osc(f * 2, n)
    air = sweep_filter_noise(n, f[0], f[-1], q=8) * 0.25
    return (tone * 0.6 + air) * env_adsr(n, 0.04, 0.25) * np.sin(np.pi * t / t[-1]) ** 0.5


def sfx_bloop():
    out = np.zeros(int(0.45 * SR))
    for d, f0, f1, a in [(0, 220, 950, 1.0), (0.13, 300, 1200, 0.6)]:
        n = int(0.16 * SR)
        t = np.arange(n) / SR
        f = f0 + (f1 - f0) * (1 - np.exp(-t * 35))
        s = osc(f, n) * np.exp(-t * 26) * a
        k = int(d * SR)
        out[k:k + n] += s
    return out


def sfx_whoosh(dur=0.42):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = sweep_filter_noise(n, 300, 3200, q=1.6)
    return s * np.sin(np.pi * t / t[-1]) ** 2


SFX = {"poof": (sfx_poof, 0.9), "clap": (sfx_clap, 0.75), "whistle": (sfx_whistle, 0.45),
       "bloop": (sfx_bloop, 0.7), "whoosh": (sfx_whoosh, 0.35)}


# ------------------------------------------------------------ музыка
def note(n):  # MIDI → Гц
    return 440.0 * 2 ** ((n - 69) / 12)


def music(total, scenes):
    n = int(total * SR)
    t = np.arange(n) / SR
    p = t / total
    final_start = scenes[-1]["start"]
    fin = np.clip((t - final_start + 0.3) / 0.8, 0, 1)        # 0 → 1 в финальной сцене
    tense = 1 - fin
    L = np.zeros(n)
    R = np.zeros(n)

    # 1) Дрон: A1 + E2, яркость и громкость растут с прогрессом
    for midi, amp, det in [(33, 0.30, 0.0), (40, 0.18, 0.15), (45, 0.12, -0.1)]:
        f = note(midi)
        dark = soft_saw(f * (1 + det / 100), n, harmonics=4, bright=0.0)
        bright = soft_saw(f * (1 - det / 100), n, harmonics=10, bright=1.0)
        s = (dark * (1 - p) + bright * p) * amp
        L += s * (0.9 + 0.1 * np.sin(2 * np.pi * 0.07 * t))
        R += s * (0.9 + 0.1 * np.cos(2 * np.pi * 0.06 * t))
    drone_gain = (0.35 + 0.65 * p ** 1.3) * tense
    L *= drone_gain
    R *= drone_gain

    # 2) Гармония: тепло (мажорная терция C#) → холод (минорная C), потом тритон D#
    warm = np.clip(1 - p / 0.35, 0, 1)
    cold = np.clip((p - 0.2) / 0.3, 0, 1) * tense
    trit = np.clip((p - 0.55) / 0.3, 0, 1) * tense
    pad = (osc(note(61), n, "tri") * warm * 0.10 + osc(note(60), n, "tri") * cold * 0.10 +
           osc(note(63) * 1.003, n, "tri") * trit * 0.07)
    pad *= 0.8 + 0.2 * np.sin(2 * np.pi * 0.5 * t)
    L += pad
    R += pad * 0.95

    # 3) Пульс «сердце»: темп растёт 62 → 112 BPM, вступает с ~20% видео
    beat_t = 0.0
    kick = np.zeros(n)
    while beat_t < final_start - 0.1:
        pp = beat_t / total
        bpm = 62 + 50 * pp
        if pp > 0.18:
            for off, a in [(0, 1.0), (0.18, 0.55)]:          # «тук-тук»
                k0 = int((beat_t + off) * SR)
                m = int(0.25 * SR)
                if k0 + m < n:
                    tt = np.arange(m) / SR
                    kick[k0:k0 + m] += np.sin(2 * np.pi * np.cumsum(55 + 90 * np.exp(-tt * 30)) / SR) \
                        * np.exp(-tt * 14) * a * (0.25 + 0.75 * pp)
        beat_t += 60 / bpm
    L += kick * 0.55
    R += kick * 0.55

    # 4) Высокое тремоло-«натяжение», вступает со второй половины
    shimmer_f = note(81) * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * t))
    shimmer = osc(shimmer_f, n) * (0.5 + 0.5 * np.sin(2 * np.pi * (3 + 5 * p) * t)) \
        * np.clip((p - 0.45) / 0.4, 0, 1) * 0.05 * tense
    L += shimmer
    R += np.roll(shimmer, 600)

    # 5) Холодный ветер (шум) — в сценах холода и дальше
    wind = fft_filter(RNG.standard_normal(n), 250, 1400)
    wind /= np.abs(wind).max()
    wenv = np.clip((p - 0.25) / 0.2, 0, 1) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.23 * t)) * tense
    L += wind * wenv * 0.12
    R += np.roll(wind, 2400) * wenv * 0.12

    # 6) Финал: тёплый мажор (A-C#-E-A) с «колокольчиками» — свет вернулся!
    if fin.any():
        warm_pad = sum(osc(note(m), n, "tri") * a for m, a in [(45, .14), (57, .1), (61, .08), (64, .08), (69, .05)])
        L += warm_pad * fin * 0.9
        R += warm_pad * fin * 0.9
        bell_t = final_start + 0.1
        seq = [69, 73, 76, 81, 76, 73, 76, 81]
        i = 0
        while bell_t < total - 0.3:
            m = int(1.2 * SR)
            k0 = int(bell_t * SR)
            tt = np.arange(min(m, n - k0)) / SR
            b = (np.sin(2 * np.pi * note(seq[i % len(seq)]) * tt) + 0.3 * np.sin(2 * np.pi * note(seq[i % len(seq)]) * 2.01 * tt)) \
                * np.exp(-tt * 4) * 0.12
            L[k0:k0 + len(tt)] += b * (0.7 if i % 2 else 1.0)
            R[k0:k0 + len(tt)] += b * (1.0 if i % 2 else 0.7)
            bell_t += 0.32
            i += 1

    # плавный вход/выход
    fade = np.clip(t / 0.6, 0, 1) * np.clip((total - t) / 1.2, 0, 1)
    out = np.stack([L * fade, R * fade], 1)
    return out / (np.abs(out).max() + 1e-9) * 0.8


def sfx_track(total, scenes):
    n = int(total * SR) + SR
    out = np.zeros((n, 2))

    def place(sig, at, gain, pan=0.0):
        k = int(max(0, at) * SR)
        m = min(len(sig), n - k)
        out[k:k + m, 0] += sig[:m] * gain * (1 - max(0, pan))
        out[k:k + m, 1] += sig[:m] * gain * (1 + min(0, pan))

    for i, sc in enumerate(scenes):
        # «вжух» на смене сцены и на каждом бите внутри сцены
        for j, b in enumerate(sc["beats"]):
            if i == 0 and j == 0:
                continue
            fn, g = SFX["whoosh"]
            place(fn(), b - 0.18, g, pan=(-0.3 if (i + j) % 2 else 0.3))
        for e in sc["sfx"]:
            fn, g = SFX[e["type"]]
            sig = fn(e["pitch"]) if e["type"] == "whistle" and "pitch" in e else fn()
            place(sig, e["t"] - (0.05 if e["type"] != "poof" else 0.0), g * e.get("gain", 1.0))
    out = out[: int(total * SR)]
    return out / max(1.0, np.abs(out).max() / 0.9)


def write_wav(path, x):
    x = np.clip(x, -1, 1)
    if x.ndim == 1:
        x = x[:, None]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())


def main():
    tl = json.loads((BUILD / "timeline.json").read_text(encoding="utf-8"))
    total, scenes = tl["total"], tl["scenes"]
    write_wav(BUILD / "music.wav", music(total, scenes))
    write_wav(BUILD / "sfx.wav", sfx_track(total, scenes))
    nfx = sum(len(s["sfx"]) for s in scenes) + sum(len(s["beats"]) for s in scenes) - 1
    print(f"[audio] music.wav и sfx.wav ({total:.2f}s, эффектов: {nfx})")


if __name__ == "__main__":
    main()
