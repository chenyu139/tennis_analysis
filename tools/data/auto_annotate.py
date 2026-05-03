"""Auto-annotate extracted frames for ball detection.

Produces YOLO-format labels:
  training/sichuan_frames/labels_ball/<name>.txt   (class 0 = tennis ball)

Player detection uses the pre-trained COCO YOLOv8x model directly (class 0 = person),
so no custom player annotation is needed.

Usage:
  python tools/data/auto_annotate.py \
    --frames-dir training/sichuan_frames \
    --ball-model models/yolo5_last.pt \
    --device cuda:0
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def annotate_ball(
    frames_dir: Path,
    output_dir: Path,
    model_path: str,
    conf: float = 0.15,
    device: str = "cuda:0",
) -> int:
    from ultralytics import YOLO

    model = YOLO(model_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(frames_dir.glob("*.jpg"))
    count = 0
    for i, img_path in enumerate(images):
        results = model.predict(str(img_path), conf=conf, verbose=False, max_det=10, device=device)
        lines: list[str] = []
        if results and len(results[0].boxes) > 0:
            boxes = results[0].boxes
            xywhn_all = boxes.xywhn.cpu().numpy()
            for row in xywhn_all:
                line = f"0 {row[0]:.6f} {row[1]:.6f} {row[2]:.6f} {row[3]:.6f}"
                lines.append(line)

        label_path = output_dir / (img_path.stem + ".txt")
        label_path.write_text("\n".join(lines) + "\n" if lines else "")
        if lines:
            count += 1
        del results

        if (i + 1) % 100 == 0:
            print(f"[ball] {i + 1}/{len(images)} frames processed, {count} with detections")

    print(f"[ball] Done: {count}/{len(images)} frames have ball annotations")
    return count


def _resolve_device(device: str) -> str:
    import torch
    if device.startswith("cuda") and not torch.cuda.is_available():
        print(f"[warn] CUDA not available, falling back to CPU")
        return "cpu"
    return device


def main():
    parser = argparse.ArgumentParser(description="Auto-annotate frames for ball detection.")
    parser.add_argument("--frames-dir", default="training/sichuan_frames", help="Directory with extracted frames.")
    parser.add_argument("--ball-model", default="models/yolo5_last.pt", help="Ball detection model path.")
    parser.add_argument("--device", default="cuda:0", help="Inference device.")
    args = parser.parse_args()

    device = _resolve_device(args.device)
    frames_dir = Path(args.frames_dir)

    print(f"[ball] Annotating with {args.ball_model}...")
    annotate_ball(frames_dir, frames_dir / "labels_ball", args.ball_model, device=device)

    print("[done] Auto-annotation complete.")


if __name__ == "__main__":
    main()
