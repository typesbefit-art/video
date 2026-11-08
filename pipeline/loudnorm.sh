#!/usr/bin/env bash
# Normalise audio to YouTube loudness (-14 LUFS, -1 dBTP) without re-encoding video.
set -euo pipefail
in="$1"; out="$2"
ffmpeg -v error -y -i "$in" -c:v copy -af loudnorm=I=-14:TP=-1.5:LRA=11 -ar 48000 -c:a aac -b:a 192k -movflags +faststart "$out"
