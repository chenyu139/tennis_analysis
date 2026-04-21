from __future__ import annotations

import subprocess
import threading
import time

from services.transport_hub import TransportHub


class RtmpAnnexBPublisher:
    def __init__(self, transport_hub: TransportHub, output_url: str, fps: float = 25.0) -> None:
        self.transport_hub = transport_hub
        self.output_url = output_url
        self.fps = max(float(fps), 1.0)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name='rtmp-annexb-publisher', daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=5.0)

    def _run(self) -> None:
        last_sequence_id = None
        while not self.stop_event.is_set():
            if self.process is None or self.process.poll() is not None:
                self.process = subprocess.Popen(self._build_command(), stdin=subprocess.PIPE)
                last_sequence_id = None

            packet = self.transport_hub.wait_for_packet(last_sequence_id=last_sequence_id, timeout=0.5)
            if packet is None:
                continue
            last_sequence_id = packet.sequence_id

            if self.process.stdin is None:
                time.sleep(0.1)
                continue

            try:
                self.process.stdin.write(packet.annexb_bytes)
                self.process.stdin.flush()
            except BrokenPipeError:
                try:
                    self.process.kill()
                except OSError:
                    pass
                self.process = None
                time.sleep(0.2)

    def _build_command(self) -> list[str]:
        return [
            'ffmpeg',
            '-hide_banner',
            '-loglevel',
            'warning',
            '-fflags',
            '+genpts',
            '-f',
            'h264',
            '-r',
            str(self.fps),
            '-i',
            'pipe:0',
            '-an',
            '-c:v',
            'copy',
            '-f',
            'flv',
            self.output_url,
        ]
