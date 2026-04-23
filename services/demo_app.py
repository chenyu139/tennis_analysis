from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.demo_server import run_demo_server
from services.overlay_ws_server import OverlayWebSocketServer
from services.production_live_stream_service import build_service_from_args
from services.rtmp_egress import RtmpAnnexBPublisher
from services.transport_hub import TransportHub


def parse_args():
    parser = argparse.ArgumentParser(description='Run the tennis live analysis demo stack.')
    parser.add_argument('--input', required=True, help='Input file path for the demo video.')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--ws-port', type=int, default=8765)
    parser.add_argument('--models-dir', default='models')
    parser.add_argument('--analysis-fps', type=float, default=12.0)
    parser.add_argument('--output-fps', type=float, default=25.0)
    parser.add_argument('--queue-size', type=int, default=8)
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument('--ball-detector', choices=('yolo', 'rtdetr'), default='yolo')
    parser.add_argument('--metrics-path', default='runtime/live_metrics.json')
    parser.add_argument('--status-path', default='runtime/live_packet.json')
    parser.add_argument('--pace-input-realtime', action='store_true')
    parser.add_argument('--disable-stats', action='store_true')
    parser.add_argument('--disable-mini-court', action='store_true')
    parser.add_argument('--render-court-keypoints', action='store_true')
    parser.add_argument('--overlay-mode', choices=('sei', 'websocket'), default='sei')
    parser.add_argument('--player-model', default=None)
    parser.add_argument('--ball-model', default=None)
    parser.add_argument('--rtdetr-ball-model', default=None)
    parser.add_argument('--court-model', default=None)
    parser.add_argument('--analysis-rtmp-url', default='rtmp://127.0.0.1:1935/live/analysis')
    parser.add_argument('--source-rtmp-url', default='rtmp://127.0.0.1:1935/live/source')
    parser.add_argument('--max-frames', type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    analysis_transport_hub = TransportHub()
    raw_transport_hub = TransportHub()
    service = build_service_from_args(
        args,
        analysis_transport_hub=analysis_transport_hub,
        raw_transport_hub=raw_transport_hub,
    )
    ws_server = None
    analysis_publisher = RtmpAnnexBPublisher(analysis_transport_hub, output_url=args.analysis_rtmp_url, fps=args.output_fps)
    analysis_publisher.start()
    ws_server = OverlayWebSocketServer(analysis_transport_hub, host=args.host, port=args.ws_port)
    ws_server.start()
    worker = threading.Thread(
        target=service.run,
        kwargs={'max_frames': args.max_frames},
        name='production-live-service',
        daemon=True,
    )
    worker.start()
    try:
        run_demo_server(
            service.state_store,
            analysis_transport_hub,
            raw_transport_hub,
            service.config,
            host=args.host,
            port=args.port,
            ws_port=args.ws_port if ws_server is not None else None,
            source_rtmp_url=args.source_rtmp_url,
            analysis_rtmp_url=args.analysis_rtmp_url,
            runtime_controller=service,
        )
    finally:
        analysis_publisher.stop()
        if ws_server is not None:
            ws_server.stop()


if __name__ == '__main__':
    main()
