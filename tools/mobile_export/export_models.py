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
    player_parser.set_defaults(output_name="player_detector")

    ball_parser = subparsers.add_parser("ball")
    add_detection_args(ball_parser)
    ball_parser.set_defaults(output_name="ball_detector")

    court_parser = subparsers.add_parser("court")
    court_parser.add_argument("--weights", required=True)
    court_parser.add_argument("--output-dir", default="mobile_artifacts/court")
    court_parser.add_argument("--output-name", default="court_keypoints")
    court_parser.add_argument("--format", choices=["onnx", "coreml"], default="coreml")
    court_parser.add_argument("--opset", type=int, default=13)
    court_parser.add_argument("--input-width", type=int, default=224)
    court_parser.add_argument("--input-height", type=int, default=224)
    court_parser.add_argument(
        "--mobile-target",
        choices=["cpu", "gpu", "nnapi", "ane"],
        default="ane",
        help="Target runtime for the exported mobile asset.",
    )

    return parser.parse_args()


def add_detection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--weights", required=True)
    parser.add_argument("--output-dir", default="mobile_artifacts")
    parser.add_argument("--output-name")
    parser.add_argument(
        "--saved-model-dir",
        help="Reuse an existing SavedModel export instead of invoking Ultralytics export again.",
    )
    parser.add_argument(
        "--calibration-data",
        help="Representative dataset .npy file to use for INT8 calibration.",
    )
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--format", choices=["onnx", "tflite", "coreml"], default="tflite")
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
        choices=["cpu", "gpu", "nnapi", "ane"],
        default="cpu",
        help="Export profile for the mobile runtime. NNAPI requires TFLite INT8 while ANE targets Core ML.",
    )


def write_metadata(path: Path, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))


def preferred_delegate_for_mobile_target(mobile_target: str) -> str:
    if mobile_target == "nnapi":
        return "NNAPI"
    if mobile_target == "ane":
        return "ANE"
    if mobile_target == "gpu":
        return "GPU"
    return "CPU"


def ensure_coremltools():
    try:
        import coremltools as ct
    except ImportError as exc:
        raise RuntimeError(
            "coremltools is required for Core ML export. Install it on macOS before running --format coreml."
        ) from exc
    return ct


def coreml_compute_unit_for_mobile_target(ct, mobile_target: str):
    if mobile_target == "ane":
        return ct.ComputeUnit.ALL
    if mobile_target == "gpu":
        return ct.ComputeUnit.CPU_AND_GPU
    return ct.ComputeUnit.CPU_ONLY


