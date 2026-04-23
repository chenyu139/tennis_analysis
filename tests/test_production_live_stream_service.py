import json
import os
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

import numpy as np

from realtime.analysis_pipeline import RealtimeAnalysisPipeline
from realtime.player_history import PlayerTrackState
from services.demo_server import build_handler
from services.h264_sei import build_sei_nal, extract_sei_messages
from services.rtmp_source_service import RtmpSourceService
from services.transport_hub import TransportHub
from services.production_live_stream_service import ProductionLiveStreamService
from streaming import IterableFrameIngress, LiveStateStore, PipelineConfig


class StaticPlayerDetector:
    def detect(self, image):
        del image
        return {1: [132, 18, 186, 96], 2: [138, 140, 198, 228]}


class StaticBallDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, image):
        del image
        self.calls += 1
        return {1: [140, 100 + (self.calls % 3) * 10, 150, 110 + (self.calls % 3) * 10]}


class SequenceBallDetector:
    def __init__(self, detections):
        self.detections = list(detections)
        self.calls = 0

    def detect(self, image):
        del image
        index = min(self.calls, len(self.detections) - 1)
        self.calls += 1
        return self.detections[index]


class StaticCourtDetector:
    def predict(self, image):
        height, width = image.shape[:2]
        return [30, 30, width - 30, 30, 30, height - 30, width - 30, height - 30, 70, 30, 70, height - 30, width - 70, 30, width - 70, height - 30, 90, 80, width - 90, 80, 90, height - 80, width - 90, height - 80, width // 2, 80, width // 2, height - 80]


class RuntimeControllerStub:
    def __init__(self):
        self.ball_detector = 'yolo'

    def get_runtime_state(self):
        return {
            'ball_detector': self.ball_detector,
            'available_ball_detectors': [
                {'key': 'yolo', 'label': 'YOLO', 'detector_type': 'yolo', 'model_path': '/tmp/yolo.pt'},
                {'key': 'rtdetr', 'label': 'RT-DETR', 'detector_type': 'rtdetr', 'model_path': '/tmp/rtdetr.pt'},
            ],
        }

    def switch_ball_detector(self, detector_key):
        normalized = str(detector_key).strip().lower()
        if normalized not in {'yolo', 'rtdetr'}:
            raise ValueError(f'Unsupported ball detector "{detector_key}"')
        self.ball_detector = normalized
        return self.get_runtime_state()


class AudienceHeavyPlayerDetector:
    def detect(self, image):
        del image
        return {
            11: [20, 5, 70, 65],
            21: [128, 18, 182, 96],
            31: [136, 148, 198, 228],
            41: [275, 5, 319, 60],
        }


class SideBiasedPlayerDetector:
    def detect(self, image):
        del image
        return {
            10: [35, 72, 96, 198],
            20: [128, 20, 188, 94],
            30: [142, 144, 206, 228],
            40: [232, 76, 292, 202],
        }


class NoSideFallbackPlayerDetector:
    def detect(self, image):
        del image
        return {
            10: [138, 48, 188, 150],
            20: [18, 142, 72, 232],
            30: [252, 138, 314, 230],
        }


class CountingPlayerDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, image):
        del image
        self.calls += 1
        return {
            1: [132, 18, 188, 98],
            2: [138, 146, 198, 228],
        }


class SequencePlayerDetector:
    def __init__(self, detections):
        self.detections = list(detections)
        self.calls = 0

    def detect(self, image):
        del image
        index = min(self.calls, len(self.detections) - 1)
        self.calls += 1
        return self.detections[index]


