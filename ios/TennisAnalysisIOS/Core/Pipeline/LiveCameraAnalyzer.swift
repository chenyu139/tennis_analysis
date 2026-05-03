@preconcurrency import AVFoundation
import CoreGraphics
import Foundation

struct LiveOverlaySnapshot: @unchecked Sendable {
    let frameNumber: Int
    let timestampNs: UInt64
    let sourceSize: CGSize
    let players: [TrackedObject]
    let ball: TrackedObject?
    let courtPoints: [CGPoint]
    let inferenceDurationMs: Double
    let analysisFPS: Double
}

private actor LiveFramePipeline {
    private let playerDetector: PlayerCoreMLDetector
    private let ballDetector: BallCoreMLDetector
    private let courtDetector: CourtCoreMLDetector

    private var playerTracker = SortTracker()
    private var ballTrackFilter = BallTrackFilter()
    private var courtKeypoints: [CGPoint] = []
    private var frameIndex = 0
    private var lastCourtRefreshFrame = -30
    private var lastAnalysisTimestampNs: UInt64?
    private var consecutiveErrors = 0
    private let maxConsecutiveErrors = 10

    init() throws {
        playerDetector = try PlayerCoreMLDetector()
        ballDetector = try BallCoreMLDetector()
        courtDetector = try CourtCoreMLDetector()
    }

    func process(sampleBuffer: CMSampleBuffer) async throws -> LiveOverlaySnapshot {
        let startedAt = CFAbsoluteTimeGetCurrent()
        let currentFrameIndex = frameIndex
        frameIndex += 1

        let timestampNs = sampleBuffer.timestampNs
        let sourcePixelBuffer = try PixelBufferTools.pixelBuffer(from: sampleBuffer)
        let frameSize = CGSize(
            width: CVPixelBufferGetWidth(sourcePixelBuffer),
            height: CVPixelBufferGetHeight(sourcePixelBuffer)
        )

        if courtKeypoints.isEmpty || (currentFrameIndex - lastCourtRefreshFrame) >= 30 {
            let refreshedKeypoints = try await courtDetector.detectCourtKeypoints(sampleBuffer: sampleBuffer)
            if !refreshedKeypoints.isEmpty {
                courtKeypoints = refreshedKeypoints
                lastCourtRefreshFrame = currentFrameIndex
            }
        }

        // Run player and ball detection sequentially to avoid CIContext
        // concurrency issues (CIContext.render is not thread-safe).
        let playerDetections = try await playerDetector.detectDetections(sampleBuffer: sampleBuffer)
        let ballDetections = try await ballDetector.detectDetections(sampleBuffer: sampleBuffer)

        let trackedPlayers = playerTracker.update(detections: playerDetections, timestampNs: timestampNs)
        let trackedBall = ballTrackFilter.update(detections: ballDetections, timestampNs: timestampNs)

        consecutiveErrors = 0

        let analysisFPS: Double
        if let lastAnalysisTimestampNs, timestampNs > lastAnalysisTimestampNs {
            analysisFPS = 1_000_000_000.0 / Double(timestampNs - lastAnalysisTimestampNs)
        } else {
            analysisFPS = 0
        }
        lastAnalysisTimestampNs = timestampNs

        return LiveOverlaySnapshot(
            frameNumber: currentFrameIndex,
            timestampNs: timestampNs,
            sourceSize: frameSize,
            players: trackedPlayers,
            ball: trackedBall,
            courtPoints: courtKeypoints,
            inferenceDurationMs: (CFAbsoluteTimeGetCurrent() - startedAt) * 1000.0,
            analysisFPS: analysisFPS
        )
    }

    func recordError() -> Bool {
        consecutiveErrors += 1
        return consecutiveErrors < maxConsecutiveErrors
    }

    func resetErrors() {
        consecutiveErrors = 0
    }
}

final class LiveCameraAnalyzer: NSObject, ObservableObject {
    @Published private(set) var latestOverlay: LiveOverlaySnapshot?
    @Published private(set) var isRunning = false
    @Published private(set) var statusText = "等待启动摄像头。"
    @Published private(set) var streamInfoText = "尚未读取到摄像头画面。"
    @Published private(set) var recentEvents: [String] = ["等待启动摄像头"]

    let captureSession = AVCaptureSession()

