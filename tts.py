#!/usr/bin/env python3
"""Озвучка через edge-tts + тайминги слов.

Для каждой сцены из script.json синтезирует отдельный mp3 и собирает
WordBoundary-события. Длительности сцен считаются ПО РЕАЛЬНОЙ длине
озвучки. Результат:
  build/voice.wav      — вся дорожка голоса (моно, 48 кГц)
  build/timeline.json  — сцены, их старт/длина, слова, биты, sfx, субтитры
"""
import asyncio
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
TTS_DIR = BUILD / "tts"
SR = 48000


# ---------------------------------------------------------------- edge-tts
def _patch_edge_tts():
    """edge-tts использует собственный SSL-контекст (certifi). За корпоративным
    прокси с собственным CA (SSL_CERT_FILE) он не проходит проверку — добавляем CA."""
    import edge_tts.communicate as comm
    ctx = ssl.create_default_context()
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        ca = os.environ.get(var)
        if ca and os.path.exists(ca):
            ctx.load_verify_locations(ca)
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    comm._SSL_CTX = ctx
    # permessage-deflate (compress=15) ломается на части прокси — отключаем сжатие
    import aiohttp
    orig = aiohttp.ClientSession.ws_connect
    if not getattr(orig, "_patched", False):
        def ws_connect(self, *a, **k):
            k["compress"] = 0
            return orig(self, *a, **k)
        ws_connect._patched = True
        aiohttp.ClientSession.ws_connect = ws_connect


