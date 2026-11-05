#!/bin/bash
# контактный лист: sheet.sh dir out.jpg t1 t2 ...
d=$1; out=$2; shift 2; args=(); f=""; i=0
for t in "$@"; do args+=(-i "$d/f_$t.jpg"); f+="[$i]scale=270:480,drawtext=text='$t':x=8:y=8:fontcolor=yellow:fontsize=22[v$i];"; i=$((i+1)); done
st=""; for ((k=0;k<i;k++)); do st+="[v$k]"; done
ffmpeg -v error -y "${args[@]}" -filter_complex "${f}${st}hstack=$i" "$out"
