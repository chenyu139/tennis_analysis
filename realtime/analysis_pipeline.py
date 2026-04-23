from __future__ import annotations

import time
from threading import Lock

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
        self._ball_detector_lock = Lock()
        self.player_state = PlayerTrackState(history_size=config.player_history_size)
        self.ball_history = BallHistoryBuffer(
            history_size=config.ball_history_size,
            trail_size=config.ball_trail_size,
            max_gap_seconds=config.max_ball_gap_seconds,
            max_missing_frames=config.ball_max_missing_frames,
            confirm_window_seconds=config.shot_confirm_window_seconds,
            shot_cooldown_seconds=config.shot_cooldown_seconds,
        )
        self.court_state = CourtState()
        self.degrade_policy = DegradePolicy(config)
        self.projector = None
        self.stats_aggregator = None
        self.consecutive_failures = 0
        self.analysis_count = 0
        self.cached_player_boxes = {}

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
        ball_trail = []
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
                should_refresh_players = self._should_refresh_players()
                if should_refresh_players:
                    raw_player_boxes = self._detect_players(video_frame.image) or {}
                    player_boxes = self._select_players_for_tennis(raw_player_boxes, court_keypoints, video_frame.image.shape) or {}
                    if player_boxes:
                        player_boxes = self._merge_with_cached_players(
                            player_boxes,
                            court_keypoints,
                            video_frame.image.shape,
                        )
                        self.cached_player_boxes = {track_id: list(bbox) for track_id, bbox in player_boxes.items()}
                    elif self.cached_player_boxes:
                        player_boxes = {track_id: list(bbox) for track_id, bbox in self.cached_player_boxes.items()}
                else:
                    player_boxes = {track_id: list(bbox) for track_id, bbox in self.cached_player_boxes.items()}
                debug['player_reused'] = not should_refresh_players
        except Exception as exc:
            status = 'player_error'
            debug['player_error'] = str(exc)
        debug['player_ms'] = round((time.perf_counter() - player_started) * 1000.0, 2)

        ball_started = time.perf_counter()
        try:
            ball_detector, ball_detector_type = self.get_ball_detector()
            if ball_detector is not None:
                ball_box = self._select_ball_box(self._detect_ball(video_frame.image, ball_detector))
                debug['ball_detector'] = ball_detector_type
        except Exception as exc:
            if status == 'ok':
                status = 'ball_error'
            debug['ball_error'] = str(exc)
        debug['ball_ms'] = round((time.perf_counter() - ball_started) * 1000.0, 2)

        normalized_players = self.player_state.update(
            player_boxes,
            pts=video_frame.pts,
            stale_seconds=float(getattr(self.config, 'player_stale_seconds', 0.3)),
        )
        ball_box, shot_event, ball_trail = self.ball_history.update(video_frame.pts, ball_box)
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
            ball_trail=ball_trail,
            shot_event=self._serialize_shot_event(shot_event),
            court_keypoints=court_keypoints,
            player_mini_court=player_mini_court,
            ball_mini_court=ball_mini_court,
            stats_row=stats_row,
            quality_level=quality,
            debug={
                'processing_ms': round(processing_ms, 2),
                'selected_players': len(player_boxes),
                'normalized_players': len(normalized_players),
                'court_points': len(court_keypoints) // 2,
                **debug,
            },
            status=status,
        )
        self.analysis_count += 1
        self.state_store.update_overlay(overlay)
        return overlay

    def _detect_players(self, image):
        if hasattr(self.player_detector, 'detect'):
            return self.player_detector.detect(image)
        if hasattr(self.player_detector, 'detect_frame'):
            return self.player_detector.detect_frame(image)
        raise TypeError('Unsupported player detector interface')

    def set_ball_detector(self, detector, detector_type: str | None = None):
        with self._ball_detector_lock:
            self.ball_detector = detector
            if detector_type:
                self.config.ball_detector_type = detector_type

    def get_ball_detector(self):
        with self._ball_detector_lock:
            return self.ball_detector, getattr(self.config, 'ball_detector_type', 'yolo')

    def _detect_ball(self, image, detector=None):
        active_detector = detector
        if active_detector is None:
            active_detector, _detector_type = self.get_ball_detector()
        if hasattr(active_detector, 'detect'):
            return active_detector.detect(image)
        if hasattr(active_detector, 'detect_frame'):
            return active_detector.detect_frame(image)
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
        top_half = []
        bottom_half = []
        for track_id, bbox in player_boxes.items():
            score = self._score_player_candidate(bbox, court_keypoints, frame_width, frame_height)
            if score is not None:
                zone = self._classify_player_zone(bbox, court_keypoints, frame_width, frame_height)
                if zone == 'top':
                    top_half.append((track_id, list(bbox), score))
                elif zone == 'bottom':
                    bottom_half.append((track_id, list(bbox), score))

        selected = []
        if top_half:
            selected.append(self._select_zone_candidate(top_half, 'top', court_keypoints, frame_width, frame_height))
        else:
            fallback_top = self._select_zone_fallback(player_boxes, 'top', court_keypoints, frame_width, frame_height)
            if fallback_top is not None:
                selected.append(fallback_top)
        if bottom_half:
            selected.append(self._select_zone_candidate(bottom_half, 'bottom', court_keypoints, frame_width, frame_height))
        else:
            fallback_bottom = self._select_zone_fallback(player_boxes, 'bottom', court_keypoints, frame_width, frame_height)
            if fallback_bottom is not None:
                selected.append(fallback_bottom)

        selected.sort(key=lambda item: get_foot_position(item[1])[1])
        return {track_id: bbox for track_id, bbox, _score in selected[:2]}

    def _score_player_candidate(self, bbox, court_keypoints, frame_width: int, frame_height: int, relaxed: bool = False):
        foot_x, foot_y = get_foot_position(bbox)
        area_score = min(self._bbox_area(bbox) / max(frame_width * frame_height, 1), 0.25)

        if not court_keypoints:
            center_x = frame_width / 2.0
            center_y = frame_height / 2.0
            center_gate = max(frame_width * 0.34, 40.0)
            center_gate_multiplier = 1.5 if relaxed else 1.35
            if abs(foot_x - center_x) > center_gate * center_gate_multiplier:
                return None
            vertical_deadband = max(frame_height * (0.045 if relaxed else 0.06), 12.0 if relaxed else 14.0)
            if abs(foot_y - center_y) < vertical_deadband:
                return None
            center_bias = 1.0 - min(abs(foot_x - center_x) / center_gate, 1.0)
            baseline_bias = min(abs(foot_y - center_y) / max(frame_height / 2.0, 1.0), 1.0)
            return area_score * 0.25 + center_bias * 0.35 + baseline_bias * 0.4

        xs = court_keypoints[0::2]
        ys = court_keypoints[1::2]
        left = min(xs)
        right = max(xs)
        top = min(ys)
        bottom = max(ys)
        expand_x = max((right - left) * (0.2 if relaxed else 0.14), 28.0 if relaxed else 22.0)
        expand_y = max((bottom - top) * (0.22 if relaxed else 0.16), 22.0 if relaxed else 18.0)
        if not (left - expand_x <= foot_x <= right + expand_x and top - expand_y <= foot_y <= bottom + expand_y):
            return None
        overlap_ratio = self._overlap_ratio(bbox, left - expand_x, top - expand_y, right + expand_x, bottom + expand_y)
        if overlap_ratio < (0.14 if relaxed else 0.25):
            return None

        center_x = (left + right) / 2.0
        center_y = (top + bottom) / 2.0
        center_gate = max((right - left) * 0.34, 44.0)
        lateral_distance = abs(foot_x - center_x)
        if lateral_distance > center_gate * (1.55 if relaxed else 1.3):
            return None
        vertical_deadband = max((bottom - top) * (0.045 if relaxed else 0.06), 12.0 if relaxed else 14.0)
        if abs(foot_y - center_y) < vertical_deadband:
            return None
        center_bias = 1.0 - min(lateral_distance / center_gate, 1.0)
        baseline_bias = min(abs(foot_y - center_y) / max((bottom - top) / 2.0, 1.0), 1.0)
        return area_score * 0.15 + overlap_ratio * 0.25 + center_bias * 0.2 + baseline_bias * 0.4

    def _player_priority(self, item):
        _track_id, bbox, score = item
        return (score, self._bbox_area(bbox))

    def _merge_with_cached_players(self, player_boxes, court_keypoints, image_shape):
        if len(player_boxes) >= 2 or not self.cached_player_boxes:
            return {track_id: list(bbox) for track_id, bbox in player_boxes.items()}

        frame_height, frame_width = image_shape[:2]
        merged = {track_id: list(bbox) for track_id, bbox in player_boxes.items()}
        occupied_zones = {
            self._classify_player_zone(bbox, court_keypoints, frame_width, frame_height)
            for bbox in merged.values()
        }

        for cached_track_id, cached_bbox in self.cached_player_boxes.items():
            zone = self._classify_player_zone(cached_bbox, court_keypoints, frame_width, frame_height)
            if zone is None or zone in occupied_zones:
                continue
            merged[cached_track_id] = list(cached_bbox)
            occupied_zones.add(zone)
            if len(merged) >= 2:
                break
        return merged

    def _select_zone_fallback(self, player_boxes, zone, court_keypoints, frame_width: int, frame_height: int):
        candidates = []
        previous_bbox = self._get_cached_zone_player(zone, court_keypoints, frame_width, frame_height)
        previous_foot = get_foot_position(previous_bbox) if previous_bbox is not None else None
        transition_gate = self._player_transition_gate(court_keypoints, frame_width, frame_height) * 1.45
        for track_id, bbox in player_boxes.items():
            if self._classify_player_zone(bbox, court_keypoints, frame_width, frame_height) != zone:
                continue
            score = self._score_player_candidate(bbox, court_keypoints, frame_width, frame_height, relaxed=True)
            if score is None:
                continue
            if previous_foot is not None:
                distance = measure_distance(get_foot_position(bbox), previous_foot)
                if distance > transition_gate:
                    continue
                score += max(0.0, 1.0 - distance / max(transition_gate, 1.0)) * 0.35
            candidates.append((track_id, list(bbox), score))
        if not candidates:
            return None
        return max(candidates, key=self._player_priority)

    def _select_zone_candidate(self, candidates, zone, court_keypoints, frame_width: int, frame_height: int):
        previous_bbox = self._get_cached_zone_player(zone, court_keypoints, frame_width, frame_height)
        if previous_bbox is None:
            return max(candidates, key=self._player_priority)

        previous_foot = get_foot_position(previous_bbox)
        transition_gate = self._player_transition_gate(court_keypoints, frame_width, frame_height)
        stable_candidates = [
            item for item in candidates
            if measure_distance(get_foot_position(item[1]), previous_foot) <= transition_gate
        ]
        if stable_candidates:
            return max(stable_candidates, key=self._player_priority)
        return max(candidates, key=self._player_priority)

    def _get_cached_zone_player(self, zone, court_keypoints, frame_width: int, frame_height: int):
        for bbox in self.cached_player_boxes.values():
            if self._classify_player_zone(bbox, court_keypoints, frame_width, frame_height) == zone:
                return bbox
        return None

    def _player_transition_gate(self, court_keypoints, _frame_width: int, frame_height: int):
        if not court_keypoints:
            return max(frame_height * 0.16, 70.0)
        ys = court_keypoints[1::2]
        court_height = max(max(ys) - min(ys), 1.0)
        return max(court_height * 0.18, 70.0)

    def _bbox_area(self, bbox):
        return max(float(bbox[2] - bbox[0]), 1.0) * max(float(bbox[3] - bbox[1]), 1.0)

    def _overlap_ratio(self, bbox, left, top, right, bottom):
        overlap_left = max(float(bbox[0]), left)
        overlap_top = max(float(bbox[1]), top)
        overlap_right = min(float(bbox[2]), right)
        overlap_bottom = min(float(bbox[3]), bottom)
        overlap_width = max(overlap_right - overlap_left, 0.0)
        overlap_height = max(overlap_bottom - overlap_top, 0.0)
        overlap_area = overlap_width * overlap_height
        return overlap_area / max(self._bbox_area(bbox), 1.0)

    def _classify_player_zone(self, bbox, court_keypoints, _frame_width: int, frame_height: int):
        foot_y = get_foot_position(bbox)[1]
        if not court_keypoints:
            center_y = frame_height / 2.0
            deadband = max(frame_height * 0.06, 14.0)
        else:
            ys = court_keypoints[1::2]
            center_y = (min(ys) + max(ys)) / 2.0
            deadband = max((max(ys) - min(ys)) * 0.06, 14.0)
        if foot_y <= center_y - deadband:
            return 'top'
        if foot_y >= center_y + deadband:
            return 'bottom'
        return None

    def _should_refresh_players(self):
        interval = max(int(getattr(self.config, 'player_detect_every_n_frames', 1)), 1)
        if not self.cached_player_boxes:
            return True
        return self.analysis_count % interval == 0

    def _infer_shooter(self, player_mini_court, ball_mini_court):
        ball_position = ball_mini_court.get(1)
        if ball_position is None or not player_mini_court:
            return None
        return min(player_mini_court, key=lambda player_id: measure_distance(player_mini_court[player_id], ball_position))

    def _serialize_shot_event(self, shot_event):
        if shot_event is None:
            return None
        return {
            'pts': round(float(shot_event.pts), 6),
            'player_id': shot_event.player_id,
            'speed_kmh': round(float(shot_event.speed_kmh), 2),
            'event_type': shot_event.event_type,
        }
