#!/bin/bash
# Assemble rendered shots into the final video (same format as the original: 576x1024, 30 fps, h264 + aac)
set -e
S=${S:-$(pwd)}
SRC="/root/.claude/uploads/b30dc362-78cf-5b3d-9fc0-51214cf518a6/9df41be8-fca7cc2a9ca057fdc1580a67397a3f2d.mp4"
OUT=${1:-$S/supra_clouds.mp4}
R=$S/render
inp() { echo "-framerate 30 -start_number 1 -i $R/s$1/%04d.png"; }
# shot1 is 86 frames (2.867 s); pixelize transition of 0.267 s into shot2 -> cut at 2.6 s like the original
ffmpeg -y -v error $(inp 1) $(inp 2) $(inp 3) $(inp 4) $(inp 5) -i "$SRC" -filter_complex "
[0:v]format=yuv420p,setsar=1[a];[1:v]format=yuv420p,setsar=1[b];
[a][b]xfade=transition=pixelize:duration=0.267:offset=2.6[ab];
[2:v]format=yuv420p,setsar=1[c];[3:v]format=yuv420p,setsar=1[d];[4:v]format=yuv420p,setsar=1[e];
[ab][c][d][e]concat=n=4:v=1:a=0,fps=30[v];
[5:a]atrim=0:12.87,afade=t=out:st=12.2:d=0.67[au]" \
  -map "[v]" -map "[au]" -c:v libx264 -preset slow -crf 18 -profile:v high -pix_fmt yuv420p \
  -c:a aac -b:a 128k -movflags +faststart -shortest "$OUT"
ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate,bit_rate -of compact "$OUT"
