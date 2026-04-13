from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
import torch.nn as nn
from PIL import Image
from torchvision import models
from torchvision.transforms import functional as TF


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="target", required=True)

    player_parser = subparsers.add_parser("player")
    add_detection_validation_args(player_parser)

    ball_parser = subparsers.add_parser("ball")
    add_detection_validation_args(ball_parser)

    court_parser = subparsers.add_parser("court")
    court_parser.add_argument("--weights", required=True)
    court_parser.add_argument("--exported", required=True)
    court_parser.add_argument("--images", required=True)
    court_parser.add_argument("--input-width", type=int, default=224)
    court_parser.add_argument("--input-height", type=int, default=224)

    return parser.parse_args()


def add_detection_validation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--weights", required=True)
    parser.add_argument("--exported", required=True)
    parser.add_argument("--images", required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.15)
    parser.add_argument("--iou", type=float, default=0.45)


def list_images(path_like: str) -> list[Path]:
    path = Path(path_like)
    if path.is_file():
        return [path]
    patterns = ["*.jpg", "*.jpeg", "*.png", "*.bmp"]
    images: list[Path] = []
    for pattern in patterns:
        images.extend(sorted(path.glob(pattern)))
    if not images:
        raise FileNotFoundError(f"no images found in {path}")
    return images


def run_exported_detection_model(exported_path: Path, image: Image.Image, imgsz: int, conf: float, iou: float) -> list[dict]:
    if exported_path.suffix.lower() == ".onnx":
        return run_detection_onnx(exported_path, image, imgsz, conf, iou)
    if exported_path.suffix.lower() == ".tflite":
        return run_detection_tflite(exported_path, image, imgsz, conf, iou)
    raise ValueError(f"unsupported exported detection model {exported_path}")


