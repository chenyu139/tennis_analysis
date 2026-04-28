from __future__ import annotations

from collections import defaultdict

from .rally_tracker import RallyTracker
from .shot_classifier import ShotClassifier
from .zone_mapper import ZoneMapper


class TacticalAggregator:
    def __init__(
        self,
        mini_court_width_pixels: float,
        rally_timeout: float = 3.0,
        ball_lost_timeout: float = 2.0,
        right_handed: dict[int, bool] | None = None,
        heatmap_grid_size: int = 10,
    ) -> None:
        self.rally_tracker = RallyTracker(
            rally_timeout=rally_timeout,
            ball_lost_timeout=ball_lost_timeout,
        )
        self.shot_classifier = ShotClassifier(
            mini_court_width_pixels=mini_court_width_pixels,
            right_handed=right_handed,
        )
        self.zone_mapper = ZoneMapper(mini_court_width_pixels=mini_court_width_pixels)
        self.heatmap_grid_size = heatmap_grid_size

        self.shot_type_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.landing_zone_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.player_heatmap: dict[int, list[list[int]]] = {}
        self.net_approach_counts: dict[int, dict[str, int]] = defaultdict(lambda: {'attempts': 0, 'wins': 0})
        self.speed_by_shot_type: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        self._player_top_zone: dict[int, bool] = {}
        self._last_net_position: dict[int, bool] = {}

    def _init_heatmap(self, player_id: int):
        if player_id not in self.player_heatmap:
            self.player_heatmap[player_id] = [
                [0] * self.heatmap_grid_size for _ in range(self.heatmap_grid_size)
            ]

    def _update_heatmap(self, player_id: int, position: tuple[float, float], frame_width: float, frame_height: float):
        self._init_heatmap(player_id)
        grid_x = min(int(position[0] / max(frame_width, 1) * self.heatmap_grid_size), self.heatmap_grid_size - 1)
        grid_y = min(int(position[1] / max(frame_height, 1) * self.heatmap_grid_size), self.heatmap_grid_size - 1)
        grid_x = max(0, grid_x)
        grid_y = max(0, grid_y)
        self.player_heatmap[player_id][grid_y][grid_x] += 1

    def _get_net_y(self, court_keypoints: list[float]) -> float:
        if not court_keypoints or len(court_keypoints) < 4:
            return 0.0
        ys = court_keypoints[1::2]
        return (min(ys) + max(ys)) / 2.0

    def _get_court_left(self, court_keypoints: list[float]) -> float:
        if not court_keypoints or len(court_keypoints) < 2:
            return 0.0
        xs = court_keypoints[0::2]
        return min(xs)

    def _is_top_player(self, player_id: int, player_position: tuple[float, float], net_y: float) -> bool:
        if player_id in self._player_top_zone:
            return self._player_top_zone[player_id]
        is_top = player_position[1] < net_y
        self._player_top_zone[player_id] = is_top
        return is_top

    def update(
        self,
        pts: float,
        shot_event,
        player_mini_court: dict[int, tuple[int, int]],
        ball_mini_court: dict[int, tuple[int, int]],
        court_keypoints: list[float],
        ball_box_is_none: bool = False,
        frame_width: float = 1.0,
        frame_height: float = 1.0,
    ) -> dict:
        net_y = self._get_net_y(court_keypoints)
        court_left = self._get_court_left(court_keypoints)

        for player_id, pos in player_mini_court.items():
            self._update_heatmap(player_id, (float(pos[0]), float(pos[1])), frame_width, frame_height)

            depth_label = self.zone_mapper.get_depth_label(float(pos[1]), net_y)
            was_at_net = self._last_net_position.get(player_id, False)
            is_at_net = depth_label == 'net'
            if is_at_net and not was_at_net:
                self.net_approach_counts[player_id]['attempts'] += 1
            self._last_net_position[player_id] = is_at_net

        if ball_box_is_none:
            finished_rally = self.rally_tracker.on_ball_lost(pts)
            if finished_rally is not None:
                self._on_rally_finished(finished_rally)
        else:
            self.rally_tracker.on_ball_seen(pts)

        if shot_event is not None:
            player_id = shot_event.player_id or 1
            player_pos = player_mini_court.get(player_id, (0, 0))
            ball_pos = ball_mini_court.get(1, (0, 0))

            is_rally_start = self.rally_tracker.current_rally is None or len(self.rally_tracker.current_rally.shots) == 0

            shot_type = self.shot_classifier.classify(
                player_id=player_id,
                player_position=(float(player_pos[0]), float(player_pos[1])),
                ball_position=(float(ball_pos[0]), float(ball_pos[1])),
                net_y_pixel=net_y,
                is_rally_start=is_rally_start,
            )

            target_player_id = 2 if player_id == 1 else 1
            is_target_top = self._is_top_player(target_player_id, (0.0, net_y - 1.0), net_y)
            landing_zone = self.zone_mapper.get_landing_zone(
                ball_position=(float(ball_pos[0]), float(ball_pos[1])),
                net_y_pixel=net_y,
                court_left_pixel=court_left,
                target_player_id=target_player_id,
                is_target_top=is_target_top,
            )

            self.shot_type_counts[player_id][shot_type] += 1
            self.landing_zone_counts[target_player_id][landing_zone] += 1
            self.speed_by_shot_type[player_id][shot_type].append(shot_event.speed_kmh or 0.0)

            finished_rally = self.rally_tracker.on_shot(
                shot_event, player_mini_court, ball_mini_court,
                shot_type=shot_type,
                landing_zone=landing_zone,
            )
            if finished_rally is not None:
                self._on_rally_finished(finished_rally)

        return self.get_tactical_state()

    def _on_rally_finished(self, rally):
        if rally.winner_player_id is not None:
            for shot in rally.shots:
                if shot.player_id == rally.winner_player_id:
                    depth_label = self.zone_mapper.get_depth_label(
                        shot.player_position[1], 0
                    )
                    if depth_label == 'net':
                        self.net_approach_counts[rally.winner_player_id]['wins'] += 1
                        break

    def get_tactical_state(self) -> dict:
        rally_stats = self.rally_tracker.get_stats()

        shot_distribution = {}
        for player_id, type_counts in self.shot_type_counts.items():
            total = sum(type_counts.values())
            shot_distribution[str(player_id)] = {
                shot_type: count for shot_type, count in type_counts.items()
            }
            if total > 0:
                shot_distribution[str(player_id)]['total'] = total

        landing_zones = {}
        for player_id, zone_counts in self.landing_zone_counts.items():
            total = sum(zone_counts.values())
            landing_zones[str(player_id)] = {
                zone: count for zone, count in zone_counts.items()
            }
            if total > 0:
                landing_zones[str(player_id)]['total'] = total

        speed_stats = {}
        for player_id, type_speeds in self.speed_by_shot_type.items():
            speed_stats[str(player_id)] = {}
            for shot_type, speeds in type_speeds.items():
                if speeds:
                    speed_stats[str(player_id)][shot_type] = {
                        'avg': round(sum(speeds) / len(speeds), 1),
                        'max': round(max(speeds), 1),
                        'count': len(speeds),
                    }

        net_stats = {}
        for player_id, counts in self.net_approach_counts.items():
            attempts = counts['attempts']
            wins = counts['wins']
            net_stats[str(player_id)] = {
                'attempts': attempts,
                'wins': wins,
                'win_rate': round(wins / attempts, 2) if attempts > 0 else 0.0,
            }

        heatmap_data = {}
        for player_id, grid in self.player_heatmap.items():
            max_val = max(max(row) for row in grid) if grid and any(any(r for r in row) for row in grid) else 1
            heatmap_data[str(player_id)] = {
                'grid': grid,
                'max': max_val,
                'size': self.heatmap_grid_size,
            }

        return {
            'rally_stats': rally_stats,
            'shot_distribution': shot_distribution,
            'landing_zones': landing_zones,
            'speed_by_shot_type': speed_stats,
            'net_approach': net_stats,
            'player_heatmap': heatmap_data,
            'recent_rallies': self.rally_tracker.get_recent_rallies(limit=10),
        }
