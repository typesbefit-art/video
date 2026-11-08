#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p out
render() { npx remotion render src/index.ts "$1" "out/$2.raw.mp4" --concurrency=4 --log=error 2>&1 | grep -v -i -E "memory|cgroup|docker|lower amount" || true
           pipeline/loudnorm.sh "out/$2.raw.mp4" "out/$2.mp4" && rm "out/$2.raw.mp4" && echo "DONE $2"; }
render Main compound_interest_5min
for i in 1 2 3 4 5; do render "Short$i" "short_$i"; done
echo ALL_DONE
