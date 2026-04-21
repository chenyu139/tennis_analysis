from __future__ import annotations

import threading
from dataclasses import dataclass

@dataclass
class PublishedPacket:
    sequence_id: int
    frame_id: int
    pts: float
    dts: float
    is_keyframe: bool
    annexb_bytes: bytes
    metadata: dict


class TransportHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._latest: PublishedPacket | None = None

    def publish(self, sequence_id: int, annexb_bytes: bytes, metadata: dict, is_keyframe: bool = False, dts: float | None = None) -> PublishedPacket:
        packet = PublishedPacket(
            sequence_id=int(sequence_id),
            frame_id=int(metadata['frame_id']),
            pts=float(metadata['pts']),
            dts=float(dts if dts is not None else metadata['pts']),
            is_keyframe=bool(is_keyframe),
            annexb_bytes=bytes(annexb_bytes),
            metadata=dict(metadata),
        )
        with self._condition:
            self._latest = packet
            self._condition.notify_all()
        return packet

    def get_latest(self) -> PublishedPacket | None:
        with self._lock:
            return self._latest

    def wait_for_packet(self, last_sequence_id: int | None = None, timeout: float = 1.0) -> PublishedPacket | None:
        with self._condition:
            def has_new_packet() -> bool:
                return self._latest is not None and (last_sequence_id is None or self._latest.sequence_id > last_sequence_id)

            if not has_new_packet():
                self._condition.wait(timeout=timeout)
            if has_new_packet():
                return self._latest
            return None
