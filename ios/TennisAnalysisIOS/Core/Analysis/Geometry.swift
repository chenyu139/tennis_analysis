import CoreGraphics
import Foundation

struct BoundingBox: Codable, Hashable {
    let x1: CGFloat
    let y1: CGFloat
    let x2: CGFloat
    let y2: CGFloat

    var center: CGPoint {
        CGPoint(x: (x1 + x2) / 2.0, y: (y1 + y2) / 2.0)
    }

    var footPosition: CGPoint {
        CGPoint(x: (x1 + x2) / 2.0, y: y2)
    }

    var height: CGFloat {
        y2 - y1
    }
}

enum Geometry {
    static func measureDistance(_ p1: CGPoint, _ p2: CGPoint) -> CGFloat {
        let dx = p1.x - p2.x
        let dy = p1.y - p2.y
        return sqrt(dx * dx + dy * dy)
    }

    static func measureXYDistance(_ p1: CGPoint, _ p2: CGPoint) -> CGPoint {
        CGPoint(x: abs(p1.x - p2.x), y: abs(p1.y - p2.y))
    }

    static func iou(_ a: BoundingBox, _ b: BoundingBox) -> CGFloat {
        let left = max(a.x1, b.x1)
        let top = max(a.y1, b.y1)
        let right = min(a.x2, b.x2)
        let bottom = min(a.y2, b.y2)
        let intersectionWidth = max(0, right - left)
        let intersectionHeight = max(0, bottom - top)
        let intersection = intersectionWidth * intersectionHeight
        let union = max(0, a.x2 - a.x1) * max(0, a.y2 - a.y1) + max(0, b.x2 - b.x1) * max(0, b.y2 - b.y1) - intersection
        return union <= 0 ? 0 : intersection / union
    }

    static func closestKeypointIndex(
        point: CGPoint,
        keypoints: [CGPoint],
        candidateIndices: [Int]
    ) -> Int {
        var closestIndex = candidateIndices[0]
        var closestDistance = CGFloat.greatestFiniteMagnitude
        for index in candidateIndices {
            let keypoint = keypoints[index]
            let distance = abs(point.y - keypoint.y)
            if distance < closestDistance {
                closestDistance = distance
                closestIndex = index
            }
        }
        return closestIndex
    }
}

enum UnitConversion {
    static func pixelDistanceToMeters(
        _ pixelDistance: CGFloat,
        referenceHeightMeters: CGFloat,
        referenceHeightPixels: CGFloat
    ) -> CGFloat {
        guard referenceHeightPixels > 0 else { return 0 }
        return (pixelDistance * referenceHeightMeters) / referenceHeightPixels
    }

    static func metersToPixelDistance(
        _ meters: CGFloat,
        referenceHeightMeters: CGFloat,
        referenceHeightPixels: CGFloat
    ) -> CGFloat {
        guard referenceHeightMeters > 0 else { return 0 }
        return (meters * referenceHeightPixels) / referenceHeightMeters
    }
}
