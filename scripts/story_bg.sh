#!/usr/bin/env bash
# Run one story part as a background user service that survives closing the terminal / Claude session.
#   scripts/story_bg.sh drafts/stories/khao_phan.json 1
#   follow:  tail -f data/logs/story.log      stop:  systemctl --user stop autovideo-story
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
systemd-run --user --unit autovideo-story --collect --working-directory "$PWD" -E PATH="$PATH" \
  -p StandardOutput=append:"$PWD/data/logs/story.log" -p StandardError=append:"$PWD/data/logs/story.log" \
  "$(command -v uv)" run autovideo story "$1" --part "$2" "${@:3}"
echo "started: tail -f data/logs/story.log"
