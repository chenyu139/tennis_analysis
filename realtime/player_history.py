from collections import deque

from utils import get_foot_position


class PlayerTrackState:
    def __init__(self, history_size: int = 30) -> None:
        self.history = deque(maxlen=history_size)
        self.last_players = {}
        self.last_seen_pts = {}

    def update(self, player_boxes, pts: float | None = None, stale_seconds: float = 0.3):
        self._prune_stale_players(pts, stale_seconds)
        if not player_boxes:
            self.history.append(self.last_players.copy())
            return self.last_players.copy()

        selected_boxes = [list(bbox) for bbox in player_boxes.values()][:2]
        if len(selected_boxes) == 1:
            normalized, seen_player_ids = self._assign_single_player(selected_boxes[0])
        else:
            normalized = self._assign_multiple_players(selected_boxes)
            seen_player_ids = set(normalized.keys())

        self.last_players = normalized.copy()
        if pts is not None:
            for player_id in seen_player_ids:
                self.last_seen_pts[player_id] = pts
            self.last_seen_pts = {player_id: last_seen for player_id, last_seen in self.last_seen_pts.items() if player_id in normalized}
        self.history.append(normalized.copy())
        return normalized

    def _assign_single_player(self, bbox):
        if not self.last_players:
            return {1: bbox}, {1}

        foot = get_foot_position(bbox)
        player_id = min(
            self.last_players,
            key=lambda candidate_id: abs(get_foot_position(self.last_players[candidate_id])[1] - foot[1]),
        )
        normalized = {player_id: bbox}
        for existing_id, existing_bbox in self.last_players.items():
            normalized.setdefault(existing_id, existing_bbox)
        return normalized, {player_id}

    def _assign_multiple_players(self, selected_boxes):
        if set(self.last_players.keys()) >= {1, 2} and len(selected_boxes) == 2:
            previous_1 = get_foot_position(self.last_players[1])
            previous_2 = get_foot_position(self.last_players[2])
            box_a, box_b = selected_boxes
            current_a = get_foot_position(box_a)
            current_b = get_foot_position(box_b)

            keep_order_cost = self._foot_distance(previous_1, current_a) + self._foot_distance(previous_2, current_b)
            swap_order_cost = self._foot_distance(previous_1, current_b) + self._foot_distance(previous_2, current_a)
            if keep_order_cost <= swap_order_cost:
                return {1: box_a, 2: box_b}
            return {1: box_b, 2: box_a}

        selected_boxes.sort(key=lambda bbox: get_foot_position(bbox)[1])
        return {1: selected_boxes[0], 2: selected_boxes[1]}

    def _foot_distance(self, left, right):
        dx = float(left[0] - right[0])
        dy = float(left[1] - right[1])
        return (dx * dx + dy * dy) ** 0.5

    def _prune_stale_players(self, pts: float | None, stale_seconds: float):
        if pts is None or stale_seconds <= 0:
            return
        active_players = {}
        active_last_seen = {}
        for player_id, bbox in self.last_players.items():
            last_seen = self.last_seen_pts.get(player_id)
            if last_seen is None or pts - last_seen <= stale_seconds:
                active_players[player_id] = bbox
                if last_seen is not None:
                    active_last_seen[player_id] = last_seen
        self.last_players = active_players
        self.last_seen_pts = active_last_seen
