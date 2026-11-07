#!/usr/bin/env python3
"""Рендер кадров: HTML/Canvas-сцены в headless Chromium (Playwright).

Собирает build/page.html (шрифты + lib.js + engine.js + сцены + таймлайн),
затем N параллельных браузерных вкладок рендерят свои диапазоны кадров и
отдают JPEG прямо в ffmpeg (без промежуточных PNG на диске).

  python3 render.py --preview   # 540x960, 15 fps
  python3 render.py             # 1080x1920, 60 fps (--fps 30 для 30)
Результат: build/video_<w>x<h>_<fps>.mp4 (без звука).
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
SCENES = ROOT / "scenes"
FONTS = ROOT / "assets" / "fonts"

FONT_CSS = """
@font-face { font-family: Rubik; font-weight: 900; src: url('{f}/rubik-cyrillic-900-normal.woff2') format('woff2');
  unicode-range: U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116; }
@font-face { font-family: Rubik; font-weight: 900; src: url('{f}/rubik-latin-900-normal.woff2') format('woff2');
  unicode-range: U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD; }
@font-face { font-family: Rubik; font-weight: 700; src: url('{f}/rubik-cyrillic-700-normal.woff2') format('woff2');
  unicode-range: U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116; }
@font-face { font-family: Rubik; font-weight: 700; src: url('{f}/rubik-latin-700-normal.woff2') format('woff2');
  unicode-range: U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD; }
html,body { margin:0; padding:0; background:#000; overflow:hidden; }
canvas { display:block; }
"""


def build_page():
    timeline = json.loads((BUILD / "timeline.json").read_text(encoding="utf-8"))
    script = json.loads((ROOT / "script.json").read_text(encoding="utf-8"))
    mods = [s["module"] for s in script["scenes"]]
    parts = [(SCENES / "lib.js").read_text(encoding="utf-8"),
             (SCENES / "engine.js").read_text(encoding="utf-8")]
    parts += [(SCENES / m).read_text(encoding="utf-8") for m in mods]
    css = FONT_CSS.replace("{f}", FONTS.as_uri())
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head>
<body><canvas id="c"></canvas><div style="font:900 10px Rubik;position:absolute;opacity:0">Аа Aa 0</div>
<script>const TIMELINE = {json.dumps(timeline, ensure_ascii=False)};</script>
<script>{chr(10).join(parts)}</script></body></html>"""
    page = BUILD / "page.html"
    page.write_text(html, encoding="utf-8")
    return page, timeline


def launch(p):
    try:
        return p.chromium.launch()
    except Exception:
        # предустановленный Chromium другой версии
        for exe in ("/opt/pw-browsers/chromium", "/usr/bin/chromium", "/usr/bin/chromium-browser"):
            if os.path.exists(exe):
                path = exe
                if os.path.isdir(exe):
                    cand = list(Path(exe).rglob("chrome"))
                    if not cand:
                        continue
                    path = str(cand[0])
                return p.chromium.launch(executable_path=path, args=["--no-sandbox"])
        raise


def open_page(p, page_path, w, h):
    browser = launch(p)
    page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
    page.on("console", lambda m: m.type in ("error", "warning") and print("  [js]", m.text, file=sys.stderr))
    page.on("pageerror", lambda e: print("  [js error]", e, file=sys.stderr))
    page.goto(page_path.as_uri())
    page.evaluate("""async () => { await document.fonts.load('900 50px Rubik', 'Аа Aa'); await document.fonts.load('700 50px Rubik', 'Аа Aa'); await document.fonts.ready; }""")
    page.evaluate(f"setup({w}, {h})")
    return browser, page


def worker(args):
    page_path, w, h, fps, f0, f1, out = args
    from playwright.sync_api import sync_playwright
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg",
         "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-r", str(fps), str(out)], stdin=subprocess.PIPE)
    with sync_playwright() as p:
        browser, page = open_page(p, Path(page_path), w, h)
        for f in range(f0, f1):
            page.evaluate(f"renderFrame({f / fps:.6f})")
            ff.stdin.write(page.screenshot(type="jpeg", quality=94))
        browser.close()
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg (сегмент) завершился с ошибкой")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="540x960, 15 fps")
    ap.add_argument("--fps", type=int)
    ap.add_argument("--width", type=int)
    ap.add_argument("--workers", type=int, default=max(1, min(6, os.cpu_count() or 2)))
    ap.add_argument("--still", type=float, nargs="*", help="только PNG-кадры в указанные секунды")
    a = ap.parse_args()
    w = a.width or (540 if a.preview else 1080)
    h = w * 16 // 9
    fps = a.fps or (15 if a.preview else 60)

    page_path, tl = build_page()
    if a.still is not None:
        from playwright.sync_api import sync_playwright
        out_dir = BUILD / "stills"
        out_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser, page = open_page(p, page_path, w, h)
            for s in a.still:
                page.evaluate(f"renderFrame({s})")
                page.screenshot(path=str(out_dir / f"still_{s:05.2f}.png"))
            browser.close()
        print(f"[render] кадры сохранены в {out_dir}")
        return

    n = int(math.ceil(tl["total"] * fps))
    k = min(a.workers, n)
    chunk = int(math.ceil(n / k))
    seg_dir = BUILD / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(str(page_path), w, h, fps, i * chunk, min(n, (i + 1) * chunk), seg_dir / f"seg_{i:02d}.mp4")
            for i in range(k) if i * chunk < n]
    print(f"[render] {w}x{h} @ {fps} fps, {n} кадров, {len(jobs)} потоков...")
    t0 = time.time()
    with ProcessPoolExecutor(len(jobs)) as ex:
        segs = list(ex.map(worker, jobs))
    lst = seg_dir / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    out = BUILD / f"video_{w}x{h}_{fps}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(out)], check=True)
    print(f"[render] готово за {time.time() - t0:.1f}s → {out}")


if __name__ == "__main__":
    main()
