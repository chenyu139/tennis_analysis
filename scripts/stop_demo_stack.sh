#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

stop_pattern() {
  local pattern="$1"
  local label="$2"
  mapfile -t pids < <(pgrep -f "$pattern" || true)
  if [[ ${#pids[@]} -eq 0 ]]; then
    return 0
  fi

  echo "Stopping $label: ${pids[*]}"
  kill "${pids[@]}" 2>/dev/null || true
}

stop_pattern "python services/demo_app.py" "demo_app"
stop_pattern "python services/rtmp_source_service.py" "rtmp_source_service"
stop_pattern "$ROOT_DIR/tools/mediamtx/mediamtx" "mediamtx"
stop_pattern "ffmpeg.*rtmp://127.0.0.1:1935/live/source" "source ffmpeg publisher"
stop_pattern "ffmpeg.*rtmp://127.0.0.1:1935/live/analysis" "analysis ffmpeg publisher"

sleep 1

for port in 1935 8080 8765; do
  if ss -ltn "( sport = :$port )" | grep -q ":$port"; then
    echo "Port still in use: $port"
  fi
done

echo "Stop request sent."
