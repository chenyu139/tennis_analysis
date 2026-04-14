from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torchvision import models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="target", required=True)

    player_parser = subparsers.add_parser("player")
    add_detection_args(player_parser)

    ball_parser = subparsers.add_parser("ball")
    add_detection_args(ball_parser)

    court_parser = subparsers.add_parser("court")
    court_parser.add_argument("--weights", required=True)
    court_parser.add_argument("--output-dir", default="mobile_artifacts/court")
    court_parser.add_argument("--output-name", default="court_keypoints.onnx")
    court_parser.add_argument("--opset", type=int, default=13)
    court_parser.add_argument("--input-width", type=int, default=224)
    court_parser.add_argument("--input-height", type=int, default=224)
    court_parser.add_argument(
        "--mobile-target",
        choices=["cpu", "gpu", "nnapi"],
        default="cpu",
        help="Target runtime for the exported mobile asset. Current court export only supports CPU/GPU-friendly ONNX.",
    )

    return parser.parse_args()


def add_detection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--weights", required=True)
    parser.add_argument("--output-dir", default="mobile_artifacts")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--format", choices=["onnx", "tflite"], default="tflite")
    parser.add_argument("--half", action="store_true")
    parser.add_argument("--int8", action="store_true")
    parser.add_argument("--data")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--simplify", action="store_true")
    parser.add_argument(
        "--calibration-samples",
        type=int,
        default=16,
        help="Number of representative samples to use for INT8 calibration.",
    )
    parser.add_argument(
        "--mobile-target",
        choices=["cpu", "gpu", "nnapi"],
        default="cpu",
        help="Export profile for the mobile runtime. NNAPI/NPU requires TFLite INT8 plus representative data.",
    )


def write_metadata(path: Path, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))


def preferred_delegate_for_mobile_target(mobile_target: str) -> str:
    if mobile_target == "nnapi":
        return "NNAPI"
    if mobile_target == "gpu":
        return "GPU"
    return "CPU"


