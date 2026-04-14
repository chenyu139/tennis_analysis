import CoreGraphics
import Foundation

struct MiniCourtLayout {
    let drawingRectangleWidth: CGFloat = 250
    let drawingRectangleHeight: CGFloat = 500
    let buffer: CGFloat = 50
    let paddingCourt: CGFloat = 20
}

struct MiniCourtMapper {
    let frameSize: CGSize
    let layout = MiniCourtLayout()

    var startX: CGFloat { frameSize.width - layout.buffer - layout.drawingRectangleWidth }
    var startY: CGFloat { layout.buffer }
    var endX: CGFloat { frameSize.width - layout.buffer }
    var endY: CGFloat { layout.buffer + layout.drawingRectangleHeight }
    var courtStartX: CGFloat { startX + layout.paddingCourt }
    var courtStartY: CGFloat { startY + layout.paddingCourt }
    var courtEndX: CGFloat { endX - layout.paddingCourt }
    var courtEndY: CGFloat { endY - layout.paddingCourt }
    var courtDrawingWidth: CGFloat { courtEndX - courtStartX }

    func convertMetersToPixels(_ meters: CGFloat) -> CGFloat {
        UnitConversion.metersToPixelDistance(
            meters,
            referenceHeightMeters: AnalysisConstants.doubleLineWidthMeters,
            referenceHeightPixels: courtDrawingWidth
        )
    }

    func drawingKeypoints() -> [CGPoint] {
        var values = Array(repeating: CGPoint.zero, count: 14)

        values[0] = CGPoint(x: courtStartX, y: courtStartY)
        values[1] = CGPoint(x: courtEndX, y: courtStartY)
        values[2] = CGPoint(
            x: courtStartX,
            y: courtStartY + convertMetersToPixels(AnalysisConstants.halfCourtLineHeightMeters * 2.0)
        )
        values[3] = CGPoint(x: courtStartX + courtDrawingWidth, y: values[2].y)
        values[4] = CGPoint(x: courtStartX + convertMetersToPixels(AnalysisConstants.doubleAllyDifferenceMeters), y: courtStartY)
        values[5] = CGPoint(x: values[4].x, y: values[2].y)
        values[6] = CGPoint(x: courtEndX - convertMetersToPixels(AnalysisConstants.doubleAllyDifferenceMeters), y: courtStartY)
        values[7] = CGPoint(x: values[6].x, y: values[2].y)
        values[8] = CGPoint(x: values[4].x, y: courtStartY + convertMetersToPixels(AnalysisConstants.noMansLandHeightMeters))
        values[9] = CGPoint(x: values[8].x + convertMetersToPixels(AnalysisConstants.singleLineWidthMeters), y: values[8].y)
        values[10] = CGPoint(x: values[5].x, y: values[5].y - convertMetersToPixels(AnalysisConstants.noMansLandHeightMeters))
        values[11] = CGPoint(x: values[10].x + convertMetersToPixels(AnalysisConstants.singleLineWidthMeters), y: values[10].y)
        values[12] = CGPoint(x: (values[8].x + values[9].x) / 2.0, y: values[8].y)
        values[13] = CGPoint(x: (values[10].x + values[11].x) / 2.0, y: values[10].y)

        return values
    }

