"""Generate voice lines with edge-tts, measure them with ffprobe, write src/timeline.json."""
import asyncio, json, os, re, ssl, subprocess, sys
import edge_tts
import edge_tts.communicate as comm

# Trust the environment's CA bundle if present (HTTPS goes through a TLS-terminating proxy).
CA = os.environ.get("SSL_CERT_FILE") or "/root/.ccr/ca-bundle.crt"
if os.path.exists(CA):
    comm._SSL_CTX = ssl.create_default_context(cafile=CA)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICE = "ru-RU-DmitryNeural"
STYLE = {"n": dict(rate="-5%", pitch="+0Hz"), "d": dict(rate="+20%", pitch="+25Hz")}
TAIL = 0.4

def norm(s):
    return re.sub(r"[^\wё]", "", s.lower().replace("ё", "е"))

async def tts(text, who, path, attempts=60):
    for i in range(attempts):
        try:
            return await tts_once(text, who, path)
        except edge_tts.exceptions.NoAudioReceived:
            print(f"  empty response, retry {i + 1}/{attempts}", file=sys.stderr)
            await asyncio.sleep(3)
    raise SystemExit(f"edge-tts failed for: {text}")

async def tts_once(text, who, path):
    c = edge_tts.Communicate(text, VOICE, boundary="WordBoundary", **STYLE[who])
    bounds = []
    with open(path, "wb") as f:
        async for ch in c.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                bounds.append(dict(t=ch["text"], s=ch["offset"] / 1e7, e=(ch["offset"] + ch["duration"]) / 1e7))
    return bounds

def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", path])
    return float(out)

def align(text, bounds):
    """Map boundaries onto the original tokens (keeps punctuation and caps)."""
    tokens = text.split()
    words, bi = [], 0
    for tok in tokens:
        key = norm(tok)
        if bi < len(bounds) and norm(bounds[bi]["t"]) and key.startswith(norm(bounds[bi]["t"])):
            s, e = bounds[bi]["s"], bounds[bi]["e"]
            bi += 1
            # swallow extra boundaries that belong to the same token
            while bi < len(bounds) and norm(bounds[bi]["t"]) and norm(bounds[bi]["t"]) in key and \
                    not (len(words) + 1 < len(tokens) and norm(tokens[len(words) + 1]).startswith(norm(bounds[bi]["t"]))):
                e = bounds[bi]["e"]; bi += 1
            words.append(dict(w=tok, s=round(s, 3), e=round(e, 3)))
        else:
            raise SystemExit(f"Alignment failed at token {tok!r}: {bounds[bi:bi+3]}")
    return words

async def main():
    script = json.load(open(os.path.join(ROOT, "scripts/script.json"), encoding="utf-8"))
    out_dir = os.path.join(ROOT, "public/voice")
    os.makedirs(out_dir, exist_ok=True)
    scenes, total = [], 0.0
    for si, sc in enumerate(script):
        lines, t = [], 0.0
        for li, ln in enumerate(sc["lines"]):
            name = f"s{si}_{li}_{ln['who']}.mp3"
            path = os.path.join(out_dir, name)
            cache = path + ".bounds.json"
            if os.path.exists(cache) and os.path.getsize(path) > 0 and \
                    json.load(open(cache, encoding="utf-8")).get("text") == ln["text"]:
                bounds = json.load(open(cache, encoding="utf-8"))["bounds"]
            else:
                bounds = await tts(ln["text"], ln["who"], path)
                json.dump(dict(text=ln["text"], bounds=bounds), open(cache, "w", encoding="utf-8"), ensure_ascii=False)
            d = duration(path)
            lines.append(dict(who=ln["who"], text=ln["text"], file=f"voice/{name}", start=round(t, 3),
                              duration=d, words=align(ln["text"], bounds)))
            print(f"scene {si} line {li} ({ln['who']}): {d:.3f}s, {len(bounds)} words")
            t += d
        scenes.append(dict(lines=lines, duration=round(t + TAIL, 3)))
        total += t + TAIL
    json.dump(dict(scenes=scenes, total=round(total, 3)),
              open(os.path.join(ROOT, "src/timeline.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"total {total:.2f}s")

asyncio.run(main())
