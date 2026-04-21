from dataclasses import dataclass
from pathlib import Path


@dataclass
class PipelineConfig:
    analysis_fps: float = 15.0
    output_fps: float = 25.0
    court_refresh_seconds: float = 1.0
    render_stats: bool = True
    render_mini_court: bool = True
    render_court_keypoints: bool = False
    player_history_size: int = 30
    ball_history_size: int = 45
    max_ball_gap_seconds: float = 0.5
    shot_confirm_window_seconds: float = 0.35
    shot_cooldown_seconds: float = 0.45
    processing_budget_ms: float = 60.0
    backlog_drop_threshold: int = 4
    ingest_queue_size: int = 8
    enable_frame_drop: bool = True
    pace_input_realtime: bool = False
    metrics_path: str = 'runtime/live_metrics.json'
    status_path: str = 'runtime/live_packet.json'
    demo_title: str = 'Tennis Live Analysis Demo'
    overlay_mode: str = 'sei'

    def ensure_runtime_dirs(self) -> None:
        for path_str in (self.metrics_path, self.status_path):
            Path(path_str).parent.mkdir(parents=True, exist_ok=True)
