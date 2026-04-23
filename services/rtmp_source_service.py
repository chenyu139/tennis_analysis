from __future__ import annotations

import argparse
import signal
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.mediamtx_manager import is_tcp_port_open, start_mediamtx, wait_for_tcp_port, write_default_config


DEFAULT_INPUT = ROOT_DIR / 'input_videos' / 'youtube' / 'youtube_match.mp4'
DEFAULT_CONFIG = ROOT_DIR / 'runtime' / 'mediamtx.yml'
DEFAULT_LOG = ROOT_DIR / 'runtime' / 'mediamtx.log'


class RtmpSourceService:
    def __init__(
        self,
        input_path: Path,
        rtmp_url: str,
        *,
        loop_input: bool = True,
        realtime: bool = True,
        start_server: bool = True,
        rtmp_host: str = '127.0.0.1',
        rtmp_port: int = 1935,
        api_port: int = 9997,
        metrics_port: int = 9998,
        mediamtx_config: Path = DEFAULT_CONFIG,
        mediamtx_log: Path = DEFAULT_LOG,
    ) -> None:
        self.input_path = Path(input_path)
        self.rtmp_url = rtmp_url
        self.loop_input = loop_input
        self.realtime = realtime
        self.start_server = start_server
        self.rtmp_host = rtmp_host
        self.rtmp_port = int(rtmp_port)
        self.api_port = int(api_port)
        self.metrics_port = int(metrics_port)
        self.mediamtx_config = Path(mediamtx_config)
        self.mediamtx_log = Path(mediamtx_log)
        self.mediamtx_process: subprocess.Popen | None = None
        self.publisher_process: subprocess.Popen | None = None

    def run(self) -> int:
        if not self.input_path.exists():
            raise FileNotFoundError(f'Input video not found: {self.input_path}')

        self._install_signal_handlers()
        if self.start_server and not is_tcp_port_open(self.rtmp_host, self.rtmp_port):
            write_default_config(self.mediamtx_config, self.rtmp_port, self.api_port, self.metrics_port)
            self.mediamtx_process = start_mediamtx(self.mediamtx_config, self.mediamtx_log)
            wait_for_tcp_port(self.rtmp_host, self.rtmp_port, timeout=10.0)

        self.publisher_process = subprocess.Popen(self._build_ffmpeg_command(), cwd=str(ROOT_DIR))
        return self.publisher_process.wait()

    def stop(self) -> None:
        if self.publisher_process is not None and self.publisher_process.poll() is None:
            self.publisher_process.terminate()
            try:
                self.publisher_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.publisher_process.kill()

        if self.mediamtx_process is not None and self.mediamtx_process.poll() is None:
            self.mediamtx_process.terminate()
            try:
                self.mediamtx_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.mediamtx_process.kill()

    def _build_ffmpeg_command(self) -> list[str]:
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'warning']
        if self.realtime:
            command.append('-re')
        if self.loop_input:
            command.extend(['-stream_loop', '-1'])
        command.extend(
            [
                '-fflags',
                '+genpts',
                '-i',
                str(self.input_path),
                '-an',
                '-c:v',
                'libx264',
                '-preset',
                'veryfast',
                '-tune',
                'zerolatency',
                '-pix_fmt',
                'yuv420p',
                '-g',
                '50',
                '-f',
                'flv',
                self.rtmp_url,
            ]
        )
        return command

    def _install_signal_handlers(self) -> None:
        def handle_signal(signum, _frame):
            self.stop()
            sys.exit(128 + signum)

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)


def parse_args():
    parser = argparse.ArgumentParser(description='Start MediaMTX and push the default demo video to a local RTMP stream.')
    parser.add_argument('--input', default=str(DEFAULT_INPUT))
    parser.add_argument('--rtmp-url', default='rtmp://127.0.0.1:1935/live/source')
    parser.add_argument('--rtmp-host', default='127.0.0.1')
    parser.add_argument('--rtmp-port', type=int, default=1935)
    parser.add_argument('--api-port', type=int, default=9997)
    parser.add_argument('--metrics-port', type=int, default=9998)
    parser.add_argument('--no-loop', action='store_true')
    parser.add_argument('--no-realtime', action='store_true')
    parser.add_argument('--no-start-server', action='store_true')
    parser.add_argument('--mediamtx-config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--mediamtx-log', default=str(DEFAULT_LOG))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = RtmpSourceService(
        input_path=Path(args.input),
        rtmp_url=args.rtmp_url,
        loop_input=not args.no_loop,
        realtime=not args.no_realtime,
        start_server=not args.no_start_server,
        rtmp_host=args.rtmp_host,
        rtmp_port=args.rtmp_port,
        api_port=args.api_port,
        metrics_port=args.metrics_port,
        mediamtx_config=Path(args.mediamtx_config),
        mediamtx_log=Path(args.mediamtx_log),
    )
    try:
        return service.run()
    finally:
        service.stop()


if __name__ == '__main__':
    raise SystemExit(main())
