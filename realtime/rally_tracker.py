from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShotRecord:
    pts: float
    player_id: int
    speed_kmh: float
    ball_position: tuple[float, float]
    player_position: tuple[float, float]
    shot_type: str = 'unknown'
    landing_zone: str | None = None


@dataclass
class Rally:
    rally_id: int
    start_pts: float
    end_pts: float | None = None
    shots: list[ShotRecord] = field(default_factory=list)
    winner_player_id: int | None = None
    last_shot_by: int | None = None

    @property
    def rally_length(self) -> int:
        return len(self.shots)


class RallyTracker:
    def __init__(
        self,
        rally_timeout: float = 3.0,
        ball_lost_timeout: float = 2.0,
    ) -> None:
        self.rally_timeout = rally_timeout
        self.ball_lost_timeout = ball_lost_timeout
        self.rallies: list[Rally] = []
        self.current_rally: Rally | None = None
        self._next_rally_id = 1
        self._last_shot_pts: float | None = None
        self._last_ball_seen_pts: float | None = None

    def on_shot(
        self,
        shot_event,
        player_mini_court: dict[int, tuple[int, int]],
        ball_mini_court: dict[int, tuple[int, int]],
        shot_type: str = 'unknown',
        landing_zone: str | None = None,
    ) -> Rally | None:
        pts = shot_event.pts
        player_id = shot_event.player_id or 1
        speed_kmh = shot_event.speed_kmh or 0.0

        ball_pos = ball_mini_court.get(1, (0.0, 0.0))
        player_pos = player_mini_court.get(player_id, (0.0, 0.0))

        shot_record = ShotRecord(
            pts=pts,
            player_id=player_id,
            speed_kmh=speed_kmh,
            ball_position=(float(ball_pos[0]), float(ball_pos[1])),
            player_position=(float(player_pos[0]), float(player_pos[1])),
            shot_type=shot_type,
            landing_zone=landing_zone,
        )

        finished_rally = None

        if self.current_rally is not None and self._last_shot_pts is not None:
            gap = pts - self._last_shot_pts
            if gap > self.rally_timeout:
                finished_rally = self._close_current_rally(winner_player_id=player_id)
            elif player_id == self.current_rally.last_shot_by:
                finished_rally = self._close_current_rally(winner_player_id=player_id)

        if self.current_rally is None:
            self.current_rally = Rally(
                rally_id=self._next_rally_id,
                start_pts=pts,
            )
            self._next_rally_id += 1

        self.current_rally.shots.append(shot_record)
        self.current_rally.last_shot_by = player_id
        self._last_shot_pts = pts
        self._last_ball_seen_pts = pts

        return finished_rally

    def on_ball_lost(self, pts: float) -> Rally | None:
        if self.current_rally is None:
            return None
        if self._last_ball_seen_pts is not None and pts - self._last_ball_seen_pts > self.ball_lost_timeout:
            winner = self.current_rally.last_shot_by
            return self._close_current_rally(winner_player_id=winner)
        return None

    def on_ball_seen(self, pts: float) -> None:
        self._last_ball_seen_pts = pts

    def _close_current_rally(self, winner_player_id: int | None = None) -> Rally:
        rally = self.current_rally
        rally.end_pts = self._last_shot_pts
        rally.winner_player_id = winner_player_id
        self.rallies.append(rally)
        self.current_rally = None
        return rally

    def get_stats(self) -> dict:
        completed = [r for r in self.rallies if r.end_pts is not None]
        active = self.current_rally

        total_rallies = len(completed)
        lengths = [r.rally_length for r in completed]
        max_length = max(lengths) if lengths else 0
        avg_length = sum(lengths) / len(lengths) if lengths else 0.0

        wins_by_player: dict[int, int] = {}
        for r in completed:
            if r.winner_player_id is not None:
                wins_by_player[r.winner_player_id] = wins_by_player.get(r.winner_player_id, 0) + 1

        return {
            'total_rallies': total_rallies,
            'max_rally_length': max_length,
            'avg_rally_length': round(avg_length, 1),
            'wins_by_player': wins_by_player,
            'current_rally_length': active.rally_length if active else 0,
            'current_rally_shots_by_player': self._current_rally_shot_counts() if active else {},
        }

    def _current_rally_shot_counts(self) -> dict[int, int]:
        if self.current_rally is None:
            return {}
        counts: dict[int, int] = {}
        for shot in self.current_rally.shots:
            counts[shot.player_id] = counts.get(shot.player_id, 0) + 1
        return counts

    def get_recent_rallies(self, limit: int = 20) -> list[dict]:
        recent = self.rallies[-limit:] if len(self.rallies) > limit else list(self.rallies)
        result = []
        for r in reversed(recent):
            result.append({
                'rally_id': r.rally_id,
                'length': r.rally_length,
                'winner': r.winner_player_id,
                'start_pts': round(r.start_pts, 3),
                'end_pts': round(r.end_pts, 3) if r.end_pts is not None else None,
                'shots': [
                    {
                        'player_id': s.player_id,
                        'speed_kmh': round(s.speed_kmh, 1),
                        'shot_type': s.shot_type,
                        'landing_zone': s.landing_zone,
                    }
                    for s in r.shots
                ],
            })
        return result
