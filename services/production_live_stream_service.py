from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Full, Queue

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from realtime.analysis_pipeline import RealtimeAnalysisPipeline
from services.h264_sei import EncodedAccessUnit, H264SeiEncoder, inject_sei
from services.live_stream_service import build_default_detectors, resolve_runtime_device
from services.transport_hub import TransportHub
from streaming import (
    LiveStateStore,
    OpenCVStreamIngress,
    PipelineConfig,
    RTMPStreamIngress,
    RuntimeMetricsTracker,
    StreamDecoder,
)
from streaming.models import TransportPacket


class ProductionLiveStreamService:
    def __init__(
        self,
        ingress,
        analysis_pipeline,
        config: PipelineConfig,
        state_store: LiveStateStore,
        analysis_transport_hub: TransportHub,
        raw_transport_hub: TransportHub | None = None,
    ) -> None:
        self.ingress = ingress
        self.decoder = StreamDecoder(ingress)
        self.analysis_pipeline = analysis_pipeline
        self.config = config
        self.state_store = state_store
        self.analysis_transport_hub = analysis_transport_hub
        self.raw_transport_hub = raw_transport_hub or TransportHub()
        self.raw_encoder = H264SeiEncoder(fps=config.output_fps, inject_metadata=False)
        self.frame_queue = Queue(maxsize=max(config.ingest_queue_size, 1))
        self.stop_event = threading.Event()
        self.metrics = RuntimeMetricsTracker(state_store, metrics_path=config.metrics_path)
        self._reader_thread = None
        self._processor_thread = None
        self._result = {'frames_in': 0, 'frames_out': 0, 'frames_dropped': 0, 'last_packet_path': config.status_path}
        self._error = None
        self._reader_started_at = None
        self._max_frames: int | None = None

    def _enqueue_frame(self, video_frame) -> None:
        try:
            self.frame_queue.put_nowait(video_frame)
        except Full:
            if not self.config.enable_frame_drop:
                self.frame_queue.put(video_frame)
                return
            try:
                self.frame_queue.get_nowait()
            except Empty:
                pass
            self.metrics.on_drop()
            self.frame_queue.put_nowait(video_frame)

    def _reader_loop(self) -> None:
        try:
            self._reader_started_at = time.perf_counter()
            for video_frame in self.decoder.frames():
                if self.stop_event.is_set():
                    break
                if self.config.pace_input_realtime:
                    elapsed = time.perf_counter() - self._reader_started_at
                    delay = video_frame.pts - elapsed
                    if delay > 0:
                        time.sleep(delay)
                self._enqueue_frame(video_frame)
                queue_size = self.frame_queue.qsize()
                self.metrics.on_ingest(queue_size)
                self._result['frames_in'] += 1
            self.frame_queue.put(None)
        except Exception as exc:
            self._error = exc
            self.metrics.mark_status('error', str(exc))
            self.stop_event.set()
            try:
                self.frame_queue.put_nowait(None)
            except Full:
                pass

    def _processor_loop(self) -> None:
        try:
            while not self.stop_event.is_set():
                try:
                    item = self.frame_queue.get(timeout=0.2)
                except Empty:
                    if self._reader_thread is not None and not self._reader_thread.is_alive():
                        break
                    continue
                if item is None:
                    break
                queue_size = self.frame_queue.qsize()
                started = time.perf_counter()
                analysis_started = time.perf_counter()
                overlay = self.analysis_pipeline.process_frame(item, queue_size=queue_size)
                analysis_ms = (time.perf_counter() - analysis_started) * 1000.0
                if overlay is None:
                    overlay = self.state_store.get_overlay()
                packet = self._build_transport_packet(item, overlay)
                overlay = self.state_store.get_overlay()
                analysis_ran = overlay.frame_id == item.frame_id
                packet_data = packet.to_dict()
                raw_encode_started = time.perf_counter()
                raw_units = self.raw_encoder.encode_access_units(item.image, packet_data)
                raw_encode_ms = (time.perf_counter() - raw_encode_started) * 1000.0
                for raw_unit in raw_units:
                    self.raw_transport_hub.publish(
                        sequence_id=raw_unit.sequence_id,
                        annexb_bytes=raw_unit.annexb_bytes,
                        metadata=raw_unit.metadata,
                        is_keyframe=raw_unit.is_keyframe,
                        dts=raw_unit.dts,
                    )
                sei_inject_started = time.perf_counter()
                analysis_units = self._build_analysis_units(raw_units, packet_data)
                sei_inject_ms = (time.perf_counter() - sei_inject_started) * 1000.0
                for encoded_unit in analysis_units:
                    self.analysis_transport_hub.publish(
                        sequence_id=encoded_unit.sequence_id,
                        annexb_bytes=encoded_unit.annexb_bytes,
                        metadata=encoded_unit.metadata,
                        is_keyframe=encoded_unit.is_keyframe,
                        dts=encoded_unit.dts,
                    )
                status_write_started = time.perf_counter()
                self._write_status(packet)
                status_write_ms = (time.perf_counter() - status_write_started) * 1000.0
                processing_ms = (time.perf_counter() - started) * 1000.0
                self.metrics.on_processed(processing_ms, analysis_ran=analysis_ran, queue_size=queue_size)
                self.metrics.on_stage_timings(
                    analysis_ms=analysis_ms,
                    raw_encode_ms=raw_encode_ms,
                    sei_inject_ms=sei_inject_ms,
                    status_write_ms=status_write_ms,
                )
                self.metrics.on_output()
                self._result['frames_out'] += 1
                if self._max_frames is not None and self._result['frames_out'] >= self._max_frames:
                    self.stop_event.set()
                    break
        except Exception as exc:
            self._error = exc
            self.metrics.mark_status('error', str(exc))
            self.stop_event.set()

    def _build_transport_packet(self, video_frame, overlay) -> TransportPacket:
        return TransportPacket(
            frame_id=video_frame.frame_id,
            pts=video_frame.pts,
            overlay_frame_id=overlay.frame_id,
            player_boxes={str(key): value for key, value in overlay.player_boxes.items()},
            ball_box=overlay.ball_box,
            ball_trail=overlay.ball_trail,
            shot_event=overlay.shot_event,
            court_keypoints=overlay.court_keypoints,
            player_mini_court={str(key): value for key, value in overlay.player_mini_court.items()},
            ball_mini_court={str(key): value for key, value in overlay.ball_mini_court.items()},
            stats_row=overlay.stats_row,
            quality_level=overlay.quality_level,
            status=overlay.status,
            debug=dict(overlay.debug),
        )

    def _build_analysis_units(self, raw_units: list[EncodedAccessUnit], metadata: dict) -> list[EncodedAccessUnit]:
        analysis_units: list[EncodedAccessUnit] = []
        for raw_unit in raw_units:
            analysis_units.append(
                EncodedAccessUnit(
                    sequence_id=raw_unit.sequence_id,
                    frame_id=raw_unit.frame_id,
                    pts=raw_unit.pts,
                    dts=raw_unit.dts,
                    is_keyframe=raw_unit.is_keyframe,
                    annexb_bytes=inject_sei(raw_unit.annexb_bytes, metadata),
                    metadata=dict(metadata),
                )
            )
        return analysis_units

    def _write_status(self, packet: TransportPacket) -> None:
        payload = {
            'packet': packet.to_dict(),
            'metrics': self.state_store.get_metrics().to_dict(),
        }
        with open(self.config.status_path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2)

    def run(self, max_frames: int | None = None):
        self.config.ensure_runtime_dirs()
        self._max_frames = max_frames if max_frames is None else max(int(max_frames), 1)
        self.metrics.mark_status('starting')
        self._reader_thread = threading.Thread(target=self._reader_loop, name='stream-reader', daemon=True)
        self._processor_thread = threading.Thread(target=self._processor_loop, name='stream-processor', daemon=True)
        self._reader_thread.start()
        self._processor_thread.start()
        self._reader_thread.join()
        self._processor_thread.join()
        self._result['frames_dropped'] = self.state_store.get_metrics().frames_dropped
        self.metrics.mark_status('stopped' if self._error is None else 'error', str(self._error or ''))
        self.decoder.close()
        if self._error is not None:
            raise self._error
        return dict(self._result)


