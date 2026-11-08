"""Procedurally generated background music (no third-party samples -> no copyright issues).

Light, upbeat lo-fi loop: soft keys + bass + gentle kick/shaker, 96 BPM, I-vi-IV-V in C.
Usage: python3 pipeline/music.py [seconds]
"""
import os
import sys
import wave

import numpy as np

SR = 48000
BPM = 96
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
length = float(sys.argv[1]) if len(sys.argv) > 1 else 305.0
rng = np.random.default_rng(7)

beat = 60 / BPM
n = int(length * SR)
L = np.zeros(n)
R = np.zeros(n)


def midi(m):
    return 440 * 2 ** ((m - 69) / 12)


def add(buf, start, sig):
    i = int(start * SR)
    if i >= n:
        return
    j = min(n, i + len(sig))
    buf[i:j] += sig[: j - i]


def keys(freq, dur, vel=0.18):
    t = np.arange(int((dur + 1.2) * SR)) / SR
    env = np.minimum(t / 0.01, 1) * np.exp(-t * 2.2)
    sig = (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t) * np.exp(-t * 4)
           + 0.12 * np.sin(6 * np.pi * freq * t) * np.exp(-t * 6))
    return vel * env * sig * (1 + 0.004 * np.sin(2 * np.pi * 5 * t))


def bass(freq, dur):
    t = np.arange(int(dur * SR)) / SR
    env = np.minimum(t / 0.02, 1) * np.minimum((dur - t) / 0.08, 1).clip(0)
    return 0.22 * env * (np.sin(2 * np.pi * freq * t) + 0.2 * np.sin(4 * np.pi * freq * t))


def kick():
    t = np.arange(int(0.35 * SR)) / SR
    f = 50 + 70 * np.exp(-t * 30)
    return 0.35 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def shaker():
    t = np.arange(int(0.08 * SR)) / SR
    x = rng.standard_normal(len(t))
    x = np.diff(x, prepend=0)  # crude high-pass
    return 0.03 * x * np.exp(-t * 60)


# C, Am, F, G (midi roots + voicings)
prog = [(48, [60, 64, 67, 71]), (45, [57, 60, 64, 67]), (41, [57, 60, 65, 69]), (43, [55, 59, 62, 67])]
melody = [72, 76, 79, 76, 74, 72, 69, 72, 69, 72, 77, 76, 74, 71, 67, 71]
bar = 4 * beat
t0, b = 0.0, 0
while t0 < length:
    root, chord = prog[b % 4]
    # chord stabs on beats 1 and 3 (and an off-beat), slightly spread for stereo
    for k, off in enumerate([0, 1.5, 2]):
        for v, m in enumerate(chord):
            s = keys(midi(m), beat, 0.07)
            pan = 0.35 + 0.1 * v
            add(L, t0 + off * beat + v * 0.012, s * (1 - pan))
            add(R, t0 + off * beat + v * 0.012, s * pan)
    # bass
    for off, d in [(0, 1.5), (1.5, 0.5), (2, 1.0), (3, 1.0)]:
        m = root if off != 3 else root + 7
        s = bass(midi(m), d * beat)
        add(L, t0 + off * beat, s)
        add(R, t0 + off * beat, s)
    # light melody every other 8 bars
    if (b // 8) % 2 == 1:
        for k in range(4):
            m = melody[(b % 4) * 4 + k]
            s = keys(midi(m), beat * 0.9, 0.08)
            add(L, t0 + k * beat, s * 0.6)
            add(R, t0 + k * beat, s * 0.4)
    # drums (start after the first 2 bars)
    if b >= 2:
        for off in [0, 2.5]:
            add(L, t0 + off * beat, kick())
            add(R, t0 + off * beat, kick())
        for k in range(8):
            s = shaker() * (1.0 if k % 2 else 0.5)
            add(L, t0 + k * beat / 2, s * 0.7)
            add(R, t0 + k * beat / 2, s)
    t0 += bar
    b += 1

mix = np.stack([L, R], 1)
# soft low-pass (one-pole) for a warmer sound
a = 0.25
for c in range(2):
    y = mix[:, c]
    out = np.empty_like(y)
    acc = 0.0

    for i in range(0, len(y), SR):
        seg = y[i:i + SR]
        res = np.empty_like(seg)
        for k in range(len(seg)):
            acc += a * (seg[k] - acc)
            res[k] = acc
        out[i:i + SR] = res
    mix[:, c] = out
fade = int(3 * SR)
mix[:fade] *= np.linspace(0, 1, fade)[:, None]
mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
mix /= np.abs(mix).max() / 0.8

with wave.open(os.path.join(ROOT, "public", "music.wav"), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype("<i2").tobytes())
print("music.wav", length, "s")
