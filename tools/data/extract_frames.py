"""Extract frames from a tennis video for annotation.

Multi-strategy sampling:
  - scene: detect scene changes, sample around each cut
  - uniform: sample at fixed time intervals
  - hard: run existing ball detector, over-sample low-confidence and missed frames

Usage:
  python tools/data/extract_frames.py \
    --input input_videos/sichuan_open.mp4 \
    --output training/sichuan_frames \
    --strategies scene uniform hard \
    --interval-seconds 3 \
    --hard-model models/yolo5_last.pt \
    --max-frames 1200
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np


def extract_scene_change_frames(
    video_path: str,
    output_dir: Path,
    threshold: float = 30.0,
    frames_per_cut: int = 3,
) -> list[str]:
    """Detect scene changes via histogram difference and sample frames around each."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    saved: list[str] = []
    frame_idx = 0
    prev_hist = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        cv2.normalize(hist, hist)

        if prev_hist is not None:
            diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
            if diff < 1.0 - threshold / 100.0:
                for offset in range(frames_per_cut):
                    target = max(frame_idx - 1 + offset, 0)
                    name = f"scene_{target:06d}.jpg"
                    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
                    _, f = cap.read()
                    if f is not None:
                        cv2.imwrite(str(output_dir / name), f)
                        saved.append(name)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx + 1)

        prev_hist = hist
        frame_idx += 1

    cap.release()
    return saved