class OffsetTopBottomPlayerDetector:
    def detect(self, image):
        del image
        return {
            10: [80, 18, 136, 94],
            20: [196, 146, 252, 228],
            30: [18, 92, 56, 202],
            40: [270, 84, 316, 198],
        }


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
        self.assertIn('ball_trail', packet.metadata)
        self.assertIn('stats_row', packet.metadata)
        self.assertGreaterEqual(len(packet.metadata['ball_trail']), 2)
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
        self.assertIn('-c:v', command)
        self.assertIn('copy', command)
        self.assertNotIn('-vf', command)
        self.assertEqual(command[-1], 'rtmp://127.0.0.1:1935/live/source')

    def test_analysis_pipeline_prefers_players_inside_court(self):
        temp_dir = tempfile.mkdtemp(prefix='tennis_pipeline_test_')
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=AudienceHeavyPlayerDetector(),
            ball_detector=StaticBallDetector(),
            court_detector=StaticCourtDetector(),
        )

        overlay = pipeline.process_frame(type('Frame', (), {'frame_id': 1, 'pts': 0.04, 'image': frame})(), queue_size=0)

        self.assertEqual(sorted(overlay.player_boxes.keys()), [1, 2])
        self.assertLess(overlay.player_boxes[1][3], overlay.player_boxes[2][3])
        self.assertEqual(overlay.debug['selected_players'], 2)

    def test_analysis_pipeline_prefers_top_and_bottom_players_for_tennis(self):
        temp_dir = tempfile.mkdtemp(prefix='tennis_pipeline_side_test_')
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=SideBiasedPlayerDetector(),
            ball_detector=StaticBallDetector(),
            court_detector=StaticCourtDetector(),
        )

        overlay = pipeline.process_frame(type('Frame', (), {'frame_id': 1, 'pts': 0.04, 'image': frame})(), queue_size=0)

        selected_boxes = list(overlay.player_boxes.values())
        self.assertEqual(len(selected_boxes), 2)
        self.assertIn([128, 20, 188, 94], selected_boxes)
        self.assertIn([142, 144, 206, 228], selected_boxes)
        xs = [((box[0] + box[2]) / 2) for box in selected_boxes]
        self.assertTrue(all(120 <= x <= 220 for x in xs))

    def test_analysis_pipeline_keeps_offset_top_bottom_players(self):
        temp_dir = tempfile.mkdtemp(prefix='tennis_pipeline_offset_player_test_')
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=OffsetTopBottomPlayerDetector(),
            ball_detector=StaticBallDetector(),
            court_detector=StaticCourtDetector(),
        )

        overlay = pipeline.process_frame(type('Frame', (), {'frame_id': 1, 'pts': 0.04, 'image': frame})(), queue_size=0)

        selected_boxes = list(overlay.player_boxes.values())
        self.assertEqual(len(selected_boxes), 2)
        self.assertIn([80, 18, 136, 94], selected_boxes)
        self.assertIn([196, 146, 252, 228], selected_boxes)

    def test_analysis_pipeline_exposes_ball_trail(self):
        temp_dir = tempfile.mkdtemp(prefix='tennis_pipeline_ball_trail_test_')
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            ball_trail_size=6,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=StaticPlayerDetector(),
            ball_detector=StaticBallDetector(),
            court_detector=StaticCourtDetector(),
        )

        overlay = None
        for frame_id in range(1, 5):
            overlay = pipeline.process_frame(type('Frame', (), {'frame_id': frame_id, 'pts': frame_id / 25.0, 'image': frame})(), queue_size=0)

        self.assertIsNotNone(overlay)
        self.assertGreaterEqual(len(overlay.ball_trail), 3)
        self.assertEqual(len(overlay.ball_trail[-1]), 2)
        ball_box = overlay.ball_box
        self.assertIsNotNone(ball_box)
        expected_center_x = (ball_box[0] + ball_box[2]) / 2.0
        expected_center_y = (ball_box[1] + ball_box[3]) / 2.0
        self.assertAlmostEqual(overlay.ball_trail[-1][0], expected_center_x)
        self.assertAlmostEqual(overlay.ball_trail[-1][1], expected_center_y)

    def test_analysis_pipeline_clears_ball_after_consecutive_misses(self):
        temp_dir = tempfile.mkdtemp(prefix='tennis_pipeline_ball_cut_test_')
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            ball_max_missing_frames=2,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=StaticPlayerDetector(),
            ball_detector=SequenceBallDetector([
                {1: [140, 100, 150, 110]},
                {},
                {},
                {},
            ]),
            court_detector=StaticCourtDetector(),
        )

        overlays = []
        for frame_id in range(1, 5):
            overlays.append(
                pipeline.process_frame(
                    type('Frame', (), {'frame_id': frame_id, 'pts': frame_id / 25.0, 'image': frame})(),
                    queue_size=0,
                )
            )

        self.assertIsNotNone(overlays[1].ball_box)
        self.assertGreaterEqual(len(overlays[1].ball_trail), 1)
        self.assertIsNone(overlays[3].ball_box)
        self.assertEqual(overlays[3].ball_trail, [])

    def test_analysis_pipeline_does_not_fallback_to_side_people(self):
        temp_dir = tempfile.mkdtemp(prefix='tennis_pipeline_no_side_fallback_test_')
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=NoSideFallbackPlayerDetector(),
            ball_detector=StaticBallDetector(),
            court_detector=StaticCourtDetector(),
        )

        overlay = pipeline.process_frame(type('Frame', (), {'frame_id': 1, 'pts': 0.04, 'image': frame})(), queue_size=0)

        self.assertEqual(len(overlay.player_boxes), 1)
        self.assertIn([138, 48, 188, 150], list(overlay.player_boxes.values()))

    def test_analysis_pipeline_reuses_player_detections_between_intervals(self):
        temp_dir = tempfile.mkdtemp(prefix='tennis_pipeline_reuse_test_')
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        player_detector = CountingPlayerDetector()
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            player_detect_every_n_frames=2,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=player_detector,
            ball_detector=StaticBallDetector(),
            court_detector=StaticCourtDetector(),
        )

        overlay_first = pipeline.process_frame(type('Frame', (), {'frame_id': 1, 'pts': 0.04, 'image': frame})(), queue_size=0)
        overlay_second = pipeline.process_frame(type('Frame', (), {'frame_id': 2, 'pts': 0.08, 'image': frame})(), queue_size=0)

        self.assertEqual(player_detector.calls, 1)
        self.assertFalse(overlay_first.debug['player_reused'])
        self.assertTrue(overlay_second.debug['player_reused'])

    def test_player_track_state_drops_stale_boxes(self):
        state = PlayerTrackState(history_size=8)

        first = state.update({1: [120, 20, 180, 96]}, pts=0.0, stale_seconds=0.2)
        second = state.update({}, pts=0.1, stale_seconds=0.2)
        third = state.update({}, pts=0.35, stale_seconds=0.2)

        self.assertEqual(list(first.keys()), [1])
        self.assertEqual(list(second.keys()), [1])
        self.assertEqual(third, {})

    def test_analysis_pipeline_clears_cached_players_after_empty_refresh(self):
        temp_dir = tempfile.mkdtemp(prefix='tennis_pipeline_clear_cache_test_')
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        player_detector = SequencePlayerDetector([
            {1: [132, 18, 188, 98], 2: [138, 146, 198, 228]},
            {},
        ])
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            player_detect_every_n_frames=2,
            player_stale_seconds=0.12,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=player_detector,
            ball_detector=StaticBallDetector(),
            court_detector=StaticCourtDetector(),
        )

        overlay_first = pipeline.process_frame(type('Frame', (), {'frame_id': 1, 'pts': 0.00, 'image': frame})(), queue_size=0)
        overlay_second = pipeline.process_frame(type('Frame', (), {'frame_id': 2, 'pts': 0.08, 'image': frame})(), queue_size=0)
        overlay_third = pipeline.process_frame(type('Frame', (), {'frame_id': 3, 'pts': 0.20, 'image': frame})(), queue_size=0)
        overlay_fourth = pipeline.process_frame(type('Frame', (), {'frame_id': 4, 'pts': 0.28, 'image': frame})(), queue_size=0)

        self.assertEqual(len(overlay_first.player_boxes), 2)
        self.assertEqual(len(overlay_second.player_boxes), 2)
        self.assertEqual(overlay_third.player_boxes, {})
        self.assertEqual(overlay_fourth.player_boxes, {})

    def test_analysis_pipeline_exposes_shot_event(self):
        temp_dir = tempfile.mkdtemp(prefix='tennis_pipeline_shot_event_test_')
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        config = PipelineConfig(
            analysis_fps=25.0,
            output_fps=25.0,
            metrics_path=os.path.join(temp_dir, 'live_metrics.json'),
            status_path=os.path.join(temp_dir, 'live_packet.json'),
        )
        state_store = LiveStateStore()
        pipeline = RealtimeAnalysisPipeline(
            config=config,
            state_store=state_store,
            player_detector=StaticPlayerDetector(),
            ball_detector=StaticBallDetector(),
            court_detector=StaticCourtDetector(),
        )

        overlays = []
        for frame_id in range(1, 5):
            overlays.append(
                pipeline.process_frame(
                    type('Frame', (), {'frame_id': frame_id, 'pts': frame_id / 25.0, 'image': frame})(),
                    queue_size=0,
                )
            )

        shot_overlays = [overlay for overlay in overlays if overlay.shot_event is not None]
        self.assertTrue(shot_overlays)
        self.assertEqual(shot_overlays[0].shot_event['event_type'], 'shot')
        self.assertIn('speed_kmh', shot_overlays[0].shot_event)


