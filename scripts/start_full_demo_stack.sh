#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

INPUT_VIDEO="${1:-$ROOT_DIR/input_videos/youtube/youtube_match.mp4}"
OVERLAY_MODE="${2:-sei}"
HTTP_PORT="${3:-8080}"
WS_PORT="${4:-8765}"
SOURCE_URL="${5:-rtmp://127.0.0.1:1935/live/source}"
ANALYSIS_URL="${6:-rtmp://127.0.0.1:1935/live/analysis}"

cleanup() {
  if [[ -n "${SOURCE_PID:-}" ]] && kill -0 "$SOURCE_PID" 2>/dev/null; then
    kill "$SOURCE_PID" 2>/dev/null || true
    wait "$SOURCE_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

python services/rtmp_source_service.py \
  --input "$INPUT_VIDEO" \
  --rtmp-url "$SOURCE_URL" &
SOURCE_PID=$!

sleep 3

python services/demo_app.py \
  --input "$SOURCE_URL" \
  --models-dir "$ROOT_DIR/models" \
  --pace-input-realtime \
  --overlay-mode "$OVERLAY_MODE" \
  --port "$HTTP_PORT" \
  --ws-port "$WS_PORT" \
  --analysis-rtmp-url "$ANALYSIS_URL" \
  --source-rtmp-url "$SOURCE_URL" \
  --device cuda:0
