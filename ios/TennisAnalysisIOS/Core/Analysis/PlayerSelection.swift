import CoreGraphics
import Foundation

struct PlayerSelection {
    func chooseAndFilterPlayers(
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