    private let videoOutput = AVCaptureVideoDataOutput()
    private let captureQueue = DispatchQueue(label: "com.chenyu.tennisanalysis.live-camera.capture")

    private var framePipeline: LiveFramePipeline?
    private var isSessionConfigured = false
    private var currentVideoOrientation: AVCaptureVideoOrientation = .portrait
    private var lastSubmittedTimestampNs: UInt64 = 0
    private let targetAnalysisFPS: Double = 15
    private var pendingFrameCount = 0
    private let maxPendingFrames = 2

    func start() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureAndStartSession()
        case .notDetermined:
            publishStatus("正在请求摄像头权限...")
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                guard let self else { return }
                if granted {
                    self.appendEvent("已获取摄像头权限")
                    self.configureAndStartSession()
                } else {
                    self.publish(error: AnalysisErrors.cameraPermissionDenied)
                }
            }
        case .denied, .restricted:
            publish(error: AnalysisErrors.cameraPermissionDenied)
        @unknown default:
            publish(error: AnalysisErrors.cameraUnavailable)
        }
    }

    func stop() {
        captureQueue.async { [weak self] in
            guard let self else { return }
            if self.captureSession.isRunning {
                self.captureSession.stopRunning()
            }
            self.framePipeline = nil
            self.pendingFrameCount = 0
            self.lastSubmittedTimestampNs = 0
            DispatchQueue.main.async {
                self.isRunning = false
                self.statusText = "实时分析已停止。"
                self.streamInfoText = "摄像头预览已停止。"
                self.appendEvent("已停止实时分析")
            }
        }
    }

    func updateVideoOrientation(_ orientation: AVCaptureVideoOrientation) {
        captureQueue.async { [weak self] in
            guard let self else { return }
            self.currentVideoOrientation = orientation
            if let connection = self.videoOutput.connection(with: .video),
               connection.isVideoOrientationSupported {
                connection.videoOrientation = orientation
            }
        }
    }

    private func configureAndStartSession() {
        captureQueue.async { [weak self] in
            guard let self else { return }
            do {
                if !self.isSessionConfigured {
                    try self.configureSession()
                }
                self.framePipeline = try LiveFramePipeline()
                self.pendingFrameCount = 0
                guard !self.captureSession.isRunning else {
                    DispatchQueue.main.async {
                        self.isRunning = true
                        self.statusText = "摄像头已在运行。"
                    }
                    return
                }
                self.captureSession.startRunning()
                DispatchQueue.main.async {
                    self.isRunning = true
                    self.statusText = "摄像头已启动，实时检测已开启。"
                    self.streamInfoText = "预览 60 fps 优先，分析按负载自适应。"
                    self.appendEvent("摄像头已启动")
                }
            } catch {
                self.publish(error: error)
            }
        }
    }

    private func configureSession() throws {
        captureSession.beginConfiguration()
        defer { captureSession.commitConfiguration() }

        if captureSession.canSetSessionPreset(.hd1280x720) {
            captureSession.sessionPreset = .hd1280x720
        } else {
            captureSession.sessionPreset = .high
        }

        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            throw AnalysisErrors.cameraUnavailable
        }

        if let existingInput = captureSession.inputs.first as? AVCaptureDeviceInput {
            captureSession.removeInput(existingInput)
        }
        if captureSession.outputs.contains(videoOutput) {
            captureSession.removeOutput(videoOutput)
        }

        let input = try AVCaptureDeviceInput(device: device)
        guard captureSession.canAddInput(input) else {
            throw AnalysisErrors.cameraUnavailable
        }
        captureSession.addInput(input)

        videoOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        ]
        videoOutput.alwaysDiscardsLateVideoFrames = true
        videoOutput.setSampleBufferDelegate(self, queue: captureQueue)
        guard captureSession.canAddOutput(videoOutput) else {
            throw AnalysisErrors.cameraUnavailable
        }
        captureSession.addOutput(videoOutput)

        if let connection = videoOutput.connection(with: .video) {
            if connection.isVideoOrientationSupported {
                connection.videoOrientation = currentVideoOrientation
            }
            if connection.isVideoMirroringSupported {
                connection.isVideoMirrored = false
            }
        }

        try configureHighFrameRate(device: device)
        isSessionConfigured = true
    }

    private func configureHighFrameRate(device: AVCaptureDevice) throws {
        try device.lockForConfiguration()
        defer { device.unlockForConfiguration() }

        let preferredFormat = device.formats
            .filter { format in
                let dimensions = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
                let maxFPS = format.videoSupportedFrameRateRanges.map(\.maxFrameRate).max() ?? 0
                return maxFPS >= 60 && dimensions.width <= 1280 && dimensions.height <= 720
            }
            .sorted { lhs, rhs in
                let lhsDimensions = CMVideoFormatDescriptionGetDimensions(lhs.formatDescription)
                let rhsDimensions = CMVideoFormatDescriptionGetDimensions(rhs.formatDescription)
                let lhsPixels = Int(lhsDimensions.width) * Int(lhsDimensions.height)
                let rhsPixels = Int(rhsDimensions.width) * Int(rhsDimensions.height)
                return lhsPixels > rhsPixels
            }
            .first

        if let preferredFormat {
            device.activeFormat = preferredFormat
            device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 60)
            device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 60)
            return
        }

        if device.activeFormat.videoSupportedFrameRateRanges.contains(where: { $0.maxFrameRate >= 30 }) {
            device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 30)
            device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 30)
        }
    }

    private func publishProcessedFrame(_ frame: LiveOverlaySnapshot) {
        DispatchQueue.main.async {
            self.latestOverlay = frame
            self.isRunning = true
            self.statusText = frame.courtPoints.isEmpty
                ? "实时检测中，正在稳定球场关键点..."
                : "实时检测中，已识别 \(frame.players.count) 名球员。"
            self.streamInfoText = [
                "源帧 \(Int(frame.sourceSize.width))x\(Int(frame.sourceSize.height))",
                String(format: "推理 %.0f ms", frame.inferenceDurationMs),
                frame.analysisFPS > 0 ? String(format: "分析 %.1f fps", frame.analysisFPS) : "分析启动中",
                frame.ball == nil ? "未检测到网球" : "已检测到网球",
            ].joined(separator: " · ")
        }
    }

    private func publishStatus(_ message: String) {
        DispatchQueue.main.async {
            self.statusText = message
        }
    }

    private func publish(error: Error) {
        let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        DispatchQueue.main.async {
            self.isRunning = false
            self.statusText = message
            self.streamInfoText = "实时分析不可用。"
            self.appendEvent(message)
        }
    }

    private func appendEvent(_ message: String) {
        if Thread.isMainThread {
            recentEvents.insert(message, at: 0)
            if recentEvents.count > 8 {
                recentEvents = Array(recentEvents.prefix(8))
            }
        } else {
            DispatchQueue.main.async {
                self.appendEvent(message)
            }
        }
    }
}

