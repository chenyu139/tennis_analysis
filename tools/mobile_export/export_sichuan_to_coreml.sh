#!/usr/bin/env bash
# Export new sichuan-trained models to CoreML for iOS.
# MUST be run on macOS with coremltools installed.
#
# Usage:
#   bash tools/mobile_export/export_sichuan_to_coreml.sh
#
# Prerequisites (macOS only):
#   pip install coremltools ultralytics
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Exporting sichuan-trained models to CoreML ==="

# Ball model: YOLOv8s → CoreML
echo ""
echo "[1/3] Exporting ball detector (YOLOv8s sichuan)..."
python tools/mobile_export/export_models.py ball \
    --weights models/yolov8s_ball_sichuan_v1.pt \
    --format coreml \
    --mobile-target ane \
    --output-dir mobile_artifacts/ball \
    --output-name ball_detector

# Player model: YOLOv8x COCO → CoreML (person detection, class 0)
echo ""
echo "[2/3] Exporting player detector (YOLOv8x COCO person)..."
python tools/mobile_export/export_models.py player \
    --weights models/yolov8x.pt \
    --format coreml \
    --mobile-target ane \
    --output-dir mobile_artifacts/player \
    --output-name player_detector

# Court model (unchanged, but re-export for consistency)
echo ""
echo "[3/3] Exporting court keypoint detector..."
python tools/mobile_export/export_models.py court \
    --weights models/keypoints_model.pth \
    --format coreml \
    --mobile-target ane

echo ""
echo "=== Copying assets to iOS project ==="
python tools/mobile_export/prepare_ios_assets.py \
    --player-model mobile_artifacts/player/player_detector.mlpackage \
    --player-meta mobile_artifacts/player/player_detector.json \
    --ball-model mobile_artifacts/ball/ball_detector.mlpackage \
    --ball-meta mobile_artifacts/ball/ball_detector.json \
    --court-model mobile_artifacts/court/court_keypoints.mlpackage \
    --court-meta mobile_artifacts/court/court_keypoints.json \
    --clean

echo ""
echo "=== Done! ==="
echo "Next steps:"
echo "  1. cd ios && xcodegen generate --spec project.yml"
echo "  2. Open the generated .xcodeproj in Xcode"
echo "  3. Build & run on a real iPhone"
