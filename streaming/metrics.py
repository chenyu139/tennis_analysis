from __future__ import annotations

import json
import time
from dataclasses import replace

from .models import ServiceMetrics


class RuntimeMetricsTracker:
    def __init__(self, state_store, metrics_path: str | None = None) -> None:
        self.state_store = state_store
        self.metrics_path = metrics_path
        self.started_at = time.perf_counter()
        self.last_output_ts = None
        self.metrics = ServiceMetrics(status='starting')

    def _publish(self) -> None:
        snapshot = replace(self.metrics)
        snapshot.uptime_seconds = time.perf_counter() - self.started_at
        self.state_store.update_metrics(snapshot)
        if self.metrics_path:
            with open(self.metrics_path, 'w', encoding='utf-8') as handle:
                json.dump(snapshot.to_dict(), handle, indent=2)

    def mark_status(self, status: str, error: str = '') -> None:
        self.metrics.status = status
        self.metrics.last_error = error
        self._publish()

    def on_ingest(self, queue_size: int) -> None:
        self.metrics.frames_in += 1
        self.metrics.queue_max_size = max(self.metrics.queue_max_size, queue_size)
        self._publish()

    def on_drop(self) -> None:
        self.metrics.frames_dropped += 1
        self._publish()

    def on_processed(self, processing_ms: float, analysis_ran: bool, queue_size: int) -> None:
        self.metrics.frames_processed += 1
        if analysis_ran:
            self.metrics.analysis_runs += 1
        else:
            self.metrics.analysis_skips += 1
        self.metrics.last_processing_ms = processing_ms
        count = self.metrics.frames_processed
        self.metrics.avg_processing_ms = ((self.metrics.avg_processing_ms * (count - 1)) + processing_ms) / max(count, 1)
        self.metrics.queue_max_size = max(self.metrics.queue_max_size, queue_size)
        self._publish()

    def on_output(self) -> None:
        now = time.perf_counter()
        self.metrics.frames_out += 1
        if self.last_output_ts is not None:
            delta = max(now - self.last_output_ts, 1e-6)
            self.metrics.output_fps = 1.0 / delta
        self.last_output_ts = now
        self._publish()