    func convertBoundingBoxesToMiniCourtCoordinates(
        playerBoxes: [[Int: BoundingBox]],
        ballBoxes: [BoundingBox?],
        originalCourtKeypoints: [CGPoint]
    ) -> (playerPositions: [[Int: CGPoint]], ballPositions: [[Int: CGPoint]]) {
        let playerHeights: [Int: CGFloat] = [
            1: AnalysisConstants.player1HeightMeters,
            2: AnalysisConstants.player2HeightMeters,
        ]

        var outputPlayerBoxes: [[Int: CGPoint]] = []
        var outputBallBoxes: [[Int: CGPoint]] = []

        for frameIndex in 0..<playerBoxes.count {
            let playerFrame = playerBoxes[frameIndex]
            guard let ballBox = frameIndex < ballBoxes.count ? ballBoxes[frameIndex] : nil else {
                outputPlayerBoxes.append([:])
                outputBallBoxes.append([:])
                continue
            }

            let ballPosition = ballBox.center
            let closestPlayerID = playerFrame.min { lhs, rhs in
                Geometry.measureDistance(lhs.value.center, ballPosition) < Geometry.measureDistance(rhs.value.center, ballPosition)
            }?.key

            var outputPlayerFrame: [Int: CGPoint] = [:]
            for (playerID, bbox) in playerFrame {
                let footPosition = bbox.footPosition
                let closestKeyPointIndex = Geometry.closestKeypointIndex(
                    point: footPosition,
                    keypoints: originalCourtKeypoints,
                    candidateIndices: [0, 2, 12, 13]
                )
                let closestKeyPoint = originalCourtKeypoints[closestKeyPointIndex]
                let frameIndexMin = max(0, frameIndex - 20)
                let frameIndexMax = min(playerBoxes.count - 1, frameIndex + 50)
                let heightsInPixels = (frameIndexMin...frameIndexMax).compactMap { idx -> CGFloat? in
                    playerBoxes[idx][playerID]?.height
                }
                let maxPlayerHeightPixels = heightsInPixels.max() ?? bbox.height

                let miniCourtPosition = getMiniCourtCoordinates(
                    objectPosition: footPosition,
                    closestKeyPoint: closestKeyPoint,
                    closestKeyPointIndex: closestKeyPointIndex,
                    playerHeightInPixels: maxPlayerHeightPixels,
                    playerHeightInMeters: playerHeights[playerID] ?? AnalysisConstants.player1HeightMeters
                )
                outputPlayerFrame[playerID] = miniCourtPosition

                if closestPlayerID == playerID {
                    let ballClosestKeyPointIndex = Geometry.closestKeypointIndex(
                        point: ballPosition,
                        keypoints: originalCourtKeypoints,
                        candidateIndices: [0, 2, 12, 13]
                    )
                    let ballClosestKeyPoint = originalCourtKeypoints[ballClosestKeyPointIndex]
                    let miniCourtBallPosition = getMiniCourtCoordinates(
                        objectPosition: ballPosition,
                        closestKeyPoint: ballClosestKeyPoint,
                        closestKeyPointIndex: ballClosestKeyPointIndex,
                        playerHeightInPixels: maxPlayerHeightPixels,
                        playerHeightInMeters: playerHeights[playerID] ?? AnalysisConstants.player1HeightMeters
                    )
                    outputBallBoxes.append([1: miniCourtBallPosition])
                }
            }
            outputPlayerBoxes.append(outputPlayerFrame)
            if outputBallBoxes.count < outputPlayerBoxes.count {
                outputBallBoxes.append([:])
            }
        }

        return (outputPlayerBoxes, outputBallBoxes)
    }

    private func getMiniCourtCoordinates(
        objectPosition: CGPoint,
        closestKeyPoint: CGPoint,
        closestKeyPointIndex: Int,
        playerHeightInPixels: CGFloat,
        playerHeightInMeters: CGFloat
    ) -> CGPoint {
        let xyDistance = Geometry.measureXYDistance(objectPosition, closestKeyPoint)
        let xMeters = UnitConversion.pixelDistanceToMeters(
            xyDistance.x,
            referenceHeightMeters: playerHeightInMeters,
            referenceHeightPixels: playerHeightInPixels
        )
        let yMeters = UnitConversion.pixelDistanceToMeters(
            xyDistance.y,
            referenceHeightMeters: playerHeightInMeters,
            referenceHeightPixels: playerHeightInPixels
        )
        let xPixels = convertMetersToPixels(xMeters)
        let yPixels = convertMetersToPixels(yMeters)
        let miniCourtKeyPoint = drawingKeypoints()[closestKeyPointIndex]
        return CGPoint(x: miniCourtKeyPoint.x + xPixels, y: miniCourtKeyPoint.y + yPixels)
    }
}
