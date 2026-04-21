from __future__ import annotations

import cv2


class IterableFrameIngress:
    def __init__(self, frames, fps: float = 25.0) -> None:
        self.frames = list(frames)
        self.fps = fps
        self.index = 0

    def read(self):
        if self.index >= len(self.frames):
            return False, None, None
        frame = self.frames[self.index]
        pts = self.index / max(self.fps, 0.001)
        self.index += 1
        return True, frame.copy(), pts

    def close(self) -> None:
        return None


class OpenCVStreamIngress:
    def __init__(self, source: str, fps_hint: float | None = None) -> None:
        self.source = source
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            self.cap.release()
            raise ValueError(f'Could not open stream source: {source}')
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if fps and fps > 0 else (fps_hint or 25.0)
        self.frame_index = 0

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            return False, None, None
        pts = self.frame_index / max(self.fps, 0.001)
        self.frame_index += 1
        return True, frame, pts

    def close(self) -> None:
        self.cap.release()


class RTMPStreamIngress(OpenCVStreamIngress):
    def __init__(self, source: str, fps_hint: float | None = None) -> None:
        super().__init__(source=source, fps_hint=fps_hint)
