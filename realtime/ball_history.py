from __future__ import annotations

from collections import deque

from streaming.models import ShotEvent


class BallHistoryBuffer:
    def __init__(
        self,
        history_size: int = 45,
        trail_size: int = 10,
        max_gap_seconds: float = 0.5,
        confirm_window_seconds: float = 0.35,
        shot_cooldown_seconds: float = 0.45,
    ) -> None:
        self.history = deque(maxlen=history_size)
        self.trail = deque(maxlen=trail_size)
        self.max_gap_seconds = max_gap_seconds
        self.confirm_window_seconds = confirm_window_seconds
        self.shot_cooldown_seconds = shot_cooldown_seconds
        self.last_ball_box = None
        self.last_ball_pts = None
        self.last_shot_pts = None

    def update(self, pts: float, ball_box):
        effective_box = ball_box
        if ball_box is None and self.last_ball_box is not None and self.last_ball_pts is not None and pts - self.last_ball_pts <= self.max_gap_seconds:
            effective_box = self.last_ball_box

        if effective_box is None:
            self.history.append((pts, None))
            self.trail.clear()
            return None, None, []

        center_y = (effective_box[1] + effective_box[3]) / 2.0
        center_x = (effective_box[0] + effective_box[2]) / 2.0
        self.history.append((pts, center_y))
        self._append_trail_point((center_x, center_y))
        self.last_ball_box = list(effective_box)
        self.last_ball_pts = pts

        shot_event = None
        if len(self.history) >= 3:
            (_, y0), (_, y1), (_, y2) = list(self.history)[-3:]
            if y0 is not None and y1 is not None and y2 is not None:
                delta1 = y1 - y0
                delta2 = y2 - y1
                sign_changed = delta1 * delta2 < 0
                cooldown_ok = self.last_shot_pts is None or pts - self.last_shot_pts >= self.shot_cooldown_seconds
                if sign_changed and cooldown_ok:
                    shot_event = ShotEvent(pts=pts)
                    self.last_shot_pts = pts

        return list(effective_box), shot_event, self._trail_points()

    def _append_trail_point(self, point):
        if self.trail and self.trail[-1] == point:
            return
        self.trail.append(point)

    def _trail_points(self):
        return [[float(x), float(y)] for x, y in self.trail]
