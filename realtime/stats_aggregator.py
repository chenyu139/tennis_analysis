from __future__ import annotations

import constants
from utils import convert_pixel_distance_to_meters, measure_distance


class LiveStatsAggregator:
    def __init__(self, mini_court_width_pixels: float) -> None:
        self.mini_court_width_pixels = max(float(mini_court_width_pixels), 1.0)
        self.last_pts = None
        self.last_player_positions = {}
        self.last_ball_position = None
        self.current_ball_speed_kmh = 0.0
        self.stats = {
            'player_1_number_of_shots': 0,
            'player_1_total_shot_speed': 0.0,
            'player_1_last_shot_speed': 0.0,
            'player_1_total_player_speed': 0.0,
            'player_1_last_player_speed': 0.0,
            'player_1_total_distance_run': 0.0,
            'player_1_last_distance_run': 0.0,
            'player_1_total_calories_burned': 0.0,
            'player_1_last_calories_burned': 0.0,
            'player_2_number_of_shots': 0,
            'player_2_total_shot_speed': 0.0,
            'player_2_last_shot_speed': 0.0,
            'player_2_total_player_speed': 0.0,
            'player_2_last_player_speed': 0.0,
            'player_2_total_distance_run': 0.0,
            'player_2_last_distance_run': 0.0,
            'player_2_total_calories_burned': 0.0,
            'player_2_last_calories_burned': 0.0,
            'ball_speed_kmh': 0.0,
        }

    def _distance_to_meters(self, distance_pixels: float) -> float:
        return convert_pixel_distance_to_meters(distance_pixels, constants.DOUBLE_LINE_WIDTH, self.mini_court_width_pixels)

    def update(self, pts: float, player_positions, ball_positions, shot_event):
        if self.last_pts is not None:
            delta_t = max(pts - self.last_pts, 1e-6)
            for player_id in (1, 2):
                if player_id in player_positions and player_id in self.last_player_positions:
                    distance_pixels = measure_distance(player_positions[player_id], self.last_player_positions[player_id])
                    distance_meters = self._distance_to_meters(distance_pixels)
                    speed_kmh = distance_meters / delta_t * 3.6
                    self.stats[f'player_{player_id}_last_distance_run'] = distance_meters
                    self.stats[f'player_{player_id}_total_distance_run'] += distance_meters
                    self.stats[f'player_{player_id}_last_player_speed'] = speed_kmh
                    self.stats[f'player_{player_id}_total_player_speed'] += speed_kmh
                    weight = constants.PLAYER_1_WEIGHT_KG if player_id == 1 else constants.PLAYER_2_WEIGHT_KG
                    calories = (distance_meters / 1000.0) * weight * constants.CALORIES_PER_KM_PER_KG
                    self.stats[f'player_{player_id}_last_calories_burned'] = calories
                    self.stats[f'player_{player_id}_total_calories_burned'] += calories

            if 1 in ball_positions and self.last_ball_position is not None:
                ball_distance_pixels = measure_distance(ball_positions[1], self.last_ball_position)
                ball_distance_meters = self._distance_to_meters(ball_distance_pixels)
                self.current_ball_speed_kmh = ball_distance_meters / delta_t * 3.6
                self.stats['ball_speed_kmh'] = self.current_ball_speed_kmh

        if shot_event is not None:
            player_id = shot_event.player_id or 1
            self.stats[f'player_{player_id}_number_of_shots'] += 1
            self.stats[f'player_{player_id}_last_shot_speed'] = shot_event.speed_kmh or self.current_ball_speed_kmh
            self.stats[f'player_{player_id}_total_shot_speed'] += self.stats[f'player_{player_id}_last_shot_speed']

        self.last_pts = pts
        self.last_player_positions = dict(player_positions)
        self.last_ball_position = ball_positions.get(1)
        return dict(self.stats)
