#!/usr/bin/env bash
# Usage: pipeline/render_all.sh [Main] [Short1 ...]   (default: everything)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p out
name() { [ "$1" = Main ] && echo compound_interest_5min || echo "short_${1#Short}"; }
render() {
  local out; out=$(name "$1")
  npx remotion render src/index.ts "$1" "out/$out.raw.mp4" --concurrency=4 --log=error 2> >(grep -v -i -E "memory|cgroup|docker|lower amount" >&2)
  pipeline/loudnorm.sh "out/$out.raw.mp4" "out/$out.mp4"
  rm "out/$out.raw.mp4"
  echo "DONE $out"
}
targets=("$@"); [ ${#targets[@]} -eq 0 ] && targets=(Main Short1 Short2 Short3 Short4 Short5)
for t in "${targets[@]}"; do render "$t"; done
echo ALL_DONE
