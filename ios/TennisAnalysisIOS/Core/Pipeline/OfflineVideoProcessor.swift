import AVFoundation
import Foundation

final class OfflineVideoProcessor {
    private let assetIO = VideoAssetIO()
    private let renderer = FrameRenderer()
    private let playerSelection = PlayerSelection()
    private let ballInterpolation = BallInterpolation()
    private let ballShotDetector = BallShotDetector()
    private let statsAggregator = StatsAggregator()

    func processVideo(
        inputURL: URL,
        progressHandler: @escaping @Sendable (Double, String) -> Void
    ) async throws -> URL {
        let asset = assetIO.makeAsset(for: inputURL)
        let frameRate = await assetIO.nominalFrameRate(for: asset)
        let frameSize = try await assetIO.frameSize(for: asset)
        let duration = try await asset.load(.duration)
        let estimatedFrameCount = max(1, Int(duration.seconds * Double(max(frameRate, 1))))

        progressHandler(0.05, "Loaded video metadata at \(Int(frameRate)) fps.")
        progressHandler(0.10, "Preparing offline analysis for frame size \(Int(frameSize.width))x\(Int(frameSize.height)).")

        let playerDetector = try PlayerCoreMLDetector()
        let ballDetector = try BallCoreMLDetector()
        let courtDetector = try CourtCoreMLDetector()

        let analysisArtifacts = try await analyzeVideo(
            asset: asset,
            frameRate: Double(frameRate),
            frameSize: frameSize,
            estimatedFrameCount: estimatedFrameCount,
            playerDetector: playerDetector,
            ballDetector: ballDetector,
            courtDetector: courtDetector,
            progressHandler: progressHandler
        )

        progressHandler(0.72, "Analysis complete. Rendering overlays and exporting video...")

        let outputURL = assetIO.makeOutputURL(for: inputURL)
        if FileManager.default.fileExists(atPath: outputURL.path) {
            try? FileManager.default.removeItem(at: outputURL)
        }

        try await exportVideo(
            asset: asset,
            outputURL: outputURL,
            frameRate: frameRate,
            frameSize: frameSize,
            analysisArtifacts: analysisArtifacts,
            estimatedFrameCount: estimatedFrameCount,
            progressHandler: progressHandler
        )

        progressHandler(1.0, "Finished exporting \(outputURL.lastPathComponent).")
        return outputURL
    }

    private func analyzeVideo(
        asset: AVAsset,
        frameRate: Double,
        frameSize: CGSize,
        estimatedFrameCount: Int,
        playerDetector: PlayerCoreMLDetector,
        ballDetector: BallCoreMLDetector,
        courtDetector: CourtCoreMLDetector,
        progressHandler: @escaping @Sendable (Double, String) -> Void
    ) async throws -> AnalysisArtifacts {
        let (reader, output, _) = try await assetIO.makeFrameReader(for: asset)
        var playerTracker = SortTracker()
        var ballTrackFilter = BallTrackFilter()
        var frameDetections: [FrameDetections] = []
        var playerBoxesPerFrame: [[Int: BoundingBox]] = []
        var ballBoxesPerFrame: [BoundingBox?] = []
        var courtKeypoints: [CGPoint] = []

        guard reader.startReading() else {
            throw reader.error ?? AnalysisErrors.unsupportedVideo
        }

        var frameIndex = 0
        while let sampleBuffer = output.copyNextSampleBuffer() {
            let timestampNs = sampleBuffer.timestampNs
            if courtKeypoints.isEmpty {
                courtKeypoints = try await courtDetector.detectCourtKeypoints(sampleBuffer: sampleBuffer)
            }

            let playerDetectionsRaw = try await playerDetector.detectDetections(sampleBuffer: sampleBuffer)
            let trackedPlayers = playerTracker.update(detections: playerDetectionsRaw, timestampNs: timestampNs)
            let playerBoxes = Dictionary(uniqueKeysWithValues: trackedPlayers.map { ($0.trackId, $0.bbox) })

            let ballDetectionsRaw = try await ballDetector.detectDetections(sampleBuffer: sampleBuffer)
            let trackedBall = ballTrackFilter.update(detections: ballDetectionsRaw, timestampNs: timestampNs)

            frameDetections.append(
                FrameDetections(
                    players: playerBoxes,
                    ball: trackedBall?.bbox
                )
            )
            playerBoxesPerFrame.append(playerBoxes)
            ballBoxesPerFrame.append(trackedBall?.bbox)

            frameIndex += 1
            if frameIndex % 10 == 0 {
                let progress = 0.10 + (0.55 * min(Double(frameIndex) / Double(estimatedFrameCount), 1.0))
                progressHandler(progress, "Analyzing frame \(frameIndex)/\(estimatedFrameCount)...")
            }
        }

        if reader.status == .failed {
            throw reader.error ?? AnalysisErrors.unsupportedVideo
        }
        guard !courtKeypoints.isEmpty else {
            throw AnalysisErrors.modelsNotReady
        }

        let selectedPlayers = playerSelection.chooseAndFilterPlayers(
            courtKeypoints: courtKeypoints,
            detectionsPerFrame: playerBoxesPerFrame
        )
        let interpolatedBallBoxes = ballInterpolation.interpolate(ballBoxes: ballBoxesPerFrame)
        let miniCourtMapper = MiniCourtMapper(frameSize: frameSize)
        let miniCourtDetections = miniCourtMapper.convertBoundingBoxesToMiniCourtCoordinates(
            playerBoxes: selectedPlayers,
            ballBoxes: interpolatedBallBoxes,
            originalCourtKeypoints: courtKeypoints
        )
        let ballShotFrames = ballShotDetector.shotFrames(ballBoxes: interpolatedBallBoxes)
        let statsRows = ballShotFrames.count >= 2
            ? statsAggregator.buildStatsRows(
                frameCount: playerBoxesPerFrame.count,
                frameRate: frameRate,
                ballShotFrames: ballShotFrames,
                playerMiniCourtDetections: miniCourtDetections.playerPositions,
                ballMiniCourtDetections: miniCourtDetections.ballPositions,
                miniCourtWidth: miniCourtMapper.courtDrawingWidth
            )
            : statsAggregator.emptyRows(frameCount: playerBoxesPerFrame.count)

        return AnalysisArtifacts(
            playerDetections: zip(selectedPlayers, interpolatedBallBoxes).map { players, ball in
                FrameDetections(players: players, ball: ball)
            },
            ballShotFrames: ballShotFrames,
            courtKeypoints: courtKeypoints,
            playerMiniCourtDetections: miniCourtDetections.playerPositions,
            ballMiniCourtDetections: miniCourtDetections.ballPositions,
            statsRows: statsRows
        )
    }

