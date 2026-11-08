"""Procedural soundtrack synthesised with numpy only.

Rain bed, drone, escalating drum beat, impact thumps with bass accents exactly
on the hit frames, whooshes, wood crash, silence-drop before the slow-motion
blow, reverb by FFT convolution, BS.1770 loudness normalisation to -14 LUFS
and a look-ahead peak limiter.
"""
import math
import wave
import numpy as np
from .timeline import EVENTS, SILENCE, SLOWMO, DURATION

SR = 48000


class Bus:
    def __init__(self, n):
        self.x = np.zeros((n, 2), np.float32)

    def add(self, sig, t, pan=0.0, gain=1.0):
        i0 = int(round(t * SR))
        if sig.ndim == 1:
            l = math.cos((pan + 1) * math.pi / 4) * math.sqrt(2)
            r = math.sin((pan + 1) * math.pi / 4) * math.sqrt(2)
            sig = np.stack([sig * l, sig * r], 1)
        j0, j1 = max(i0, 0), min(i0 + len(sig), len(self.x))
        if j1 > j0:
            self.x[j0:j1] += sig[j0 - i0:j1 - i0] * gain


def band(x, lo, hi, sr=SR, soft=1.25):
    n = len(x)
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(n, 1 / sr)
    m = np.ones_like(f)
    if lo > 0:
        m *= 1 / (1 + (lo / np.maximum(f, 1e-3)) ** (2 * soft))
    if hi < sr / 2:
        m *= 1 / (1 + (f / hi) ** (2 * soft))
    if X.ndim == 2:
        m = m[:, None]
    return np.fft.irfft(X * m, n, axis=0).astype(np.float32)


def tt(dur):
    return np.arange(int(dur * SR), dtype=np.float32) / SR


def env_exp(dur, dec, att=0.002):
    t = tt(dur)
    return np.minimum(t / att, 1.0) * np.exp(-t / dec)


def sweep_sine(dur, f0, f1, k, dec):
    t = tt(dur)
    f = f1 + (f0 - f1) * np.exp(-t / k)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * env_exp(dur, dec)


class Synth:
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed + 4242)

    def noise(self, dur):
        return self.rng.standard_normal(int(dur * SR)).astype(np.float32)

    def kick(self, big=1.0):
        s = sweep_sine(0.6, 160 * big ** 0.2, 44, 0.035, 0.30 * big)
        click = band(self.noise(0.01), 2000, 8000) * env_exp(0.01, 0.003)
        s[:len(click)] += click * 0.3
        return np.tanh(s * 1.6) * 0.8

    def snare(self):
        n = band(self.noise(0.3), 900, 7000) * env_exp(0.3, 0.07)
        tone = sweep_sine(0.3, 260, 185, 0.02, 0.06)
        return n * 0.55 + tone * 0.4

    def hat(self, dec=0.03):
        return band(self.noise(0.12), 7000, 16000) * env_exp(0.12, dec) * 0.35

    def thump(self, power):
        dur = 0.5 + 0.9 * power
        body = sweep_sine(dur, 120 + 40 * power, 38, 0.04, 0.12 + 0.25 * power)
        crack = band(self.noise(dur), 250, 3500) * env_exp(dur, 0.025 + 0.05 * power)
        slap = band(self.noise(dur), 2500, 12000) * env_exp(dur, 0.008)
        s = body * 1.0 + crack * 0.55 + slap * 0.35
        return np.tanh(s * (1.2 + power)) * (0.6 + 0.4 * power)

    def sub(self, power, dur=1.4):
        return sweep_sine(dur, 70, 32, 0.15, 0.25 + 0.6 * power) * power

    def block(self):
        s = sweep_sine(0.25, 340, 210, 0.01, 0.05) * 0.6
        s += band(self.noise(0.25), 1200, 6000) * env_exp(0.25, 0.03) * 0.5
        s += band(self.noise(0.25), 120, 500) * env_exp(0.25, 0.05) * 0.5
        return s

    def whoosh(self, dur=0.32, f0=300, f1=1800, gain=0.5):
        t = tt(dur)
        n = band(self.noise(dur), 0, 450)
        f = f0 + (f1 - f0) * (t / dur)
        car = np.sin(2 * np.pi * np.cumsum(f) / SR)
        e = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
        return n * car * e * gain * 3.0

    def splash(self, dur=0.8, power=1.0):
        n = band(self.noise(dur), 900, 9000)
        e = env_exp(dur, 0.12 * power, att=0.01)
        drops = (self.rng.random(len(n)) < 0.002).astype(np.float32) * self.rng.uniform(0.3, 1, len(n))
        drops = band(drops, 2000, 10000) * env_exp(dur, 0.35)
        return n * e * 0.5 + drops * 2.5

    def crash(self):
        dur = 1.6
        out = self.thump(1.0)
        out = np.concatenate([out, np.zeros(int(dur * SR) - len(out), np.float32)]) if len(out) < dur * SR else out[:int(dur * SR)]
        for _ in range(26):
            t0 = self.rng.uniform(0, 0.7) ** 1.6
            d = self.rng.uniform(0.03, 0.12)
            cr = band(self.noise(d), self.rng.uniform(300, 900), self.rng.uniform(1500, 4000)) * env_exp(d, d / 3)
            i = int(t0 * SR)
            out[i:i + len(cr)] += cr * self.rng.uniform(0.3, 0.9)
        rattle = band(self.noise(dur), 500, 5000) * env_exp(dur, 0.45, att=0.05) * 0.25
        return out + rattle

    def reverse_swell(self, dur):
        t = tt(dur)
        n = band(self.noise(dur), 2500, 14000) * 0.5 + band(self.noise(dur), 200, 1200) * 0.3
        return n * (t / dur) ** 3.5

    def ir(self, dur=2.2):
        t = tt(dur)
        L = self.noise(dur) * np.exp(-t / 0.45)
        R = self.noise(dur) * np.exp(-t / 0.45)
        ir = np.stack([band(L, 150, 7000), band(R, 150, 7000)], 1)
        return ir / np.sqrt((ir ** 2).sum() / 2)


