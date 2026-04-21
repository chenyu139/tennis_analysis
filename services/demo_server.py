from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

DEMO_HTML_PATH = ROOT_DIR / 'demo' / 'index.html'
DEMO_CSS_PATH = ROOT_DIR / 'demo' / 'styles.css'
DEMO_JS_PATH = ROOT_DIR / 'demo' / 'app.js'


class DemoRequestHandler(BaseHTTPRequestHandler):
    state_store = None
    analysis_transport_hub = None
    raw_transport_hub = None
    ws_port = None
    config = None
    source_rtmp_url = None
    analysis_rtmp_url = None

    def _send_bytes(self, payload: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, data: dict, status: int = 200):
        payload = json.dumps(data).encode('utf-8')
        self._send_bytes(payload, 'application/json; charset=utf-8', status=status)

    def _serve_h264_stream(self, transport_hub):
        self.send_response(200)
        self.send_header('Cache-Control', 'no-cache, private')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Content-Type', 'video/h264')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()
        last_sequence_id = None
        while True:
            packet = transport_hub.wait_for_packet(last_sequence_id=last_sequence_id, timeout=1.0)
            if packet is None:
                continue
            last_sequence_id = packet.sequence_id
            try:
                self.wfile.write(packet.annexb_bytes)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break

    def do_GET(self):
        route = urlparse(self.path).path
        if route == '/':
            self._send_bytes(DEMO_HTML_PATH.read_bytes(), 'text/html; charset=utf-8')
            return
        if route == '/styles.css':
            self._send_bytes(DEMO_CSS_PATH.read_bytes(), 'text/css; charset=utf-8')
            return
        if route == '/app.js':
            self._send_bytes(DEMO_JS_PATH.read_bytes(), 'application/javascript; charset=utf-8')
            return
        if route == '/api/metrics':
            self._send_json(self.state_store.get_metrics().to_dict())
            return
        if route == '/api/overlay':
            overlay = self.state_store.get_overlay()
            self._send_json({
                'frame_id': overlay.frame_id,
                'pts': overlay.pts,
                'status': overlay.status,
                'quality_level': overlay.quality_level,
                'players': list(overlay.player_boxes.keys()),
                'has_ball': overlay.ball_box is not None,
                'stats_row': overlay.stats_row,
            })
            return
        if route == '/api/runtime':
            host = self.headers.get('Host', '127.0.0.1').split(':')[0]
            overlay_mode = getattr(self.config, 'overlay_mode', 'sei')
            self._send_json({
                'overlay_mode': overlay_mode,
                'available_modes': [overlay_mode],
                'ws_url': f'ws://{host}:{self.ws_port}/overlay' if self.ws_port is not None else None,
                'raw_stream_url': '/stream/raw.h264',
                'analysis_stream_url': '/stream/analysis.h264',
                'source_rtmp_url': self.source_rtmp_url,
                'analysis_rtmp_url': self.analysis_rtmp_url,
                'title': self.config.demo_title,
                'fps': self.config.output_fps,
            })
            return
        if route == '/stream/raw.h264':
            self._serve_h264_stream(self.raw_transport_hub)
            return
        if route == '/stream/analysis.h264':
            self._serve_h264_stream(self.analysis_transport_hub)
            return
        self._send_json({'error': 'not found'}, status=404)


def build_handler(
    state_store,
    analysis_transport_hub,
    raw_transport_hub,
    config,
    ws_port: int | None,
    source_rtmp_url: str | None,
    analysis_rtmp_url: str | None,
):
    class BoundDemoRequestHandler(DemoRequestHandler):
        pass

    BoundDemoRequestHandler.state_store = state_store
    BoundDemoRequestHandler.analysis_transport_hub = analysis_transport_hub
    BoundDemoRequestHandler.raw_transport_hub = raw_transport_hub
    BoundDemoRequestHandler.config = config
    BoundDemoRequestHandler.ws_port = ws_port
    BoundDemoRequestHandler.source_rtmp_url = source_rtmp_url
    BoundDemoRequestHandler.analysis_rtmp_url = analysis_rtmp_url
    return BoundDemoRequestHandler


def run_demo_server(
    state_store,
    analysis_transport_hub,
    raw_transport_hub,
    config,
    host: str = '0.0.0.0',
    port: int = 8080,
    ws_port: int | None = 8765,
    source_rtmp_url: str | None = None,
    analysis_rtmp_url: str | None = None,
):
    server = ThreadingHTTPServer(
        (host, port),
        build_handler(
            state_store,
            analysis_transport_hub,
            raw_transport_hub,
            config,
            ws_port,
            source_rtmp_url,
            analysis_rtmp_url,
        ),
    )
    print(f'Demo server listening on http://{host}:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def parse_args():
    parser = argparse.ArgumentParser(description='Run HTTP demo server for tennis live analysis.')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--ws-port', type=int, default=8765)
    return parser.parse_args()
