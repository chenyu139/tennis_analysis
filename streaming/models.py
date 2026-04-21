from dataclasses import dataclass, field
from typing import Any

import numpy as np


def to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


@dataclass
class VideoFrame:
    frame_id: int
    pts: float
    image: np.ndarray


@dataclass
class ShotEvent:
    pts: float
    player_id: int | None = None
    speed_kmh: float = 0.0
    event_type: str = 'shot'


@dataclass
class OverlayState:
    frame_id: int = -1
    pts: float = 0.0
    player_boxes: dict[int, list[float]] = field(default_factory=dict)
    ball_box: list[float] | None = None
    ball_trail: list[list[float]] = field(default_factory=list)
    shot_event: dict[str, Any] | None = None
    court_keypoints: list[float] = field(default_factory=list)
    player_mini_court: dict[int, tuple[int, int]] = field(default_factory=dict)
    ball_mini_court: dict[int, tuple[int, int]] = field(default_factory=dict)
    stats_row: dict[str, Any] = field(default_factory=dict)
    quality_level: str = 'full'
    debug: dict[str, Any] = field(default_factory=dict)
    status: str = 'idle'


@dataclass
class ServiceMetrics:
    frames_in: int = 0
    frames_processed: int = 0
    frames_out: int = 0
    frames_dropped: int = 0
    analysis_runs: int = 0
    analysis_skips: int = 0
    queue_max_size: int = 0
    last_processing_ms: float = 0.0
    avg_processing_ms: float = 0.0
    last_analysis_ms: float = 0.0
    avg_analysis_ms: float = 0.0
    last_raw_encode_ms: float = 0.0
    avg_raw_encode_ms: float = 0.0
    last_sei_inject_ms: float = 0.0
    avg_sei_inject_ms: float = 0.0
    last_status_write_ms: float = 0.0
    avg_status_write_ms: float = 0.0
    uptime_seconds: float = 0.0
    output_fps: float = 0.0
    status: str = 'idle'
    last_error: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'frames_in': self.frames_in,
            'frames_processed': self.frames_processed,
            'frames_out': self.frames_out,
            'frames_dropped': self.frames_dropped,
            'analysis_runs': self.analysis_runs,
            'analysis_skips': self.analysis_skips,
            'queue_max_size': self.queue_max_size,
            'last_processing_ms': round(self.last_processing_ms, 2),
            'avg_processing_ms': round(self.avg_processing_ms, 2),
            'last_analysis_ms': round(self.last_analysis_ms, 2),
            'avg_analysis_ms': round(self.avg_analysis_ms, 2),
            'last_raw_encode_ms': round(self.last_raw_encode_ms, 2),
            'avg_raw_encode_ms': round(self.avg_raw_encode_ms, 2),
            'last_sei_inject_ms': round(self.last_sei_inject_ms, 2),
            'avg_sei_inject_ms': round(self.avg_sei_inject_ms, 2),
            'last_status_write_ms': round(self.last_status_write_ms, 2),
            'avg_status_write_ms': round(self.avg_status_write_ms, 2),
            'uptime_seconds': round(self.uptime_seconds, 2),
            'output_fps': round(self.output_fps, 2),
            'status': self.status,
            'last_error': self.last_error,
        }


@dataclass
class TransportPacket:
    frame_id: int
    pts: float
    overlay_frame_id: int
    player_boxes: dict[str, list[float]] = field(default_factory=dict)
    ball_box: list[float] | None = None
    ball_trail: list[list[float]] = field(default_factory=list)
    shot_event: dict[str, Any] | None = None
    court_keypoints: list[float] = field(default_factory=list)
    player_mini_court: dict[str, tuple[int, int]] = field(default_factory=dict)
    ball_mini_court: dict[str, tuple[int, int]] = field(default_factory=dict)
    stats_row: dict[str, Any] = field(default_factory=dict)
    quality_level: str = 'full'
    status: str = 'idle'
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'frame_id': self.frame_id,
            'pts': round(self.pts, 6),
            'overlay_frame_id': self.overlay_frame_id,
            'player_boxes': to_json_safe(self.player_boxes),
            'ball_box': to_json_safe(self.ball_box),
            'ball_trail': to_json_safe(self.ball_trail),
            'shot_event': to_json_safe(self.shot_event),
            'court_keypoints': to_json_safe(self.court_keypoints),
            'player_mini_court': to_json_safe(self.player_mini_court),
            'ball_mini_court': to_json_safe(self.ball_mini_court),
            'stats_row': to_json_safe(self.stats_row),
            'quality_level': self.quality_level,
            'status': self.status,
            'debug': to_json_safe(self.debug),
        }
