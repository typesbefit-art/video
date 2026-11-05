#!/usr/bin/env bash
# Full pipeline: voiceover -> background music -> render.
set -e
cd "$(dirname "$0")/.."
python3 scripts/tts.py
if [ -f assets/music.mp3 ]; then
  cp assets/music.mp3 public/music.mp3
else
  scripts/ambient.sh 90
fi
npx remotion render src/index.ts ForestSurvival output/forest_survival.mp4 \
  --browser-executable="${BROWSER:-/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell}" "$@"