def parse_args():
    parser = argparse.ArgumentParser(description='Run production-ready tennis live stream service.')
    parser.add_argument('--input', required=True, help='Input file path or live stream URL.')
    parser.add_argument('--player-model', default=None, help='Optional player detector model path.')
    parser.add_argument('--ball-model', default=None, help='Optional tennis ball detector model path.')
    parser.add_argument('--court-model', default=None, help='Optional court keypoint model path.')
    parser.add_argument('--models-dir', default='models', help='Directory containing all required model weights.')
    parser.add_argument('--analysis-fps', type=float, default=20.0)
    parser.add_argument('--output-fps', type=float, default=25.0)
    parser.add_argument('--queue-size', type=int, default=8)
    parser.add_argument('--metrics-path', default='runtime/live_metrics.json')
    parser.add_argument('--status-path', default='runtime/live_packet.json')
    parser.add_argument('--device', default='cuda:0', help='GPU device, e.g. cuda:0.')
    parser.add_argument('--pace-input-realtime', action='store_true', help='Throttle file input to match source timestamps.')
    parser.add_argument('--disable-stats', action='store_true')
    parser.add_argument('--disable-mini-court', action='store_true')
    parser.add_argument('--render-court-keypoints', action='store_true')
    parser.add_argument('--overlay-mode', choices=('sei', 'websocket'), default='sei', help='Client overlay mode to expose in demo runtime config.')
    parser.add_argument('--max-frames', type=int, default=None, help='Stop after processing the given number of output frames.')
    return parser.parse_args()