class DemoServerTests(unittest.TestCase):
    def test_demo_handler_serves_metrics_and_overlay(self):
        from http.server import ThreadingHTTPServer

        state_store = LiveStateStore()
        analysis_transport_hub = TransportHub()
        raw_transport_hub = TransportHub()
        runtime_controller = RuntimeControllerStub()
        handler = build_handler(
            state_store,
            analysis_transport_hub,
            raw_transport_hub,
            PipelineConfig(overlay_mode='sei'),
            ws_port=None,
            source_rtmp_url='rtmp://127.0.0.1:1935/live/source',
            analysis_rtmp_url='rtmp://127.0.0.1:1935/live/analysis',
            runtime_controller=runtime_controller,
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
            self.assertEqual(runtime['ball_detector'], 'yolo')
            self.assertEqual(len(runtime['available_ball_detectors']), 2)
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
        runtime_controller = RuntimeControllerStub()
        handler = build_handler(
            state_store,
            analysis_transport_hub,
            raw_transport_hub,
            PipelineConfig(overlay_mode='websocket'),
            ws_port=8765,
            source_rtmp_url='rtmp://127.0.0.1:1935/live/source',
            analysis_rtmp_url='rtmp://127.0.0.1:1935/live/analysis',
            runtime_controller=runtime_controller,
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
            self.assertEqual(runtime['available_modes'], ['sei', 'websocket'])
            self.assertTrue(runtime['ws_url'].endswith(':8765/overlay'))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_demo_handler_switches_ball_detector(self):
        from http.server import ThreadingHTTPServer

        state_store = LiveStateStore()
        analysis_transport_hub = TransportHub()
        raw_transport_hub = TransportHub()
        runtime_controller = RuntimeControllerStub()
        handler = build_handler(
            state_store,
            analysis_transport_hub,
            raw_transport_hub,
            PipelineConfig(overlay_mode='sei'),
            ws_port=None,
            source_rtmp_url='rtmp://127.0.0.1:1935/live/source',
            analysis_rtmp_url='rtmp://127.0.0.1:1935/live/analysis',
            runtime_controller=runtime_controller,
        )
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f'http://127.0.0.1:{server.server_port}/api/runtime',
                data=json.dumps({'ball_detector': 'rtdetr'}).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            runtime = json.loads(urlopen(request).read().decode('utf-8'))
            self.assertEqual(runtime['ball_detector'], 'rtdetr')
            self.assertEqual(runtime_controller.ball_detector, 'rtdetr')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
