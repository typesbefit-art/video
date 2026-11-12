#!/usr/bin/env python3
"""GTA 6 Shorts: вертикальное 2D-видео, целиком собранное кодом.

Этапы:  audio  -> TTS (RHVoice), тайминги слов, синтез музыки и SFX, сведение
        frames -> рендер 1800 кадров (Pillow + numpy) прямо в ffmpeg
        thumb  -> обложка thumbnail.png
        check  -> проверка длительности / fps / разрешения

    python3 build.py              # всё
    python3 build.py audio
    python3 build.py preview 0.5 4 11   # контрольные кадры в output/preview/
"""
import json, math, os, random, subprocess, sys, wave
from functools import lru_cache
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(ROOT, "assets")
OUT = os.path.join(ROOT, "output")
S = json.load(open(os.path.join(ROOT, "script.json"), encoding="utf-8"))
W, H, FPS, DUR = S["meta"]["width"], S["meta"]["height"], S["meta"]["fps"], S["meta"]["duration"]
NF = int(round(FPS * DUR))
SR = 48000

FONT_ACC = os.path.join(A, "fonts", "RussoOne-Regular.ttf")
FONT_SUB = os.path.join(A, "fonts", "Montserrat-VF.ttf")

# ---------------------------------------------------------------- palette
INK = (26, 10, 46)
PINK = (255, 46, 146)
HOT = (255, 92, 170)
TEAL = (0, 224, 208)
DTEAL = (0, 150, 160)
ORANGE = (255, 140, 40)
YELLOW = (255, 228, 77)
PURPLE = (120, 40, 200)
DPURP = (52, 18, 96)
WHITE = (255, 250, 240)
SKIN = (214, 140, 100)
SKIN2 = (242, 190, 150)

SAFE_TOP, SAFE_BOT = int(H * 0.10), int(H * 0.85)


# ================================================================= utils
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def eo(x):  # ease-out cubic
    x = clamp(x)
    return 1 - (1 - x) ** 3


def eio(x):
    x = clamp(x)
    return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2


def back(x):
    x = clamp(x)
    c1 = 1.9
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def pop(lt, delay=0.0, dur=0.38):
    x = (lt - delay) / dur
    return 0.0 if x <= 0 else back(x)


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


# ================================================================= AUDIO
def read_audio(path):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1",
                                   "-ar", str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32).copy()


def write_wav(path, x):
    x = np.clip(x, -1, 1)
    if x.ndim == 1:
        x = x[:, None]
    pcm = (x * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(pcm.shape[1]); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def env_db(x, win=0.01):
    n = int(SR * win)
    m = len(x) // n
    e = np.sqrt((x[:m * n].reshape(m, n) ** 2).mean(1) + 1e-12)
    return 20 * np.log10(e / (np.abs(x).max() + 1e-9)), n


def trim(x, th=-42):
    e, n = env_db(x)
    idx = np.where(e > th)[0]
    if not len(idx):
        return x
    a, b = max(0, idx[0] * n - int(.01 * SR)), min(len(x), (idx[-1] + 1) * n + int(.03 * SR))
    return x[a:b]


def split_words(seg):
    """[(display, spoken)] ; пустое spoken ('—|') приклеивается к предыдущему слову."""
    out = []
    for w in seg["words"]:
        disp, sp = (w.split("|", 1) + [None])[:2] if "|" in w else (w, w)
        if not sp.strip():
            out[-1] = (out[-1][0] + " " + disp, out[-1][1])
            continue
        out.append((disp, sp))
    return out


def tts(text, rate, path):
    run(["RHVoice-test", "-p", S["meta"]["voice"], "-r", str(int(rate)), "-o", path], input=text.encode())
    return trim(read_audio(path))


def syllables(s):
    return max(1, sum(ch in "аеёиоуыэюяaeiouy" for ch in s.lower()))


def word_timings(words, x, offset):
    """Пропорционально слогам + привязка концов фраз (пунктуация) к найденным паузам."""
    e, n = env_db(x)
    sil = e < -36
    gaps = []  # (start, end) пауз >= 60 мс внутри речи
    i = 0
    while i < len(sil):
        if sil[i]:
            j = i
            while j < len(sil) and sil[j]:
                j += 1
            if (j - i) * n / SR >= 0.06 and i > 0 and j < len(sil):
                gaps.append((i * n / SR, j * n / SR))
            i = j
        else:
            i += 1
    total = len(x) / SR
    wts = [syllables(sp) + 0.4 + (0.9 if sp.rstrip()[-1] in ".,!?:;" else 0) for _, sp in words]
    cum = np.concatenate([[0], np.cumsum(wts)]) / sum(wts) * total
    starts, ends = list(cum[:-1]), list(cum[1:])
    for k, (_, sp) in enumerate(words[:-1]):
        if sp.rstrip()[-1] in ".,!?:;" and gaps:
            g = min(gaps, key=lambda g: abs((g[0] + g[1]) / 2 - ends[k]))
            if abs((g[0] + g[1]) / 2 - ends[k]) < 0.45:
                ends[k], starts[k + 1] = g[0], g[1]
    # перераспределить внутри групп между якорями
    anchors = [0] + [k + 1 for k, (_, sp) in enumerate(words[:-1]) if sp.rstrip()[-1] in ".,!?:;"] + [len(words)]
    for a, b in zip(anchors[:-1], anchors[1:]):
        t0, t1 = starts[a], ends[b - 1]
        ww = wts[a:b]
        c = np.concatenate([[0], np.cumsum(ww)]) / sum(ww) * (t1 - t0) + t0
        for k in range(a, b):
            starts[k], ends[k] = c[k - a], c[k - a + 1]
            if k > a:
                starts[k] = c[k - a]
    return [{"w": d, "t0": round(offset + s, 3), "t1": round(offset + e_, 3)}
            for (d, _), s, e_ in zip(words, starts, ends)]


def synth_voice():
    os.makedirs(os.path.join(A, "voice"), exist_ok=True)
    track = np.zeros(int(SR * DUR), np.float32)
    timings = []
    for seg in S["voice"]:
        words = split_words(seg)
        text = " ".join(sp for _, sp in words)
        slot = (seg["end"] - seg["start"]) * 0.97
        p = os.path.join(A, "voice", seg["id"] + ".wav")
        rate = 100
        x = tts(text, rate, p)
        for _ in range(3):
            d = len(x) / SR
            if d <= slot and d > slot * 0.8:
                break
            rate = clamp(rate * d / slot, 95, 175)
            x = tts(text, rate, p)
        d = len(x) / SR
        if d > slot:  # последний шанс: ускорить без смены тона
            tmp = p.replace(".wav", "_fit.wav")
            write_wav(tmp, x)
            run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-af", f"atempo={d / slot:.4f}", p])
            x = trim(read_audio(p))
        print(f"  voice {seg['id']:6s} rate={rate:5.1f} dur={len(x) / SR:.2f}s slot={slot:.2f}s")
        a = int(seg["start"] * SR)
        track[a:a + len(x)] += x[:len(track) - a] / (np.abs(x).max() + 1e-9) * 0.89
        timings += [dict(t, seg=seg["id"]) for t in word_timings(words, x, seg["start"])]
    json.dump(timings, open(os.path.join(A, "voice", "timings.json"), "w"), ensure_ascii=False, indent=1)
    with open(os.path.join(ROOT, "voiceover.txt"), "w", encoding="utf-8") as f:
        for seg in S["voice"]:
            f.write(f"[{seg['start']:.2f}-{seg['end']:.2f}] " + " ".join(d for d, _ in split_words(seg)) + "\n")
    return track, timings


# --------------------------------------------------------------- music
def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def fft_filter(x, lo=None, hi=None):
    """Циклический (зацикливаемый) фильтр через FFT."""
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    g = np.ones_like(f)
    if hi:
        g *= 1 / np.sqrt(1 + (f / hi) ** 4)
    if lo:
        g *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** 4)
    return np.fft.irfft(X * (g[:, None] if x.ndim > 1 else g), n=len(x), axis=0)


def saw(ph):
    return 2 * (ph % 1.0) - 1


