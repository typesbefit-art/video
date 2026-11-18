#!/bin/bash
cd ${S:-$(pwd)}
for s in 1 2 3 4 5; do
  ./venv/bin/python blend/scene.py ${S:-$(pwd)}/blend ${S:-$(pwd)}/render $s 1 10 0 > ${S:-$(pwd)}/render_s$s.log 2>&1
  echo "shot $s done $(date)" >> ${S:-$(pwd)}/progress.log
done
echo ALLDONE >> ${S:-$(pwd)}/progress.log
