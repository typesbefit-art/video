#!/usr/bin/env python3
"""Synthesise every line of script.json with edge-tts.

Writes tts/<hash>.mp3 + tts/<hash>.words.json for each line (cached by a hash
of text + voice settings, so re-runs are free and offline once generated) and
tts/manifest.json describing scene -> lines -> files.

Usage: python3 scripts/tts.py [--rate +15%]
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import ssl
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TTS_DIR = ROOT / "tts"


def make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    # Corporate / sandbox proxies re-terminate TLS: trust their CA if provided.
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "EDGE_TTS_CA_BUNDLE"):
        path = os.environ.get(var)
        if path and Path(path).is_file():
            ctx.load_verify_locations(path)
    return ctx


def norm(s: str) -> str:
    return re.sub(r"[^\w]", "", s.lower().replace("ё", "е"))


def attach_punctuation(text: str, words: list) -> list:
    """WordBoundary words come without punctuation; map them back onto the
    original tokens so subtitles keep commas, question marks etc."""
    tokens = text.split()
    ti = 0
    out = []
    for w in words:
        nw = norm(w["text"])
        display = w["text"]
        for j in range(ti, min(ti + 3, len(tokens))):
            if norm(tokens[j]).startswith(nw) or nw.startswith(norm(tokens[j])):
                display = tokens[j]
                ti = j + 1
                break
        out.append({**w, "display": display})
    return out


async def synth(text: str, voice: dict, mp3: Path, words_json: Path, ssl_ctx):
    import edge_tts
    import edge_tts.communicate as comm

    comm._SSL_CTX = ssl_ctx  # edge-tts only trusts certifi by default
    communicate = edge_tts.Communicate(
        text,
        voice["name"],
        rate=voice.get("rate", "+0%"),
        pitch=voice.get("pitch", "+0Hz"),
        volume=voice.get("volume", "+0%"),
        boundary="WordBoundary",
        proxy=os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
    )
    words = []
    tmp = mp3.with_suffix(".part")
    with open(tmp, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append(
                    {
                        "text": chunk["text"],
                        "start": round(start, 4),
                        "end": round(start + chunk["duration"] / 1e7, 4),
                    }
                )
    if tmp.stat().st_size == 0 or not words:
        raise RuntimeError(f"edge-tts returned no audio for: {text!r}")
    tmp.rename(mp3)
    words_json.write_text(
        json.dumps(attach_punctuation(text, words), ensure_ascii=False, indent=1)
    )


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", help="override voice.rate from script.json")
    args = ap.parse_args()

    script = json.loads((ROOT / "script.json").read_text(encoding="utf-8"))
    base_voice = dict(script["voice"])
    if args.rate:
        base_voice["rate"] = args.rate
    TTS_DIR.mkdir(exist_ok=True)
    ssl_ctx = make_ssl_context()

    manifest = {"voice": base_voice, "scenes": []}
    for scene in script["scenes"]:
        lines = []
        for line in scene["lines"]:
            voice = {**base_voice, **line.get("voice", {})}
            key = json.dumps([line["text"], voice], ensure_ascii=False, sort_keys=True)
            h = hashlib.sha1(key.encode()).hexdigest()[:12]
            mp3 = TTS_DIR / f"{scene['id']}_{h}.mp3"
            wj = TTS_DIR / f"{scene['id']}_{h}.words.json"
            if not (mp3.exists() and wj.exists()):
                print(f"  tts  {scene['id']}: {line['text'][:50]}…", flush=True)
                attempts = 10
                for attempt in range(attempts):
                    try:
                        await synth(line["text"], voice, mp3, wj, ssl_ctx)
                        break
                    except Exception as e:  # the free endpoint is flaky / throttles
                        if attempt == attempts - 1:
                            raise
                        wait = min(2 ** (attempt + 1), 30)
                        print(f"  retry in {wait}s ({e})", flush=True)
                        await asyncio.sleep(wait)
                await asyncio.sleep(1.0)  # be gentle with the service
            else:
                print(f"  cache {scene['id']}: {line['text'][:50]}…", flush=True)
            lines.append(
                {
                    "speaker": line.get("speaker", "max"),
                    "text": line["text"],
                    "mp3": str(mp3.relative_to(ROOT)),
                    "words": json.loads(wj.read_text(encoding="utf-8")),
                }
            )
        manifest["scenes"].append({"id": scene["id"], "lines": lines})

    (TTS_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1)
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"TTS failed: {e}", file=sys.stderr)
        sys.exit(1)