def synth_music():
    """Синтвейв-луп 128 BPM: 16 тактов = ровно 30 с, бесшовный."""
    rng = np.random.default_rng(7)
    N = int(SR * DUR)
    t = np.arange(N) / SR
    beat = 60 / 128
    bar = beat * 4
    out = np.zeros((N, 2))
    prog = [(45, "m"), (41, "M"), (48, "M"), (43, "M")]  # Am F C G, по 2 такта

    def chord_at(b):
        return prog[(int(b) // 2) % 4]

    # pad + bass + arp ----------------------------------------------
    pad = np.zeros((N, 2)); bass = np.zeros(N); arp = np.zeros(N)
    for b in range(16):
        root, q = chord_at(b)
        tri = [0, 3 if q == "m" else 4, 7]
        a, z = int(b * bar * SR), int((b + 1) * bar * SR)
        tt = t[a:z] - b * bar
        for k, iv in enumerate(tri + [12]):
            f = midi(root + 12 + iv)
            for ch, det in ((0, -0.08), (1, 0.08)):
                pad[a:z, ch] += saw(f * (1 + det / 100 * 12) * t[a:z] + k * .3) * 0.18
        # бас: восьмые с октавой
        for e in range(8):
            ea = a + int(e * beat / 2 * SR); ez = a + int((e + 1) * beat / 2 * SR)
            te = (np.arange(ez - ea)) / SR
            f = midi(root - 12 + (12 if e % 2 else 0))
            bass[ea:ez] += saw(f * te) * np.exp(-te * 7) * 0.9
        # арпеджио: шестнадцатые
        notes = [root + 24 + iv for iv in tri] + [root + 36]
        seq = [0, 1, 2, 3, 2, 1, 2, 3]
        for s16 in range(16):
            sa = a + int(s16 * beat / 4 * SR); sz = a + int((s16 + 1) * beat / 4 * SR)
            te = np.arange(sz - sa) / SR
            f = midi(notes[seq[s16 % 8]])
            arp[sa:sz] += np.sign(np.sin(2 * np.pi * f * te)) * np.exp(-te * 18) * 0.35
    pad = fft_filter(pad, hi=1400) * 0.55
    bass = fft_filter(bass, hi=500)
    arp = fft_filter(arp, lo=300, hi=3500)
    arp_st = np.stack([arp, arp], 1)
    d = int(beat * 0.75 * SR)
    arp_st[:, 0] += np.roll(arp, d) * 0.45
    arp_st[:, 1] += np.roll(arp, 2 * d) * 0.3

    # drums -------------------------------------------------------------
    drums = np.zeros(N)
    nbeats = 64
    for k in range(nbeats):
        a = int(k * beat * SR)
        n = int(0.35 * SR); te = np.arange(n) / SR
        f = 45 + 90 * np.exp(-te * 30)
        kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-te * 9)
        idx = (a + np.arange(n)) % N
        drums[idx] += kick * 1.0
        if k % 2 == 1:  # снейр
            n2 = int(0.25 * SR); te2 = np.arange(n2) / SR
            sn = (rng.standard_normal(n2) * 0.6 + np.sin(2 * np.pi * 190 * te2) * 0.5) * np.exp(-te2 * 16)
            drums[(a + np.arange(n2)) % N] += fft_filter(sn, lo=200, hi=6000) * 0.7
        for h in (0.5,):  # хэт на офбит
            ha = a + int(h * beat * SR); n3 = int(0.06 * SR); te3 = np.arange(n3) / SR
            hh = rng.standard_normal(n3) * np.exp(-te3 * 70)
            drums[(ha + np.arange(n3)) % N] += hh * 0.25
    drums = fft_filter(drums, hi=9000)
    # сайдчейн-«дыхание» пэда от бочки
    pump = 1 - 0.45 * np.exp(-((t % beat) / 0.12))
    out += pad * pump[:, None] + bass[:, None] * 0.55 * pump[:, None] + arp_st * 0.32 + drums[:, None] * 0.55
    # простая циклическая реверберация
    rev = np.zeros_like(out)
    for dl, g in ((0.031, .3), (0.047, .25), (0.071, .2), (0.113, .15), (0.173, .1)):
        rev[:, 0] += np.roll(out[:, 0], int(dl * SR)) * g
        rev[:, 1] += np.roll(out[:, 1], int(dl * 1.13 * SR)) * g
    out += fft_filter(rev, hi=4000) * 0.5
    out /= np.abs(out).max() + 1e-9
    return out


# --------------------------------------------------------------- sfx
def sfx_track(timings):
    rng = np.random.default_rng(3)
    N = int(SR * DUR)
    tr = np.zeros(N)

    def put(sig, at, g=1.0):
        a = int(at * SR)
        if a < 0:
            sig = sig[-a:]; a = 0
        n = min(len(sig), N - a)
        if n > 0:
            tr[a:a + n] += sig[:n] * g

    def whoosh(d=0.35):
        n = int(d * SR); te = np.arange(n) / SR
        noise = rng.standard_normal(n)
        env = np.sin(np.pi * te / d) ** 2
        lo = fft_filter(noise, lo=400, hi=1200); hi_ = fft_filter(noise, lo=1500, hi=5000)
        m = te / d
        return (lo * (1 - m) + hi_ * m) * env * 1.2

    def impact():
        n = int(0.5 * SR); te = np.arange(n) / SR
        f = 40 + 120 * np.exp(-te * 25)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-te * 6) + \
            fft_filter(rng.standard_normal(n), hi=3000) * np.exp(-te * 20) * 0.5

    def glitch():
        n = int(0.22 * SR)
        x = np.repeat(rng.standard_normal(n // 60 + 1), 60)[:n]
        x *= (np.sin(np.arange(n) / SR * 2 * np.pi * 37) > 0)
        return fft_filter(x, lo=300, hi=7000) * 0.6

    def popsnd(f0=900):
        n = int(0.12 * SR); te = np.arange(n) / SR
        f = f0 * np.exp(-te * 10) + 200
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-te * 30) * 0.8

    def tick():
        n = int(0.05 * SR); te = np.arange(n) / SR
        return np.sin(2 * np.pi * 2200 * te) * np.exp(-te * 120) + rng.standard_normal(n) * np.exp(-te * 200) * .3

    def ding():
        n = int(0.9 * SR); te = np.arange(n) / SR
        return sum(np.sin(2 * np.pi * f * te) * a for f, a in ((1320, .6), (1980, .3), (2640, .15))) * np.exp(-te * 4)

    for sc in S["scenes"][1:]:
        kind, at = sc["in"], sc["start"]
        if kind == "whip":
            put(whoosh(), at - 0.2, .5)
        elif kind == "zoom":
            put(whoosh(0.25), at - 0.22, .35); put(impact(), at, .45)
        elif kind == "glitch":
            put(glitch(), at - 0.08, .4)
    # pop-ins акцентов
    for sc in S["scenes"]:
        for i, _ in enumerate(sc.get("accent", [])):
            put(popsnd(900 + 200 * i), sc["start"] + 0.12 + 0.18 * i, .25)
    put(tick(), 0.5, .5)                      # перелистывание 8 -> 7
    sub = next(s for s in S["scenes"] if s["id"] == "subscribe")
    put(tick() * 2, sub["start"] + 1.3, .6)   # клик
    put(ding(), sub["start"] + 1.4, .3)
    return tr


def build_audio():
    print("[audio] TTS ...")
    voice, timings = synth_voice()
    print("[audio] music + sfx ...")
    music = synth_music()
    sfx = sfx_track(timings)
    # ducking музыки под голос
    win = int(0.05 * SR)
    v2 = np.convolve(voice ** 2, np.ones(win) / win, mode="same")
    env = np.sqrt(v2)
    env = np.convolve(env, np.ones(int(.25 * SR)) / int(.25 * SR), mode="same")
    env = np.clip(env / (env.max() * 0.35 + 1e-9), 0, 1)
    duck = 1 - 0.6 * env
    mus_gain = 10 ** (-17 / 20)  # музыка тихая, под голос
    mixd = music * (mus_gain * duck)[:, None] + voice[:, None] + sfx[:, None]
    mixd = np.tanh(mixd * 1.1) / np.tanh(1.1)
    write_wav(os.path.join(A, "music_loop.wav"), music * 0.7)
    write_wav(os.path.join(A, "voice_track.wav"), voice)
    write_wav(os.path.join(A, "mix.wav"), mixd)
    print("[audio] ok ->", os.path.join(A, "mix.wav"))


# ================================================================= GRAPHICS
class Pen:
    """Рисование с суперсэмплингом x2: толстые контуры, сглаживание при уменьшении."""

    def __init__(s, w, h, ss=2):
        s.w, s.h, s.ss = w, h, ss
        s.im = Image.new("RGBA", (int(w * ss), int(h * ss)), (0, 0, 0, 0))
        s.d = ImageDraw.Draw(s.im)

    def P(s, pts):
        return [(x * s.ss, y * s.ss) for x, y in pts]

    def B(s, box):
        return [v * s.ss for v in box]

    def stroke(s, p, ow, oc, closed=False):
        if closed:
            p = p + [p[0], p[1]] if len(p) > 1 else p
        w = max(1, int(ow * s.ss))
        s.d.line(p, fill=oc, width=w, joint="curve")
        r = w / 2
        for x, y in (p if not closed else p[:-1]):
            s.d.ellipse((x - r, y - r, x + r, y + r), fill=oc)

    def poly(s, pts, fill, ow=7, oc=INK):
        p = s.P(pts)
        s.d.polygon(p, fill=fill)
        if ow:
            s.stroke(p, ow, oc, closed=True)

    def line(s, pts, col=INK, w=7):
        s.stroke(s.P(pts), w, col)

    def ell(s, box, fill, ow=7, oc=INK):
        s.d.ellipse(s.B(box), fill=fill, outline=oc if ow else None, width=int(ow * s.ss))

    def rect(s, box, fill, ow=7, oc=INK, r=0):
        s.d.rounded_rectangle(s.B(box), radius=r * s.ss, fill=fill, outline=oc if ow else None,
                              width=int(ow * s.ss))

    def arc(s, box, a0, a1, col=INK, w=7):
        s.d.arc(s.B(box), a0, a1, fill=col, width=int(w * s.ss))

    def chord(s, box, a0, a1, fill, ow=7, oc=INK):
        s.d.chord(s.B(box), a0, a1, fill=fill, outline=oc if ow else None, width=int(ow * s.ss))

    def text(s, xy, txt, size, fill, font=FONT_ACC, anchor="mm", stroke=0, sc=INK):
        f = font_(font, int(size * s.ss))
        s.d.text((xy[0] * s.ss, xy[1] * s.ss), txt, font=f, fill=fill, anchor=anchor,
                 stroke_width=int(stroke * s.ss), stroke_fill=sc)

    def img(s):
        return s.im.resize((int(s.w), int(s.h)), Image.LANCZOS)


@lru_cache(maxsize=64)
def font_(path, size, var="Black"):
    f = ImageFont.truetype(path, size)
    if path == FONT_SUB:
        f.set_variation_by_name(var)
    return f


def bez(p0, p1, p2, n=16):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in np.linspace(0, 1, n)]


