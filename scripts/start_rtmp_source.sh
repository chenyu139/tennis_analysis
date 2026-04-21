#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

python services/rtmp_source_service.py \
  --input "${1:-$ROOT_DIR/input_videos/tennis.mp4}" \
  --rtmp-url "${2:-rtmp://127.0.0.1:1935/live/source}"
