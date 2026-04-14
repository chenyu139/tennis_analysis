# PC To iOS Migration Plan

## Product Goal

Run the full tennis analysis pipeline on iPhone using a local input video and export a rendered output video with feature parity to the current PC workflow.

## Scope Confirmed

- Offline local video processing only
- Export rendered `mp4`
- Keep the same analysis metrics and overlay categories as the PC pipeline

## PC To iOS Module Mapping

| PC Module | Current File | iOS Target |
| --- | --- | --- |
| Main orchestration | `main.py` | `OfflineVideoProcessor.swift` |
| Player detection | `trackers/player_tracker.py` | `PlayerDetector` Core ML wrapper |
| Ball detection | `trackers/ball_tracker.py` | `BallDetector` Core ML wrapper |
| Ball interpolation | `trackers/ball_tracker.py` | `BallInterpolation.swift` |
| Ball hit detection | `trackers/ball_tracker.py` | `BallShotDetector.swift` |
| Court keypoints | `court_line_detector/court_line_detector.py` | `CourtKeypointDetector` Core ML wrapper |
| Mini-court conversion | `mini_court/mini_court.py` | `MiniCourtMapper.swift` |
| Stats formulas | `main.py` | `StatsAggregator.swift` |
| Stats panel drawing | `utils/player_stats_drawer_utils.py` | `FrameRenderer.swift` |
| Video read/write | `utils/video_utils.py` | `VideoAssetIO.swift` |

## Required iOS Modules

### Phase 1

- `VideoAssetIO`
- `OfflineVideoProcessor`
- `PlayerDetector`
- `BallDetector`
- `CourtKeypointDetector`

### Phase 2

- `BallInterpolation`
- `BallShotDetector`
- `StatsAggregator`
- `FrameRenderer`
- `ExportCoordinator`

## Feature Parity Checklist

- [ ] Two-player filtering
- [ ] Ball interpolation
- [ ] Court keypoints on rendered frames
- [ ] Mini-court drawing
- [ ] Player dots on mini-court
- [ ] Ball dots on mini-court
- [ ] Shot speed
- [ ] Player speed
- [ ] Distance
- [ ] Calories
- [ ] Frame number overlay
- [ ] Output video export

## Model Work Needed

- Convert player YOLO model to Core ML
- Convert ball YOLO model to Core ML
- Convert court keypoint model to Core ML
- Verify input normalization and output decoding against the PC implementation

## Validation Strategy

- Use the same sample video on PC and iPhone
- Compare frame-by-frame outputs at fixed frame checkpoints
- Compare stats rows for shot speed, player speed, distance, and calories
- Accept only small numeric drift caused by floating-point differences