def build_service_from_args(
    args,
    analysis_transport_hub: TransportHub | None = None,
    raw_transport_hub: TransportHub | None = None,
):
    device = resolve_runtime_device(args.device, require_gpu=True)
    config = PipelineConfig(
        analysis_fps=args.analysis_fps,
        output_fps=args.output_fps,
        ingest_queue_size=args.queue_size,
        pace_input_realtime=args.pace_input_realtime,
        render_stats=not args.disable_stats,
        render_mini_court=not args.disable_mini_court,
        render_court_keypoints=args.render_court_keypoints,
        metrics_path=args.metrics_path,
        status_path=args.status_path,
        overlay_mode=args.overlay_mode,
    )
    state_store = LiveStateStore()
    player_detector, ball_detector, court_detector = build_default_detectors(
        models_dir=args.models_dir,
        player_model_path=args.player_model,
        ball_model_path=args.ball_model,
        court_model_path=args.court_model,
        device=device,
    )
    analysis_pipeline = RealtimeAnalysisPipeline(
        config=config,
        state_store=state_store,
        player_detector=player_detector,
        ball_detector=ball_detector,
        court_detector=court_detector,
    )
    ingress_cls = RTMPStreamIngress if str(args.input).startswith('rtmp://') else OpenCVStreamIngress
    ingress = ingress_cls(args.input, fps_hint=config.output_fps)
    analysis_hub = analysis_transport_hub or TransportHub()
    raw_hub = raw_transport_hub or TransportHub()
    return ProductionLiveStreamService(ingress, analysis_pipeline, config, state_store, analysis_hub, raw_hub)


def main():
    args = parse_args()
    service = build_service_from_args(args)
    result = service.run(max_frames=args.max_frames)
    print(result)


if __name__ == '__main__':
    main()
