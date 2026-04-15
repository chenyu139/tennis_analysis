import CoreGraphics
import Foundation

struct FrameDetections {
    var players: [Int: BoundingBox] = [:]
    var ball: BoundingBox?
}

struct Detection {
    let classId: Int
    let score: Float
    let bbox: BoundingBox
    let timestampNs: UInt64
}

struct TrackedObject {
    let trackId: Int
    let classId: Int
    let score: Float
    let bbox: BoundingBox
    let center: CGPoint
    let velocity: CGPoint?
    let timestampNs: UInt64
}

struct CourtKeypointSet {
    let points: [CGPoint]
    let confidence: Float
    let timestampNs: UInt64
}

enum ShotEventType {
    case hitCandidate
    case hitConfirmed
    case lostBall
}

struct ShotEvent {
    let type: ShotEventType
    let timestampNs: UInt64
    let confidence: Float
}

struct OverlayFrame {
    let frameNumber: Int
    let timestampNs: UInt64
    let sourceSize: CGSize
    let players: [TrackedObject]
    let ball: TrackedObject?
    let court: CourtKeypointSet?
    let stats: PlayerStatsRow?
}

struct PlayerStatsRow: Identifiable {
    let id = UUID()
    var frameNumber: Int
    var player1NumberOfShots: Int = 0
    var player1TotalShotSpeed: Double = 0
    var player1LastShotSpeed: Double = 0
    var player1TotalPlayerSpeed: Double = 0
    var player1LastPlayerSpeed: Double = 0
    var player1TotalDistanceRun: Double = 0
    var player1LastDistanceRun: Double = 0
    var player1TotalCaloriesBurned: Double = 0
    var player1LastCaloriesBurned: Double = 0

    var player2NumberOfShots: Int = 0
    var player2TotalShotSpeed: Double = 0
    var player2LastShotSpeed: Double = 0
    var player2TotalPlayerSpeed: Double = 0
    var player2LastPlayerSpeed: Double = 0
    var player2TotalDistanceRun: Double = 0
    var player2LastDistanceRun: Double = 0
    var player2TotalCaloriesBurned: Double = 0
    var player2LastCaloriesBurned: Double = 0

    var player1AverageShotSpeed: Double = 0
    var player2AverageShotSpeed: Double = 0
    var player1AveragePlayerSpeed: Double = 0
    var player2AveragePlayerSpeed: Double = 0
}

struct AnalysisArtifacts {
    var playerDetections: [FrameDetections] = []
    var ballShotFrames: [Int] = []
    var courtKeypoints: [CGPoint] = []
    var playerMiniCourtDetections: [[Int: CGPoint]] = []
    var ballMiniCourtDetections: [[Int: CGPoint]] = []
    var statsRows: [PlayerStatsRow] = []
}

enum AnalysisErrors: LocalizedError {
    case unsupportedVideo
    case exportFailed
    case modelsNotReady

    var errorDescription: String? {
        switch self {
        case .unsupportedVideo:
            return "无法读取该视频文件。"
        case .exportFailed:
            return "视频导出失败。"
        case .modelsNotReady:
            return "Core ML 模型尚未正确配置。"
        }
    }
}