def extract_uniform_frames(
    video_path: str,
    output_dir: Path,
    interval_seconds: float = 3.0,
) -> list[str]:
    """Sample frames at fixed time intervals."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(int(fps * interval_seconds), 1)

    saved: list[str] = []
    for idx in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            break
        name = f"uniform_{idx:06d}.jpg"
        cv2.imwrite(str(output_dir / name), frame)
        saved.append(name)

    cap.release()
    return saved


def extract_hard_negative_frames(
    video_path: str,
    output_dir: Path,
    model_path: str | None = None,
    device: str = "cuda:0",
    high_conf_ratio: float = 0.2,
    low_conf_ratio: float = 0.4,
    miss_ratio: float = 0.4,
    sample_every_n: int = 5,
) -> list[str]:
    """Run ball detector, over-sample low-confidence and missed-detection frames.

    Only stores frame indices in memory (not pixel data), then re-reads
    selected frames from disk in a second pass to avoid OOM on long videos.
    """
    if model_path is None:
        print("[hard] No model path provided, skipping hard-negative extraction.")
        return []

    from ultralytics import YOLO

    model = YOLO(model_path)
    if device and device.startswith("cuda"):
        try:
            model.to(device)
        except Exception:
            pass

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # Store only frame indices to avoid OOM
    buckets: dict[str, list[int]] = {
        "high": [],
        "low": [],
        "miss": [],
    }

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every_n != 0:
            frame_idx += 1
            continue

        results = model.predict(frame, conf=0.15, verbose=False, max_det=3)
        if not results or len(results[0].boxes) == 0:
            buckets["miss"].append(frame_idx)
        else:
            max_conf = float(results[0].boxes.conf.max())
            if max_conf >= 0.6:
                buckets["high"].append(frame_idx)
            elif max_conf >= 0.22:
                buckets["low"].append(frame_idx)
            else:
                buckets["miss"].append(frame_idx)
        frame_idx += 1
        del results

        if frame_idx % 5000 == 0:
            print(f"[hard] Progress: {frame_idx}/{total} frames processed")

    cap.release()

    total_bucket = sum(len(v) for v in buckets.values())
    if total_bucket == 0:
        return []

    target_total = min(total_bucket, 400)
    counts = {
        "high": int(target_total * high_conf_ratio),
        "low": int(target_total * low_conf_ratio),
        "miss": int(target_total * miss_ratio),
    }

    # Select frame indices to save
    selected_indices: list[tuple[str, int]] = []
    for bucket_name, indices in buckets.items():
        n = min(counts[bucket_name], len(indices))
        if n == 0:
            continue
        step = max(len(indices) // n, 1)
        for idx in indices[::step][:n]:
            selected_indices.append((bucket_name, idx))

    # Second pass: re-read only selected frames from disk
    cap = cv2.VideoCapture(video_path)
    saved: list[str] = []
    selected_set = {idx for _, idx in selected_indices}
    # Sort by frame index for sequential reads
    idx_to_name = {idx: name for name, idx in selected_indices}

    current = 0
    for target_idx in sorted(selected_set):
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
        ret, frame = cap.read()
        if not ret:
            continue
        bucket_name = idx_to_name[target_idx].split("_")[0]
        name = f"hard_{bucket_name}_{target_idx:06d}.jpg"
        cv2.imwrite(str(output_dir / name), frame)
        saved.append(name)

    cap.release()

    print(f"[hard] Bucket sizes: high={len(buckets['high'])}, low={len(buckets['low'])}, miss={len(buckets['miss'])}")
    print(f"[hard] Sampled: high={min(counts['high'], len(buckets['high']))}, "
          f"low={min(counts['low'], len(buckets['low']))}, "
          f"miss={min(counts['miss'], len(buckets['miss']))}")
    return saved


def main():
    parser = argparse.ArgumentParser(description="Extract frames from tennis video for annotation.")
    parser.add_argument("--input", required=True, help="Path to input video.")
    parser.add_argument("--output", required=True, help="Output directory for extracted frames.")
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=["scene", "uniform", "hard"],
        choices=["scene", "uniform", "hard"],
        help="Sampling strategies to use.",
    )
    parser.add_argument("--interval-seconds", type=float, default=3.0, help="Interval for uniform sampling.")
    parser.add_argument("--hard-model", default=None, help="Ball detector model path for hard-negative mining.")
    parser.add_argument("--device", default="cuda:0", help="Device for hard-negative model inference.")
    parser.add_argument("--max-frames", type=int, default=1200, help="Maximum total frames to extract.")
    parser.add_argument("--scene-threshold", type=float, default=30.0, help="Scene change sensitivity (0-100).")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_saved: list[str] = []

    if "scene" in args.strategies:
        print(f"[scene] Extracting scene-change frames (threshold={args.scene_threshold})...")
        saved = extract_scene_change_frames(args.input, output_dir, threshold=args.scene_threshold)
        print(f"[scene] Saved {len(saved)} frames.")
        all_saved.extend(saved)

    if "uniform" in args.strategies:
        print(f"[uniform] Extracting frames every {args.interval_seconds}s...")
        saved = extract_uniform_frames(args.input, output_dir, interval_seconds=args.interval_seconds)
        print(f"[uniform] Saved {len(saved)} frames.")
        all_saved.extend(saved)

    if "hard" in args.strategies:
        print(f"[hard] Extracting hard-negative frames (model={args.hard_model})...")
        saved = extract_hard_negative_frames(
            args.input, output_dir, model_path=args.hard_model, device=args.device,
        )
        print(f"[hard] Saved {len(saved)} frames.")
        all_saved.extend(saved)

    # Deduplicate by frame index
    seen_indices: set[str] = set()
    unique_saved: list[str] = []
    for name in all_saved:
        parts = name.split("_")
        idx_key = parts[-1] if len(parts) >= 2 else name
        if idx_key not in seen_indices:
            seen_indices.add(idx_key)
            unique_saved.append(name)

    # Trim to max_frames
    if len(unique_saved) > args.max_frames:
        step = max(len(unique_saved) // args.max_frames, 1)
        unique_saved = unique_saved[::step][: args.max_frames]

    # Remove files not in the final set
    final_set = set(unique_saved)
    for f in output_dir.iterdir():
        if f.is_file() and f.name not in final_set:
            f.unlink()

    print(f"\nTotal unique frames saved: {len(unique_saved)} in {output_dir}")


if __name__ == "__main__":
    main()
