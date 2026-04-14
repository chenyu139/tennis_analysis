import CoreGraphics
import Foundation

struct SortTracker {
    private struct TrackState {
        let id: Int
        var bbox: BoundingBox
        var score: Float
        var hits: Int
        var missed: Int
        var lastTimestampNs: UInt64
        var velocity: CGPoint?
    }

    private let maxAge: Int
    private let minHits: Int
    private let iouThreshold: CGFloat
    private var tracks: [TrackState] = []
    private var nextTrackID = 1

    init(maxAge: Int = 8, minHits: Int = 2, iouThreshold: CGFloat = 0.2) {
        self.maxAge = maxAge
        self.minHits = minHits
        self.iouThreshold = iouThreshold
    }

    mutating func update(detections: [Detection], timestampNs: UInt64) -> [TrackedObject] {
        var unmatchedTrackIndices = Set(tracks.indices)
        var unmatchedDetections = detections

        for detection in detections.sorted(by: { $0.score > $1.score }) {
            let bestTrackIndex = unmatchedTrackIndices.max { lhs, rhs in
                Geometry.iou(tracks[lhs].bbox, detection.bbox) < Geometry.iou(tracks[rhs].bbox, detection.bbox)
            }
            let bestIoU = bestTrackIndex.map { Geometry.iou(tracks[$0].bbox, detection.bbox) } ?? 0
            if let bestTrackIndex, bestIoU >= iouThreshold {
                let previousCenter = tracks[bestTrackIndex].bbox.center
                let nextCenter = detection.bbox.center
                let dt = max(1, Int64(timestampNs) - Int64(tracks[bestTrackIndex].lastTimestampNs))
                let dtSeconds = CGFloat(dt) / 1_000_000_000.0
                tracks[bestTrackIndex].velocity = CGPoint(
                    x: (nextCenter.x - previousCenter.x) / dtSeconds,
                    y: (nextCenter.y - previousCenter.y) / dtSeconds
                )
                tracks[bestTrackIndex].bbox = detection.bbox
                tracks[bestTrackIndex].score = detection.score
                tracks[bestTrackIndex].hits += 1
                tracks[bestTrackIndex].missed = 0
                tracks[bestTrackIndex].lastTimestampNs = timestampNs
                unmatchedTrackIndices.remove(bestTrackIndex)
                unmatchedDetections.removeAll { $0.timestampNs == detection.timestampNs && $0.bbox == detection.bbox }
            }
        }

        for trackIndex in unmatchedTrackIndices {
            tracks[trackIndex].missed += 1
            tracks[trackIndex].lastTimestampNs = timestampNs
        }

        for detection in unmatchedDetections {
            tracks.append(
                TrackState(
                    id: nextTrackID,
                    bbox: detection.bbox,
                    score: detection.score,
                    hits: 1,
                    missed: 0,
                    lastTimestampNs: timestampNs,
                    velocity: nil
                )
            )
            nextTrackID += 1
        }

        tracks.removeAll { $0.missed > maxAge }

        return tracks
            .filter { $0.hits >= minHits || $0.missed == 0 }
            .sorted { lhs, rhs in
                let lhsArea = (lhs.bbox.x2 - lhs.bbox.x1) * (lhs.bbox.y2 - lhs.bbox.y1)
                let rhsArea = (rhs.bbox.x2 - rhs.bbox.x1) * (rhs.bbox.y2 - rhs.bbox.y1)
                return (CGFloat(lhs.score) * lhsArea) > (CGFloat(rhs.score) * rhsArea)
            }
            .prefix(2)
            .map {
                TrackedObject(
                    trackId: $0.id,
                    classId: 0,
                    score: $0.score,
                    bbox: $0.bbox,
                    center: $0.bbox.center,
                    velocity: $0.velocity,
                    timestampNs: timestampNs
                )
            }
    }
}

struct BallTrackFilter {
    private let maxLostFrames: Int
    private var lastBall: TrackedObject?
    private var lostFrames = 0

    init(maxLostFrames: Int = 5) {
        self.maxLostFrames = maxLostFrames
    }

    mutating func update(detections: [Detection], timestampNs: UInt64) -> TrackedObject? {
        let bestDetection: Detection?
        if let lastBall {
            bestDetection = detections.min { lhs, rhs in
                let lhsValue = Geometry.measureDistance(lhs.bbox.center, lastBall.center) - CGFloat(lhs.score * 50)
                let rhsValue = Geometry.measureDistance(rhs.bbox.center, lastBall.center) - CGFloat(rhs.score * 50)
                return lhsValue < rhsValue
            }
        } else {
            bestDetection = detections.max(by: { $0.score < $1.score })
        }

        guard let bestDetection else {
            lostFrames += 1
            if lostFrames > maxLostFrames {
                lastBall = nil
            }
            return lastBall
        }

        let previousBall = lastBall
        let nextCenter = bestDetection.bbox.center
        let velocity = previousBall.map { previousBall in
            let dt = max(1, Int64(timestampNs) - Int64(previousBall.timestampNs))
            let dtSeconds = CGFloat(dt) / 1_000_000_000.0
            return CGPoint(
                x: (nextCenter.x - previousBall.center.x) / dtSeconds,
                y: (nextCenter.y - previousBall.center.y) / dtSeconds
            )
        }
        let smoothedBox = previousBall.map { smooth(previous: $0.bbox, current: bestDetection.bbox) } ?? bestDetection.bbox

        let tracked = TrackedObject(
            trackId: 1,
            classId: bestDetection.classId,
            score: bestDetection.score,
            bbox: smoothedBox,
            center: smoothedBox.center,
            velocity: velocity,
            timestampNs: timestampNs
        )
        lastBall = tracked
        lostFrames = 0
        return tracked
    }

    private func smooth(previous: BoundingBox, current: BoundingBox) -> BoundingBox {
        let alpha: CGFloat = 0.65
        return BoundingBox(
            x1: previous.x1 * alpha + current.x1 * (1 - alpha),
            y1: previous.y1 * alpha + current.y1 * (1 - alpha),
            x2: previous.x2 * alpha + current.x2 * (1 - alpha),
            y2: previous.y2 * alpha + current.y2 * (1 - alpha)
        )
    }
}
