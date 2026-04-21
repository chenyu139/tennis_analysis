from __future__ import annotations

import time

from mini_court import MiniCourt
from utils import get_center_of_bbox, get_foot_position, measure_distance

from .ball_history import BallHistoryBuffer
from .court_state import CourtState
from .degrade_policy import DegradePolicy
from .player_history import PlayerTrackState
from .stats_aggregator import LiveStatsAggregator
from streaming.models import OverlayState
from streaming.scheduler import AnalysisScheduler


class MiniCourtProjector:
    def __init__(self, frame, player_state) -> None:
        self.player_state = player_state
        self.frame_height, self.frame_width = frame.shape[:2]
        self.mini_court = MiniCourt(frame)
        self.start_x, self.start_y = self.mini_court.get_start_point_of_mini_court()
        self.court_width = self.mini_court.get_width_of_mini_court()
        keypoints = self.mini_court.get_court_drawing_keypoints()
        self.court_top = min(keypoints[1::2])
        self.court_bottom = max(keypoints[1::2])

    def project(self, player_boxes, ball_box, court_keypoints=None):
        del court_keypoints
        player_positions = {player_id: self._project_bbox(bbox, use_foot=True) for player_id, bbox in player_boxes.items()}
        ball_positions = {}
        if ball_box is not None:
            ball_positions[1] = self._project_bbox(ball_box, use_foot=False)
        return player_positions, ball_positions

    def _project_bbox(self, bbox, use_foot: bool):
        if use_foot:
            x, y = get_foot_position(bbox)
        else:
            x, y = get_center_of_bbox(bbox)
        mapped_x = self.start_x + int((x / max(self.frame_width, 1)) * self.court_width)
        mapped_y = self.court_top + int((y / max(self.frame_height, 1)) * (self.court_bottom - self.court_top))
        return (mapped_x, mapped_y)


class RealtimeAnalysisPipeline:
    def __init__(
        self,
        config,
        state_store,
        player_detector=None,
        ball_detector=None,
        court_detector=None,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.scheduler = AnalysisScheduler(config)
        self.player_detector = player_detector
        self.ball_detector = ball_detector
        self.court_detector = court_detector
        self.player_state = PlayerTrackState(history_size=config.player_history_size)
        self.ball_history = BallHistoryBuffer(
            history_size=config.ball_history_size,
            max_gap_seconds=config.max_ball_gap_seconds,
            confirm_window_seconds=config.shot_confirm_window_seconds,
            shot_cooldown_seconds=config.shot_cooldown_seconds,
        )
        self.court_state = CourtState()
        self.degrade_policy = DegradePolicy(config)
        self.projector = None
        self.stats_aggregator = None
        self.consecutive_failures = 0

    def process_frame(self, video_frame, queue_size: int = 0):
        if self.projector is None:
            self.projector = MiniCourtProjector(video_frame.image, self.player_state)
            self.stats_aggregator = LiveStatsAggregator(self.projector.mini_court.get_width_of_mini_court())

        if not self.scheduler.should_analyze(video_frame.pts):
            return self.state_store.get_overlay()

        start = time.perf_counter()
        status = 'ok'
        debug = {}
        player_boxes = {}
        ball_box = None
        shot_event = None

        try:
            if self.player_detector is not None:
                player_boxes = self._detect_players(video_frame.image) or {}
        except Exception as exc:
            status = 'player_error'
            debug['player_error'] = str(exc)

        try:
            if self.ball_detector is not None:
                ball_box = self._select_ball_box(self._detect_ball(video_frame.image))
        except Exception as exc:
            if status == 'ok':
                status = 'ball_error'
            debug['ball_error'] = str(exc)

        normalized_players = self.player_state.update(player_boxes)
        ball_box, shot_event = self.ball_history.update(video_frame.pts, ball_box)

        if self.scheduler.should_refresh_court(video_frame.pts):
            try:
                if self.court_detector is not None:
                    keypoints = self._detect_court(video_frame.image)
                    self.court_state.update(keypoints, video_frame.pts)
            except Exception as exc:
                if status == 'ok':
                    status = 'court_error'
                debug['court_error'] = str(exc)

        court_keypoints = self.court_state.get()
        player_mini_court, ball_mini_court = self.projector.project(normalized_players, ball_box, court_keypoints)

        if shot_event is not None and shot_event.player_id is None:
            shot_event.player_id = self._infer_shooter(player_mini_court, ball_mini_court)
        if shot_event is not None and self.stats_aggregator is not None:
            shot_event.speed_kmh = self.stats_aggregator.current_ball_speed_kmh

        stats_row = {}
        if self.stats_aggregator is not None:
            stats_row = self.stats_aggregator.update(video_frame.pts, player_mini_court, ball_mini_court, shot_event)

        processing_ms = (time.perf_counter() - start) * 1000.0
        if status == 'ok':
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
        quality = self.degrade_policy.select_quality(processing_ms, queue_size=queue_size, consecutive_failures=self.consecutive_failures)

        overlay = OverlayState(
            frame_id=video_frame.frame_id,
            pts=video_frame.pts,
            player_boxes=normalized_players,
            ball_box=ball_box,
            court_keypoints=court_keypoints,
            player_mini_court=player_mini_court,
            ball_mini_court=ball_mini_court,
            stats_row=stats_row,
            quality_level=quality,
            debug={'processing_ms': round(processing_ms, 2), **debug},
            status=status,
        )
        self.state_store.update_overlay(overlay)
        return overlay

    def _detect_players(self, image):
        if hasattr(self.player_detector, 'detect'):
            return self.player_detector.detect(image)
        if hasattr(self.player_detector, 'detect_frame'):
            return self.player_detector.detect_frame(image)
        raise TypeError('Unsupported player detector interface')

    def _detect_ball(self, image):
        if hasattr(self.ball_detector, 'detect'):
            return self.ball_detector.detect(image)
        if hasattr(self.ball_detector, 'detect_frame'):
            return self.ball_detector.detect_frame(image)
        raise TypeError('Unsupported ball detector interface')

    def _detect_court(self, image):
        if hasattr(self.court_detector, 'predict'):
            return self.court_detector.predict(image)
        if hasattr(self.court_detector, 'detect'):
            return self.court_detector.detect(image)
        raise TypeError('Unsupported court detector interface')

    def _select_ball_box(self, raw_ball):
        if raw_ball is None:
            return None
        if isinstance(raw_ball, dict):
            if not raw_ball:
                return None
            return list(next(iter(raw_ball.values())))
        if isinstance(raw_ball, (list, tuple)) and len(raw_ball) == 4:
            return list(raw_ball)
        return None

    def _infer_shooter(self, player_mini_court, ball_mini_court):
        ball_position = ball_mini_court.get(1)
        if ball_position is None or not player_mini_court:
            return None
        return min(player_mini_court, key=lambda player_id: measure_distance(player_mini_court[player_id], ball_position))
