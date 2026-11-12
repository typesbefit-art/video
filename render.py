#!/usr/bin/env python3
"""Render avatar.svg into a seamless Telegram video avatar (avatar.mp4) and a static avatar.png.

Steps:
  1. avatar.svg -> avatar_square.svg: drop clipPath and the outer stroked circle,
     retime every animation so that 6 s is an integer number of iterations.
  2. Deterministic frame render with Playwright (all animations paused,
     currentTime = frame / FPS * 1000 for every frame).
  3. ffmpeg -> H.264 / yuv420p / faststart, CRF stepped up until the file is <= 2 MB.
  4. ffprobe check + seam check (frame 0 vs. the frame "after" the last one).

Usage: python3 render.py [--src avatar.svg] [--keep-frames]
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

LOOP_S = 6
FPS = 30
SIZE = 800
PNG_SIZE = 640
PNG_TIME_S = 1.5          # moment used for the static avatar.png
CRFS = [22, 23, 24, 25, 26, 28, 30]
MAX_BYTES = 2 * 1024 * 1024
ALLOWED = [6, 3, 2, 1.5, 1, 0.75, 0.6]
HERE = Path(__file__).resolve().parent

# Original duration -> looped duration. Anything not listed is snapped to the nearest allowed value.
DURATION_MAP = {
    5: 6,      # .hd  head sway
    7: 6,      # .fl  lightning, once per loop
    0.7: 0.75, # .r1  fast rain   (8 x per loop)
    0.9: 1,    # .r2  medium rain (6 x per loop)
    1.1: 1.5,  # .r3  slow rain   (4 x per loop)
    3.4: 3,    # .dr  hair drips  (2 x per loop)
    2.6: 3,    # .tip chin drop   (2 x per loop)
}


def snap(d):
    if d in DURATION_MAP:
        return DURATION_MAP[d]
    return min(ALLOWED, key=lambda a: abs(a - d))


def fmt(x):
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def prepare_svg(src: str) -> str:
    svg = src
    # 1. square: no clip, no outer ring
    svg = re.sub(r"<clipPath\b.*?</clipPath>", "", svg, flags=re.S)
    svg = re.sub(r"<defs>\s*</defs>", "", svg)
    svg = re.sub(r'\s*clip-path="url\(#[^)]*\)"', "", svg)
    svg = re.sub(r'<circle\b[^>]*\bstroke="[^"]*"[^>]*/>', "", svg)
    svg = svg.replace('width="100%"', f'width="{SIZE}" height="{SIZE}"', 1)

    style_m = re.search(r"<style>(.*?)</style>", svg, flags=re.S)
    css = style_m.group(1)

    # 2. durations: "animation: name 5s ..." and "animation-duration: .7s"
    old_dur = {}  # class selector -> (old, new) duration, used for delay scaling

    def dur_sub(m):
        old = float(m.group(2))
        return f"{m.group(1)}{fmt(snap(old))}s"

    def rule_sub(rule):
        sel, body = rule.group(1), rule.group(2)
        found = re.search(r"animation(?:-duration)?:\s*(?:[a-z][\w-]*\s+)?(\d*\.?\d+)s", body)
        if found:
            old_dur[sel.strip()] = float(found.group(1))
        body = re.sub(r"(animation:\s*[a-z][\w-]*\s+)(\d*\.?\d+)s", dur_sub, body)
        body = re.sub(r"(animation-duration:\s*)(\d*\.?\d+)s", dur_sub, body)
        return sel + "{" + body + "}"

    # top-level rules only (keyframes contain nested braces and no 's' durations)
    head, sep, keyframes = css.partition("@keyframes")
    head = re.sub(r"([^{}]+)\{([^{}]*)\}", rule_sub, head)

    # 3. delays: scale with the duration change and make them negative
    #    (a positive delay shows the un-animated state at t=0 -> visible seam).
    #    The duration a delay belongs to is taken from the same rule or from the
    #    rule whose class is the delay rule's first class (e.g. .dr2 -> .dr).
    def delay_rule(rule):
        sel, body = rule.group(1), rule.group(2)
        m = re.search(r"animation-delay:\s*(-?\d*\.?\d+)s", body)
        if not m:
            return rule.group(0)
        d = float(m.group(1))
        old = old_dur.get(sel.strip())
        if old is None:  # e.g. ".dr2" belongs to ".dr"
            base = re.sub(r"\d+$", "", sel.strip())
            old = old_dur.get(base)
        if old is None:
            return rule.group(0)
        new = snap(old)
        nd = d * new / old
        nd = round(nd / (1 / FPS)) * (1 / FPS)  # keep phases on frame boundaries
        nd = -((-nd) % new)                     # -> (-new, 0]
        body = body[: m.start(1)] + fmt(nd) + body[m.end(1):]
        return sel + "{" + body + "}"

    head = re.sub(r"([^{}]+)\{([^{}]*)\}", delay_rule, head)
    css = head + sep + keyframes
    svg = svg[: style_m.start(1)] + css + svg[style_m.end(1):]
    return svg


def render_frames(svg_text: str, out_dir: Path, times_ms):
    from playwright.sync_api import sync_playwright

    html = (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "html,body{margin:0;padding:0;background:#0A1224;overflow:hidden}"
        f"svg{{display:block;width:{SIZE}px;height:{SIZE}px}}"
        "</style></head><body>" + svg_text + "</body></html>"
    )
    with sync_playwright() as p:
        launch = {}
        if Path("/opt/pw-browsers/chromium").exists():
            launch["executable_path"] = "/opt/pw-browsers/chromium"
        try:
            browser = p.chromium.launch(**launch)
        except Exception:
            browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": SIZE, "height": SIZE}, device_scale_factor=1)
        page.set_content(html)
        info = page.evaluate(
            """() => {
              const a = document.getAnimations();
              a.forEach(x => x.pause());
              return a.map(x => {
                const t = x.effect.getTiming();
                return {name: x.animationName, dur: t.duration, delay: t.delay};
              });
            }"""
        )
        print(f"animations: {len(info)}")
        bad = [i for i in info if round(LOOP_S * 1000 / i["dur"], 6) % 1]
        for name in sorted({(i["name"], i["dur"], i["delay"]) for i in info}):
            print(f"  {name[0]:<6} duration {name[1]:>6.0f} ms  delay {name[2]:>6.0f} ms")
        if bad:
            sys.exit(f"durations that do not divide {LOOP_S}s: {bad}")
        paths = []
        for i, t in enumerate(times_ms):
            page.evaluate("t => document.getAnimations().forEach(a => a.currentTime = t)", t)
            path = out_dir / f"f{i:04d}.png"
            page.screenshot(path=str(path))
            paths.append(path)
        browser.close()
    return paths


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def encode(frames_dir: Path, out: Path, crf: int):
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-framerate", str(FPS), "-i", str(frames_dir / "f%04d.png"),
        "-frames:v", str(LOOP_S * FPS),
        "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-r", str(FPS), "-an", "-movflags", "+faststart", str(out),
    ])


def mean_diff(a: Path, b: Path) -> float:
    from PIL import Image, ImageChops, ImageStat
    d = ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB"))
    return sum(ImageStat.Stat(d).mean) / 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(HERE / "avatar.svg"))
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()

    square = prepare_svg(Path(args.src).read_text(encoding="utf-8"))
    (HERE / "avatar_square.svg").write_text(square, encoding="utf-8")
    print("wrote avatar_square.svg")

    n = LOOP_S * FPS
    tmp = HERE / "frames"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    # frames 0..n-1 for the video, frame n (= t 6000 ms) only for the seam check
    times = [i / FPS * 1000 for i in range(n + 1)]
    frames = render_frames(square, tmp, times)
    seam_frame = frames.pop()

    seam = mean_diff(frames[0], seam_frame)
    step = mean_diff(frames[0], frames[1])
    print(f"seam check: |frame0 - frame(6s)| = {seam:.3f}  (normal frame step {step:.3f})")
    if seam > 0.01:
        sys.exit("loop is not seamless")

    out = HERE / "avatar.mp4"
    for crf in CRFS:
        encode(tmp, out, crf)
        size = out.stat().st_size
        print(f"CRF {crf}: {size / 1024:.0f} KB")
        if size <= MAX_BYTES:
            break
    else:
        sys.exit("could not get under 2 MB")

    # static PNG for WhatsApp
    from PIL import Image
    idx = int(PNG_TIME_S * FPS)
    Image.open(frames[idx]).convert("RGB").resize((PNG_SIZE, PNG_SIZE), Image.LANCZOS).save(HERE / "avatar.png")
    print(f"wrote avatar.png ({PNG_SIZE}x{PNG_SIZE}, t={PNG_TIME_S}s)")

    # ffprobe report
    probe = json.loads(run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt,nb_read_frames:format=duration,size",
        "-of", "json", str(out)]).stdout)
    s, f = probe["streams"][0], probe["format"]
    audio = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                 "-of", "csv=p=0", str(out)]).stdout.strip()
    print(f"ffprobe: {s['codec_name']} {s['width']}x{s['height']} {s['pix_fmt']} "
          f"{s['r_frame_rate']} fps, {s['nb_read_frames']} frames, {float(f['duration']):.3f} s, "
          f"{int(f['size']) / 1024:.0f} KB, audio: {'yes' if audio else 'none'}")

    if args.keep_frames:
        print(f"frames kept in {tmp}")
    else:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
