# TennisAnalysis iOS

## Export Core ML Models

Run these commands on macOS:

```bash
python tools/mobile_export/export_models.py player --weights models/yolov8n_player_sichuan_v1.pt --format coreml --mobile-target ane
python tools/mobile_export/export_models.py ball --weights models/yolov8s_ball_sichuan_v1.pt --format coreml --mobile-target ane
python tools/mobile_export/export_models.py court --weights models/keypoints_model.pth --format coreml --mobile-target ane
```

This produces:

- `mobile_artifacts/player/player_detector.mlpackage`
- `mobile_artifacts/player/player_detector.json`
- `mobile_artifacts/ball/ball_detector.mlpackage`
- `mobile_artifacts/ball/ball_detector.json`
- `mobile_artifacts/court/court_keypoints.mlpackage`
- `mobile_artifacts/court/court_keypoints.json`

## Copy Assets Into The App

```bash
python tools/mobile_export/prepare_ios_assets.py \
  --player-model mobile_artifacts/player/player_detector.mlpackage \
  --player-meta mobile_artifacts/player/player_detector.json \
  --ball-model mobile_artifacts/ball/ball_detector.mlpackage \
  --ball-meta mobile_artifacts/ball/ball_detector.json \
  --court-model mobile_artifacts/court/court_keypoints.mlpackage \
  --court-meta mobile_artifacts/court/court_keypoints.json \
  --clean
```

The default destination is `ios/TennisAnalysisIOS/Resources/Models`.

## Xcode Notes

- Generate the project first with `xcodegen generate --spec ios/project.yml`.
- Add `ios/TennisAnalysisIOS/Resources/Models` to `Copy Bundle Resources`.
- Open the SwiftUI app target and run on a real iPhone or iPad.
- Pick a local video, then wait for the offline pass to analyze and export `*_analyzed.mp4`.

## Current Pipeline

- First pass: detect players, ball, and court keypoints.
- Mid pass: interpolate ball path, detect hit frames, map to mini-court, and aggregate stats.
- Second pass: draw boxes, court keypoints, mini-court, and stats overlay, then export MP4.
