import CoreGraphics
import CoreVideo
import Foundation
import UIKit

struct FrameRenderer {
    func render(
        pixelBuffer: CVPixelBuffer,
        overlay: OverlayFrame,
        playerMiniCourtPositions: [Int: CGPoint],
        ballMiniCourtPosition: CGPoint?
    ) {
        CVPixelBufferLockBaseAddress(pixelBuffer, [])
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }

        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else { return }
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        guard let context = CGContext(
            data: baseAddress,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: bytesPerRow,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        ) else {
            return
        }

        context.translateBy(x: 0, y: CGFloat(height))
        context.scaleBy(x: 1, y: -1)

        drawPlayers(context: context, players: overlay.players)
        drawBall(context: context, ball: overlay.ball)
        drawCourtKeypoints(context: context, keypoints: overlay.court?.points ?? [])
        drawMiniCourt(
            context: context,
            frameSize: overlay.sourceSize,
            playerPositions: playerMiniCourtPositions,
            ballPosition: ballMiniCourtPosition
        )
        if let stats = overlay.stats {
            drawStats(context: context, frameSize: overlay.sourceSize, stats: stats)
        }
        drawFrameNumber(context: context, frameNumber: overlay.frameNumber)
    }

    private func drawPlayers(context: CGContext, players: [TrackedObject]) {
        context.setLineWidth(3)
        context.setStrokeColor(UIColor.red.cgColor)
        for player in players {
            let rect = CGRect(
                x: player.bbox.x1,
                y: player.bbox.y1,
                width: player.bbox.x2 - player.bbox.x1,
                height: player.bbox.y2 - player.bbox.y1
            )
            context.stroke(rect)
            drawText(
                context: context,
                text: "Player ID: \(player.trackId)",
                origin: CGPoint(x: rect.minX, y: max(12, rect.minY - 18)),
                color: .red,
                fontSize: 16
            )
        }
    }

    private func drawBall(context: CGContext, ball: TrackedObject?) {
        guard let ball else { return }
        let rect = CGRect(
            x: ball.bbox.x1,
            y: ball.bbox.y1,
            width: ball.bbox.x2 - ball.bbox.x1,
            height: ball.bbox.y2 - ball.bbox.y1
        )
        context.setLineWidth(3)
        context.setStrokeColor(UIColor.yellow.cgColor)
        context.stroke(rect)
        drawText(
            context: context,
            text: "Ball ID: \(ball.trackId)",
            origin: CGPoint(x: rect.minX, y: max(12, rect.minY - 18)),
            color: .yellow,
            fontSize: 16
        )
    }

    private func drawCourtKeypoints(context: CGContext, keypoints: [CGPoint]) {
        context.setFillColor(UIColor.red.cgColor)
        for (index, point) in keypoints.enumerated() {
            let circleRect = CGRect(x: point.x - 4, y: point.y - 4, width: 8, height: 8)
            context.fillEllipse(in: circleRect)
            drawText(
                context: context,
                text: "\(index)",
                origin: CGPoint(x: point.x + 6, y: point.y - 6),
                color: .red,
                fontSize: 12
            )
        }
    }

    private func drawMiniCourt(
        context: CGContext,
        frameSize: CGSize,
        playerPositions: [Int: CGPoint],
        ballPosition: CGPoint?
    ) {
        let mapper = MiniCourtMapper(frameSize: frameSize)
        let keypoints = mapper.drawingKeypoints()
        let backgroundRect = CGRect(
            x: mapper.startX,
            y: mapper.startY,
            width: mapper.endX - mapper.startX,
            height: mapper.endY - mapper.startY
        )
        context.setFillColor(UIColor.white.withAlphaComponent(0.5).cgColor)
        context.fill(backgroundRect)

        let lines = [(0, 2), (4, 5), (6, 7), (1, 3), (0, 1), (8, 9), (10, 11), (2, 3)]
        context.setStrokeColor(UIColor.black.cgColor)
        context.setLineWidth(2)
        for (start, end) in lines {
            context.move(to: keypoints[start])
            context.addLine(to: keypoints[end])
            context.strokePath()
        }
        context.setStrokeColor(UIColor.blue.cgColor)
        context.move(to: CGPoint(x: keypoints[0].x, y: (keypoints[0].y + keypoints[2].y) / 2))
        context.addLine(to: CGPoint(x: keypoints[1].x, y: (keypoints[1].y + keypoints[3].y) / 2))
        context.strokePath()

        context.setFillColor(UIColor.green.cgColor)
        for (_, position) in playerPositions {
            context.fillEllipse(in: CGRect(x: position.x - 4, y: position.y - 4, width: 8, height: 8))
        }
        if let ballPosition {
            context.setFillColor(UIColor.yellow.cgColor)
            context.fillEllipse(in: CGRect(x: ballPosition.x - 4, y: ballPosition.y - 4, width: 8, height: 8))
        }
    }

    private func drawStats(context: CGContext, frameSize: CGSize, stats: PlayerStatsRow) {
        let startX = frameSize.width - 400
        let startY = frameSize.height - 500
        let width: CGFloat = 360
        let height: CGFloat = 320
        let rect = CGRect(x: startX, y: startY, width: width, height: height)
        context.setFillColor(UIColor.black.withAlphaComponent(0.5).cgColor)
        context.fill(rect)

        drawText(context: context, text: "     Player 1     Player 2", origin: CGPoint(x: startX + 85, y: startY + 30), color: .white, fontSize: 18, weight: .semibold)
        drawText(context: context, text: "Shot Speed", origin: CGPoint(x: startX + 10, y: startY + 80), color: .white, fontSize: 14)
        drawText(context: context, text: String(format: "%.1f km/h    %.1f km/h", stats.player1LastShotSpeed, stats.player2LastShotSpeed), origin: CGPoint(x: startX + 130, y: startY + 80), color: .white, fontSize: 16, weight: .semibold)
        drawText(context: context, text: "Player Speed", origin: CGPoint(x: startX + 10, y: startY + 120), color: .white, fontSize: 14)
        drawText(context: context, text: String(format: "%.1f km/h    %.1f km/h", stats.player1LastPlayerSpeed, stats.player2LastPlayerSpeed), origin: CGPoint(x: startX + 130, y: startY + 120), color: .white, fontSize: 16, weight: .semibold)
        drawText(context: context, text: "avg. S. Speed", origin: CGPoint(x: startX + 10, y: startY + 160), color: .white, fontSize: 14)
        drawText(context: context, text: String(format: "%.1f km/h    %.1f km/h", stats.player1AverageShotSpeed, stats.player2AverageShotSpeed), origin: CGPoint(x: startX + 130, y: startY + 160), color: .white, fontSize: 16, weight: .semibold)
        drawText(context: context, text: "avg. P. Speed", origin: CGPoint(x: startX + 10, y: startY + 200), color: .white, fontSize: 14)
        drawText(context: context, text: String(format: "%.1f km/h    %.1f km/h", stats.player1AveragePlayerSpeed, stats.player2AveragePlayerSpeed), origin: CGPoint(x: startX + 130, y: startY + 200), color: .white, fontSize: 16, weight: .semibold)
        drawText(context: context, text: "Distance", origin: CGPoint(x: startX + 10, y: startY + 240), color: .white, fontSize: 14)
        drawText(context: context, text: String(format: "%.1f m      %.1f m", stats.player1TotalDistanceRun, stats.player2TotalDistanceRun), origin: CGPoint(x: startX + 130, y: startY + 240), color: .white, fontSize: 16, weight: .semibold)
        drawText(context: context, text: "Calories", origin: CGPoint(x: startX + 10, y: startY + 280), color: .white, fontSize: 14)
        drawText(context: context, text: String(format: "%.1f kcal   %.1f kcal", stats.player1TotalCaloriesBurned, stats.player2TotalCaloriesBurned), origin: CGPoint(x: startX + 130, y: startY + 280), color: .white, fontSize: 16, weight: .semibold)
    }

    private func drawFrameNumber(context: CGContext, frameNumber: Int) {
        drawText(context: context, text: "Frame: \(frameNumber)", origin: CGPoint(x: 10, y: 30), color: .green, fontSize: 24, weight: .bold)
    }

    private func drawText(
        context: CGContext,
        text: String,
        origin: CGPoint,
        color: UIColor,
        fontSize: CGFloat,
        weight: UIFont.Weight = .regular
    ) {
        UIGraphicsPushContext(context)
        let attributes: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: fontSize, weight: weight),
            .foregroundColor: color,
        ]
        NSString(string: text).draw(at: origin, withAttributes: attributes)
        UIGraphicsPopContext()
    }
}
