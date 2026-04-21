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
        court_keypoints = self.court_state.get()

        if self.scheduler.should_refresh_court(video_frame.pts):
            court_started = time.perf_counter()
            try:
                if self.court_detector is not None:
                    keypoints = self._detect_court(video_frame.image)
                    self.court_state.update(keypoints, video_frame.pts)
                    court_keypoints = self.court_state.get()
            except Exception as exc:
                if status == 'ok':
                    status = 'court_error'
                debug['court_error'] = str(exc)
            debug['court_ms'] = round((time.perf_counter() - court_started) * 1000.0, 2)

        player_started = time.perf_counter()
        try:
            if self.player_detector is not None:
                raw_player_boxes = self._detect_players(video_frame.image) or {}
                player_boxes = self._select_players_for_tennis(raw_player_boxes, court_keypoints, video_frame.image.shape) or {}
        except Exception as exc:
            status = 'player_error'
            debug['player_error'] = str(exc)
        debug['player_ms'] = round((time.perf_counter() - player_started) * 1000.0, 2)

        ball_started = time.perf_counter()
        try:
            if self.ball_detector is not None:
                ball_box = self._select_ball_box(self._detect_ball(video_frame.image))
        except Exception as exc:
            if status == 'ok':
                status = 'ball_error'
            debug['ball_error'] = str(exc)
        debug['ball_ms'] = round((time.perf_counter() - ball_started) * 1000.0, 2)

        normalized_players = self.player_state.update(player_boxes)
        ball_box, shot_event = self.ball_history.update(video_frame.pts, ball_box)
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
            debug={
                'processing_ms': round(processing_ms, 2),
                'selected_players': len(player_boxes),
                'court_points': len(court_keypoints) // 2,
                **debug,
            },
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

    def _select_players_for_tennis(self, player_boxes, court_keypoints, image_shape):
        if not player_boxes:
            return {}

        frame_height, frame_width = image_shape[:2]
        scored_players = []
        for track_id, bbox in player_boxes.items():
            score = self._score_player_candidate(bbox, court_keypoints, frame_width, frame_height)
            if score is not None:
                scored_players.append((track_id, list(bbox), score))

        if not scored_players:
            return {}

        if not court_keypoints:
            scored_players.sort(key=lambda item: (get_foot_position(item[1])[1], -item[2]))
            return {track_id: bbox for track_id, bbox, _score in scored_players[:2]}

        top_half = []
        bottom_half = []
        split_y = self._court_mid_y(court_keypoints)
        for track_id, bbox, score in scored_players:
            foot_y = get_foot_position(bbox)[1]
            if foot_y <= split_y:
                top_half.append((track_id, bbox, score))
            else:
                bottom_half.append((track_id, bbox, score))

        selected = []
        if top_half:
            selected.append(max(top_half, key=lambda item: item[2]))
        if bottom_half:
            selected.append(max(bottom_half, key=lambda item: item[2]))

        if len(selected) < 2:
            chosen_ids = {track_id for track_id, _bbox, _score in selected}
            remaining = [item for item in scored_players if item[0] not in chosen_ids]
            remaining.sort(key=lambda item: item[2], reverse=True)
            selected.extend(remaining[: 2 - len(selected)])

        selected.sort(key=lambda item: get_foot_position(item[1])[1])
        return {track_id: bbox for track_id, bbox, _score in selected[:2]}

    def _score_player_candidate(self, bbox, court_keypoints, frame_width: int, frame_height: int):
        foot_x, foot_y = get_foot_position(bbox)
        box_width = max(float(bbox[2] - bbox[0]), 1.0)
        box_height = max(float(bbox[3] - bbox[1]), 1.0)
        area_score = min((box_width * box_height) / max(frame_width * frame_height, 1), 0.2)

        if not court_keypoints:
            center_bias = 1.0 - min(abs(foot_x - (frame_width / 2.0)) / max(frame_width / 2.0, 1.0), 1.0)
            return area_score * 0.6 + center_bias * 0.4

        xs = court_keypoints[0::2]
        ys = court_keypoints[1::2]
        left = min(xs)
        right = max(xs)
        top = min(ys)
        bottom = max(ys)
        expand_x = max((right - left) * 0.08, 12.0)
        expand_y = max((bottom - top) * 0.12, 12.0)
        if not (left - expand_x <= foot_x <= right + expand_x and top - expand_y <= foot_y <= bottom + expand_y):
            return None

        center_x = (left + right) / 2.0
        center_bias = 1.0 - min(abs(foot_x - center_x) / max((right - left) / 2.0, 1.0), 1.0)
        vertical_bias = 1.0 - min(abs(foot_y - ((top + bottom) / 2.0)) / max((bottom - top) / 2.0, 1.0), 1.0)
        return area_score * 0.45 + center_bias * 0.4 + vertical_bias * 0.15

    def _court_mid_y(self, court_keypoints):
        ys = court_keypoints[1::2]
        return (min(ys) + max(ys)) / 2.0

    def _infer_shooter(self, player_mini_court, ball_mini_court):
        ball_position = ball_mini_court.get(1)
        if ball_position is None or not player_mini_court:
            return None
        return min(player_mini_court, key=lambda player_id: measure_distance(player_mini_court[player_id], ball_position))
