#!/usr/bin/env bash
# Soft low ambient pad (used only when assets/music.mp3 is absent).
set -e
DUR=${1:-82}
cd "$(dirname "$0")/.."
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=f=98:d=$DUR" -f lavfi -i "sine=f=147:d=$DUR" -f lavfi -i "sine=f=196.5:d=$DUR" \
  -f lavfi -i "anoisesrc=c=brown:a=0.25:d=$DUR" \
  -filter_complex "[0]volume='0.5*(1-0.4/2+0.4/2*sin(2*PI*0.08*t))':eval=frame[a];[1]volume='0.3*(1-0.5/2+0.5/2*sin(2*PI*0.11*t))':eval=frame[b];[2]volume='0.15*(1-0.6/2+0.6/2*sin(2*PI*0.06*t))':eval=frame[c];[3]lowpass=f=400,volume='0.35*(1-0.7/2+0.7/2*sin(2*PI*0.05*t))':eval=frame[n];[a][b][c][n]amix=inputs=4:normalize=0,lowpass=f=900,afade=t=in:d=3,afade=t=out:st=$((DUR-4)):d=4,loudnorm=I=-20[o]" \
  -map "[o]" -ac 2 -ar 48000 -b:a 160k public/music.mp3
