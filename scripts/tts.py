"""Generate per-scene voiceover with edge-tts and build src/timeline.json.

Each scene lasts exactly (voice duration measured by ffprobe + 0.4 s pause),
rounded up to whole frames so speech is never cut.
"""
import asyncio, json, math, os, re, subprocess, sys

# edge-tts pins certifi's bundle; trust the environment's CA bundle if one is set
# (e.g. behind a TLS-terminating proxy). Verification stays enabled.
CA = os.environ.get("SSL_CERT_FILE") or ("/root/.ccr/ca-bundle.crt" if os.path.exists("/root/.ccr/ca-bundle.crt") else None)
if CA:
    import certifi
    certifi.where = lambda: CA

import edge_tts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICE, RATE, FPS, PAUSE = "ru-RU-SvetlanaNeural", "-5%", 30, 0.4


def norm(s):
    return re.sub(r"[^\wёЁ]", "", s.lower().replace("ё", "е"))


def probe(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", path])
    return float(out.decode().strip())


async def synth(text, out_path):
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
    bounds = []
    with open(out_path, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                bounds.append({"text": ch["text"], "start": ch["offset"] / 1e7,
                               "end": (ch["offset"] + ch["duration"]) / 1e7})
    return bounds


def align(text, bounds, duration):
    """Map displayed tokens (with punctuation) onto TTS word boundaries."""
    tokens = text.split()
    words, bi = [], 0
    for tok in tokens:
        key = norm(tok)
        start = end = None
        acc = ""
        while bi < len(bounds) and len(acc) < len(key):
            b = bounds[bi]
            if start is None:
                start = b["start"]
            acc += norm(b["text"])
            end = b["end"]
            bi += 1
        if acc != key:
            sys.exit(f"alignment failed at '{tok}': got '{acc}'")
        words.append({"text": tok, "start": round(start, 3), "end": round(end, 3)})
    return words


async def main():
    scenes = json.load(open(os.path.join(ROOT, "scripts", "script.json"), encoding="utf-8"))
    timeline, total = [], 0
    for i, sc in enumerate(scenes):
        rel = f"voice/scene_{i}.mp3"
        path = os.path.join(ROOT, "public", rel)
        bounds = await synth(sc["text"], path)
        dur = probe(path)
        frames = math.ceil((dur + PAUSE) * FPS)
        words = align(sc["text"], bounds, dur)
        timeline.append({"id": sc["id"], "text": sc["text"], "audio": rel,
                         "audioDuration": dur, "durationInFrames": frames, "words": words})
        total += frames
        print(f"scene {i} {sc['id']:8s} voice={dur:.3f}s frames={frames}")
    print(f"total {total} frames = {total / FPS:.2f}s")
    with open(os.path.join(ROOT, "src", "timeline.json"), "w", encoding="utf-8") as f:
        json.dump({"fps": FPS, "scenes": timeline}, f, ensure_ascii=False, indent=1)


asyncio.run(main())
