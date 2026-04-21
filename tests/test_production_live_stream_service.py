import json
import os
import tempfile
import threading
import unittest
from urllib.request import urlopen

import numpy as np

from realtime.analysis_pipeline import RealtimeAnalysisPipeline
from services.demo_server import build_handler
from services.h264_sei import build_sei_nal, extract_sei_messages
from services.rtmp_source_service import RtmpSourceService
from services.transport_hub import TransportHub
from services.production_live_stream_service import ProductionLiveStreamService
from streaming import IterableFrameIngress, LiveStateStore, PipelineConfig


class StaticPlayerDetector:
    def detect(self, image):
        del image
        return {1: [30, 60, 80, 180], 2: [200, 60, 250, 180]}


class StaticBallDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, image):
        del image
        self.calls += 1
        return {1: [140, 100 + (self.calls % 3) * 10, 150, 110 + (self.calls % 3) * 10]}


class StaticCourtDetector:
    def predict(self, image):
        height, width = image.shape[:2]
        return [30, 30, width - 30, 30, 30, height - 30, width - 30, height - 30, 70, 30, 70, height - 30, width - 70, 30, width - 70, height - 30, 90, 80, width - 90, 80, 90, height - 80, width - 90, height - 80, width // 2, 80, width // 2, height - 80]


class ProductionLiveStreamServiceTests(unittest.TestCase):
    def _build_service(self, frame_count=18, queue_size=32):
        temp_dir = tempfile.mkdtemp(prefix='tennis_prod_test_')
        frames = [np.zeros((240, 320, 3), dtype=np.uint8) for _ in range(frame_count)]
        ingress = IterableFrameIngress(frames, fps=25.0)
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            ingest_queue_size=queue_size,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        analysis_transport_hub = TransportHub()
        raw_transport_hub = TransportHub()
        analysis_pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=StaticPlayerDetector(),
            ball_detector=StaticBallDetector(),
            court_detector=StaticCourtDetector(),
        )
        return (
            ProductionLiveStreamService(
                ingress,
                analysis_pipeline,
                config,
                state_store,
                analysis_transport_hub,
                raw_transport_hub,
            ),
            analysis_transport_hub,
            raw_transport_hub,
            state_store,
            temp_dir,
        )

    def test_production_service_writes_metrics_and_packet(self):
        service, transport_hub, raw_transport_hub, state_store, temp_dir = self._build_service(frame_count=10)
        result = service.run()

        self.assertEqual(result['frames_in'], 10)
        self.assertEqual(result['frames_out'], 10)
        self.assertIsNotNone(transport_hub.get_latest())
        self.assertIsNotNone(raw_transport_hub.get_latest())
        self.assertTrue(os.path.exists(os.path.join(temp_dir, 'live_metrics.json')))
        self.assertTrue(os.path.exists(os.path.join(temp_dir, 'live_packet.json')))
        with open(os.path.join(temp_dir, 'live_metrics.json'), 'r', encoding='utf-8') as handle:
            metrics = json.load(handle)
        with open(os.path.join(temp_dir, 'live_packet.json'), 'r', encoding='utf-8') as handle:
            packet = json.load(handle)
        self.assertEqual(metrics['frames_out'], 10)
        self.assertIn('packet', packet)
        self.assertIn('metrics', packet)
        self.assertEqual(state_store.get_metrics().status, 'stopped')

    def test_production_service_emits_transport_metadata(self):
        service, transport_hub, raw_transport_hub, _, _ = self._build_service(frame_count=3)
        result = service.run()
        packet = transport_hub.get_latest()
        raw_packet = raw_transport_hub.get_latest()
        self.assertEqual(result['frames_out'], 3)
        self.assertIsNotNone(packet)
        self.assertIsNotNone(raw_packet)
        self.assertIn('player_boxes', packet.metadata)
        self.assertIn('ball_box', packet.metadata)
        self.assertTrue(packet.annexb_bytes.startswith(b'\x00\x00'))
        self.assertEqual(extract_sei_messages(packet.annexb_bytes)[0]['frame_id'], packet.frame_id)
        self.assertEqual(extract_sei_messages(raw_packet.annexb_bytes), [])

    def test_production_service_honors_max_frames(self):
        service, _, _, _, _ = self._build_service(frame_count=12)
        result = service.run(max_frames=4)
        self.assertEqual(result['frames_out'], 4)
        self.assertLessEqual(result['frames_in'], 12)

    def test_rtmp_source_service_builds_low_latency_ffmpeg_command(self):
        temp_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
        temp_file.close()
        self.addCleanup(lambda: os.path.exists(temp_file.name) and os.remove(temp_file.name))
        service = RtmpSourceService(
            input_path=temp_file.name,
            rtmp_url='rtmp://127.0.0.1:1935/live/source',
            loop_input=True,
            realtime=True,
            start_server=False,
        )
        command = service._build_ffmpeg_command()
        self.assertEqual(command[:3], ['ffmpeg', '-hide_banner', '-loglevel'])
        self.assertIn('-re', command)
        self.assertIn('-stream_loop', command)
        self.assertIn('-tune', command)
        self.assertIn('zerolatency', command)
        self.assertEqual(command[-1], 'rtmp://127.0.0.1:1935/live/source')


