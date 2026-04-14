import CoreGraphics
import Foundation

struct StatsAggregator {
    func emptyRows(frameCount: Int) -> [PlayerStatsRow] {
        (0..<frameCount).map { PlayerStatsRow(frameNumber: $0) }
    }

    func caloriesBurned(distanceMeters: Double, playerWeightKg: Double) -> Double {
        (distanceMeters / 1000.0) * playerWeightKg * AnalysisConstants.caloriesPerKmPerKg
    }

    func speedKmPerHour(distanceMeters: Double, durationSeconds: Double) -> Double {
        guard durationSeconds > 0 else { return 0 }
        return distanceMeters / durationSeconds * 3.6
    }

    func average(total: Double, count: Int) -> Double {
        guard count > 0 else { return 0 }
        return total / Double(count)
    }

    func buildStatsRows(
        frameCount: Int,
        frameRate: Double,
        ballShotFrames: [Int],
        playerMiniCourtDetections: [[Int: CGPoint]],
        ballMiniCourtDetections: [[Int: CGPoint]],
        miniCourtWidth: CGFloat
    ) -> [PlayerStatsRow] {
        guard frameCount > 0 else { return [] }
        var rows = [PlayerStatsRow(frameNumber: 0)]

        for index in 0..<(max(0, ballShotFrames.count - 1)) {
            let startFrame = ballShotFrames[index]
            let endFrame = ballShotFrames[index + 1]
            let shotDuration = Double(endFrame - startFrame) / max(frameRate, 1)
            guard shotDuration > 0,
                  startFrame < ballMiniCourtDetections.count,
                  endFrame < ballMiniCourtDetections.count,
                  startFrame < playerMiniCourtDetections.count,
                  endFrame < playerMiniCourtDetections.count,
                  let ballStart = ballMiniCourtDetections[startFrame][1],
                  let ballEnd = ballMiniCourtDetections[endFrame][1] else {
                continue
            }

            let ballDistancePixels = Geometry.measureDistance(ballStart, ballEnd)
            let ballDistanceMeters = Double(
                UnitConversion.pixelDistanceToMeters(
                    ballDistancePixels,
                    referenceHeightMeters: AnalysisConstants.doubleLineWidthMeters,
                    referenceHeightPixels: miniCourtWidth
                )
            )
            let ballShotSpeed = speedKmPerHour(distanceMeters: ballDistanceMeters, durationSeconds: shotDuration)

            let playerPositions = playerMiniCourtDetections[startFrame]
            let hitterID = playerPositions.min { lhs, rhs in
                guard let lhsBall = ballMiniCourtDetections[startFrame][1] else { return false }
                return Geometry.measureDistance(lhs.value, lhsBall) < Geometry.measureDistance(rhs.value, lhsBall)
            }?.key ?? 1
            let opponentID = hitterID == 2 ? 1 : 2

            let opponentDistancePixels = Geometry.measureDistance(
                playerMiniCourtDetections[startFrame][opponentID] ?? .zero,
                playerMiniCourtDetections[endFrame][opponentID] ?? .zero
            )
            let opponentDistanceMeters = Double(
                UnitConversion.pixelDistanceToMeters(
                    opponentDistancePixels,
                    referenceHeightMeters: AnalysisConstants.doubleLineWidthMeters,
                    referenceHeightPixels: miniCourtWidth
                )
            )
            let opponentSpeed = speedKmPerHour(distanceMeters: opponentDistanceMeters, durationSeconds: shotDuration)

            let player1DistancePixels = Geometry.measureDistance(
                playerMiniCourtDetections[startFrame][1] ?? .zero,
                playerMiniCourtDetections[endFrame][1] ?? .zero
            )
            let player2DistancePixels = Geometry.measureDistance(
                playerMiniCourtDetections[startFrame][2] ?? .zero,
                playerMiniCourtDetections[endFrame][2] ?? .zero
            )
            let player1DistanceMeters = Double(
                UnitConversion.pixelDistanceToMeters(
                    player1DistancePixels,
                    referenceHeightMeters: AnalysisConstants.doubleLineWidthMeters,
                    referenceHeightPixels: miniCourtWidth
                )
            )
            let player2DistanceMeters = Double(
                UnitConversion.pixelDistanceToMeters(
                    player2DistancePixels,
                    referenceHeightMeters: AnalysisConstants.doubleLineWidthMeters,
                    referenceHeightPixels: miniCourtWidth
                )
            )

            let player1Calories = caloriesBurned(distanceMeters: player1DistanceMeters, playerWeightKg: AnalysisConstants.player1WeightKg)
            let player2Calories = caloriesBurned(distanceMeters: player2DistanceMeters, playerWeightKg: AnalysisConstants.player2WeightKg)

            var current = rows.last ?? PlayerStatsRow(frameNumber: startFrame)
            current.frameNumber = startFrame
            if hitterID == 1 {
                current.player1NumberOfShots += 1
                current.player1TotalShotSpeed += ballShotSpeed
                current.player1LastShotSpeed = ballShotSpeed
                current.player2TotalPlayerSpeed += opponentSpeed
                current.player2LastPlayerSpeed = opponentSpeed
            } else {
                current.player2NumberOfShots += 1
                current.player2TotalShotSpeed += ballShotSpeed
                current.player2LastShotSpeed = ballShotSpeed
                current.player1TotalPlayerSpeed += opponentSpeed
                current.player1LastPlayerSpeed = opponentSpeed
            }

            current.player1TotalDistanceRun += player1DistanceMeters
            current.player1LastDistanceRun = player1DistanceMeters
            current.player1TotalCaloriesBurned += player1Calories
            current.player1LastCaloriesBurned = player1Calories

            current.player2TotalDistanceRun += player2DistanceMeters
            current.player2LastDistanceRun = player2DistanceMeters
            current.player2TotalCaloriesBurned += player2Calories
            current.player2LastCaloriesBurned = player2Calories

            rows.append(current)
        }

        var expanded = [PlayerStatsRow]()
        var lastRow = rows.first ?? PlayerStatsRow(frameNumber: 0)
        let keyedRows = Dictionary(uniqueKeysWithValues: rows.map { ($0.frameNumber, $0) })
        for frameNumber in 0..<frameCount {
            if let row = keyedRows[frameNumber] {
                lastRow = row
            }
            var forwardFilled = lastRow
            forwardFilled.frameNumber = frameNumber
            let player1Shots = max(forwardFilled.player1NumberOfShots, 1)
            let player2Shots = max(forwardFilled.player2NumberOfShots, 1)
            forwardFilled.player1AverageShotSpeed = average(total: forwardFilled.player1TotalShotSpeed, count: player1Shots)
            forwardFilled.player2AverageShotSpeed = average(total: forwardFilled.player2TotalShotSpeed, count: player2Shots)
            forwardFilled.player1AveragePlayerSpeed = average(total: forwardFilled.player1TotalPlayerSpeed, count: player2Shots)
            forwardFilled.player2AveragePlayerSpeed = average(total: forwardFilled.player2TotalPlayerSpeed, count: player1Shots)
            expanded.append(forwardFilled)
        }
        return expanded
    }
}
