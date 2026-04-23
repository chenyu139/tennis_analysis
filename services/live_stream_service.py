from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

DEFAULT_RTDETR_BALL_MODEL = ROOT_DIR / 'runtime' / 'runs' / 'rtdetr_tennis_ball_v1' / 'weights' / 'best.pt'


def resolve_runtime_device(device: str | None = None, require_gpu: bool = True) -> str:
    resolved = device or 'cuda:0'
    if resolved == 'cpu' and require_gpu:
        raise RuntimeError('GPU is required, but device=cpu was requested.')
    try:
        import torch
    except Exception as exc:
        raise RuntimeError(f'PyTorch is required for GPU inference: {exc}') from exc
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is not available, but GPU mode is required.')
    if not resolved.startswith('cuda'):
        raise RuntimeError(f'GPU device is required, got: {resolved}')
    return resolved


def _first_existing_path(candidates: list[str | os.PathLike[str] | None]) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        resolved = Path(candidate).expanduser().resolve()
        if resolved.exists():
            return str(resolved)
    return None


def _ensure_existing_path(path_str: str, label: str) -> str:
    resolved = Path(path_str).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f'Missing {label} model: {resolved}')
    return str(resolved)


def resolve_model_paths(
    models_dir: str | None = None,
    player_model_path: str | None = None,
    ball_model_path: str | None = None,
    court_model_path: str | None = None,
) -> tuple[str, str, str]:
    base_dir = Path(models_dir or (ROOT_DIR / 'models')).resolve()
    if not base_dir.exists():
        raise FileNotFoundError(f'Model directory does not exist: {base_dir}')

    player_candidates = [
        player_model_path,
        str(base_dir / 'yolov8x.pt'),
        str(base_dir / 'player_yolo.pt'),
        str(base_dir / 'player_detector.pt'),
        str(base_dir / 'player_model.pt'),
        str(base_dir / 'yolov8l.pt'),
        str(base_dir / 'yolov8m.pt'),
        str(base_dir / 'yolov8n.pt'),
    ]
    player_path = _first_existing_path(player_candidates)
    if player_path is None:
        raise FileNotFoundError(
            f'Player model is missing under {base_dir}. '
            'Expected one of: yolov8x.pt, player_yolo.pt, player_detector.pt, player_model.pt, yolov8l.pt, yolov8m.pt, yolov8n.pt'
        )

    ball_path = _first_existing_path([
        ball_model_path,
        str(base_dir / 'yolo5_last.pt'),
        str(base_dir / 'ball_detector.pt'),
    ])
    if ball_path is None:
        raise FileNotFoundError(
            f'Ball model is missing under {base_dir}. '
            'Expected one of: yolo5_last.pt, ball_detector.pt'
        )
    court_path = _first_existing_path([
        court_model_path,
        str(base_dir / 'keypoints_model.pth'),
    ])
    if court_path is None:
        raise FileNotFoundError(
            f'Court model is missing under {base_dir}. '
            'Expected keypoints_model.pth'
        )
    return (
        _ensure_existing_path(player_path, 'player'),
        _ensure_existing_path(ball_path, 'ball'),
        _ensure_existing_path(court_path, 'court'),
    )


def resolve_ball_detector_options(
    models_dir: str | None = None,
    yolo_ball_model_path: str | None = None,
    rtdetr_ball_model_path: str | None = None,
) -> dict[str, dict[str, str]]:
    base_dir = Path(models_dir or (ROOT_DIR / 'models')).resolve()
    if not base_dir.exists():
        raise FileNotFoundError(f'Model directory does not exist: {base_dir}')

    options: dict[str, dict[str, str]] = {}
    yolo_path = _first_existing_path([
        yolo_ball_model_path,
        str(base_dir / 'yolo5_last.pt'),
        str(base_dir / 'ball_detector.pt'),
    ])
    if yolo_path is not None:
        options['yolo'] = {
            'key': 'yolo',
            'label': 'YOLO',
            'detector_type': 'yolo',
            'model_path': _ensure_existing_path(yolo_path, 'ball'),
        }

    rtdetr_path = _first_existing_path([
        rtdetr_ball_model_path,
        str(base_dir / 'rtdetr_tennis_ball_v1.pt'),
        str(base_dir / 'rtdetr_ball.pt'),
        str(DEFAULT_RTDETR_BALL_MODEL),
    ])
    if rtdetr_path is not None:
        options['rtdetr'] = {
            'key': 'rtdetr',
            'label': 'RT-DETR',
            'detector_type': 'rtdetr',
            'model_path': _ensure_existing_path(rtdetr_path, 'ball'),
        }

    if not options:
        raise FileNotFoundError(
            f'No supported ball detector models found under {base_dir} or runtime outputs.'
        )
    return options


def build_ball_detector(detector_option: dict[str, str], device: str | None = None):
    from trackers.ball_tracker import BallTracker

    return BallTracker(
        model_path=detector_option['model_path'],
        device=device,
        detector_type=detector_option['detector_type'],
    )


def build_default_detectors(
    models_dir: str | None = None,
    player_model_path: str | None = None,
    ball_model_path: str | None = None,
    court_model_path: str | None = None,
    device: str | None = None,
    ball_detector_type: str = 'yolo',
    rtdetr_ball_model_path: str | None = None,
):
    device = resolve_runtime_device(device=device, require_gpu=True)
    player_model, ball_model, court_model = resolve_model_paths(
        models_dir=models_dir,
        player_model_path=player_model_path,
        ball_model_path=ball_model_path,
        court_model_path=court_model_path,
    )
    ball_detector_options = resolve_ball_detector_options(
        models_dir=models_dir,
        yolo_ball_model_path=ball_model,
        rtdetr_ball_model_path=rtdetr_ball_model_path,
    )
    if ball_detector_type not in ball_detector_options:
        available = ', '.join(ball_detector_options.keys())
        raise FileNotFoundError(f'Unsupported ball detector "{ball_detector_type}". Available: {available}')

    from trackers.player_tracker import PlayerTracker
    from court_line_detector import CourtLineDetector

    player_detector = PlayerTracker(model_path=player_model, device=device)
    ball_detector = build_ball_detector(ball_detector_options[ball_detector_type], device=device)
    court_detector = CourtLineDetector(court_model, device=device)
    return player_detector, ball_detector, court_detector, ball_detector_options
