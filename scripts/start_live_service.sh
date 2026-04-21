#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

python services/production_live_stream_service.py \
  --input "${1:-rtmp://127.0.0.1:1935/live/source}" \
  --models-dir "${2:-$ROOT_DIR/models}" \
  --queue-size "${3:-8}" \
  --pace-input-realtime \
  --analysis-fps "${4:-12}" \
  --output-fps "${5:-25}" \
  --overlay-mode "${6:-sei}" \
  --device cuda:0