def fft_convolve(x, ir):
    n = len(x) + len(ir)
    nf = 1 << (n - 1).bit_length()
    X = np.fft.rfft(x, nf, axis=0)
    H = np.fft.rfft(ir, nf, axis=0)
    return np.fft.irfft(X * H, nf, axis=0)[:len(x)].astype(np.float32)


# ------------------------------------------------------------- loudness
def _biquad_resp(b, a, f, sr):
    w = 2 * np.pi * f / sr
    z = np.exp(-1j * w)
    return (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)


def k_weight(x, sr=SR):
    # ITU-R BS.1770-4 coefficients (48 kHz)
    b1, a1 = [1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585]
    b2, a2 = [1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621]
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / sr)
    H = np.abs(_biquad_resp(b1, a1, f, sr) * _biquad_resp(b2, a2, f, sr))
    return np.fft.irfft(np.fft.rfft(x, axis=0) * H[:, None], n, axis=0)


def lufs(x, sr=SR):
    y = k_weight(x, sr)
    blk, hop = int(0.4 * sr), int(0.1 * sr)
    ms = []
    for i in range(0, len(y) - blk + 1, hop):
        ms.append((y[i:i + blk] ** 2).mean(axis=0).sum())
    ms = np.array(ms)
    l = -0.691 + 10 * np.log10(ms + 1e-12)
    g = ms[l > -70]
    if len(g) == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(g.mean()) - 10
    g2 = ms[(l > -70) & (l > rel)]
    return float(-0.691 + 10 * np.log10(g2.mean()))


def true_peak(x):
    n = len(x)
    X = np.fft.rfft(x, axis=0)
    up = np.fft.irfft(X, n * 4, axis=0) * 4
    return float(np.abs(up).max())


