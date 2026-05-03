import CoreGraphics
import Foundation

struct PlayerSelection {
    func chooseAndFilterPlayers(
        courtKeypoints: [CGPoint],
        detectionsPerFrame: [[Int: BoundingBox]]
    ) -> [[Int: BoundingBox]] {
        guard !detectionsPerFrame.isEmpty else { return detectionsPerFrame }
        let chosenPlayers = choosePlayersByVoting(
            courtKeypoints: courtKeypoints,
            detectionsPerFrame: detectionsPerFrame
        )
        guard chosenPlayers.count == 2 else {
            return chooseAndFilterPlayersFallback(
                courtKeypoints: courtKeypoints,
                detectionsPerFrame: detectionsPerFrame
            )
        }

        let playerIDMap = [
            chosenPlayers[0]: 1,
            chosenPlayers[1]: 2,
        ]

        return detectionsPerFrame.map { frameDetections in
            var filtered: [Int: BoundingBox] = [:]
            for (trackID, bbox) in frameDetections {
                if let normalizedID = playerIDMap[trackID] {
                    filtered[normalizedID] = bbox
                }
            }
            return filtered
        }
    }

    private func choosePlayersByVoting(
        courtKeypoints: [CGPoint],
        detectionsPerFrame: [[Int: BoundingBox]]
    ) -> [Int] {
        let sampleWindow = min(30, detectionsPerFrame.count)
        let sampleStride = max(1, sampleWindow / 10)
        var voteCounts: [Int: Int] = [:]

        for frameIndex in stride(from: 0, to: sampleWindow, by: sampleStride) {
            let frameDetections = detectionsPerFrame[frameIndex]
            let chosen = choosePlayers(courtKeypoints: courtKeypoints, playerDetections: frameDetections)
            for playerID in chosen {
                voteCounts[playerID, default: 0] += 1
            }
        }

        let sortedByVotes = voteCounts.sorted { $0.value > $1.value }
        guard sortedByVotes.count >= 2 else {
            return sortedByVotes.map(\.key)
        }
        return [sortedByVotes[0].key, sortedByVotes[1].key]
    }

    private func chooseAndFilterPlayersFallback(
        courtKeypoints: [CGPoint],
        detectionsPerFrame: [[Int: BoundingBox]]
    ) -> [[Int: BoundingBox]] {
        guard let firstFrame = detectionsPerFrame.first else { return detectionsPerFrame }
        let chosenPlayers = choosePlayers(courtKeypoints: courtKeypoints, playerDetections: firstFrame)
        guard chosenPlayers.count == 2 else { return detectionsPerFrame }

        let playerIDMap = [
            chosenPlayers[0]: 1,
            chosenPlayers[1]: 2,
        ]

        return detectionsPerFrame.map { frameDetections in
            var filtered: [Int: BoundingBox] = [:]
            for (trackID, bbox) in frameDetections {
                if let normalizedID = playerIDMap[trackID] {
                    filtered[normalizedID] = bbox
                }
            }
            return filtered
        }
    }

    private func choosePlayers(courtKeypoints: [CGPoint], playerDetections: [Int: BoundingBox]) -> [Int] {
        let distances = playerDetections.map { trackID, bbox -> (Int, CGFloat) in
            let playerCenter = bbox.center
            let minDistance = courtKeypoints.map { Geometry.measureDistance(playerCenter, $0) }.min() ?? .greatestFiniteMagnitude
            return (trackID, minDistance)
        }
        return distances.sorted { $0.1 < $1.1 }.prefix(2).map(\.0)
    }
}
