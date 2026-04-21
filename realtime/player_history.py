from collections import deque


class PlayerTrackState:
    def __init__(self, history_size: int = 30) -> None:
        self.history = deque(maxlen=history_size)
        self.last_players = {}

    def update(self, player_boxes):
        if not player_boxes:
            self.history.append(self.last_players.copy())
            return self.last_players.copy()

        sorted_players = sorted(player_boxes.values(), key=lambda bbox: ((bbox[0] + bbox[2]) / 2.0, bbox[3]))
        normalized = {index: list(bbox) for index, bbox in enumerate(sorted_players[:2], start=1)}
        for player_id, bbox in self.last_players.items():
            normalized.setdefault(player_id, bbox)

        self.last_players = normalized.copy()
        self.history.append(normalized.copy())
        return normalized
