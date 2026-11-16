#!/usr/bin/env bash
# Полная сборка: музыка → кадры → субтитры → итоговый mp4.
# Если есть запись голоса: ./build.sh path/to/voice.wav  (музыка автоматически приглушается под голос)
set -euo pipefail
cd "$(dirname "$0")"
VOICE="${1:-}"
python3 src/music.py
python3 src/render.py
python3 src/texts.py
if [[ -n "$VOICE" ]]; then
  ffmpeg -y -loglevel error -i build/video_noaudio.mp4 -i "$VOICE" -i output/music.wav \
    -filter_complex "[1:a]aresample=44100,apad,asplit[v][vs];[2:a]volume=0.35[m];[m][vs]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[md];[md][v]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]" \
    -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -t 59 -movflags +faststart output/video.mp4
else
  ffmpeg -y -loglevel error -i build/video_noaudio.mp4 -i output/music.wav \
    -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -af "volume=0.8" -t 59 -movflags +faststart output/video.mp4
fi
echo "OK: output/video.mp4"
