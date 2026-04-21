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
            selected_boxes.sort(key=lambda bbox: get_foot_position(bbox)[1])
            normalized = {1: selected_boxes[0], 2: selected_boxes[1]}

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