extension LiveCameraAnalyzer: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        _ = output
        _ = connection

        let timestampNs = sampleBuffer.timestampNs
        let minimumIntervalNs = UInt64(1_000_000_000.0 / targetAnalysisFPS)
        guard timestampNs >= lastSubmittedTimestampNs + minimumIntervalNs else { return }
        guard pendingFrameCount < maxPendingFrames, let framePipeline else { return }

        pendingFrameCount += 1
        lastSubmittedTimestampNs = timestampNs

        var sampleBufferCopy: CMSampleBuffer?
        let copyStatus = CMSampleBufferCreateCopy(
            allocator: kCFAllocatorDefault,
            sampleBuffer: sampleBuffer,
            sampleBufferOut: &sampleBufferCopy
        )
        guard copyStatus == noErr, let sampleBufferCopy else {
            pendingFrameCount -= 1
            return
        }

        Task(priority: .userInitiated) { [weak self, framePipeline] in
            do {
                let processedFrame = try await framePipeline.process(sampleBuffer: sampleBufferCopy)
                self?.publishProcessedFrame(processedFrame)
            } catch {
                let shouldContinue = await framePipeline.recordError()
                if !shouldContinue {
                    self?.captureQueue.async {
                        self?.framePipeline = nil
                        if self?.captureSession.isRunning == true {
                            self?.captureSession.stopRunning()
                        }
                    }
                    self?.publish(error: error)
                }
            }
            self?.captureQueue.async {
                self?.pendingFrameCount -= 1
            }
        }
    }
}
