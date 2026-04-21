from .models import VideoFrame


class StreamDecoder:
    def __init__(self, ingress) -> None:
        self.ingress = ingress

    def frames(self):
        frame_id = 0
        while True:
            ok, image, pts = self.ingress.read()
            if not ok:
                break
            yield VideoFrame(frame_id=frame_id, pts=float(pts or 0.0), image=image)
            frame_id += 1

    def close(self) -> None:
        self.ingress.close()
