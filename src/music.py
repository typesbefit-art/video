"""Синтез спокойного эмбиент-пэда (без авторских прав — генерируется кодом).
Выход: output/music.wav (44.1 кГц, стерео, 59 с) и output/voiceover_silence.wav."""
import os, wave
import numpy as np
from narration import DURATION

SR = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def write_wav(path, data):
    data = np.clip(data, -1, 1)
    pcm = (data * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(pcm.shape[1]); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    n = int(SR * DURATION)
    t = np.arange(n) / SR
    L = np.zeros(n); R = np.zeros(n)
    # Am – F – C – G, по 3.6875 с (16 тактов на 59 с)
    chords = [[57, 60, 64], [53, 57, 60], [48, 55, 64], [55, 59, 62]]
    dur = DURATION / 16
    for k in range(16):
        notes = chords[k % 4]
        a, b = k * dur, (k + 1) * dur + 1.2
        i0, i1 = int(a * SR), min(n, int(b * SR))
        tt = t[i0:i1] - a
        env = np.minimum(1, tt / 1.0) * np.minimum(1, np.maximum(0, (b - a - tt) / 1.4))
        for j, m in enumerate(notes + [notes[0] - 12]):
            f = midi(m)
            amp = 0.06 if j < 3 else 0.075
            for det, pan in ((-0.6, 0.8), (0.6, 0.2)):
                ph = 2 * np.pi * (f + det) * tt
                s = np.sin(ph) + 0.25 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
                L[i0:i1] += amp * env * s * pan
                R[i0:i1] += amp * env * s * (1 - pan)
        # мягкое арпеджио (колокольчик)
        arp = notes + [notes[1] + 12]
        step = dur / 8
        for q in range(8):
            st = a + q * step
            j0 = int(st * SR); j1 = min(n, j0 + int(1.6 * SR))
            if j0 >= n:
                break
            u = t[j0:j1] - st
            f = midi(arp[q % 4] + 12)
            s = np.sin(2 * np.pi * f * u) * np.exp(-u * 3.2) * 0.035
            pan = 0.3 + 0.4 * (q % 2)
            L[j0:j1] += s * pan; R[j0:j1] += s * (1 - pan)
    mix = np.stack([L, R], 1)
    # простое сглаживание (ФНЧ) и фейды
    ker = np.ones(9) / 9
    for c in range(2):
        mix[:, c] = np.convolve(mix[:, c], ker, mode="same")
    fade_in, fade_out = int(0.4 * SR), int(2.5 * SR)
    mix[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    mix[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    mix *= 0.5 / np.max(np.abs(mix))   # пик ≈ −6 dBFS
    os.makedirs(OUT, exist_ok=True)
    write_wav(os.path.join(OUT, "music.wav"), mix)
    write_wav(os.path.join(OUT, "voiceover_silence.wav"), np.zeros((n, 1)))
    print("music.wav, voiceover_silence.wav written")


if __name__ == "__main__":
    main()