def copy_exported_model(exported: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / exported.name
    if exported.resolve() != destination.resolve():
        shutil.copy2(exported, destination)
    return destination


def normalize_exported_model_path(exported: Path, output_dir: Path, output_name: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "".join(exported.suffixes)
    destination = output_dir / f"{output_name}{suffix}"
    if exported.is_dir():
        if exported.resolve() != destination.resolve():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(exported, destination)
        return destination
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


def infer_saved_model_dir(weights: Path) -> Path | None:
    candidate = weights.with_name(f"{weights.stem}_saved_model")
    return candidate if candidate.exists() else None


def infer_calibration_path(saved_model_dir: Path | None) -> Path | None:
    if saved_model_dir is None:
        return None
    candidate = saved_model_dir / "tmp_tflite_int8_calibration_images.npy"
    return candidate if candidate.exists() else None


def find_existing_int8_tflite(search_dirs: list[Path], stem: str) -> Path | None:
    exact_names = [
        f"{stem}_int8.tflite",
        f"{stem}_int8_probe.tflite",
        f"{stem}_int8_probe2.tflite",
        f"{stem}_int8_probe_old.tflite",
    ]
    for directory in search_dirs:
        if not directory.exists():
            continue
        for name in exact_names:
            candidate = directory / name
            if candidate.exists():
                return candidate
        candidates = sorted(directory.glob(f"{stem}_int8*.tflite"))
        if candidates:
            return candidates[0]
    return None


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
    if args.mobile_target == "ane" and args.format != "coreml":
        raise ValueError("ANE export requires --format coreml")

    output_dir = Path(args.output_dir) / name
    weights_path = Path(args.weights)
    output_name = args.output_name or f"{name}_detector"
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
        saved_model_dir = Path(args.saved_model_dir) if args.saved_model_dir else infer_saved_model_dir(weights_path)
        calibration_path = Path(args.calibration_data) if args.calibration_data else infer_calibration_path(saved_model_dir)
        exported_path = output_dir / f"{weights_path.stem}_int8.tflite"

        if saved_model_dir is None or calibration_path is None:
            model = YOLO(args.weights)
            saved_model_export_kwargs = {
                **export_kwargs,
                "format": "saved_model",
                "half": False,
                "int8": False,
            }
            saved_model_dir = Path(str(model.export(**saved_model_export_kwargs)))
            calibration_path = saved_model_dir / "tmp_tflite_int8_calibration_images.npy"

        saved_model_pb = saved_model_dir / "saved_model.pb"
        saved_model_size_mb = saved_model_pb.stat().st_size / (1024 * 1024) if saved_model_pb.exists() else 0.0
        if is_wsl() and saved_model_size_mb > 256:
            existing_int8 = find_existing_int8_tflite(
                search_dirs=[output_dir, saved_model_dir, weights_path.parent],
                stem=weights_path.stem,
            )
            if existing_int8 is None:
                raise RuntimeError(
                    "SavedModel is too large for stable INT8 conversion inside WSL "
                    f"({saved_model_size_mb:.1f} MB), and no reusable INT8 TFLite artifact was found."
                )
            exported_path = normalize_exported_model_path(existing_int8, output_dir, output_name)
        else:
            raw_output_path = output_dir / f"{weights_path.stem}_int8.tflite"
            quantize_saved_model_to_int8(
                saved_model_dir=saved_model_dir,
                output_path=raw_output_path,
                calibration_path=calibration_path,
                sample_count=args.calibration_samples,
            )
            exported_path = normalize_exported_model_path(raw_output_path, output_dir, output_name)
    else:
        model = YOLO(args.weights)
        exported = model.export(**export_kwargs)
        exported_raw = Path(str(exported))
        exported_path = normalize_exported_model_path(exported_raw, output_dir, output_name)

    # Load model to get class metadata
    from ultralytics import YOLO as _YOLO
    _model = _YOLO(args.weights)
    _num_classes = len(_model.names)
    _class_names = list(_model.names.values())
    # YOLOv8/v11 models don't have objectness scores; YOLOv5 models do
    _has_objectness = "yolo5" in Path(args.weights).stem.lower()
    del _model

    write_metadata(
        output_dir / f"{output_name}.json",
        {
            "name": name,
            "source_weights": str(Path(args.weights).resolve()),
            "exported_model": str(exported_path.resolve()),
            "format": args.format,
            "input_shape": [1, args.imgsz, args.imgsz, 3] if args.format in {"tflite", "coreml"} else [1, 3, args.imgsz, args.imgsz],
            "input_layout": "NHWC" if args.format in {"tflite", "coreml"} else "NCHW",
            "input_range": [0.0, 1.0],
            "half": args.half,
            "int8": args.int8,
            "mobile_target": args.mobile_target,
            "preferred_delegate": preferred_delegate_for_mobile_target(args.mobile_target),
            "tracked_class_ids": [0],
            "num_classes": _num_classes,
            "has_objectness": _has_objectness,
            "class_names": _class_names,
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

    if args.format == "onnx":
        output_path = output_dir / f"{args.output_name}.onnx"
        torch.onnx.export(
            model,
            dummy_input,
            str(output_path),
            input_names=["input"],
            output_names=["keypoints"],
            opset_version=args.opset,
            do_constant_folding=True,
        )
    else:
        ct = ensure_coremltools()
        traced = torch.jit.trace(model, dummy_input)
        output_path = output_dir / f"{args.output_name}.mlpackage"
        mlmodel = ct.convert(
            traced,
            convert_to="mlprogram",
            inputs=[
                ct.TensorType(
                    name="input",
                    shape=dummy_input.shape,
                    dtype=np.float32,
                )
            ],
            outputs=[ct.TensorType(name="keypoints")],
            compute_units=coreml_compute_unit_for_mobile_target(ct, args.mobile_target),
        )
        mlmodel.save(str(output_path))

    write_metadata(
        output_dir / f"{args.output_name}.json",
        {
            "name": "court",
            "source_weights": str(Path(args.weights).resolve()),
            "exported_model": str(output_path.resolve()),
            "format": args.format,
            "input_shape": [1, 3, args.input_height, args.input_width],
            "input_layout": "NCHW",
            "normalize_mean": [0.485, 0.456, 0.406],
            "normalize_std": [0.229, 0.224, 0.225],
            "output_shape": [1, 28],
            "mobile_target": args.mobile_target,
            "preferred_delegate": preferred_delegate_for_mobile_target(args.mobile_target),
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
