from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--output-dir", default="mobile_artifacts/court_tflite")
    parser.add_argument("--copy-to-assets", action="store_true")
    parser.add_argument("--assets-dir", default="mobile/android/app/src/main/assets")
    return parser.parse_args()


def run_conversion(onnx_path: Path, output_dir: Path) -> Path:
    if shutil.which("onnx2tf") is None:
        raise RuntimeError("onnx2tf command not found. Install it before converting the court model.")

    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "onnx2tf",
            "-i",
            str(onnx_path),
            "-o",
            str(output_dir),
            "-coion",
        ],
        check=True,
    )

    candidates = sorted(output_dir.rglob("*.tflite"))
    if not candidates:
        raise FileNotFoundError("no tflite file produced by onnx2tf")
    return candidates[0]


def maybe_copy_to_assets(model_path: Path, assets_dir: Path) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(model_path, assets_dir / "court_keypoints.tflite")


def sync_metadata(onnx_path: Path, tflite_path: Path, output_dir: Path, assets_dir: Path | None) -> None:
    onnx_metadata_path = onnx_path.with_suffix(".json")
    if not onnx_metadata_path.exists():
        return

    metadata = json.loads(onnx_metadata_path.read_text())
    metadata["exported_model"] = str(tflite_path.resolve())
    metadata["format"] = "tflite"
    metadata["input_shape"] = [1, metadata["input_shape"][2], metadata["input_shape"][3], metadata["input_shape"][1]]
    metadata["input_layout"] = "NHWC"

    output_metadata_path = output_dir / "court_keypoints.json"
    output_metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

    if assets_dir is not None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_metadata_path, assets_dir / "court_keypoints.json")


def main() -> None:
    args = parse_args()
    onnx_path = Path(args.onnx)
    output_dir = Path(args.output_dir)

    tflite_path = run_conversion(onnx_path, output_dir)
    assets_dir = Path(args.assets_dir) if args.copy_to_assets else None
    sync_metadata(onnx_path, tflite_path, output_dir, assets_dir)
    if args.copy_to_assets:
        maybe_copy_to_assets(tflite_path, assets_dir)
    print(tflite_path.resolve())


if __name__ == "__main__":
    main()
