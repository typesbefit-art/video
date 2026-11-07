#!/usr/bin/env bash
# Одна команда — всё видео.
#   ./run.sh preview   — быстрый предпросмотр 540x960 @ 15 fps → output/preview.mp4
#   ./run.sh           — финал 1080x1920 @ 60 fps → output/video.mp4
#   FPS=30 ./run.sh    — финал с другой частотой кадров
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-final}"
FLAG=""
[ "$MODE" = "preview" ] && FLAG="--preview"
[ -n "${FPS:-}" ] && FLAG="$FLAG --fps $FPS"

# зависимости (ставятся один раз)
python3 -c "import edge_tts, numpy, playwright" 2>/dev/null || pip install -q -r requirements.txt
command -v ffmpeg >/dev/null || { echo "Нужен ffmpeg (apt install ffmpeg / brew install ffmpeg)"; exit 1; }
python3 - <<'EOF' || python3 -m playwright install chromium
import os
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try:
        p.chromium.launch().close()
    except Exception:
        if not os.path.exists("/opt/pw-browsers/chromium"):
            raise
EOF

python3 tts.py            # озвучка + тайминги слов → build/voice.wav, build/timeline.json
python3 audio.py          # музыка и эффекты       → build/music.wav, build/sfx.wav
python3 render.py $FLAG   # кадры (Playwright)     → build/video_*.mp4
python3 build.py $FLAG    # сборка + проверка      → output/*.mp4
