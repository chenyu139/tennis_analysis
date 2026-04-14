import CoreGraphics
import CoreMedia
import Foundation

protocol PlayerDetecting {
    func detectPlayers(sampleBuffer: CMSampleBuffer) async throws -> [Int: BoundingBox]
}

protocol BallDetecting {
    func detectBall(sampleBuffer: CMSampleBuffer) async throws -> BoundingBox?
}

protocol CourtKeypointDetecting {
    func detectCourtKeypoints(sampleBuffer: CMSampleBuffer) async throws -> [CGPoint]
}

struct UnconfiguredPlayerDetector: PlayerDetecting {
    func detectPlayers(sampleBuffer: CMSampleBuffer) async throws -> [Int: BoundingBox] {
        _ = sampleBuffer
        throw AnalysisErrors.modelsNotReady
    }
}

struct UnconfiguredBallDetector: BallDetecting {
    func detectBall(sampleBuffer: CMSampleBuffer) async throws -> BoundingBox? {
        _ = sampleBuffer
        throw AnalysisErrors.modelsNotReady
    }
}

struct UnconfiguredCourtKeypointDetector: CourtKeypointDetecting {
    func detectCourtKeypoints(sampleBuffer: CMSampleBuffer) async throws -> [CGPoint] {
        _ = sampleBuffer
        throw AnalysisErrors.modelsNotReady
    }
}
