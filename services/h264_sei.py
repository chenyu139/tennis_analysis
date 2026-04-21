from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable
from uuid import UUID

import av


SEI_UUID = UUID('7ce15f86-8754-4f0f-a4cf-c9a0ab12f65b').bytes
START_CODE = b'\x00\x00\x00\x01'


@dataclass
class EncodedAccessUnit:
    sequence_id: int
    frame_id: int
    pts: float
    dts: float
    is_keyframe: bool
    annexb_bytes: bytes
    metadata: dict


def _apply_emulation_prevention(rbsp: bytes) -> bytes:
    output = bytearray()
    zero_count = 0
    for value in rbsp:
        if zero_count >= 2 and value <= 0x03:
            output.append(0x03)
            zero_count = 0
        output.append(value)
        if value == 0x00:
            zero_count += 1
        else:
            zero_count = 0
    return bytes(output)


def _remove_emulation_prevention(ebsp: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(ebsp):
        if index + 2 < len(ebsp) and ebsp[index] == 0x00 and ebsp[index + 1] == 0x00 and ebsp[index + 2] == 0x03:
            output.extend((0x00, 0x00))
            index += 3
            continue
        output.append(ebsp[index])
        index += 1
    return bytes(output)


def split_annexb_nals(data: bytes) -> list[bytes]:
    starts: list[int] = []
    index = 0
    while index < len(data) - 3:
        if data[index:index + 4] == START_CODE:
            starts.append(index)
            index += 4
            continue
        if data[index:index + 3] == b'\x00\x00\x01':
            starts.append(index)
            index += 3
            continue
        index += 1
    units: list[bytes] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(data)
        units.append(data[start:end])
    return units


def get_nal_type(nal_unit: bytes) -> int:
    prefix_length = 4 if nal_unit.startswith(START_CODE) else 3
    return nal_unit[prefix_length] & 0x1F


def build_sei_nal(metadata: dict) -> bytes:
    payload = json.dumps(metadata, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    sei_payload = SEI_UUID + payload
    rbsp = bytearray()
    remaining_type = 5
    while remaining_type >= 0xFF:
        rbsp.append(0xFF)
        remaining_type -= 0xFF
    rbsp.append(remaining_type)
    remaining_size = len(sei_payload)
    while remaining_size >= 0xFF:
        rbsp.append(0xFF)
        remaining_size -= 0xFF
    rbsp.append(remaining_size)
    rbsp.extend(sei_payload)
    rbsp.append(0x80)
    return START_CODE + b'\x06' + _apply_emulation_prevention(bytes(rbsp))


def inject_sei(access_unit: bytes, metadata: dict) -> bytes:
    sei_nal = build_sei_nal(metadata)
    nal_units = split_annexb_nals(access_unit)
    if not nal_units:
        return sei_nal + access_unit
    insert_index = len(nal_units)
    for index, nal_unit in enumerate(nal_units):
        nal_type = get_nal_type(nal_unit)
        if nal_type in (1, 5):
            insert_index = index
            break
    nal_units.insert(insert_index, sei_nal)
    return b''.join(nal_units)


def extract_sei_messages(access_unit: bytes) -> list[dict]:
    messages: list[dict] = []
    for nal_unit in split_annexb_nals(access_unit):
        if get_nal_type(nal_unit) != 6:
            continue
        prefix_length = 4 if nal_unit.startswith(START_CODE) else 3
        rbsp = _remove_emulation_prevention(nal_unit[prefix_length + 1:])
        cursor = 0
        while cursor + 2 <= len(rbsp):
            payload_type = 0
            while cursor < len(rbsp) and rbsp[cursor] == 0xFF:
                payload_type += 0xFF
                cursor += 1
            if cursor >= len(rbsp):
                break
            payload_type += rbsp[cursor]
            cursor += 1

            payload_size = 0
            while cursor < len(rbsp) and rbsp[cursor] == 0xFF:
                payload_size += 0xFF
                cursor += 1
            if cursor >= len(rbsp):
                break
            payload_size += rbsp[cursor]
            cursor += 1
            payload = rbsp[cursor:cursor + payload_size]
            cursor += payload_size
            if payload_type == 5 and len(payload) >= 16 and payload[:16] == SEI_UUID:
                messages.append(json.loads(payload[16:].decode('utf-8')))
            if cursor < len(rbsp) and rbsp[cursor] == 0x80:
                break
    return messages


class H264SeiEncoder:
    def __init__(self, fps: float = 25.0, bitrate: int = 4_000_000, inject_metadata: bool = True) -> None:
        self.fps = max(float(fps), 1.0)
        self.bitrate = int(bitrate)
        self.inject_metadata = bool(inject_metadata)
        self.width: int | None = None
        self.height: int | None = None
        self._codec: av.codec.context.CodecContext | None = None
        self._sequence_id = 0
        self._frame_index = 0

    def _ensure_codec(self, width: int, height: int) -> None:
        if self._codec is not None:
            return
        fps_num = int(round(self.fps * 1000))
        codec = av.CodecContext.create('libx264', 'w')
        codec.width = int(width)
        codec.height = int(height)
        codec.pix_fmt = 'yuv420p'
        codec.time_base = Fraction(1, fps_num)
        codec.framerate = Fraction(fps_num, 1000)
        codec.bit_rate = self.bitrate
        codec.options = {
            'preset': 'veryfast',
            'tune': 'zerolatency',
            'profile': 'baseline',
            'repeat-headers': '1',
            'annexb': '1',
            'aud': '1',
            'g': str(max(int(round(self.fps)), 1)),
            'keyint_min': str(max(int(round(self.fps)), 1)),
            'sc_threshold': '0',
        }
        codec.open()
        self.width = int(width)
        self.height = int(height)
        self._codec = codec

    def _encode_packets(self, image, pts_seconds: float) -> Iterable[av.packet.Packet]:
        self._ensure_codec(image.shape[1], image.shape[0])
        assert self._codec is not None
        video_frame = av.VideoFrame.from_ndarray(image, format='bgr24')
        video_frame = video_frame.reformat(width=image.shape[1], height=image.shape[0], format='yuv420p')
        video_frame.pts = self._frame_index
        self._frame_index += 1
        return self._codec.encode(video_frame)

    def encode_access_units(self, image, metadata: dict) -> list[EncodedAccessUnit]:
        packets = []
        for packet in self._encode_packets(image, metadata['pts']):
            encoded = bytes(packet)
            output_bytes = inject_sei(encoded, metadata) if self.inject_metadata else encoded
            packets.append(
                EncodedAccessUnit(
                    sequence_id=self._sequence_id,
                    frame_id=int(metadata['frame_id']),
                    pts=float(metadata['pts']),
                    dts=float(metadata['pts']),
                    is_keyframe=bool(packet.is_keyframe),
                    annexb_bytes=output_bytes,
                    metadata=dict(metadata),
                )
            )
            self._sequence_id += 1
        return packets

    def flush(self) -> list[EncodedAccessUnit]:
        if self._codec is None:
            return []
        packets = []
        for packet in self._codec.encode(None):
            packets.append(
                EncodedAccessUnit(
                    sequence_id=self._sequence_id,
                    frame_id=-1,
                    pts=0.0,
                    dts=0.0,
                    is_keyframe=bool(packet.is_keyframe),
                    annexb_bytes=bytes(packet),
                    metadata={},
                )
            )
            self._sequence_id += 1
        return packets