class DemoServerTests(unittest.TestCase):
    def test_demo_handler_serves_metrics_and_overlay(self):
        from http.server import ThreadingHTTPServer

        state_store = LiveStateStore()
        analysis_transport_hub = TransportHub()
        raw_transport_hub = TransportHub()
        handler = build_handler(
            state_store,
            analysis_transport_hub,
            raw_transport_hub,
            PipelineConfig(overlay_mode='sei'),
            ws_port=None,
            source_rtmp_url='rtmp://127.0.0.1:1935/live/source',
            analysis_rtmp_url='rtmp://127.0.0.1:1935/live/analysis',
        )
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            metrics = json.loads(urlopen(f'http://127.0.0.1:{server.server_port}/api/metrics').read().decode('utf-8'))
            overlay = json.loads(urlopen(f'http://127.0.0.1:{server.server_port}/api/overlay').read().decode('utf-8'))
            runtime = json.loads(urlopen(f'http://127.0.0.1:{server.server_port}/api/runtime').read().decode('utf-8'))
            self.assertIn('frames_in', metrics)
            self.assertIn('status', overlay)
            self.assertEqual(runtime['overlay_mode'], 'sei')
            self.assertEqual(runtime['available_modes'], ['sei'])
            self.assertIsNone(runtime['ws_url'])
            self.assertEqual(runtime['source_rtmp_url'], 'rtmp://127.0.0.1:1935/live/source')
            self.assertEqual(runtime['analysis_rtmp_url'], 'rtmp://127.0.0.1:1935/live/analysis')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_demo_handler_serves_h264_stream_with_real_sei(self):
        from http.server import ThreadingHTTPServer

        state_store = LiveStateStore()
        analysis_transport_hub = TransportHub()
        raw_transport_hub = TransportHub()
        metadata = {'frame_id': 1, 'pts': 0.04, 'status': 'ready'}
        access_unit = build_sei_nal(metadata) + b'\x00\x00\x00\x01\x09\xf0'
        analysis_transport_hub.publish(sequence_id=1, annexb_bytes=access_unit, metadata=metadata, is_keyframe=True)
        raw_transport_hub.publish(sequence_id=1, annexb_bytes=b'\x00\x00\x00\x01\x09\xf0', metadata=metadata, is_keyframe=True)
        handler = build_handler(
            state_store,
            analysis_transport_hub,
            raw_transport_hub,
            PipelineConfig(overlay_mode='websocket'),
            ws_port=8765,
            source_rtmp_url='rtmp://127.0.0.1:1935/live/source',
            analysis_rtmp_url='rtmp://127.0.0.1:1935/live/analysis',
        )
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            runtime = json.loads(urlopen(f'http://127.0.0.1:{server.server_port}/api/runtime').read().decode('utf-8'))
            response = urlopen(f'http://127.0.0.1:{server.server_port}/stream/analysis.h264', timeout=2)
            self.assertEqual(response.info().get_content_type(), 'video/h264')
            chunk = response.read(len(access_unit))
            self.assertIn(build_sei_nal(metadata), chunk)
            response.close()
            self.assertEqual(runtime['overlay_mode'], 'websocket')
            self.assertEqual(runtime['available_modes'], ['websocket'])
            self.assertTrue(runtime['ws_url'].endswith(':8765/overlay'))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
