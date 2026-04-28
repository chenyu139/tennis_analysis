from __future__ import annotations

import constants


class ZoneMapper:
    DEPTH_BOUNDARY = constants.NO_MANS_LAND_HEIGHT
    HALF_COURT_LENGTH = constants.HALF_COURT_LINE_HEIGHT
    SINGLE_WIDTH = constants.SINGLE_LINE_WIDTH

    DEPTH_ZONES = ['deep', 'mid', 'net']
    LATERAL_ZONES = ['backhand', 'center', 'forehand']

    def __init__(self, mini_court_width_pixels: float) -> None:
        self.mini_court_width_pixels = max(float(mini_court_width_pixels), 1.0)
        self.pixels_per_meter = self.mini_court_width_pixels / max(constants.DOUBLE_LINE_WIDTH, 0.01)

    def pixel_to_meters(self, position: tuple[float, float], net_y_pixel: float, court_left_pixel: float) -> tuple[float, float]:
        x_meters = (position[0] - court_left_pixel) / max(self.pixels_per_meter, 0.01)
        y_meters = abs(position[1] - net_y_pixel) / max(self.pixels_per_meter, 0.01)
        return (x_meters, y_meters)

    def map_position_to_zone(
        self,
        position: tuple[float, float],
        net_y_pixel: float,
        court_left_pixel: float,
        player_id: int,
        is_top_player: bool = True,
    ) -> str:
        x_meters, y_meters = self.pixel_to_meters(position, net_y_pixel, court_left_pixel)

        if y_meters >= self.DEPTH_BOUNDARY:
            depth = 'deep'
        elif y_meters >= self.DEPTH_BOUNDARY * 0.5:
            depth = 'mid'
        else:
            depth = 'net'

        third = self.SINGLE_WIDTH / 3.0
        if x_meters < third:
            lateral = 'backhand' if is_top_player else 'forehand'
        elif x_meters < third * 2:
            lateral = 'center'
        else:
            lateral = 'forehand' if is_top_player else 'backhand'

        return f"{depth}_{lateral}"

    def get_landing_zone(
        self,
        ball_position: tuple[float, float],
        net_y_pixel: float,
        court_left_pixel: float,
        target_player_id: int,
        is_target_top: bool,
    ) -> str:
        return self.map_position_to_zone(
            ball_position, net_y_pixel, court_left_pixel, target_player_id, is_target_top
        )

    def get_depth_label(self, position_y_pixel: float, net_y_pixel: float) -> str:
        y_meters = abs(position_y_pixel - net_y_pixel) / max(self.pixels_per_meter, 0.01)
        if y_meters >= self.DEPTH_BOUNDARY:
            return 'baseline'
        if y_meters >= self.DEPTH_BOUNDARY * 0.5:
            return 'midcourt'
        return 'net'