    private func exportVideo(
        asset: AVAsset,
        outputURL: URL,
        frameRate: Float,
        frameSize: CGSize,
        analysisArtifacts: AnalysisArtifacts,
        estimatedFrameCount: Int,
        progressHandler: @escaping @Sendable (Double, String) -> Void
    ) async throws {
        let (reader, output, _) = try await assetIO.makeFrameReader(for: asset)
        let (writer, writerInput, adaptor) = try assetIO.makeWriter(
            outputURL: outputURL,
            frameSize: frameSize,
            frameRate: frameRate
        )

        guard writer.startWriting() else {
            throw writer.error ?? AnalysisErrors.exportFailed
        }
        writer.startSession(atSourceTime: .zero)
        guard reader.startReading() else {
            throw reader.error ?? AnalysisErrors.unsupportedVideo
        }

        var frameIndex = 0
        while let sampleBuffer = output.copyNextSampleBuffer() {
            guard let imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { continue }
            while !writerInput.isReadyForMoreMediaData {
                try await Task.sleep(nanoseconds: 2_000_000)
            }

            let renderBuffer = try PixelBufferTools.copyPixelBuffer(
                from: imageBuffer,
                using: adaptor.pixelBufferPool
            )
            let overlay = makeOverlayFrame(
                frameIndex: frameIndex,
                timestampNs: sampleBuffer.timestampNs,
                frameSize: frameSize,
                analysisArtifacts: analysisArtifacts
            )
            let playerPositions = frameIndex < analysisArtifacts.playerMiniCourtDetections.count
                ? analysisArtifacts.playerMiniCourtDetections[frameIndex]
                : [:]
            let ballPosition = frameIndex < analysisArtifacts.ballMiniCourtDetections.count
                ? analysisArtifacts.ballMiniCourtDetections[frameIndex][1]
                : nil
            renderer.render(
                pixelBuffer: renderBuffer,
                overlay: overlay,
                playerMiniCourtPositions: playerPositions,
                ballMiniCourtPosition: ballPosition
            )

            let presentationTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            guard adaptor.append(renderBuffer, withPresentationTime: presentationTime) else {
                throw writer.error ?? AnalysisErrors.exportFailed
            }

            frameIndex += 1
            if frameIndex % 10 == 0 {
                let progress = 0.72 + (0.27 * min(Double(frameIndex) / Double(estimatedFrameCount), 1.0))
                progressHandler(progress, "Rendering frame \(frameIndex)/\(estimatedFrameCount)...")
            }
        }

        writerInput.markAsFinished()
        if reader.status == .failed {
            throw reader.error ?? AnalysisErrors.unsupportedVideo
        }
        try await finishWriting(writer: writer)
    }

    private func makeOverlayFrame(
        frameIndex: Int,
        timestampNs: UInt64,
        frameSize: CGSize,
        analysisArtifacts: AnalysisArtifacts
    ) -> OverlayFrame {
        let frameDetections = frameIndex < analysisArtifacts.playerDetections.count
            ? analysisArtifacts.playerDetections[frameIndex]
            : FrameDetections()
        let players = frameDetections.players
            .sorted { $0.key < $1.key }
            .map { trackId, bbox in
                TrackedObject(
                    trackId: trackId,
                    classId: 0,
                    score: 1.0,
                    bbox: bbox,
                    center: bbox.center,
                    velocity: nil,
                    timestampNs: timestampNs
                )
            }
        let ball = frameDetections.ball.map { bbox in
            TrackedObject(
                trackId: 1,
                classId: 0,
                score: 1.0,
                bbox: bbox,
                center: bbox.center,
                velocity: nil,
                timestampNs: timestampNs
            )
        }
        let stats = frameIndex < analysisArtifacts.statsRows.count ? analysisArtifacts.statsRows[frameIndex] : nil
        return OverlayFrame(
            frameNumber: frameIndex,
            timestampNs: timestampNs,
            sourceSize: frameSize,
            players: players,
            ball: ball,
            court: CourtKeypointSet(points: analysisArtifacts.courtKeypoints, confidence: 1.0, timestampNs: timestampNs),
            stats: stats
        )
    }

    private func finishWriting(writer: AVAssetWriter) async throws {
        try await withCheckedThrowingContinuation { continuation in
            writer.finishWriting {
                if let error = writer.error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: ())
                }
            }
        }
    }
}
