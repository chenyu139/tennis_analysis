import CoreGraphics
import Foundation

struct BallInterpolation {
    func interpolate(ballBoxes: [BoundingBox?]) -> [BoundingBox?] {
        guard !ballBoxes.isEmpty else { return [] }
        var x1 = ballBoxes.map { $0?.x1 }
        var y1 = ballBoxes.map { $0?.y1 }
        var x2 = ballBoxes.map { $0?.x2 }
        var y2 = ballBoxes.map { $0?.y2 }

        interpolateInPlace(&x1)
        interpolateInPlace(&y1)
        interpolateInPlace(&x2)
        interpolateInPlace(&y2)

        return (0..<ballBoxes.count).map { index in
            guard let x1 = x1[index], let y1 = y1[index], let x2 = x2[index], let y2 = y2[index] else {
                return nil
            }
            return BoundingBox(x1: x1, y1: y1, x2: x2, y2: y2)
        }
    }

    private func interpolateInPlace(_ values: inout [CGFloat?]) {
        let validIndices = values.indices.filter { values[$0] != nil }
        guard let first = validIndices.first, let last = validIndices.last else { return }

        for index in values.indices where index < first {
            values[index] = values[first]
        }
        for index in values.indices where index > last {
            values[index] = values[last]
        }

        var previousIndex = first
        for currentIndex in validIndices.dropFirst() {
            guard currentIndex - previousIndex > 1 else {
                previousIndex = currentIndex
                continue
            }
            let start = values[previousIndex]!
            let end = values[currentIndex]!
            let stepCount = CGFloat(currentIndex - previousIndex)
            for gapIndex in (previousIndex + 1)..<currentIndex {
                let ratio = CGFloat(gapIndex - previousIndex) / stepCount
                values[gapIndex] = start + (end - start) * ratio
            }
            previousIndex = currentIndex
        }
    }
}

struct BallShotDetector {
    func shotFrames(ballBoxes: [BoundingBox?]) -> [Int] {
        let midY = ballBoxes.map { box -> CGFloat? in
            guard let box else { return nil }
            return (box.y1 + box.y2) / 2.0
        }
        let rollingMean = rollingAverage(values: midY, window: 5)
        var deltaY = Array<CGFloat?>(repeating: nil, count: rollingMean.count)
        for index in 1..<rollingMean.count {
            if let current = rollingMean[index], let previous = rollingMean[index - 1] {
                deltaY[index] = current - previous
            }
        }

        let minimumChangeFramesForHit = 25
        var hitFrames: [Int] = []
        if deltaY.count > Int(Double(minimumChangeFramesForHit) * 1.2) {
            for index in 1..<(deltaY.count - Int(Double(minimumChangeFramesForHit) * 1.2)) {
                guard let current = deltaY[index], let next = deltaY[index + 1] else { continue }
                let negativePositionChange = current > 0 && next < 0
                let positivePositionChange = current < 0 && next > 0
                if negativePositionChange || positivePositionChange {
                    var changeCount = 0
                    for changeFrame in (index + 1)...min(deltaY.count - 1, index + Int(Double(minimumChangeFramesForHit) * 1.2)) {
                        guard let candidate = deltaY[changeFrame] else { continue }
                        let negativeFollowing = current > 0 && candidate < 0
                        let positiveFollowing = current < 0 && candidate > 0
                        if negativePositionChange && negativeFollowing {
                            changeCount += 1
                        } else if positivePositionChange && positiveFollowing {
                            changeCount += 1
                        }
                    }
                    if changeCount > minimumChangeFramesForHit - 1 {
                        hitFrames.append(index)
                    }
                }
            }
        }

        if !hitFrames.isEmpty {
            return hitFrames
        }

        var signChanges: [Int] = []
        var lastSign: Int?
        for (index, delta) in deltaY.enumerated() {
            guard let delta else { continue }
            let sign = delta > 0 ? 1 : 0
            if let lastSign, lastSign != sign {
                signChanges.append(index)
            }
            lastSign = sign
        }

        var filteredFrames: [Int] = []
        let minimumGap = 12
        for frame in signChanges {
            if filteredFrames.isEmpty || frame - filteredFrames[filteredFrames.count - 1] >= minimumGap {
                filteredFrames.append(frame)
            }
        }
        return filteredFrames
    }

    private func rollingAverage(values: [CGFloat?], window: Int) -> [CGFloat?] {
        values.indices.map { index in
            let start = max(0, index - window + 1)
            let slice = values[start...index].compactMap { $0 }
            guard !slice.isEmpty else { return nil }
            return slice.reduce(0, +) / CGFloat(slice.count)
        }
    }
}