async def _synth(text, voice, rate, pitch, out_mp3):
    import edge_tts
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                               proxy=proxy, boundary="WordBoundary")
    words = []
    with open(out_mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({
                    "text": ch["text"],
                    "start": ch["offset"] / 1e7,
                    "end": (ch["offset"] + ch["duration"]) / 1e7,
                })
    if not words:
        raise RuntimeError("edge-tts не вернул тайминги слов")
    return words


def synth_with_retry(text, voice, rate, pitch, out_mp3, tries=25):
    """Сервис периодически рвёт соединение — повторяем с короткой паузой."""
    import time
    last = None
    for i in range(tries):
        try:
            return asyncio.run(_synth(text, voice, rate, pitch, out_mp3))
        except Exception as e:
            last = e
            print(f"  ! {voice} попытка {i + 1}/{tries}: {type(e).__name__}", file=sys.stderr)
            time.sleep(min(4.0, 0.7 + 0.3 * i))
    raise RuntimeError(f"{voice}: не удалось получить озвучку ({last})")


def sentence_audio(sent, voice, rate, pitch):
    """Синтез одного предложения с кэшем на диске."""
    key = hashlib.md5(json.dumps([sent, voice, rate, pitch], ensure_ascii=False).encode()).hexdigest()[:12]
    mp3 = TTS_DIR / f"{key}.mp3"
    meta = mp3.with_suffix(".json")
    if mp3.exists() and meta.exists():
        return mp3, json.loads(meta.read_text(encoding="utf-8"))["words"]
    print(f"[tts] {voice}: «{sent}»")
    words = synth_with_retry(sent, voice, rate, pitch, mp3)
    meta.write_text(json.dumps({"voice": voice, "words": words, "text": sent},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return mp3, words


def split_sentences(text):
    return [x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x]


def pick_voice(script, voices):
    """Озвучивает все предложения ОДНИМ голосом; при полном отказе — запасной голос
    для всего видео целиком (чтобы голоса не перемешивались)."""
    for voice in voices:
        try:
            for sc in script["scenes"]:
                for sent in split_sentences(sc["text"]):
                    sentence_audio(sent, voice, script["rate"], script["pitch"])
            return voice
        except RuntimeError as e:
            print(f"[tts] {e} — пробую следующий голос", file=sys.stderr)
    raise SystemExit("[tts] ни один голос не доступен")


# ---------------------------------------------------------------- helpers
def norm(s):
    return re.sub(r"[^\wё]+", "", s.lower().replace("ё", "е"))


def align_words(text, boundaries):
    """Сопоставляет слова из WordBoundary исходным токенам текста, чтобы
    в субтитрах сохранились регистр и пунктуация («ВООБЩЕ?», «70!»)."""
    tokens = text.split()
    out, ti = [], 0
    for b in boundaries:
        nb = norm(b["text"])
        found = None
        # ищем ближайший токен (или 2-3 токена подряд: «8 минут»), совпадающий по виду
        for j in range(ti, min(ti + 3, len(tokens))):
            for L in (1, 2, 3):
                if norm("".join(tokens[j:j + L])) == nb:
                    found = (j, L)
                    break
            if found:
                break
        if found:
            j, L = found
            # пропущенные токены (без таймингов) приклеиваем к предыдущему слову
            for k in range(ti, j):
                if out:
                    out[-1]["text"] += " " + tokens[k]
            out.append(dict(b, text=" ".join(tokens[j:j + L])))
            ti = j + L
        else:
            out.append(dict(b))
    for k in range(ti, len(tokens)):  # хвост без таймингов
        if out:
            out[-1]["text"] += " " + tokens[k]
    return out


def find_word(words, key):
    """'слово' или 'слово#2' (второе вхождение) -> индекс."""
    name, _, nth = key.partition("#")
    nth = int(nth or 1)
    n = 0
    for i, w in enumerate(words):
        if norm(w["text"]) == norm(name) or norm(name) in [norm(x) for x in w["text"].split()]:
            n += 1
            if n == nth:
                return i
    raise KeyError(f"слово '{key}' не найдено в тексте сцены")


def decode_to_array(mp3):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "s16le", "-ac", "1",
         "-ar", str(SR), "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def trim_silence(a, thr=0.004):
    """Обрезает тишину в конце (edge-tts добавляет хвост)."""
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a
    return a[: min(len(a), idx[-1] + int(0.08 * SR))]


def make_groups(words, max_words=4, min_words=2):
    """Режет слова на группы по 2-4 для субтитров: внутри каждого предложения
    динамическим программированием ищем разбиение без «висячих» одиночных слов,
    предпочитая разрывы на запятых и двоеточиях."""
    sentences, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.!?]$", w["text"]):
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)

    groups = []
    for sent in sentences:
        n = len(sent)
        if n <= max_words:
            groups.append(sent)
            continue
        best = [0.0] + [1e9] * n
        prev = [0] * (n + 1)
        for i in range(1, n + 1):
            for size in range(min_words, max_words + 1):
                j = i - size
                if j < 0 or best[j] >= 1e9:
                    continue
                c = 0.5                                    # меньше групп — лучше
                if i < n and not re.search(r"[,:;—]$", sent[i - 1]["text"]):
                    c += 1.0                               # разрыв не на знаке препинания
                c += 1.2 * sum(bool(re.search(r"[,:;—]$", w["text"])) for w in sent[j:i - 1])
                if size == 2:
                    c += 0.3
                if best[j] + c < best[i]:
                    best[i], prev[i] = best[j] + c, j
        if best[n] >= 1e9:                                 # не делится — режем по 4
            groups += [sent[k:k + max_words] for k in range(0, n, max_words)]
            continue
        cuts, i = [], n
        while i > 0:
            cuts.append((prev[i], i))
            i = prev[i]
        groups += [sent[j:i] for j, i in reversed(cuts)]
    return groups


def write_wav(path, a):
    a = np.clip(a, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((a * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- main
def main():
    _patch_edge_tts()
    script = json.loads((ROOT / "script.json").read_text(encoding="utf-8"))
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    voices = [script["voice"], script.get("fallback_voice")]
    voices = [v for v in voices if v]

    voice = pick_voice(script, voices)
    print(f"[tts] голос: {voice}")
    t = 0.0
    scenes_out, voice_parts = [], []
    for i, sc in enumerate(script["scenes"]):
        sentences = split_sentences(sc["text"])
        audio_parts, words, pos = [], [], 0.0
        for si, sent in enumerate(sentences):
            mp3, sw = sentence_audio(sent, voice, script["rate"], script["pitch"])
            a = trim_silence(decode_to_array(mp3))
            alen = max(len(a) / SR, sw[-1]["end"] + 0.05)
            for w in sw:
                words.append({"text": w["text"], "start": w["start"] + pos, "end": w["end"] + pos})
            audio_parts.append((pos, a))
            pos += alen + (0.12 if si < len(sentences) - 1 else 0)
        vlen = pos
        audio = np.zeros(int(vlen * SR) + 10, dtype=np.float32)
        for p0, a in audio_parts:
            k = int(p0 * SR)
            audio[k:k + len(a)] = a[: len(audio) - k]

        pre = script["lead_in"] if i == 0 else 0.12
        post = script["tail"] if i == len(script["scenes"]) - 1 else script["scene_gap"]
        dur = pre + vlen + post
        vstart = t + pre

        words = align_words(sc["text"], words)
        for w in words:
            w["start"] = round(w["start"] + vstart, 3)
            w["end"] = round(w["end"] + vstart, 3)

        beats = [t] + [words[find_word(words, b)]["start"] - 0.08 for b in sc.get("beats", [])]
        sfx = []
        for s in sc.get("sfx", []):
            e = dict(s)
            e["t"] = round(words[find_word(words, s["at"])]["start"], 3)
            sfx.append(e)

        scenes_out.append({
            "id": sc["id"], "module": sc["module"], "text": sc["text"],
            "start": round(t, 3), "dur": round(dur, 3), "voice": voice,
            "beats": [round(b, 3) for b in beats], "words": words, "sfx": sfx,
        })
        voice_parts.append((vstart, audio))
        print(f"       старт {t:6.2f}s  длина {dur:5.2f}s  (голос {vlen:.2f}s)")
        t += dur

    total = t
    track = np.zeros(int(total * SR) + SR, dtype=np.float32)
    for st, a in voice_parts:
        k = int(st * SR)
        track[k:k + len(a)] += a
    track = track[: int(total * SR)]
    write_wav(BUILD / "voice.wav", track)

    all_words = [w for s in scenes_out for w in s["words"]]
    groups = []
    for s in scenes_out:
        for g in make_groups(s["words"]):
            groups.append({"words": g, "start": g[0]["start"]})
    for k, g in enumerate(groups):
        nxt = groups[k + 1]["start"] if k + 1 < len(groups) else total
        g["end"] = round(min(nxt, g["words"][-1]["end"] + 0.6), 3)

    timeline = {"total": round(total, 3), "scenes": scenes_out, "subtitles": groups,
                "words": len(all_words)}
    (BUILD / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"[tts] итого {total:.2f}s, слов {len(all_words)}, групп субтитров {len(groups)}")


if __name__ == "__main__":
    main()
