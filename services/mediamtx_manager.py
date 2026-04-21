from __future__ import annotations

import os
import socket
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
MEDIAMTX_VERSION = '1.17.1'
MEDIAMTX_DIR = ROOT_DIR / 'tools' / 'mediamtx'
MEDIAMTX_BINARY = MEDIAMTX_DIR / 'mediamtx'
MEDIAMTX_ARCHIVE = MEDIAMTX_DIR / f'mediamtx_v{MEDIAMTX_VERSION}_linux_amd64.tar.gz'
MEDIAMTX_DOWNLOAD_URL = (
    f'https://github.com/bluenviron/mediamtx/releases/download/v{MEDIAMTX_VERSION}/'
    f'mediamtx_v{MEDIAMTX_VERSION}_linux_amd64.tar.gz'
)

DEFAULT_CONFIG_TEMPLATE = """logLevel: info
api: true
apiAddress: 127.0.0.1:{api_port}
metrics: true
metricsAddress: 127.0.0.1:{metrics_port}
pprof: false
rtsp: false
hls: false
webrtc: false
srt: false
rtmp: true
rtmpAddress: 127.0.0.1:{rtmp_port}
paths:
  live/source:
    source: publisher
  live/analysis:
    source: publisher
"""


def ensure_mediamtx_binary() -> Path:
    MEDIAMTX_DIR.mkdir(parents=True, exist_ok=True)
    if MEDIAMTX_BINARY.exists():
        MEDIAMTX_BINARY.chmod(MEDIAMTX_BINARY.stat().st_mode | 0o111)
        return MEDIAMTX_BINARY

    urllib.request.urlretrieve(MEDIAMTX_DOWNLOAD_URL, MEDIAMTX_ARCHIVE)
    with tarfile.open(MEDIAMTX_ARCHIVE, 'r:gz') as archive:
        archive.extractall(MEDIAMTX_DIR)
    MEDIAMTX_BINARY.chmod(MEDIAMTX_BINARY.stat().st_mode | 0o111)
    return MEDIAMTX_BINARY


def write_default_config(config_path: Path, rtmp_port: int = 1935, api_port: int = 9997, metrics_port: int = 9998) -> Path:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        DEFAULT_CONFIG_TEMPLATE.format(
            rtmp_port=int(rtmp_port),
            api_port=int(api_port),
            metrics_port=int(metrics_port),
        ),
        encoding='utf-8',
    )
    return config_path


def is_tcp_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, int(port))) == 0


def wait_for_tcp_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_tcp_port_open(host, port):
            return
        time.sleep(0.1)
    raise TimeoutError(f'TCP port did not become ready: {host}:{port}')


def start_mediamtx(config_path: Path, log_path: Path | None = None) -> subprocess.Popen:
    binary_path = ensure_mediamtx_binary()
    stdout_handle = open(log_path, 'a', encoding='utf-8') if log_path is not None else subprocess.DEVNULL
    process = subprocess.Popen(
        [str(binary_path), str(config_path)],
        cwd=str(MEDIAMTX_DIR),
        stdout=stdout_handle,
        stderr=subprocess.STDOUT,
        env={**os.environ, 'MTX_CONFIG': str(config_path)},
    )
    return process
