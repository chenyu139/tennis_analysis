from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player-model")
    parser.add_argument("--ball-model")
    parser.add_argument("--court-model")
    parser.add_argument("--player-meta")
    parser.add_argument("--ball-meta")
    parser.add_argument("--court-meta")
    parser.add_argument(
        "--assets-dir",
        default="mobile/android/app/src/main/assets",
    )
    return parser.parse_args()


def copy_if_present(source: str | None, target_dir: Path, target_name: str) -> None:
    if not source:
        return
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_dir / target_name)


def main() -> None:
    args = parse_args()
    assets_dir = Path(args.assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    player_name = f"player_detector{Path(args.player_model).suffix}" if args.player_model else ""
    ball_name = f"ball_detector{Path(args.ball_model).suffix}" if args.ball_model else ""
    court_name = f"court_keypoints{Path(args.court_model).suffix}" if args.court_model else ""

    copy_if_present(args.player_model, assets_dir, player_name)
    copy_if_present(args.ball_model, assets_dir, ball_name)
    copy_if_present(args.court_model, assets_dir, court_name)

    copy_if_present(args.player_meta, assets_dir, "player_detector.json")
    copy_if_present(args.ball_meta, assets_dir, "ball_detector.json")
    copy_if_present(args.court_meta, assets_dir, "court_keypoints.json")


if __name__ == "__main__":
    main()
