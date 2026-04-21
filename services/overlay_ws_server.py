from __future__ import annotations

import json
import threading

from websockets.sync.server import serve


class OverlayWebSocketServer:
    def __init__(self, transport_hub, host: str = '0.0.0.0', port: int = 8765) -> None:
        self.transport_hub = transport_hub
        self.host = host
        self.port = port
        self._server = None
        self._thread = None

    def _handler(self, websocket):
        last_sequence_id = None
        while True:
            packet = self.transport_hub.wait_for_packet(last_sequence_id=last_sequence_id, timeout=1.0)
            if packet is None:
                websocket.send(json.dumps({'type': 'heartbeat'}))
                continue
            payload = dict(packet.metadata)
            payload['transport'] = 'websocket'
            websocket.send(json.dumps(payload, ensure_ascii=True))
            last_sequence_id = packet.sequence_id

    def start(self) -> None:
        def run_server():
            with serve(self._handler, self.host, self.port) as server:
                self._server = server
                server.serve_forever()

        self._thread = threading.Thread(target=run_server, name='overlay-ws-server', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2)
