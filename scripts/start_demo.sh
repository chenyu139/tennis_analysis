#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

python services/demo_app.py \
  --input "${1:-rtmp://127.0.0.1:1935/live/source}" \
  --models-dir "${2:-$ROOT_DIR/models}" \
  --pace-input-realtime \
  --overlay-mode "${3:-sei}" \
  --port "${4:-8080}" \
  --ws-port "${5:-8765}" \
  --analysis-rtmp-url "${6:-rtmp://127.0.0.1:1935/live/analysis}" \
  --source-rtmp-url "${7:-rtmp://127.0.0.1:1935/live/source}" \
  --device cuda:0