def copy_exported_model(exported: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / exported.name
    if exported.resolve() != destination.resolve():
        shutil.copy2(exported, destination)
    return destination


def is_wsl() -> bool:
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in release or "wsl" in release


def configure_tensorflow_runtime():
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("TF_NUM_INTRAOP_THREADS", "1")
    os.environ.setdefault("TF_NUM_INTEROP_THREADS", "1")
    import tensorflow as tf

    tf.config.threading.set_intra_op_parallelism_threads(1)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    return tf


def representative_dataset_from_npy(calibration_path: Path, sample_count: int):
    images = np.load(calibration_path, mmap_mode="r")
    limit = min(sample_count, int(images.shape[0]))

    def generator():
        for index in range(limit):
            image = np.asarray(images[index], dtype=np.float32)
            if float(image.max()) > 1.0:
                image = image / 255.0
            yield [image[None, ...]]

    return generator


def quantize_saved_model_to_int8(
    saved_model_dir: Path,
    output_path: Path,
    calibration_path: Path,
    sample_count: int,
) -> None:
    saved_model_pb = saved_model_dir / "saved_model.pb"
    if not saved_model_pb.exists():
        raise FileNotFoundError(f"Missing SavedModel protobuf: {saved_model_pb}")
    if not calibration_path.exists():
        raise FileNotFoundError(f"Missing calibration data: {calibration_path}")

    saved_model_size_mb = saved_model_pb.stat().st_size / (1024 * 1024)
    if is_wsl() and saved_model_size_mb > 256:
        raise RuntimeError(
            "SavedModel is too large for stable INT8 conversion inside WSL "
            f"({saved_model_size_mb:.1f} MB). Use a native Linux environment or a smaller model."
        )

    tf = configure_tensorflow_runtime()
    loaded = tf.saved_model.load(str(saved_model_dir))
    serving_fn = loaded.signatures["serving_default"]
    converter = tf.lite.TFLiteConverter.from_concrete_functions([serving_fn], loaded)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_dataset_from_npy(calibration_path, sample_count)
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    converter._experimental_new_quantizer = True

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(converter.convert())


def export_detection_model(args: argparse.Namespace, name: str) -> None:
    from ultralytics import YOLO

    if args.mobile_target == "nnapi":
        if args.format != "tflite":
            raise ValueError("NNAPI/NPU export requires --format tflite")
        if not args.int8:
            raise ValueError("NNAPI/NPU export requires --int8")
        if not args.data:
            raise ValueError("NNAPI/NPU export requires --data for representative calibration")

    model = YOLO(args.weights)
    is_tflite = args.format == "tflite"
    export_kwargs = {
        "format": args.format,
        "imgsz": args.imgsz,
        "device": args.device,
        "half": args.half,
        "int8": args.int8,
        "simplify": args.simplify,
    }
    if args.data:
        export_kwargs["data"] = args.data

    if args.mobile_target == "nnapi" and args.int8 and args.format == "tflite":
        saved_model_export_kwargs = {
            **export_kwargs,
            "format": "saved_model",
            "half": False,
            "int8": False,
        }
        exported_saved_model = Path(str(model.export(**saved_model_export_kwargs)))
        calibration_path = exported_saved_model / "tmp_tflite_int8_calibration_images.npy"
        exported_path = Path(args.output_dir) / name / f"{Path(args.weights).stem}_int8.tflite"
        quantize_saved_model_to_int8(
            saved_model_dir=exported_saved_model,
            output_path=exported_path,
            calibration_path=calibration_path,
            sample_count=args.calibration_samples,
        )
    else:
        exported = model.export(**export_kwargs)
        exported_path = copy_exported_model(Path(str(exported)), Path(args.output_dir) / name)

    write_metadata(
        exported_path.with_suffix(".json"),
        {
            "name": name,
            "source_weights": str(Path(args.weights).resolve()),
            "exported_model": str(exported_path.resolve()),
            "format": args.format,
            "input_shape": [1, args.imgsz, args.imgsz, 3] if is_tflite else [1, 3, args.imgsz, args.imgsz],
            "input_layout": "NHWC" if is_tflite else "NCHW",
            "input_range": [0.0, 1.0],
            "half": args.half,
            "int8": args.int8,
            "mobile_target": args.mobile_target,
            "preferred_delegate": preferred_delegate_for_mobile_target(args.mobile_target),
            "tracked_class_ids": [0],
        },
    )


def export_court_model(args: argparse.Namespace) -> None:
    if args.mobile_target == "nnapi":
        raise ValueError("Court export does not support NNAPI/NPU yet. Current implementation only emits ONNX.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model = models.resnet50(weights=None)
    model.fc = nn.Linear(model.fc.in_features, 28)
    state_dict = torch.load(args.weights, map_location="cpu")
    model.load_state_dict(state_dict)
    model.eval()

    dummy_input = torch.randn(1, 3, args.input_height, args.input_width)
    output_path = output_dir / args.output_name

    torch.onnx.export(
        model,
        dummy_input,
        str(output_path),
        input_names=["input"],
        output_names=["keypoints"],
        opset_version=args.opset,
        do_constant_folding=True,
    )

    write_metadata(
        output_path.with_suffix(".json"),
        {
            "name": "court",
            "source_weights": str(Path(args.weights).resolve()),
            "exported_model": str(output_path.resolve()),
            "format": "onnx",
            "input_shape": [1, 3, args.input_height, args.input_width],
            "input_layout": "NCHW",
            "normalize_mean": [0.485, 0.456, 0.406],
            "normalize_std": [0.229, 0.224, 0.225],
            "output_shape": [1, 28],
        },
    )


def main() -> None:
    args = parse_args()
    if args.target == "player":
        export_detection_model(args, "player")
    elif args.target == "ball":
        export_detection_model(args, "ball")
    else:
        export_court_model(args)


if __name__ == "__main__":
    main()
