package com.chenyu.tennisanalysis.pipeline

import android.graphics.PointF
import android.graphics.RectF
import java.util.concurrent.CopyOnWriteArrayList

enum class DelegatePreference {
    AUTO,
    GPU,
    CPU
}

data class RuntimeConfig(
    val preferredDelegate: DelegatePreference = DelegatePreference.AUTO,
    val numThreads: Int = 4
)

data class DetectorConfig(
    val assetFileName: String,
    val inputWidth: Int,
    val inputHeight: Int,
    val confidenceThreshold: Float,
    val iouThreshold: Float = 0.45f,
    val trackedClassIds: Set<Int> = emptySet(),
    val metadataAssetName: String? = null,
    val runtimeConfig: RuntimeConfig = RuntimeConfig()
)

data class ModelMetadata(
    val inputShape: List<Int> = emptyList(),
    val outputShape: List<Int> = emptyList(),
    val inputLayout: String? = null,
    val inputRange: List<Float> = emptyList(),
    val normalizeMean: List<Float> = emptyList(),
    val normalizeStd: List<Float> = emptyList(),
    val trackedClassIds: Set<Int> = emptySet()
)

data class InputSpec(
    val width: Int,
    val height: Int,
    val layout: String
)

data class Detection(
    val classId: Int,
    val score: Float,
    val bbox: RectF,
    val timestampNs: Long
)

data class TrackedObject(
    val trackId: Int,
    val classId: Int,
    val score: Float,
    val bbox: RectF,
    val center: PointF,
    val velocity: PointF?,
    val timestampNs: Long
)

data class CourtKeypointSet(
    val points: List<PointF>,
    val confidence: Float,
    val timestampNs: Long
)

enum class ShotEventType {
    HIT_CANDIDATE,
    HIT_CONFIRMED,
    LOST_BALL
}

data class ShotEvent(
    val type: ShotEventType,
    val timestampNs: Long,
    val confidence: Float
)

data class PlayerStats(
    val player1ShotCount: Int = 0,
    val player2ShotCount: Int = 0,
    val player1LastShotSpeedKmh: Float = 0f,
    val player2LastShotSpeedKmh: Float = 0f,
    val player1DistanceM: Float = 0f,
    val player2DistanceM: Float = 0f
)

data class PerformanceStats(
    val totalMs: Float = 0f,
    val convertMs: Float = 0f,
    val playerMs: Float = 0f,
    val courtMs: Float = 0f,
    val ballMs: Float = 0f
)

data class OverlayFrame(
    val timestampNs: Long,
    val sourceWidth: Int,
    val sourceHeight: Int,
    val players: List<TrackedObject>,
    val ball: TrackedObject?,
    val court: CourtKeypointSet?,
    val events: List<ShotEvent>,
    val stats: PlayerStats,
    val performance: PerformanceStats = PerformanceStats()
)

data class AnalyzerSettings(
    val playerFrameStride: Int = 2,
    val ballFrameStride: Int = 2,
    val courtFrameStride: Int = 45,
    val enableBallDetection: Boolean = true,
    val enableCourtDetection: Boolean = true,
    val showPerformanceStats: Boolean = false
)

data class ShotEventInput(
    val players: List<TrackedObject>,
    val ball: TrackedObject?,
    val court: CourtKeypointSet?
)

data class StatsInput(
    val players: List<TrackedObject>,
    val ball: TrackedObject?,
    val events: List<ShotEvent>,
    val court: CourtKeypointSet?
)

class OverlayStateStore {
    private val listeners = CopyOnWriteArrayList<(OverlayFrame) -> Unit>()

    fun publish(frame: OverlayFrame) {
        listeners.forEach { it.invoke(frame) }
    }

    fun addListener(listener: (OverlayFrame) -> Unit) {
        listeners.add(listener)
    }

    fun clear() {
        listeners.clear()
    }
}
