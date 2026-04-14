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
        default="ios/TennisAnalysisIOS/Resources/Models",
        help="Directory copied into the Xcode app bundle resources.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing model assets in the destination before copying new ones.",
    )
    return parser.parse_args()


def copy_if_present(source: str | None, target_dir: Path, target_name: str) -> None:
    if not source:
        return
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    destination = target_dir / target_name
    if source_path.is_dir():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source_path, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def clear_known_assets(target_dir: Path) -> None:
    for name in [
        "player_detector.mlpackage",
        "ball_detector.mlpackage",
        "court_keypoints.mlpackage",
        "player_detector.mlmodelc",
        "ball_detector.mlmodelc",
        "court_keypoints.mlmodelc",
        "player_detector.json",
        "ball_detector.json",
        "court_keypoints.json",
    ]:
        path = target_dir / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()


def main() -> None:
    args = parse_args()
    assets_dir = Path(args.assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    if args.clean:
        clear_known_assets(assets_dir)

    copy_if_present(args.player_model, assets_dir, "player_detector" + "".join(Path(args.player_model).suffixes) if args.player_model else "")
    copy_if_present(args.ball_model, assets_dir, "ball_detector" + "".join(Path(args.ball_model).suffixes) if args.ball_model else "")
    copy_if_present(args.court_model, assets_dir, "court_keypoints" + "".join(Path(args.court_model).suffixes) if args.court_model else "")

    copy_if_present(args.player_meta, assets_dir, "player_detector.json")
    copy_if_present(args.ball_meta, assets_dir, "ball_detector.json")
    copy_if_present(args.court_meta, assets_dir, "court_keypoints.json")


if __name__ == "__main__":
    main()
