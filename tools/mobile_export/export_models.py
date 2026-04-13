from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

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


def write_metadata(path: Path, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))


def copy_exported_model(exported: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / exported.name
    if exported.resolve() != destination.resolve():
        shutil.copy2(exported, destination)
    return destination


def export_detection_model(args: argparse.Namespace, name: str) -> None:
    from ultralytics import YOLO

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
            "tracked_class_ids": [0],
        },
    )


def export_court_model(args: argparse.Namespace) -> None:
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