def limiter(x, ceiling, look=0.003, sr=SR):
    L = int(look * sr)
    pk = np.abs(x).max(axis=1)
    g = np.minimum(1.0, ceiling / np.maximum(pk, 1e-9))
    pad = np.pad(g, (L, L), constant_values=1.0)
    from numpy.lib.stride_tricks import sliding_window_view
    gmin = sliding_window_view(pad, 2 * L + 1).min(axis=1)
    k = np.ones(L + 1) / (L + 1)
    gs = np.convolve(np.pad(gmin, (L // 2, L - L // 2), constant_values=1.0), k, mode='valid')[:len(g)]
    gs = np.minimum(gs, gmin)
    return x * gs[:, None]


# ------------------------------------------------------------- score
def build_audio(seed=1337, duration=DURATION, target_lufs=-14.0):
    n = int(round(duration * SR))
    sy = Synth(seed)
    mus, sfx, amb = Bus(n), Bus(n), Bus(n)
    t = np.arange(n, dtype=np.float32) / SR

    # ---- rain bed (muffled + dipped around the slow-mo)
    rn = np.stack([sy.noise(duration), sy.noise(duration)], 1)
    hi = band(rn, 1200, 11000) * 0.16
    lo = band(rn, 80, 600) * 0.10
    ticks = (sy.rng.random((n, 2)) < 0.0015).astype(np.float32) * sy.rng.uniform(0.2, 1, (n, 2))
    ticks = band(ticks, 3000, 12000) * 0.9
    s0, s1 = SILENCE
    slow = np.clip((t - SLOWMO['start']) / 0.15, 0, 1) * np.clip((SLOWMO['end'] + 0.1 - t) / 0.15, 0, 1)
    dip = 1 - 0.8 * np.clip((t - s0) / 0.05, 0, 1) * np.clip((s1 - t) / 0.05, 0, 1)
    muff = band(hi + ticks, 0, 700) * 1.6
    rain = (hi + ticks) * (1 - slow)[:, None] + muff * slow[:, None] + lo
    amb.x += rain * dip[:, None]

    # ---- drone (A minor power chord), swelling toward the climax
    drone = np.zeros(n, np.float32)
    for f, a in ((55.0, 1.0), (82.41, 0.6), (110.0, 0.45), (164.8, 0.2)):
        for h in range(1, 6):
            drone += np.sin(2 * np.pi * f * h * t * (1 + 0.0007 * h) + h) * a / h
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.23 * t)
    inten = np.interp(t, [0, 1, 3, 7, 7.45, 11, 15, 15.08, 15.46, 17.0, 17.6, 19.0, 20.0],
                      [0.25, 0.3, 0.4, 0.55, 0.7, 0.6, 0.9, 0.0, 0.0, 0.25, 0.8, 0.5, 0.0])
    drone = band(drone, 30, 900) * lfo * inten * 0.11
    mus.x += np.stack([drone, np.roll(drone, 240)], 1)

    # ---- drum beat (128 bpm), escalating; drops out for the silence
    beat = 60 / 128.0
    kick, snare = sy.kick(), sy.snare()
    hat_c, hat_o = sy.hat(0.025), sy.hat(0.09)
    b = 1.0
    i = 0
    while b < 19.2:
        if s0 - 0.02 <= b < SLOWMO['end']:
            b += beat / 4
            i += 1
            continue
        pos = i % 16
        if b < 3.0:
            if pos in (0, 8):
                mus.add(kick, b, 0, 0.7)
            if pos % 4 == 2:
                mus.add(hat_c, b, 0.3, 0.5)
        elif b < 7.0 or (11.0 <= b < 15.0):
            if pos in (0, 6, 8, 11) or (b >= 11 and pos in (14,)):
                mus.add(kick, b, 0, 0.8)
            if pos in (4, 12):
                mus.add(snare, b, -0.1, 0.55)
            mus.add(hat_o if pos % 4 == 2 else hat_c, b, 0.35, 0.45 if pos % 2 == 0 else 0.3)
        elif b < 11.0:
            if pos in (0, 10):
                mus.add(kick, b, 0, 0.9)
            if pos == 8:
                mus.add(snare, b, 0, 0.7)
            if pos % 4 == 0:
                mus.add(hat_c, b, 0.35, 0.35)
        elif b >= 17.0 and b < 18.6:
            if pos in (0, 8):
                mus.add(kick, b, 0, 0.8)
            if pos in (4, 12):
                mus.add(snare, b, 0, 0.5)
        b += beat / 4
        i += 1

    # ---- hook riser
    sfx.add(sy.reverse_swell(0.4) * 0.5, 0.02)
    # ---- event sounds
    for e in EVENTS:
        k, te, p = e['kind'], e['t'], e['power']
        pan = float(np.clip(e.get('pan', 0.0), -1, 1))
        if k in ('hit', 'heavy', 'hook', 'final', 'block'):
            sfx.add(sy.whoosh(0.2, 400, 2200, 0.35 * p), te - 0.17, -0.2)
        if k == 'whoosh':
            sfx.add(sy.whoosh(0.34, 250, 1900, 0.6 * p), te - 0.2, 0.2)
        elif k == 'block':
            sfx.add(sy.block(), te, 0.1, 0.8 * p + 0.3)
            sfx.add(sy.sub(0.35, 0.4), te, 0, 0.6)
        elif k == 'hit':
            sfx.add(sy.thump(p), te, 0.0, 0.9)
            sfx.add(sy.sub(p, 0.7), te, 0, 0.8)
            sfx.add(sy.splash(0.5, 0.6), te, 0.2, 0.4)
        elif k in ('heavy', 'hook'):
            sfx.add(sy.thump(1.0), te, 0, 1.0)
            sfx.add(sy.sub(1.0, 1.5), te, 0, 1.0)
            sfx.add(sy.splash(0.8, 1.0), te, 0.2, 0.5)
            mus.add(sy.kick(1.6), te, 0, 0.8)
        elif k == 'crash':
            sfx.add(sy.crash(), te, -0.3, 1.0)
            sfx.add(sy.sub(1.0, 1.8), te, 0, 1.0)
        elif k in ('jump', 'land'):
            sfx.add(sy.splash(0.6, 0.7), te, 0, 0.6)
            sfx.add(sy.sub(0.3, 0.3), te, 0, 0.6)
        elif k == 'fall':
            sfx.add(sy.thump(1.0), te, 0.2, 1.0)
            sfx.add(sy.sub(1.0, 2.0), te, 0, 1.1)
            sfx.add(sy.splash(1.2, 1.6), te, 0.2, 0.9)
            mus.add(sy.kick(1.8), te, 0, 1.0)
            cym = band(sy.noise(2.5), 4000, 15000) * env_exp(2.5, 0.8, 0.003) * 0.35
            mus.add(cym, te, 0.2)
        elif k == 'final':
            sfx.add(sy.reverse_swell(te - s1 + 0.05) * 0.8, s1 - 0.05)
            # slowed-down monster hit: pitched-down body + huge sub + long tail
            body = sweep_sine(3.0, 90, 24, 0.25, 0.9)
            crack = band(sy.noise(3.0), 120, 1500) * env_exp(3.0, 0.35)
            sfx.add(np.tanh((body + crack * 0.5) * 2.2) * 0.95, te, 0, 1.0)
            sfx.add(sy.thump(1.0), te, 0, 0.8)
            for hb in (16.25, 16.75):  # heartbeat in slow motion
                sfx.add(sy.sub(0.6, 0.5), hb, 0, 0.9)
                sfx.add(sy.sub(0.4, 0.4), hb + 0.18, 0, 0.6)
            sfx.add(sy.whoosh(0.5, 200, 1500, 0.7), SLOWMO['end'] - 0.3, 0)
    for st in np.arange(9.0, 10.6, 0.42):  # B's footsteps in puddles
        sfx.add(sy.splash(0.25, 0.3), float(st), 0.4, 0.25)

    # ---- reverb send on sfx
    wet = fft_convolve(sfx.x, sy.ir())
    mix = amb.x + mus.x * 0.9 + sfx.x + wet * 0.18
    # fade edges (loop-friendly: both ends are just rain)
    fade = np.clip(t / 0.03, 0, 1) * np.clip((duration - t) / 0.6, 0, 1) ** 0.5
    fade = np.maximum(fade, 0.0)
    mix *= fade[:, None]
    mix = band(mix, 25, 18000)
    # ---- loudness normalisation + limiter (iterate to converge)
    ceil = 10 ** (-1.5 / 20)
    for _ in range(4):
        l = lufs(mix)
        mix = mix * 10 ** ((target_lufs - l) / 20)
        mix = limiter(mix, ceil)
    mix = mix * min(1.0, 10 ** (-1.0 / 20) / max(true_peak(mix), 1e-9))
    return mix.astype(np.float32), lufs(mix), true_peak(mix)


def write_wav(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
