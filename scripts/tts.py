"""Озвучка сцен через edge-tts: voice/<scene>.mp3 + тайминги слов в src/voice.json."""
import asyncio, json, os, subprocess

VOICE = "ru-RU-DmitryNeural"
RATE = "+5%"
SCENES = [
    ("hook", "Ты не поверишь, что в космосе пахнет жареным стейком!"),
    ("fact1", "Факт первый. Один день на Венере длиннее её года."),
    ("fact2", "Факт второй. На Нептуне ветер быстрее звука."),
    ("fact3", "Факт третий. Космос полностью беззвучен."),
    ("outro", "Подпишись — завтра ещё три факта!"),
]


def duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]
    )
    return float(out)


async def synth(key, text):
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary",
                                proxy=os.environ.get("HTTPS_PROXY"))
    path = f"voice/{key}.mp3"
    words = []
    with open(path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration в единицах по 100 нс
                words.append({"word": chunk["text"], "start": chunk["offset"] / 1e7,
                              "end": (chunk["offset"] + chunk["duration"]) / 1e7})
    return {"key": key, "text": text, "file": path, "duration": duration(path), "words": words}


async def main():
    result = [await synth(k, t) for k, t in SCENES]
    with open("src/voice.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    for r in result:
        print(f"{r['key']:6} {r['duration']:.2f}s  words={len(r['words'])}")


import edge_tts  # noqa: E402
asyncio.run(main())
