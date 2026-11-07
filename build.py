#!/usr/bin/env python3
"""Сборка финального mp4: видео-кадры + голос + музыка (с дакингом под голос) + эффекты.

  python3 build.py --preview  → output/preview.mp4 (540x960, 15 fps)
  python3 build.py            → output/video.mp4   (1080x1920, 30 fps)
После сборки проверяет результат через ffprobe.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
OUT = ROOT / "output"


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                        "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return json.loads(r.stdout)


def check(path, w, h, fps, total):
    info = probe(path)
    v = [s for s in info["streams"] if s["codec_type"] == "video"]
    a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    dur = float(info["format"]["duration"])
    num, den = map(int, v[0]["r_frame_rate"].split("/")) if v else (0, 1)
    problems = []
    if not v or v[0]["codec_name"] != "h264":
        problems.append("видео не H.264")
    if v and (v[0]["width"], v[0]["height"]) != (w, h):
        problems.append(f"разрешение {v[0]['width']}x{v[0]['height']} вместо {w}x{h}")
    if v and abs(num / den - fps) > 0.01:
        problems.append(f"fps {num / den:.2f} вместо {fps}")
    if not a or a[0]["codec_name"] != "aac":
        problems.append("нет AAC-звука")
    if abs(dur - total) > 0.25:
        problems.append(f"длительность {dur:.2f}s, ожидалось {total:.2f}s")
    # звук не тишина?
    vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mean = [l for l in vol.splitlines() if "mean_volume" in l]
    mean_db = float(mean[0].split(":")[1].replace("dB", "")) if mean else -99
    if mean_db < -40:
        problems.append(f"звук слишком тихий ({mean_db} dB)")
    print(f"[check] {path.name}: {v[0]['width']}x{v[0]['height']} {v[0]['codec_name']} {num / den:.0f}fps, "
          f"аудио {a[0]['codec_name'] if a else '—'} {a[0].get('sample_rate', '') if a else ''}Hz, "
          f"{dur:.2f}s, громкость {mean_db} dB")
    if problems:
        print("[check] ПРОБЛЕМЫ: " + "; ".join(problems))
        return False
    print("[check] OK")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()
    w, h, fps = (540, 960, 15) if a.preview else (1080, 1920, 30)
    tl = json.loads((BUILD / "timeline.json").read_text(encoding="utf-8"))
    total = tl["total"]
    video = BUILD / f"video_{w}x{h}_{fps}.mp4"
    OUT.mkdir(exist_ok=True)
    out = OUT / ("preview.mp4" if a.preview else "video.mp4")

    fc = (
        "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[vo][sc];"
        "[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.32[mu];"
        "[mu][sc]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=350:makeup=1[duck];"
        "[3:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.85[fx];"
        "[vo]volume=1.0[v1];"
        "[v1][duck][fx]amix=inputs=3:normalize=0:duration=first,"
        "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    )
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-i", str(video), "-i", str(BUILD / "voice.wav"), "-i", str(BUILD / "music.wav"), "-i", str(BUILD / "sfx.wav"),
           "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    ok = check(out, w, h, fps, total)
    print(f"[build] → {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
