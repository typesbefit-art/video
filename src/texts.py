"""Генерирует captions.srt (фразы как в ролике), captions_words.srt (по словам)
и voiceover.txt (текст для диктора с таймкодами)."""
import os
from narration import SCENES, WORDS, fmt_srt, fmt_tc
from render import CHUNKS, ROOT

NAMES = {"hook": "Хук", "security": "Безопасность", "people": "Люди", "economy": "Экономика",
         "risks": "Риски и неопределённость", "final": "Финал"}


def main():
    out = os.path.join(ROOT, "output")
    with open(os.path.join(out, "captions.srt"), "w", encoding="utf-8") as f:
        for i, ch in enumerate(CHUNKS, 1):
            text = "\n".join(" ".join(w[1] for w in ln) for ln in ch["lines"])
            f.write(f"{i}\n{fmt_srt(ch['start'])} --> {fmt_srt(ch['end'])}\n{text}\n\n")
    with open(os.path.join(out, "captions_words.srt"), "w", encoding="utf-8") as f:
        for i, (_, w, s, e) in enumerate(WORDS, 1):
            f.write(f"{i}\n{fmt_srt(s)} --> {fmt_srt(e)}\n{w}\n\n")
    with open(os.path.join(ROOT, "voiceover.txt"), "w", encoding="utf-8") as f:
        f.write("ТЕКСТ ДЛЯ ОЗВУЧКИ (русский, спокойный нейтральный тон, ~5 слогов/с)\n")
        f.write("Таймкоды — когда фраза должна звучать в ролике (длительность ролика 59 с).\n\n")
        for sc in SCENES:
            f.write(f"[{fmt_tc(sc['start'])}–{fmt_tc(sc['end'])}] {NAMES[sc['id']]}\n")
            for ch in [c for c in CHUNKS if c["words"][0][0] == sc["id"]]:
                f.write(f"  {fmt_tc(ch['words'][0][2])}  {' '.join(w[1] for w in ch['words'])}\n")
            f.write("\n")
    print("captions.srt, captions_words.srt, voiceover.txt written")


if __name__ == "__main__":
    main()