def run_detection_onnx(exported_path: Path, image: Image.Image, imgsz: int, conf: float, iou: float) -> list[dict]:
    session = ort.InferenceSession(str(exported_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    input_tensor = preprocess_detection_image(image, imgsz)
    output = session.run(None, {input_name: input_tensor})[0]
    return decode_yolo_output(output, image.size[0], image.size[1], imgsz, conf, iou)


def run_detection_tflite(exported_path: Path, image: Image.Image, imgsz: int, conf: float, iou: float) -> list[dict]:
    import tensorflow as tf

    interpreter = tf.lite.Interpreter(model_path=str(exported_path))
    interpreter.allocate_tensors()
    input_info = interpreter.get_input_details()[0]
    output_info = interpreter.get_output_details()[0]
    input_tensor = preprocess_detection_image(image, imgsz)

    if input_info["shape"][-1] == 3:
        input_tensor = np.transpose(input_tensor, (0, 2, 3, 1))

    if np.issubdtype(input_info["dtype"], np.integer):
        scale, zero_point = input_info["quantization"]
        scale = scale or 1.0
        input_tensor = np.round(input_tensor / scale + zero_point)

    interpreter.set_tensor(input_info["index"], input_tensor.astype(input_info["dtype"]))
    interpreter.invoke()
    output = interpreter.get_tensor(output_info["index"])
    if np.issubdtype(output_info["dtype"], np.integer):
        scale, zero_point = output_info["quantization"]
        scale = scale or 1.0
        output = (output.astype(np.float32) - zero_point) * scale
    return decode_yolo_output(output, image.size[0], image.size[1], imgsz, conf, iou)


def preprocess_detection_image(image: Image.Image, imgsz: int) -> np.ndarray:
    resized = image.convert("RGB").resize((imgsz, imgsz))
    array = np.asarray(resized).astype(np.float32) / 255.0
    return np.transpose(array, (2, 0, 1))[None, ...]


def decode_yolo_output(
    output: np.ndarray,
    source_width: int,
    source_height: int,
    input_size: int,
    confidence_threshold: float,
    iou_threshold: float,
) -> list[dict]:
    array = np.asarray(output, dtype=np.float32)
    if array.ndim == 2:
        array = array[None, ...]
    if array.ndim != 3:
        return []

    transposed = array.shape[1] < array.shape[2]
    attr_count = array.shape[1] if transposed else array.shape[2]
    candidate_count = array.shape[2] if transposed else array.shape[1]
    has_objectness = attr_count == 6 or attr_count == 85
    class_start = 5 if has_objectness else 4
    class_count = attr_count - class_start
    detections = []

    for candidate_index in range(candidate_count):
        if transposed:
            values = array[0, :, candidate_index]
        else:
            values = array[0, candidate_index, :]

        cx, cy, w, h = values[:4]
        if class_count > 0:
            class_scores = values[class_start:class_start + class_count]
            best_class_id = int(np.argmax(class_scores))
            best_class_score = float(class_scores[best_class_id])
        else:
            best_class_id = 0
            best_class_score = float(values[4])

        confidence = float(values[4] * best_class_score) if has_objectness and class_count > 0 else best_class_score
        if confidence < confidence_threshold:
            continue

        left = (cx - w / 2.0) * source_width / float(input_size)
        top = (cy - h / 2.0) * source_height / float(input_size)
        right = (cx + w / 2.0) * source_width / float(input_size)
        bottom = (cy + h / 2.0) * source_height / float(input_size)
        detections.append(
            {
                "class_id": best_class_id,
                "score": confidence,
                "bbox": [left, top, right, bottom],
            }
        )

    return nms(detections, iou_threshold)


def nms(detections: list[dict], iou_threshold: float) -> list[dict]:
    remaining = sorted(detections, key=lambda item: item["score"], reverse=True)
    kept: list[dict] = []
    while remaining:
        current = remaining.pop(0)
        kept.append(current)
        remaining = [
            item
            for item in remaining
            if item["class_id"] != current["class_id"] or iou(item["bbox"], current["bbox"]) < iou_threshold
        ]
    return kept


def iou(a: list[float], b: list[float]) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    width = max(0.0, right - left)
    height = max(0.0, bottom - top)
    intersection = width * height
    if intersection == 0.0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return 0.0 if union <= 0.0 else intersection / union


def compare_detection_models(args: argparse.Namespace) -> None:
    from ultralytics import YOLO

    images = list_images(args.images)
    reference_model = YOLO(args.weights)
    exported_path = Path(args.exported)
    report = []

    for image_path in images:
        reference_result = reference_model.predict(str(image_path), conf=args.conf, verbose=False)[0]
        exported_result = run_exported_detection_model(exported_path, Image.open(image_path), args.imgsz, args.conf, args.iou)

        reference_boxes = reference_result.boxes.xyxy.cpu().numpy() if reference_result.boxes is not None else np.empty((0, 4))
        reference_scores = reference_result.boxes.conf.cpu().numpy() if reference_result.boxes is not None else np.empty((0,))
        exported_boxes = np.array([item["bbox"] for item in exported_result], dtype=np.float32) if exported_result else np.empty((0, 4))
        exported_scores = np.array([item["score"] for item in exported_result], dtype=np.float32) if exported_result else np.empty((0,))

        pair_count = min(len(reference_boxes), len(exported_boxes))
        center_errors = []
        ious = []
        for index in range(pair_count):
            ref_box = reference_boxes[index]
            exp_box = exported_boxes[index]
            ref_center = np.array([(ref_box[0] + ref_box[2]) / 2.0, (ref_box[1] + ref_box[3]) / 2.0])
            exp_center = np.array([(exp_box[0] + exp_box[2]) / 2.0, (exp_box[1] + exp_box[3]) / 2.0])
            center_errors.append(float(np.linalg.norm(ref_center - exp_center)))
            ious.append(iou(ref_box.tolist(), exp_box.tolist()))

        report.append(
            {
                "image": str(image_path),
                "reference_count": int(len(reference_boxes)),
                "exported_count": int(len(exported_boxes)),
                "mean_center_error": float(np.mean(center_errors)) if center_errors else None,
                "mean_iou": float(np.mean(ious)) if ious else None,
                "reference_top_score": float(reference_scores[0]) if len(reference_scores) else None,
                "exported_top_score": float(exported_scores[0]) if len(exported_scores) else None,
            }
        )

    print(json.dumps(report, indent=2, ensure_ascii=False))


def compare_court_models(args: argparse.Namespace) -> None:
    images = list_images(args.images)
    exported_path = Path(args.exported)

    model = models.resnet50(weights=None)
    model.fc = nn.Linear(model.fc.in_features, 28)
    model.load_state_dict(torch.load(args.weights, map_location="cpu"))
    model.eval()

    session = ort.InferenceSession(str(exported_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)

    report = []
    for image_path in images:
        image = Image.open(image_path).convert("RGB")
        resized = image.resize((args.input_width, args.input_height))
        tensor = TF.to_tensor(resized)
        normalized = ((tensor - mean) / std).unsqueeze(0)

        with torch.no_grad():
            reference = model(normalized).cpu().numpy()
        exported = session.run(None, {input_name: normalized.cpu().numpy().astype(np.float32)})[0]

        diff = np.abs(reference - exported)
        report.append(
            {
                "image": str(image_path),
                "mean_abs_error": float(diff.mean()),
                "max_abs_error": float(diff.max()),
            }
        )

    print(json.dumps(report, indent=2, ensure_ascii=False))


def main() -> None:
    args = parse_args()
    if args.target in {"player", "ball"}:
        compare_detection_models(args)
    else:
        compare_court_models(args)


if __name__ == "__main__":
    main()
