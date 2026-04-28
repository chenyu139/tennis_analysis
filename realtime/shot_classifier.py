from __future__ import annotations

import constants


class ShotClassifier:
    SERVICE_LINE_DEPTH = constants.NO_MANS_LAND_HEIGHT
    RIGHT_HANDED_DEFAULT = {1: True, 2: True}

    def __init__(
        self,
        mini_court_width_pixels: float,
        right_handed: dict[int, bool] | None = None,
    ) -> None:
        self.mini_court_width_pixels = max(float(mini_court_width_pixels), 1.0)
        self.pixels_per_meter = self.mini_court_width_pixels / max(constants.DOUBLE_LINE_WIDTH, 0.01)
        self.right_handed = right_handed or dict(self.RIGHT_HANDED_DEFAULT)

    def classify(
        self,
        player_id: int,
        player_position: tuple[float, float],
        ball_position: tuple[float, float],
        net_y_pixel: float,
        is_rally_start: bool,
        ball_history_y: list[float] | None = None,
    ) -> str:
        if is_rally_start:
            return 'serve'

        player_depth_meters = abs(player_position[1] - net_y_pixel) / max(self.pixels_per_meter, 0.01)

        if player_depth_meters < self.SERVICE_LINE_DEPTH * 0.55:
            if ball_history_y and len(ball_history_y) >= 3:
                if self._is_overhead(ball_history_y):
                    return 'overhead'
            return 'volley'

        is_right_handed = self.right_handed.get(player_id, True)
        ball_relative_x = ball_position[0] - player_position[0]

        if is_right_handed:
            return 'forehand' if ball_relative_x >= 0 else 'backhand'
        else:
            return 'backhand' if ball_relative_x >= 0 else 'forehand'

    def _is_overhead(self, ball_history_y: list[float]) -> bool:
        if len(ball_history_y) < 3:
            return False
        recent = ball_history_y[-3:]
        deltas = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
        if not deltas:
            return False
        descending = sum(1 for d in deltas if d > 0)
        return descending >= len(deltas) * 0.6
