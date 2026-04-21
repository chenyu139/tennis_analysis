class CourtState:
    def __init__(self) -> None:
        self.keypoints = []
        self.last_updated_pts = None

    def update(self, keypoints, pts: float) -> None:
        self.keypoints = list(keypoints) if keypoints is not None else []
        self.last_updated_pts = pts

    def get(self):
        return list(self.keypoints)
