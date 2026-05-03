"""Build YOLO-format ball detection dataset from auto-annotated sichuan frames.

Creates:
  training/sichuan_ball_merged/ - Merged ball detection dataset
  (existing Roboflow + sichuan auto-labeled)

Player detection uses the pre-trained COCO YOLOv8x model directly (class 0 = person),
so no custom player dataset is needed.

Usage:
  python tools/data/build_datasets.py
"""
from __future__ import annotations

import random
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SICHUAN_FRAMES = PROJECT_ROOT / "training" / "sichuan_frames"
ROBOFLOW_DIR = PROJECT_ROOT / "training" / "tennis-ball-detection-6" / "tennis-ball-detection-6"
BALL_OUTPUT = PROJECT_ROOT / "training" / "sichuan_ball_merged"
VAL_RATIO = 0.2
SEED = 42


def build_ball_dataset():
    """Merge Roboflow + sichuan auto-labeled ball data into YOLO dataset."""
    print("[ball] Building merged ball dataset...")

    for split in ("train", "val"):
        (BALL_OUTPUT / split / "images").mkdir(parents=True, exist_ok=True)
        (BALL_OUTPUT / split / "labels").mkdir(parents=True, exist_ok=True)

    # Copy Roboflow data (already split)
    for split in ("train", "valid"):
        src_img = ROBOFLOW_DIR / split / "images"
        src_lbl = ROBOFLOW_DIR / split / "labels"
        dst_split = "val" if split == "valid" else "train"
        if src_img.exists():
            for f in src_img.glob("*.jpg"):
                shutil.copy2(f, BALL_OUTPUT / dst_split / "images" / f.name)
        if src_lbl.exists():
            for f in src_lbl.glob("*.txt"):
                shutil.copy2(f, BALL_OUTPUT / dst_split / "labels" / f.name)

    # Add sichuan auto-labeled frames
    labels_dir = SICHUAN_FRAMES / "labels_ball"
    if not labels_dir.exists():
        print(f"[ball] WARNING: {labels_dir} not found, skipping sichuan frames")
        return

    frames = sorted(SICHUAN_FRAMES.glob("*.jpg"))
    random.seed(SEED)
    random.shuffle(frames)
    val_count = int(len(frames) * VAL_RATIO)

    for i, img_path in enumerate(frames):
        label_path = labels_dir / (img_path.stem + ".txt")
        split = "val" if i < val_count else "train"
        shutil.copy2(img_path, BALL_OUTPUT / split / "images" / img_path.name)
        if label_path.exists():
            shutil.copy2(label_path, BALL_OUTPUT / split / "labels" / label_path.name)
        else:
            # Create empty label file for frames with no ball
            (BALL_OUTPUT / split / "labels" / (img_path.stem + ".txt")).write_text("")

    # Write data.yaml
    train_count = len(list((BALL_OUTPUT / "train" / "images").glob("*.jpg")))
    val_count = len(list((BALL_OUTPUT / "val" / "images").glob("*.jpg")))
    data_yaml = f"""names:
- tennis ball
nc: 1
train: {BALL_OUTPUT}/train/images
val: {BALL_OUTPUT}/val/images
"""
    (BALL_OUTPUT / "data.yaml").write_text(data_yaml)
    print(f"[ball] Dataset ready: {train_count} train, {val_count} val images")


def main():
    build_ball_dataset()
    print("[done] Ball dataset built. Player detection uses COCO YOLOv8x directly.")


if __name__ == "__main__":
    main()
