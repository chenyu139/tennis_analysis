from collections import deque

from utils import get_foot_position


class PlayerTrackState:
    def __init__(self, history_size: int = 30) -> None:
        self.history = deque(maxlen=history_size)
        self.last_players = {}

    def update(self, player_boxes):
        if not player_boxes:
            self.history.append(self.last_players.copy())
            return self.last_players.copy()

        selected_boxes = [list(bbox) for bbox in player_boxes.values()][:2]
        if len(selected_boxes) == 1:
            normalized = self._assign_single_player(selected_boxes[0])
        else:
            normalized = self._assign_multiple_players(selected_boxes)

        self.last_players = normalized.copy()
        self.history.append(normalized.copy())
        return normalized

    def _assign_single_player(self, bbox):
        if not self.last_players:
            return {1: bbox}

        foot = get_foot_position(bbox)
        player_id = min(
            self.last_players,
            key=lambda candidate_id: abs(get_foot_position(self.last_players[candidate_id])[1] - foot[1]),
        )
        normalized = {player_id: bbox}
        for existing_id, existing_bbox in self.last_players.items():
            normalized.setdefault(existing_id, existing_bbox)
        return normalized

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