def ribbon(center, w0, w1):
    """Полигон-лента вдоль ломаной с шириной w0 -> w1 (стволы, листья)."""
    L, R = [], []
    n = len(center)
    for i, (x, y) in enumerate(center):
        a = center[max(0, i - 1)]; b = center[min(n - 1, i + 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        l = math.hypot(dx, dy) or 1
        nx, ny = -dy / l, dx / l
        w = lerp(w0, w1, i / (n - 1)) / 2
        L.append((x + nx * w, y + ny * w)); R.append((x - nx * w, y - ny * w))
    return L + R[::-1]


def composite(cv, im, x, y):
    """alpha_composite с обрезкой за краями."""
    w, h = im.size
    x0, y0 = int(round(x)), int(round(y))
    sx, sy = max(0, -x0), max(0, -y0)
    ex, ey = min(w, cv.width - x0), min(h, cv.height - y0)
    if ex <= sx or ey <= sy:
        return
    cv.alpha_composite(im, (x0 + sx, y0 + sy), (sx, sy, ex, ey))


def paste(cv, im, cx, cy, s=1.0, rot=0.0, alpha=1.0, sx=1.0, sy=1.0):
    if s <= 0.01 or alpha <= 0.01:
        return
    w, h = im.size
    nw, nh = max(1, int(w * s * sx)), max(1, int(h * s * sy))
    if (nw, nh) != (w, h):
        im = im.resize((nw, nh), Image.BILINEAR)
    if abs(rot) > 0.05:
        im = im.rotate(rot, Image.BILINEAR, expand=True)
    if alpha < 1:
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    composite(cv, im, cx - im.width / 2, cy - im.height / 2)


@lru_cache(maxsize=256)
def text_img(txt, size, fill=WHITE, font=FONT_ACC, stroke=12, shadow=12, shcol=PINK, glow=None, var="Black"):
    f = font_(font, size, var)
    bb = f.getbbox(txt, stroke_width=stroke)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    gp = 30 if glow else 0
    pad = stroke + gp + 4
    im = Image.new("RGBA", (w + 2 * pad, h + 2 * pad + shadow), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ox, oy = pad - bb[0], pad - bb[1]
    if glow:
        g = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).text((ox, oy), txt, font=f, fill=glow, stroke_width=stroke + 6, stroke_fill=glow)
        g = g.filter(ImageFilter.GaussianBlur(18))
        im.alpha_composite(g); im.alpha_composite(g)
    if shadow:
        d.text((ox, oy + shadow), txt, font=f, fill=shcol, stroke_width=stroke, stroke_fill=INK)
    d.text((ox, oy), txt, font=f, fill=fill, stroke_width=stroke, stroke_fill=INK)
    return im


def fit_size(txt, size, maxw=980, font=FONT_ACC, stroke=12):
    while size > 30:
        bb = font_(font, size).getbbox(txt, stroke_width=stroke)
        if bb[2] - bb[0] <= maxw:
            return size
        size -= 4
    return size


def accent(cv, txt, cx, cy, lt, delay=0.1, size=170, fill=YELLOW, shcol=PINK, glow=None, out=None, rot=0):
    s = pop(lt, delay)
    if out is not None:
        s *= 1 - eio((lt - out) / 0.3)
    if s <= 0.01:
        return
    size = fit_size(txt, size)
    im = text_img(txt, size, fill, FONT_ACC, 12, 12, shcol, glow)
    wob = math.sin(lt * 6 + cy) * 1.2 + rot
    paste(cv, im, cx, cy, s, wob)


# ----------------------------------------------------------------- assets
G = {}


def build_assets():
    if G:
        return
    rnd = random.Random(11)
    # --- небо заката
    y = np.linspace(0, 1, H)[:, None]
    stops = [(0.0, (30, 10, 70)), (0.30, (95, 28, 140)), (0.50, (220, 55, 150)), (0.62, (255, 100, 120)),
             (0.70, (255, 160, 80)), (1.0, (255, 190, 90))]
    sky = np.zeros((H, W, 3))
    for (a, ca), (b, cb) in zip(stops[:-1], stops[1:]):
        m = ((y >= a) & (y <= b)).astype(float)
        k = np.clip((y - a) / (b - a), 0, 1)
        for c in range(3):
            sky[..., c] += m[:, 0:1] * (ca[c] + (cb[c] - ca[c]) * k)
    sky = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8)).convert("RGBA")
    pn = Pen(W, H)
    for _ in range(70):  # звёзды
        x, yy = rnd.uniform(0, W), rnd.uniform(0, H * 0.35)
        r = rnd.uniform(1.5, 4)
        pn.ell((x - r, yy - r, x + r, yy + r), (255, 240, 255, 220), 0)
    # солнце в полоску
    cx, cy, R = 540, 1010, 300
    sun = Pen(2 * R, 2 * R)
    for i in range(2 * R):
        col = mix((255, 236, 110), (255, 90, 140), i / (2 * R))
        sun.d.line([(0, i * 2), (4 * R, i * 2)], fill=col + (255,), width=2)
    mask = Image.new("L", (4 * R, 4 * R), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, 4 * R, 4 * R), fill=255)
    for k in range(7):
        yy = 4 * R * 0.52 + k * (4 * R * 0.07)
        md.rectangle((0, yy, 4 * R, yy + 6 + k * 5), fill=0)
    sun.im.putalpha(mask)
    sky.alpha_composite(pn.img())
    sglow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sglow).ellipse((cx - R - 90, cy - R - 90, cx + R + 90, cy + R + 90), fill=(255, 120, 160, 120))
    sky.alpha_composite(sglow.filter(ImageFilter.GaussianBlur(60)))
    composite(sky, sun.img(), cx - R, cy - R)
    G["sky"] = sky

    HOR = 1300  # линия дороги
    G["hor"] = HOR

    # --- дальний город
    def city(wd, seed, col, hmin, hmax, wmin, wmax, base, winc, ow=6):
        r = random.Random(seed)
        p = Pen(wd, H)
        x = -20
        while x < wd:
            bw = r.randint(wmin, wmax); bh = r.randint(hmin, hmax)
            top = base - bh
            kind = r.random()
            p.rect((x, top, x + bw, base + 40), col, ow)
            if kind < 0.25:  # антенна
                p.line([(x + bw / 2, top), (x + bw / 2, top - 60)], INK, 5)
                p.ell((x + bw / 2 - 7, top - 70, x + bw / 2 + 7, top - 56), PINK, 3)
            elif kind < 0.45:  # ступенчатый верх (ар-деко)
                p.rect((x + bw * .2, top - 40, x + bw * .8, top + 5), col, ow)
                p.rect((x + bw * .35, top - 75, x + bw * .65, top - 35), col, ow)
            for wy in range(top + 25, base - 20, 34):
                for wx in range(int(x + 14), int(x + bw - 18), 26):
                    if r.random() < 0.5:
                        p.rect((wx, wy, wx + 12, wy + 16), r.choice(winc), 0)
            x += bw + r.randint(-10, 18)
        return p.img()

    G["far"] = city(1700, 1, (88, 34, 140), 240, 560, 90, 170, HOR - 120,
                    [(255, 210, 120, 255), (120, 255, 240, 255), (255, 140, 200, 255)], 5)
    G["mid"] = city(2100, 2, (52, 18, 96), 160, 420, 130, 230, HOR - 10,
                    [(255, 230, 120, 255), (0, 224, 208, 255), (255, 46, 146, 255)], 7)

    # неоновые вывески на средний план
    def neon(txt, col, size=58):
        im = text_img(txt, size, WHITE, FONT_ACC, 4, 0, INK, glow=col + (255,))
        return im
    G["neons"] = [(neon("ОТЕЛЬ", PINK), 260, HOR - 300), (neon("24/7", TEAL), 900, HOR - 250),
                  (neon("КЛУБ", ORANGE), 1500, HOR - 330), (neon("ПЛЯЖ", TEAL), 1900, HOR - 230)]

    # --- пальма
    def palm(h=900, lean=60, seed=0):
        r = random.Random(seed)
        p = Pen(700, h + 120)
        base = (350, h + 100); top = (350 + lean, 200)
        trunk = bez(base, (350 - lean * .4, h * .5), top, 20)
        p.poly(ribbon(trunk, 56, 30), (120, 52, 92), 7)
        for i in range(2, 19, 2):  # кольца ствола
            (x0, y0), (x1, y1) = trunk[i - 1], trunk[i + 1]
            p.line([(trunk[i][0] - 22 + i * .6, trunk[i][1]), (trunk[i][0] + 22 - i * .6, trunk[i][1] + 4)], INK, 4)
        tx, ty = top
        for ang in (-170, -135, -100, -60, -25, 10, 40, -80):
            a = math.radians(ang + r.uniform(-8, 8))
            L = r.uniform(230, 300)
            end = (tx + math.cos(a) * L, ty + math.sin(a) * L * .55 + 90)
            ctrl = (tx + math.cos(a) * L * .55, ty + math.sin(a) * L * .5 - 70)
            c = bez((tx, ty), ctrl, end, 14)
            p.poly(ribbon(c, 70, 4), (24, 120, 110) if r.random() < .5 else (16, 96, 100), 7)
            p.line(c[:-2], (40, 170, 140), 3)
        for k in range(3):
            p.ell((tx - 30 + k * 22, ty + 10, tx - 4 + k * 22, ty + 36), (110, 60, 40), 5)
        return p.img()

    G["palm"] = palm(880, 70, 1)
    G["palm2"] = palm(760, -60, 2)
    # --- машина (ретро-спорткар, вид сбоку)
    p = Pen(640, 240)
    body = [(18, 160), (30, 118), (210, 98), (300, 48), (430, 44), (510, 92), (612, 108), (624, 150),
            (604, 178), (30, 178)]
    p.poly(body, TEAL, 8)
    p.poly([(312, 58), (422, 55), (478, 94), (282, 100)], (40, 20, 80), 6)
    p.line([(380, 56), (372, 98)], INK, 7)
    p.line([(318, 64), (300, 90)], (160, 240, 255), 5)
    p.poly([(40, 132), (600, 124), (604, 138), (40, 146)], PINK, 0)
    p.line([(40, 132), (600, 124)], INK, 3); p.line([(40, 146), (604, 138)], INK, 3)
    p.rect((596, 112, 622, 124), YELLOW, 4, r=3)      # фара
    p.rect((20, 124, 40, 140), (255, 40, 80), 4, r=3)  # стоп-сигнал
    p.ell((90, 120, 200, 230), INK, 0); p.ell((460, 120, 570, 230), INK, 0)  # арки
    p.poly([(520, 95), (560, 70), (580, 72), (552, 100)], TEAL, 5)  # зеркало-спойлер
    G["car"] = p.img()
    w = Pen(110, 110)
    w.ell((4, 4, 106, 106), (30, 14, 50), 6)
    w.ell((26, 26, 84, 84), (210, 210, 230), 5)
    for k in range(5):
        a = math.radians(k * 72)
        w.line([(55, 55), (55 + math.cos(a) * 26, 55 + math.sin(a) * 26)], INK, 6)
    w.ell((47, 47, 63, 63), PINK, 4)
    G["wheel"] = w.img()

    G["hero"] = hero_sprite()
    G["hero2"] = hero2_sprite()
    G["arm"] = arm_sprite()
    G["pad_pink"] = gamepad_sprite(PINK)
    G["pad_teal"] = gamepad_sprite(TEAL)
    G["monitor"] = monitor_sprite()
    G["trophy"] = trophy_sprite()
    G["map"] = map_sprite()
    G["pin"] = pin_sprite(PINK)
    G["pin2"] = pin_sprite(ORANGE)
    G["bell"] = bell_sprite()
    G["cursor"] = cursor_sprite()
    G["cal"] = calendar_sprite()
    for d in "78":
        G["card" + d] = card_sprite(d)
    # виньетка
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / (W * .75)) ** 2 + ((yy - H / 2) / (H * .62)) ** 2)
    a = (np.clip(r - 0.55, 0, 1) ** 1.6 * 300).clip(0, 150).astype(np.uint8)
    v = np.zeros((H, W, 4), np.uint8); v[..., :3] = INK; v[..., 3] = a
    G["vign"] = Image.fromarray(v, "RGBA")
    # полутон
    ht = Pen(W + 120, H + 120, 1)
    for yy_ in range(0, H + 120, 40):
        for xx_ in range(0, W + 120, 40):
            o = 20 if (yy_ // 40) % 2 else 0
            ht.d.ellipse((xx_ + o - 6, yy_ - 6, xx_ + o + 6, yy_ + 6), fill=(255, 46, 146, 60))
    G["halftone"] = ht.im


def hero_sprite():
    """Оригинальный герой: кепка, очки-авиаторы, гавайская рубашка."""
    p = Pen(520, 720)
    # торс
    p.poly([(40, 720), (60, 560), (130, 490), (390, 490), (460, 560), (480, 720)], ORANGE, 8)
    for (x, y) in [(110, 600), (200, 660), (330, 590), (400, 670), (160, 540), (290, 690), (420, 560)]:
        p.ell((x - 18, y - 18, x + 18, y + 18), PINK, 4)
        p.ell((x - 6, y - 6, x + 6, y + 6), YELLOW, 0)
    p.poly([(200, 490), (260, 590), (320, 490)], (240, 230, 220), 7)  # майка под рубашкой
    p.poly([(170, 490), (230, 560), (200, 600), (150, 500)], (255, 170, 80), 6)  # воротник
    p.poly([(350, 490), (290, 560), (320, 600), (370, 500)], (255, 170, 80), 6)
    # шея и голова
    p.rect((215, 400, 305, 510), SKIN, 7, r=20)
    p.ell((130, 330, 175, 400), SKIN, 7); p.ell((345, 330, 390, 400), SKIN, 7)  # уши
    p.ell((150, 170, 370, 470), SKIN, 8)
    # кепка
    p.chord((140, 140, 380, 360), 180, 360, PINK, 8)
    p.poly([(330, 236), (470, 248), (470, 270), (300, 262)], (220, 30, 120), 8)  # козырёк
    p.ell((240, 170, 280, 210), TEAL, 5)
    p.line([(142, 250), (378, 250)], INK, 8)
    # очки
    p.rect((170, 285, 255, 345), (40, 20, 80), 7, r=22)
    p.rect((275, 285, 360, 345), (40, 20, 80), 7, r=22)
    p.line([(255, 300), (275, 300)], INK, 7)
    p.line([(186, 300), (206, 318)], TEAL, 6); p.line([(291, 300), (311, 318)], TEAL, 6)
    # улыбка и щетина
    p.arc((225, 365, 325, 425), 20, 150, INK, 8)
    p.line([(258, 340), (250, 375), (268, 378)], (170, 100, 70), 5)
    return p.img()


def hero2_sprite():
    """Второй оригинальный герой: каре, круглые очки, серьги-кольца, куртка."""
    p = Pen(520, 720)
    p.poly([(40, 720), (70, 560), (140, 490), (380, 490), (450, 560), (480, 720)], TEAL, 8)
    p.poly([(190, 490), (260, 640), (330, 490)], (40, 20, 80), 7)
    p.poly([(140, 490), (250, 620), (210, 660), (110, 530)], (0, 180, 170), 6)
    p.poly([(380, 490), (270, 620), (310, 660), (410, 530)], (0, 180, 170), 6)
    p.rect((225, 410, 295, 510), SKIN2, 7, r=20)
    # волосы сзади
    p.rect((120, 170, 400, 470), PURPLE, 8, r=110)
    p.ell((150, 180, 370, 470), SKIN2, 8)
    # чёлка
    p.chord((130, 140, 390, 360), 180, 360, PURPLE, 8)
    p.poly([(140, 250), (380, 250), (390, 300), (300, 262), (200, 280), (130, 300)], PURPLE, 0)
    p.line([(140, 252), (200, 280), (300, 262), (385, 300)], INK, 7)
    # серьги
    p.ell((136, 380, 172, 430), None, 7, YELLOW); p.ell((348, 380, 384, 430), None, 7, YELLOW)
    # очки
    p.ell((180, 300, 255, 370), (255, 120, 190), 7); p.ell((268, 300, 343, 370), (255, 120, 190), 7)
    p.line([(255, 330), (268, 330)], INK, 7)
    p.line([(200, 318), (215, 335)], WHITE, 5); p.line([(288, 318), (303, 335)], WHITE, 5)
    p.arc((230, 380, 300, 430), 15, 165, INK, 8)
    p.line([(258, 368), (252, 392), (266, 394)], (200, 130, 100), 5)
    return p.img()


def arm_sprite():
    """Машущая рука; точка плеча = центр картинки (удобно вращать)."""
    p = Pen(480, 480)
    p.poly(ribbon([(240, 250), (262, 100), (276, 60)], 54, 46), SKIN, 8)       # предплечье
    p.poly(ribbon([(236, 270), (246, 200), (252, 160)], 96, 84), ORANGE, 8)    # рукав
    p.ell((262, 176, 284, 198), PINK, 4)
    for k, (x, h) in enumerate([(252, 46), (270, 56), (288, 54), (306, 42)]):
        p.rect((x - 9, 40 - h, x + 9, 50), SKIN, 6, r=9)                      # пальцы
    p.poly(ribbon([(250, 62), (226, 40), (214, 26)], 22, 18), SKIN, 6)        # большой палец
    p.ell((240, 22, 318, 92), SKIN, 7)                                         # ладонь
    p.d.rectangle(p.B((246, 30, 312, 46)), fill=SKIN)
    p.arc((262, 50, 296, 76), 20, 160, (170, 100, 70), 4)
    return p.img()


def gamepad_sprite(col):
    p = Pen(520, 340)
    dark = mix(col, INK, .35)
    p.ell((10, 120, 200, 330), col, 8)
    p.ell((320, 120, 510, 330), col, 8)
    p.rect((60, 60, 460, 250), col, 8, r=90)
    p.d.rectangle(p.B((70, 130, 450, 245)), fill=col)
    p.ell((24, 134, 186, 316), col, 0); p.ell((334, 134, 496, 316), col, 0)
    p.rect((95, 125, 175, 155), dark, 5, r=6); p.rect((120, 100, 150, 180), dark, 5, r=6)
    p.d.rectangle(p.B((123, 128, 147, 152)), fill=dark)
    for (x, y, c) in [(385, 105, YELLOW), (425, 140, PINK if col != PINK else TEAL), (345, 140, WHITE),
                      (385, 175, ORANGE)]:
        p.ell((x - 20, y - 20, x + 20, y + 20), c, 5)
    p.ell((160, 190, 230, 260), INK, 0); p.ell((170, 200, 220, 250), dark, 5)
    p.ell((290, 190, 360, 260), INK, 0); p.ell((300, 200, 350, 250), dark, 5)
    p.rect((225, 110, 295, 135), WHITE, 5, r=10)
    return p.img()


def monitor_sprite():
    p = Pen(700, 620)
    p.poly([(300, 480), (400, 480), (430, 580), (270, 580)], (90, 50, 140), 8)
    p.rect((180, 570, 520, 605), (90, 50, 140), 8, r=12)
    p.rect((10, 10, 690, 500), (70, 34, 120), 9, r=30)
    p.rect((44, 44, 656, 450), (16, 8, 34), 7, r=12)
    p.ell((340, 466, 360, 486), TEAL, 4)
    return p.img()


def trophy_sprite():
    p = Pen(520, 640)
    gold, dg = (255, 205, 60), (220, 150, 30)
    p.arc((10, 60, 170, 300), 90, 270, INK, 30); p.arc((10, 60, 170, 300), 90, 270, gold, 16)
    p.arc((350, 60, 510, 300), 270, 90, INK, 30); p.arc((350, 60, 510, 300), 270, 90, gold, 16)
    p.poly([(80, 40), (440, 40), (420, 220), (330, 330), (190, 330), (100, 220)], gold, 9)
    p.poly([(120, 60), (170, 60), (180, 250), (150, 220)], (255, 240, 160), 0)
    p.rect((220, 320, 300, 430), dg, 8)
    p.rect((130, 420, 390, 500), dg, 9, r=10)
    p.rect((90, 495, 430, 600), (90, 50, 140), 9, r=12)
    p.text((260, 548), "№1", 70, YELLOW, stroke=4)
    star = [(260 + math.cos(math.radians(-90 + i * 36)) * (70 if i % 2 == 0 else 30),
             170 + math.sin(math.radians(-90 + i * 36)) * (70 if i % 2 == 0 else 30)) for i in range(10)]
    p.poly(star, WHITE, 6)
    return p.img()


MAP_PTS = [(120, 60), (330, 40), (520, 70), (560, 120), (520, 180), (470, 200), (500, 300), (560, 420),
           (600, 560), (610, 690), (580, 800), (530, 860), (480, 850), (440, 760), (380, 640), (330, 520),
           (300, 400), (250, 300), (200, 230), (110, 200), (60, 140)]


def map_sprite():
    p = Pen(680, 920)
    p.poly([(x + 14, y + 16) for x, y in MAP_PTS], (0, 90, 110), 0)
    p.poly(MAP_PTS, (255, 176, 80), 9)
    p.poly([(x * 0.86 + 50, y * 0.9 + 40) for x, y in MAP_PTS[4:16]] + [(330, 300), (360, 160)], (120, 210, 120), 0)
    for k, (x, y) in enumerate([(200, 120), (420, 110), (380, 330), (470, 520), (520, 690)]):
        p.ell((x - 8, y - 8, x + 8, y + 8), (60, 140, 90), 0)
    # острова
    for i in range(5):
        x, y = 470 - i * 55, 900 - i * 10
        p.ell((x - 18, y - 10, x + 18, y + 10), (255, 176, 80), 5)
    return p.img()


def pin_sprite(col):
    p = Pen(120, 160)
    p.poly([(60, 155), (18, 80), (102, 80)], col, 0)
    p.ell((10, 6, 110, 106), col, 0)
    p.line([(20, 82), (60, 154), (100, 82)], INK, 7)
    p.arc((10, 6, 110, 106), 150, 30 + 360, INK, 7)
    p.ell((38, 34, 82, 78), WHITE, 6)
    return p.img()


def bell_sprite():
    p = Pen(200, 220)
    p.poly([(100, 20), (150, 50), (160, 140), (185, 170), (15, 170), (40, 140), (50, 50)], YELLOW, 8)
    p.ell((78, 160, 122, 205), YELLOW, 8)
    p.ell((88, 4, 112, 28), YELLOW, 6)
    p.line([(70, 60), (66, 120)], WHITE, 7)
    return p.img()


def cursor_sprite():
    p = Pen(140, 180)
    p.poly([(10, 10), (10, 150), (45, 118), (70, 170), (95, 158), (70, 108), (118, 104)], WHITE, 8)
    return p.img()


def calendar_sprite():
    p = Pen(540, 600)
    p.rect((20, 40, 520, 580), (255, 246, 232), 9, r=40)
    p.rect((20, 40, 520, 190), PINK, 9, r=40)
    p.d.rectangle(p.B((26, 140, 514, 186)), fill=PINK)
    p.line([(24, 190), (516, 190)], INK, 9)
    for x in (150, 390):
        p.rect((x - 16, 0, x + 16, 80), (120, 120, 140), 7, r=14)
    p.text((270, 118), "НОЯБРЬ", 72, WHITE, stroke=5)
    p.text((270, 375), "19", 250, (40, 20, 80))
    p.text((270, 530), "ЧЕТВЕРГ", 50, (255, 92, 170))
    return p.img()


def card_sprite(d):
    p = Pen(400, 470)
    p.rect((10, 10, 390, 460), (60, 22, 110), 10, r=40)
    p.rect((10, 10, 390, 235), (86, 32, 150), 0, r=40)
    p.d.rectangle(p.B((14, 150, 386, 235)), fill=(86, 32, 150))
    p.text((200, 240), d, 380, YELLOW, stroke=10)
    p.line([(14, 235), (386, 235)], INK, 8)
    for y in (225,):
        p.ell((0, y - 12, 26, y + 22), INK, 0); p.ell((374, y - 12, 400, y + 22), INK, 0)
    p.rect((10, 10, 390, 460), None, 10, PINK, r=40)
    return p.img()


# ----------------------------------------------------------------- backgrounds
def city_bg(cv, camx, t, neons=True):
    cv.alpha_composite(G["sky"])
    hor = G["hor"]
    for key, f, yoff in (("far", 0.15, 0), ("mid", 0.35, 0)):
        im = G[key]
        x = -((camx * f) % (im.width - W)) if im.width > W else 0
        composite(cv, im, x - 0, yoff)
        if key == "mid" and neons:
            for nim, nx, ny in G["neons"]:
                flick = 0.75 + 0.25 * math.sin(t * 2 * math.pi * 3 + nx)
                paste(cv, nim, nx + x, ny, 1.0, 0, flick)
    d = ImageDraw.Draw(cv)
    # дорога
    d.rectangle((0, hor, W, H), fill=(44, 18, 74))
    d.rectangle((0, hor, W, hor + 10), fill=INK)
    d.rectangle((0, hor + 10, W, hor + 26), fill=(255, 92, 170))
    d.rectangle((0, hor + 26, W, hor + 34), fill=INK)
    off = -(camx * 1.0) % 220
    for k in range(-1, 7):
        x = k * 220 + off - 220
        d.rounded_rectangle((x, hor + 78, x + 120, hor + 92), 6, fill=YELLOW)
    d.rectangle((0, hor + 300, W, H), fill=(30, 12, 56))
    d.rectangle((0, hor + 292, W, hor + 300), fill=INK)
    # пальмы (параллакс ближе)
    off2 = -(camx * 0.7)
    for k, (key, px, s) in enumerate((("palm", 120, 1.0), ("palm2", 820, 0.9), ("palm", 1400, 1.05),
                                       ("palm2", 1950, 0.95))):
        x = ((px + off2) % 2400) - 300
        im = G[key]
        paste(cv, im, x, hor + 40 - im.height * s / 2, s)


def sunburst(cv, c1, c2, rot, cx=540, cy=900, n=18):
    d = ImageDraw.Draw(cv)
    d.rectangle((0, 0, W, H), fill=c1)
    R = 2400
    for k in range(n):
        a0 = math.radians(rot + k * 360 / n); a1 = math.radians(rot + (k + .5) * 360 / n)
        d.polygon([(cx, cy), (cx + math.cos(a0) * R, cy + math.sin(a0) * R),
                   (cx + math.cos(a1) * R, cy + math.sin(a1) * R)], fill=c2)


def stripes(cv, c1, c2, off, w=110):
    d = ImageDraw.Draw(cv)
    d.rectangle((0, 0, W, H), fill=c1)
    o = off % (2 * w)
    for x in range(-H - 2 * w, W + 2 * w, 2 * w):
        x0 = x + o
        d.polygon([(x0, 0), (x0 + w, 0), (x0 + w + H * .5, H), (x0 + H * .5, H)], fill=c2)


def grid_floor(cv, top_col, bot_col, line_col, t, horizon=980, speed=1.0):
    d = ImageDraw.Draw(cv)
    for y in range(0, horizon, 8):
        d.rectangle((0, y, W, y + 8), fill=mix(top_col, bot_col, y / horizon))
    d.rectangle((0, horizon, W, H), fill=(22, 8, 44))
    for k in range(-12, 13):
        d.line([(540 + k * 40, horizon), (540 + k * 260, H)], fill=line_col, width=4)
    ph = (t * speed) % 1.0
    for i in range(14):
        z = (i + ph) / 14
        y = horizon + (H - horizon) * z ** 2.2
        d.line([(0, y), (W, y)], fill=line_col, width=max(2, int(6 * z)))
    d.rectangle((0, horizon - 3, W, horizon + 3), fill=PINK)


def badge(cv, num, lt, cx=150, cy=318):
    s = pop(lt, 0.0, 0.32)
    if s <= .01:
        return
    im = badge_img(num)
    paste(cv, im, cx, cy, s, math.sin(lt * 5) * 5)


@lru_cache(maxsize=4)
def badge_img(num):
    p = Pen(220, 230)
    p.ell((10, 10, 210, 210), PINK, 9)
    p.ell((26, 26, 194, 194), None, 5, WHITE)
    p.text((110, 104), num, 120, WHITE, stroke=7)
    p.rect((40, 170, 180, 222), YELLOW, 7, r=14)
    p.text((110, 196), "ФАКТ", 34, INK)
    return p.img()


def confetti(cv, lt, seed=1, n=46, area=(0, 0, W, 1300), t0=0.1):
    r = random.Random(seed)
    d = ImageDraw.Draw(cv)
    cols = [PINK, TEAL, YELLOW, ORANGE, WHITE]
    for i in range(n):
        x0 = r.uniform(area[0], area[2]); vy = r.uniform(250, 520); vx = r.uniform(-120, 120)
        delay = r.uniform(0, .5); sp = r.uniform(4, 12)
        tt = lt - t0 - delay
        if tt < 0:
            continue
        x = x0 + vx * tt; y = area[1] - 40 + vy * tt
        if y > area[3]:
            continue
        a = sp * tt + i
        s = 14
        pts = [(x + math.cos(a + k * math.pi / 2) * s * (1 if k % 2 else .5),
                y + math.sin(a + k * math.pi / 2) * s * (1 if k % 2 else .5)) for k in range(4)]
        d.polygon(pts, fill=cols[i % 5], outline=INK)


def sparkle(cv, x, y, s, col=WHITE):
    if s <= 0:
        return
    d = ImageDraw.Draw(cv)
    pts = []
    for k in range(8):
        r = s if k % 2 == 0 else s * .28
        a = math.pi / 4 * k
        pts.append((x + math.cos(a) * r, y + math.sin(a) * r))
    d.polygon(pts, fill=col, outline=INK, width=3)


def car(cv, x, y, wheel_ang=0.0, s=1.0, bob=0.0):
    im = G["car"]
    paste(cv, im, x, y + bob, s)
    wh = G["wheel"]
    for wx in (145, 515):
        paste(cv, wh, x + (wx - im.width / 2) * s, y + (175 - im.height / 2) * s, s, -wheel_ang)


# ----------------------------------------------------------------- scenes
def sc_countdown(cv, lt, D, t):
    camx = 40 * lt
    city_bg(cv, camx, t)
    car(cv, 540, 1230, 0, 1.0, -4 * math.sin(math.pi * clamp(lt / D)) * abs(math.sin(lt * 18)))
    s = pop(lt, 0.05, 0.4)
    sy = 1.0
    if 0.38 < lt < 0.62:
        sy = max(0.04, abs((lt - 0.5) / 0.12))
    card = G["card8"] if lt < 0.5 else G["card7"]
    paste(cv, card, 540, 530, s, math.sin(lt * 4) * 2, sy=sy)
    for i, (x, y) in enumerate([(300, 380), (790, 420), (770, 760), (320, 720)]):
        sparkle(cv, x, y, 34 * pop(lt, 0.6 + i * .08) * (0.7 + 0.3 * math.sin(lt * 9 + i)))
    accent(cv, "ДНЕЙ", 540, 900, lt, 0.55, 170, YELLOW)
    accent(cv, "ДО РЕЛИЗА", 540, 1050, lt, 0.75, 96, TEAL, PURPLE)
    return {"z": 0.05 * eo(lt / D)}


def sc_three(cv, lt, D, t):
    sunburst(cv, (90, 24, 150), (130, 40, 190), lt * 25, 540, 1100)
    hero = G["hero"]
    paste(cv, hero, 540, 1170 + math.sin(lt * 10) * 8, 1.2 * (0.9 + 0.1 * eo(lt / .3)), math.sin(lt * 6) * 3)
    accent(cv, "3 ВЕЩИ", 540, 390, lt, 0.08, 220, YELLOW)
    for i, (x, c) in enumerate([(250, PINK), (540, TEAL), (830, ORANGE)]):
        s = pop(lt, 0.35 + i * .18, .3)
        if s > .01:
            im = num_bubble(str(i + 1), c)
            paste(cv, im, x, 620 + math.sin(lt * 7 + i) * 10, s)
    return {"z": 0.04 * lt / D}


@lru_cache(maxsize=8)
def num_bubble(n, c):
    p = Pen(160, 160)
    p.ell((8, 8, 152, 152), c, 9)
    p.text((80, 76), n, 96, WHITE, stroke=6)
    return p.img()


def sc_date(cv, lt, D, t):
    stripes(cv, (0, 170, 165), (0, 140, 150), lt * 160)
    confetti(cv, lt, 3, 50, (0, 0, W, 1650))
    s = pop(lt, 0.05, 0.45)
    paste(cv, G["cal"], 540, 840, s * 1.05, math.sin(lt * 3) * 4 * (1 - eo(lt)) + 3 * math.sin(lt * 5))
    badge(cv, "1", lt)
    accent(cv, "РЕЛИЗ", 600, 330, lt, 0.12, 120, WHITE, PURPLE)
    accent(cv, "19.11.2026", 540, 1270, lt, 0.45, 150, YELLOW)
    return {"z": 0.03 * lt / D}


def sc_consoles(cv, lt, D, t):
    d = ImageDraw.Draw(cv)
    d.rectangle((0, 0, W, H), fill=(62, 20, 112))
    composite(cv, G["halftone"], -(lt * 60 % 40) - 40, -(lt * 60 % 40) - 40)
    accent(cv, "КОНСОЛИ", 540, 320, lt, 0.05, 120, WHITE, PURPLE)
    s1 = pop(lt, 0.1, .4); s2 = pop(lt, 0.45, .4)
    paste(cv, G["pad_pink"], 320, 760 + math.sin(lt * 5) * 10, s1 * 1.0, -12 + math.sin(lt * 4) * 4)
    accent(cv, "PS5", 320, 540, lt, 0.2, 130, YELLOW)
    paste(cv, G["pad_teal"], 760, 1110 + math.sin(lt * 5 + 1) * 10, s2 * 1.0, 12 + math.sin(lt * 4 + 1) * 4)
    accent(cv, "XBOX SERIES X|S", 560, 1330, lt, 0.6, 96, YELLOW)
    accent(cv, "+", 560, 950, lt, 0.4, 150, WHITE, PINK)
    return {"z": 0.035 * lt / D}


def sc_pc(cv, lt, D, t):
    grid_floor(cv, (24, 8, 54), (130, 30, 120), (0, 224, 208), lt, 1150, 1.2)
    mon = G["monitor"]
    s = pop(lt, 0.05, .4)
    mx, my = 540, 860
    paste(cv, mon, mx, my, s)
    if s > 0.9:
        d = ImageDraw.Draw(cv)
        x0, x1, y0 = mx - 230, mx + 230, my + 20
        prog = min(0.62, lt * 0.6) + (0.02 * math.sin(lt * 20) if lt > 1.1 else 0)
        d.rounded_rectangle((x0, y0, x1, y0 + 44), 12, fill=(40, 20, 80), outline=TEAL, width=5)
        d.rounded_rectangle((x0 + 8, y0 + 8, x0 + 8 + (x1 - x0 - 16) * prog, y0 + 36), 8, fill=PINK)
        for yy in range(my - 200, my + 180, 10):  # скан-линии
            d.line([(mx - 300, yy), (mx + 300, yy)], fill=(0, 0, 0), width=1)
        im = text_img("ЗАГРУЗКА…", 46, TEAL, FONT_ACC, 3, 0, INK)
        if int(lt * 3) % 2 == 0:
            paste(cv, im, mx, my - 50)
        # песочные часы
        hg = hourglass()
        paste(cv, hg, mx, my - 150, 1, (lt * 180) % 360 if (lt % 1.2) < .4 else 0)
    accent(cv, "ПК — ПОЗЖЕ", 540, 330, lt, 0.15, 150, YELLOW)
    accent(cv, "ДАТЫ ПОКА НЕТ", 540, 1300, lt, 0.7, 84, TEAL, PURPLE)
    return {"z": 0.04 * lt / D}


@lru_cache(maxsize=1)
def hourglass():
    p = Pen(80, 100)
    p.poly([(10, 8), (70, 8), (44, 50), (70, 92), (10, 92), (36, 50)], (255, 230, 160), 6)
    p.poly([(24, 82), (56, 82), (40, 62)], ORANGE, 0)
    return p.img()


def sc_city(cv, lt, D, t):
    camx = 300 + 700 * lt / D
    city_bg(cv, camx, t)
    cx = lerp(-350, 1450, lt / D)
    car(cv, cx, 1235, cx / 50 * 57.3)
    badge(cv, "2", lt)
    accent(cv, "ВАЙС-СИТИ", 560, 470, lt, 0.12, 170, WHITE, PINK, glow=PINK + (255,))
    return {"z": 0.02 + 0.03 * lt / D}


def sc_map(cv, lt, D, t):
    d = ImageDraw.Draw(cv)
    for y in range(0, H, 16):
        d.rectangle((0, y, W, y + 16), fill=mix((0, 170, 190), (0, 90, 140), y / H))
    for i in range(12):  # волны
        y = 250 + i * 140 + (i % 2) * 40
        x = ((lt * 50 * (1 if i % 2 else -1) + i * 170) % (W + 200)) - 100
        d.arc((x, y, x + 80, y + 40), 200, 340, fill=(160, 250, 250), width=6)
    s = pop(lt, 0.05, .45)
    mp = G["map"]
    paste(cv, mp, 560, 940, s * 1.15, math.sin(lt * 2) * 1.5)
    # точки на карте (координаты спрайта -> экран)
    def scr(px, py):
        return 560 + (px - 340) * 1.15 * s, 940 + (py - 460) * 1.15 * s
    route = [(200, 120), (420, 110), (380, 330), (470, 520), (550, 760)]
    if s > .9:
        pts = [scr(*p_) for p_ in route]
        prog = clamp((lt - 0.5) / 1.2) * (len(pts) - 1)
        for k in range(int(prog)):
            _dash(d, pts[k], pts[k + 1])
        k = int(prog)
        if k < len(pts) - 1:
            f = prog - k
            _dash(d, pts[k], (lerp(pts[k][0], pts[k + 1][0], f), lerp(pts[k][1], pts[k + 1][1], f)))
        for i, p_ in enumerate(pts[:-1]):
            ps = pop(lt, 0.4 + i * .2, .3)
            paste(cv, G["pin2"], p_[0], p_[1] - 50 * ps, ps * .6)
        ps = pop(lt, 1.5, .35)
        x, y = pts[-1]
        paste(cv, G["pin"], x, y - 70 * ps, ps * 1.0)
        lab = text_img("ВАЙС-СИТИ", 52, WHITE, FONT_ACC, 6, 6, PINK)
        paste(cv, lab, x - 170, y - 150, pop(lt, 1.6, .3))
    accent(cv, "ШТАТ ЛЕОНИДА", 540, 330, lt, 0.12, 130, YELLOW)
    return {"z": 0.04 * lt / D}


def _dash(d, a, b, seg=22):
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    n = int(L / seg)
    for i in range(0, n, 2):
        f0, f1 = i / max(n, 1), min(1, (i + 1) / max(n, 1))
        d.line([(lerp(a[0], b[0], f0), lerp(a[1], b[1], f0)), (lerp(a[0], b[0], f1), lerp(a[1], b[1], f1))],
               fill=WHITE, width=8)


def sc_heroes(cv, lt, D, t):
    d = ImageDraw.Draw(cv)
    d.rectangle((0, 0, W, H), fill=(0, 170, 165))
    k = eo(lt / .35)
    d.polygon([(0, 0), (lerp(-200, 640, k), 0), (lerp(-600, 440, k), H), (0, H)], fill=(230, 40, 130))
    d.line([(lerp(-200, 640, k), 0), (lerp(-600, 440, k), H)], fill=INK, width=14)
    x1 = lerp(-300, 290, eo((lt - 0.05) / .4)); x2 = lerp(1400, 800, eo((lt - 0.25) / .4))
    paste(cv, G["hero"], x1, 1150 + math.sin(lt * 8) * 6, 0.95, math.sin(lt * 5) * 2)
    paste(cv, G["hero2"], x2, 1150 + math.sin(lt * 8 + 1.5) * 6, 0.95, math.sin(lt * 5 + 1) * 2)
    accent(cv, "2 ГЕРОЯ", 540, 340, lt, 0.2, 200, YELLOW)
    accent(cv, "&", 545, 700, lt, 0.5, 170, WHITE, PURPLE)
    return {"z": 0.03 * lt / D}


def sc_hype(cv, lt, D, t):
    sunburst(cv, (255, 120, 40), (255, 80, 110), -lt * 30, 540, 950)
    badge(cv, "3", lt)
    accent(cv, "САМАЯ", 600, 360, lt, 0.1, 140, WHITE, PURPLE)
    accent(cv, "ОЖИДАЕМАЯ", 540, 520, lt, 0.28, 140, YELLOW)
    d = ImageDraw.Draw(cv)
    x0, x1, y0, y1 = 110, 970, 860, 990
    sh = pop(lt, 0.3, .3)
    if sh > .5:
        prog = eio((lt - 0.4) / 1.1)
        d.rounded_rectangle((x0 + 10, y0 + 14, x1 + 10, y1 + 14), 60, fill=INK)
        d.rounded_rectangle((x0, y0, x1, y1), 60, fill=(50, 20, 90), outline=INK, width=10)
        fx = x0 + 14 + (x1 - x0 - 28) * prog
        if prog > 0.02:
            for i in range(int(fx - x0 - 14)):
                pass
            fill = mix(TEAL, PINK, prog) if prog < .7 else mix(PINK, YELLOW, (prog - .7) / .3)
            d.rounded_rectangle((x0 + 14, y0 + 14, fx, y1 - 14), 48, fill=fill)
            d.rounded_rectangle((x0 + 30, y0 + 24, max(x0 + 60, fx - 20), y0 + 44), 10, fill=(255, 255, 255))
        pct = text_img(f"{int(prog * 100)}%", 150, WHITE, FONT_ACC, 12, 12, PINK)
        paste(cv, pct, 540, 1170, 1 + (0.15 * math.sin(lt * 20) if prog >= 1 else 0))
        if prog >= 1:
            r = random.Random(int(lt * 30))
            for i in range(10):
                sparkle(cv, r.uniform(120, 960), r.uniform(820, 1030), r.uniform(18, 40), YELLOW)
    return {"z": 0.04 * lt / D, "shake": 6 if lt > 1.5 else 0}


def sc_decade(cv, lt, D, t):
    sunburst(cv, (52, 18, 96), (80, 30, 130), lt * 20, 540, 1000, 24)
    glow = Image.new("RGBA", (700, 700), (0, 0, 0, 0))
    gl = _glow()
    composite(cv, gl, 540 - gl.width / 2, 1000 - gl.height / 2)
    s = pop(lt, 0.1, .5)
    paste(cv, G["trophy"], 540, 1020 + math.sin(lt * 4) * 10, s * 1.05)
    for i in range(7):
        a = lt * 1.6 + i * 2 * math.pi / 7
        sparkle(cv, 540 + math.cos(a) * 380, 1000 + math.sin(a) * 300, 30 * pop(lt, .3 + i * .05), YELLOW)
    accent(cv, "ИГРА", 540, 330, lt, 0.1, 140, WHITE, PURPLE)
    accent(cv, "ДЕСЯТИЛЕТИЯ", 540, 490, lt, 0.3, 140, YELLOW)
    return {"z": 0.04 * lt / D}


@lru_cache(maxsize=1)
def _glow():
    g = Image.new("RGBA", (900, 900), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse((150, 150, 750, 750), fill=(255, 200, 80, 140))
    return g.filter(ImageFilter.GaussianBlur(90))


def sc_years(cv, lt, D, t):
    grid_floor(cv, (40, 10, 80), (255, 80, 140), (255, 92, 170), lt, 1150, 1.0)
    yr = 2013 + int(round(13 * eio((lt - 0.15) / 1.0)))
    im = text_img(str(yr), 230, WHITE if yr < 2026 else YELLOW, FONT_ACC, 12, 14, PINK)
    paste(cv, im, 540, 700, pop(lt, 0.05, .35) * (1.12 if yr == 2026 and lt < 1.4 else 1))
    d = ImageDraw.Draw(cv)
    x0, x1, y = 160, 920, 960
    d.line([(x0, y), (x1, y)], fill=INK, width=22)
    d.line([(x0, y), (x1, y)], fill=TEAL, width=10)
    prog = eio((lt - 0.15) / 1.0)
    d.line([(x0, y), (lerp(x0, x1, prog), y)], fill=YELLOW, width=10)
    for x, c in ((x0, PINK), (x1, YELLOW)):
        d.ellipse((x - 26, y - 26, x + 26, y + 26), fill=c, outline=INK, width=8)
    paste(cv, text_img("GTA 5", 56, WHITE, FONT_ACC, 6, 6, PURPLE), x0 + 30, y + 70, pop(lt, .2))
    paste(cv, text_img("GTA 6", 56, YELLOW, FONT_ACC, 6, 6, PINK), x1 - 30, y + 70, pop(lt, 1.1))
    accent(cv, "13 ЛЕТ", 540, 340, lt, 1.0, 200, YELLOW)
    accent(cv, "ОЖИДАНИЯ", 540, 1180, lt, 1.25, 96, TEAL, PURPLE)
    return {"z": 0.04 * lt / D}


def sc_subscribe(cv, lt, D, t):
    d = ImageDraw.Draw(cv)
    for y in range(0, H, 16):
        d.rectangle((0, y, W, y + 16), fill=mix((120, 30, 170), (255, 70, 140), y / H))
    composite(cv, G["halftone"], -(lt * 40 % 40) - 40, -(lt * 40 % 40) - 40)
    # рука машет (за телом)
    hero = G["hero"]
    hx, hy, hs = 540, 1200, 1.15
    wave = 20 * math.sin(lt * 9)
    paste(cv, G["arm"], hx + 190 * hs, hy - 70 * hs, hs, -18 + wave)
    paste(cv, hero, hx, hy + math.sin(lt * 7) * 6, hs)
    clicked = lt > 1.3
    press = 1 - 0.1 * math.exp(-((lt - 1.3) / 0.08) ** 2)
    s = pop(lt, 0.1, .4) * press
    btn = sub_button(clicked)
    paste(cv, btn, 500, 560, s)
    bell_rot = 22 * math.sin(lt * 30) * math.exp(-(lt - 1.35) * 3) if clicked else 0
    paste(cv, G["bell"], 900, 560, pop(lt, 0.3, .3) * .75, bell_rot)
    if clicked:
        for k in range(2):
            rr = (lt - 1.35) * 300 + k * 40
            if 0 < rr < 220:
                d2 = ImageDraw.Draw(cv)
                a = int(255 * (1 - rr / 220))
                d2.arc((900 - rr, 560 - rr, 900 + rr, 560 + rr), -60, 60, fill=YELLOW, width=8)
                d2.arc((900 - rr, 560 - rr, 900 + rr, 560 + rr), 120, 240, fill=YELLOW, width=8)
    # курсор
    ct = eio((lt - 0.5) / 0.75)
    cx, cy = lerp(1000, 560, ct), lerp(1500, 600, ct)
    if lt > 1.3:
        cx, cy = lerp(560, 760, eio((lt - 1.6) / .8)), lerp(600, 820, eio((lt - 1.6) / .8))
    paste(cv, G["cursor"], cx + 40, cy + 60, 0.9 * press)
    accent(cv, "НЕ ПРОПУСТИ РАЗБОРЫ", 540, 330, lt, 0.2, 80, WHITE, PURPLE)
    return {"z": 0.03 * lt / D}


@lru_cache(maxsize=2)
def sub_button(done):
    p = Pen(700, 190)
    col = (110, 70, 150) if done else (255, 40, 90)
    p.rect((14, 24, 690, 186), INK, 0, r=60)
    p.rect((6, 6, 680, 166), col, 9, r=60)
    p.text((343, 88), "ПОДПИСАН" if done else "ПОДПИШИСЬ", 84, WHITE, stroke=6)
    return p.img()


def sc_outro(cv, lt, D, t):
    k = eo(lt / 1.5)
    camx = lerp(-320, 0, k)
    city_bg(cv, camx, t)
    cxp = lerp(-420, 540, k)
    car(cv, cxp, 1230, (cxp - 540) / 50 * 57.3)
    out = D - 0.75
    accent(cv, "ДО ВСТРЕЧИ", 540, 470, lt, 0.4, 130, WHITE, PURPLE, out=out)
    accent(cv, "19.11", 540, 700, lt, 0.6, 260, YELLOW, PINK, out=out - 0.05)
    for i, (x, y) in enumerate([(220, 640), (860, 600), (800, 860), (260, 880)]):
        sparkle(cv, x, y, 30 * pop(lt, .8 + i * .08) * (1 - eio((lt - out) / .3)))
    # камера: к концу в точности как кадр 0 (бесшовный луп)
    return {"z": 0.04 * (1 - eio(lt / D))}


SCENES = {"countdown": sc_countdown, "three": sc_three, "date": sc_date, "consoles": sc_consoles, "pc": sc_pc,
          "city": sc_city, "map": sc_map, "heroes": sc_heroes, "hype": sc_hype, "decade": sc_decade,
          "years": sc_years, "subscribe": sc_subscribe, "outro": sc_outro}


# ----------------------------------------------------------------- subtitles
def load_timings():
    T = json.load(open(os.path.join(A, "voice", "timings.json"), encoding="utf-8"))
    # фразы-чанки до 3 слов, не шире 960 px, разрыв на пунктуации
    chunks, cur = [], []
    f = font_(FONT_SUB, 88)

    def width(ws):
        txt = " ".join(w["w"].upper() for w in ws)
        bb = f.getbbox(txt, stroke_width=10)
        return bb[2] - bb[0]

    for w in T:
        if cur and (len(cur) >= 3 or width(cur + [w]) > 940 or cur[-1]["seg"] != w["seg"]):
            chunks.append(cur); cur = []
        cur.append(w)
        if w["w"].rstrip()[-1] in ".,!?:":
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    return chunks


def draw_subs(cv, t, chunks):
    for i, ch in enumerate(chunks):
        t0 = ch[0]["t0"]
        nxt = chunks[i + 1][0]["t0"] if i + 1 < len(chunks) else 99
        t1 = min(ch[-1]["t1"] + 0.35, nxt)
        if not (t0 - 0.03 <= t < t1):
            continue
        words = [w["w"].upper() for w in ch]
        f = font_(FONT_SUB, 88)
        sp = 24
        ims, total = [], 0
        for w in ch:
            active = w["t0"] <= t < w["t1"] + 0.05
            shown = t >= w["t0"] - 0.03
            im = text_img(w["w"].upper(), 88, YELLOW if active else WHITE, FONT_SUB, 11, 8, INK)
            ims.append((im, shown, active, w))
            total += im.width + sp
        total -= sp
        x = W / 2 - total / 2
        cy = 1490
        for im, shown, active, w in ims:
            if shown:
                s = pop(t, w["t0"] - 0.03, 0.18)
                s = s * (1.08 if active else 1.0)
                paste(cv, im, x + im.width / 2, cy, s)
            x += im.width + sp
        return


# ----------------------------------------------------------------- frame pipeline
TW = 0.14  # половина длительности перехода


def scene_at(t):
    for i, sc in enumerate(S["scenes"]):
        if sc["start"] <= t < sc["end"] or i == len(S["scenes"]) - 1:
            return i, sc


def affine(img, z, rot, tx, ty):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    cx, cy = W / 2, H / 2
    # выход (x,y) -> вход: C + R^-1 ((p - C - T)/z)
    a, b = c / z, s / z
    d, e = -s / z, c / z
    ox, oy = -cx - tx, -cy - ty
    return img.transform((W, H), Image.AFFINE,
                         (a, b, a * ox + b * oy + cx, d, e, d * ox + e * oy + cy),
                         Image.BILINEAR, fillcolor=INK + (255,))


def hblur(arr, amount):
    n = max(2, int(amount / 12))
    step = max(1, int(amount / n))
    acc = arr.astype(np.uint16)
    for k in range(1, n):
        acc += np.roll(arr, k * step, axis=1)
    return (acc // n).astype(np.uint8)


def glitch(arr, strength, seed):
    r = np.random.default_rng(seed)
    out = arr.copy()
    dx = int(18 * strength) + 2
    out[..., 0] = np.roll(arr[..., 0], dx, axis=1)
    out[..., 2] = np.roll(arr[..., 2], -dx, axis=1)
    for _ in range(int(10 * strength) + 2):
        y = r.integers(0, H - 80); h = r.integers(8, 90); s = r.integers(-120, 120)
        out[y:y + h] = np.roll(out[y:y + h], int(s * strength), axis=1)
    if strength > 0.5:
        y = r.integers(0, H - 200)
        out[y:y + 12, :, :] = np.array(TEAL, np.uint8)
    return out


_CHUNKS = None


def render_frame(fi):
    global _CHUNKS
    if _CHUNKS is None:
        _CHUNKS = load_timings()
    t = fi / FPS
    i, sc = scene_at(t)
    lt, D = t - sc["start"], sc["end"] - sc["start"]
    cv = Image.new("RGBA", (W, H), INK + (255,))
    lead = 0.07 if i > 0 else 0.0  # контент уже «в кадре» во время перехода (кроме кадра лупа)
    cam = SCENES[sc["id"]](cv, lt + lead, D, t) or {}
    # камера: покачивание (периоды кратны 30 с -> луп бесшовный)
    z = 1.05 + cam.get("z", 0)
    rot = 0.55 * math.sin(2 * math.pi * t / 3.75)
    tx = 7 * math.sin(2 * math.pi * t / 2.5)
    ty = 6 * math.sin(2 * math.pi * t / 3.0)
    if cam.get("shake"):
        tx += cam["shake"] * math.sin(t * 77); ty += cam["shake"] * math.cos(t * 91)
    # переходы
    kind_in = sc["in"] if lt < TW and i > 0 else None
    nxt = S["scenes"][i + 1] if i + 1 < len(S["scenes"]) else None
    kind_out = nxt["in"] if nxt and (D - lt) < TW else None
    blur = 0; flash = 0; gl = 0
    if kind_in:
        p = 1 - lt / TW
        if kind_in == "whip":
            tx += W * 0.55 * p * p * (1 if i % 2 else -1); blur = 260 * p
        elif kind_in == "zoom":
            z *= 1 + 0.45 * p * p; flash = 0.6 * p
        elif kind_in == "glitch":
            gl = p
    if kind_out:
        q = 1 - (D - lt) / TW
        if kind_out == "whip":
            tx -= W * 0.55 * q * q * (1 if (i + 1) % 2 else -1); blur = 260 * q
        elif kind_out == "zoom":
            z *= 1 + 0.7 * q * q; flash = 0.6 * q
        elif kind_out == "glitch":
            gl = q
    img = affine(cv, z, rot, tx, ty)
    if blur > 8 or gl > 0.02:
        arr = np.asarray(img.convert("RGB"))
        if blur > 8:
            arr = hblur(arr, blur)
        if gl > 0.02:
            arr = glitch(arr, gl, fi)
        img = Image.fromarray(arr).convert("RGBA")
    if flash > 0.01:
        img.alpha_composite(Image.new("RGBA", (W, H), (255, 245, 250, int(255 * flash))))
    img.alpha_composite(G["vign"])
    draw_subs(img, t, _CHUNKS)
    return img.convert("RGB").tobytes()


def render_video():
    build_assets()
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, "gta6_short.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", os.path.join(A, "mix.wav"),
           "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-g", str(FPS), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{DUR:.3f}", "-movflags", "+faststart", out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(os.cpu_count()) as pool:
        for k, buf in enumerate(pool.imap(render_frame, range(NF), chunksize=4)):
            ff.stdin.write(buf)
            if k % 120 == 0:
                print(f"  frame {k}/{NF}", flush=True)
    ff.stdin.close()
    if ff.wait() != 0:
        sys.exit("ffmpeg failed")
    print("[video] ->", out)


def preview(times):
    build_assets()
    d = os.path.join(OUT, "preview"); os.makedirs(d, exist_ok=True)
    for tt in times:
        fi = int(round(float(tt) * FPS))
        Image.frombytes("RGB", (W, H), render_frame(fi)).save(os.path.join(d, f"f_{float(tt):05.2f}.png"))
    print("preview ->", d)


def thumbnail():
    build_assets()
    cv = Image.new("RGBA", (W, H), INK + (255,))
    city_bg(cv, 120, 0, neons=False)
    car(cv, 540, 1290, 0)
    paste(cv, G["hero"], 290, 1290, 0.95, 4)
    paste(cv, G["hero2"], 800, 1300, 0.92, -4)
    paste(cv, G["card7"], 540, 470, 0.8, -4)
    sz = fit_size("ДНЕЙ ДО GTA 6", 150)
    paste(cv, text_img("ДНЕЙ ДО GTA 6", sz, YELLOW, FONT_ACC, 14, 14, PINK), 540, 790)
    d = ImageDraw.Draw(cv)
    d.polygon([(0, 1560), (W, 1520), (W, 1700), (0, 1740)], fill=PINK, outline=INK, width=10)
    paste(cv, text_img("3 ФАКТА ЗА 30 СЕКУНД", fit_size("3 ФАКТА ЗА 30 СЕКУНД", 96, 960), WHITE, FONT_ACC, 10, 8, INK),
          540, 1625, 1, 2)
    for (x, y) in [(220, 330), (850, 360), (860, 620)]:
        sparkle(cv, x, y, 40)
    cv.alpha_composite(G["vign"])
    cv.convert("RGB").save(os.path.join(OUT, "thumbnail.png"))
    print("[thumb] ->", os.path.join(OUT, "thumbnail.png"))


def check():
    out = os.path.join(OUT, "gta6_short.mp4")
    info = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_name,width,height,r_frame_rate,nb_frames,duration",
         "-of", "json", out]))
    print(json.dumps(info, indent=1))
    dur = float(info["format"]["duration"])
    v = next(s for s in info["streams"] if s["codec_name"] == "h264")
    ok = (abs(dur - DUR) < 0.03 and abs(float(v["duration"]) - DUR) < 0.02 and int(v["nb_frames"]) == NF
          and all(abs(float(s["duration"]) - DUR) < 0.03 for s in info["streams"])
          and v["width"] == W and v["height"] == H and v["r_frame_rate"] == f"{FPS}/1")
    print("CHECK", "OK" if ok else "FAIL", f"duration={dur:.3f}s frames={v.get('nb_frames')}")
    return ok


if __name__ == "__main__":
    args = sys.argv[1:] or ["all"]
    st = args[0]
    if st in ("audio", "all"):
        build_audio()
    if st in ("frames", "all"):
        render_video()
    if st in ("thumb", "all"):
        thumbnail()
    if st in ("check", "all"):
        check()
    if st == "preview":
        preview(args[1:])
