"""Narration pipeline.

1. Synthesizes every script line with edge-tts (ru-RU-DmitryNeural) and stores
   word-boundary timestamps (cached in .cache/tts).
2. Concatenates lines into public/voice.wav with controlled pauses so the video
   lands on the target length.
3. Writes src/data/timeline.json: shots (with frame ranges), subtitle phrases
   with per-word timing, section starts and Shorts windows.

Usage: python3 pipeline/tts.py [--rate +3%] [--target 298]
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import wave

import numpy as np
import edge_tts
import edge_tts.communicate as etc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "tts")
VOICE = "ru-RU-DmitryNeural"
SR = 48000
FPS = 60

# The sandbox HTTPS proxy re-signs TLS; edge-tts pins certifi, so trust the proxy CA if present.
_CA = os.environ.get("TTS_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
if os.path.exists(_CA):
    etc._SSL_CTX = ssl.create_default_context(cafile=_CA)


def norm(w):
    return re.sub(r"[^0-9a-zа-я]", "", w.lower().replace("ё", "е"))


async def synth(text, rate, sem):
    key = hashlib.sha1(f"{VOICE}|{rate}|{text}".encode()).hexdigest()[:16]
    mp3, js = os.path.join(CACHE, key + ".mp3"), os.path.join(CACHE, key + ".json")
    if os.path.exists(js):
        return mp3, json.load(open(js))
    async with sem:
        for attempt in range(15):
            try:
                audio, words = bytearray(), []
                com = edge_tts.Communicate(text, VOICE, rate=rate, boundary="WordBoundary")
                async for chunk in com.stream():
                    if chunk["type"] == "audio":
                        audio += chunk["data"]
                    elif chunk["type"] == "WordBoundary":
                        words.append({"text": chunk["text"], "start": chunk["offset"] / 1e7,
                                      "end": (chunk["offset"] + chunk["duration"]) / 1e7})
                if not audio or not words:
                    raise RuntimeError("empty response")
                open(mp3, "wb").write(audio)
                json.dump(words, open(js, "w"), ensure_ascii=False)
                return mp3, words
            except Exception as e:  # service is flaky: empty responses / dropped sockets
                await asyncio.sleep(min(1 + attempt, 6))
        sys.exit(f"edge-tts failed 15 times for: {text}")


def decode(mp3):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", mp3, "-f", "f32le",
                                   "-ac", "1", "-ar", str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32)


def align(tokens, words):
    """Map script tokens (with punctuation, for display) onto TTS word boundaries."""
    out, j = [], 0
    for tok in tokens:
        n = norm(tok)
        if not n:  # pure punctuation like "—": glue to previous token
            if out:
                out[-1]["text"] += " " + tok
            continue
        if j >= len(words):
            last = out[-1]["end"] if out else 0
            out.append({"text": tok, "start": last, "end": last + 0.2})
            continue
        w = words[j]
        out.append({"text": tok, "start": w["start"], "end": w["end"]})
        # TTS may merge/split words differently; consume boundaries until the text matches up
        acc = norm(w["text"])
        j += 1
        while len(acc) < len(n) and j < len(words) and n.startswith(acc + norm(words[j]["text"])[:1]):
            acc += norm(words[j]["text"])
            out[-1]["end"] = words[j]["end"]
            j += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", default="+3%")
    ap.add_argument("--target", type=float, default=298.0)
    args = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)

    script = json.load(open(os.path.join(ROOT, "src/data/script.json")))
    lines = []
    for si, sec in enumerate(script["sections"]):
        for li, line in enumerate(sec["lines"]):
            pieces = [p.strip() for p in line["text"].split("|")]
            assert len(pieces) == len(line["shots"]), line["text"]
            lines.append({"section": sec["id"], "si": si, "first": li == 0,
                          "text": " ".join(pieces), "pieces": pieces, "shots": line["shots"]})

    async def run_all():
        sem = asyncio.Semaphore(4)
        return await asyncio.gather(*(synth(l["text"], args.rate, sem) for l in lines))

    results = asyncio.run(run_all())

    clips, speech = [], 0.0
    for l, (mp3, words) in zip(lines, results):
        a = decode(mp3)
        tail = min(len(a), int((words[-1]["end"] + 0.12) * SR))
        a = a[:tail]
        lead = max(0.0, words[0]["start"] - 0.05)
        a = a[int(lead * SR):]
        for w in words:
            w["start"] -= lead
            w["end"] -= lead
        clips.append((a, words))
        speech += len(a) / SR

    INTRO, OUTRO_TAIL, SECTION_EXTRA = 0.6, 2.5, 0.6
    n_gaps = len(lines) - 1
    n_sec = len(script["sections"]) - 1
    fixed = speech + INTRO + OUTRO_TAIL + n_sec * SECTION_EXTRA
    gap = (args.target - fixed) / n_gaps
    print(f"speech {speech:.1f}s, line gap {gap:.3f}s")
    if not 0.15 <= gap <= 0.9:
        print("WARNING: gap out of comfortable range, adjust --rate", file=sys.stderr)
        gap = min(max(gap, 0.15), 0.9)

    t = INTRO
    voice, shots, phrases, sections, line_times = [], [], [], [], []
    voice.append(np.zeros(int(INTRO * SR), np.float32))
    for i, (l, (a, words)) in enumerate(zip(lines, clips)):
        if l["first"]:
            if i:
                extra = np.zeros(int(SECTION_EXTRA * SR), np.float32)
                voice.append(extra)
                t += SECTION_EXTRA
            sections.append({"id": l["section"], "start": round(t, 3)})
        start = t
        voice.append(a)
        dur = len(a) / SR

        tokens_per_piece = [p.split() for p in l["pieces"]]
        aligned = align([tok for p in tokens_per_piece for tok in p], words)
        # piece split times: start of first word of each piece
        counts = [sum(1 for tok in p if norm(tok)) for p in tokens_per_piece]
        idx, piece_starts = 0, []
        for c in counts:
            piece_starts.append(start + (aligned[idx]["start"] if idx < len(aligned) else 0))
            idx += c
        piece_starts[0] = start

        line_times.append({"start": start, "end": start + dur, "section": l["section"]})
        for k, shot in enumerate(l["shots"]):
            shots.append({"scene": shot["scene"], "props": shot.get("props", {}),
                          "cont": shot.get("cont", False), "start": piece_starts[k],
                          "line": i})

        # subtitle phrases: up to 5 words / 32 chars, break after punctuation
        cur = []
        for w in aligned:
            cur.append({"text": w["text"], "start": round(start + w["start"], 3), "end": round(start + w["end"], 3)})
            chars = sum(len(x["text"]) + 1 for x in cur)
            if len(cur) >= 5 or chars >= 30 or re.search(r"[.?!…:;,—»]$", w["text"]) and len(cur) >= 2:
                phrases.append(cur)
                cur = []
        if cur:
            if phrases and len(cur) == 1 and phrases[-1] and phrases[-1][-1]["end"] > start:
                phrases[-1].extend(cur)
            else:
                phrases.append(cur)

        t += dur
        if i < len(lines) - 1:
            voice.append(np.zeros(int(gap * SR), np.float32))
            t += gap
    voice.append(np.zeros(int(OUTRO_TAIL * SR), np.float32))
    total = t + OUTRO_TAIL

    # shot end = next shot start
    for k, s in enumerate(shots):
        s["end"] = shots[k + 1]["start"] if k + 1 < len(shots) else total
    f = lambda x: int(round(x * FPS))
    out_shots = [{"scene": s["scene"], "props": s["props"], "cont": s["cont"],
                  "from": f(s["start"]), "dur": f(s["end"]) - f(s["start"])} for s in shots]
    out_phrases = [{"from": f(p[0]["start"]), "to": f(p[-1]["end"]),
                    "words": [{"text": w["text"], "from": f(w["start"]), "to": f(w["end"])} for w in p]}
                   for p in phrases]

    # Shorts: windows of <= 60s that start and end on line boundaries
    shorts, s0 = [], 0
    while s0 < len(line_times):
        st = line_times[s0]["start"] - (0.3 if s0 else INTRO)
        e = s0
        while e + 1 < len(line_times) and line_times[e + 1]["end"] + 0.6 - st <= 59.5:
            e += 1
        end = min(line_times[e]["end"] + 0.6, total)
        shorts.append({"from": f(max(st, 0)), "to": f(end)})
        s0 = e + 1
    # the forward pass leaves a short tail; replace it with a full window anchored at the end
    if len(shorts) > 1 and (shorts[-1]["to"] - shorts[-1]["from"]) < 30 * FPS:
        shorts.pop()
        k = next(i for i, lt in enumerate(line_times) if total - (lt["start"] - 0.3) <= 59.5)
        tail = {"from": f(line_times[k]["start"] - 0.3), "to": f(total)}
        while shorts and shorts[-1]["to"] - tail["from"] > 20 * FPS:  # mostly duplicated content
            shorts.pop()
        shorts.append(tail)

    pcm = np.concatenate(voice)
    pcm = np.clip(pcm, -1, 1)
    with wave.open(os.path.join(ROOT, "public", "voice.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())

    timeline = {"fps": FPS, "durationInFrames": f(total), "sections": [
        {"id": s["id"], "from": f(s["start"])} for s in sections],
        "shots": out_shots, "phrases": out_phrases, "shorts": shorts}
    json.dump(timeline, open(os.path.join(ROOT, "src/data/timeline.json"), "w"), ensure_ascii=False, indent=0)

    print(f"total {total:.1f}s ({total // 60:.0f}:{total % 60:04.1f}), {len(out_shots)} shots")
    for s in sections:
        print(f"  {s['id']:<8} {s['start'] // 60:.0f}:{s['start'] % 60:04.1f}")
    short_shots = [(s["scene"], s["dur"] / FPS) for s in out_shots if s["dur"] < 2.0 * FPS]
    print("shots < 2s:", [(n, round(d, 1)) for n, d in short_shots])
    long_shots = [(s["scene"], s["dur"] / FPS) for s in out_shots if s["dur"] > 6.0 * FPS]
    print("shots > 6s:", [(n, round(d, 1)) for n, d in long_shots])
    print("shorts:", [(round(s["from"] / FPS, 1), round((s["to"] - s["from"]) / FPS, 1)) for s in shorts])


if __name__ == "__main__":
    main()
