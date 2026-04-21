from __future__ import annotations

from threading import Lock

from .models import OverlayState, ServiceMetrics


class LiveStateStore:
    def __init__(self) -> None:
        self._overlay = OverlayState()
        self._metrics = ServiceMetrics()
        self._lock = Lock()

    def update_overlay(self, overlay: OverlayState) -> None:
        with self._lock:
            self._overlay = overlay

    def get_overlay(self) -> OverlayState:
        with self._lock:
            return self._overlay

    def update_metrics(self, metrics: ServiceMetrics) -> None:
        with self._lock:
            self._metrics = metrics

    def get_metrics(self) -> ServiceMetrics:
        with self._lock:
            return self._metrics
