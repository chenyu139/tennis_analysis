from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


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


def resolve_model_paths(models_dir: str | None = None, player_model_path: str | None = None, ball_model_path: str | None = None, court_model_path: str | None = None) -> tuple[str, str, str]:
    base_dir = Path(models_dir or (ROOT_DIR / 'models')).resolve()
    if not base_dir.exists():
        raise FileNotFoundError(f'Model directory does not exist: {base_dir}')

    def ensure_in_models_dir(path_str: str, label: str) -> str:
        resolved = Path(path_str).resolve()
        try:
            resolved.relative_to(base_dir)
        except ValueError as exc:
            raise FileNotFoundError(f'{label} model must be stored under {base_dir}, got: {resolved}') from exc
        if not resolved.exists():
            raise FileNotFoundError(f'Missing {label} model: {resolved}')
        return str(resolved)

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
    player_path = next((candidate for candidate in player_candidates if candidate and Path(candidate).exists()), None)
    if player_path is None:
        raise FileNotFoundError(
            f'Player model is missing under {base_dir}. '
            'Expected one of: yolov8x.pt, player_yolo.pt, player_detector.pt, player_model.pt, yolov8l.pt, yolov8m.pt, yolov8n.pt'
        )

    ball_path = ball_model_path or str(base_dir / 'yolo5_last.pt')
    court_path = court_model_path or str(base_dir / 'keypoints_model.pth')
    return (
        ensure_in_models_dir(player_path, 'player'),
        ensure_in_models_dir(ball_path, 'ball'),
        ensure_in_models_dir(court_path, 'court'),
    )


def build_default_detectors(models_dir: str | None = None, player_model_path: str | None = None, ball_model_path: str | None = None, court_model_path: str | None = None, device: str | None = None):
    device = resolve_runtime_device(device=device, require_gpu=True)
    player_model, ball_model, court_model = resolve_model_paths(
        models_dir=models_dir,
        player_model_path=player_model_path,
        ball_model_path=ball_model_path,
        court_model_path=court_model_path,
    )

    from trackers.player_tracker import PlayerTracker
    from trackers.ball_tracker import BallTracker
    from court_line_detector import CourtLineDetector

    player_detector = PlayerTracker(model_path=player_model, device=device)
    ball_detector = BallTracker(model_path=ball_model, device=device)
    court_detector = CourtLineDetector(court_model, device=device)
    return player_detector, ball_detector, court_detector
